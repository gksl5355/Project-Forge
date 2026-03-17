"""Tests for forge.core.promote."""

import pytest

from forge.config import ForgeConfig
from forge.core.promote import (
    check_global_promote,
    check_knowledge_promote,
    merge_q,
    promote_to_global,
    promote_to_knowledge,
)
from forge.storage.models import Failure, Knowledge


def _make_failure(
    pattern: str = "connection_error",
    q: float = 0.5,
    times_helped: int = 0,
    projects_seen: list[str] | None = None,
    workspace_id: str = "project_a",
) -> Failure:
    return Failure(
        workspace_id=workspace_id,
        pattern=pattern,
        avoid_hint="check your network",
        hint_quality="near_miss",
        q=q,
        times_seen=5,
        times_helped=times_helped,
        times_warned=2,
        tags=["network"],
        projects_seen=projects_seen or [],
        observed_error="ConnectionError",
        likely_cause="network issue",
        id=42,
    )


# --- check_global_promote ---

def test_check_global_promote_above_threshold():
    config = ForgeConfig(promote_threshold=2)
    failure = _make_failure(projects_seen=["proj_a", "proj_b", "proj_c"])
    assert check_global_promote(failure, config) is True


def test_check_global_promote_exact_threshold():
    config = ForgeConfig(promote_threshold=2)
    failure = _make_failure(projects_seen=["proj_a", "proj_b"])
    assert check_global_promote(failure, config) is True


def test_check_global_promote_below_threshold():
    config = ForgeConfig(promote_threshold=2)
    failure = _make_failure(projects_seen=["proj_a"])
    assert check_global_promote(failure, config) is False


def test_check_global_promote_empty_projects():
    config = ForgeConfig(promote_threshold=2)
    failure = _make_failure(projects_seen=[])
    assert check_global_promote(failure, config) is False


def test_promote_blocked_by_min_times_seen():
    config = ForgeConfig(promote_threshold=2, promote_min_times_seen=3)
    failure = _make_failure(projects_seen=["proj_a", "proj_b"])
    failure.times_seen = 2
    assert check_global_promote(failure, config) is False


def test_promote_passes_with_min_times_seen():
    config = ForgeConfig(promote_threshold=2, promote_min_times_seen=3)
    failure = _make_failure(projects_seen=["proj_a", "proj_b"])
    failure.times_seen = 3
    assert check_global_promote(failure, config) is True


def test_promote_custom_min_times_seen():
    config = ForgeConfig(promote_threshold=2, promote_min_times_seen=10)
    failure = _make_failure(projects_seen=["proj_a", "proj_b"])
    failure.times_seen = 9
    assert check_global_promote(failure, config) is False
    failure.times_seen = 10
    assert check_global_promote(failure, config) is True


def test_promote_default_min_times_seen():
    config = ForgeConfig(promote_threshold=2)
    assert config.promote_min_times_seen == 3
    failure = _make_failure(projects_seen=["proj_a", "proj_b"])
    failure.times_seen = 3
    assert check_global_promote(failure, config) is True


# --- promote_to_global ---

def test_promote_to_global_workspace_is_global():
    failure = _make_failure()
    global_failure = promote_to_global(failure)
    assert global_failure.workspace_id == "__global__"


def test_promote_to_global_id_is_none():
    failure = _make_failure()
    global_failure = promote_to_global(failure)
    assert global_failure.id is None


def test_promote_to_global_preserves_pattern():
    failure = _make_failure(pattern="conn_error")
    assert promote_to_global(failure).pattern == "conn_error"


def test_promote_to_global_preserves_q():
    failure = _make_failure(q=0.8)
    assert promote_to_global(failure).q == pytest.approx(0.8)


def test_promote_to_global_preserves_hint():
    failure = _make_failure()
    global_failure = promote_to_global(failure)
    assert global_failure.avoid_hint == failure.avoid_hint


def test_promote_to_global_copies_lists_independently():
    failure = _make_failure(projects_seen=["a", "b"])
    global_failure = promote_to_global(failure)
    failure.projects_seen.append("c")
    assert "c" not in global_failure.projects_seen


def test_promote_to_global_copies_tags_independently():
    failure = _make_failure()
    failure.tags = ["tag1"]
    global_failure = promote_to_global(failure)
    failure.tags.append("tag2")
    assert "tag2" not in global_failure.tags


def test_promote_to_global_uses_failure_q_when_no_merge_from():
    failure = _make_failure(q=0.7)
    global_failure = promote_to_global(failure)
    assert global_failure.q == pytest.approx(0.7)


def test_promote_to_global_uses_merge_q_when_merge_from_provided():
    f1 = _make_failure(q=0.8)
    f1.times_seen = 3
    f2 = _make_failure(q=0.2)
    f2.times_seen = 1
    # merge_q = (0.8*3 + 0.2*1) / 4 = 0.65
    global_failure = promote_to_global(f1, merge_from=[f1, f2])
    assert global_failure.q == pytest.approx(0.65)


def test_promote_to_global_merge_from_overrides_failure_q():
    f1 = _make_failure(q=0.9)
    f2 = _make_failure(q=0.1)
    for f in [f1, f2]:
        f.times_seen = 1
    # merge_q = 0.5, not 0.9
    global_failure = promote_to_global(f1, merge_from=[f1, f2])
    assert global_failure.q != pytest.approx(0.9)
    assert global_failure.q == pytest.approx(0.5)


# --- check_knowledge_promote ---

def test_check_knowledge_promote_true():
    config = ForgeConfig(knowledge_promote_q=0.8, knowledge_promote_helped=5)
    failure = _make_failure(q=0.85, times_helped=6)
    assert check_knowledge_promote(failure, config) is True


def test_check_knowledge_promote_exact_thresholds():
    config = ForgeConfig(knowledge_promote_q=0.8, knowledge_promote_helped=5)
    failure = _make_failure(q=0.8, times_helped=5)
    assert check_knowledge_promote(failure, config) is True


def test_check_knowledge_promote_low_q():
    config = ForgeConfig(knowledge_promote_q=0.8, knowledge_promote_helped=5)
    failure = _make_failure(q=0.7, times_helped=6)
    assert check_knowledge_promote(failure, config) is False


def test_check_knowledge_promote_low_helped():
    config = ForgeConfig(knowledge_promote_q=0.8, knowledge_promote_helped=5)
    failure = _make_failure(q=0.85, times_helped=4)
    assert check_knowledge_promote(failure, config) is False


def test_check_knowledge_promote_both_low():
    config = ForgeConfig(knowledge_promote_q=0.8, knowledge_promote_helped=5)
    failure = _make_failure(q=0.5, times_helped=2)
    assert check_knowledge_promote(failure, config) is False


# --- promote_to_knowledge ---

def test_promote_to_knowledge_returns_knowledge():
    failure = _make_failure()
    result = promote_to_knowledge(failure)
    assert isinstance(result, Knowledge)


def test_promote_to_knowledge_id_is_none():
    failure = _make_failure()
    assert promote_to_knowledge(failure).id is None


def test_promote_to_knowledge_title_is_pattern():
    failure = _make_failure(pattern="conn_error")
    assert promote_to_knowledge(failure).title == "conn_error"


def test_promote_to_knowledge_workspace_matches():
    failure = _make_failure(workspace_id="my_project")
    assert promote_to_knowledge(failure).workspace_id == "my_project"


def test_promote_to_knowledge_q_matches():
    failure = _make_failure(q=0.88)
    assert promote_to_knowledge(failure).q == pytest.approx(0.88)


def test_promote_to_knowledge_source_is_organic():
    failure = _make_failure()
    assert promote_to_knowledge(failure).source == "organic"


def test_promote_to_knowledge_promoted_from_is_failure_id():
    failure = _make_failure()
    assert promote_to_knowledge(failure).promoted_from == failure.id


def test_promote_to_knowledge_content_includes_avoid_hint():
    failure = _make_failure()
    knowledge = promote_to_knowledge(failure)
    assert failure.avoid_hint in knowledge.content


def test_promote_to_knowledge_content_includes_likely_cause():
    failure = _make_failure()
    knowledge = promote_to_knowledge(failure)
    assert failure.likely_cause in knowledge.content


# --- merge_q ---

def test_merge_q_weighted_average():
    failures = [
        _make_failure(q=0.8, times_helped=0),
        _make_failure(q=0.2, times_helped=0),
    ]
    failures[0].times_seen = 3
    failures[1].times_seen = 1
    # (0.8*3 + 0.2*1) / (3+1) = (2.4 + 0.2) / 4 = 0.65
    assert merge_q(failures) == pytest.approx(0.65)


def test_merge_q_single_failure():
    failure = _make_failure(q=0.7)
    failure.times_seen = 5
    assert merge_q([failure]) == pytest.approx(0.7)


def test_merge_q_equal_weights():
    failures = [_make_failure(q=0.4), _make_failure(q=0.6)]
    for f in failures:
        f.times_seen = 2
    assert merge_q(failures) == pytest.approx(0.5)


def test_merge_q_zero_times_seen_falls_back_to_mean():
    failures = [_make_failure(q=0.4), _make_failure(q=0.6)]
    for f in failures:
        f.times_seen = 0
    assert merge_q(failures) == pytest.approx(0.5)


def test_merge_q_empty_returns_zero():
    assert merge_q([]) == pytest.approx(0.0)


def test_promote_to_knowledge_copies_tags():
    failure = _make_failure()
    failure.tags = ["net", "timeout"]
    knowledge = promote_to_knowledge(failure)
    failure.tags.append("extra")
    assert "extra" not in knowledge.tags
