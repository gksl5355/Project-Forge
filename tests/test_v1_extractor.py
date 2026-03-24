"""Tests for v1 LLM extractor (offline parsing only, no API calls)."""

from __future__ import annotations

import json
import pytest

from forge.extras.extractor import _parse_extraction_response


class TestParseExtractionResponse:
    def test_valid_json_array(self):
        text = json.dumps([
            {"type": "failure", "pattern": "missing_dep", "hint": "Install dep first", "quality": "preventable", "tags": ["python"]},
            {"type": "decision", "statement": "Use SQLite", "rationale": "Simple", "tags": ["arch"]},
        ])
        results = _parse_extraction_response(text)
        assert len(results) == 2
        assert results[0]["type"] == "failure"
        assert results[0]["pattern"] == "missing_dep"
        assert results[0]["source"] == "llm_extract"
        assert results[1]["type"] == "decision"

    def test_json_in_markdown_block(self):
        text = '```json\n[{"type": "failure", "pattern": "test", "hint": "fix it", "quality": "near_miss"}]\n```'
        results = _parse_extraction_response(text)
        assert len(results) == 1
        assert results[0]["quality"] == "near_miss"

    def test_json_with_surrounding_text(self):
        text = 'Here are the results:\n[{"type": "failure", "pattern": "err", "hint": "h"}]\nDone.'
        results = _parse_extraction_response(text)
        assert len(results) == 1

    def test_invalid_quality_defaults_to_preventable(self):
        text = json.dumps([
            {"type": "failure", "pattern": "test", "hint": "h", "quality": "invalid_quality"},
        ])
        results = _parse_extraction_response(text)
        assert results[0]["quality"] == "preventable"

    def test_missing_required_fields_skipped(self):
        text = json.dumps([
            {"type": "failure"},  # no pattern or hint
            {"type": "decision"},  # no statement
            {"type": "failure", "pattern": "good", "hint": "valid"},
        ])
        results = _parse_extraction_response(text)
        assert len(results) == 1
        assert results[0]["pattern"] == "good"

    def test_truncation_enforced(self):
        long_pattern = "x" * 300
        long_hint = "y" * 3000
        text = json.dumps([
            {"type": "failure", "pattern": long_pattern, "hint": long_hint},
        ])
        results = _parse_extraction_response(text)
        assert len(results[0]["pattern"]) <= 200
        assert len(results[0]["hint"]) <= 2000

    def test_non_list_response(self):
        assert _parse_extraction_response('{"not": "a list"}') == []

    def test_completely_invalid_json(self):
        assert _parse_extraction_response("not json at all") == []

    def test_empty_string(self):
        assert _parse_extraction_response("") == []

    def test_non_dict_items_skipped(self):
        text = json.dumps([
            "string item",
            42,
            {"type": "failure", "pattern": "valid", "hint": "h"},
        ])
        results = _parse_extraction_response(text)
        assert len(results) == 1

    def test_unknown_type_skipped(self):
        text = json.dumps([
            {"type": "unknown", "data": "something"},
            {"type": "failure", "pattern": "p", "hint": "h"},
        ])
        results = _parse_extraction_response(text)
        assert len(results) == 1
