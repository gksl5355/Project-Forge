"""Tests for forge.core.output_analyzer."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from forge.core.output_analyzer import (
    OutputPattern,
    analyze_transcript_outputs,
    generate_output_hints,
    _estimate_useful_portion,
    _generate_summary_hint,
    _normalize_command,
)


class TestNormalizeCommand:
    """Test command normalization."""

    def test_pytest_with_args(self) -> None:
        """Pytest with file and flags normalizes to 'pytest *'."""
        assert _normalize_command("pytest tests/test_foo.py -v") == "pytest *"
        assert _normalize_command("pytest tests/ -xvs") == "pytest *"

    def test_grep_with_pattern(self) -> None:
        """Grep with pattern and flags normalizes to 'grep *'."""
        assert _normalize_command('grep -r "pattern" src/') == "grep *"
        assert _normalize_command("grep -n error logs/") == "grep *"

    def test_cat_with_file(self) -> None:
        """Cat with file normalizes to 'cat *'."""
        assert _normalize_command("cat src/foo.py") == "cat *"
        assert _normalize_command("cat /home/user/file.txt") == "cat *"

    def test_git_status_preserved(self) -> None:
        """Simple git status command is preserved."""
        assert _normalize_command("git status") == "git status"

    def test_git_log_subcommand(self) -> None:
        """Git log subcommand is preserved."""
        assert _normalize_command("git log --oneline") == "git log"
        assert _normalize_command("git log -n 10") == "git log"

    def test_git_diff_subcommand(self) -> None:
        """Git diff subcommand is preserved."""
        assert _normalize_command("git diff HEAD") == "git diff"

    def test_ls_command(self) -> None:
        """Ls command is preserved."""
        assert _normalize_command("ls") == "ls"
        assert _normalize_command("ls -la /home") == "ls *"

    def test_simple_git_subcommand(self) -> None:
        """Git show subcommand is preserved."""
        assert _normalize_command("git show abc123") == "git show"

    def test_pathlike_commands(self) -> None:
        """Commands with paths are normalized."""
        assert _normalize_command("./script.py arg1") == "script.py *"
        assert _normalize_command("/usr/bin/python -m pytest") == "python *"

    def test_empty_command(self) -> None:
        """Empty command returns wildcard."""
        assert _normalize_command("") == "*"
        assert _normalize_command("   ") == "*"

    def test_single_word_commands(self) -> None:
        """Single-word simple commands are preserved."""
        assert _normalize_command("pwd") == "pwd"
        assert _normalize_command("whoami") == "whoami"


class TestEstimateUsefulPortion:
    """Test useful portion estimation."""

    def test_pytest_output_with_summary(self) -> None:
        """Pytest output: extracts summary lines."""
        output = "test_foo.py ..\ntest_bar.py .F\n" + "x" * 5000 + "\n2 passed, 1 failed in 1.23s"
        useful = _estimate_useful_portion(output, "pytest tests/")
        # Should capture the summary lines
        assert useful > 100
        assert useful < len(output) / 2

    def test_pytest_output_large(self) -> None:
        """Pytest output: defaults to 20% if no summary found."""
        output = "test line 1\n" + "x" * 5000
        useful = _estimate_useful_portion(output, "pytest tests/")
        assert useful > 0

    def test_grep_output(self) -> None:
        """Grep output: extracts match results."""
        # Create output with many lines where grep output is sparse
        lines = ["file1:match line"] + ["x" * 100 for _ in range(20)]
        output = "\n".join(lines)
        useful = _estimate_useful_portion(output, "grep -r pattern")
        # Should be significantly less than full output
        assert useful < len(output) * 0.5
        assert useful > 50

    def test_git_status_full(self) -> None:
        """Git status: full output is useful."""
        output = "On branch main\nModified: file.py\nUntracked: new.py"
        useful = _estimate_useful_portion(output, "git status")
        assert useful == len(output)

    def test_git_log_partial(self) -> None:
        """Git log: only first entries matter."""
        lines = ["commit abc"] * 100
        output = "\n".join(lines)
        useful = _estimate_useful_portion(output, "git log --oneline")
        # Should be < full output but reasonable portion
        assert useful < len(output)

    def test_cat_file_output(self) -> None:
        """Cat output: only first lines matter."""
        lines = ["line " + str(i) for i in range(100)]
        output = "\n".join(lines)
        useful = _estimate_useful_portion(output, "cat large_file.py")
        # Should limit to first ~20 lines
        assert useful < len(output)

    def test_ls_output(self) -> None:
        """Ls output: directory listings are fully useful."""
        output = "file1.py\nfile2.py\ndir/\n"
        useful = _estimate_useful_portion(output, "ls -la /home")
        assert useful == len(output)

    def test_large_output_default(self) -> None:
        """Large output with unknown command: estimate 20%."""
        output = "x" * 5000
        useful = _estimate_useful_portion(output, "unknown command")
        assert useful == int(5000 * 0.2)

    def test_small_output_preserved(self) -> None:
        """Small output (<2000 chars): assume most is useful."""
        output = "small output"
        useful = _estimate_useful_portion(output, "unknown command")
        assert useful == len(output)

    def test_empty_output(self) -> None:
        """Empty output returns 0."""
        assert _estimate_useful_portion("", "any command") == 0


class TestGenerateSummaryHint:
    """Test summary hint generation."""

    def test_pytest_hint(self) -> None:
        """Pytest patterns generate relevant hints."""
        hint = _generate_summary_hint("pytest *", 5000, 200)
        assert "Test output" in hint
        assert "pass/fail" in hint

    def test_grep_hint(self) -> None:
        """Grep patterns generate relevant hints."""
        hint = _generate_summary_hint("grep *", 3000, 100)
        assert "Grep output" in hint
        assert "match count" in hint

    def test_git_log_hint(self) -> None:
        """Git log patterns generate relevant hints."""
        hint = _generate_summary_hint("git log", 4000, 500)
        assert "Git log" in hint

    def test_cat_hint(self) -> None:
        """Cat/file read patterns generate relevant hints."""
        hint = _generate_summary_hint("cat *", 6000, 300)
        assert "File read" in hint

    def test_generic_hint(self) -> None:
        """Unknown patterns generate generic hints."""
        hint = _generate_summary_hint("unknown *", 2000, 400)
        assert "unknown *" in hint


class TestAnalyzeTranscriptOutputs:
    """Test transcript output analysis."""

    def test_nonexistent_file(self) -> None:
        """Nonexistent transcript returns empty list."""
        result = analyze_transcript_outputs(Path("/nonexistent/path.jsonl"))
        assert result == []

    def test_empty_transcript(self) -> None:
        """Empty transcript returns empty list."""
        with TemporaryDirectory() as tmpdir:
            transcript_path = Path(tmpdir) / "transcript.jsonl"
            transcript_path.write_text("")
            result = analyze_transcript_outputs(transcript_path)
            assert result == []

    def test_single_bash_call_with_output(self) -> None:
        """Single bash call with output creates one pattern."""
        with TemporaryDirectory() as tmpdir:
            transcript_path = Path(tmpdir) / "transcript.jsonl"

            # Tool use
            transcript_path.write_text(
                json.dumps({"type": "tool_use", "tool_name": "Bash", "id": "1", "tool_input": {"command": "pytest tests/"}})
                + "\n"
            )

            # Tool result
            with open(transcript_path, "a") as f:
                f.write(
                    json.dumps(
                        {
                            "type": "tool_result",
                            "tool_use_id": "1",
                            "content": "test passed\n" + "x" * 3000,
                        }
                    )
                    + "\n"
                )

            result = analyze_transcript_outputs(transcript_path)
            assert len(result) == 1
            assert result[0].command_pattern == "pytest *"
            assert result[0].occurrences == 1
            assert result[0].avg_output_size > 3000

    def test_multiple_same_commands(self) -> None:
        """Multiple same commands are aggregated."""
        with TemporaryDirectory() as tmpdir:
            transcript_path = Path(tmpdir) / "transcript.jsonl"

            lines = []
            for i in range(3):
                # Tool use
                lines.append(
                    json.dumps(
                        {
                            "type": "tool_use",
                            "tool_name": "Bash",
                            "id": str(i),
                            "tool_input": {"command": "grep -r pattern"},
                        }
                    )
                )
                # Tool result
                lines.append(
                    json.dumps(
                        {
                            "type": "tool_result",
                            "tool_use_id": str(i),
                            "content": "match1\nmatch2\n" + "x" * (1000 * (i + 1)),
                        }
                    )
                )

            transcript_path.write_text("\n".join(lines))

            result = analyze_transcript_outputs(transcript_path)
            assert len(result) == 1
            assert result[0].command_pattern == "grep *"
            assert result[0].occurrences == 3

    def test_non_bash_tools_ignored(self) -> None:
        """Non-Bash tools are ignored."""
        with TemporaryDirectory() as tmpdir:
            transcript_path = Path(tmpdir) / "transcript.jsonl"

            lines = [
                json.dumps({"type": "tool_use", "tool_name": "Read", "id": "1", "tool_input": {"file_path": "foo.py"}}),
                json.dumps({"type": "tool_result", "tool_use_id": "1", "content": "file content"}),
            ]

            transcript_path.write_text("\n".join(lines))

            result = analyze_transcript_outputs(transcript_path)
            assert result == []

    def test_malformed_json_skipped(self) -> None:
        """Malformed JSON lines are skipped gracefully."""
        with TemporaryDirectory() as tmpdir:
            transcript_path = Path(tmpdir) / "transcript.jsonl"

            lines = [
                json.dumps({"type": "tool_use", "tool_name": "Bash", "id": "1", "tool_input": {"command": "ls"}}),
                "not valid json",
                json.dumps({"type": "tool_result", "tool_use_id": "1", "content": "file1\nfile2"}),
            ]

            transcript_path.write_text("\n".join(lines))

            result = analyze_transcript_outputs(transcript_path)
            assert len(result) == 1

    def test_claude_code_format_list_content(self) -> None:
        """Claude Code format with content as list is handled."""
        with TemporaryDirectory() as tmpdir:
            transcript_path = Path(tmpdir) / "transcript.jsonl"

            lines = [
                json.dumps({"type": "tool_use", "tool_name": "Bash", "id": "1", "tool_input": {"command": "pytest"}}),
                json.dumps(
                    {
                        "type": "tool_result",
                        "tool_use_id": "1",
                        "content": [
                            {"type": "text", "text": "test output part1\n"},
                            {"type": "text", "text": "test output part2\n" + "x" * 2000},
                        ],
                    }
                ),
            ]

            transcript_path.write_text("\n".join(lines))

            result = analyze_transcript_outputs(transcript_path)
            assert len(result) == 1
            assert result[0].avg_output_size > 2000

    def test_results_sorted_by_size(self) -> None:
        """Results are sorted by output size descending."""
        with TemporaryDirectory() as tmpdir:
            transcript_path = Path(tmpdir) / "transcript.jsonl"

            lines = []
            # Small output
            lines.append(
                json.dumps({"type": "tool_use", "tool_name": "Bash", "id": "1", "tool_input": {"command": "pwd"}})
            )
            lines.append(json.dumps({"type": "tool_result", "tool_use_id": "1", "content": "/home"}))

            # Large output
            lines.append(
                json.dumps({"type": "tool_use", "tool_name": "Bash", "id": "2", "tool_input": {"command": "grep test"}})
            )
            lines.append(json.dumps({"type": "tool_result", "tool_use_id": "2", "content": "x" * 5000}))

            transcript_path.write_text("\n".join(lines))

            result = analyze_transcript_outputs(transcript_path)
            # Should be sorted by size
            assert result[0].avg_output_size >= result[1].avg_output_size


class TestGenerateOutputHints:
    """Test hint generation for knowledge insertion."""

    def test_empty_patterns(self) -> None:
        """Empty pattern list returns empty hints."""
        result = generate_output_hints([])
        assert result == []

    def test_only_scriptable_patterns_included(self) -> None:
        """Only scriptable patterns (>30% waste) are included."""
        patterns = [
            OutputPattern(
                command_pattern="pytest *",
                avg_output_size=5000,
                avg_useful_size=200,  # 4% useful
                occurrences=3,
                summary_hint="Test summary",
                scriptable=True,
            ),
            OutputPattern(
                command_pattern="ls *",
                avg_output_size=1000,
                avg_useful_size=900,  # 90% useful
                occurrences=2,
                summary_hint="Directory listing",
                scriptable=False,
            ),
        ]

        result = generate_output_hints(patterns)
        assert len(result) == 1
        assert "pytest" in result[0]["title"]

    def test_hint_structure(self) -> None:
        """Generated hints have correct structure."""
        pattern = OutputPattern(
            command_pattern="grep *",
            avg_output_size=3000,
            avg_useful_size=100,
            occurrences=5,
            summary_hint="Match count only needed",
            scriptable=True,
        )

        result = generate_output_hints([pattern])
        assert len(result) == 1

        hint = result[0]
        assert "title" in hint
        assert "content" in hint
        assert "tags" in hint

        assert "grep" in hint["title"]
        assert "grep *" in hint["content"]
        assert "5 occurrences" in hint["content"]
        assert "3000 chars" in hint["content"]
        assert "100 chars" in hint["content"]
        assert "output-pattern" in hint["tags"]

    def test_efficiency_percentage(self) -> None:
        """Efficiency percentage is calculated correctly."""
        pattern = OutputPattern(
            command_pattern="pytest *",
            avg_output_size=5000,
            avg_useful_size=1000,  # 20%
            occurrences=1,
            summary_hint="Test output",
            scriptable=True,
        )

        result = generate_output_hints([pattern])
        assert len(result) == 1
        assert "20%" in result[0]["content"]

    def test_multiple_patterns(self) -> None:
        """Multiple scriptable patterns generate multiple hints."""
        patterns = [
            OutputPattern(
                command_pattern="pytest *",
                avg_output_size=4000,
                avg_useful_size=100,
                occurrences=3,
                summary_hint="Test summary",
                scriptable=True,
            ),
            OutputPattern(
                command_pattern="grep *",
                avg_output_size=3000,
                avg_useful_size=150,
                occurrences=2,
                summary_hint="Match count",
                scriptable=True,
            ),
        ]

        result = generate_output_hints(patterns)
        assert len(result) == 2


class TestIntegration:
    """Integration tests for full workflow."""

    def test_analyze_and_generate_hints(self) -> None:
        """Full workflow: analyze transcript and generate hints."""
        with TemporaryDirectory() as tmpdir:
            transcript_path = Path(tmpdir) / "transcript.jsonl"

            lines = []
            # Pytest calls
            for i in range(2):
                lines.append(
                    json.dumps(
                        {
                            "type": "tool_use",
                            "tool_name": "Bash",
                            "id": f"pytest{i}",
                            "tool_input": {"command": "pytest tests/"},
                        }
                    )
                )
                lines.append(
                    json.dumps(
                        {
                            "type": "tool_result",
                            "tool_use_id": f"pytest{i}",
                            "content": "test passed\n" + "x" * 4000,
                        }
                    )
                )

            transcript_path.write_text("\n".join(lines))

            # Analyze
            patterns = analyze_transcript_outputs(transcript_path)
            assert len(patterns) == 1

            # Generate hints
            hints = generate_output_hints(patterns)
            assert len(hints) >= 1

            # Verify hint content
            hint = hints[0]
            assert "pytest" in hint["title"]
            assert "occurrences" in hint["content"].lower()
