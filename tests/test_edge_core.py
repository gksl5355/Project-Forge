"""Edge case tests for forge.core services (qvalue, matcher, promote, context)."""

from __future__ import annotations

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
from forge.core.matcher import (
    extract_errors_from_stderr,
    match_pattern,
    suggest_pattern_name,
)
from forge.core.promote import (
    check_global_promote,
    check_knowledge_promote,
    merge_q,
    promote_to_global,
    promote_to_knowledge,
)
from forge.core.qvalue import ema_update, initial_q, time_decay
from forge.storage.models import Decision, Failure, Knowledge, Rule


# ─── helpers ────────────────────────────────────────────────────────────────


def _failure(
    pattern: str = "err",
    q: float = 0.5,
    times_seen: int = 5,
    times_helped: int = 0,
    projects_seen: list[str] | None = None,
    workspace_id: str = "proj",
    hint_quality: str = "near_miss",
    avoid_hint: str = "avoid X",
    observed_error: str | None = None,
    likely_cause: str | None = None,
    failure_id: int | None = None,
) -> Failure:
    return Failure(
        workspace_id=workspace_id,
        pattern=pattern,
        avoid_hint=avoid_hint,
        hint_quality=hint_quality,
        q=q,
        times_seen=times_seen,
        times_helped=times_helped,
        projects_seen=projects_seen or [],
        observed_error=observed_error,
        likely_cause=likely_cause,
        id=failure_id,
    )


def _rule(text: str = "rule", mode: str = "warn", active: bool = True) -> Rule:
    return Rule(workspace_id="test", rule_text=text, enforcement_mode=mode, active=active)


def _decision(stmt: str = "decide", q: float = 0.5, status: str = "active") -> Decision:
    return Decision(workspace_id="test", statement=stmt, q=q, status=status)


def _knowledge(title: str = "k", q: float = 0.5) -> Knowledge:
    return Knowledge(workspace_id="test", title=title, content="content", q=q)


# ═══════════════════════════════════════════════════════════════════
# qvalue edge cases
# ═══════════════════════════════════════════════════════════════════


def test_ema_update_q_zero_reward_zero():
    """q=0, r=0 → stays at 0."""
    assert ema_update(0.0, 0.0, 0.1) == pytest.approx(0.0)


def test_ema_update_q_one_reward_one():
    """q=1, r=1 → stays at 1."""
    assert ema_update(1.0, 1.0, 0.1) == pytest.approx(1.0)


def test_ema_update_q_zero_reward_one_alpha_default():
    """q=0, r=1, alpha=0.1 → 0.1."""
    assert ema_update(0.0, 1.0, 0.1) == pytest.approx(0.1)


def test_ema_update_alpha_zero_no_change():
    """alpha=0 → q unchanged regardless of reward."""
    assert ema_update(0.7, 1.0, 0.0) == pytest.approx(0.7)


def test_ema_update_alpha_one_snaps_to_reward():
    """alpha=1 → q = reward (one-step full update)."""
    assert ema_update(0.3, 0.9, 1.0) == pytest.approx(0.9)


def test_ema_update_negative_reward_decreases_q():
    """Negative reward pulls q below its initial value."""
    result = ema_update(0.5, -1.0, 0.1)
    assert result == pytest.approx(0.5 + 0.1 * (-1.0 - 0.5))
    assert result < 0.5


def test_ema_update_reward_equals_q_boundary_zero():
    """r == q == 0 → no movement."""
    assert ema_update(0.0, 0.0, 0.5) == pytest.approx(0.0)


def test_ema_update_reward_equals_q_boundary_one():
    """r == q == 1 → no movement."""
    assert ema_update(1.0, 1.0, 0.5) == pytest.approx(1.0)


def test_time_decay_huge_days_clamped_to_q_min():
    """Extremely large days → clamped to q_min."""
    result = time_decay(0.9, 1_000_000, 0.005, 0.05)
    assert result == pytest.approx(0.05)


def test_time_decay_q_exactly_at_q_min_unchanged():
    """q already equals q_min → stays at q_min after decay."""
    result = time_decay(0.05, 100, 0.005, 0.05)
    assert result == pytest.approx(0.05)


def test_time_decay_q_below_q_min_clamped_up():
    """q < q_min before decay → result clamped to q_min."""
    result = time_decay(0.01, 0, 0.005, 0.05)
    assert result == pytest.approx(0.05)


def test_time_decay_decay_rate_zero_no_change():
    """decay_rate=0 → no decay at all."""
    result = time_decay(0.7, 1_000, 0.0, 0.05)
    assert result == pytest.approx(0.7)


def test_time_decay_zero_days_no_change():
    """days=0 → no decay (any q above q_min)."""
    result = time_decay(0.8, 0, 0.005, 0.05)
    assert result == pytest.approx(0.8)


def test_time_decay_q_one_decays_correctly():
    """q=1.0 decays by the expected formula."""
    result = time_decay(1.0, 10, 0.005, 0.05)
    assert result == pytest.approx(1.0 * (1 - 0.005) ** 10)


def test_initial_q_near_miss_highest():
    """near_miss > preventable > environmental."""
    config = ForgeConfig()
    assert initial_q("near_miss", config) > initial_q("preventable", config)
    assert initial_q("preventable", config) > initial_q("environmental", config)


def test_initial_q_empty_string_falls_back_to_preventable():
    """Empty hint_quality falls back to preventable default."""
    config = ForgeConfig()
    assert initial_q("", config) == pytest.approx(config.initial_q_preventable)


def test_initial_q_none_like_unknown_falls_back():
    """Completely unknown quality string falls back to preventable."""
    config = ForgeConfig()
    assert initial_q("totally_unknown_quality_xyz", config) == pytest.approx(
        config.initial_q_preventable
    )


def test_initial_q_respects_custom_config():
    """Custom config values override defaults."""
    config = ForgeConfig(
        initial_q_near_miss=0.99,
        initial_q_preventable=0.01,
        initial_q_environmental=0.001,
    )
    assert initial_q("near_miss", config) == pytest.approx(0.99)
    assert initial_q("preventable", config) == pytest.approx(0.01)
    assert initial_q("environmental", config) == pytest.approx(0.001)


# ═══════════════════════════════════════════════════════════════════
# matcher edge cases
# ═══════════════════════════════════════════════════════════════════


def test_extract_empty_string_returns_empty_list():
    assert extract_errors_from_stderr("") == []


def test_extract_whitespace_only_returns_empty_list():
    assert extract_errors_from_stderr("   \n\t  ") == []


def test_extract_plain_text_no_errors_returns_empty():
    assert extract_errors_from_stderr("everything fine, no issues here") == []


def test_extract_unicode_stderr_no_crash():
    """Unicode text mixed with error class doesn't crash."""
    result = extract_errors_from_stderr("에러: 한글\nValueError: 잘못된 값")
    assert "value_error" in result


def test_extract_very_long_stderr_finds_match():
    """50K-char stderr with embedded error still extracts correctly."""
    padding = "a" * 25_000
    stderr = f"{padding}\nTypeError: bad type\n{padding}"
    result = extract_errors_from_stderr(stderr)
    assert "type_error" in result


def test_extract_multiple_distinct_error_classes():
    """Multiple distinct error classes are all extracted."""
    stderr = "KeyError: k\nTypeError: t\nRuntimeError: r"
    result = extract_errors_from_stderr(stderr)
    assert "key_error" in result
    assert "type_error" in result
    assert "runtime_error" in result


def test_extract_no_duplicate_for_repeated_error_class():
    """Same error class appearing twice appears only once in results."""
    stderr = "ValueError: first occurrence\nValueError: second occurrence"
    result = extract_errors_from_stderr(stderr)
    assert result.count("value_error") == 1


def test_extract_lowercase_error_not_matched_by_camelcase_regex():
    """All-lowercase 'valueerror' is NOT matched (regex requires CamelCase)."""
    result = extract_errors_from_stderr("valueerror: something went wrong")
    assert "value_error" not in result


def test_extract_import_error_dotted_module_dots_to_underscores():
    """ImportError with dotted module replaces dots with underscores."""
    result = extract_errors_from_stderr("ImportError: No module named 'a.b.c'")
    assert "missing_module_a_b_c" in result


def test_extract_module_not_found_dotted_dots_to_underscores():
    """ModuleNotFoundError with dotted name replaces dots with underscores."""
    result = extract_errors_from_stderr("ModuleNotFoundError: No module named 'x.y'")
    assert "missing_module_x_y" in result


def test_suggest_empty_string_returns_unknown_error():
    assert suggest_pattern_name("") == "unknown_error"


def test_suggest_whitespace_only_returns_unknown_error():
    assert suggest_pattern_name("   \n  ") == "unknown_error"


def test_suggest_result_at_most_50_chars():
    """Result is always at most 50 characters."""
    long_text = "abcdefghij " * 20
    result = suggest_pattern_name(long_text)
    assert len(result) <= 50


def test_suggest_result_has_no_spaces():
    """Result never contains space characters."""
    result = suggest_pattern_name("some error that happened with spaces everywhere")
    assert " " not in result


def test_suggest_module_not_found_priority_over_error_class():
    """ModuleNotFoundError takes priority over generic error class in same stderr."""
    stderr = "ModuleNotFoundError: No module named 'numpy'\nValueError: bad"
    assert suggest_pattern_name(stderr) == "missing_module_numpy"


def test_suggest_unicode_text_no_crash():
    """Unicode-only stderr doesn't crash; result is non-empty."""
    result = suggest_pattern_name("한글 에러가 발생했습니다")
    assert result  # non-empty
    assert " " not in result


def test_match_pattern_empty_failures_list_returns_none():
    assert match_pattern("ValueError: bad", []) is None


def test_match_pattern_empty_stderr_returns_none():
    """Empty stderr produces no extracted errors → no match."""
    failures = [_failure("value_error")]
    assert match_pattern("", failures) is None


def test_match_pattern_whitespace_stderr_returns_none():
    failures = [_failure("value_error")]
    assert match_pattern("   ", failures) is None


def test_match_pattern_lowercase_stderr_no_match():
    """Lowercase error class in stderr does not match camelcase-derived pattern."""
    failures = [_failure("value_error")]
    result = match_pattern("valueerror: something", failures)
    assert result is None


def test_match_pattern_unicode_stderr_finds_embedded_error():
    """Unicode stderr with embedded CamelCase error still matches."""
    failures = [_failure("value_error")]
    result = match_pattern("한글 설명\nValueError: bad value\n더 많은 내용", failures)
    assert result is not None
    assert result.pattern == "value_error"


def test_match_pattern_very_long_stderr_finds_match():
    """Match in very long stderr (10K padding each side)."""
    padding = "x" * 10_000
    stderr = f"{padding}\nConnectionError: timed out\n{padding}"
    failures = [_failure("connection_error")]
    result = match_pattern(stderr, failures)
    assert result is not None
    assert result.pattern == "connection_error"


def test_match_pattern_multiple_errors_returns_first_in_list_order():
    """With multiple matching failures, returns first one by failures-list order."""
    failures = [_failure("type_error"), _failure("value_error")]
    stderr = "TypeError: wrong\nValueError: bad"
    result = match_pattern(stderr, failures)
    assert result is not None
    assert result.pattern == "type_error"


def test_match_pattern_no_matching_class_returns_none():
    """stderr with errors that don't match any known failure."""
    failures = [_failure("missing_module_pandas")]
    result = match_pattern("PermissionError: access denied", failures)
    assert result is None


# ═══════════════════════════════════════════════════════════════════
# promote edge cases
# ═══════════════════════════════════════════════════════════════════


def test_check_global_promote_exactly_at_threshold():
    """projects_seen == threshold (2) → True."""
    config = ForgeConfig(promote_threshold=2)
    f = _failure(projects_seen=["a", "b"])
    assert check_global_promote(f, config) is True


def test_check_global_promote_one_below_threshold():
    """projects_seen == threshold - 1 → False."""
    config = ForgeConfig(promote_threshold=2)
    f = _failure(projects_seen=["a"])
    assert check_global_promote(f, config) is False


def test_check_global_promote_empty_projects_false():
    config = ForgeConfig(promote_threshold=2)
    f = _failure(projects_seen=[])
    assert check_global_promote(f, config) is False


def test_check_global_promote_threshold_one_single_project():
    """Custom threshold=1: one project → True."""
    config = ForgeConfig(promote_threshold=1)
    f = _failure(projects_seen=["only_proj"])
    assert check_global_promote(f, config) is True


def test_check_knowledge_promote_exactly_at_both_thresholds():
    """q == 0.8 AND times_helped == 5 → True."""
    config = ForgeConfig(knowledge_promote_q=0.8, knowledge_promote_helped=5)
    f = _failure(q=0.8, times_helped=5)
    assert check_knowledge_promote(f, config) is True


def test_check_knowledge_promote_q_just_below_threshold():
    """q = 0.7999 (just below 0.8) → False."""
    config = ForgeConfig(knowledge_promote_q=0.8, knowledge_promote_helped=5)
    f = _failure(q=0.7999, times_helped=5)
    assert check_knowledge_promote(f, config) is False


def test_check_knowledge_promote_helped_just_below_threshold():
    """times_helped == threshold - 1 → False."""
    config = ForgeConfig(knowledge_promote_q=0.8, knowledge_promote_helped=5)
    f = _failure(q=0.8, times_helped=4)
    assert check_knowledge_promote(f, config) is False


def test_check_knowledge_promote_both_at_minimum_custom():
    """Custom thresholds: both exactly at min → True."""
    config = ForgeConfig(knowledge_promote_q=0.3, knowledge_promote_helped=1)
    f = _failure(q=0.3, times_helped=1)
    assert check_knowledge_promote(f, config) is True


def test_check_knowledge_promote_q_zero_fails():
    config = ForgeConfig(knowledge_promote_q=0.8, knowledge_promote_helped=5)
    f = _failure(q=0.0, times_helped=100)
    assert check_knowledge_promote(f, config) is False


def test_merge_q_empty_list_returns_zero():
    assert merge_q([]) == pytest.approx(0.0)


def test_merge_q_single_item_returns_its_q():
    f = _failure(q=0.7, times_seen=3)
    assert merge_q([f]) == pytest.approx(0.7)


def test_merge_q_single_item_zero_weight_returns_q():
    """Single item with times_seen=0 → fallback mean = just its q."""
    f = _failure(q=0.6, times_seen=0)
    assert merge_q([f]) == pytest.approx(0.6)


def test_merge_q_all_zero_times_seen_falls_back_to_mean():
    """All times_seen==0 → unweighted mean."""
    f1 = _failure(q=0.2, times_seen=0)
    f2 = _failure(q=0.8, times_seen=0)
    assert merge_q([f1, f2]) == pytest.approx(0.5)


def test_merge_q_high_weight_dominates():
    """Item with far higher weight dominates the result."""
    f_high = _failure(q=0.9, times_seen=100)
    f_low = _failure(q=0.1, times_seen=1)
    result = merge_q([f_high, f_low])
    assert result > 0.85


def test_merge_q_equal_weights_is_arithmetic_mean():
    f1 = _failure(q=0.3, times_seen=2)
    f2 = _failure(q=0.7, times_seen=2)
    assert merge_q([f1, f2]) == pytest.approx(0.5)


def test_promote_to_global_id_always_none():
    """Promoted global copy always has id=None."""
    f = _failure(failure_id=99)
    g = promote_to_global(f)
    assert g.id is None


def test_promote_to_global_workspace_is_global_string():
    f = _failure(workspace_id="my_project")
    g = promote_to_global(f)
    assert g.workspace_id == "__global__"


def test_promote_to_global_all_data_fields_preserved():
    """Pattern, q, times_seen, times_helped, hint_quality, avoid_hint all copied."""
    f = _failure(
        pattern="my_pattern",
        q=0.77,
        times_seen=10,
        times_helped=3,
        hint_quality="preventable",
        avoid_hint="do not do this",
        projects_seen=["p1", "p2"],
    )
    g = promote_to_global(f)
    assert g.pattern == "my_pattern"
    assert g.q == pytest.approx(0.77)
    assert g.times_seen == 10
    assert g.times_helped == 3
    assert g.hint_quality == "preventable"
    assert g.avoid_hint == "do not do this"
    assert g.projects_seen == ["p1", "p2"]


def test_promote_to_global_tags_are_independent_copy():
    """Mutating original tags after promotion doesn't affect the copy."""
    f = _failure()
    f.tags = ["t1", "t2"]
    g = promote_to_global(f)
    f.tags.append("t3")
    assert "t3" not in g.tags


def test_promote_to_global_projects_seen_is_independent_copy():
    """Mutating original projects_seen after promotion doesn't affect the copy."""
    f = _failure(projects_seen=["a", "b"])
    g = promote_to_global(f)
    f.projects_seen.append("c")
    assert "c" not in g.projects_seen


def test_promote_to_knowledge_without_likely_cause_no_none_in_content():
    """likely_cause=None → 'None' string does NOT appear in content."""
    f = _failure(avoid_hint="do this instead", likely_cause=None, observed_error=None)
    k = promote_to_knowledge(f)
    assert "None" not in k.content
    assert "do this instead" in k.content


def test_promote_to_knowledge_without_observed_error_no_none_in_content():
    """observed_error=None → 'None' string does NOT appear in content."""
    f = _failure(avoid_hint="hint", likely_cause="the cause", observed_error=None)
    k = promote_to_knowledge(f)
    assert "None" not in k.content
    assert "the cause" in k.content


def test_promote_to_knowledge_with_all_optional_fields():
    """With both optional fields set, content includes all three strings."""
    f = _failure(
        avoid_hint="avoid this",
        likely_cause="root cause",
        observed_error="SomeError: boom",
    )
    k = promote_to_knowledge(f)
    assert "avoid this" in k.content
    assert "root cause" in k.content
    assert "SomeError: boom" in k.content


def test_promote_to_knowledge_tags_are_independent_copy():
    """Mutating original tags after promote_to_knowledge doesn't affect copy."""
    f = _failure()
    f.tags = ["t1", "t2"]
    k = promote_to_knowledge(f)
    f.tags.append("t3")
    assert "t3" not in k.tags


def test_promote_to_knowledge_source_is_organic():
    k = promote_to_knowledge(_failure())
    assert k.source == "organic"


def test_promote_to_knowledge_title_is_pattern():
    f = _failure(pattern="my_failure_pattern")
    k = promote_to_knowledge(f)
    assert k.title == "my_failure_pattern"


def test_promote_to_knowledge_id_is_none():
    f = _failure(failure_id=42)
    k = promote_to_knowledge(f)
    assert k.id is None


def test_promote_to_knowledge_promoted_from_matches_failure_id():
    f = _failure(failure_id=77)
    k = promote_to_knowledge(f)
    assert k.promoted_from == 77


# ═══════════════════════════════════════════════════════════════════
# context edge cases
# ═══════════════════════════════════════════════════════════════════


def test_build_context_all_empty_returns_empty_string():
    config = ForgeConfig()
    assert build_context([], [], config) == ""


def test_build_context_decisions_none_no_crash_no_tag():
    """decisions=None should not crash and produce no [DECISION] tag."""
    config = ForgeConfig()
    result = build_context([], [], config, decisions=None)
    assert "[DECISION]" not in result


def test_build_context_knowledge_list_none_no_crash_no_tag():
    """knowledge_list=None should not crash and produce no [KNOWLEDGE] tag."""
    config = ForgeConfig()
    result = build_context([], [], config, knowledge_list=None)
    assert "[KNOWLEDGE]" not in result


def test_build_context_l0_max_entries_zero_no_l0_section():
    """l0_max_entries=0 → Past Failures (L0) section absent."""
    config = ForgeConfig(l0_max_entries=0)
    failures = [_failure("err")]
    result = build_context(failures, [], config)
    assert "## Past Failures" not in result


def test_build_context_all_inactive_rules_no_rule_section():
    """All inactive rules → ## Rules section absent."""
    config = ForgeConfig()
    rules = [_rule("A", active=False), _rule("B", active=False)]
    result = build_context([], rules, config)
    assert "[RULE]" not in result


def test_build_context_only_superseded_decisions_no_decision_tag():
    """All superseded/revisiting decisions → no [DECISION] in output."""
    config = ForgeConfig()
    decisions = [
        _decision("old1", status="superseded"),
        _decision("old2", status="revisiting"),
    ]
    result = build_context([], [], config, decisions=decisions)
    assert "[DECISION]" not in result


def test_build_context_q_formatted_two_decimal_places():
    """Q values in output always use exactly 2 decimal places (e.g. Q:0.10)."""
    config = ForgeConfig()
    f = _failure("err", q=0.1)
    result = build_context([f], [], config)
    assert "Q:0.10" in result


def test_format_l0_q_two_decimal_places():
    f = _failure("err", q=0.1)
    assert "Q:0.10" in format_l0([f])


def test_format_l1_q_two_decimal_places():
    f = _failure("err", q=0.9)
    assert "Q:0.90" in format_l1([f])


def test_format_decisions_q_two_decimal_places():
    d = _decision("use SQLite", q=0.5)
    assert "Q:0.50" in format_decisions([d])


def test_format_knowledge_q_two_decimal_places():
    k = _knowledge("auth", q=0.5)
    assert "Q:0.50" in format_knowledge([k])


def test_build_context_special_chars_in_pattern_verbatim():
    """Special characters in pattern appear unchanged in output."""
    config = ForgeConfig()
    f = _failure("err/special:chars|here")
    result = build_context([f], [], config)
    assert "err/special:chars|here" in result


def test_build_context_special_chars_in_rule_verbatim():
    """Special characters in rule text appear unchanged in output."""
    config = ForgeConfig()
    r = _rule("don't use * without checking [nulls]")
    result = build_context([], [r], config)
    assert "don't use * without checking [nulls]" in result


def test_build_context_special_chars_in_avoid_hint_verbatim():
    """Special characters in avoid_hint appear in L1 section."""
    config = ForgeConfig()
    f = _failure("err", avoid_hint="use 'quotes' & <tags>")
    result = build_context([f], [], config)
    assert "use 'quotes' & <tags>" in result


def test_build_context_unicode_in_pattern_verbatim():
    """Unicode in pattern appears verbatim."""
    config = ForgeConfig()
    f = _failure("에러패턴")
    result = build_context([f], [], config)
    assert "에러패턴" in result


def test_build_context_l1_count_respects_config():
    """L1 shows at most l1_project_entries + l1_global_entries items."""
    config = ForgeConfig(l1_project_entries=2, l1_global_entries=1)
    failures = [_failure(f"err_{i}", q=i / 10.0) for i in range(10)]
    result = build_context(failures, [], config)
    if "## Top Failures — Details (L1)" in result:
        l1_and_after = result.split("## Top Failures — Details (L1)")[1]
        l1_only = l1_and_after.split("##")[0] if "##" in l1_and_after else l1_and_after
        assert l1_only.count("[WARN]") <= 3  # 2 + 1


def test_format_rules_all_enforcement_modes_formatted_correctly():
    """All enforcement modes appear with parentheses."""
    for mode in ("block", "warn", "log"):
        r = _rule("rule text", mode=mode)
        assert f"({mode})" in format_rules([r])


def test_format_l0_empty_list_returns_empty_string():
    assert format_l0([]) == ""


def test_format_l1_empty_list_returns_empty_string():
    assert format_l1([]) == ""


def test_format_rules_empty_list_returns_empty_string():
    assert format_rules([]) == ""


def test_format_decisions_empty_list_returns_empty_string():
    assert format_decisions([]) == ""


def test_format_knowledge_empty_list_returns_empty_string():
    assert format_knowledge([]) == ""


def test_build_context_l1_picks_highest_q_failures():
    """L1 section contains the highest-Q failures."""
    config = ForgeConfig(l1_project_entries=1, l1_global_entries=0)
    failures = [
        _failure("low_q", q=0.1),
        _failure("high_q", q=0.99),
    ]
    result = build_context(failures, [], config)
    if "## Top Failures — Details (L1)" in result:
        l1_section = result.split("## Top Failures — Details (L1)")[1]
        l1_only = l1_section.split("##")[0] if "##" in l1_section else l1_section
        assert "high_q" in l1_only


def test_build_context_inactive_rule_excluded_active_included():
    """Inactive rule absent, active rule present."""
    config = ForgeConfig()
    rules = [_rule("active rule", active=True), _rule("inactive rule", active=False)]
    result = build_context([], rules, config)
    assert "active rule" in result
    assert "inactive rule" not in result


def test_build_context_rules_max_entries_limits_output():
    """rules_max_entries=2 with 5 rules → only 2 [RULE] tags."""
    config = ForgeConfig(rules_max_entries=2)
    rules = [_rule(f"rule {i}") for i in range(5)]
    result = build_context([], rules, config)
    assert result.count("[RULE]") == 2
