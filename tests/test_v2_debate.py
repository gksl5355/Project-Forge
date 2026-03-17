"""Tests for v2 debate engine."""

from __future__ import annotations

import pytest

from forge.config import ForgeConfig
from forge.engines.debate import (
    DebateResult,
    _build_proposal,
    _collect_context,
    _extract_tags,
    _parse_critique,
    _save_result_file,
    _save_decision,
)
from forge.storage.models import Failure, Knowledge
from forge.storage.queries import insert_failure, insert_knowledge, get_decision_by_id


@pytest.fixture
def config():
    return ForgeConfig()


class TestExtractTags:
    def test_basic(self):
        assert "jwt" in _extract_tags("JWT vs Session Auth")
        assert "session" in _extract_tags("JWT vs Session Auth")

    def test_filters_stopwords(self):
        tags = _extract_tags("Use the best approach for auth")
        assert "the" not in tags
        assert "for" not in tags

    def test_filters_short(self):
        tags = _extract_tags("a b cd efg")
        assert "a" not in tags
        assert "b" not in tags
        assert "efg" in tags


class TestCollectContext:
    def test_collects_failures(self, db, config):
        insert_failure(db, Failure(
            workspace_id="test_ws",
            pattern="auth_leak",
            avoid_hint="Check tokens",
            hint_quality="preventable",
            tags=["auth"],
        ))

        context = _collect_context("auth system review", "test_ws", db)
        assert any("auth_leak" in c for c in context)

    def test_empty_workspace(self, db):
        context = _collect_context("anything", "empty_ws", db)
        assert isinstance(context, list)


class TestBuildProposal:
    def test_basic(self):
        proposal = _build_proposal("JWT vs Session", ["[FAILURE] token_leak: Check expiry"])
        assert "JWT vs Session" in proposal
        assert "token_leak" in proposal

    def test_truncation(self):
        long_context = [f"[ITEM] {'x' * 500}" for _ in range(20)]
        proposal = _build_proposal("topic", long_context)
        assert len(proposal) <= 3000

    def test_no_context(self):
        proposal = _build_proposal("Simple topic", [])
        assert "Simple topic" in proposal


class TestParseCritique:
    def test_all_severities(self):
        text = """[BLOCK] Security: No input validation
[TRADEOFF] Performance: Extra network hop needed
[ACCEPT] Naming: Use consistent naming convention"""
        critiques = _parse_critique(text)
        assert len(critiques) == 3
        assert critiques[0]["severity"] == "BLOCK"
        assert critiques[1]["severity"] == "TRADEOFF"
        assert critiques[2]["severity"] == "ACCEPT"

    def test_with_surrounding_text(self):
        text = """Here are my findings:

[BLOCK] Auth: Missing rate limiting
Some detail about why this matters.

[ACCEPT] Code: Add type hints
"""
        critiques = _parse_critique(text)
        assert len(critiques) == 2

    def test_empty(self):
        assert _parse_critique("") == []
        assert _parse_critique("no critiques here") == []

    def test_category_and_summary(self):
        text = "[BLOCK] Security: SQL injection risk in user input"
        critiques = _parse_critique(text)
        assert critiques[0]["category"] == "Security"
        assert "SQL injection" in critiques[0]["summary"]


class TestSaveResultFile:
    def test_creates_file(self, tmp_path):
        result = DebateResult(
            topic="Test topic",
            proposal="Test proposal",
            critiques=[{"severity": "ACCEPT", "category": "Test", "summary": "Good"}],
            has_blocks=False,
        )
        path = _save_result_file(result)
        assert path.startswith("/tmp/debate-result-")
        from pathlib import Path
        content = Path(path).read_text()
        assert "Test topic" in content
        assert "ADOPTED" in content

    def test_rejected_with_blocks(self):
        result = DebateResult(
            topic="Bad idea",
            proposal="...",
            critiques=[{"severity": "BLOCK", "category": "Security", "summary": "Critical"}],
            has_blocks=True,
        )
        path = _save_result_file(result)
        from pathlib import Path
        content = Path(path).read_text()
        assert "REJECTED" in content


class TestSaveDecision:
    def test_saves_active_decision(self, db, config):
        critiques = [{"severity": "ACCEPT", "category": "Style", "summary": "OK"}]
        did = _save_decision("Good topic", "test_ws", critiques, db, config)
        assert did > 0

        d = get_decision_by_id(db, did, "test_ws")
        assert d is not None
        assert d.status == "active"
        assert "debate" in d.tags
        assert "[Debate]" in d.statement

    def test_saves_revisiting_with_blocks(self, db, config):
        critiques = [{"severity": "BLOCK", "category": "Security", "summary": "Bad"}]
        did = _save_decision("Blocked topic", "test_ws", critiques, db, config)

        d = get_decision_by_id(db, did, "test_ws")
        assert d.status == "revisiting"
