"""CLI edge case tests — Typer CliRunner.

Coverage:
  forge init (double init)
  forge record failure/decision/rule/knowledge (missing fields, duplicates, enums)
  forge list (empty DB, type/sort variations)
  forge search (tags)
  forge detail (existing/non-existent)
  forge edit (valid/invalid ID)
  forge promote (valid/invalid, --to-knowledge)
  forge stats, decay --dry-run
  forge resume, writeback, detect
  forge install-hooks
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from forge.cli import app
from forge.config import ForgeConfig
from forge.storage.models import Decision, Failure, Knowledge, Rule, Session
from forge.storage.queries import (
    insert_decision,
    insert_failure,
    insert_knowledge,
    insert_rule,
    insert_session,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def runner():
    return CliRunner()


def _invoke(runner: CliRunner, db, args: list[str], *, stdin: str | None = None):
    """CLI 호출 헬퍼: get_connection/load_config/init_db를 인메모리 DB로 패치."""
    with (
        patch("forge.cli.get_connection", return_value=db),
        patch("forge.cli.load_config", return_value=ForgeConfig()),
        patch("forge.cli.init_db"),
    ):
        return runner.invoke(app, args, input=stdin)


def _make_failure(
    ws: str = "default",
    pattern: str = "test_pattern",
    q: float = 0.5,
    avoid_hint: str = "some hint",
    hint_quality: str = "preventable",
    **kwargs,
) -> Failure:
    return Failure(
        workspace_id=ws,
        pattern=pattern,
        avoid_hint=avoid_hint,
        hint_quality=hint_quality,
        q=q,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# forge init
# ---------------------------------------------------------------------------

class TestInit:
    def test_init_prints_message(self, runner: CliRunner):
        with patch("forge.cli.init_db") as mock_init:
            result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert "initialized" in result.output.lower()
        mock_init.assert_called_once()

    def test_double_init_idempotent(self, runner: CliRunner):
        """init 두 번 호출해도 오류 없음 (idempotent)."""
        with patch("forge.cli.init_db"):
            r1 = runner.invoke(app, ["init"])
            r2 = runner.invoke(app, ["init"])
        assert r1.exit_code == 0
        assert r2.exit_code == 0


# ---------------------------------------------------------------------------
# forge record failure
# ---------------------------------------------------------------------------

class TestRecordFailure:
    def test_record_success(self, db, runner: CliRunner):
        result = _invoke(runner, db, [
            "record", "failure", "--pattern", "my_error", "--hint", "fix it",
        ])
        assert result.exit_code == 0
        assert "my_error" in result.output

    def test_missing_pattern(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["record", "failure", "--hint", "fix it"])
        assert result.exit_code != 0

    def test_missing_hint(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["record", "failure", "--pattern", "my_error"])
        assert result.exit_code != 0

    def test_invalid_quality(self, db, runner: CliRunner):
        result = _invoke(runner, db, [
            "record", "failure",
            "--pattern", "my_error", "--hint", "fix it",
            "--quality", "bad_value",
        ])
        assert result.exit_code == 1
        assert "quality" in result.output.lower()

    def test_quality_near_miss(self, db, runner: CliRunner):
        result = _invoke(runner, db, [
            "record", "failure",
            "--pattern", "near_err", "--hint", "hint",
            "--quality", "near_miss",
        ])
        assert result.exit_code == 0

    def test_quality_preventable(self, db, runner: CliRunner):
        result = _invoke(runner, db, [
            "record", "failure",
            "--pattern", "prev_err", "--hint", "hint",
            "--quality", "preventable",
        ])
        assert result.exit_code == 0

    def test_quality_environmental(self, db, runner: CliRunner):
        result = _invoke(runner, db, [
            "record", "failure",
            "--pattern", "env_err", "--hint", "hint",
            "--quality", "environmental",
        ])
        assert result.exit_code == 0

    def test_duplicate_pattern_fails(self, db, runner: CliRunner):
        _invoke(runner, db, ["record", "failure", "--pattern", "dup_err", "--hint", "h"])
        result = _invoke(runner, db, ["record", "failure", "--pattern", "dup_err", "--hint", "h"])
        assert result.exit_code == 1
        assert "dup_err" in result.output

    def test_with_tags(self, db, runner: CliRunner):
        result = _invoke(runner, db, [
            "record", "failure",
            "--pattern", "tagged_err", "--hint", "h",
            "--tag", "python", "--tag", "import",
        ])
        assert result.exit_code == 0

    def test_with_observed_and_cause(self, db, runner: CliRunner):
        result = _invoke(runner, db, [
            "record", "failure",
            "--pattern", "obs_err", "--hint", "h",
            "--observed", "TypeError: x", "--cause", "bad cast",
        ])
        assert result.exit_code == 0

    def test_with_workspace(self, db, runner: CliRunner):
        result = _invoke(runner, db, [
            "record", "failure",
            "--pattern", "ws_err", "--hint", "h",
            "--workspace", "proj_alpha",
        ])
        assert result.exit_code == 0
        assert "ws_err" in result.output

    def test_output_contains_id(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["record", "failure", "--pattern", "id_err", "--hint", "h"])
        assert result.exit_code == 0
        assert "id=" in result.output


# ---------------------------------------------------------------------------
# forge record decision
# ---------------------------------------------------------------------------

class TestRecordDecision:
    def test_missing_statement(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["record", "decision"])
        assert result.exit_code != 0

    def test_record_minimal(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["record", "decision", "--statement", "Use SQLite"])
        assert result.exit_code == 0
        assert "recorded" in result.output.lower() or "Use SQLite" in result.output

    def test_record_full(self, db, runner: CliRunner):
        result = _invoke(runner, db, [
            "record", "decision",
            "--statement", "No ORM",
            "--rationale", "simpler",
            "--tag", "db",
            "--alternative", "SQLAlchemy",
        ])
        assert result.exit_code == 0

    def test_output_contains_id(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["record", "decision", "--statement", "Use uv"])
        assert result.exit_code == 0
        assert "id=" in result.output


# ---------------------------------------------------------------------------
# forge record rule
# ---------------------------------------------------------------------------

class TestRecordRule:
    def test_missing_text(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["record", "rule"])
        assert result.exit_code != 0

    def test_invalid_mode(self, db, runner: CliRunner):
        result = _invoke(runner, db, [
            "record", "rule", "--text", "no raw sql", "--mode", "yell",
        ])
        assert result.exit_code == 1
        assert "mode" in result.output.lower()

    def test_mode_block(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["record", "rule", "--text", "rule_b", "--mode", "block"])
        assert result.exit_code == 0

    def test_mode_warn(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["record", "rule", "--text", "rule_w", "--mode", "warn"])
        assert result.exit_code == 0

    def test_mode_log(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["record", "rule", "--text", "rule_l", "--mode", "log"])
        assert result.exit_code == 0

    def test_with_scope(self, db, runner: CliRunner):
        result = _invoke(runner, db, [
            "record", "rule", "--text", "rule_s", "--scope", "tests/",
        ])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# forge record knowledge
# ---------------------------------------------------------------------------

class TestRecordKnowledge:
    def test_missing_title(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["record", "knowledge", "--content", "some content"])
        assert result.exit_code != 0

    def test_missing_content(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["record", "knowledge", "--title", "some title"])
        assert result.exit_code != 0

    def test_record_success(self, db, runner: CliRunner):
        result = _invoke(runner, db, [
            "record", "knowledge", "--title", "Python tip", "--content", "use walrus",
        ])
        assert result.exit_code == 0
        assert "Python tip" in result.output

    def test_with_tags(self, db, runner: CliRunner):
        result = _invoke(runner, db, [
            "record", "knowledge",
            "--title", "tagged tip", "--content", "content",
            "--tag", "python",
        ])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# forge list
# ---------------------------------------------------------------------------

class TestList:
    def test_empty_db_type_failure(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["list"])
        assert result.exit_code == 0
        # 빈 DB → 출력 없음 (에러 없음)

    def test_list_failures_shows_item(self, db, runner: CliRunner):
        insert_failure(db, _make_failure(ws="default", pattern="err1"))
        result = _invoke(runner, db, ["list", "--type", "failure"])
        assert result.exit_code == 0
        assert "err1" in result.output

    def test_list_decisions(self, db, runner: CliRunner):
        insert_decision(db, Decision(workspace_id="default", statement="Use X"))
        result = _invoke(runner, db, ["list", "--type", "decision"])
        assert result.exit_code == 0
        assert "Use X" in result.output

    def test_list_rules(self, db, runner: CliRunner):
        insert_rule(db, Rule(workspace_id="default", rule_text="no raw sql"))
        result = _invoke(runner, db, ["list", "--type", "rule"])
        assert result.exit_code == 0
        assert "no raw sql" in result.output

    def test_list_knowledge(self, db, runner: CliRunner):
        insert_knowledge(db, Knowledge(workspace_id="default", title="K tip", content="c"))
        result = _invoke(runner, db, ["list", "--type", "knowledge"])
        assert result.exit_code == 0
        assert "K tip" in result.output

    def test_invalid_type(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["list", "--type", "bogus"])
        assert result.exit_code == 1
        assert "unknown type" in result.output.lower() or "bogus" in result.output

    def test_sort_by_times_seen(self, db, runner: CliRunner):
        insert_failure(db, _make_failure(pattern="sort_a"))
        result = _invoke(runner, db, ["list", "--sort", "times_seen"])
        assert result.exit_code == 0

    def test_sort_by_created_at(self, db, runner: CliRunner):
        insert_failure(db, _make_failure(pattern="sort_b"))
        result = _invoke(runner, db, ["list", "--sort", "created_at"])
        assert result.exit_code == 0

    def test_workspace_filter(self, db, runner: CliRunner):
        insert_failure(db, _make_failure(ws="proj_a", pattern="proj_err"))
        insert_failure(db, _make_failure(ws="proj_b", pattern="other_err"))
        result = _invoke(runner, db, ["list", "--workspace", "proj_a"])
        assert result.exit_code == 0
        assert "proj_err" in result.output
        assert "other_err" not in result.output

    def test_list_multiple_failures(self, db, runner: CliRunner):
        insert_failure(db, _make_failure(pattern="multi1", q=0.8))
        insert_failure(db, _make_failure(pattern="multi2", q=0.6))
        result = _invoke(runner, db, ["list", "--type", "failure"])
        assert result.exit_code == 0
        assert "multi1" in result.output
        assert "multi2" in result.output

    def test_flagged_shows_only_flagged(self, db, runner: CliRunner):
        insert_failure(db, _make_failure(pattern="flagged_f", review_flag=True))
        insert_failure(db, _make_failure(pattern="normal_f", review_flag=False))
        result = _invoke(runner, db, ["list", "--flagged"])
        assert result.exit_code == 0
        assert "flagged_f" in result.output
        assert "normal_f" not in result.output

    def test_flagged_empty_db(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["list", "--flagged"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# forge search
# ---------------------------------------------------------------------------

class TestSearch:
    def test_missing_tag(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["search"])
        assert result.exit_code != 0

    def test_no_results(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["search", "--tag", "nonexistent_tag_xyz"])
        assert result.exit_code == 0
        assert "No results found" in result.output

    def test_with_matching_tag(self, db, runner: CliRunner):
        insert_failure(db, _make_failure(pattern="tagged_err", tags=["python"]))
        result = _invoke(runner, db, ["search", "--tag", "python"])
        assert result.exit_code == 0
        assert "tagged_err" in result.output

    def test_multiple_tags_union(self, db, runner: CliRunner):
        insert_failure(db, _make_failure(pattern="tag_a", tags=["foo"]))
        insert_failure(db, _make_failure(pattern="tag_b", tags=["bar"]))
        result = _invoke(runner, db, ["search", "--tag", "foo", "--tag", "bar"])
        assert result.exit_code == 0
        assert "tag_a" in result.output
        assert "tag_b" in result.output

    def test_empty_db_no_results(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["search", "--tag", "python"])
        assert result.exit_code == 0
        assert "No results found" in result.output


# ---------------------------------------------------------------------------
# forge detail
# ---------------------------------------------------------------------------

class TestDetail:
    def test_existing_pattern(self, db, runner: CliRunner):
        insert_failure(db, _make_failure(pattern="detail_err"))
        result = _invoke(runner, db, ["detail", "detail_err"])
        assert result.exit_code == 0
        assert "detail_err" in result.output
        assert "Hint" in result.output

    def test_nonexistent_pattern(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["detail", "no_such_pattern_xyz"])
        assert result.exit_code == 1

    def test_detail_shows_all_fields(self, db, runner: CliRunner):
        f = Failure(
            workspace_id="default",
            pattern="full_err",
            avoid_hint="do this instead",
            hint_quality="near_miss",
            q=0.75,
            times_seen=3,
            observed_error="ValueError: bad",
            likely_cause="wrong input",
            tags=["tag1"],
        )
        insert_failure(db, f)
        result = _invoke(runner, db, ["detail", "full_err"])
        assert result.exit_code == 0
        assert "full_err" in result.output
        assert "0.75" in result.output
        assert "ValueError: bad" in result.output
        assert "wrong input" in result.output

    def test_workspace_option(self, db, runner: CliRunner):
        insert_failure(db, _make_failure(ws="ws_detail", pattern="ws_err"))
        result = _invoke(runner, db, ["detail", "ws_err", "--workspace", "ws_detail"])
        assert result.exit_code == 0

    def test_wrong_workspace_not_found(self, db, runner: CliRunner):
        insert_failure(db, _make_failure(ws="proj_x", pattern="proj_x_err"))
        result = _invoke(runner, db, ["detail", "proj_x_err", "--workspace", "default"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# forge edit
# ---------------------------------------------------------------------------

class TestEdit:
    def test_edit_failure_hint(self, db, runner: CliRunner):
        fid = insert_failure(db, _make_failure(pattern="edit_err"))
        result = _invoke(runner, db, ["edit", str(fid), "--hint", "new hint"])
        assert result.exit_code == 0
        assert "updated" in result.output.lower()

    def test_edit_decision_rationale(self, db, runner: CliRunner):
        did = insert_decision(db, Decision(workspace_id="default", statement="Use X"))
        result = _invoke(runner, db, ["edit", str(did), "--rationale", "because X is better"])
        assert result.exit_code == 0
        assert "updated" in result.output.lower()

    def test_nonexistent_id(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["edit", "99999"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_edit_failure_no_hint_provided(self, db, runner: CliRunner):
        """hint 없이 호출하면 변경 없이 조용히 반환 (GAP: 피드백 없음)."""
        fid = insert_failure(db, _make_failure(pattern="no_hint_err"))
        result = _invoke(runner, db, ["edit", str(fid)])
        assert result.exit_code == 0

    def test_edit_updates_db_value(self, db, runner: CliRunner):
        """실제로 DB 값이 변경되는지 검증."""
        from forge.storage.queries import get_failure_by_pattern
        fid = insert_failure(db, _make_failure(pattern="db_update_err"))
        _invoke(runner, db, ["edit", str(fid), "--hint", "updated hint text"])
        row = db.execute("SELECT avoid_hint FROM failures WHERE id = ?", (fid,)).fetchone()
        assert row["avoid_hint"] == "updated hint text"


# ---------------------------------------------------------------------------
# forge promote
# ---------------------------------------------------------------------------

class TestPromote:
    def test_promote_to_global(self, db, runner: CliRunner):
        fid = insert_failure(db, _make_failure(pattern="promo_err"))
        result = _invoke(runner, db, ["promote", str(fid)])
        assert result.exit_code == 0
        assert "global" in result.output.lower()

    def test_promote_already_in_global(self, db, runner: CliRunner):
        fid = insert_failure(db, _make_failure(pattern="already_global"))
        # __global__ 워크스페이스에 동일 패턴 미리 추가
        insert_failure(db, _make_failure(ws="__global__", pattern="already_global"))
        result = _invoke(runner, db, ["promote", str(fid)])
        assert result.exit_code == 0
        assert "Already in __global__" in result.output

    def test_promote_to_knowledge(self, db, runner: CliRunner):
        fid = insert_failure(db, _make_failure(pattern="know_err"))
        result = _invoke(runner, db, ["promote", str(fid), "--to-knowledge"])
        assert result.exit_code == 0
        assert "knowledge" in result.output.lower()

    def test_promote_invalid_id(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["promote", "99999"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_promote_to_global_creates_global_entry(self, db, runner: CliRunner):
        """전역 승격 후 __global__ 워크스페이스에 패턴이 존재하는지 확인."""
        from forge.storage.queries import get_failure_by_pattern
        fid = insert_failure(db, _make_failure(pattern="new_global_err"))
        _invoke(runner, db, ["promote", str(fid)])
        global_entry = get_failure_by_pattern(db, "__global__", "new_global_err")
        assert global_entry is not None
        assert global_entry.workspace_id == "__global__"

    def test_promote_to_knowledge_creates_knowledge_entry(self, db, runner: CliRunner):
        """knowledge 승격 후 knowledge 테이블에 항목이 생성되는지 확인."""
        from forge.storage.queries import list_knowledge
        fid = insert_failure(db, _make_failure(pattern="know2_err"))
        _invoke(runner, db, ["promote", str(fid), "--to-knowledge"])
        knowledge_list = list_knowledge(db, "default", include_global=False)
        assert any(k.title == "know2_err" for k in knowledge_list)


# ---------------------------------------------------------------------------
# forge stats
# ---------------------------------------------------------------------------

class TestStats:
    def test_empty_db(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["stats"])
        assert result.exit_code == 0
        assert "Failures" in result.output
        assert "0" in result.output

    def test_with_failures(self, db, runner: CliRunner):
        insert_failure(db, _make_failure(pattern="s1", q=0.8))
        insert_failure(db, _make_failure(pattern="s2", q=0.4))
        result = _invoke(runner, db, ["stats"])
        assert result.exit_code == 0
        assert "Avg Q" in result.output
        assert "Top patterns" in result.output

    def test_with_all_types(self, db, runner: CliRunner):
        insert_failure(db, _make_failure(pattern="stat_f"))
        insert_decision(db, Decision(workspace_id="default", statement="D1"))
        insert_rule(db, Rule(workspace_id="default", rule_text="R1"))
        result = _invoke(runner, db, ["stats"])
        assert result.exit_code == 0
        assert "Decisions" in result.output
        assert "Rules" in result.output
        assert "Knowledge" in result.output

    def test_shows_workspace_name(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["stats", "--workspace", "myws"])
        assert result.exit_code == 0
        assert "myws" in result.output


# ---------------------------------------------------------------------------
# forge decay
# ---------------------------------------------------------------------------

class TestDecay:
    def test_empty_db(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["decay"])
        assert result.exit_code == 0
        assert "0" in result.output

    def test_dry_run_shows_preview(self, db, runner: CliRunner):
        stale_time = datetime.now(UTC) - timedelta(days=30)
        f = Failure(
            workspace_id="default",
            pattern="stale_err",
            avoid_hint="h",
            hint_quality="preventable",
            q=0.5,
            last_used=stale_time,
        )
        insert_failure(db, f)
        result = _invoke(runner, db, ["decay", "--dry-run"])
        assert result.exit_code == 0
        assert "Would update" in result.output
        assert "[DRY]" in result.output

    def test_decay_updates_stale_failure(self, db, runner: CliRunner):
        stale_time = datetime.now(UTC) - timedelta(days=10)
        f = Failure(
            workspace_id="default",
            pattern="stale_real",
            avoid_hint="h",
            hint_quality="preventable",
            q=0.5,
            last_used=stale_time,
        )
        insert_failure(db, f)
        result = _invoke(runner, db, ["decay"])
        assert result.exit_code == 0
        assert "Updated 1" in result.output

    def test_fresh_failure_not_decayed(self, db, runner: CliRunner):
        """last_used가 1일 미만이면 감쇠 대상 아님."""
        f = Failure(
            workspace_id="default",
            pattern="fresh_err",
            avoid_hint="h",
            hint_quality="preventable",
            q=0.5,
            last_used=datetime.now(UTC),
        )
        insert_failure(db, f)
        result = _invoke(runner, db, ["decay"])
        assert result.exit_code == 0
        assert "Updated 0" in result.output

    def test_no_last_used_skipped(self, db, runner: CliRunner):
        """last_used=None인 패턴은 감쇠 대상에서 제외."""
        f = _make_failure(pattern="no_last_used", q=0.5)
        insert_failure(db, f)
        result = _invoke(runner, db, ["decay"])
        assert result.exit_code == 0
        assert "Updated 0" in result.output

    def test_dry_run_does_not_update_db(self, db, runner: CliRunner):
        """--dry-run 실행 후 DB Q값 변경 없음."""
        from forge.storage.queries import get_failure_by_pattern
        stale_time = datetime.now(UTC) - timedelta(days=10)
        f = Failure(
            workspace_id="default",
            pattern="dry_check",
            avoid_hint="h",
            hint_quality="preventable",
            q=0.5,
            last_used=stale_time,
        )
        insert_failure(db, f)
        _invoke(runner, db, ["decay", "--dry-run"])
        unchanged = get_failure_by_pattern(db, "default", "dry_check")
        assert unchanged.q == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# forge resume
# ---------------------------------------------------------------------------

class TestResume:
    def test_missing_workspace(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["resume", "--session-id", "s1"])
        assert result.exit_code != 0

    def test_missing_session_id(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["resume", "--workspace", "ws"])
        assert result.exit_code != 0

    def test_resume_empty_db(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["resume", "--workspace", "ws1", "--session-id", "s1"])
        assert result.exit_code == 0

    def test_resume_with_failure_data(self, db, runner: CliRunner):
        insert_failure(db, _make_failure(ws="ws2", pattern="err1", q=0.7))
        result = _invoke(runner, db, ["resume", "--workspace", "ws2", "--session-id", "s2"])
        assert result.exit_code == 0
        assert "err1" in result.output

    def test_resume_creates_session(self, db, runner: CliRunner):
        from forge.storage.queries import get_session
        _invoke(runner, db, ["resume", "--workspace", "ws3", "--session-id", "sess-new"])
        session = get_session(db, "sess-new")
        assert session is not None
        assert session.session_id == "sess-new"


# ---------------------------------------------------------------------------
# forge writeback
# ---------------------------------------------------------------------------

class TestWriteback:
    def test_missing_workspace(self, db, runner: CliRunner):
        result = _invoke(runner, db, [
            "writeback", "--session-id", "s1", "--transcript", "/tmp/t.jsonl",
        ])
        assert result.exit_code != 0

    def test_missing_session_id(self, db, runner: CliRunner):
        result = _invoke(runner, db, [
            "writeback", "--workspace", "ws", "--transcript", "/tmp/t.jsonl",
        ])
        assert result.exit_code != 0

    def test_missing_transcript_arg(self, db, runner: CliRunner):
        result = _invoke(runner, db, [
            "writeback", "--workspace", "ws", "--session-id", "s1",
        ])
        assert result.exit_code != 0

    def test_writeback_nonexistent_transcript(self, db, runner: CliRunner, tmp_path):
        """transcript 파일 없어도 graceful 완료."""
        missing = str(tmp_path / "missing.jsonl")
        insert_session(db, Session(session_id="wb-s1", workspace_id="ws1"))
        result = _invoke(runner, db, [
            "writeback",
            "--workspace", "ws1",
            "--session-id", "wb-s1",
            "--transcript", missing,
        ])
        assert result.exit_code == 0
        assert "Writeback complete" in result.output

    def test_writeback_empty_transcript(self, db, runner: CliRunner, tmp_path):
        transcript = tmp_path / "empty.jsonl"
        transcript.write_text("")
        insert_session(db, Session(session_id="wb-s2", workspace_id="ws2"))
        result = _invoke(runner, db, [
            "writeback",
            "--workspace", "ws2",
            "--session-id", "wb-s2",
            "--transcript", str(transcript),
        ])
        assert result.exit_code == 0
        assert "Writeback complete" in result.output

    def test_writeback_with_bash_failure(self, db, runner: CliRunner, tmp_path):
        """실패가 있는 transcript → 패턴 자동 생성."""
        from forge.storage.queries import list_failures
        lines = [
            {"tool_name": "Bash", "exit_code": 1,
             "stderr": "ModuleNotFoundError: No module named 'requests'",
             "stdout": "", "command": "python run.py"},
        ]
        transcript = tmp_path / "t.jsonl"
        transcript.write_text("\n".join(json.dumps(l) for l in lines))
        insert_session(db, Session(session_id="wb-s3", workspace_id="ws3"))
        result = _invoke(runner, db, [
            "writeback",
            "--workspace", "ws3",
            "--session-id", "wb-s3",
            "--transcript", str(transcript),
        ])
        assert result.exit_code == 0
        failures = list_failures(db, "ws3", include_global=False)
        assert any("requests" in f.pattern for f in failures)


# ---------------------------------------------------------------------------
# forge detect
# ---------------------------------------------------------------------------

class TestDetect:
    def test_bash_failure_with_match(self, db, runner: CliRunner):
        insert_failure(db, _make_failure(
            pattern="value_error",
            ws="ws_detect",
            avoid_hint="check input types",
        ))
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_response": {
                "exit_code": 1,
                "stderr": "ValueError: invalid literal",
            },
        })
        result = _invoke(runner, db, ["detect", "--workspace", "ws_detect"], stdin=payload)
        assert result.exit_code == 0
        assert result.output.strip(), "매치된 실패에 대해 JSON 출력 예상"
        data = json.loads(result.output.strip())
        assert "hookSpecificOutput" in data

    def test_non_bash_tool_no_output(self, db, runner: CliRunner):
        payload = json.dumps({"tool_name": "Read", "tool_response": {}})
        result = _invoke(runner, db, ["detect", "--workspace", "ws_detect"], stdin=payload)
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_exit_code_zero_no_output(self, db, runner: CliRunner):
        """exit_code=0이면 탐지하지 않음."""
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_response": {"exit_code": 0, "stderr": "ValueError: x"},
        })
        result = _invoke(runner, db, ["detect", "--workspace", "ws_detect"], stdin=payload)
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_invalid_json_silently_ignored(self, db, runner: CliRunner):
        result = _invoke(runner, db, ["detect", "--workspace", "ws_detect"], stdin="{not json}")
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_no_pattern_match_no_output(self, db, runner: CliRunner):
        """DB에 패턴 없으면 출력 없음."""
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_response": {"exit_code": 1, "stderr": "some unknown xyzzy error"},
        })
        result = _invoke(runner, db, ["detect", "--workspace", "ws_detect"], stdin=payload)
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_output_contains_avoid_hint(self, db, runner: CliRunner):
        """매치 결과에 avoid_hint가 포함되어 있는지 확인."""
        insert_failure(db, _make_failure(
            pattern="value_error",
            ws="ws_hint",
            avoid_hint="never pass raw user input",
        ))
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_response": {"exit_code": 1, "stderr": "ValueError: bad value"},
        })
        result = _invoke(runner, db, ["detect", "--workspace", "ws_hint"], stdin=payload)
        assert result.exit_code == 0
        assert "never pass raw user input" in result.output


# ---------------------------------------------------------------------------
# forge install-hooks
# ---------------------------------------------------------------------------

class TestInstallHooks:
    def test_install_hooks_success(self, runner: CliRunner):
        with patch("forge.hooks.install.install_hooks") as mock_install:
            result = runner.invoke(app, ["install-hooks"])
        assert result.exit_code == 0
        assert "Hooks installed" in result.output
        mock_install.assert_called_once()

    def test_install_hooks_called_once(self, runner: CliRunner):
        """install_hooks가 정확히 한 번 호출되는지 확인."""
        with patch("forge.hooks.install.install_hooks") as mock_install:
            runner.invoke(app, ["install-hooks"])
            runner.invoke(app, ["install-hooks"])
        assert mock_install.call_count == 2
