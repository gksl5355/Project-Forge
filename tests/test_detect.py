"""단위 테스트: run_detect — Bash 실패 감지 + hookSpecificOutput 포맷."""

from __future__ import annotations

import pytest

from forge.engines.detect import run_detect
from forge.storage.models import Failure
from forge.storage.queries import insert_failure


@pytest.fixture
def workspace():
    return "ws-detect"


@pytest.fixture
def failure_in_db(db, workspace):
    """DB에 미리 등록된 실패 패턴."""
    f = Failure(
        workspace_id=workspace,
        pattern="value_error",
        avoid_hint="입력값을 검증하세요",
        hint_quality="near_miss",
        q=0.7,
        times_seen=3,
        times_helped=2,
    )
    insert_failure(db, f)
    return f


class TestRunDetectBashMatch:
    def test_returns_hook_specific_output(self, db, workspace, failure_in_db):
        result = run_detect(
            "Bash",
            {"exit_code": 1, "stderr": "ValueError: invalid input", "stdout": ""},
            workspace,
            db,
        )
        assert result is not None
        assert "hookSpecificOutput" in result

    def test_hook_event_name(self, db, workspace, failure_in_db):
        result = run_detect(
            "Bash",
            {"exit_code": 1, "stderr": "ValueError: invalid input", "stdout": ""},
            workspace,
            db,
        )
        assert result["hookSpecificOutput"]["hookEventName"] == "PostToolUse"

    def test_additional_context_contains_pattern(self, db, workspace, failure_in_db):
        result = run_detect(
            "Bash",
            {"exit_code": 1, "stderr": "ValueError: invalid input", "stdout": ""},
            workspace,
            db,
        )
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "value_error" in ctx

    def test_additional_context_contains_avoid_hint(self, db, workspace, failure_in_db):
        result = run_detect(
            "Bash",
            {"exit_code": 1, "stderr": "ValueError: invalid input", "stdout": ""},
            workspace,
            db,
        )
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "입력값을 검증하세요" in ctx

    def test_additional_context_contains_q_value(self, db, workspace, failure_in_db):
        result = run_detect(
            "Bash",
            {"exit_code": 1, "stderr": "ValueError: invalid input", "stdout": ""},
            workspace,
            db,
        )
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "Q:" in ctx
        assert "0.70" in ctx

    def test_additional_context_has_warning_emoji(self, db, workspace, failure_in_db):
        result = run_detect(
            "Bash",
            {"exit_code": 1, "stderr": "ValueError: invalid input", "stdout": ""},
            workspace,
            db,
        )
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "⚠️" in ctx

    def test_module_not_found_match(self, db, workspace):
        f = Failure(
            workspace_id=workspace,
            pattern="missing_module_requests",
            avoid_hint="pip install requests",
            hint_quality="environmental",
            q=0.4,
        )
        insert_failure(db, f)
        result = run_detect(
            "Bash",
            {"exit_code": 1,
             "stderr": "ModuleNotFoundError: No module named 'requests'",
             "stdout": ""},
            workspace,
            db,
        )
        assert result is not None
        assert "missing_module_requests" in result["hookSpecificOutput"]["additionalContext"]


class TestRunDetectIgnored:
    def test_bash_success_returns_none(self, db, workspace, failure_in_db):
        result = run_detect(
            "Bash",
            {"exit_code": 0, "stderr": "", "stdout": "OK"},
            workspace,
            db,
        )
        assert result is None

    def test_non_bash_tool_returns_none(self, db, workspace, failure_in_db):
        result = run_detect(
            "Read",
            {"exit_code": 1, "stderr": "ValueError: bad input", "stdout": ""},
            workspace,
            db,
        )
        assert result is None

    def test_edit_tool_returns_none(self, db, workspace, failure_in_db):
        result = run_detect(
            "Edit",
            {"exit_code": 1, "stderr": "some error", "stdout": ""},
            workspace,
            db,
        )
        assert result is None

    def test_case_insensitive_tool_name(self, db, workspace):
        result = run_detect(
            "bash",
            {"exit_code": 0, "stderr": "", "stdout": "done"},
            workspace,
            db,
        )
        assert result is None

    def test_exit_code_string_zero_returns_none(self, db, workspace, failure_in_db):
        result = run_detect(
            "Bash",
            {"exit_code": "0", "stderr": "ValueError: x", "stdout": ""},
            workspace,
            db,
        )
        assert result is None


class TestRunDetectNoMatch:
    def test_no_pattern_in_db_returns_none(self, db, workspace):
        result = run_detect(
            "Bash",
            {"exit_code": 1, "stderr": "SomeObscureError: xyz", "stdout": ""},
            workspace,
            db,
        )
        assert result is None

    def test_different_workspace_no_match(self, db):
        f = Failure(
            workspace_id="other-ws",
            pattern="value_error",
            avoid_hint="avoid it",
            hint_quality="near_miss",
            q=0.5,
        )
        insert_failure(db, f)
        result = run_detect(
            "Bash",
            {"exit_code": 1, "stderr": "ValueError: x", "stdout": ""},
            "ws-detect",
            db,
        )
        assert result is None

    def test_empty_stderr_returns_none(self, db, workspace, failure_in_db):
        result = run_detect(
            "Bash",
            {"exit_code": 1, "stderr": "", "stdout": ""},
            workspace,
            db,
        )
        assert result is None

    def test_global_pattern_matches_any_workspace(self, db):
        f = Failure(
            workspace_id="__global__",
            pattern="value_error",
            avoid_hint="global hint",
            hint_quality="near_miss",
            q=0.6,
        )
        insert_failure(db, f)
        result = run_detect(
            "Bash",
            {"exit_code": 1, "stderr": "ValueError: global error", "stdout": ""},
            "any-workspace",
            db,
        )
        assert result is not None
        assert "hookSpecificOutput" in result
