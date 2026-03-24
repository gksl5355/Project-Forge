"""Forge v5 KPI computation functions."""

from __future__ import annotations

import json
import sqlite3

from forge.config import ForgeConfig
from forge.core.context import build_context, estimate_tokens
from forge.storage.queries import list_failures, list_rules


def compute_routing_accuracy(conn: sqlite3.Connection, workspace_id: str) -> float:
    """Routing Accuracy = 최고성공률 모델이 실제 선택된 비율.

    model_choices 테이블에서 카테고리별 best model vs actual selection 비교.
    데이터 없으면 0.0.
    """
    rows = conn.execute(
        "SELECT task_category, selected_model, outcome FROM model_choices"
        " WHERE workspace_id = ?",
        (workspace_id,),
    ).fetchall()

    if not rows:
        return 0.0

    # category → model → list of outcomes
    category_model_outcomes: dict[str, dict[str, list[float]]] = {}
    for category, model, outcome in rows:
        if outcome is None:
            continue
        if category not in category_model_outcomes:
            category_model_outcomes[category] = {}
        if model not in category_model_outcomes[category]:
            category_model_outcomes[category][model] = []
        category_model_outcomes[category][model].append(float(outcome))

    if not category_model_outcomes:
        return 0.0

    best_model: dict[str, str] = {}
    for category, model_outcomes in category_model_outcomes.items():
        best = max(
            model_outcomes.keys(),
            key=lambda m: sum(model_outcomes[m]) / len(model_outcomes[m]),
        )
        best_model[category] = best

    total = sum(1 for r in rows if r[0] in best_model)
    correct = sum(1 for r in rows if r[0] in best_model and r[1] == best_model[r[0]])

    return correct / total if total > 0 else 0.0


def compute_circuit_efficiency(conn: sqlite3.Connection, workspace_id: str) -> float:
    """Circuit Efficiency = 1 - (breaks / sessions).

    forge_meta에서 breaker:* 키 조회, tripped=True 카운트.
    세션 없으면 1.0 (완벽).
    """
    rows = conn.execute(
        "SELECT session_id FROM sessions WHERE workspace_id = ?",
        (workspace_id,),
    ).fetchall()

    if not rows:
        return 1.0

    total_sessions = len(rows)
    breaks = 0

    for (session_id,) in rows:
        meta_row = conn.execute(
            "SELECT value FROM forge_meta WHERE key = ?",
            (f"breaker:{session_id}",),
        ).fetchone()
        if meta_row:
            try:
                state = json.loads(meta_row[0])
                if state.get("tripped", False):
                    breaks += 1
            except (json.JSONDecodeError, TypeError):
                pass

    return 1.0 - (breaks / total_sessions)


def compute_agent_utilization(conn: sqlite3.Connection, workspace_id: str) -> float:
    """Agent Utilization = completed / (completed + error + timed_out).

    agents 테이블에서 status 집계. 데이터 없으면 0.0.
    """
    rows = conn.execute(
        "SELECT status, COUNT(*) FROM agents"
        " WHERE workspace_id = ? AND status IN ('completed', 'error', 'timed_out')"
        " GROUP BY status",
        (workspace_id,),
    ).fetchall()

    if not rows:
        return 0.0

    counts: dict[str, int] = {row[0]: row[1] for row in rows}
    completed = counts.get("completed", 0)
    total = sum(counts.values())

    return completed / total if total > 0 else 0.0


def compute_context_hit_rate(conn: sqlite3.Connection, workspace_id: str) -> float:
    """Context Hit Rate = 주입된 경고 중 실제 helped 비율.

    failures 테이블: sum(times_helped) / sum(times_warned). warned=0이면 0.0.
    """
    row = conn.execute(
        "SELECT SUM(times_helped), SUM(times_warned) FROM failures"
        " WHERE workspace_id = ?",
        (workspace_id,),
    ).fetchone()

    if not row or row[1] is None or row[1] == 0:
        return 0.0

    return min(1.0, row[0] / row[1])


def compute_tool_efficiency(conn: sqlite3.Connection, workspace_id: str) -> float:
    """Token Efficiency (helped per 1k tokens).

    기존 measure.py의 helped_per_1k_tokens 로직 재사용.
    결과를 0~1로 정규화 (cap at 10 helped/1k → 1.0).
    """
    config = ForgeConfig()
    failures = list_failures(conn, workspace_id)
    rules = list_rules(conn, workspace_id)

    if not failures:
        return 0.0

    total_helped = sum(f.times_helped for f in failures)
    context = build_context(failures, rules, config)
    tokens = estimate_tokens(context)

    if tokens == 0:
        return 0.0

    helped_per_1k = total_helped / (tokens / 1000)
    return min(1.0, helped_per_1k / 10.0)


def compute_redundant_call_rate(conn: sqlite3.Connection, workspace_id: str) -> float:
    """Redundant Call Rate = forge_meta에서 breaker:* 키의 평균 tool_calls 대비 consecutive_failures 비율.

    (total_consecutive_failures / total_tool_calls). 데이터 없으면 0.0.
    """
    rows = conn.execute(
        "SELECT session_id FROM sessions WHERE workspace_id = ?",
        (workspace_id,),
    ).fetchall()

    if not rows:
        return 0.0

    total_consecutive_failures = 0
    total_tool_calls = 0

    for (session_id,) in rows:
        meta_row = conn.execute(
            "SELECT value FROM forge_meta WHERE key = ?",
            (f"breaker:{session_id}",),
        ).fetchone()
        if meta_row:
            try:
                state = json.loads(meta_row[0])
                total_consecutive_failures += state.get("consecutive_failures", 0)
                total_tool_calls += state.get("tool_calls", 0)
            except (json.JSONDecodeError, TypeError):
                pass

    return total_consecutive_failures / total_tool_calls if total_tool_calls > 0 else 0.0


def compute_stale_warning_rate(conn: sqlite3.Connection, workspace_id: str) -> float:
    """Stale Warning Rate = times_warned > 0 but times_helped == 0 비율.

    failures 테이블에서 warned > 0인 것 중 helped == 0인 비율.
    전부 helped면 0.0.
    """
    row = conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN times_helped = 0 THEN 1 ELSE 0 END)"
        " FROM failures WHERE workspace_id = ? AND times_warned > 0",
        (workspace_id,),
    ).fetchone()

    if not row or row[0] == 0:
        return 0.0

    return row[1] / row[0]
