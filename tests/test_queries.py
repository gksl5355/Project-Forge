"""Unit tests for forge/storage/queries.py CRUD functions."""

import pytest
from datetime import datetime

from forge.storage.models import Decision, Failure, Knowledge, Rule, Session
from forge.storage.queries import (
    get_failure_by_pattern,
    get_session,
    insert_decision,
    insert_failure,
    insert_knowledge,
    insert_rule,
    insert_session,
    list_decisions,
    list_failures,
    list_knowledge,
    list_rules,
    search_by_tags,
    update_failure,
    update_session_end,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_failure(**kwargs) -> Failure:
    defaults = dict(
        workspace_id="ws1",
        pattern="conn_error",
        avoid_hint="Use retry logic",
        hint_quality="near_miss",
    )
    defaults.update(kwargs)
    return Failure(**defaults)


# ---------------------------------------------------------------------------
# Failure
# ---------------------------------------------------------------------------

class TestInsertAndGetFailure:
    def test_insert_returns_id(self, db):
        f = make_failure()
        fid = insert_failure(db, f)
        assert isinstance(fid, int)
        assert fid > 0

    def test_get_by_pattern_found(self, db):
        insert_failure(db, make_failure())
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        assert found is not None
        assert found.pattern == "conn_error"
        assert found.workspace_id == "ws1"

    def test_get_by_pattern_not_found(self, db):
        result = get_failure_by_pattern(db, "ws1", "nonexistent")
        assert result is None

    def test_get_by_pattern_wrong_workspace(self, db):
        insert_failure(db, make_failure())
        result = get_failure_by_pattern(db, "other_ws", "conn_error")
        assert result is None

    def test_json_fields_roundtrip(self, db):
        f = make_failure(tags=["docker", "network"], projects_seen=["proj-a", "proj-b"])
        insert_failure(db, f)
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        assert found.tags == ["docker", "network"]
        assert found.projects_seen == ["proj-a", "proj-b"]

    def test_default_q_value(self, db):
        insert_failure(db, make_failure())
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        assert found.q == 0.5

    def test_review_flag_roundtrip(self, db):
        f = make_failure(review_flag=True)
        insert_failure(db, f)
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        assert found.review_flag is True


class TestListFailures:
    def test_list_own_workspace(self, db):
        insert_failure(db, make_failure(pattern="err_a"))
        insert_failure(db, make_failure(pattern="err_b"))
        results = list_failures(db, "ws1", include_global=False)
        patterns = {f.pattern for f in results}
        assert patterns == {"err_a", "err_b"}

    def test_include_global_true(self, db):
        insert_failure(db, make_failure(workspace_id="__global__", pattern="global_err"))
        insert_failure(db, make_failure(pattern="local_err"))
        results = list_failures(db, "ws1", include_global=True)
        patterns = {f.pattern for f in results}
        assert "global_err" in patterns
        assert "local_err" in patterns

    def test_include_global_false(self, db):
        insert_failure(db, make_failure(workspace_id="__global__", pattern="global_err"))
        insert_failure(db, make_failure(pattern="local_err"))
        results = list_failures(db, "ws1", include_global=False)
        patterns = {f.pattern for f in results}
        assert "global_err" not in patterns
        assert "local_err" in patterns

    def test_sorted_by_q_desc(self, db):
        insert_failure(db, make_failure(pattern="low_q", q=0.2))
        insert_failure(db, make_failure(pattern="high_q", q=0.9))
        results = list_failures(db, "ws1", sort_by="q", include_global=False)
        assert results[0].q >= results[1].q

    def test_empty_workspace_returns_empty(self, db):
        results = list_failures(db, "ws_empty", include_global=False)
        assert results == []


class TestUpdateFailure:
    def test_update_fields(self, db):
        fid = insert_failure(db, make_failure())
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        found.q = 0.9
        found.times_seen = 5
        found.times_helped = 3
        found.avoid_hint = "Updated hint"
        update_failure(db, found)

        updated = get_failure_by_pattern(db, "ws1", "conn_error")
        assert updated.q == 0.9
        assert updated.times_seen == 5
        assert updated.times_helped == 3
        assert updated.avoid_hint == "Updated hint"

    def test_update_tags(self, db):
        insert_failure(db, make_failure(tags=[]))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        found.tags = ["new_tag"]
        update_failure(db, found)
        updated = get_failure_by_pattern(db, "ws1", "conn_error")
        assert updated.tags == ["new_tag"]

    def test_update_review_flag(self, db):
        insert_failure(db, make_failure(review_flag=False))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        found.review_flag = True
        update_failure(db, found)
        updated = get_failure_by_pattern(db, "ws1", "conn_error")
        assert updated.review_flag is True


class TestSearchByTags:
    def test_finds_matching_tag(self, db):
        insert_failure(db, make_failure(pattern="err_a", tags=["docker"]))
        insert_failure(db, make_failure(pattern="err_b", tags=["network"]))
        results = search_by_tags(db, "ws1", ["docker"])
        assert len(results) == 1
        assert results[0].pattern == "err_a"

    def test_multi_tag_union(self, db):
        insert_failure(db, make_failure(pattern="err_a", tags=["docker"]))
        insert_failure(db, make_failure(pattern="err_b", tags=["network"]))
        insert_failure(db, make_failure(pattern="err_c", tags=["auth"]))
        results = search_by_tags(db, "ws1", ["docker", "network"])
        patterns = {f.pattern for f in results}
        assert patterns == {"err_a", "err_b"}

    def test_no_duplicates_when_multiple_tags_match(self, db):
        insert_failure(db, make_failure(pattern="err_a", tags=["docker", "network"]))
        results = search_by_tags(db, "ws1", ["docker", "network"])
        assert len(results) == 1

    def test_includes_global_failures(self, db):
        insert_failure(db, make_failure(workspace_id="__global__", pattern="g_err", tags=["ci"]))
        results = search_by_tags(db, "ws1", ["ci"])
        assert any(f.pattern == "g_err" for f in results)

    def test_no_match_returns_empty(self, db):
        insert_failure(db, make_failure(tags=["docker"]))
        results = search_by_tags(db, "ws1", ["unknown_tag"])
        assert results == []


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

class TestDecisionCRUD:
    def make_decision(self, **kwargs) -> Decision:
        defaults = dict(workspace_id="ws1", statement="Use sqlite3 not SQLAlchemy")
        defaults.update(kwargs)
        return Decision(**defaults)

    def test_insert_returns_id(self, db):
        did = insert_decision(db, self.make_decision())
        assert isinstance(did, int) and did > 0

    def test_list_active_decisions(self, db):
        insert_decision(db, self.make_decision(statement="Decision A"))
        insert_decision(db, self.make_decision(statement="Decision B"))
        results = list_decisions(db, "ws1", status="active")
        assert len(results) == 2

    def test_list_filters_by_status(self, db):
        insert_decision(db, self.make_decision(statement="Active one", status="active"))
        insert_decision(db, self.make_decision(statement="Old one", status="superseded"))
        active = list_decisions(db, "ws1", status="active")
        assert len(active) == 1
        assert active[0].statement == "Active one"

    def test_alternatives_roundtrip(self, db):
        d = self.make_decision(alternatives=["SQLAlchemy", "peewee"])
        insert_decision(db, d)
        results = list_decisions(db, "ws1")
        assert results[0].alternatives == ["SQLAlchemy", "peewee"]

    def test_empty_workspace_returns_empty(self, db):
        assert list_decisions(db, "no_ws") == []


# ---------------------------------------------------------------------------
# Rule
# ---------------------------------------------------------------------------

class TestRuleCRUD:
    def make_rule(self, **kwargs) -> Rule:
        defaults = dict(workspace_id="ws1", rule_text="No bare except")
        defaults.update(kwargs)
        return Rule(**defaults)

    def test_insert_returns_id(self, db):
        rid = insert_rule(db, self.make_rule())
        assert isinstance(rid, int) and rid > 0

    def test_list_active_rules_only(self, db):
        insert_rule(db, self.make_rule(rule_text="Active rule", active=True))
        insert_rule(db, self.make_rule(rule_text="Inactive rule", active=False))
        results = list_rules(db, "ws1")
        texts = {r.rule_text for r in results}
        assert "Active rule" in texts
        assert "Inactive rule" not in texts

    def test_multiple_rules(self, db):
        for i in range(3):
            insert_rule(db, self.make_rule(rule_text=f"Rule {i}"))
        results = list_rules(db, "ws1")
        assert len(results) == 3

    def test_enforcement_mode_roundtrip(self, db):
        insert_rule(db, self.make_rule(enforcement_mode="block"))
        results = list_rules(db, "ws1")
        assert results[0].enforcement_mode == "block"

    def test_empty_workspace_returns_empty(self, db):
        assert list_rules(db, "no_ws") == []


# ---------------------------------------------------------------------------
# Knowledge
# ---------------------------------------------------------------------------

class TestKnowledgeCRUD:
    def make_knowledge(self, **kwargs) -> Knowledge:
        defaults = dict(workspace_id="ws1", title="WAL mode", content="Always use WAL")
        defaults.update(kwargs)
        return Knowledge(**defaults)

    def test_insert_returns_id(self, db):
        kid = insert_knowledge(db, self.make_knowledge())
        assert isinstance(kid, int) and kid > 0

    def test_list_own_workspace(self, db):
        insert_knowledge(db, self.make_knowledge(title="K1"))
        insert_knowledge(db, self.make_knowledge(title="K2"))
        results = list_knowledge(db, "ws1", include_global=False)
        assert len(results) == 2

    def test_include_global(self, db):
        insert_knowledge(db, self.make_knowledge(workspace_id="__global__", title="Global K"))
        insert_knowledge(db, self.make_knowledge(title="Local K"))
        results = list_knowledge(db, "ws1", include_global=True)
        titles = {k.title for k in results}
        assert "Global K" in titles
        assert "Local K" in titles

    def test_exclude_global(self, db):
        insert_knowledge(db, self.make_knowledge(workspace_id="__global__", title="Global K"))
        insert_knowledge(db, self.make_knowledge(title="Local K"))
        results = list_knowledge(db, "ws1", include_global=False)
        titles = {k.title for k in results}
        assert "Global K" not in titles

    def test_tags_roundtrip(self, db):
        insert_knowledge(db, self.make_knowledge(tags=["perf", "sqlite"]))
        results = list_knowledge(db, "ws1")
        assert results[0].tags == ["perf", "sqlite"]

    def test_sorted_by_q_desc(self, db):
        insert_knowledge(db, self.make_knowledge(title="Low Q", q=0.2))
        insert_knowledge(db, self.make_knowledge(title="High Q", q=0.9))
        results = list_knowledge(db, "ws1", include_global=False)
        assert results[0].q >= results[1].q


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class TestSessionCRUD:
    def make_session(self, **kwargs) -> Session:
        defaults = dict(session_id="sess-001", workspace_id="ws1")
        defaults.update(kwargs)
        return Session(**defaults)

    def test_insert_returns_id(self, db):
        sid = insert_session(db, self.make_session())
        assert isinstance(sid, int) and sid > 0

    def test_get_session_found(self, db):
        insert_session(db, self.make_session(warnings_injected=["conn_error"]))
        s = get_session(db, "sess-001")
        assert s is not None
        assert s.session_id == "sess-001"
        assert s.workspace_id == "ws1"
        assert s.warnings_injected == ["conn_error"]

    def test_get_session_not_found(self, db):
        assert get_session(db, "nonexistent") is None

    def test_ended_at_initially_none(self, db):
        insert_session(db, self.make_session())
        s = get_session(db, "sess-001")
        assert s.ended_at is None

    def test_update_session_end(self, db):
        insert_session(db, self.make_session())
        update_session_end(db, "sess-001")
        s = get_session(db, "sess-001")
        assert s.ended_at is not None

    def test_warnings_injected_empty_list(self, db):
        insert_session(db, self.make_session(warnings_injected=[]))
        s = get_session(db, "sess-001")
        assert s.warnings_injected == []
