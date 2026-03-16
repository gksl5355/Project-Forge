"""engines 레이어 엣지 케이스 테스트.

각 테스트는 하나의 엣지 케이스만 검증한다.

커버리지:
- transcript: empty, missing, whitespace, malformed JSON, Claude Code/flat/nested format,
              non-Bash tools, exit_code=0, missing command, tool key variants
- writeback:  empty transcript, no stderr, Q EMA math, decay, decay floor, session absent,
              promotion (global/knowledge), no duplicate global, transaction rollback,
              session tracking, review_flag
- resume:     empty DB, deduplication, decisions/knowledge, session recording
- detect:     non-Bash, exit_code=0, invalid exit_code, matching, no match,
              Q value in output, empty stderr
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.config import ForgeConfig
from forge.engines.detect import run_detect
from forge.engines.resume import run_resume
from forge.engines.transcript import BashFailure, parse_transcript
from forge.engines.writeback import run_writeback
from forge.storage.models import Decision, Failure, Knowledge, Rule, Session
from forge.storage.queries import (
    get_failure_by_pattern,
    get_session,
    insert_decision,
    insert_failure,
    insert_knowledge,
    insert_rule,
    insert_session,
    list_failures,
    list_knowledge,
)


@pytest.fixture
def config() -> ForgeConfig:
    return ForgeConfig()


# ============================================================================
# Transcript
# ============================================================================


class TestTranscriptEmptyAndMissing:
    def test_empty_file_returns_empty_list(self, tmp_path: Path) -> None:
        """빈 파일 → []."""
        p = tmp_path / "empty.jsonl"
        p.write_text("", encoding="utf-8")
        assert parse_transcript(p) == []

    def test_missing_file_returns_empty_list(self, tmp_path: Path) -> None:
        """파일 없음 → []."""
        p = tmp_path / "nonexistent.jsonl"
        assert parse_transcript(p) == []

    def test_whitespace_only_returns_empty_list(self, tmp_path: Path) -> None:
        """공백만 있는 파일 → []."""
        p = tmp_path / "ws.jsonl"
        p.write_text("   \n\t\n  ", encoding="utf-8")
        assert parse_transcript(p) == []

    def test_malformed_json_line_skipped(self, tmp_path: Path) -> None:
        """잘못된 JSON 줄은 건너뛰고 유효한 줄만 처리."""
        lines = [
            '{"tool_name":"Bash","exit_code":1,"stderr":"ValueError: x","stdout":"","command":"py"}',
            "{bad json}",
            '{"tool_name":"Bash","exit_code":0,"stderr":"","stdout":"ok","command":"ls"}',
        ]
        p = tmp_path / "mixed.jsonl"
        p.write_text("\n".join(lines), encoding="utf-8")
        results = parse_transcript(p)
        assert len(results) == 1
        assert results[0].exit_code == 1

    def test_all_malformed_lines_returns_empty(self, tmp_path: Path) -> None:
        """모든 줄이 malformed → []."""
        p = tmp_path / "bad.jsonl"
        p.write_text("{bad}\nnot json\n{also}", encoding="utf-8")
        assert parse_transcript(p) == []


class TestTranscriptFormats:
    def test_flat_format_bash_failure(self, tmp_path: Path) -> None:
        """직접 키를 가진 flat format 파싱."""
        line = {
            "tool_name": "Bash",
            "command": "python run.py",
            "exit_code": 1,
            "stdout": "",
            "stderr": "SomeError: oops",
        }
        p = tmp_path / "flat.jsonl"
        p.write_text(json.dumps(line), encoding="utf-8")
        results = parse_transcript(p)
        assert len(results) == 1
        assert results[0].command == "python run.py"
        assert results[0].stderr == "SomeError: oops"
        assert results[0].exit_code == 1

    def test_nested_result_format(self, tmp_path: Path) -> None:
        """exit_code/stderr가 'result' 하위 dict에 있는 nested format."""
        line = {
            "tool_name": "Bash",
            "command": "pytest",
            "result": {"exit_code": 2, "stdout": "", "stderr": "FAILED: test_foo"},
        }
        p = tmp_path / "nested.jsonl"
        p.write_text(json.dumps(line), encoding="utf-8")
        results = parse_transcript(p)
        assert len(results) == 1
        assert results[0].exit_code == 2
        assert "FAILED" in results[0].stderr

    def test_claude_code_content_list_format(self, tmp_path: Path) -> None:
        """Claude Code transcript 형식: content list with text."""
        line = {
            "tool_name": "Bash",
            "input": {"command": "python run.py"},
            "content": [
                {
                    "type": "text",
                    "text": "Exit code: 1\nstderr: ModuleNotFoundError: No module named 'foo'",
                }
            ],
        }
        p = tmp_path / "cc.jsonl"
        p.write_text(json.dumps(line), encoding="utf-8")
        results = parse_transcript(p)
        assert len(results) == 1
        assert results[0].exit_code == 1
        assert "ModuleNotFoundError" in results[0].stderr

    def test_claude_code_format_extracts_input_command(self, tmp_path: Path) -> None:
        """Claude Code 형식에서 input.command 추출."""
        line = {
            "tool_name": "Bash",
            "input": {"command": "npm test"},
            "content": [{"type": "text", "text": "Exit code: 1\nstderr: Error: test failed"}],
        }
        p = tmp_path / "cc_cmd.jsonl"
        p.write_text(json.dumps(line), encoding="utf-8")
        results = parse_transcript(p)
        assert len(results) == 1
        assert results[0].command == "npm test"

    def test_claude_code_format_exit_code_zero_filtered(self, tmp_path: Path) -> None:
        """Claude Code 형식에서 exit_code=0이면 실패 아님."""
        line = {
            "tool_name": "Bash",
            "input": {"command": "ls"},
            "content": [{"type": "text", "text": "Exit code: 0\nstdout: file.py"}],
        }
        p = tmp_path / "cc_zero.jsonl"
        p.write_text(json.dumps(line), encoding="utf-8")
        assert parse_transcript(p) == []

    def test_non_bash_tool_filtered(self, tmp_path: Path) -> None:
        """Bash가 아닌 tool은 무시."""
        lines = [
            {"tool_name": "Read", "exit_code": 1, "stderr": "File not found", "command": "cat x"},
            {
                "tool_name": "Bash",
                "exit_code": 1,
                "stderr": "ImportError: missing",
                "command": "py",
                "stdout": "",
            },
        ]
        p = tmp_path / "multi_tool.jsonl"
        p.write_text("\n".join(json.dumps(l) for l in lines), encoding="utf-8")
        results = parse_transcript(p)
        assert len(results) == 1
        assert "ImportError" in results[0].stderr

    def test_exit_code_zero_filtered(self, tmp_path: Path) -> None:
        """exit_code=0은 실패로 처리하지 않음."""
        line = {"tool_name": "Bash", "command": "ls", "exit_code": 0, "stdout": ".", "stderr": ""}
        p = tmp_path / "success.jsonl"
        p.write_text(json.dumps(line), encoding="utf-8")
        assert parse_transcript(p) == []

    def test_missing_command_returns_empty_string(self, tmp_path: Path) -> None:
        """command 키 없으면 빈 문자열."""
        line = {"tool_name": "Bash", "exit_code": 1, "stderr": "ValueError: x", "stdout": ""}
        p = tmp_path / "no_cmd.jsonl"
        p.write_text(json.dumps(line), encoding="utf-8")
        results = parse_transcript(p)
        assert len(results) == 1
        assert results[0].command == ""

    def test_tool_key_recognized_as_bash(self, tmp_path: Path) -> None:
        """'tool_name' 대신 'tool' 키도 지원."""
        line = {"tool": "Bash", "command": "py", "exit_code": 1, "stderr": "RuntimeError: crash", "stdout": ""}
        p = tmp_path / "tool_key.jsonl"
        p.write_text(json.dumps(line), encoding="utf-8")
        results = parse_transcript(p)
        assert len(results) == 1

    def test_tool_name_case_insensitive(self, tmp_path: Path) -> None:
        """'BASH'도 Bash로 처리."""
        line = {"tool_name": "BASH", "command": "py", "exit_code": 1, "stderr": "KeyError: 'x'", "stdout": ""}
        p = tmp_path / "upper.jsonl"
        p.write_text(json.dumps(line), encoding="utf-8")
        results = parse_transcript(p)
        assert len(results) == 1


# ============================================================================
# Writeback
# ============================================================================


class TestWritebackEmptyTranscript:
    def test_success_only_transcript_creates_no_patterns(
        self, db, config: ForgeConfig, tmp_path: Path
    ) -> None:
        """성공만 있는 transcript → 패턴 생성 없음."""
        p = tmp_path / "ok.jsonl"
        p.write_text(
            json.dumps({"tool_name": "Bash", "command": "ls", "exit_code": 0, "stdout": ".", "stderr": ""}),
            encoding="utf-8",
        )
        session = Session(session_id="sess-ew1", workspace_id="ws_ew1", warnings_injected=[])
        insert_session(db, session)
        run_writeback("ws_ew1", "sess-ew1", p, db, config)
        assert list_failures(db, "ws_ew1", include_global=False) == []

    def test_missing_transcript_no_exception(self, db, config: ForgeConfig, tmp_path: Path) -> None:
        """존재하지 않는 transcript → 예외 없이 처리."""
        p = tmp_path / "nonexistent.jsonl"
        session = Session(session_id="sess-mw1", workspace_id="ws_mw1", warnings_injected=[])
        insert_session(db, session)
        run_writeback("ws_mw1", "sess-mw1", p, db, config)
        assert list_failures(db, "ws_mw1", include_global=False) == []

    def test_failure_with_empty_stderr_not_inserted(
        self, db, config: ForgeConfig, tmp_path: Path
    ) -> None:
        """stderr 없는 Bash 실패 → 패턴 생성 안 함."""
        p = tmp_path / "no_stderr.jsonl"
        p.write_text(
            json.dumps({"tool_name": "Bash", "command": "py", "exit_code": 1, "stdout": "out", "stderr": ""}),
            encoding="utf-8",
        )
        session = Session(session_id="sess-ns1", workspace_id="ws_ns1", warnings_injected=[])
        insert_session(db, session)
        run_writeback("ws_ns1", "sess-ns1", p, db, config)
        assert list_failures(db, "ws_ns1", include_global=False) == []


class TestWritebackQMath:
    def _success_transcript(self, tmp_path: Path) -> Path:
        p = tmp_path / "ok.jsonl"
        p.write_text(
            json.dumps({"tool_name": "Bash", "command": "ls", "exit_code": 0, "stdout": ".", "stderr": ""}),
            encoding="utf-8",
        )
        return p

    def test_ema_reward_1_when_warning_not_triggered(
        self, db, config: ForgeConfig, tmp_path: Path
    ) -> None:
        """경고 후 실패 미발생 → Q ← Q + α(1 - Q)."""
        f = Failure(
            workspace_id="ws_q1",
            pattern="value_error",
            avoid_hint="avoid value error",
            hint_quality="near_miss",
            q=0.5,
        )
        insert_failure(db, f)
        p = self._success_transcript(tmp_path)
        session = Session(
            session_id="sess-q1", workspace_id="ws_q1", warnings_injected=["value_error"]
        )
        insert_session(db, session)
        run_writeback("ws_q1", "sess-q1", p, db, config)
        updated = get_failure_by_pattern(db, "ws_q1", "value_error")
        expected = 0.5 + config.alpha * (1.0 - 0.5)
        assert abs(updated.q - expected) < 1e-9

    def test_ema_reward_0_when_warning_triggered(
        self, db, config: ForgeConfig, tmp_path: Path
    ) -> None:
        """경고 후 실패 발생 → Q ← Q + α(0 - Q)."""
        f = Failure(
            workspace_id="ws_q2",
            pattern="value_error",
            avoid_hint="avoid value error",
            hint_quality="near_miss",
            q=0.5,
        )
        insert_failure(db, f)
        p = tmp_path / "fail.jsonl"
        p.write_text(
            json.dumps(
                {
                    "tool_name": "Bash",
                    "command": "py",
                    "exit_code": 1,
                    "stderr": "ValueError: invalid literal for int()",
                    "stdout": "",
                }
            ),
            encoding="utf-8",
        )
        session = Session(
            session_id="sess-q2", workspace_id="ws_q2", warnings_injected=["value_error"]
        )
        insert_session(db, session)
        run_writeback("ws_q2", "sess-q2", p, db, config)
        updated = get_failure_by_pattern(db, "ws_q2", "value_error")
        expected = 0.5 + config.alpha * (0.0 - 0.5)
        assert abs(updated.q - expected) < 1e-9

    def test_no_q_update_when_no_session_exists(
        self, db, config: ForgeConfig, tmp_path: Path
    ) -> None:
        """세션이 없으면 Q 업데이트 없음 (session 없이 run_writeback 호출)."""
        f = Failure(
            workspace_id="ws_q3",
            pattern="value_error",
            avoid_hint="avoid",
            hint_quality="near_miss",
            q=0.5,
        )
        insert_failure(db, f)
        p = self._success_transcript(tmp_path)
        # session NOT inserted
        run_writeback("ws_q3", "sess-q3-absent", p, db, config)
        updated = get_failure_by_pattern(db, "ws_q3", "value_error")
        # decay skipped (last_used=None); no session → no Q update
        assert abs(updated.q - 0.5) < 1e-9

    def test_times_warned_and_helped_incremented(
        self, db, config: ForgeConfig, tmp_path: Path
    ) -> None:
        """경고 후 미발생 → times_warned=1, times_helped=1."""
        f = Failure(
            workspace_id="ws_q4",
            pattern="value_error",
            avoid_hint="hint",
            hint_quality="near_miss",
            q=0.5,
        )
        insert_failure(db, f)
        p = self._success_transcript(tmp_path)
        session = Session(
            session_id="sess-q4", workspace_id="ws_q4", warnings_injected=["value_error"]
        )
        insert_session(db, session)
        run_writeback("ws_q4", "sess-q4", p, db, config)
        updated = get_failure_by_pattern(db, "ws_q4", "value_error")
        assert updated.times_warned == 1
        assert updated.times_helped == 1

    def test_review_flag_set_when_warning_did_not_help(
        self, db, config: ForgeConfig, tmp_path: Path
    ) -> None:
        """경고했지만 실패 발생 → review_flag=True."""
        f = Failure(
            workspace_id="ws_rf",
            pattern="value_error",
            avoid_hint="avoid value error",
            hint_quality="near_miss",
            q=0.5,
        )
        insert_failure(db, f)
        p = tmp_path / "fail.jsonl"
        p.write_text(
            json.dumps(
                {"tool_name": "Bash", "command": "py", "exit_code": 1,
                 "stderr": "ValueError: bad input", "stdout": ""}
            ),
            encoding="utf-8",
        )
        session = Session(
            session_id="sess-rf", workspace_id="ws_rf", warnings_injected=["value_error"]
        )
        insert_session(db, session)
        run_writeback("ws_rf", "sess-rf", p, db, config)
        updated = get_failure_by_pattern(db, "ws_rf", "value_error")
        assert updated.review_flag is True

    def test_times_seen_incremented_on_rematch(
        self, db, config: ForgeConfig, tmp_path: Path
    ) -> None:
        """기존 패턴과 매칭 시 times_seen 증가."""
        f = Failure(
            workspace_id="ws_ts",
            pattern="value_error",
            avoid_hint="avoid",
            hint_quality="near_miss",
            q=0.5,
            times_seen=1,
        )
        insert_failure(db, f)
        p = tmp_path / "fail.jsonl"
        p.write_text(
            json.dumps(
                {"tool_name": "Bash", "command": "py", "exit_code": 1,
                 "stderr": "ValueError: bad input", "stdout": ""}
            ),
            encoding="utf-8",
        )
        session = Session(session_id="sess-ts", workspace_id="ws_ts", warnings_injected=[])
        insert_session(db, session)
        run_writeback("ws_ts", "sess-ts", p, db, config)
        updated = get_failure_by_pattern(db, "ws_ts", "value_error")
        assert updated.times_seen > 1


class TestWritebackDecay:
    def _success_transcript(self, tmp_path: Path) -> Path:
        p = tmp_path / "ok.jsonl"
        p.write_text(
            json.dumps({"tool_name": "Bash", "command": "ls", "exit_code": 0, "stdout": ".", "stderr": ""}),
            encoding="utf-8",
        )
        return p

    def test_decay_applied_to_stale_failure(
        self, db, config: ForgeConfig, tmp_path: Path
    ) -> None:
        """1일 이상 지난 failure의 Q가 감쇠됨."""
        old_date = datetime.now(UTC) - timedelta(days=10)
        f = Failure(
            workspace_id="ws_dec",
            pattern="stale_error",
            avoid_hint="avoid stale",
            hint_quality="preventable",
            q=0.5,
            last_used=old_date,
        )
        insert_failure(db, f)
        p = self._success_transcript(tmp_path)
        session = Session(session_id="sess-dec", workspace_id="ws_dec", warnings_injected=[])
        insert_session(db, session)
        run_writeback("ws_dec", "sess-dec", p, db, config)
        updated = get_failure_by_pattern(db, "ws_dec", "stale_error")
        assert updated.q < 0.5

    def test_no_decay_for_recent_failure(
        self, db, config: ForgeConfig, tmp_path: Path
    ) -> None:
        """최근(오늘) failure는 감쇠되지 않음."""
        f = Failure(
            workspace_id="ws_nodec",
            pattern="fresh_error",
            avoid_hint="avoid fresh",
            hint_quality="preventable",
            q=0.5,
            last_used=datetime.now(UTC),
        )
        insert_failure(db, f)
        p = self._success_transcript(tmp_path)
        session = Session(session_id="sess-nodec", workspace_id="ws_nodec", warnings_injected=[])
        insert_session(db, session)
        run_writeback("ws_nodec", "sess-nodec", p, db, config)
        updated = get_failure_by_pattern(db, "ws_nodec", "fresh_error")
        assert abs(updated.q - 0.5) < 1e-9

    def test_q_never_falls_below_q_min(
        self, db, config: ForgeConfig, tmp_path: Path
    ) -> None:
        """감쇠 후 Q는 q_min 이하로 내려가지 않음."""
        old_date = datetime.now(UTC) - timedelta(days=1000)
        f = Failure(
            workspace_id="ws_qmin",
            pattern="very_old_error",
            avoid_hint="avoid",
            hint_quality="preventable",
            q=0.1,  # low starting Q
            last_used=old_date,
        )
        insert_failure(db, f)
        p = self._success_transcript(tmp_path)
        session = Session(session_id="sess-qmin", workspace_id="ws_qmin", warnings_injected=[])
        insert_session(db, session)
        run_writeback("ws_qmin", "sess-qmin", p, db, config)
        updated = get_failure_by_pattern(db, "ws_qmin", "very_old_error")
        assert updated.q >= config.q_min


class TestWritebackPromotion:
    def _success_transcript(self, tmp_path: Path) -> Path:
        p = tmp_path / "ok.jsonl"
        p.write_text(
            json.dumps({"tool_name": "Bash", "command": "ls", "exit_code": 0, "stdout": ".", "stderr": ""}),
            encoding="utf-8",
        )
        return p

    def test_global_promotion_when_projects_seen_at_threshold(
        self, db, config: ForgeConfig, tmp_path: Path
    ) -> None:
        """projects_seen >= promote_threshold → __global__ 복사본 생성."""
        f = Failure(
            workspace_id="ws_promo",
            pattern="known_error",
            avoid_hint="avoid this",
            hint_quality="preventable",
            q=0.5,
            projects_seen=["proj1", "proj2"],  # >= 2
        )
        insert_failure(db, f)
        p = self._success_transcript(tmp_path)
        session = Session(session_id="sess-promo", workspace_id="ws_promo", warnings_injected=[])
        insert_session(db, session)
        run_writeback("ws_promo", "sess-promo", p, db, config)
        global_f = get_failure_by_pattern(db, "__global__", "known_error")
        assert global_f is not None

    def test_no_global_promotion_below_threshold(
        self, db, config: ForgeConfig, tmp_path: Path
    ) -> None:
        """projects_seen < promote_threshold → 전역 승격 없음."""
        f = Failure(
            workspace_id="ws_nopromo",
            pattern="local_only_error",
            avoid_hint="avoid this",
            hint_quality="preventable",
            q=0.5,
            projects_seen=["proj1"],  # 1 < 2
        )
        insert_failure(db, f)
        p = self._success_transcript(tmp_path)
        session = Session(session_id="sess-nopromo", workspace_id="ws_nopromo", warnings_injected=[])
        insert_session(db, session)
        run_writeback("ws_nopromo", "sess-nopromo", p, db, config)
        assert get_failure_by_pattern(db, "__global__", "local_only_error") is None

    def test_no_duplicate_global_promotion(
        self, db, config: ForgeConfig, tmp_path: Path
    ) -> None:
        """이미 __global__에 있으면 중복 생성 안 함."""
        insert_failure(
            db,
            Failure(
                workspace_id="ws_dup",
                pattern="dup_pattern",
                avoid_hint="avoid",
                hint_quality="preventable",
                q=0.5,
                projects_seen=["p1", "p2"],
            ),
        )
        insert_failure(
            db,
            Failure(
                workspace_id="__global__",
                pattern="dup_pattern",
                avoid_hint="global hint",
                hint_quality="preventable",
                q=0.7,
            ),
        )
        p = self._success_transcript(tmp_path)
        session = Session(session_id="sess-dup", workspace_id="ws_dup", warnings_injected=[])
        insert_session(db, session)
        run_writeback("ws_dup", "sess-dup", p, db, config)
        cnt = db.execute(
            "SELECT COUNT(*) as c FROM failures WHERE workspace_id='__global__' AND pattern='dup_pattern'"
        ).fetchone()["c"]
        assert cnt == 1

    def test_knowledge_promotion_at_threshold(
        self, db, config: ForgeConfig, tmp_path: Path
    ) -> None:
        """q >= knowledge_promote_q AND times_helped >= knowledge_promote_helped → knowledge 생성."""
        f = Failure(
            workspace_id="ws_kprom",
            pattern="high_q_error",
            avoid_hint="very helpful hint",
            hint_quality="near_miss",
            q=config.knowledge_promote_q + 0.05,
            times_helped=config.knowledge_promote_helped,
        )
        insert_failure(db, f)
        p = self._success_transcript(tmp_path)
        session = Session(session_id="sess-kprom", workspace_id="ws_kprom", warnings_injected=[])
        insert_session(db, session)
        run_writeback("ws_kprom", "sess-kprom", p, db, config)
        knowledge = list_knowledge(db, "ws_kprom", include_global=False)
        assert any(k.title == "high_q_error" for k in knowledge)


class TestWritebackTransaction:
    def test_rollback_on_exception_reverts_all_inserts(
        self, db, config: ForgeConfig, tmp_path: Path
    ) -> None:
        """예외 발생 시 전체 writeback이 롤백됨 (단일 트랜잭션)."""
        p = tmp_path / "fail.jsonl"
        p.write_text(
            json.dumps(
                {"tool_name": "Bash", "command": "py", "exit_code": 1,
                 "stderr": "RuntimeError: crash", "stdout": ""}
            ),
            encoding="utf-8",
        )
        session = Session(session_id="sess-rb", workspace_id="ws_rb", warnings_injected=[])
        insert_session(db, session)
        with patch(
            "forge.engines.writeback.update_session_metrics",
            side_effect=RuntimeError("forced failure"),
        ):
            with pytest.raises(RuntimeError, match="forced failure"):
                run_writeback("ws_rb", "sess-rb", p, db, config)
        # Failures inserted via proxy should have been rolled back
        assert list_failures(db, "ws_rb", include_global=False) == []


class TestWritebackSessionTracking:
    def test_session_ended_at_set_after_writeback(
        self, db, config: ForgeConfig, tmp_path: Path
    ) -> None:
        """writeback 완료 후 session.ended_at이 설정됨."""
        p = tmp_path / "ok.jsonl"
        p.write_text(
            json.dumps({"tool_name": "Bash", "command": "ls", "exit_code": 0, "stdout": ".", "stderr": ""}),
            encoding="utf-8",
        )
        session = Session(session_id="sess-end", workspace_id="ws_end", warnings_injected=[])
        insert_session(db, session)
        run_writeback("ws_end", "sess-end", p, db, config)
        sess = get_session(db, "sess-end")
        assert sess.ended_at is not None


# ============================================================================
# Resume
# ============================================================================


class TestResumeEmptyDb:
    def test_returns_string_on_empty_db(self, db, config: ForgeConfig) -> None:
        ctx = run_resume("ws_re1", "sess-re1", db, config)
        assert isinstance(ctx, str)

    def test_session_inserted_on_resume(self, db, config: ForgeConfig) -> None:
        run_resume("ws_re2", "sess-re2", db, config)
        sess = get_session(db, "sess-re2")
        assert sess is not None
        assert sess.workspace_id == "ws_re2"

    def test_warnings_injected_empty_when_no_failures(self, db, config: ForgeConfig) -> None:
        run_resume("ws_re3", "sess-re3", db, config)
        sess = get_session(db, "sess-re3")
        assert sess.warnings_injected == []


class TestResumeDeduplication:
    def test_project_local_preferred_over_global(self, db, config: ForgeConfig) -> None:
        """동일 pattern: 프로젝트 로컬 avoid_hint가 context에 포함됨."""
        insert_failure(
            db,
            Failure(
                workspace_id="__global__",
                pattern="dedup_pattern",
                avoid_hint="global hint",
                hint_quality="preventable",
                q=0.3,
            ),
        )
        insert_failure(
            db,
            Failure(
                workspace_id="ws_dedup",
                pattern="dedup_pattern",
                avoid_hint="local hint",
                hint_quality="near_miss",
                q=0.8,
            ),
        )
        ctx = run_resume("ws_dedup", "sess-dedup", db, config)
        assert "local hint" in ctx

    def test_global_hint_excluded_when_local_exists(
        self, db, config: ForgeConfig
    ) -> None:
        """동일 pattern에 로컬이 있으면 global avoid_hint는 context에 나타나지 않음."""
        insert_failure(
            db,
            Failure(
                workspace_id="__global__",
                pattern="once_pattern",
                avoid_hint="global hint only",
                hint_quality="preventable",
                q=0.3,
            ),
        )
        insert_failure(
            db,
            Failure(
                workspace_id="ws_once",
                pattern="once_pattern",
                avoid_hint="local hint only",
                hint_quality="near_miss",
                q=0.8,
            ),
        )
        ctx = run_resume("ws_once", "sess-once", db, config)
        assert "local hint only" in ctx
        assert "global hint only" not in ctx

    def test_global_failure_included_when_no_local(self, db, config: ForgeConfig) -> None:
        """로컬에 없는 __global__ 패턴도 context에 포함."""
        insert_failure(
            db,
            Failure(
                workspace_id="__global__",
                pattern="global_only",
                avoid_hint="global hint",
                hint_quality="preventable",
                q=0.7,
            ),
        )
        ctx = run_resume("ws_gonly", "sess-gonly", db, config)
        assert "global_only" in ctx


class TestResumeDecisionsAndKnowledge:
    def test_active_decision_in_context(self, db, config: ForgeConfig) -> None:
        insert_decision(
            db,
            Decision(
                workspace_id="ws_da",
                statement="Use SQLite for all storage",
                q=0.7,
                status="active",
            ),
        )
        ctx = run_resume("ws_da", "sess-da", db, config)
        assert "Use SQLite for all storage" in ctx

    def test_superseded_decision_not_in_context(self, db, config: ForgeConfig) -> None:
        insert_decision(
            db,
            Decision(
                workspace_id="ws_ds",
                statement="Old approach",
                q=0.3,
                status="superseded",
            ),
        )
        ctx = run_resume("ws_ds", "sess-ds", db, config)
        assert "Old approach" not in ctx

    def test_knowledge_in_context(self, db, config: ForgeConfig) -> None:
        insert_knowledge(
            db,
            Knowledge(
                workspace_id="ws_kn",
                title="Important Tip",
                content="Always check imports",
                q=0.7,
            ),
        )
        ctx = run_resume("ws_kn", "sess-kn", db, config)
        assert "Important Tip" in ctx

    def test_global_knowledge_included(self, db, config: ForgeConfig) -> None:
        insert_knowledge(
            db,
            Knowledge(
                workspace_id="__global__",
                title="Global Tip",
                content="Always do X",
                q=0.7,
            ),
        )
        ctx = run_resume("ws_gk", "sess-gk", db, config)
        assert "Global Tip" in ctx

    def test_knowledge_deduplication_prefers_local(self, db, config: ForgeConfig) -> None:
        """동일 title knowledge: 프로젝트 로컬이 우선."""
        insert_knowledge(
            db,
            Knowledge(
                workspace_id="__global__",
                title="Shared Tip",
                content="global content",
                q=0.5,
            ),
        )
        insert_knowledge(
            db,
            Knowledge(
                workspace_id="ws_kdup",
                title="Shared Tip",
                content="local content",
                q=0.6,
            ),
        )
        ctx = run_resume("ws_kdup", "sess-kdup", db, config)
        assert ctx.count("Shared Tip") == 1

    def test_warnings_injected_contains_all_failure_patterns(
        self, db, config: ForgeConfig
    ) -> None:
        """run_resume 후 session.warnings_injected에 모든 패턴 기록."""
        for pat in ("runtime_error", "value_error"):
            insert_failure(
                db,
                Failure(
                    workspace_id="ws_wi",
                    pattern=pat,
                    avoid_hint=f"avoid {pat}",
                    hint_quality="near_miss",
                    q=0.6,
                ),
            )
        run_resume("ws_wi", "sess-wi", db, config)
        sess = get_session(db, "sess-wi")
        assert "runtime_error" in sess.warnings_injected
        assert "value_error" in sess.warnings_injected


# ============================================================================
# Detect
# ============================================================================


class TestDetect:
    def test_non_bash_tool_returns_none(self, db) -> None:
        result = run_detect("Read", {"exit_code": 1, "stderr": "Error"}, "ws_dt1", db)
        assert result is None

    def test_non_bash_tool_edit_returns_none(self, db) -> None:
        result = run_detect("Edit", {"exit_code": 1, "stderr": "Error"}, "ws_dt1b", db)
        assert result is None

    def test_exit_code_zero_returns_none(self, db) -> None:
        result = run_detect("Bash", {"exit_code": 0, "stderr": "some error"}, "ws_dt2", db)
        assert result is None

    def test_invalid_string_exit_code_treated_as_zero(self, db) -> None:
        """exit_code가 int 변환 불가 문자열 → 0으로 처리 → None."""
        result = run_detect("Bash", {"exit_code": "invalid", "stderr": "some error"}, "ws_dt3", db)
        assert result is None

    def test_missing_exit_code_key_defaults_to_zero(self, db) -> None:
        """exit_code 키 없으면 기본값 0 → None."""
        result = run_detect("Bash", {"stderr": "ValueError: x"}, "ws_dt4", db)
        assert result is None

    def test_no_matching_pattern_returns_none(self, db) -> None:
        """DB에 패턴 없으면 None."""
        result = run_detect("Bash", {"exit_code": 1, "stderr": "some obscure error xyz"}, "ws_dt5", db)
        assert result is None

    def test_matching_pattern_returns_hook_specific_output(self, db) -> None:
        """패턴 매칭 시 hookSpecificOutput 반환."""
        insert_failure(
            db,
            Failure(
                workspace_id="ws_dt6",
                pattern="value_error",
                avoid_hint="don't pass invalid values",
                hint_quality="near_miss",
                q=0.7,
            ),
        )
        result = run_detect(
            "Bash",
            {"exit_code": 1, "stderr": "ValueError: invalid input"},
            "ws_dt6",
            db,
        )
        assert result is not None
        assert "hookSpecificOutput" in result
        assert result["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
        assert "value_error" in result["hookSpecificOutput"]["additionalContext"]

    def test_matching_output_contains_q_value(self, db) -> None:
        """hookSpecificOutput additionalContext에 Q 값 포함."""
        insert_failure(
            db,
            Failure(
                workspace_id="ws_dt7",
                pattern="import_error",
                avoid_hint="check imports",
                hint_quality="near_miss",
                q=0.65,
            ),
        )
        result = run_detect(
            "Bash",
            {"exit_code": 1, "stderr": "ImportError: No module named 'pkg'"},
            "ws_dt7",
            db,
        )
        assert result is not None
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "0.65" in ctx

    def test_matching_output_contains_avoid_hint(self, db) -> None:
        """hookSpecificOutput additionalContext에 avoid_hint 포함."""
        insert_failure(
            db,
            Failure(
                workspace_id="ws_dt8",
                pattern="value_error",
                avoid_hint="validate inputs before conversion",
                hint_quality="near_miss",
                q=0.7,
            ),
        )
        result = run_detect(
            "Bash",
            {"exit_code": 1, "stderr": "ValueError: invalid literal"},
            "ws_dt8",
            db,
        )
        assert result is not None
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "validate inputs before conversion" in ctx

    def test_empty_stderr_with_nonzero_exit_returns_none(self, db) -> None:
        """exit_code!=0이지만 stderr 빈 문자열 → 패턴 없음 → None."""
        insert_failure(
            db,
            Failure(
                workspace_id="ws_dt9",
                pattern="value_error",
                avoid_hint="hint",
                hint_quality="near_miss",
                q=0.5,
            ),
        )
        result = run_detect("Bash", {"exit_code": 1, "stderr": ""}, "ws_dt9", db)
        assert result is None

    def test_bash_case_insensitive_with_matching_pattern(self, db) -> None:
        """tool_name='bash' (소문자)도 처리."""
        insert_failure(
            db,
            Failure(
                workspace_id="ws_dt10",
                pattern="value_error",
                avoid_hint="hint",
                hint_quality="near_miss",
                q=0.5,
            ),
        )
        result = run_detect(
            "bash",
            {"exit_code": 1, "stderr": "ValueError: x"},
            "ws_dt10",
            db,
        )
        assert result is not None
        assert "hookSpecificOutput" in result


class TestDetectRuleEnforcement:
    def test_block_rule_matched_in_stderr(self, db) -> None:
        """block 모드 규칙이 stderr에 매칭 → [BLOCK] 접두사 반환."""
        insert_rule(db, Rule(workspace_id="ws_rb1", rule_text="forbidden_cmd", enforcement_mode="block"))
        result = run_detect("Bash", {"exit_code": 1, "stderr": "forbidden_cmd failed"}, "ws_rb1", db)
        assert result is not None
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert ctx.startswith("[BLOCK]")
        assert "forbidden_cmd" in ctx

    def test_warn_rule_matched_in_stderr(self, db) -> None:
        """warn 모드 규칙이 stderr에 매칭 → [WARN] 접두사 반환."""
        insert_rule(db, Rule(workspace_id="ws_rw1", rule_text="raw_sql", enforcement_mode="warn"))
        result = run_detect("Bash", {"exit_code": 1, "stderr": "raw_sql execution error"}, "ws_rw1", db)
        assert result is not None
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert ctx.startswith("[WARN]")
        assert "raw_sql" in ctx

    def test_rule_matched_in_command(self, db) -> None:
        """규칙 텍스트가 command에 포함 → 매칭."""
        insert_rule(db, Rule(workspace_id="ws_rc1", rule_text="drop table", enforcement_mode="block"))
        result = run_detect(
            "Bash",
            {"exit_code": 1, "command": "drop table users", "stderr": "syntax error"},
            "ws_rc1",
            db,
        )
        assert result is not None
        assert "[BLOCK]" in result["hookSpecificOutput"]["additionalContext"]

    def test_block_stronger_than_failure_pattern(self, db) -> None:
        """block 규칙 + 실패 패턴 동시 매칭 → [BLOCK] 우선."""
        insert_rule(db, Rule(workspace_id="ws_rbf", rule_text="forbidden", enforcement_mode="block"))
        insert_failure(
            db,
            Failure(workspace_id="ws_rbf", pattern="value_error", avoid_hint="hint", hint_quality="near_miss", q=0.7),
        )
        result = run_detect(
            "Bash",
            {"exit_code": 1, "stderr": "forbidden ValueError: x"},
            "ws_rbf",
            db,
        )
        assert result is not None
        assert "[BLOCK]" in result["hookSpecificOutput"]["additionalContext"]

    def test_warn_stronger_than_failure_pattern(self, db) -> None:
        """warn 규칙 + 실패 패턴 동시 매칭 → [WARN] 우선."""
        insert_rule(db, Rule(workspace_id="ws_rwf", rule_text="no_raw_sql", enforcement_mode="warn"))
        insert_failure(
            db,
            Failure(workspace_id="ws_rwf", pattern="value_error", avoid_hint="hint", hint_quality="near_miss", q=0.7),
        )
        result = run_detect(
            "Bash",
            {"exit_code": 1, "stderr": "no_raw_sql ValueError: x"},
            "ws_rwf",
            db,
        )
        assert result is not None
        assert "[WARN]" in result["hookSpecificOutput"]["additionalContext"]

    def test_log_rule_writes_to_log_file(self, db, tmp_path) -> None:
        """log 모드 규칙 매칭 → rules.log에 기록."""
        import forge.engines.detect as detect_mod
        original = detect_mod._RULES_LOG
        detect_mod._RULES_LOG = tmp_path / "rules.log"
        try:
            insert_rule(db, Rule(workspace_id="ws_rl1", rule_text="log_me", enforcement_mode="log"))
            run_detect("Bash", {"exit_code": 1, "stderr": "log_me triggered"}, "ws_rl1", db)
            assert (tmp_path / "rules.log").exists()
            content = (tmp_path / "rules.log").read_text()
            assert "log_me" in content
            assert "[LOG]" in content
        finally:
            detect_mod._RULES_LOG = original

    def test_log_rule_returns_failure_match(self, db, tmp_path) -> None:
        """log 모드 규칙 + 실패 패턴 → 실패 패턴 반환 (log는 기록만)."""
        import forge.engines.detect as detect_mod
        original = detect_mod._RULES_LOG
        detect_mod._RULES_LOG = tmp_path / "rules.log"
        try:
            insert_rule(db, Rule(workspace_id="ws_rl2", rule_text="log_token", enforcement_mode="log"))
            insert_failure(
                db,
                Failure(workspace_id="ws_rl2", pattern="value_error", avoid_hint="hint", hint_quality="near_miss", q=0.5),
            )
            result = run_detect(
                "Bash",
                {"exit_code": 1, "stderr": "log_token ValueError: bad"},
                "ws_rl2",
                db,
            )
            assert result is not None
            ctx = result["hookSpecificOutput"]["additionalContext"]
            assert "value_error" in ctx
            assert "[LOG]" not in ctx
        finally:
            detect_mod._RULES_LOG = original

    def test_log_rule_only_returns_none(self, db, tmp_path) -> None:
        """log 모드 규칙만 매칭 (실패 패턴 없음) → None 반환."""
        import forge.engines.detect as detect_mod
        original = detect_mod._RULES_LOG
        detect_mod._RULES_LOG = tmp_path / "rules.log"
        try:
            insert_rule(db, Rule(workspace_id="ws_rl3", rule_text="only_log", enforcement_mode="log"))
            result = run_detect("Bash", {"exit_code": 1, "stderr": "only_log triggered"}, "ws_rl3", db)
            assert result is None
        finally:
            detect_mod._RULES_LOG = original

    def test_no_rule_match_falls_through_to_failure(self, db) -> None:
        """규칙 미매칭 → 실패 패턴 매칭으로 fallthrough."""
        insert_rule(db, Rule(workspace_id="ws_rf2", rule_text="unrelated_token", enforcement_mode="block"))
        insert_failure(
            db,
            Failure(workspace_id="ws_rf2", pattern="value_error", avoid_hint="hint", hint_quality="near_miss", q=0.7),
        )
        result = run_detect("Bash", {"exit_code": 1, "stderr": "ValueError: something"}, "ws_rf2", db)
        assert result is not None
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "value_error" in ctx
        assert "[BLOCK]" not in ctx

    def test_block_over_warn_rule(self, db) -> None:
        """block + warn 규칙 동시 매칭 → block 우선."""
        insert_rule(db, Rule(workspace_id="ws_rbw", rule_text="bad_token", enforcement_mode="block"))
        insert_rule(db, Rule(workspace_id="ws_rbw", rule_text="bad_token", enforcement_mode="warn"))
        result = run_detect("Bash", {"exit_code": 1, "stderr": "bad_token error"}, "ws_rbw", db)
        assert result is not None
        assert "[BLOCK]" in result["hookSpecificOutput"]["additionalContext"]
