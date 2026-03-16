"""Tests for forge.core.context."""

import pytest

from forge.config import ForgeConfig
from forge.core.context import (
    build_context,
    format_decisions,
    format_knowledge,
    format_l0,
    format_l1,
    format_rules,
)
from forge.storage.models import Decision, Failure, Knowledge, Rule


def _make_failure(
    pattern: str,
    q: float = 0.5,
    hint_quality: str = "near_miss",
    times_seen: int = 3,
    times_helped: int = 1,
    avoid_hint: str = "avoid doing X",
) -> Failure:
    return Failure(
        workspace_id="test",
        pattern=pattern,
        avoid_hint=avoid_hint,
        hint_quality=hint_quality,
        q=q,
        times_seen=times_seen,
        times_helped=times_helped,
    )


def _make_decision(
    statement: str,
    q: float = 0.5,
    status: str = "active",
) -> Decision:
    return Decision(
        workspace_id="test",
        statement=statement,
        q=q,
        status=status,
    )


def _make_knowledge(title: str, q: float = 0.5) -> Knowledge:
    return Knowledge(
        workspace_id="test",
        title=title,
        content="some content",
        q=q,
    )


def _make_rule(
    rule_text: str,
    enforcement_mode: str = "warn",
    active: bool = True,
) -> Rule:
    return Rule(
        workspace_id="test",
        rule_text=rule_text,
        enforcement_mode=enforcement_mode,
        active=active,
    )


# --- format_l0 ---

def test_format_l0_contains_warn_tag():
    result = format_l0([_make_failure("connection_error")])
    assert "[WARN]" in result


def test_format_l0_contains_pattern():
    result = format_l0([_make_failure("connection_error")])
    assert "connection_error" in result


def test_format_l0_contains_q_value():
    result = format_l0([_make_failure("err", q=0.75)])
    assert "Q:0.75" in result


def test_format_l0_contains_seen_and_helped():
    result = format_l0([_make_failure("err", times_seen=5, times_helped=2)])
    assert "seen:5" in result
    assert "helped:2" in result


def test_format_l0_contains_hint_quality():
    result = format_l0([_make_failure("err", hint_quality="preventable")])
    assert "preventable" in result


def test_format_l0_empty():
    assert format_l0([]) == ""


def test_format_l0_multiple_lines():
    failures = [_make_failure("err_a"), _make_failure("err_b")]
    lines = format_l0(failures).splitlines()
    assert len(lines) == 2


# --- format_l1 ---

def test_format_l1_includes_hint():
    result = format_l1([_make_failure("err", avoid_hint="check firewall")])
    assert "check firewall" in result


def test_format_l1_includes_warn_tag():
    result = format_l1([_make_failure("err")])
    assert "[WARN]" in result


def test_format_l1_more_lines_than_l0():
    f = _make_failure("err")
    l0_lines = format_l0([f]).splitlines()
    l1_lines = format_l1([f]).splitlines()
    assert len(l1_lines) > len(l0_lines)


def test_format_l1_empty():
    assert format_l1([]) == ""


# --- format_rules ---

def test_format_rules_contains_rule_tag():
    result = format_rules([_make_rule("no direct DB calls")])
    assert "[RULE]" in result


def test_format_rules_contains_text():
    result = format_rules([_make_rule("no direct DB calls")])
    assert "no direct DB calls" in result


def test_format_rules_contains_enforcement_mode():
    result = format_rules([_make_rule("check types", enforcement_mode="block")])
    assert "block" in result


def test_format_rules_empty():
    assert format_rules([]) == ""


def test_format_rules_multiple():
    rules = [_make_rule("rule A"), _make_rule("rule B")]
    lines = format_rules(rules).splitlines()
    assert len(lines) == 2


# --- build_context ---

def test_build_context_empty_returns_empty():
    config = ForgeConfig()
    assert build_context([], [], config) == ""


def test_build_context_with_failures_has_warn():
    config = ForgeConfig()
    result = build_context([_make_failure("err")], [], config)
    assert "[WARN]" in result


def test_build_context_with_rules_has_rule():
    config = ForgeConfig()
    result = build_context([], [_make_rule("use transactions")], config)
    assert "[RULE]" in result


def test_build_context_inactive_rules_excluded():
    config = ForgeConfig()
    rules = [_make_rule("active rule"), _make_rule("inactive rule", active=False)]
    result = build_context([], rules, config)
    assert "active rule" in result
    assert "inactive rule" not in result


def test_build_context_l0_max_entries():
    config = ForgeConfig(l0_max_entries=2)
    failures = [_make_failure(f"err_{i}") for i in range(5)]
    result = build_context(failures, [], config)
    # L0는 2개만 출력, L1은 l1_project_entries+l1_global_entries
    l0_section = result.split("## Top Failures")[0] if "## Top Failures" in result else result
    warn_count = l0_section.count("[WARN]")
    assert warn_count <= 2


def test_build_context_rules_max_entries():
    config = ForgeConfig(rules_max_entries=2)
    rules = [_make_rule(f"rule {i}") for i in range(5)]
    result = build_context([], rules, config)
    assert result.count("[RULE]") == 2


def test_build_context_l1_sorted_by_q():
    config = ForgeConfig(l1_project_entries=1, l1_global_entries=0)
    failures = [
        _make_failure("low_q", q=0.2),
        _make_failure("high_q", q=0.9),
    ]
    result = build_context(failures, [], config)
    # L1에는 높은 Q가 포함되어야 함
    if "## Top Failures" in result:
        l1_section = result.split("## Top Failures")[1]
        assert "high_q" in l1_section


# --- format_decisions ---

def test_format_decisions_contains_decision_tag():
    result = format_decisions([_make_decision("use SQLite")])
    assert "[DECISION]" in result


def test_format_decisions_contains_statement():
    result = format_decisions([_make_decision("use SQLite")])
    assert "use SQLite" in result


def test_format_decisions_contains_q():
    result = format_decisions([_make_decision("use SQLite", q=0.75)])
    assert "Q:0.75" in result


def test_format_decisions_contains_status():
    result = format_decisions([_make_decision("use SQLite", status="active")])
    assert "active" in result


def test_format_decisions_empty():
    assert format_decisions([]) == ""


def test_format_decisions_multiple():
    decisions = [_make_decision("dec A"), _make_decision("dec B")]
    assert len(format_decisions(decisions).splitlines()) == 2


# --- format_knowledge ---

def test_format_knowledge_contains_knowledge_tag():
    result = format_knowledge([_make_knowledge("auth pattern")])
    assert "[KNOWLEDGE]" in result


def test_format_knowledge_contains_title():
    result = format_knowledge([_make_knowledge("auth pattern")])
    assert "auth pattern" in result


def test_format_knowledge_contains_q():
    result = format_knowledge([_make_knowledge("auth pattern", q=0.88)])
    assert "Q:0.88" in result


def test_format_knowledge_empty():
    assert format_knowledge([]) == ""


def test_format_knowledge_multiple():
    items = [_make_knowledge("k1"), _make_knowledge("k2")]
    assert len(format_knowledge(items).splitlines()) == 2


# --- build_context with decisions and knowledge ---

def test_build_context_with_decisions():
    config = ForgeConfig()
    result = build_context([], [], config, decisions=[_make_decision("use SQLite")])
    assert "[DECISION]" in result
    assert "use SQLite" in result


def test_build_context_non_active_decisions_excluded():
    config = ForgeConfig()
    decisions = [
        _make_decision("active dec", status="active"),
        _make_decision("old dec", status="superseded"),
    ]
    result = build_context([], [], config, decisions=decisions)
    assert "active dec" in result
    assert "old dec" not in result


def test_build_context_with_knowledge():
    config = ForgeConfig()
    result = build_context([], [], config, knowledge_list=[_make_knowledge("auth pattern")])
    assert "[KNOWLEDGE]" in result
    assert "auth pattern" in result


def test_build_context_decisions_before_rules():
    config = ForgeConfig()
    result = build_context(
        [],
        [_make_rule("a rule")],
        config,
        decisions=[_make_decision("a decision")],
    )
    assert result.index("[DECISION]") < result.index("[RULE]")


def test_build_context_knowledge_before_rules():
    config = ForgeConfig()
    result = build_context(
        [],
        [_make_rule("a rule")],
        config,
        knowledge_list=[_make_knowledge("some knowledge")],
    )
    assert result.index("[KNOWLEDGE]") < result.index("[RULE]")


def test_build_context_no_decisions_no_knowledge_unchanged():
    config = ForgeConfig()
    result = build_context([], [], config)
    assert "[DECISION]" not in result
    assert "[KNOWLEDGE]" not in result
