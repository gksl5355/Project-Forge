"""통합 테스트: run_writeback — transcript 파싱 → Q 갱신 → 패턴 생성."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.config import ForgeConfig
from forge.engines.resume import run_resume
from forge.engines.writeback import run_writeback
from forge.storage.models import Failure, Session
from forge.storage.queries import (
    get_failure_by_pattern,
    get_session,
    insert_failure,
    insert_session,
    list_failures,
)


@pytest.fixture
def config():
    return ForgeConfig()


@pytest.fixture
def sample_transcript(tmp_path) -> Path:
    """실패가 있는 샘플 transcript."""
    lines = [
        {"tool_name": "Bash", "command": "python run.py", "exit_code": 0,
         "stdout": "OK", "stderr": ""},
        {"tool_name": "Bash", "command": "python -c 'import missing_lib'",
         "exit_code": 1, "stdout": "",
         "stderr": "ModuleNotFoundError: No module named 'missing_lib'"},
        {"tool_name": "Bash", "command": "pytest", "exit_code": 2,
         "stdout": "", "stderr": "ERROR collecting tests/test_foo.py\nImportError: cannot import name 'Bar'"},
    ]
    p = tmp_path / "transcript.jsonl"
    p.write_text("\n".join(json.dumps(l) for l in lines), encoding="utf-8")
    return p


@pytest.fixture
def empty_transcript(tmp_path) -> Path:
    """성공만 있는 transcript."""
    lines = [
        {"tool_name": "Bash", "command": "ls", "exit_code": 0, "stdout": ".", "stderr": ""},
    ]
    p = tmp_path / "empty.jsonl"
    p.write_text("\n".join(json.dumps(l) for l in lines), encoding="utf-8")
    return p


class TestRunWritebackPatternCreation:
    def test_creates_new_pattern(self, db, config, sample_transcript):
        # 먼저 session 생성
        session = Session(session_id="sess-wb1", workspace_id="ws1", warnings_injected=[])
        insert_session(db, session)
        run_writeback("ws1", "sess-wb1", sample_transcript, db, config)
        failures = list_failures(db, "ws1", include_global=False)
        # 실패에서 패턴 자동 생성
        assert len(failures) >= 1

    def test_missing_module_pattern_name(self, db, config, sample_transcript):
        session = Session(session_id="sess-wb2", workspace_id="ws2", warnings_injected=[])
        insert_session(db, session)
        run_writeback("ws2", "sess-wb2", sample_transcript, db, config)
        failures = list_failures(db, "ws2", include_global=False)
        patterns = [f.pattern for f in failures]
        # ModuleNotFoundError → missing_module_missing_lib
        assert any("missing_module" in p for p in patterns)

    def test_source_is_auto(self, db, config, sample_transcript):
        session = Session(session_id="sess-wb3", workspace_id="ws3", warnings_injected=[])
        insert_session(db, session)
        run_writeback("ws3", "sess-wb3", sample_transcript, db, config)
        failures = list_failures(db, "ws3", include_global=False)
        assert any(f.source == "auto" for f in failures)

    def test_no_failures_from_success_transcript(self, db, config, empty_transcript):
        session = Session(session_id="sess-wb4", workspace_id="ws4", warnings_injected=[])
        insert_session(db, session)
        run_writeback("ws4", "sess-wb4", empty_transcript, db, config)
        failures = list_failures(db, "ws4", include_global=False)
        assert len(failures) == 0

    def test_missing_transcript_file(self, db, config, tmp_path):
        session = Session(session_id="sess-wb5", workspace_id="ws5", warnings_injected=[])
        insert_session(db, session)
        missing = tmp_path / "nonexistent.jsonl"
        # 예외 발생 없이 처리
        run_writeback("ws5", "sess-wb5", missing, db, config)


class TestRunWritebackQUpdate:
    def test_q_increases_when_warning_helped(self, db, config, empty_transcript):
        """경고 후 실패 미발생 → Q 상승 (reward=1)."""
        f = Failure(
            workspace_id="ws6",
            pattern="value_error",
            avoid_hint="avoid value error",
            hint_quality="near_miss",
            q=0.5,
        )
        insert_failure(db, f)
        # 세션에 경고 기록
        session = Session(
            session_id="sess-q1",
            workspace_id="ws6",
            warnings_injected=["value_error"],
        )
        insert_session(db, session)
        run_writeback("ws6", "sess-q1", empty_transcript, db, config)
        updated = get_failure_by_pattern(db, "ws6", "value_error")
        # reward=1 → Q 상승
        assert updated.q > 0.5
        assert updated.times_warned == 1
        assert updated.times_helped == 1

    def test_q_decreases_when_warning_failed(self, db, config, tmp_path):
        """경고 후에도 실패 발생 → Q 감소 (reward=0)."""
        # value_error가 발생하는 transcript
        lines = [
            {"tool_name": "Bash", "command": "python run.py",
             "exit_code": 1, "stdout": "",
             "stderr": "ValueError: invalid literal for int()"},
        ]
        p = tmp_path / "value_err.jsonl"
        p.write_text("\n".join(json.dumps(l) for l in lines), encoding="utf-8")

        f = Failure(
            workspace_id="ws7",
            pattern="value_error",
            avoid_hint="avoid value error",
            hint_quality="near_miss",
            q=0.5,
        )
        insert_failure(db, f)
        session = Session(
            session_id="sess-q2",
            workspace_id="ws7",
            warnings_injected=["value_error"],
        )
        insert_session(db, session)
        run_writeback("ws7", "sess-q2", p, db, config)
        updated = get_failure_by_pattern(db, "ws7", "value_error")
        # reward=0 → Q 감소
        assert updated.q < 0.5
        assert updated.times_warned >= 1

    def test_existing_pattern_times_seen_incremented(self, db, config, sample_transcript):
        """기존 패턴과 매칭 시 times_seen 증가."""
        f = Failure(
            workspace_id="ws8",
            pattern="missing_module_missing_lib",
            avoid_hint="install missing_lib",
            hint_quality="environmental",
            q=0.3,
            times_seen=1,
        )
        insert_failure(db, f)
        session = Session(session_id="sess-q3", workspace_id="ws8", warnings_injected=[])
        insert_session(db, session)
        run_writeback("ws8", "sess-q3", sample_transcript, db, config)
        updated = get_failure_by_pattern(db, "ws8", "missing_module_missing_lib")
        assert updated.times_seen > 1

    def test_session_ended_after_writeback(self, db, config, empty_transcript):
        """writeback 후 session ended_at 기록."""
        session = Session(session_id="sess-end1", workspace_id="ws9", warnings_injected=[])
        insert_session(db, session)
        run_writeback("ws9", "sess-end1", empty_transcript, db, config)
        sess = get_session(db, "sess-end1")
        assert sess.ended_at is not None

    def test_global_promotion(self, db, config, sample_transcript):
        """projects_seen >= promote_threshold → 전역 승격."""
        # promote_threshold=2 이상 projects_seen 가진 패턴 설정
        f = Failure(
            workspace_id="ws10",
            pattern="missing_module_missing_lib",
            avoid_hint="install missing_lib",
            hint_quality="environmental",
            q=0.3,
            times_seen=5,
            projects_seen=["projA", "projB"],  # 2개 → 전역 승격 대상
        )
        insert_failure(db, f)
        session = Session(session_id="sess-promo1", workspace_id="ws10", warnings_injected=[])
        insert_session(db, session)
        run_writeback("ws10", "sess-promo1", sample_transcript, db, config)
        global_f = get_failure_by_pattern(db, "__global__", "missing_module_missing_lib")
        assert global_f is not None


class TestTranscriptEdgeCases:
    def test_bad_json_line_skipped(self, db, config, tmp_path):
        """잘못된 JSON 줄은 건너뜀."""
        content = (
            '{"tool_name": "Bash", "exit_code": 1, "stderr": "ValueError: x", "stdout": "", "command": "py"}\n'
            '{bad json}\n'
            '{"tool_name": "Bash", "exit_code": 0, "stderr": "", "stdout": "ok", "command": "ls"}\n'
        )
        p = tmp_path / "mixed.jsonl"
        p.write_text(content, encoding="utf-8")
        session = Session(session_id="sess-edge1", workspace_id="ws11", warnings_injected=[])
        insert_session(db, session)
        # 예외 없이 처리 확인
        run_writeback("ws11", "sess-edge1", p, db, config)
        failures = list_failures(db, "ws11", include_global=False)
        assert len(failures) >= 1
