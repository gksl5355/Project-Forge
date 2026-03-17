"""Forge CLI — Typer 앱, 모든 명령 등록."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import typer

from forge.config import load_config
from forge.core.promote import promote_to_global, promote_to_knowledge
from forge.core.qvalue import ema_update, initial_q, time_decay
from forge.engines.detect import run_detect
from forge.engines.resume import run_resume
from forge.engines.writeback import run_writeback
from forge.storage.db import get_connection, init_db
from forge.storage.models import Decision, Failure, Knowledge, Rule
from forge.storage.queries import (
    _row_to_failure,
    get_decision_by_id,
    get_failure_by_id,
    get_failure_by_pattern,
    insert_decision,
    insert_failure,
    insert_knowledge,
    insert_rule,
    list_decisions,
    list_failures,
    list_flagged_failures,
    list_knowledge,
    list_rules,
    list_team_runs,
    search_by_tags,
    update_decision,
    update_failure,
    update_rule,
)

app = typer.Typer(help="Project Forge — 코딩 에이전트를 위한 경험 학습 CLI")
record_app = typer.Typer(help="경험 데이터 기록")
app.add_typer(record_app, name="record")


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
    tag: list[str] | None = typer.Option(None, "--tag", "-t", help="태그 (반복 가능)"),
    observed: str | None = typer.Option(None, "--observed", help="관찰된 에러 메시지"),
    cause: str | None = typer.Option(None, "--cause", help="예상 원인"),
):
    """실패 패턴 기록."""
    if not pattern.strip():
        typer.echo("Error: pattern cannot be empty", err=True)
        raise typer.Exit(1)
    if not hint.strip():
        typer.echo("Error: hint cannot be empty", err=True)
        raise typer.Exit(1)
    if len(pattern) > 200:
        typer.echo("Error: pattern must be 200 chars or less", err=True)
        raise typer.Exit(1)
    if len(hint) > 2000:
        typer.echo("Error: hint must be 2000 chars or less", err=True)
        raise typer.Exit(1)
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
    try:
        fid = insert_failure(db, failure)
    except sqlite3.IntegrityError:
        typer.echo(f"Pattern '{pattern}' already exists in workspace '{workspace}'. Use 'forge edit' to update.", err=True)
        raise typer.Exit(1)
    typer.echo(f"Failure recorded (id={fid}): {pattern}")


# ---------------------------------------------------------------------------
# forge record decision
# ---------------------------------------------------------------------------

@record_app.command("decision")
def cmd_record_decision(
    statement: str = typer.Option(..., "--statement", "-s", help="결정 내용"),
    workspace: str = typer.Option("default", "--workspace", "-w", help="워크스페이스 ID"),
    rationale: str | None = typer.Option(None, "--rationale", "-r", help="이유"),
    tag: list[str] | None = typer.Option(None, "--tag", "-t", help="태그 (반복 가능)"),
    alternative: list[str] | None = typer.Option(None, "--alternative", help="대안 (반복 가능)"),
):
    """결정 기록."""
    if not statement.strip():
        typer.echo("Error: statement cannot be empty", err=True)
        raise typer.Exit(1)
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
    scope: str | None = typer.Option(None, "--scope", help="적용 범위"),
    mode: str = typer.Option("warn", "--mode", "-m", help="block | warn | log"),
):
    """룰 기록."""
    if not text.strip():
        typer.echo("Error: rule text cannot be empty", err=True)
        raise typer.Exit(1)
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
    tag: list[str] | None = typer.Option(None, "--tag", "-t", help="태그 (반복 가능)"),
):
    """지식 기록."""
    if not title.strip():
        typer.echo("Error: title cannot be empty", err=True)
        raise typer.Exit(1)
    if not content.strip():
        typer.echo("Error: content cannot be empty", err=True)
        raise typer.Exit(1)
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
                               help="failure | decision | rule | knowledge | team_run"),
    sort: str = typer.Option("q", "--sort", "-s", help="정렬 기준 (q, times_seen, created_at)"),
    flagged: bool = typer.Option(False, "--flagged", help="review_flag가 True인 실패만 표시"),
):
    """경험 목록 조회."""
    db = get_connection()

    if type_ == "failure":
        if flagged:
            items = list_flagged_failures(db, workspace)
        else:
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
    elif type_ == "team_run":
        items = list_team_runs(db, workspace)
        for tr in items:
            sr = f"{tr.success_rate:.0%}" if tr.success_rate is not None else "N/A"
            typer.echo(f"[{tr.id}] {tr.run_id} | {tr.complexity or 'N/A'} | success:{sr} | {tr.verdict or ''}")
    else:
        valid = "failure, decision, rule, knowledge, team_run"
        typer.echo(f"Error: unknown type '{type_}'. Valid: {valid}", err=True)
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
    hint: str | None = typer.Option(None, "--hint", help="새 avoid_hint (failure용)"),
    rationale: str | None = typer.Option(None, "--rationale", help="새 rationale (decision용)"),
    status: str | None = typer.Option(
        None, "--status", help="새 status (decision용): active | superseded | revisiting"
    ),
):
    """기록 편집."""
    db = get_connection()

    # Failure 시도
    failure = get_failure_by_id(db, id_, workspace)
    if failure:
        if not hint:
            typer.echo("No changes requested. Use --hint to update avoid_hint.", err=True)
            return
        failure.avoid_hint = hint
        update_failure(db, failure)
        typer.echo(f"Failure {id_} hint updated.")
        return

    # Decision 시도
    decision = get_decision_by_id(db, id_, workspace)
    if decision:
        if not rationale and not status:
            typer.echo(
                "No changes requested. Use --rationale or --status to update.", err=True
            )
            return

        if rationale:
            decision.rationale = rationale

        if status:
            valid_statuses = {"active", "superseded", "revisiting"}
            if status not in valid_statuses:
                typer.echo(f"Error: status must be one of {valid_statuses}", err=True)
                raise typer.Exit(1)
            if status != decision.status:
                config = load_config()
                if status == "superseded":
                    reward = 0.0
                elif status == "revisiting":
                    reward = 0.5
                else:  # active
                    reward = 1.0
                decision.q = ema_update(decision.q, reward, config.alpha)
                decision.status = status

        update_decision(db, decision)
        typer.echo(f"Decision {id_} updated.")
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
    db = get_connection()
    failure = get_failure_by_id(db, id_, workspace)
    if not failure:
        failure = get_failure_by_id(db, id_, "__global__")
    if not failure:
        # Fallback: try without workspace filter
        row = db.execute("SELECT * FROM failures WHERE id = ?", (id_,)).fetchone()
        if not row:
            typer.echo(f"Failure {id_} not found.", err=True)
            raise typer.Exit(1)
        failure = _row_to_failure(row)

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

    row = db.execute(
        """
        SELECT COUNT(*) as cnt,
               AVG(failures_encountered) as avg_f,
               SUM(q_updates_count) as sum_q,
               SUM(promotions_count) as sum_p
        FROM sessions WHERE workspace_id = ?
        """,
        (workspace,),
    ).fetchone()
    total_sessions = row["cnt"] if row else 0
    typer.echo(f"  Sessions:  {total_sessions}")
    if total_sessions > 0:
        avg_f = row["avg_f"] or 0.0
        typer.echo(f"  Avg failures per session: {avg_f:.1f}")
        typer.echo(f"  Total Q-updates: {row['sum_q'] or 0}")
        typer.echo(f"  Total promotions: {row['sum_p'] or 0}")


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
    team_brief: bool = typer.Option(False, "--team-brief", help="팀 경험 요약만 출력 (TO 연동용)"),
):
    """세션 시작 시 context 주입 (SessionStart hook용)."""
    db = get_connection()
    config = load_config()
    context = run_resume(workspace, session_id, db, config, team_brief=team_brief)
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
    llm_extract: bool = typer.Option(False, "--llm-extract", help="LLM 기반 자동 추출 활성화"),
):
    """세션 종료 시 학습 (SessionEnd hook용)."""
    db = get_connection()
    config = load_config()
    run_writeback(workspace, session_id, Path(transcript), db, config, llm_extract=llm_extract)
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
    from forge.hooks.install import install_hooks  # lazy import to avoid startup cost
    install_hooks()
    typer.echo("Hooks installed successfully.")


# ---------------------------------------------------------------------------
# forge setup (one-stop setup)
# ---------------------------------------------------------------------------

@app.command("setup")
def cmd_setup():
    """Forge 전체 설정 (DB 초기화 + hooks 설치 + 팀 환경 구성)."""
    from forge.hooks.install import install_hooks

    # 1. Init DB
    init_db()
    typer.echo("[1/3] DB initialized.")

    # 2. Install hooks + teammate + env
    install_hooks()
    typer.echo("[2/3] Hooks + teammate.sh installed.")

    # 3. Summary
    typer.echo("[3/3] Setup complete.")
    typer.echo("")
    typer.echo("Installed:")
    typer.echo("  ~/.forge/forge.db          (experience database)")
    typer.echo("  ~/.forge/hooks/resume.sh   (SessionStart hook)")
    typer.echo("  ~/.forge/hooks/writeback.sh (SessionEnd hook)")
    typer.echo("  ~/.forge/hooks/detect.sh   (PostToolUse hook)")
    typer.echo("  ~/.forge/hooks/teammate.sh (team model selector)")
    typer.echo("  ~/.claude/settings.json    (hooks + env patched)")
    typer.echo("")
    typer.echo("Next: Start a Claude Code session. Forge will auto-learn.")


# ---------------------------------------------------------------------------
# forge ingest (v1: TO 런 데이터 수집)
# ---------------------------------------------------------------------------

@app.command("ingest")
def cmd_ingest(
    workspace: str = typer.Option(..., "--workspace", "-w", help="워크스페이스 ID"),
    run_dir: str | None = typer.Option(None, "--run-dir", help=".claude/runs/<RUN_ID>/ 경로"),
    auto: bool = typer.Option(False, "--auto", help=".claude/runs/ 아래 자동 감지"),
):
    """TO 런 데이터를 forge.db로 수집."""
    from forge.engines.ingest import run_ingest, run_ingest_auto

    db = init_db()
    config = load_config()

    if auto:
        runs_base = Path.cwd() / ".claude" / "runs"
        counts = run_ingest_auto(workspace, runs_base, db, config)
    elif run_dir:
        counts = run_ingest(workspace, Path(run_dir), db, config)
    else:
        typer.echo("Error: specify --run-dir or --auto", err=True)
        raise typer.Exit(1)

    typer.echo(f"Ingested: {counts['team_runs']} runs, {counts['failures']} failures, {counts['knowledge']} knowledge")


# ---------------------------------------------------------------------------
# forge embed (v1: 벡터 임베딩 생성)
# ---------------------------------------------------------------------------

@app.command("embed")
def cmd_embed(
    workspace: str = typer.Option("default", "--workspace", "-w", help="워크스페이스 ID"),
):
    """실패 패턴에 대한 벡터 임베딩 생성."""
    from forge.core.embedding import embed_failures, get_embedder

    if get_embedder() is None:
        typer.echo("Error: sentence-transformers not installed. Run: pip install sentence-transformers", err=True)
        raise typer.Exit(1)

    db = init_db()
    count = embed_failures(db, workspace)
    typer.echo(f"Embedded {count} failure(s).")


# ---------------------------------------------------------------------------
# forge dedup (v1: 중복 병합)
# ---------------------------------------------------------------------------

@app.command("dedup")
def cmd_dedup(
    workspace: str = typer.Option("default", "--workspace", "-w", help="워크스페이스 ID"),
    auto: bool = typer.Option(False, "--auto", help="자동 병합 (확인 없이)"),
):
    """유사 실패 패턴 중복 탐지 및 병합."""
    from forge.core.dedup import run_dedup

    db = init_db()
    config = load_config()
    results = run_dedup(db, workspace, config, auto=auto)

    if not results:
        typer.echo("No duplicates found.")
        return

    for r in results:
        action = "MERGED" if r.get("merged") else "SUGGEST"
        typer.echo(
            f"[{action}] {r['pattern_a']} (Q:{r['q_a']:.2f}) "
            f"↔ {r['pattern_b']} (Q:{r['q_b']:.2f}) — similarity {r['similarity']:.2f}"
        )

    if not auto:
        typer.echo(f"\n{len(results)} duplicate pair(s) found. Use --auto to merge automatically.")


# ---------------------------------------------------------------------------
# forge optimize (AutoResearch)
# ---------------------------------------------------------------------------

@app.command("optimize")
def cmd_optimize(
    workspace: str = typer.Option("default", "--workspace", "-w", help="워크스페이스 ID"),
    max_experiments: int = typer.Option(50, "--max-experiments", help="최대 실험 횟수"),
    strategy: str = typer.Option("greedy", "--strategy", help="탐색 전략 (greedy)"),
    save_best: bool = typer.Option(False, "--save-best", help="최적 설정을 config.yml에 저장"),
    dry_run: bool = typer.Option(False, "--dry-run", help="저장하지 않고 결과만 표시"),
):
    """컨텍스트 설정 자동 최적화 (AutoResearch)."""
    from forge.engines.optimizer import PARAM_GRID, run_autoresearch

    db = get_connection()
    config = load_config()

    failures_count = len(list_failures(db, workspace, include_global=False))

    def on_progress(step, total, desc, result, improved):
        marker = " IMPROVED" if improved else ""
        typer.echo(f"[{step}/{total}] {desc} -> QWHR: {result.qwhr:.2f}{marker}")

    typer.echo(f"Optimizing with {failures_count} failures...")

    result = run_autoresearch(
        workspace, db, config, max_experiments, strategy,
        on_progress=on_progress,
    )

    if result.baseline.sessions_evaluated == 0:
        typer.echo("Need at least 1 session with warnings data.")
        return

    typer.echo(f"\n=== Results ===")
    b = result.baseline
    best = result.best
    typer.echo(
        f"Baseline:  QWHR={b.qwhr:.2f}  TokenEff={b.token_efficiency:.3f}"
        f"  PromoPrecision={b.promotion_precision:.2f}  Fitness={b.composite_fitness:.2f}"
    )
    if b.composite_fitness > 0:
        pct = (best.composite_fitness - b.composite_fitness) / b.composite_fitness * 100
        typer.echo(
            f"Best:      QWHR={best.qwhr:.2f}  TokenEff={best.token_efficiency:.3f}"
            f"  PromoPrecision={best.promotion_precision:.2f}  Fitness={best.composite_fitness:.2f} ({pct:+.0f}%)"
        )
    else:
        typer.echo(
            f"Best:      QWHR={best.qwhr:.2f}  TokenEff={best.token_efficiency:.3f}"
            f"  PromoPrecision={best.promotion_precision:.2f}  Fitness={best.composite_fitness:.2f}"
        )
    typer.echo(f"Experiments: {result.total_experiments}")

    typer.echo(f"\n=== Recommended Config ===")
    for param in PARAM_GRID:
        baseline_val = getattr(result.baseline.config, param)
        best_val = getattr(result.best.config, param)
        marker = " *" if baseline_val != best_val else ""
        typer.echo(f"  {param}: {best_val}{marker}")

    if save_best and not dry_run and result.improved:
        from forge.config import save_config_yaml
        save_config_yaml(result.best.config)
        typer.echo(f"\nConfig saved to ~/.forge/config.yml")
    elif not result.improved:
        typer.echo(f"\nCurrent config is already optimal.")


# ---------------------------------------------------------------------------
# forge measure
# ---------------------------------------------------------------------------

@app.command("measure")
def cmd_measure(
    workspace: str = typer.Option("default", "--workspace", "-w", help="워크스페이스 ID"),
) -> None:
    """현재 워크스페이스의 최적화 메트릭 측정."""
    from forge.engines.measure import run_measure

    db = get_connection()
    config = load_config()

    result = run_measure(workspace, db, config)

    typer.echo(f"=== Forge Metrics (workspace: {workspace}) ===")
    typer.echo(f"  QWHR:                  {result.qwhr:.2f}")
    typer.echo(f"  Promotion precision:   {result.promotion_precision:.2f}")
    sign = "+" if result.l1_vs_l0_help_rate >= 0 else ""
    typer.echo(f"  L1 vs L0 help rate:   {sign}{result.l1_vs_l0_help_rate:.2f}")
    typer.echo(f"  Helped per 1K tokens:  {result.helped_per_1k_tokens:.2f}")
    typer.echo(f"  Q convergence speed:   {result.q_convergence_speed:.1f} sessions")
    typer.echo(f"  Failures: {result.total_failures} | Sessions: {result.total_sessions}")
    typer.echo("")
    typer.echo("  Section effectiveness:")
    for section, value in result.section_effectiveness.items():
        if value is None:
            typer.echo(f"    {section}:   N/A")
        else:
            typer.echo(f"    {section}:   {value:.2f}")

    # TO metrics
    if result.to_total_runs > 0:
        typer.echo("")
        typer.echo(f"=== TO Metrics (Team Runs: {result.to_total_runs}) ===")
        sr = f"{result.to_avg_success_rate:.0%}" if result.to_avg_success_rate is not None else "N/A"
        rr = f"{result.to_avg_retry_rate:.0%}" if result.to_avg_retry_rate is not None else "N/A"
        sv = f"{result.to_avg_scope_violations:.1f}" if result.to_avg_scope_violations is not None else "N/A"
        typer.echo(f"  Avg success rate:      {sr}")
        typer.echo(f"  Avg retry rate:        {rr}")
        typer.echo(f"  Avg scope violations:  {sv}")
        if result.to_best_configs:
            typer.echo("  Best configs:")
            for complexity, info in result.to_best_configs.items():
                typer.echo(
                    f"    {complexity}: {info['config']} "
                    f"(success: {info['success_rate']:.0%}, runs: {info['runs']})"
                )
    typer.echo(f"  Unified fitness:       {result.unified_fitness:.4f}")


# ---------------------------------------------------------------------------
# forge recommend
# ---------------------------------------------------------------------------

@app.command("recommend")
def cmd_recommend(
    workspace: str = typer.Option("default", "--workspace", "-w", help="워크스페이스 ID"),
    complexity: str = typer.Option("MEDIUM", "--complexity", "-c",
                                    help="SIMPLE | MEDIUM | COMPLEX"),
) -> None:
    """팀 구성 추천 (과거 TO 런 기반)."""
    from forge.engines.recommend import run_recommend

    db = get_connection()

    result = run_recommend(workspace, complexity, db)

    if result is None:
        typer.echo(f"No team runs found for complexity={complexity} in workspace '{workspace}'.")
        return

    typer.echo(
        f"{result.config} "
        f"({result.runs} runs, success: {result.avg_success_rate:.0%}, "
        f"confidence: {result.confidence})"
    )


# ---------------------------------------------------------------------------
# forge trend
# ---------------------------------------------------------------------------

@app.command("trend")
def cmd_trend(
    workspace: str = typer.Option("default", "--workspace", "-w", help="워크스페이스 ID"),
    n: int = typer.Option(20, "-n", help="표시할 실험 수"),
) -> None:
    """실험 fitness 추이 조회."""
    from forge.storage.queries import get_best_experiment, list_experiments

    db = get_connection()
    experiments = list_experiments(db, workspace, limit=n, order_by="recorded_at")

    if not experiments:
        typer.echo(f"No experiments found for workspace '{workspace}'.")
        return

    # Reverse to show oldest first (list_experiments returns newest first)
    experiments = list(reversed(experiments))

    typer.echo(f"=== Fitness Trend (last {len(experiments)}) ===")
    typer.echo(f"{'Time':<18} | {'Fitness':>7} | {'Δ':>7} | {'Config':>8} | {'Doc':>8} | {'Type':<8}")
    typer.echo("-" * 75)

    prev_fitness = None
    worst = min(e.unified_fitness for e in experiments)
    for exp in experiments:
        delta = ""
        if prev_fitness is not None:
            d = exp.unified_fitness - prev_fitness
            delta = f"{d:+.3f}"
        time_str = exp.recorded_at.strftime("%Y-%m-%d %H:%M") if exp.recorded_at else "N/A"
        typer.echo(
            f"{time_str:<18} | {exp.unified_fitness:>7.4f} | {delta:>7} | "
            f"{exp.config_hash[:8]:>8} | {exp.document_hash[:8]:>8} | {exp.experiment_type:<8}"
        )
        prev_fitness = exp.unified_fitness

    best_exp = get_best_experiment(db, workspace)
    best_fitness = best_exp.unified_fitness if best_exp else 0.0
    current = experiments[-1].unified_fitness if experiments else 0.0
    typer.echo("-" * 75)
    typer.echo(
        f"Best: {best_fitness:.4f} | Worst: {worst:.4f} | Current: {current:.4f}"
    )


# ---------------------------------------------------------------------------
# forge research
# ---------------------------------------------------------------------------

@app.command("research")
def cmd_research(
    workspace: str = typer.Option("default", "--workspace", "-w", help="워크스페이스 ID"),
    max_rounds: int = typer.Option(50, "--max-rounds", help="최대 반복 횟수"),
    strategy: str = typer.Option("greedy", "--strategy", help="greedy | ablation"),
    include_docs: bool = typer.Option(False, "--include-docs", help="문서 directive도 탐색 대상에 포함"),
    target_fitness: float = typer.Option(0.85, "--target-fitness", help="목표 fitness"),
    save_best: bool = typer.Option(False, "--save-best", help="최적 config 저장"),
) -> None:
    """AutoResearch 확장 — 문서 포함 최적화 루프."""
    import json as json_mod
    from forge.core.hashing import compute_config_hash, compute_combined_doc_hash, compute_doc_hashes
    from forge.engines.fitness import compute_unified_fitness
    from forge.engines.measure import run_measure
    from forge.engines.optimizer import run_autoresearch, PARAM_GRID
    from forge.storage.models import Experiment
    from forge.storage.queries import insert_experiment

    db = get_connection()
    config = load_config()

    # 1. Baseline measurement
    measure_result = run_measure(workspace, db, config)
    typer.echo(f"Baseline fitness: {measure_result.unified_fitness:.4f}")

    if measure_result.total_sessions == 0 and measure_result.total_failures == 0:
        typer.echo("No data to optimize. Record some sessions first.")
        return

    # 2. Config hash + doc hashes
    config_hash = compute_config_hash(config)
    doc_hashes = compute_doc_hashes(Path.cwd())
    doc_hash = compute_combined_doc_hash(doc_hashes)

    # 3. Record baseline experiment
    baseline_exp = Experiment(
        workspace_id=workspace,
        experiment_type="manual",
        config_snapshot=json_mod.dumps({
            k: getattr(config, k) for k in PARAM_GRID
        }),
        config_hash=config_hash,
        document_hashes=doc_hashes,
        document_hash=doc_hash,
        unified_fitness=measure_result.unified_fitness,
        qwhr=measure_result.qwhr,
        token_efficiency=measure_result.helped_per_1k_tokens / 1000.0,
        promotion_precision=measure_result.promotion_precision,
        to_success_rate=measure_result.to_avg_success_rate,
        to_retry_rate=measure_result.to_avg_retry_rate,
        to_scope_violations=measure_result.to_avg_scope_violations,
        sessions_evaluated=measure_result.total_sessions,
        team_runs_evaluated=measure_result.to_total_runs,
        notes="baseline",
    )
    insert_experiment(db, baseline_exp)

    # 4. Run config optimization
    def on_progress(step, total, desc, result, improved):
        marker = " IMPROVED" if improved else ""
        typer.echo(f"  [{step}/{total}] {desc} -> fitness: {result.composite_fitness:.4f}{marker}")

    typer.echo(f"\nOptimizing config (max {max_rounds} rounds, strategy: {strategy})...")
    opt_result = run_autoresearch(
        workspace, db, config, max_experiments=max_rounds, strategy=strategy,
        on_progress=on_progress,
    )

    if opt_result.improved:
        best = opt_result.best
        new_config_hash = compute_config_hash(best.config)

        best_exp = Experiment(
            workspace_id=workspace,
            experiment_type="auto",
            config_snapshot=json_mod.dumps({
                k: getattr(best.config, k) for k in PARAM_GRID
            }),
            config_hash=new_config_hash,
            document_hashes=doc_hashes,
            document_hash=doc_hash,
            unified_fitness=best.composite_fitness,
            qwhr=best.qwhr,
            token_efficiency=best.token_efficiency,
            promotion_precision=best.promotion_precision,
            sessions_evaluated=best.sessions_evaluated,
            notes="auto-research best",
        )
        insert_experiment(db, best_exp)

        typer.echo(f"\nBest fitness: {best.composite_fitness:.4f} (was {opt_result.baseline.composite_fitness:.4f})")

        if best.composite_fitness >= target_fitness:
            typer.echo(f"Target fitness {target_fitness:.2f} reached!")

        if save_best:
            from forge.config import save_config_yaml
            save_config_yaml(best.config)
            typer.echo("Best config saved to ~/.forge/config.yml")

        typer.echo(f"\n=== Recommended Config Changes ===")
        for param in PARAM_GRID:
            baseline_val = getattr(opt_result.baseline.config, param)
            best_val = getattr(opt_result.best.config, param)
            if baseline_val != best_val:
                typer.echo(f"  {param}: {baseline_val} -> {best_val}")
    else:
        typer.echo("\nCurrent config is already optimal.")

    # 5. Document ablation (if --include-docs)
    if include_docs:
        typer.echo(f"\n=== Document Directive Analysis ===")
        try:
            from forge.engines.directive_extractor import extract_directives
            # Find CLAUDE.md in cwd
            claude_md = Path.cwd() / "CLAUDE.md"
            if claude_md.exists():
                directives = extract_directives(claude_md)
                typer.echo(f"Extracted {len(directives)} directives from CLAUDE.md")
                by_type: dict[str, int] = {}
                for d in directives:
                    by_type[d.directive_type] = by_type.get(d.directive_type, 0) + 1
                for dt, count in sorted(by_type.items()):
                    typer.echo(f"  {dt}: {count}")
                total_tokens = sum(d.tokens for d in directives)
                typer.echo(f"  Total tokens: ~{total_tokens}")
            else:
                typer.echo("No CLAUDE.md found in current directory.")
        except ImportError:
            typer.echo("Directive extractor not available.")

    typer.echo(f"\nExperiments: {opt_result.total_experiments}")


if __name__ == "__main__":
    app()
