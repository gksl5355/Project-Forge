"""통합 테스트: run_resume — 빈 DB, 데이터 있는 DB."""

from __future__ import annotations

import pytest

from forge.config import ForgeConfig
from forge.engines.resume import run_resume
from forge.storage.models import Failure, Rule
from forge.storage.queries import insert_failure, insert_rule, get_session


@pytest.fixture
def config():
    return ForgeConfig()


class TestRunResumeEmptyDb:
    def test_returns_string(self, db, config):
        ctx = run_resume("ws1", "sess-empty", db, config)
        assert isinstance(ctx, str)

    def test_empty_db_empty_context(self, db, config):
        ctx = run_resume("ws1", "sess-empty2", db, config)
        # 데이터 없으면 빈 문자열 또는 섹션 없음
        assert "WARN" not in ctx

    def test_session_created(self, db, config):
        run_resume("ws1", "sess-check", db, config)
        session = get_session(db, "sess-check")
        assert session is not None
        assert session.session_id == "sess-check"
        assert session.workspace_id == "ws1"

    def test_warnings_injected_empty(self, db, config):
        run_resume("ws1", "sess-wi", db, config)
        session = get_session(db, "sess-wi")
        assert session.warnings_injected == []


class TestRunResumeWithData:
    def _insert_failure(self, db, workspace_id: str, pattern: str, q: float = 0.6):
        f = Failure(
            workspace_id=workspace_id,
            pattern=pattern,
            avoid_hint=f"Avoid {pattern}",
            hint_quality="near_miss",
            q=q,
        )
        insert_failure(db, f)

    def _insert_rule(self, db, workspace_id: str, rule_text: str):
        r = Rule(
            workspace_id=workspace_id,
            rule_text=rule_text,
            enforcement_mode="warn",
        )
        insert_rule(db, r)

    def test_context_contains_failure(self, db, config):
        self._insert_failure(db, "ws2", "import_error")
        ctx = run_resume("ws2", "sess-data1", db, config)
        assert "import_error" in ctx

    def test_context_contains_warn(self, db, config):
        self._insert_failure(db, "ws2b", "type_error")
        ctx = run_resume("ws2b", "sess-data2", db, config)
        assert "[WARN]" in ctx

    def test_context_contains_rule(self, db, config):
        self._insert_rule(db, "ws3", "no raw SQL in app layer")
        ctx = run_resume("ws3", "sess-rule", db, config)
        assert "no raw SQL" in ctx
        assert "[RULE]" in ctx

    def test_warnings_injected_populated(self, db, config):
        self._insert_failure(db, "ws4", "runtime_error")
        self._insert_failure(db, "ws4", "value_error")
        run_resume("ws4", "sess-wi2", db, config)
        session = get_session(db, "sess-wi2")
        assert "runtime_error" in session.warnings_injected
        assert "value_error" in session.warnings_injected

    def test_multiple_sessions_independent(self, db, config):
        self._insert_failure(db, "ws5", "key_error")
        run_resume("ws5", "sess-a", db, config)
        run_resume("ws5", "sess-b", db, config)
        sess_a = get_session(db, "sess-a")
        sess_b = get_session(db, "sess-b")
        assert sess_a is not None
        assert sess_b is not None
        assert sess_a.session_id != sess_b.session_id

    def test_global_failures_included(self, db, config):
        # __global__ 워크스페이스 패턴도 포함
        f = Failure(
            workspace_id="__global__",
            pattern="global_pattern",
            avoid_hint="global hint",
            hint_quality="preventable",
            q=0.7,
        )
        insert_failure(db, f)
        ctx = run_resume("ws6", "sess-global", db, config)
        assert "global_pattern" in ctx

    def test_l1_section_present(self, db, config):
        self._insert_failure(db, "ws7", "attr_error", q=0.8)
        ctx = run_resume("ws7", "sess-l1", db, config)
        assert "Details" in ctx or "L1" in ctx
