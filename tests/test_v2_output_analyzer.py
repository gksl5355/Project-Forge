"""Tests for v2 output analyzer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.core.output_analyzer import (
    OutputPattern,
    _estimate_useful_portion,
    _generate_summary_hint,
    _normalize_command,
    analyze_transcript_outputs,
    generate_output_hints,
)


class TestNormalizeCommand:
    def test_pytest(self):
        assert _normalize_command("pytest tests/test_foo.py -v") == "pytest *"

    def test_grep(self):
        assert _normalize_command("grep -r 'pattern' src/") == "grep *"

    def test_git_status(self):
        assert _normalize_command("git status") == "git status"

    def test_git_log(self):
        assert _normalize_command("git log --oneline -5") == "git log"

    def test_cat(self):
        assert _normalize_command("cat src/foo.py") == "cat *"

    def test_empty(self):
        assert _normalize_command("") == "*"

    def test_path_command(self):
        assert _normalize_command("/usr/bin/python3 script.py") == "python3 *"


class TestEstimateUsefulPortion:
    def test_pytest_output(self):
        output = "\n".join([
            "tests/test_a.py::test_1 PASSED",
            "tests/test_a.py::test_2 PASSED",
            "tests/test_b.py::test_3 FAILED",
            "=" * 40,
            "VERBOSE OUTPUT LINE " * 50,
            "=" * 40,
            "2 passed, 1 failed in 0.5s",
        ])
        useful = _estimate_useful_portion(output, "pytest tests/ -v")
        assert useful < len(output)

    def test_git_status_full(self):
        output = "On branch main\nnothing to commit"
        assert _estimate_useful_portion(output, "git status") == len(output)

    def test_empty_output(self):
        assert _estimate_useful_portion("", "any") == 0

    def test_large_default(self):
        output = "x" * 5000
        useful = _estimate_useful_portion(output, "unknown_cmd")
        assert useful == 1000  # 20% of 5000


class TestGenerateSummaryHint:
    def test_pytest(self):
        hint = _generate_summary_hint("pytest *", 5000, 500)
        assert "Test output" in hint

    def test_grep(self):
        hint = _generate_summary_hint("grep *", 3000, 200)
        assert "Grep output" in hint

    def test_generic(self):
        hint = _generate_summary_hint("unknown *", 2000, 400)
        assert "20%" in hint


class TestAnalyzeTranscriptOutputs:
    def test_basic_transcript(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps({"type": "tool_use", "id": "t1", "tool_name": "Bash", "tool_input": {"command": "pytest tests/ -v"}}),
            json.dumps({"type": "tool_result", "tool_use_id": "t1", "content": "x" * 5000 + "\n5 passed in 1.0s"}),
        ]
        transcript.write_text("\n".join(lines))

        patterns = analyze_transcript_outputs(transcript)
        assert len(patterns) >= 1
        assert patterns[0].command_pattern == "pytest *"

    def test_nonexistent_file(self, tmp_path):
        assert analyze_transcript_outputs(tmp_path / "nope.jsonl") == []

    def test_empty_file(self, tmp_path):
        transcript = tmp_path / "empty.jsonl"
        transcript.write_text("")
        assert analyze_transcript_outputs(transcript) == []

    def test_malformed_json(self, tmp_path):
        transcript = tmp_path / "bad.jsonl"
        transcript.write_text("not json\nalso not json\n")
        assert analyze_transcript_outputs(transcript) == []


class TestGenerateOutputHints:
    def test_scriptable_pattern(self):
        patterns = [
            OutputPattern(
                command_pattern="pytest *",
                avg_output_size=5000,
                avg_useful_size=500,
                occurrences=3,
                summary_hint="Test output...",
                scriptable=True,
            ),
        ]
        hints = generate_output_hints(patterns)
        assert len(hints) == 1
        assert "pytest" in hints[0]["title"]
        assert "output-pattern" in hints[0]["tags"]

    def test_non_scriptable_excluded(self):
        patterns = [
            OutputPattern(
                command_pattern="git status",
                avg_output_size=200,
                avg_useful_size=200,
                occurrences=5,
                summary_hint="Full output useful",
                scriptable=False,
            ),
        ]
        hints = generate_output_hints(patterns)
        assert len(hints) == 0

    def test_high_efficiency_excluded(self):
        patterns = [
            OutputPattern(
                command_pattern="ls *",
                avg_output_size=1000,
                avg_useful_size=900,
                occurrences=2,
                summary_hint="...",
                scriptable=True,  # even if marked, efficiency > 30%
            ),
        ]
        hints = generate_output_hints(patterns)
        assert len(hints) == 0
