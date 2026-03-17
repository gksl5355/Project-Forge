"""Tests for forge/engines/recommend.py."""

from __future__ import annotations

import pytest

from forge.engines.recommend import Recommendation, run_recommend
from forge.storage.queries import insert_team_run
from forge.storage.models import TeamRun


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_team_run(
    workspace_id: str,
    run_id: str,
    complexity: str = "MEDIUM",
    team_config: str = "sonnet:2+haiku:1",
    success_rate: float | None = 0.8,
    retry_rate: float | None = 0.1,
) -> TeamRun:
    return TeamRun(
        workspace_id=workspace_id,
        run_id=run_id,
        complexity=complexity,
        team_config=team_config,
        success_rate=success_rate,
        retry_rate=retry_rate,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_recommend_no_runs(db):
    """런 데이터가 없으면 None 반환."""
    result = run_recommend("empty_ws", "MEDIUM", db)
    assert result is None


def test_recommend_no_matching_complexity(db):
    """다른 complexity만 있으면 None 반환."""
    insert_team_run(db, _make_team_run("ws", "run-1", complexity="SIMPLE"))
    result = run_recommend("ws", "COMPLEX", db)
    assert result is None


def test_recommend_single_config(db):
    """단일 config → 해당 config 추천."""
    ws = "single_ws"
    insert_team_run(db, _make_team_run(ws, "run-1", success_rate=0.9))
    insert_team_run(db, _make_team_run(ws, "run-2", success_rate=0.7))

    result = run_recommend(ws, "MEDIUM", db)
    assert result is not None
    assert result.config == "sonnet:2+haiku:1"
    assert result.complexity == "MEDIUM"
    assert result.runs == 2
    assert result.avg_success_rate == pytest.approx(0.8)
    assert result.confidence == "low"  # 2 runs → low (threshold: 3+ for medium)


def test_recommend_best_config_selected(db):
    """여러 config 중 success_rate 높은 것 추천."""
    ws = "multi_ws"
    # Config A: avg success 60%
    insert_team_run(db, _make_team_run(ws, "run-1", team_config="sonnet:1+haiku:2", success_rate=0.6))
    insert_team_run(db, _make_team_run(ws, "run-2", team_config="sonnet:1+haiku:2", success_rate=0.6))
    # Config B: avg success 90%
    insert_team_run(db, _make_team_run(ws, "run-3", team_config="sonnet:3", success_rate=0.9))
    insert_team_run(db, _make_team_run(ws, "run-4", team_config="sonnet:3", success_rate=0.9))

    result = run_recommend(ws, "MEDIUM", db)
    assert result is not None
    assert result.config == "sonnet:3"
    assert result.avg_success_rate == pytest.approx(0.9)


def test_recommend_confidence_levels(db):
    """런 수에 따른 confidence 레벨."""
    ws = "conf_ws"
    # 1-2 runs → low
    insert_team_run(db, _make_team_run(ws, "run-1", success_rate=0.8))
    result = run_recommend(ws, "MEDIUM", db)
    assert result is not None
    assert result.confidence == "low"

    insert_team_run(db, _make_team_run(ws, "run-2", success_rate=0.8))
    result = run_recommend(ws, "MEDIUM", db)
    assert result.confidence == "low"

    # 3-7 runs → medium
    insert_team_run(db, _make_team_run(ws, "run-3", success_rate=0.8))
    result = run_recommend(ws, "MEDIUM", db)
    assert result.confidence == "medium"

    # 8+ runs → high
    for i in range(4, 9):
        insert_team_run(db, _make_team_run(ws, f"run-{i}", success_rate=0.8))
    result = run_recommend(ws, "MEDIUM", db)
    assert result.confidence == "high"


def test_recommend_retry_rate(db):
    """retry_rate 평균 계산."""
    ws = "rr_ws"
    insert_team_run(db, _make_team_run(ws, "run-1", retry_rate=0.2))
    insert_team_run(db, _make_team_run(ws, "run-2", retry_rate=0.4))

    result = run_recommend(ws, "MEDIUM", db)
    assert result is not None
    assert result.avg_retry_rate == pytest.approx(0.3)


def test_recommend_case_insensitive_complexity(db):
    """complexity 대소문자 무관."""
    ws = "case_ws"
    insert_team_run(db, _make_team_run(ws, "run-1", complexity="MEDIUM", success_rate=0.8))

    result = run_recommend(ws, "medium", db)
    assert result is not None
    assert result.complexity == "MEDIUM"


def test_recommend_skips_null_success_rate(db):
    """success_rate가 None인 런은 무시."""
    ws = "null_ws"
    insert_team_run(db, _make_team_run(ws, "run-1", success_rate=None))

    result = run_recommend(ws, "MEDIUM", db)
    assert result is None


def test_recommend_high_sr_few_runs_beats_low_sr_many_runs(db):
    """적은 런이라도 success_rate가 높은 config가 우선."""
    ws = "sr_priority_ws"
    # Config A: 많은 런, 낮은 success_rate
    for i in range(20):
        insert_team_run(db, _make_team_run(ws, f"run-a{i}", team_config="bad_config", success_rate=0.5))
    # Config B: 적은 런, 높은 success_rate
    insert_team_run(db, _make_team_run(ws, "run-b1", team_config="good_config", success_rate=0.95))

    result = run_recommend(ws, "MEDIUM", db)
    assert result is not None
    assert result.config == "good_config"
    assert result.avg_success_rate == pytest.approx(0.95)


def test_recommend_deterministic_tie(db):
    """동일 score일 때 결정적 결과 (config 이름 역순)."""
    ws = "tie_ws"
    insert_team_run(db, _make_team_run(ws, "run-1", team_config="alpha", success_rate=0.8))
    insert_team_run(db, _make_team_run(ws, "run-2", team_config="beta", success_rate=0.8))

    result1 = run_recommend(ws, "MEDIUM", db)
    result2 = run_recommend(ws, "MEDIUM", db)
    assert result1 is not None
    assert result1.config == result2.config  # 항상 같은 결과
