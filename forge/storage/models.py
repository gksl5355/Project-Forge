"""Dataclass models for all Forge entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC


@dataclass
class Failure:
    workspace_id: str
    pattern: str
    avoid_hint: str
    hint_quality: str          # near_miss | preventable | environmental
    q: float = 0.5
    times_seen: int = 1
    times_helped: int = 0
    times_warned: int = 0
    tags: list[str] = field(default_factory=list)
    projects_seen: list[str] = field(default_factory=list)
    source: str = "manual"     # auto | manual | organic
    review_flag: bool = False
    observed_error: str | None = None
    likely_cause: str | None = None
    last_used: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: int | None = None


@dataclass
class Decision:
    workspace_id: str
    statement: str
    q: float = 0.5
    status: str = "active"     # active | superseded | revisiting
    rationale: str | None = None
    alternatives: list[str] = field(default_factory=list)
    superseded_by: int | None = None
    tags: list[str] = field(default_factory=list)
    last_used: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: int | None = None


@dataclass
class Rule:
    workspace_id: str
    rule_text: str
    scope: str | None = None
    enforcement_mode: str = "warn"  # block | warn | log
    active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: int | None = None


@dataclass
class Knowledge:
    workspace_id: str
    title: str
    content: str
    source: str = "seeded"     # seeded | organic
    q: float = 0.5
    tags: list[str] = field(default_factory=list)
    promoted_from: int | None = None
    last_used: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: int | None = None


@dataclass
class Session:
    session_id: str
    workspace_id: str
    warnings_injected: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    id: int | None = None
