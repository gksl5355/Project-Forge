"""Tests for forge/engines/measure.py."""

from __future__ import annotations

import pytest

from forge.config import ForgeConfig
from forge.engines.measure import MeasureResult, run_measure
from forge.storage.queries import insert_failure, insert_session, insert_team_run
from forge.storage.models import Failure, Session, TeamRun


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_failure(
    workspace_id: str,
    pattern: str,
    q: float = 0.5,
    times_seen: int = 1,
    times_helped: int = 0,
    times_warned: int = 0,
) -> Failure:
    return Failure(
        workspace_id=workspace_id,
        pattern=pattern,
        avoid_hint=f"avoid {pattern}",
        hint_quality="preventable",
        q=q,
        times_seen=times_seen,
        times_helped=times_helped,
        times_warned=times_warned,
    )


def _make_session(workspace_id: str, session_id: str) -> Session:
    return Session(session_id=session_id, workspace_id=workspace_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_measure_empty_workspace(db):
    """빈 workspace → MeasureResult 모든 수치 0."""
    config = ForgeConfig()
    result = run_measure("empty_ws", db, config)

    assert isinstance(result, MeasureResult)
    assert result.qwhr == 0.0
    assert result.promotion_precision == 0.0
    assert result.l1_vs_l0_help_rate == 0.0
    assert result.helped_per_1k_tokens == 0.0
    assert result.q_convergence_speed == 0.0
    assert result.total_failures == 0
    assert result.total_sessions == 0
    assert result.section_effectiveness["failures"] is None


def test_measure_qwhr_calculation(db):
    """failures 데이터로 QWHR 정확한 계산 확인."""
    ws = "qwhr_ws"
    # pattern A: Q=0.8, helped/warned = 4/5 → help_rate=0.8
    # pattern B: Q=0.4, helped/warned = 1/4 → help_rate=0.25
    insert_failure(db, _make_failure(ws, "patternA", q=0.8, times_helped=4, times_warned=5))
    insert_failure(db, _make_failure(ws, "patternB", q=0.4, times_helped=1, times_warned=4))

    config = ForgeConfig()
    result = run_measure(ws, db, config)

    # QWHR = (0.8*0.8 + 0.4*0.25) / (0.8 + 0.4) = (0.64 + 0.1) / 1.2 = 0.74 / 1.2 ≈ 0.617
    expected_qwhr = (0.8 * 0.8 + 0.4 * 0.25) / (0.8 + 0.4)
    assert abs(result.qwhr - expected_qwhr) < 1e-6


def test_measure_promotion_precision(db):
    """__global__ failures 중 helped 비율 정확도."""
    # 2개 global 중 1개만 helped
    insert_failure(db, _make_failure("__global__", "globalA", times_helped=3, times_warned=5))
    insert_failure(db, _make_failure("__global__", "globalB", times_helped=0, times_warned=2))

    config = ForgeConfig()
    result = run_measure("any_ws", db, config)

    assert result.promotion_precision == 0.5  # 1/2


def test_measure_l1_vs_l0(db):
    """상위 L1 패턴 vs 전체 help rate 차이 검증."""
    ws = "l1_ws"
    # High Q patterns: helped=8/10 → 0.8
    insert_failure(db, _make_failure(ws, "highQ1", q=0.9, times_helped=8, times_warned=10))
    insert_failure(db, _make_failure(ws, "highQ2", q=0.85, times_helped=8, times_warned=10))
    # Low Q patterns: helped=1/10 → 0.1
    insert_failure(db, _make_failure(ws, "lowQ1", q=0.3, times_helped=1, times_warned=10))
    insert_failure(db, _make_failure(ws, "lowQ2", q=0.2, times_helped=1, times_warned=10))
    insert_failure(db, _make_failure(ws, "lowQ3", q=0.1, times_helped=1, times_warned=10))

    # l1_count = l1_project_entries(3) + l1_global_entries(2) = 5
    # Top 5 by Q: highQ1, highQ2, lowQ1, lowQ2, lowQ3
    # But with default config l1_project_entries=3, l1_global_entries=2, total=5
    config = ForgeConfig(l1_project_entries=2, l1_global_entries=0)
    result = run_measure(ws, db, config)

    # L1 (top 2): highQ1 + highQ2 → avg=0.8
    # Overall avg: (0.8 + 0.8 + 0.1 + 0.1 + 0.1) / 5 = 0.38
    # l1_vs_l0 = 0.8 - 0.38 = 0.42
    assert result.l1_vs_l0_help_rate > 0  # L1 패턴이 전체보다 help rate 높아야 함


def test_measure_helped_per_1k_tokens(db):
    """토큰 대비 도움 횟수 양수 확인."""
    ws = "token_ws"
    insert_failure(db, _make_failure(ws, "pat1", times_helped=10, times_warned=20))
    insert_failure(db, _make_failure(ws, "pat2", times_helped=5, times_warned=10))

    config = ForgeConfig()
    result = run_measure(ws, db, config)

    assert result.helped_per_1k_tokens > 0.0
    # total_helped = 15, tokens > 0, so ratio > 0
    assert result.total_failures == 2


def test_measure_convergence_speed(db):
    """helped 패턴 평균 times_seen 계산."""
    ws = "conv_ws"
    # 2 helped failures: times_seen=3 and times_seen=7
    insert_failure(db, _make_failure(ws, "fast", times_seen=3, times_helped=1, times_warned=2))
    insert_failure(db, _make_failure(ws, "slow", times_seen=7, times_helped=2, times_warned=3))
    # 1 not-helped failure: should not count
    insert_failure(db, _make_failure(ws, "zero", times_seen=10, times_helped=0, times_warned=5))

    config = ForgeConfig()
    result = run_measure(ws, db, config)

    assert result.q_convergence_speed == pytest.approx(5.0)  # (3+7)/2


def test_measure_no_sessions(db):
    """세션 없을 때 graceful 처리."""
    ws = "no_session_ws"
    insert_failure(db, _make_failure(ws, "pat1", times_helped=2, times_warned=3))

    config = ForgeConfig()
    result = run_measure(ws, db, config)

    assert result.total_sessions == 0
    assert result.total_failures == 1
    assert result.qwhr >= 0.0  # 정상 계산됨


def test_measure_section_effectiveness(db):
    """section_effectiveness: failures는 float, 나머지는 None."""
    ws = "section_ws"
    insert_failure(db, _make_failure(ws, "p1", times_helped=3, times_warned=6))
    insert_failure(db, _make_failure(ws, "p2", times_helped=1, times_warned=4))

    config = ForgeConfig()
    result = run_measure(ws, db, config)

    assert isinstance(result.section_effectiveness["failures"], float)
    assert result.section_effectiveness["decisions"] is None
    assert result.section_effectiveness["rules"] is None
    assert result.section_effectiveness["knowledge"] is None


# ---------------------------------------------------------------------------
# TO Metrics Tests
# ---------------------------------------------------------------------------

def _make_team_run(
    workspace_id: str,
    run_id: str,
    complexity: str = "MEDIUM",
    team_config: str = "sonnet:2+haiku:1",
    success_rate: float | None = 0.8,
    retry_rate: float | None = 0.1,
    scope_violations: int = 0,
) -> TeamRun:
    return TeamRun(
        workspace_id=workspace_id,
        run_id=run_id,
        complexity=complexity,
        team_config=team_config,
        success_rate=success_rate,
        retry_rate=retry_rate,
        scope_violations=scope_violations,
    )


def test_measure_to_no_runs(db):
    """TO 런 없으면 기본값."""
    config = ForgeConfig()
    result = run_measure("no_to_ws", db, config)

    assert result.to_total_runs == 0
    assert result.to_avg_success_rate is None
    assert result.to_avg_retry_rate is None
    assert result.to_avg_scope_violations is None
    assert result.to_best_configs == {}


def test_measure_to_avg_metrics(db):
    """TO 평균 메트릭 계산."""
    ws = "to_avg_ws"
    insert_team_run(db, _make_team_run(ws, "run-1", success_rate=0.8, retry_rate=0.2, scope_violations=1))
    insert_team_run(db, _make_team_run(ws, "run-2", success_rate=0.6, retry_rate=0.4, scope_violations=3))

    config = ForgeConfig()
    result = run_measure(ws, db, config)

    assert result.to_total_runs == 2
    assert result.to_avg_success_rate == pytest.approx(0.7)
    assert result.to_avg_retry_rate == pytest.approx(0.3)
    assert result.to_avg_scope_violations == pytest.approx(2.0)


def test_measure_to_best_configs(db):
    """complexity별 best config 선택."""
    ws = "to_best_ws"
    insert_team_run(db, _make_team_run(ws, "run-1", complexity="SIMPLE", team_config="haiku:2", success_rate=0.9))
    insert_team_run(db, _make_team_run(ws, "run-2", complexity="SIMPLE", team_config="sonnet:1", success_rate=0.7))
    insert_team_run(db, _make_team_run(ws, "run-3", complexity="MEDIUM", team_config="sonnet:2+haiku:1", success_rate=0.85))

    config = ForgeConfig()
    result = run_measure(ws, db, config)

    assert "SIMPLE" in result.to_best_configs
    assert result.to_best_configs["SIMPLE"]["config"] == "haiku:2"
    assert result.to_best_configs["SIMPLE"]["success_rate"] == pytest.approx(0.9)
    assert "MEDIUM" in result.to_best_configs


def test_measure_to_null_rates_skipped(db):
    """success_rate/retry_rate가 None인 런은 평균 계산에서 제외."""
    ws = "to_null_ws"
    insert_team_run(db, _make_team_run(ws, "run-1", success_rate=0.8, retry_rate=None))
    insert_team_run(db, _make_team_run(ws, "run-2", success_rate=None, retry_rate=0.2))

    config = ForgeConfig()
    result = run_measure(ws, db, config)

    assert result.to_total_runs == 2
    assert result.to_avg_success_rate == pytest.approx(0.8)  # only run-1
    assert result.to_avg_retry_rate == pytest.approx(0.2)    # only run-2


def test_measure_to_complexity_none(db):
    """complexity=None인 런은 UNKNOWN으로 그룹핑."""
    ws = "to_unknown_ws"
    insert_team_run(db, _make_team_run(ws, "run-1", complexity=None, success_rate=0.7))

    config = ForgeConfig()
    result = run_measure(ws, db, config)

    assert "UNKNOWN" in result.to_best_configs
    assert result.to_best_configs["UNKNOWN"]["success_rate"] == pytest.approx(0.7)


def test_measure_to_group_all_null_sr(db):
    """complexity 그룹 내 모든 success_rate=None → best_configs에 미포함."""
    ws = "to_allnull_ws"
    insert_team_run(db, _make_team_run(ws, "run-1", complexity="COMPLEX", success_rate=None))
    insert_team_run(db, _make_team_run(ws, "run-2", complexity="COMPLEX", success_rate=None))

    config = ForgeConfig()
    result = run_measure(ws, db, config)

    assert result.to_total_runs == 2
    assert "COMPLEX" not in result.to_best_configs


def test_measure_to_zero_scope_violations(db):
    """모든 scope_violations=0 → avg_scope_violations=0.0."""
    ws = "to_zero_sv_ws"
    insert_team_run(db, _make_team_run(ws, "run-1", scope_violations=0))
    insert_team_run(db, _make_team_run(ws, "run-2", scope_violations=0))

    config = ForgeConfig()
    result = run_measure(ws, db, config)

    assert result.to_avg_scope_violations == pytest.approx(0.0)
