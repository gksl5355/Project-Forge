"""Comprehensive tests for quality audit gaps."""

import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone
    UTC = timezone.utc

import pytest

from forge.config import ForgeConfig, load_config, _validate_config
from forge.core.dedup import find_duplicates
from forge.core.output_analyzer import _normalize_command, _estimate_useful_portion
from forge.engines.extractor import _parse_extraction_response
from forge.storage.models import Knowledge, Rule, TeamRun
from forge.storage.queries import (
    get_knowledge_by_id,
    get_rule_by_id,
    get_team_run,
    insert_knowledge,
    insert_rule,
    insert_team_run,
    set_meta,
    get_meta,
    update_knowledge,
    update_team_run,
)


# ============================================================================
# 1. Config validation tests
# ============================================================================


def test_load_config_malformed_yaml(tmp_path):
    """Malformed YAML should return defaults."""
    config_file = tmp_path / "bad.yml"
    config_file.write_text("not: [valid: yaml: :")
    config = load_config(config_file)
    assert config.alpha == 0.1  # default


def test_validate_config_clamps_alpha():
    """Alpha < 0 should clamp to 0."""
    config = ForgeConfig(alpha=-5.0)
    validated = _validate_config(config)
    assert validated.alpha == 0.0


def test_validate_config_clamps_alpha_max():
    """Alpha > 1 should clamp to 1."""
    config = ForgeConfig(alpha=99.0)
    validated = _validate_config(config)
    assert validated.alpha == 1.0


def test_validate_config_negative_max_tokens():
    """Negative max_tokens should reset to default."""
    config = ForgeConfig(max_tokens=-100)
    validated = _validate_config(config)
    assert validated.max_tokens == 3000


def test_validate_config_zero_max_tokens():
    """Zero max_tokens should reset to default."""
    config = ForgeConfig(max_tokens=0)
    validated = _validate_config(config)
    assert validated.max_tokens == 3000


def test_validate_config_clamps_decay():
    """Decay should clamp to [0, 1]."""
    config = ForgeConfig(decay_daily=-0.5)
    validated = _validate_config(config)
    assert validated.decay_daily == 0.0

    config = ForgeConfig(decay_daily=2.5)
    validated = _validate_config(config)
    assert validated.decay_daily == 1.0


def test_validate_config_clamps_q_values():
    """All Q values should clamp to [0, 1]."""
    config = ForgeConfig(
        q_min=-0.1,
        initial_q_near_miss=1.5,
        initial_q_preventable=-0.5,
        initial_q_environmental=2.0,
    )
    validated = _validate_config(config)
    assert validated.q_min == 0.0
    assert validated.initial_q_near_miss == 1.0
    assert validated.initial_q_preventable == 0.0
    assert validated.initial_q_environmental == 1.0


def test_validate_config_clamps_lambda_weight():
    """Lambda weight should clamp to [0, 1]."""
    config = ForgeConfig(lambda_weight=-0.5)
    validated = _validate_config(config)
    assert validated.lambda_weight == 0.0

    config = ForgeConfig(lambda_weight=5.0)
    validated = _validate_config(config)
    assert validated.lambda_weight == 1.0


def test_validate_config_clamps_dedup_threshold():
    """Dedup threshold should clamp to [0, 1]."""
    config = ForgeConfig(dedup_threshold=-0.1)
    validated = _validate_config(config)
    assert validated.dedup_threshold == 0.0

    config = ForgeConfig(dedup_threshold=1.5)
    validated = _validate_config(config)
    assert validated.dedup_threshold == 1.0


def test_validate_config_preserves_valid_values():
    """Valid values should remain unchanged."""
    config = ForgeConfig(alpha=0.5, max_tokens=5000, promote_threshold=3)
    validated = _validate_config(config)
    assert validated.alpha == 0.5
    assert validated.max_tokens == 5000
    assert validated.promote_threshold == 3


# ============================================================================
# 2. New CRUD functions tests
# ============================================================================


def test_get_knowledge_by_id(db):
    """Get knowledge by ID should return the exact record."""
    k = Knowledge(workspace_id="ws", title="t", content="c")
    kid = insert_knowledge(db, k)
    result = get_knowledge_by_id(db, kid, "ws")
    assert result is not None
    assert result.title == "t"
    assert result.content == "c"
    assert result.id == kid


def test_get_knowledge_by_id_not_found(db):
    """Get knowledge with invalid ID should return None."""
    assert get_knowledge_by_id(db, 999, "ws") is None


def test_get_knowledge_by_id_wrong_workspace(db):
    """Get knowledge from different workspace should return None."""
    k = Knowledge(workspace_id="ws1", title="t", content="c")
    kid = insert_knowledge(db, k)
    assert get_knowledge_by_id(db, kid, "ws2") is None


def test_update_knowledge(db):
    """Update knowledge should reflect all changes."""
    k = Knowledge(workspace_id="ws", title="old", content="old_c")
    kid = insert_knowledge(db, k)
    k2 = get_knowledge_by_id(db, kid, "ws")
    k2.title = "new"
    k2.q = 0.9
    k2.tags = ["tag1", "tag2"]
    update_knowledge(db, k2)
    result = get_knowledge_by_id(db, kid, "ws")
    assert result.title == "new"
    assert result.q == 0.9
    assert result.tags == ["tag1", "tag2"]


def test_get_rule_by_id(db):
    """Get rule by ID should return the exact record."""
    r = Rule(workspace_id="ws", rule_text="no force push")
    rid = insert_rule(db, r)
    result = get_rule_by_id(db, rid, "ws")
    assert result is not None
    assert "force push" in result.rule_text
    assert result.id == rid


def test_get_rule_by_id_not_found(db):
    """Get rule with invalid ID should return None."""
    assert get_rule_by_id(db, 999, "ws") is None


def test_get_rule_by_id_wrong_workspace(db):
    """Get rule from different workspace should return None."""
    r = Rule(workspace_id="ws1", rule_text="test rule")
    rid = insert_rule(db, r)
    assert get_rule_by_id(db, rid, "ws2") is None


def test_update_team_run(db):
    """Update team run should reflect all changes."""
    tr = TeamRun(workspace_id="ws", run_id="r1", verdict="PENDING")
    tid = insert_team_run(db, tr)
    tr2 = get_team_run(db, "r1")
    assert tr2 is not None
    tr2.verdict = "SUCCESS"
    tr2.success_rate = 0.95
    update_team_run(db, tr2)
    result = get_team_run(db, "r1")
    assert result.verdict == "SUCCESS"
    assert result.success_rate == 0.95


def test_get_team_run_not_found(db):
    """Get team run with invalid ID should return None."""
    assert get_team_run(db, "nonexistent") is None


def test_team_run_with_agents(db):
    """TeamRun with agents list should serialize/deserialize correctly."""
    agents = [{"name": "agent1", "model": "claude-opus"}, {"name": "agent2", "model": "gpt-4"}]
    tr = TeamRun(workspace_id="ws", run_id="r1", agents=agents)
    tid = insert_team_run(db, tr)
    result = get_team_run(db, "r1")
    assert result.agents == agents


# ============================================================================
# 3. Migration test
# ============================================================================


def test_migration_v2_to_v3():
    """Create v2 schema, run migration, verify v3 features."""
    from forge.storage.db import _migrate

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version VALUES (2);
        CREATE TABLE failures (
            id INTEGER PRIMARY KEY, workspace_id TEXT, pattern TEXT,
            observed_error TEXT, likely_cause TEXT, avoid_hint TEXT NOT NULL,
            hint_quality TEXT NOT NULL, q REAL DEFAULT 0.5,
            times_seen INTEGER DEFAULT 1, times_helped INTEGER DEFAULT 0,
            times_warned INTEGER DEFAULT 0, tags TEXT DEFAULT '[]',
            projects_seen TEXT DEFAULT '[]', source TEXT DEFAULT 'manual',
            review_flag INTEGER DEFAULT 0, last_used DATETIME,
            created_at DATETIME, updated_at DATETIME,
            UNIQUE(workspace_id, pattern)
        );
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY, session_id TEXT UNIQUE,
            workspace_id TEXT, warnings_injected TEXT DEFAULT '[]',
            started_at DATETIME, ended_at DATETIME,
            failures_encountered INTEGER DEFAULT 0,
            q_updates_count INTEGER DEFAULT 0,
            promotions_count INTEGER DEFAULT 0
        );
    """)

    _migrate(conn, from_version=2)

    # Verify active column exists on failures
    conn.execute("SELECT active FROM failures LIMIT 0")

    # Verify team_runs table exists
    conn.execute("INSERT INTO team_runs (workspace_id, run_id) VALUES ('ws', 'r1')")

    # Verify version updated (migrates through to v5)
    version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
    assert version == 5
    conn.close()


def test_migration_v1_to_v5():
    """Create v1 schema, migrate through v2, v3, v4, v5."""
    from forge.storage.db import _migrate

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version VALUES (1);
        CREATE TABLE failures (
            id INTEGER PRIMARY KEY, workspace_id TEXT, pattern TEXT,
            observed_error TEXT, likely_cause TEXT, avoid_hint TEXT NOT NULL,
            hint_quality TEXT NOT NULL, q REAL DEFAULT 0.5,
            times_seen INTEGER DEFAULT 1, times_helped INTEGER DEFAULT 0,
            times_warned INTEGER DEFAULT 0, tags TEXT DEFAULT '[]',
            projects_seen TEXT DEFAULT '[]', source TEXT DEFAULT 'manual',
            review_flag INTEGER DEFAULT 0, last_used DATETIME,
            created_at DATETIME, updated_at DATETIME,
            UNIQUE(workspace_id, pattern)
        );
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY, session_id TEXT UNIQUE,
            workspace_id TEXT, warnings_injected TEXT DEFAULT '[]',
            started_at DATETIME, ended_at DATETIME
        );
    """)

    _migrate(conn, from_version=1)

    # Verify columns added in v2
    conn.execute("SELECT failures_encountered FROM sessions LIMIT 0")

    # Verify columns added in v3
    conn.execute("SELECT active FROM failures LIMIT 0")
    conn.execute("INSERT INTO team_runs (workspace_id, run_id) VALUES ('ws', 'r1')")

    # Verify version updated (migrates through to v5)
    version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
    assert version == 5

    # Verify v4: experiments table and session extensions
    conn.execute("SELECT id FROM experiments LIMIT 0")
    conn.execute("SELECT config_hash, document_hash, unified_fitness FROM sessions LIMIT 0")

    # Verify v5: model_choices and agents tables
    conn.execute("SELECT id FROM model_choices LIMIT 0")
    conn.execute("SELECT agent_id FROM agents LIMIT 0")
    conn.close()


# ============================================================================
# 4. Dedup edge cases
# ============================================================================


def test_dedup_find_duplicates_no_crash_without_embeddings(db):
    """find_duplicates should not crash when no embeddings exist."""
    # No embeddings stored, should return empty
    result = find_duplicates(db, "ws")
    assert result == []


def test_dedup_find_duplicates_empty_workspace(db):
    """find_duplicates on empty workspace should return empty list."""
    result = find_duplicates(db, "nonexistent_ws")
    assert result == []


# ============================================================================
# 5. Extractor edge cases
# ============================================================================


def test_extractor_parse_empty_content():
    """Parsing empty JSON array should return empty list."""
    assert _parse_extraction_response("[]") == []


def test_extractor_parse_nested_brackets():
    """Parsing text with nested brackets and JSON should find the array."""
    # The parser looks for [...] boundary to extract JSON
    # It finds multiple brackets and tries to parse; with nested brackets it might fail
    text = 'before [{"type": "failure", "pattern": "x", "hint": "y", "quality": "preventable"}]'
    results = _parse_extraction_response(text)
    assert len(results) == 1
    assert results[0]["type"] == "failure"
    assert results[0]["pattern"] == "x"


def test_extractor_parse_markdown_code_block():
    """Parsing markdown code block should extract JSON."""
    text = """```json
[{"type": "failure", "pattern": "test_pat", "hint": "test hint", "quality": "preventable"}]
```"""
    results = _parse_extraction_response(text)
    assert len(results) == 1
    assert results[0]["pattern"] == "test_pat"


def test_extractor_parse_multiple_items():
    """Parsing multiple items should return all valid ones."""
    text = json.dumps([
        {"type": "failure", "pattern": "p1", "hint": "h1", "quality": "near_miss"},
        {"type": "decision", "statement": "s1", "rationale": "r1"},
        {"type": "failure", "pattern": "p2", "hint": "h2", "quality": "preventable"},
    ])
    results = _parse_extraction_response(text)
    assert len(results) == 3


def test_extractor_parse_invalid_quality():
    """Invalid quality should default to 'preventable'."""
    text = json.dumps([
        {"type": "failure", "pattern": "p", "hint": "h", "quality": "invalid"},
    ])
    results = _parse_extraction_response(text)
    assert results[0]["quality"] == "preventable"


def test_extractor_parse_missing_pattern():
    """Missing pattern should skip the failure."""
    text = json.dumps([
        {"type": "failure", "hint": "h"},
        {"type": "failure", "pattern": "p", "hint": "h"},
    ])
    results = _parse_extraction_response(text)
    assert len(results) == 1
    assert results[0]["pattern"] == "p"


def test_extractor_parse_missing_statement():
    """Missing statement should skip the decision."""
    text = json.dumps([
        {"type": "decision", "rationale": "r"},
        {"type": "decision", "statement": "s", "rationale": "r"},
    ])
    results = _parse_extraction_response(text)
    assert len(results) == 1
    assert results[0]["statement"] == "s"


def test_extractor_parse_malformed_json():
    """Malformed JSON should return empty list."""
    results = _parse_extraction_response("not valid json")
    assert results == []


def test_extractor_parse_not_array():
    """Non-array JSON should return empty list."""
    text = json.dumps({"type": "failure", "pattern": "p"})
    results = _parse_extraction_response(text)
    assert results == []


# ============================================================================
# 6. Forge meta (key-value store) tests
# ============================================================================


def test_meta_set_get(db):
    """Set and get metadata should work."""
    set_meta(db, "test_key", "test_val")
    assert get_meta(db, "test_key") == "test_val"


def test_meta_upsert(db):
    """Setting same key twice should update the value."""
    set_meta(db, "k", "v1")
    set_meta(db, "k", "v2")
    assert get_meta(db, "k") == "v2"


def test_meta_get_nonexistent(db):
    """Getting nonexistent key should return None."""
    assert get_meta(db, "nonexistent") is None


def test_meta_set_empty_value(db):
    """Setting empty string should work."""
    set_meta(db, "k", "")
    assert get_meta(db, "k") == ""


def test_meta_with_json_value(db):
    """Meta can store JSON values."""
    data = {"key": "value", "nested": {"a": 1}}
    json_str = json.dumps(data)
    set_meta(db, "json_key", json_str)
    retrieved = get_meta(db, "json_key")
    assert json.loads(retrieved) == data


# ============================================================================
# 7. Output analyzer edge cases
# ============================================================================


def test_normalize_empty_command():
    """Empty command should normalize to '*'."""
    assert _normalize_command("") == "*"


def test_normalize_whitespace_only():
    """Whitespace-only command should normalize to '*'."""
    assert _normalize_command("   ") == "*"


def test_normalize_none_type():
    """None command should normalize to '*'."""
    assert _normalize_command(None) == "*"


def test_normalize_simple_commands():
    """Simple commands should be preserved."""
    assert _normalize_command("git status") == "git status"
    assert _normalize_command("git log") == "git log"
    assert _normalize_command("ls") == "ls"
    assert _normalize_command("pwd") == "pwd"


def test_normalize_command_with_args():
    """Commands with args should be normalized."""
    assert _normalize_command("pytest tests/test_foo.py -v") == "pytest *"
    assert _normalize_command("grep -r pattern src/") == "grep *"
    assert _normalize_command("cat src/foo.py") == "cat *"


def test_normalize_command_with_path():
    """Commands with paths should extract base name."""
    assert _normalize_command("./scripts/test.py") == "test.py *"
    assert _normalize_command("/usr/bin/python3") == "python3 *"


def test_normalize_git_subcommands():
    """Git subcommands should be preserved."""
    assert _normalize_command("git status") == "git status"
    assert _normalize_command("git log -10") == "git log"
    assert _normalize_command("git diff HEAD~1") == "git diff"
    assert _normalize_command("git show abc123") == "git show"
    # Other git subcommands should be collapsed
    assert _normalize_command("git remote -v") == "git *"


def test_estimate_useful_empty():
    """Empty output should estimate 0 useful chars."""
    assert _estimate_useful_portion("", "anything") == 0


def test_estimate_useful_none():
    """None output should estimate 0 useful chars."""
    assert _estimate_useful_portion(None, "anything") == 0


def test_estimate_useful_pytest():
    """pytest output should extract summary lines."""
    output = """
test_foo.py::test_a PASSED
test_foo.py::test_b FAILED
test_foo.py::test_c SKIPPED
=== 1 passed, 1 failed, 1 skipped in 0.5s ===
"""
    useful = _estimate_useful_portion(output, "pytest tests/")
    assert useful > 0
    # The function returns at least 200 chars for pytest or 20% estimate
    assert useful >= 200


def test_estimate_useful_grep():
    """grep output should estimate useful portion."""
    output = "line1\nline2\nline3\nline4\nline5"
    useful = _estimate_useful_portion(output, "grep pattern file")
    assert useful > 0
    # The function returns at least 100 chars for grep or actual useful lines
    assert useful >= 100


def test_estimate_useful_git_status():
    """git status output should be fully useful."""
    output = """On branch main
Your branch is up to date with 'origin/main'.

nothing to commit, working tree clean"""
    useful = _estimate_useful_portion(output, "git status")
    assert useful == len(output)


def test_estimate_useful_git_log():
    """git log should estimate limited useful portion."""
    output = "\n".join([f"commit abc{i}" for i in range(100)])
    useful = _estimate_useful_portion(output, "git log")
    assert useful < len(output)


def test_estimate_useful_cat():
    """cat output should estimate first lines as useful."""
    output = "\n".join([f"line {i}" for i in range(100)])
    useful = _estimate_useful_portion(output, "cat large_file.txt")
    assert useful <= len(output)
    assert useful > 0


def test_estimate_useful_small_output():
    """Small outputs should estimate as mostly useful."""
    output = "one two three"
    useful = _estimate_useful_portion(output, "some command")
    assert useful == len(output)


def test_estimate_useful_large_output():
    """Large outputs (>2000 chars) should estimate 20%."""
    output = "x" * 5000
    useful = _estimate_useful_portion(output, "unknown command")
    assert useful == int(5000 * 0.2)


# ============================================================================
# 8. Integration tests
# ============================================================================


def test_knowledge_lifecycle(db):
    """Test complete knowledge lifecycle."""
    k = Knowledge(workspace_id="proj", title="tip", content="content", q=0.6, tags=["tag1"])
    kid = insert_knowledge(db, k)

    result = get_knowledge_by_id(db, kid, "proj")
    assert result.title == "tip"
    assert result.q == 0.6
    assert result.tags == ["tag1"]

    result.q = 0.9
    result.tags.append("tag2")
    update_knowledge(db, result)

    updated = get_knowledge_by_id(db, kid, "proj")
    assert updated.q == 0.9
    assert "tag2" in updated.tags


def test_rule_lifecycle(db):
    """Test complete rule lifecycle."""
    r = Rule(
        workspace_id="proj",
        rule_text="Never commit without tests",
        scope="git",
        enforcement_mode="warn",
    )
    rid = insert_rule(db, r)

    result = get_rule_by_id(db, rid, "proj")
    assert result.rule_text == "Never commit without tests"
    assert result.enforcement_mode == "warn"


def test_team_run_lifecycle(db):
    """Test complete team run lifecycle."""
    tr = TeamRun(
        workspace_id="proj",
        run_id="run-123",
        complexity="COMPLEX",
        team_config="sonnet:2",
    )
    tid = insert_team_run(db, tr)

    result = get_team_run(db, "run-123")
    assert result.complexity == "COMPLEX"
    assert result.verdict is None

    result.verdict = "SUCCESS"
    result.success_rate = 0.98
    update_team_run(db, result)

    updated = get_team_run(db, "run-123")
    assert updated.verdict == "SUCCESS"
    assert updated.success_rate == 0.98


def test_config_with_real_file(tmp_path):
    """Test loading config from real YAML file."""
    config_file = tmp_path / "config.yml"
    config_file.write_text("""
alpha: 0.2
max_tokens: 5000
promote_threshold: 3
lambda_weight: 0.7
""")

    config = load_config(config_file)
    assert config.alpha == 0.2
    assert config.max_tokens == 5000
    assert config.promote_threshold == 3
    assert config.lambda_weight == 0.7


def test_config_partial_override(tmp_path):
    """Test loading config with partial overrides."""
    config_file = tmp_path / "config.yml"
    config_file.write_text("""
alpha: 0.05
""")

    config = load_config(config_file)
    assert config.alpha == 0.05
    # Other values should use defaults
    assert config.max_tokens == 3000
    assert config.promote_threshold == 2


def test_meta_multiple_keys(db):
    """Test storing multiple meta keys."""
    set_meta(db, "key1", "val1")
    set_meta(db, "key2", "val2")
    set_meta(db, "key3", "val3")

    assert get_meta(db, "key1") == "val1"
    assert get_meta(db, "key2") == "val2"
    assert get_meta(db, "key3") == "val3"


def test_extractor_with_defaults():
    """Test that extractor fills in defaults for optional fields."""
    text = json.dumps([
        {"type": "failure", "pattern": "p", "hint": "h"},
        {"type": "decision", "statement": "s"},
    ])
    results = _parse_extraction_response(text)

    # Failure should have default quality
    assert results[0]["quality"] == "preventable"
    assert results[0]["tags"] == []

    # Decision should have default rationale
    assert results[1]["rationale"] == ""
    assert results[1]["tags"] == []
