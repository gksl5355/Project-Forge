"""Forge CLI — Typer 앱, 모든 명령 등록."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from forge.config import load_config
from forge.core.qvalue import initial_q, time_decay
from forge.engines.detect import run_detect
from forge.engines.resume import run_resume
from forge.engines.writeback import run_writeback
from forge.storage.db import get_connection, init_db
from forge.storage.models import Decision, Failure, Knowledge, Rule
from forge.storage.queries import (
    get_failure_by_pattern,
    insert_decision,
    insert_failure,
    insert_knowledge,
    insert_rule,
    list_decisions,
    list_failures,
    list_knowledge,
    list_rules,
    update_decision,
    update_failure,
    update_rule,
)

app = typer.Typer(help="Project Forge — 코딩 에이전트를 위한 경험 학습 CLI")
record_app = typer.Typer(help="경험 데이터 기록")
app.add_typer(record_app, name="record")


def _get_db():
    config = load_config()
    return get_connection(), config


# ---------------------------------------------------------------------------
# forge init
# ---------------------------------------------------------------------------

@app.command("init")
def cmd_init():
    """DB 초기화 (idempotent)."""
    init_db()
    typer.echo("Forge DB initialized.")


# ---------------------------------------------------------------------------
# forge record failure
# ---------------------------------------------------------------------------

@record_app.command("failure")
def cmd_record_failure(
    pattern: str = typer.Option(..., "--pattern", "-p", help="패턴 이름"),
    hint: str = typer.Option(..., "--hint", "-h", help="회피 힌트"),
    quality: str = typer.Option("preventable", "--quality", "-q",
                                 help="near_miss | preventable | environmental"),
    workspace: str = typer.Option("default", "--workspace", "-w", help="워크스페이스 ID"),
    tag: Optional[list[str]] = typer.Option(None, "--tag", "-t", help="태그 (반복 가능)"),
    observed: Optional[str] = typer.Option(None, "--observed", help="관찰된 에러 메시지"),
    cause: Optional[str] = typer.Option(None, "--cause", help="예상 원인"),
):
    """실패 패턴 기록."""
    valid_qualities = {"near_miss", "preventable", "environmental"}
    if quality not in valid_qualities:
        typer.echo(f"Error: quality must be one of {valid_qualities}", err=True)
        raise typer.Exit(1)

    db = get_connection()
    config = load_config()
    q0 = initial_q(quality, config)
    failure = Failure(
        workspace_id=workspace,
        pattern=pattern,
        avoid_hint=hint,
        hint_quality=quality,
        q=q0,
        tags=tag or [],
        observed_error=observed,
        likely_cause=cause,
        source="manual",
    )
    fid = insert_failure(db, failure)
    typer.echo(f"Failure recorded (id={fid}): {pattern}")


# ---------------------------------------------------------------------------
# forge record decision
# ---------------------------------------------------------------------------

@record_app.command("decision")
def cmd_record_decision(
    statement: str = typer.Option(..., "--statement", "-s", help="결정 내용"),
    workspace: str = typer.Option("default", "--workspace", "-w", help="워크스페이스 ID"),
    rationale: Optional[str] = typer.Option(None, "--rationale", "-r", help="이유"),
    tag: Optional[list[str]] = typer.Option(None, "--tag", "-t", help="태그 (반복 가능)"),
    alternative: Optional[list[str]] = typer.Option(None, "--alternative", help="대안 (반복 가능)"),
):
    """결정 기록."""
    db = get_connection()
    config = load_config()
    decision = Decision(
        workspace_id=workspace,
        statement=statement,
        rationale=rationale,
        alternatives=alternative or [],
        tags=tag or [],
        q=config.initial_q_decision,
    )
    did = insert_decision(db, decision)
    typer.echo(f"Decision recorded (id={did}): {statement[:60]}")


# ---------------------------------------------------------------------------
# forge record rule
# ---------------------------------------------------------------------------

@record_app.command("rule")
def cmd_record_rule(
    text: str = typer.Option(..., "--text", help="룰 텍스트"),
    workspace: str = typer.Option("default", "--workspace", "-w", help="워크스페이스 ID"),
    scope: Optional[str] = typer.Option(None, "--scope", help="적용 범위"),
    mode: str = typer.Option("warn", "--mode", "-m", help="block | warn | log"),
):
    """룰 기록."""
    valid_modes = {"block", "warn", "log"}
    if mode not in valid_modes:
        typer.echo(f"Error: mode must be one of {valid_modes}", err=True)
        raise typer.Exit(1)

    db = get_connection()
    rule = Rule(
        workspace_id=workspace,
        rule_text=text,
        scope=scope,
        enforcement_mode=mode,
    )
    rid = insert_rule(db, rule)
    typer.echo(f"Rule recorded (id={rid}): {text[:60]}")


# ---------------------------------------------------------------------------
# forge record knowledge
# ---------------------------------------------------------------------------

@record_app.command("knowledge")
def cmd_record_knowledge(
    title: str = typer.Option(..., "--title", help="제목"),
    content: str = typer.Option(..., "--content", help="내용"),
    workspace: str = typer.Option("default", "--workspace", "-w", help="워크스페이스 ID"),
    tag: Optional[list[str]] = typer.Option(None, "--tag", "-t", help="태그 (반복 가능)"),
):
    """지식 기록."""
    db = get_connection()
    config = load_config()
    knowledge = Knowledge(
        workspace_id=workspace,
        title=title,
        content=content,
        source="seeded",
        q=config.initial_q_knowledge,
        tags=tag or [],
    )
    kid = insert_knowledge(db, knowledge)
    typer.echo(f"Knowledge recorded (id={kid}): {title}")


# ---------------------------------------------------------------------------
# forge list
# ---------------------------------------------------------------------------

@app.command("list")
def cmd_list(
    workspace: str = typer.Option("default", "--workspace", "-w", help="워크스페이스 ID"),
    type_: str = typer.Option("failure", "--type", "-t",
                               help="failure | decision | rule | knowledge"),
    sort: str = typer.Option("q", "--sort", "-s", help="정렬 기준 (q, times_seen, created_at)"),
):
    """경험 목록 조회."""
    db = get_connection()

    if type_ == "failure":
        items = list_failures(db, workspace, sort_by=sort)
        for f in items:
            typer.echo(f"[{f.id}] {f.pattern} | Q:{f.q:.2f} | {f.hint_quality} | seen:{f.times_seen}")
    elif type_ == "decision":
        items = list_decisions(db, workspace)
        for d in items:
            typer.echo(f"[{d.id}] {d.statement[:60]} | Q:{d.q:.2f} | {d.status}")
    elif type_ == "rule":
        items = list_rules(db, workspace)
        for r in items:
            typer.echo(f"[{r.id}] [{r.enforcement_mode}] {r.rule_text[:60]}")
    elif type_ == "knowledge":
        items = list_knowledge(db, workspace)
        for k in items:
            typer.echo(f"[{k.id}] {k.title} | Q:{k.q:.2f}")
    else:
        typer.echo(f"Error: unknown type '{type_}'", err=True)
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# forge search
# ---------------------------------------------------------------------------

@app.command("search")
def cmd_search(
    tag: list[str] = typer.Option(..., "--tag", "-t", help="태그 (반복 가능)"),
    workspace: str = typer.Option("default", "--workspace", "-w", help="워크스페이스 ID"),
):
    """태그로 실패 검색."""
    from forge.storage.queries import search_by_tags
    db = get_connection()
    items = search_by_tags(db, workspace, tag)
    if not items:
        typer.echo("No results found.")
        return
    for f in items:
        typer.echo(f"[{f.id}] {f.pattern} | Q:{f.q:.2f} | tags:{f.tags}")


# ---------------------------------------------------------------------------
# forge detail
# ---------------------------------------------------------------------------

@app.command("detail")
def cmd_detail(
    pattern: str = typer.Argument(..., help="패턴 이름"),
    workspace: str = typer.Option("default", "--workspace", "-w", help="워크스페이스 ID"),
):
    """패턴 상세 조회."""
    db = get_connection()
    failure = get_failure_by_pattern(db, workspace, pattern)
    if not failure:
        typer.echo(f"Pattern not found: {pattern}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Pattern:    {failure.pattern}")
    typer.echo(f"Quality:    {failure.hint_quality}")
    typer.echo(f"Q:          {failure.q:.4f}")
    typer.echo(f"Times seen: {failure.times_seen}")
    typer.echo(f"Helped:     {failure.times_helped}")
    typer.echo(f"Warned:     {failure.times_warned}")
    typer.echo(f"Source:     {failure.source}")
    typer.echo(f"Tags:       {failure.tags}")
    if failure.observed_error:
        typer.echo(f"Error:      {failure.observed_error}")
    if failure.likely_cause:
        typer.echo(f"Cause:      {failure.likely_cause}")
    typer.echo(f"Hint:       {failure.avoid_hint}")


# ---------------------------------------------------------------------------
# forge edit
# ---------------------------------------------------------------------------

@app.command("edit")
def cmd_edit(
    id_: int = typer.Argument(..., metavar="ID", help="편집할 항목 ID"),
    workspace: str = typer.Option("default", "--workspace", "-w", help="워크스페이스 ID"),
    hint: Optional[str] = typer.Option(None, "--hint", help="새 avoid_hint (failure용)"),
    rationale: Optional[str] = typer.Option(None, "--rationale", help="새 rationale (decision용)"),
):
    """기록 편집."""
    db = get_connection()

    # Failure 시도
    row = db.execute("SELECT * FROM failures WHERE id = ? AND workspace_id = ?",
                     (id_, workspace)).fetchone()
    if row:
        from forge.storage.queries import _row_to_failure  # type: ignore[attr-defined]
        # 직접 update
        if hint:
            db.execute("UPDATE failures SET avoid_hint = ?, updated_at = datetime('now') WHERE id = ?",
                       (hint, id_))
            db.commit()
            typer.echo(f"Failure {id_} hint updated.")
        return

    # Decision 시도
    row = db.execute("SELECT * FROM decisions WHERE id = ? AND workspace_id = ?",
                     (id_, workspace)).fetchone()
    if row:
        if rationale:
            db.execute("UPDATE decisions SET rationale = ?, updated_at = datetime('now') WHERE id = ?",
                       (rationale, id_))
            db.commit()
            typer.echo(f"Decision {id_} rationale updated.")
        return

    typer.echo(f"Item {id_} not found in workspace '{workspace}'", err=True)
    raise typer.Exit(1)


# ---------------------------------------------------------------------------
# forge promote
# ---------------------------------------------------------------------------

@app.command("promote")
def cmd_promote(
    id_: int = typer.Argument(..., metavar="ID", help="승격할 failure ID"),
    workspace: str = typer.Option("default", "--workspace", "-w", help="워크스페이스 ID"),
    to_knowledge: bool = typer.Option(False, "--to-knowledge", help="knowledge로 승격"),
):
    """Failure를 전역 또는 knowledge로 승격."""
    from forge.core.promote import promote_to_global, promote_to_knowledge
    db = get_connection()
    row = db.execute("SELECT * FROM failures WHERE id = ?", (id_,)).fetchone()
    if not row:
        typer.echo(f"Failure {id_} not found.", err=True)
        raise typer.Exit(1)

    from forge.storage.queries import _row_to_failure  # type: ignore[attr-defined]
    import json as _json

    # 직접 row → Failure 변환 (private 함수 직접 참조 대신 inline)
    failure = Failure(
        id=row["id"],
        workspace_id=row["workspace_id"],
        pattern=row["pattern"],
        avoid_hint=row["avoid_hint"],
        hint_quality=row["hint_quality"],
        q=row["q"],
        times_seen=row["times_seen"],
        times_helped=row["times_helped"],
        times_warned=row["times_warned"],
        tags=_json.loads(row["tags"] or "[]"),
        projects_seen=_json.loads(row["projects_seen"] or "[]"),
        source=row["source"],
        review_flag=bool(row["review_flag"]),
        observed_error=row["observed_error"],
        likely_cause=row["likely_cause"],
    )

    if to_knowledge:
        knowledge = promote_to_knowledge(failure)
        kid = insert_knowledge(db, knowledge)
        typer.echo(f"Promoted to knowledge (id={kid}): {failure.pattern}")
    else:
        existing = get_failure_by_pattern(db, "__global__", failure.pattern)
        if existing:
            typer.echo(f"Already in __global__: {failure.pattern}")
            return
        global_copy = promote_to_global(failure)
        fid = insert_failure(db, global_copy)
        typer.echo(f"Promoted to global (id={fid}): {failure.pattern}")


# ---------------------------------------------------------------------------
# forge stats
# ---------------------------------------------------------------------------

@app.command("stats")
def cmd_stats(
    workspace: str = typer.Option("default", "--workspace", "-w", help="워크스페이스 ID"),
):
    """워크스페이스 통계."""
    db = get_connection()
    failures = list_failures(db, workspace, include_global=False)
    decisions = list_decisions(db, workspace)
    rules = list_rules(db, workspace)
    knowledge = list_knowledge(db, workspace, include_global=False)

    typer.echo(f"Workspace: {workspace}")
    typer.echo(f"  Failures:  {len(failures)}")
    if failures:
        avg_q = sum(f.q for f in failures) / len(failures)
        top = sorted(failures, key=lambda f: f.q, reverse=True)[:3]
        typer.echo(f"  Avg Q:     {avg_q:.3f}")
        typer.echo(f"  Top patterns: {[f.pattern for f in top]}")
    typer.echo(f"  Decisions: {len(decisions)}")
    typer.echo(f"  Rules:     {len(rules)}")
    typer.echo(f"  Knowledge: {len(knowledge)}")


# ---------------------------------------------------------------------------
# forge decay
# ---------------------------------------------------------------------------

@app.command("decay")
def cmd_decay(
    workspace: str = typer.Option("default", "--workspace", "-w", help="워크스페이스 ID"),
    dry_run: bool = typer.Option(False, "--dry-run", help="실제로 적용하지 않고 미리보기"),
):
    """시간 감쇠 적용 (오래된 실패 패턴 Q 감소)."""
    from datetime import datetime, UTC
    db = get_connection()
    config = load_config()
    failures = list_failures(db, workspace, include_global=False)
    now = datetime.now(UTC)
    updated = 0

    for failure in failures:
        if failure.last_used is None:
            continue
        days = (now - failure.last_used).total_seconds() / 86400.0
        if days <= 1.0:
            continue
        new_q = time_decay(failure.q, days, config.decay_daily, config.q_min)
        if dry_run:
            typer.echo(f"[DRY] {failure.pattern}: Q {failure.q:.4f} → {new_q:.4f} ({days:.1f} days)")
        else:
            failure.q = new_q
            update_failure(db, failure)
        updated += 1

    action = "Would update" if dry_run else "Updated"
    typer.echo(f"{action} {updated} failure(s).")


# ---------------------------------------------------------------------------
# forge resume (hook용)
# ---------------------------------------------------------------------------

@app.command("resume")
def cmd_resume(
    workspace: str = typer.Option(..., "--workspace", "-w", help="워크스페이스 ID (cwd)"),
    session_id: str = typer.Option(..., "--session-id", help="세션 ID"),
):
    """세션 시작 시 context 주입 (SessionStart hook용)."""
    db = get_connection()
    config = load_config()
    context = run_resume(workspace, session_id, db, config)
    if context:
        typer.echo(context)


# ---------------------------------------------------------------------------
# forge writeback (hook용)
# ---------------------------------------------------------------------------

@app.command("writeback")
def cmd_writeback(
    workspace: str = typer.Option(..., "--workspace", "-w", help="워크스페이스 ID"),
    session_id: str = typer.Option(..., "--session-id", help="세션 ID"),
    transcript: str = typer.Option(..., "--transcript", help="transcript.jsonl 경로"),
):
    """세션 종료 시 학습 (SessionEnd hook용)."""
    db = get_connection()
    config = load_config()
    run_writeback(workspace, session_id, Path(transcript), db, config)
    typer.echo("Writeback complete.")


# ---------------------------------------------------------------------------
# forge detect (hook용)
# ---------------------------------------------------------------------------

@app.command("detect")
def cmd_detect(
    workspace: str = typer.Option(..., "--workspace", "-w", help="워크스페이스 ID"),
):
    """Bash 실패 실시간 감지 (PostToolUse hook용). stdin에서 JSON 읽기."""
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # JSON이 아니면 아무것도 하지 않음
        return

    tool_name = payload.get("tool_name") or payload.get("tool") or ""
    tool_response = payload.get("tool_response") or payload.get("result") or payload

    db = get_connection()
    result = run_detect(tool_name, tool_response, workspace, db)
    if result:
        typer.echo(json.dumps(result))


# ---------------------------------------------------------------------------
# forge install-hooks
# ---------------------------------------------------------------------------

@app.command("install-hooks")
def cmd_install_hooks():
    """Claude Code hook 설정 설치."""
    from forge.hooks.install import install_hooks
    install_hooks()
    typer.echo("Hooks installed successfully.")


if __name__ == "__main__":
    app()
