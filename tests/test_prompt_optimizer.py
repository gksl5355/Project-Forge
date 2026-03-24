"""Unit tests for forge/engines/prompt_optimizer.py + context.py A/B integration."""
from __future__ import annotations

import json
from datetime import datetime, UTC

import pytest

from forge.storage.models import Failure
from forge.engines.prompt_optimizer import (
    CONCISE_VARIANT,
    DETAILED_VARIANT,
    analyze_skill_directives,
    compute_injection_score,
    compute_skill_effectiveness,
    generate_ab_format,
    get_active_variant,
    get_best_format,
    list_low_quality_hints,
    record_format_outcome,
    score_hint_quality,
    suggest_hint_improvement,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_failure(
    pattern: str = "test_pattern",
    avoid_hint: str = "Use correct approach",
    hint_quality: str = "near_miss",
    q: float = 0.7,
    times_seen: int = 3,
    times_helped: int = 1,
    times_warned: int = 2,
    tags: list[str] | None = None,
) -> Failure:
    return Failure(
        workspace_id="ws1",
        pattern=pattern,
        avoid_hint=avoid_hint,
        hint_quality=hint_quality,
        q=q,
        times_seen=times_seen,
        times_helped=times_helped,
        times_warned=times_warned,
        tags=tags or [],
    )


def insert_failure(conn, workspace_id: str, pattern: str, avoid_hint: str,
                   hint_quality: str = "near_miss", q: float = 0.5,
                   times_warned: int = 0, times_helped: int = 0) -> None:
    conn.execute(
        """
        INSERT INTO failures (workspace_id, pattern, avoid_hint, hint_quality,
                              q, times_seen, times_warned, times_helped)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (workspace_id, pattern, avoid_hint, hint_quality, q, times_warned, times_helped),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# A/B Format Generation
# ---------------------------------------------------------------------------

class TestGenerateAbFormat:
    def test_concise_contains_pattern_and_q(self):
        f = make_failure(pattern="null_deref", q=0.75)
        result = generate_ab_format(f, "concise")
        assert "null_deref" in result
        assert "0.75" in result
        assert result.startswith("[WARN]")

    def test_detailed_contains_all_fields(self):
        f = make_failure(pattern="bad_import", hint_quality="preventable",
                         q=0.60, times_seen=5, times_helped=2,
                         avoid_hint="Import from correct module path")
        result = generate_ab_format(f, "detailed")
        assert "bad_import" in result
        assert "preventable" in result
        assert "0.60" in result
        assert "seen:5" in result
        assert "helped:2" in result
        assert "Import from correct module path" in result
        assert "last_seen=never" in result

    def test_default_falls_back_to_concise(self):
        f = make_failure()
        concise = generate_ab_format(f, "concise")
        default = generate_ab_format(f)  # default param = "concise"
        assert concise == default

    def test_hint_truncated_in_concise(self):
        long_hint = "A" * 60
        f = make_failure(avoid_hint=long_hint)
        result = generate_ab_format(f, "concise")
        assert "..." in result

    def test_detailed_with_last_used_date(self):
        f = make_failure()
        f.last_used = datetime(2024, 6, 15, tzinfo=UTC)
        result = generate_ab_format(f, "detailed")
        assert "2024-06-15" in result


# ---------------------------------------------------------------------------
# A/B Outcome Tracking
# ---------------------------------------------------------------------------

class TestAbOutcomeTracking:
    def test_record_and_retrieve_outcomes(self, db):
        for _ in range(12):
            record_format_outcome(db, "ws1", "concise", helped=True)
        for _ in range(10):
            record_format_outcome(db, "ws1", "detailed", helped=False)

        key = "ab_outcomes:ws1"
        row = db.execute("SELECT value FROM forge_meta WHERE key = ?", (key,)).fetchone()
        data = json.loads(row[0])
        assert data["concise"]["total"] == 12
        assert data["concise"]["helped"] == 12
        assert data["detailed"]["total"] == 10
        assert data["detailed"]["helped"] == 0

    def test_get_best_format_insufficient_data(self, db):
        # Only 5 observations each → default to concise
        for _ in range(5):
            record_format_outcome(db, "ws2", "concise", helped=True)
            record_format_outcome(db, "ws2", "detailed", helped=True)
        assert get_best_format(db, "ws2") == "concise"

    def test_get_best_format_picks_detailed(self, db):
        for _ in range(10):
            record_format_outcome(db, "ws3", "concise", helped=False)
        for _ in range(10):
            record_format_outcome(db, "ws3", "detailed", helped=True)
        assert get_best_format(db, "ws3") == "detailed"

    def test_get_best_format_picks_concise(self, db):
        for _ in range(10):
            record_format_outcome(db, "ws4", "concise", helped=True)
        for _ in range(10):
            record_format_outcome(db, "ws4", "detailed", helped=False)
        assert get_best_format(db, "ws4") == "concise"

    def test_get_best_format_no_data(self, db):
        assert get_best_format(db, "unknown_ws") == "concise"

    def test_get_active_variant_default(self, db):
        assert get_active_variant(db, "new_ws") == "concise"

    def test_get_active_variant_stored(self, db):
        db.execute(
            "INSERT INTO forge_meta(key, value) VALUES ('ab_variant:ws5', 'detailed')"
        )
        db.commit()
        assert get_active_variant(db, "ws5") == "detailed"


# ---------------------------------------------------------------------------
# Hint Quality Scoring
# ---------------------------------------------------------------------------

class TestScoreHintQuality:
    def test_good_hint_scores_high(self):
        hint = "Use json.loads() instead of eval() to parse JSON safely"
        score = score_hint_quality(hint)
        assert score >= 0.6

    def test_short_hint_scores_low(self):
        score = score_hint_quality("bad")
        assert score < 0.4

    def test_vague_hint_penalized(self):
        score_vague = score_hint_quality("maybe check the code sometimes")
        score_clear = score_hint_quality("Check the return value before use")
        assert score_clear > score_vague

    def test_actionable_hint_bonus(self):
        actionable = "Avoid using global state in async handlers"
        plain = "global state is bad in async handlers"
        assert score_hint_quality(actionable) > score_hint_quality(plain)

    def test_score_in_range(self):
        for hint in ["", "x", "Use something", "A" * 300, "Avoid calling foo() without checking result"]:
            score = score_hint_quality(hint)
            assert 0.0 <= score <= 1.0

    def test_hint_with_file_path_scores_higher(self):
        with_path = "Check /config/settings.yml for missing keys"
        without_path = "Check the config file for missing keys"
        assert score_hint_quality(with_path) >= score_hint_quality(without_path)


# ---------------------------------------------------------------------------
# Low Quality Hint Listing
# ---------------------------------------------------------------------------

class TestListLowQualityHints:
    def test_returns_only_below_threshold(self, db):
        # Low quality: very short hint
        insert_failure(db, "ws1", "bad_pat", "bad", times_warned=1, times_helped=0)
        # High quality: descriptive hint
        insert_failure(
            db, "ws1", "good_pat",
            "Avoid calling foo() without checking return value",
            times_warned=2, times_helped=1,
        )

        results = list_low_quality_hints(db, "ws1", threshold=0.4)
        patterns = [r["pattern"] for r in results]
        assert "bad_pat" in patterns
        assert "good_pat" not in patterns

    def test_results_sorted_by_score_asc(self, db):
        insert_failure(db, "ws10", "p1", "x")
        insert_failure(db, "ws10", "p2", "y")
        results = list_low_quality_hints(db, "ws10", threshold=1.0)
        scores = [r["quality_score"] for r in results]
        assert scores == sorted(scores)

    def test_empty_workspace(self, db):
        assert list_low_quality_hints(db, "empty_ws") == []

    def test_result_keys(self, db):
        insert_failure(db, "ws20", "pat", "ok")
        results = list_low_quality_hints(db, "ws20", threshold=1.0)
        if results:
            r = results[0]
            assert set(r.keys()) == {"pattern", "avoid_hint", "quality_score", "times_warned", "times_helped"}


# ---------------------------------------------------------------------------
# Hint Improvement Suggestions
# ---------------------------------------------------------------------------

class TestSuggestHintImprovement:
    def test_short_hint_expanded(self):
        improved = suggest_hint_improvement("bad", "null_pointer")
        assert len(improved) > 10
        assert "null_pointer" in improved

    def test_vague_words_removed(self):
        improved = suggest_hint_improvement("maybe check the value sometimes", "check_val")
        assert "maybe" not in improved.lower()
        assert "sometimes" not in improved.lower()

    def test_non_actionable_gets_verb(self):
        improved = suggest_hint_improvement("the database connection pool exhausted", "db_pool")
        first_word = improved.split()[0].lower().rstrip(".,;:")
        action_verbs = {"avoid", "check", "use", "run", "ensure", "prefer", "never", "always"}
        assert first_word in action_verbs

    def test_empty_hint_expanded(self):
        improved = suggest_hint_improvement("", "some_pattern")
        assert len(improved) > 0
        assert "some_pattern" in improved

    def test_already_good_hint_unchanged_structure(self):
        hint = "Avoid using eval() — use json.loads() instead"
        improved = suggest_hint_improvement(hint, "eval_usage")
        assert improved  # non-empty


# ---------------------------------------------------------------------------
# Skill Directive Analysis
# ---------------------------------------------------------------------------

SAMPLE_SKILL_MD = """\
# Test Skill

## Rules
- Always use type hints on all function signatures
- Never call external APIs without retry logic
- Use the existing helper function instead of rewriting

## Thresholds
- Max retries: 3
- Timeout must be <= 30 seconds

## Workflow
- Step 1: validate input → Step 2: process → Step 3: return result

## Description
This skill manages deployment pipelines.
"""


class TestAnalyzeSkillDirectives:
    def test_returns_list_of_dicts(self):
        results = analyze_skill_directives(SAMPLE_SKILL_MD)
        assert isinstance(results, list)
        assert len(results) > 0
        for item in results:
            assert "text" in item
            assert "type" in item
            assert "clarity_score" in item

    def test_rule_type_detected(self):
        results = analyze_skill_directives(SAMPLE_SKILL_MD)
        types = {r["type"] for r in results}
        assert "rule" in types

    def test_threshold_type_detected(self):
        results = analyze_skill_directives(SAMPLE_SKILL_MD)
        types = {r["type"] for r in results}
        assert "threshold" in types

    def test_workflow_type_detected(self):
        results = analyze_skill_directives(SAMPLE_SKILL_MD)
        types = {r["type"] for r in results}
        assert "workflow" in types

    def test_clarity_score_in_range(self):
        results = analyze_skill_directives(SAMPLE_SKILL_MD)
        for r in results:
            assert 0.0 <= r["clarity_score"] <= 1.0

    def test_empty_content(self):
        assert analyze_skill_directives("") == []

    def test_headers_excluded(self):
        results = analyze_skill_directives(SAMPLE_SKILL_MD)
        for r in results:
            assert not r["text"].startswith("#")


# ---------------------------------------------------------------------------
# Injection Score Computation
# ---------------------------------------------------------------------------

class TestComputeInjectionScore:
    def test_score_is_positive(self):
        f = make_failure(q=0.8)
        score = compute_injection_score(f)
        assert score > 0

    def test_newer_scores_higher(self):
        f = make_failure(q=0.8)
        score_new = compute_injection_score(f, recency_days=0.0)
        score_old = compute_injection_score(f, recency_days=30.0)
        assert score_new > score_old

    def test_tag_overlap_increases_score(self):
        f = make_failure(q=0.8, tags=["python", "async"])
        score_overlap = compute_injection_score(f, session_tags=["python", "async"])
        score_no_overlap = compute_injection_score(f, session_tags=["java", "spring"])
        assert score_overlap > score_no_overlap

    def test_no_tags_zero_relevance(self):
        f = make_failure(q=0.8, tags=[])
        score = compute_injection_score(f, session_tags=["python"])
        # relevance = 0, score = q * (0.6 + 0.2 * recency_weight + 0.0)
        import math
        expected_max = 0.8 * (0.6 + 0.2 * 1.0)  # recency_days=0 → weight=1
        assert abs(score - expected_max) < 1e-9

    def test_formula_correctness(self):
        import math
        f = make_failure(q=0.5, tags=["x"])
        score = compute_injection_score(f, session_tags=["x"], recency_days=10.0)
        rw = math.exp(-0.1 * 10.0)
        expected = 0.5 * (0.6 + 0.2 * rw + 0.2 * 1.0)  # full overlap
        assert abs(score - expected) < 1e-9

    def test_high_q_higher_score(self):
        f_high = make_failure(q=0.9)
        f_low = make_failure(q=0.1)
        assert compute_injection_score(f_high) > compute_injection_score(f_low)


# ---------------------------------------------------------------------------
# context.py A/B Integration
# ---------------------------------------------------------------------------

class TestContextAbIntegration:
    def _make_failures(self) -> list[Failure]:
        return [
            make_failure("pat_a", "Use A instead of B", q=0.8),
            make_failure("pat_b", "Check return value", q=0.6),
        ]

    def test_format_l0_default_unchanged(self):
        from forge.core.context import format_l0
        failures = self._make_failures()
        result = format_l0(failures)
        assert "[WARN] pat_a | near_miss | Q:0.80" in result

    def test_format_l0_concise_variant(self):
        from forge.core.context import format_l0
        failures = self._make_failures()
        result = format_l0(failures, variant="concise")
        assert "pat_a" in result
        assert "0.80" in result
        # concise format does not include quality field
        assert "near_miss" not in result

    def test_format_l0_detailed_variant(self):
        from forge.core.context import format_l0
        failures = self._make_failures()
        result = format_l0(failures, variant="detailed")
        assert "near_miss" in result
        assert "seen:" in result

    def test_format_l1_default_unchanged(self):
        from forge.core.context import format_l1
        failures = self._make_failures()
        result = format_l1(failures)
        assert "→ Use A instead of B" in result

    def test_format_l1_variant_uses_ab_format(self):
        from forge.core.context import format_l1
        failures = self._make_failures()
        result_default = format_l1(failures)
        result_concise = format_l1(failures, variant="concise")
        # concise variant has different structure than default L1
        assert result_default != result_concise

    def test_build_context_default_backward_compatible(self):
        from forge.core.context import build_context
        from forge.config import ForgeConfig
        failures = self._make_failures()
        config = ForgeConfig()
        result = build_context(failures, [], config)
        assert "Past Failures" in result
        assert "pat_a" in result

    def test_build_context_with_variant(self):
        from forge.core.context import build_context
        from forge.config import ForgeConfig
        failures = self._make_failures()
        config = ForgeConfig()
        result = build_context(failures, [], config, variant="concise")
        assert "pat_a" in result

    def test_build_context_sort_by_injection_score(self):
        from forge.core.context import build_context
        from forge.config import ForgeConfig
        # High Q failure should appear before low Q when sorted
        failures = [
            make_failure("low_q_pat", q=0.1),
            make_failure("high_q_pat", q=0.9),
        ]
        config = ForgeConfig()
        result = build_context(failures, [], config, sort_by_injection_score=True)
        assert result.index("high_q_pat") < result.index("low_q_pat")
