"""Comprehensive edge case tests for forge/storage/ (db.py, models.py, queries.py)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, UTC

import pytest

from forge.storage.db import CURRENT_SCHEMA_VERSION, _ensure_schema
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
    update_decision,
    update_failure,
    update_rule,
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


def make_knowledge(**kwargs) -> Knowledge:
    defaults = dict(workspace_id="ws1", title="WAL mode", content="Always use WAL")
    defaults.update(kwargs)
    return Knowledge(**defaults)


def make_session(**kwargs) -> Session:
    defaults = dict(session_id="sess-001", workspace_id="ws1")
    defaults.update(kwargs)
    return Session(**defaults)


def make_decision(**kwargs) -> Decision:
    defaults = dict(workspace_id="ws1", statement="Use sqlite3 not SQLAlchemy")
    defaults.update(kwargs)
    return Decision(**defaults)


def make_rule(**kwargs) -> Rule:
    defaults = dict(workspace_id="ws1", rule_text="No bare except")
    defaults.update(kwargs)
    return Rule(**defaults)


# ---------------------------------------------------------------------------
# DB Init & Schema Idempotency
# ---------------------------------------------------------------------------

class TestDbInitIdempotency:
    def test_ensure_schema_idempotent(self, db):
        """Calling _ensure_schema twice on already-initialized DB is safe."""
        _ensure_schema(db)  # second call — should not raise or corrupt schema
        version = db.execute("SELECT version FROM schema_version").fetchone()[0]
        assert version == CURRENT_SCHEMA_VERSION

    def test_schema_version_is_correct(self, db):
        version = db.execute("SELECT version FROM schema_version").fetchone()[0]
        assert version == CURRENT_SCHEMA_VERSION

    def test_all_tables_exist(self, db):
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        for expected in ("failures", "decisions", "rules", "knowledge", "sessions"):
            assert expected in tables

    def test_schema_version_table_has_one_row(self, db):
        count = db.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
        assert count == 1


# ---------------------------------------------------------------------------
# JSON Column Edge Cases
# ---------------------------------------------------------------------------

class TestJsonColumnEdgeCases:
    def test_empty_tags_list_roundtrip(self, db):
        insert_failure(db, make_failure(tags=[]))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        assert found.tags == []

    def test_empty_projects_seen_list_roundtrip(self, db):
        insert_failure(db, make_failure(projects_seen=[]))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        assert found.projects_seen == []

    def test_unicode_in_tags(self, db):
        unicode_tags = ["日本語", "中文", "한국어", "emoji🚀"]
        insert_failure(db, make_failure(tags=unicode_tags))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        assert found.tags == unicode_tags

    def test_very_long_single_tag(self, db):
        long_tag = "x" * 10_000
        insert_failure(db, make_failure(tags=[long_tag]))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        assert found.tags == [long_tag]

    def test_many_tags_roundtrip(self, db):
        many_tags = [f"tag_{i}" for i in range(100)]
        insert_failure(db, make_failure(tags=many_tags))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        assert found.tags == many_tags

    def test_unicode_in_pattern(self, db):
        unicode_pattern = "错误_conn_🔥"
        insert_failure(db, make_failure(pattern=unicode_pattern))
        found = get_failure_by_pattern(db, "ws1", unicode_pattern)
        assert found is not None
        assert found.pattern == unicode_pattern

    def test_very_long_avoid_hint(self, db):
        long_hint = "Avoid this pattern. " * 500
        insert_failure(db, make_failure(avoid_hint=long_hint))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        assert found.avoid_hint == long_hint

    def test_unicode_in_knowledge_content(self, db):
        content = "Unicode: 日本語 中文 🎉 الع"
        insert_knowledge(db, make_knowledge(content=content))
        results = list_knowledge(db, "ws1", include_global=False)
        assert results[0].content == content

    def test_empty_alternatives_in_decision(self, db):
        insert_decision(db, make_decision(alternatives=[]))
        results = list_decisions(db, "ws1")
        assert results[0].alternatives == []

    def test_empty_warnings_injected_in_session(self, db):
        insert_session(db, make_session(warnings_injected=[]))
        s = get_session(db, "sess-001")
        assert s.warnings_injected == []

    def test_unicode_in_warnings_injected(self, db):
        warnings = ["error_日本語", "fail_🔥", "broken_中文"]
        insert_session(db, make_session(warnings_injected=warnings))
        s = get_session(db, "sess-001")
        assert s.warnings_injected == warnings

    def test_knowledge_empty_tags_roundtrip(self, db):
        insert_knowledge(db, make_knowledge(tags=[]))
        results = list_knowledge(db, "ws1")
        assert results[0].tags == []


# ---------------------------------------------------------------------------
# Duplicate Insert Handling (UNIQUE constraints)
# ---------------------------------------------------------------------------

class TestDuplicateInsert:
    def test_duplicate_failure_same_workspace_and_pattern_raises(self, db):
        insert_failure(db, make_failure())
        with pytest.raises(sqlite3.IntegrityError):
            insert_failure(db, make_failure())  # identical workspace_id + pattern

    def test_same_pattern_different_workspace_is_ok(self, db):
        insert_failure(db, make_failure(workspace_id="ws1"))
        fid = insert_failure(db, make_failure(workspace_id="ws2"))
        assert fid > 0

    def test_same_workspace_different_pattern_is_ok(self, db):
        insert_failure(db, make_failure(pattern="err_a"))
        fid = insert_failure(db, make_failure(pattern="err_b"))
        assert fid > 0

    def test_duplicate_session_id_raises(self, db):
        insert_session(db, make_session(session_id="sess-dup"))
        with pytest.raises(sqlite3.IntegrityError):
            insert_session(db, make_session(session_id="sess-dup"))


# ---------------------------------------------------------------------------
# list_failures: sort_by variations
# ---------------------------------------------------------------------------

class TestListFailuresSortBy:
    def test_sort_by_times_seen_desc(self, db):
        insert_failure(db, make_failure(pattern="low", times_seen=1))
        insert_failure(db, make_failure(pattern="high", times_seen=10))
        results = list_failures(db, "ws1", sort_by="times_seen", include_global=False)
        counts = [r.times_seen for r in results]
        assert counts == sorted(counts, reverse=True)

    def test_sort_by_created_at_desc(self, db):
        t1 = datetime.now(UTC)
        t2 = t1 + timedelta(seconds=1)
        insert_failure(db, make_failure(pattern="older", created_at=t1, updated_at=t1))
        insert_failure(db, make_failure(pattern="newer", created_at=t2, updated_at=t2))
        results = list_failures(db, "ws1", sort_by="created_at", include_global=False)
        assert results[0].pattern == "newer"

    def test_sort_by_updated_at_desc(self, db):
        t1 = datetime.now(UTC)
        t2 = t1 + timedelta(seconds=1)
        insert_failure(db, make_failure(pattern="older", updated_at=t1))
        insert_failure(db, make_failure(pattern="newer", updated_at=t2))
        results = list_failures(db, "ws1", sort_by="updated_at", include_global=False)
        assert results[0].pattern == "newer"

    def test_sort_by_last_used_nulls_sort_last(self, db):
        """NULL last_used rows should sort after non-null rows in DESC order."""
        t = datetime.now(UTC)
        insert_failure(db, make_failure(pattern="used", last_used=t))
        insert_failure(db, make_failure(pattern="never_used", last_used=None))
        results = list_failures(db, "ws1", sort_by="last_used", include_global=False)
        assert results[0].pattern == "used"

    def test_invalid_sort_by_falls_back_to_q(self, db):
        insert_failure(db, make_failure(pattern="low", q=0.2))
        insert_failure(db, make_failure(pattern="high", q=0.9))
        results = list_failures(db, "ws1", sort_by="DROP TABLE failures--", include_global=False)
        qs = [r.q for r in results]
        assert qs == sorted(qs, reverse=True)

    def test_sort_by_q_produces_desc_order(self, db):
        insert_failure(db, make_failure(pattern="a", q=0.3))
        insert_failure(db, make_failure(pattern="b", q=0.7))
        insert_failure(db, make_failure(pattern="c", q=0.5))
        results = list_failures(db, "ws1", sort_by="q", include_global=False)
        qs = [r.q for r in results]
        assert qs == sorted(qs, reverse=True)


# ---------------------------------------------------------------------------
# list_failures: include_global edge cases
# ---------------------------------------------------------------------------

class TestListFailuresIncludeGlobal:
    def test_global_workspace_not_duplicated_when_querying_as_global(self, db):
        """workspace_id=__global__ with include_global=True should not duplicate rows."""
        insert_failure(db, make_failure(workspace_id="__global__", pattern="g_err"))
        results = list_failures(db, "__global__", include_global=True)
        patterns = [f.pattern for f in results]
        assert patterns.count("g_err") == 1

    def test_other_workspace_excluded_even_with_include_global(self, db):
        insert_failure(db, make_failure(workspace_id="ws_other", pattern="other_err"))
        insert_failure(db, make_failure(workspace_id="__global__", pattern="global_err"))
        results = list_failures(db, "ws1", include_global=True)
        patterns = {f.pattern for f in results}
        assert "other_err" not in patterns
        assert "global_err" in patterns

    def test_empty_db_include_global_returns_empty(self, db):
        assert list_failures(db, "ws1", include_global=True) == []

    def test_empty_db_exclude_global_returns_empty(self, db):
        assert list_failures(db, "ws1", include_global=False) == []

    def test_include_global_false_excludes_global_workspace(self, db):
        insert_failure(db, make_failure(workspace_id="__global__", pattern="g_err"))
        results = list_failures(db, "ws1", include_global=False)
        assert results == []


# ---------------------------------------------------------------------------
# search_by_tags edge cases
# ---------------------------------------------------------------------------

class TestSearchByTagsEdgeCases:
    def test_empty_tags_list_returns_empty(self, db):
        insert_failure(db, make_failure(tags=["docker"]))
        results = search_by_tags(db, "ws1", [])
        assert results == []

    def test_nonexistent_tag_returns_empty(self, db):
        insert_failure(db, make_failure(tags=["docker"]))
        results = search_by_tags(db, "ws1", ["nonexistent_xyz"])
        assert results == []

    def test_single_tag_exact_match(self, db):
        insert_failure(db, make_failure(pattern="a", tags=["auth"]))
        insert_failure(db, make_failure(pattern="b", tags=["network"]))
        results = search_by_tags(db, "ws1", ["auth"])
        assert len(results) == 1
        assert results[0].pattern == "a"

    def test_multiple_tags_union_semantics(self, db):
        insert_failure(db, make_failure(pattern="a", tags=["auth"]))
        insert_failure(db, make_failure(pattern="b", tags=["network"]))
        insert_failure(db, make_failure(pattern="c", tags=["db"]))
        results = search_by_tags(db, "ws1", ["auth", "network"])
        patterns = {f.pattern for f in results}
        assert patterns == {"a", "b"}

    def test_no_duplicate_when_failure_matches_multiple_search_tags(self, db):
        insert_failure(db, make_failure(pattern="a", tags=["auth", "network"]))
        results = search_by_tags(db, "ws1", ["auth", "network"])
        assert len(results) == 1

    def test_includes_global_workspace(self, db):
        insert_failure(db, make_failure(workspace_id="__global__", pattern="g_err", tags=["global_tag"]))
        results = search_by_tags(db, "ws1", ["global_tag"])
        assert any(f.pattern == "g_err" for f in results)

    def test_excludes_other_workspace(self, db):
        insert_failure(db, make_failure(workspace_id="ws_other", pattern="other_err", tags=["shared_tag"]))
        results = search_by_tags(db, "ws1", ["shared_tag"])
        assert not any(f.pattern == "other_err" for f in results)

    def test_partial_tag_string_does_not_match(self, db):
        """Tag 'docker' should NOT match search term 'dock'."""
        insert_failure(db, make_failure(tags=["docker"]))
        results = search_by_tags(db, "ws1", ["dock"])
        assert results == []

    def test_empty_failure_tags_not_matched_by_any_tag(self, db):
        insert_failure(db, make_failure(tags=[]))
        results = search_by_tags(db, "ws1", ["any_tag"])
        assert results == []

    def test_unicode_tag_match(self, db):
        insert_failure(db, make_failure(tags=["日本語"]))
        results = search_by_tags(db, "ws1", ["日本語"])
        assert len(results) == 1

    def test_unicode_tag_no_false_match(self, db):
        insert_failure(db, make_failure(tags=["日本語"]))
        results = search_by_tags(db, "ws1", ["日本"])
        assert results == []

    def test_empty_db_returns_empty(self, db):
        assert search_by_tags(db, "ws1", ["docker"]) == []


# ---------------------------------------------------------------------------
# Session CRUD edge cases
# ---------------------------------------------------------------------------

class TestSessionEdgeCases:
    def test_update_end_on_nonexistent_session_is_noop(self, db):
        """update_session_end on a missing session_id must not raise."""
        update_session_end(db, "nonexistent-session-id")  # no exception

    def test_session_with_many_warnings(self, db):
        warnings = [f"warn_{i}" for i in range(50)]
        insert_session(db, make_session(warnings_injected=warnings))
        s = get_session(db, "sess-001")
        assert s.warnings_injected == warnings

    def test_ended_at_none_after_insert(self, db):
        insert_session(db, make_session(ended_at=None))
        s = get_session(db, "sess-001")
        assert s.ended_at is None

    def test_update_end_sets_non_null_timestamp(self, db):
        insert_session(db, make_session())
        update_session_end(db, "sess-001")
        s = get_session(db, "sess-001")
        assert s.ended_at is not None

    def test_get_nonexistent_session_returns_none(self, db):
        assert get_session(db, "no-such-session") is None

    def test_session_unicode_session_id(self, db):
        uid = "session_🔥_日本語"
        insert_session(db, make_session(session_id=uid))
        s = get_session(db, uid)
        assert s is not None
        assert s.session_id == uid

    def test_session_workspace_id_preserved(self, db):
        insert_session(db, make_session(workspace_id="my_special_ws"))
        s = get_session(db, "sess-001")
        assert s.workspace_id == "my_special_ws"


# ---------------------------------------------------------------------------
# Datetime Handling
# ---------------------------------------------------------------------------

class TestDatetimeHandling:
    def test_failure_last_used_none_roundtrip(self, db):
        insert_failure(db, make_failure(last_used=None))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        assert found.last_used is None

    def test_failure_last_used_set_roundtrip(self, db):
        t = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)
        insert_failure(db, make_failure(last_used=t))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        assert found.last_used is not None
        assert found.last_used.isoformat() == t.isoformat()

    def test_knowledge_last_used_none_roundtrip(self, db):
        insert_knowledge(db, make_knowledge(last_used=None))
        results = list_knowledge(db, "ws1")
        assert results[0].last_used is None

    def test_decision_last_used_none_roundtrip(self, db):
        insert_decision(db, make_decision(last_used=None))
        results = list_decisions(db, "ws1")
        assert results[0].last_used is None

    def test_failure_created_at_roundtrip(self, db):
        t = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        insert_failure(db, make_failure(created_at=t))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        assert found.created_at.isoformat() == t.isoformat()

    def test_session_started_at_preserved(self, db):
        t = datetime(2026, 6, 1, 9, 30, 0, tzinfo=UTC)
        insert_session(db, make_session(started_at=t))
        s = get_session(db, "sess-001")
        assert s.started_at.isoformat() == t.isoformat()


# ---------------------------------------------------------------------------
# Knowledge CRUD with include_global
# ---------------------------------------------------------------------------

class TestKnowledgeIncludeGlobal:
    def test_include_global_true_returns_both(self, db):
        insert_knowledge(db, make_knowledge(workspace_id="__global__", title="Global K"))
        insert_knowledge(db, make_knowledge(title="Local K"))
        results = list_knowledge(db, "ws1", include_global=True)
        titles = {k.title for k in results}
        assert "Global K" in titles
        assert "Local K" in titles

    def test_include_global_false_omits_global(self, db):
        insert_knowledge(db, make_knowledge(workspace_id="__global__", title="Global K"))
        insert_knowledge(db, make_knowledge(title="Local K"))
        results = list_knowledge(db, "ws1", include_global=False)
        titles = {k.title for k in results}
        assert "Global K" not in titles
        assert "Local K" in titles

    def test_empty_db_returns_empty(self, db):
        assert list_knowledge(db, "ws1", include_global=True) == []

    def test_other_workspace_not_included_even_with_global(self, db):
        insert_knowledge(db, make_knowledge(workspace_id="ws_other", title="Other K"))
        results = list_knowledge(db, "ws1", include_global=True)
        titles = {k.title for k in results}
        assert "Other K" not in titles

    def test_sorted_by_q_desc(self, db):
        insert_knowledge(db, make_knowledge(title="A", q=0.1))
        insert_knowledge(db, make_knowledge(title="B", q=0.9))
        insert_knowledge(db, make_knowledge(title="C", q=0.5))
        results = list_knowledge(db, "ws1", include_global=False)
        qs = [k.q for k in results]
        assert qs == sorted(qs, reverse=True)

    def test_promoted_from_roundtrip(self, db):
        fid = insert_failure(db, make_failure())
        insert_knowledge(db, make_knowledge(promoted_from=fid))
        results = list_knowledge(db, "ws1")
        assert results[0].promoted_from == fid

    def test_promoted_from_none_roundtrip(self, db):
        insert_knowledge(db, make_knowledge(promoted_from=None))
        results = list_knowledge(db, "ws1")
        assert results[0].promoted_from is None


# ---------------------------------------------------------------------------
# Empty Database Queries
# ---------------------------------------------------------------------------

class TestEmptyDatabaseQueries:
    def test_get_failure_empty_db(self, db):
        assert get_failure_by_pattern(db, "ws1", "any_pattern") is None

    def test_list_failures_empty_db(self, db):
        assert list_failures(db, "ws1") == []

    def test_search_by_tags_empty_db(self, db):
        assert search_by_tags(db, "ws1", ["tag"]) == []

    def test_list_decisions_empty_db(self, db):
        assert list_decisions(db, "ws1") == []

    def test_list_rules_empty_db(self, db):
        assert list_rules(db, "ws1") == []

    def test_list_knowledge_empty_db(self, db):
        assert list_knowledge(db, "ws1") == []

    def test_get_session_empty_db(self, db):
        assert get_session(db, "any_session") is None


# ---------------------------------------------------------------------------
# Update Function Edge Cases
# ---------------------------------------------------------------------------

class TestUpdateEdgeCases:
    def test_update_failure_clears_last_used_to_none(self, db):
        t = datetime.now(UTC)
        insert_failure(db, make_failure(last_used=t))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        found.last_used = None
        update_failure(db, found)
        updated = get_failure_by_pattern(db, "ws1", "conn_error")
        assert updated.last_used is None

    def test_update_failure_sets_last_used_from_none(self, db):
        insert_failure(db, make_failure(last_used=None))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        found.last_used = datetime(2026, 6, 1, tzinfo=UTC)
        update_failure(db, found)
        updated = get_failure_by_pattern(db, "ws1", "conn_error")
        assert updated.last_used is not None

    def test_update_failure_q_value(self, db):
        insert_failure(db, make_failure(q=0.5))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        found.q = 0.8
        update_failure(db, found)
        updated = get_failure_by_pattern(db, "ws1", "conn_error")
        assert updated.q == 0.8

    def test_update_failure_projects_seen(self, db):
        insert_failure(db, make_failure(projects_seen=[]))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        found.projects_seen = ["proj-alpha", "proj-beta"]
        update_failure(db, found)
        updated = get_failure_by_pattern(db, "ws1", "conn_error")
        assert updated.projects_seen == ["proj-alpha", "proj-beta"]

    def test_update_failure_review_flag_toggle(self, db):
        insert_failure(db, make_failure(review_flag=False))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        found.review_flag = True
        update_failure(db, found)
        updated = get_failure_by_pattern(db, "ws1", "conn_error")
        assert updated.review_flag is True

    def test_update_rule_deactivates(self, db):
        insert_rule(db, make_rule(active=True))
        rule = list_rules(db, "ws1")[0]
        rule.active = False
        update_rule(db, rule)
        # list_rules returns only active=1
        assert list_rules(db, "ws1") == []

    def test_update_decision_status_to_superseded(self, db):
        insert_decision(db, make_decision(status="active"))
        d = list_decisions(db, "ws1", status="active")[0]
        d.status = "superseded"
        update_decision(db, d)
        assert list_decisions(db, "ws1", status="active") == []
        assert len(list_decisions(db, "ws1", status="superseded")) == 1

    def test_update_decision_alternatives(self, db):
        insert_decision(db, make_decision(alternatives=[]))
        d = list_decisions(db, "ws1")[0]
        d.alternatives = ["option_a", "option_b"]
        update_decision(db, d)
        updated = list_decisions(db, "ws1")
        assert updated[0].alternatives == ["option_a", "option_b"]


# ---------------------------------------------------------------------------
# hint_quality CHECK constraint
# ---------------------------------------------------------------------------

class TestHintQualityConstraint:
    def test_near_miss_valid(self, db):
        assert insert_failure(db, make_failure(hint_quality="near_miss")) > 0

    def test_preventable_valid(self, db):
        assert insert_failure(db, make_failure(hint_quality="preventable")) > 0

    def test_environmental_valid(self, db):
        assert insert_failure(db, make_failure(hint_quality="environmental")) > 0

    def test_invalid_hint_quality_raises_integrity_error(self, db):
        with pytest.raises(sqlite3.IntegrityError):
            insert_failure(db, make_failure(hint_quality="bogus_quality"))


# ---------------------------------------------------------------------------
# source field values
# ---------------------------------------------------------------------------

class TestSourceField:
    def test_default_source_is_manual(self, db):
        insert_failure(db, make_failure())
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        assert found.source == "manual"

    def test_source_auto_roundtrip(self, db):
        insert_failure(db, make_failure(source="auto"))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        assert found.source == "auto"

    def test_source_organic_roundtrip(self, db):
        insert_failure(db, make_failure(source="organic"))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        assert found.source == "organic"


# ---------------------------------------------------------------------------
# Observed error / likely cause (optional text fields)
# ---------------------------------------------------------------------------

class TestOptionalTextFields:
    def test_observed_error_none_roundtrip(self, db):
        insert_failure(db, make_failure(observed_error=None))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        assert found.observed_error is None

    def test_likely_cause_none_roundtrip(self, db):
        insert_failure(db, make_failure(likely_cause=None))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        assert found.likely_cause is None

    def test_observed_error_unicode(self, db):
        err = "ConnectionError: 接続失敗 🔌"
        insert_failure(db, make_failure(observed_error=err))
        found = get_failure_by_pattern(db, "ws1", "conn_error")
        assert found.observed_error == err

    def test_rule_scope_none_roundtrip(self, db):
        insert_rule(db, make_rule(scope=None))
        results = list_rules(db, "ws1")
        assert results[0].scope is None

    def test_rule_scope_set_roundtrip(self, db):
        insert_rule(db, make_rule(scope="backend"))
        results = list_rules(db, "ws1")
        assert results[0].scope == "backend"
