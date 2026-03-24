"""Prompt and skill auto-improvement engine."""
from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass

from forge.storage.models import Failure


# --- A/B Format Testing ---


@dataclass
class FormatVariant:
    variant_id: str  # "concise" or "detailed"
    template: str


CONCISE_VARIANT = FormatVariant(
    "concise",
    "[WARN] {pattern} Q:{q:.2f} → {hint_short}",
)
DETAILED_VARIANT = FormatVariant(
    "detailed",
    "[WARN] {pattern} | {quality} | Q:{q:.2f} | seen:{seen} helped:{helped}\n  → {hint}\n  Context: last_seen={last_seen}",
)


def generate_ab_format(failure: Failure, variant: str = "concise") -> str:
    """Generate warning text in A/B variant format."""
    hint_short = (
        failure.avoid_hint[:50] + "..."
        if len(failure.avoid_hint) > 50
        else failure.avoid_hint
    )
    last_seen = (
        failure.last_used.strftime("%Y-%m-%d") if failure.last_used else "never"
    )

    if variant == "detailed":
        return DETAILED_VARIANT.template.format(
            pattern=failure.pattern,
            quality=failure.hint_quality,
            q=failure.q,
            seen=failure.times_seen,
            helped=failure.times_helped,
            hint=failure.avoid_hint,
            last_seen=last_seen,
        )
    return CONCISE_VARIANT.template.format(
        pattern=failure.pattern,
        q=failure.q,
        hint_short=hint_short,
    )


def get_active_variant(conn: sqlite3.Connection, workspace_id: str) -> str:
    """Get current A/B variant from forge_meta. Default 'concise'."""
    key = f"ab_variant:{workspace_id}"
    row = conn.execute(
        "SELECT value FROM forge_meta WHERE key = ?", (key,)
    ).fetchone()
    if row and row[0]:
        return row[0]
    return "concise"


def record_format_outcome(
    conn: sqlite3.Connection,
    workspace_id: str,
    variant: str,
    helped: bool,
) -> None:
    """Record A/B outcome in forge_meta as JSON: {concise: {helped: N, total: N}, detailed: {...}}."""
    key = f"ab_outcomes:{workspace_id}"
    row = conn.execute(
        "SELECT value FROM forge_meta WHERE key = ?", (key,)
    ).fetchone()

    if row and row[0]:
        data: dict = json.loads(row[0])
    else:
        data = {
            "concise": {"helped": 0, "total": 0},
            "detailed": {"helped": 0, "total": 0},
        }

    v = variant if variant in data else "concise"
    data[v]["total"] += 1
    if helped:
        data[v]["helped"] += 1

    conn.execute(
        """
        INSERT INTO forge_meta(key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, json.dumps(data)),
    )
    conn.commit()


def get_best_format(conn: sqlite3.Connection, workspace_id: str) -> str:
    """Return variant with higher helped rate. Min 10 observations each, else 'concise'."""
    key = f"ab_outcomes:{workspace_id}"
    row = conn.execute(
        "SELECT value FROM forge_meta WHERE key = ?", (key,)
    ).fetchone()

    if not row or not row[0]:
        return "concise"

    data: dict = json.loads(row[0])
    concise = data.get("concise", {"helped": 0, "total": 0})
    detailed = data.get("detailed", {"helped": 0, "total": 0})

    if concise["total"] < 10 or detailed["total"] < 10:
        return "concise"

    concise_rate = concise["helped"] / concise["total"]
    detailed_rate = detailed["helped"] / detailed["total"]
    return "detailed" if detailed_rate > concise_rate else "concise"


# --- Hint Quality Scoring ---

_VAGUE_WORDS = {"maybe", "sometimes", "might", "could", "possibly", "perhaps", "usually"}
_ACTION_VERBS = {
    "use", "avoid", "check", "run", "add", "remove", "set", "pass", "call",
    "import", "ensure", "prefer", "never", "always", "do",
}
_SPECIFIC_PATTERNS = [
    r"\b[A-Za-z_][A-Za-z0-9_]*\(\)",   # function calls e.g. foo()
    r"\.[a-z_]+",                         # attribute/method refs e.g. .method
    r"['\"][^'\"]{2,}['\"]",              # quoted strings
    r"\b[A-Z][A-Z0-9_]{2,}\b",           # constants / error names (ALL_CAPS)
    r"\b\w+Error\b|\b\w+Exception\b",    # error class names
    r"[/\\][\w.]+",                       # file paths
    r"--[\w-]+",                          # CLI flags
]


def score_hint_quality(hint: str) -> float:
    """Score hint text quality 0.0~1.0.

    Factors:
    - Length: 10-100 chars optimal (penalty outside)
    - Specificity: code patterns, file paths, error names → bonus
    - Actionability: starts with verb → bonus
    - Vagueness: hedging words → penalty
    """
    score = 0.5  # baseline

    length = len(hint)
    if 10 <= length <= 100:
        score += 0.2
    elif length < 10:
        score -= 0.3
    elif length > 200:
        score -= 0.1

    # Specificity bonus (capped at 0.2)
    specificity = 0.0
    for pat in _SPECIFIC_PATTERNS:
        if re.search(pat, hint):
            specificity = min(specificity + 0.05, 0.2)
    score += specificity

    # Actionability bonus
    first_word = hint.split()[0].lower().rstrip(".,;:") if hint.split() else ""
    if first_word in _ACTION_VERBS:
        score += 0.15

    # Vagueness penalty
    hint_lower = hint.lower()
    vague_count = sum(1 for w in _VAGUE_WORDS if w in hint_lower.split())
    score -= vague_count * 0.1

    return max(0.0, min(1.0, score))


def list_low_quality_hints(
    conn: sqlite3.Connection,
    workspace_id: str,
    threshold: float = 0.3,
) -> list[dict]:
    """Return failures with quality_score < threshold, sorted by score ascending."""
    rows = conn.execute(
        """
        SELECT pattern, avoid_hint, times_warned, times_helped
        FROM failures
        WHERE workspace_id = ? AND active = 1
        """,
        (workspace_id,),
    ).fetchall()

    results = []
    for row in rows:
        qs = score_hint_quality(row[1])
        if qs < threshold:
            results.append(
                {
                    "pattern": row[0],
                    "avoid_hint": row[1],
                    "quality_score": qs,
                    "times_warned": row[2],
                    "times_helped": row[3],
                }
            )

    results.sort(key=lambda x: x["quality_score"])
    return results


def suggest_hint_improvement(hint: str, pattern: str) -> str:
    """Generate improved hint text.

    - If too short: expand with pattern context
    - If too vague: remove hedging words
    - If not actionable: prefix with action verb
    """
    improved = hint.strip()

    if len(improved) < 10:
        improved = f"Avoid {pattern}: {improved or 'check implementation carefully'}"

    # Strip vague hedging words
    for vague in _VAGUE_WORDS:
        improved = re.sub(rf"\b{vague}\b", "", improved, flags=re.IGNORECASE).strip()
    improved = re.sub(r"\s{2,}", " ", improved).strip()

    # Prefix action verb if not actionable
    first_word = improved.split()[0].lower().rstrip(".,;:") if improved.split() else ""
    if first_word not in _ACTION_VERBS:
        if pattern.lower() in improved.lower():
            improved = f"Avoid {improved}"
        else:
            improved = f"Check: {improved}"

    return improved


# --- Skill Directive Analysis ---


def _score_directive_clarity(text: str, d_type: str) -> float:
    """Score a single directive's clarity 0.0~1.0."""
    score = 0.5

    if d_type == "threshold" and re.search(r"\d+", text):
        score += 0.2

    imperative_words = {
        "must", "never", "always", "avoid", "use", "run", "check", "prefer", "ensure"
    }
    if set(text.lower().split()) & imperative_words:
        score += 0.15

    if re.search(r"`[^`]+`|'[^']+'|\"[^\"]+\"", text):
        score += 0.15

    if len(text) < 15:
        score -= 0.3
    elif len(text) > 300:
        score -= 0.1

    return max(0.0, min(1.0, score))


def _classify_line_type(line: str) -> str:
    """Classify a directive line type."""
    lower = line.lower()
    if any(kw in lower for kw in [">=", "<=", "threshold", "cap:", "limit", "max", "min"]):
        return "threshold"
    if any(kw in lower for kw in ["step", "→", "->", "flow", "pipeline", "then"]):
        return "workflow"
    if any(kw in lower for kw in [
        "must", "never", "always", "required", "do not", "don't", "avoid",
        "prefer", "ensure", "check", "use", "run", "should",
    ]):
        return "rule"
    if "|" in line and line.count("|") >= 2:
        return "constraint"
    return "description"


def analyze_skill_directives(skill_content: str) -> list[dict]:
    """Parse SKILL.md content into directives with clarity scores.

    Returns list of {text, type, clarity_score}.
    """
    directives = []
    for line in skill_content.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        list_match = re.match(r"^[-*+]\s+(.+)$|^\d+\.\s+(.+)$", stripped)
        text = (list_match.group(1) or list_match.group(2)) if list_match else stripped

        d_type = _classify_line_type(text)
        clarity = _score_directive_clarity(text, d_type)
        directives.append({"text": text, "type": d_type, "clarity_score": clarity})

    return directives


def flag_problematic_directives(skill_path: str) -> list[dict]:
    """Return directives with clarity_score < 0.4 from a SKILL.md file path."""
    try:
        with open(skill_path, encoding="utf-8") as f:
            content = f.read()
    except (OSError, FileNotFoundError):
        return []

    all_directives = analyze_skill_directives(content)
    return [d for d in all_directives if d["clarity_score"] < 0.4]


def compute_skill_effectiveness(
    conn: sqlite3.Connection,
    workspace_id: str,
) -> list[dict]:
    """Per-skill metrics from forge_meta circuit breaker data.

    Returns [{skill_name, retry_rate, circuit_break_rate, avg_session_duration}].
    """
    breaker_key = f"circuit_breaker:{workspace_id}"
    row = conn.execute(
        "SELECT value FROM forge_meta WHERE key = ?", (breaker_key,)
    ).fetchone()

    if not row or not row[0]:
        return []

    try:
        breaker_data: dict = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return []

    results = []
    for skill_name, stats in breaker_data.items():
        calls = stats.get("calls", 0)
        trips = stats.get("trips", 0)
        circuit_break_rate = trips / calls if calls > 0 else 0.0
        results.append(
            {
                "skill_name": skill_name,
                "retry_rate": stats.get("retry_rate", 0.0),
                "circuit_break_rate": circuit_break_rate,
                "avg_session_duration": stats.get("avg_session_duration", 0.0),
            }
        )
    return results


# --- Injection Order ---


def compute_injection_score(
    failure: Failure,
    session_tags: list[str] | None = None,
    recency_days: float = 0.0,
) -> float:
    """Composite injection priority score.

    Formula: Q * (0.6 + 0.2*recency_weight + 0.2*relevance)
    - recency_weight = exp(-0.1 * recency_days)  (newer = higher)
    - relevance = Jaccard overlap of failure.tags with session_tags (0 if either empty)
    """
    recency_weight = math.exp(-0.1 * recency_days)

    relevance = 0.0
    if session_tags and failure.tags:
        session_set = set(session_tags)
        failure_set = set(failure.tags)
        union = session_set | failure_set
        if union:
            relevance = len(session_set & failure_set) / len(union)

    return failure.q * (0.6 + 0.2 * recency_weight + 0.2 * relevance)
