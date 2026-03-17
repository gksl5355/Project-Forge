"""Output Analyzer: Identifies "scriptable" tool outputs for context optimization.

Analyzes transcript outputs to learn which ones produce large outputs but only
a small useful portion, helping prevent context pollution in future sessions.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("forge")

# Pre-compiled regex patterns for pytest output analysis
_PYTEST_SUMMARY_PATTERNS = [
    re.compile(r".*passed.*", re.IGNORECASE),
    re.compile(r".*failed.*", re.IGNORECASE),
    re.compile(r".*error.*", re.IGNORECASE),
    re.compile(r".*skipped.*", re.IGNORECASE),
    re.compile(r"=+ .* in [\d.]+s =+"),
]


@dataclass
class OutputPattern:
    """Pattern of tool output behavior across occurrences."""

    command_pattern: str  # normalized command (e.g., "pytest *", "grep *")
    avg_output_size: int  # average output chars
    avg_useful_size: int  # estimated useful portion
    occurrences: int  # how many times seen
    summary_hint: str  # e.g., "Test output: only pass/fail summary needed"
    scriptable: bool  # can be handled locally


def analyze_transcript_outputs(transcript_path: Path) -> list[OutputPattern]:
    """Parse a transcript.jsonl file and analyze tool outputs.

    For each Bash tool call, checks:
    - Output length (chars)
    - Whether the output was "used" (referenced in subsequent assistant messages)
    - Command pattern (what was run)

    Identifies patterns where output was large (>1000 chars) but the useful
    part was small.

    Args:
        transcript_path: Path to transcript.jsonl file

    Returns:
        List of OutputPattern objects
    """
    if not transcript_path.exists():
        logger.warning("Transcript file not found: %s", transcript_path)
        return []

    try:
        lines = transcript_path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        logger.warning("Failed to read transcript: %s", e)
        return []

    # Parse transcript into tool calls and results
    tool_calls: dict[str, dict] = {}  # tool_use_id -> {"command": str, "output": str}
    assistant_messages: list[str] = []

    for line_num, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue

        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("Skipping malformed JSON line %d", line_num)
            continue

        obj_type = obj.get("type", "")

        # Capture tool uses (Bash commands)
        if obj_type == "tool_use":
            tool_name = obj.get("tool_name", "")
            if tool_name == "Bash":
                tool_id = obj.get("id", "")
                tool_input = obj.get("tool_input", {})
                if isinstance(tool_input, dict):
                    command = tool_input.get("command", "")
                    tool_calls[tool_id] = {"command": command, "output": "", "output_size": 0}

        # Capture tool results (outputs)
        elif obj_type == "tool_result":
            tool_use_id = obj.get("tool_use_id", "")
            if tool_use_id in tool_calls:
                content = obj.get("content", "")
                if isinstance(content, str):
                    output = content
                elif isinstance(content, list):
                    # Claude Code format: list of dicts
                    text_parts = []
                    for item in content:
                        if isinstance(item, dict):
                            text_parts.append(item.get("text", ""))
                    output = "".join(text_parts)
                else:
                    output = str(content)

                tool_calls[tool_use_id]["output"] = output
                tool_calls[tool_use_id]["output_size"] = len(output)

        # Capture assistant messages (to detect if output was used)
        elif obj_type == "text":
            content = obj.get("content", "")
            if isinstance(content, str):
                assistant_messages.append(content)

    # Analyze tool calls to identify patterns
    patterns_dict: dict[str, list[dict]] = {}  # command_pattern -> [{"output_size": int, "useful_size": int}]

    for tool_id, tool_info in tool_calls.items():
        command = tool_info["command"]
        output_size = tool_info["output_size"]
        output = tool_info["output"]

        if not command or output_size == 0:
            continue

        # Normalize command to pattern
        pattern = _normalize_command(command)

        # Estimate useful portion
        useful_size = _estimate_useful_portion(output, command)

        if pattern not in patterns_dict:
            patterns_dict[pattern] = []

        patterns_dict[pattern].append({"output_size": output_size, "useful_size": useful_size})

    # Convert patterns to OutputPattern objects
    results: list[OutputPattern] = []

    for pattern, occurrences_data in patterns_dict.items():
        if not occurrences_data:
            continue

        avg_output_size = int(sum(o["output_size"] for o in occurrences_data) / len(occurrences_data))
        avg_useful_size = int(sum(o["useful_size"] for o in occurrences_data) / len(occurrences_data))
        occurrences = len(occurrences_data)

        # Generate hint based on pattern
        summary_hint = _generate_summary_hint(pattern, avg_output_size, avg_useful_size)

        # Determine if scriptable (can be handled locally)
        scriptable = avg_output_size > 1000 and avg_useful_size < avg_output_size * 0.3

        results.append(
            OutputPattern(
                command_pattern=pattern,
                avg_output_size=avg_output_size,
                avg_useful_size=avg_useful_size,
                occurrences=occurrences,
                summary_hint=summary_hint,
                scriptable=scriptable,
            )
        )

    # Sort by output size descending
    results.sort(key=lambda x: x.avg_output_size, reverse=True)

    return results


def _normalize_command(command: str) -> str:
    """Normalize commands for pattern matching.

    Examples:
    - "pytest tests/test_foo.py -v" → "pytest *"
    - "grep -r "pattern" src/" → "grep *"
    - "cat src/foo.py" → "cat *"
    - "git status" → "git status"

    Args:
        command: Raw command string

    Returns:
        Normalized command pattern
    """
    if not command or not isinstance(command, str):
        return "*"

    command = command.strip()

    # Split into tokens
    parts = command.split()
    if not parts:
        return "*"

    base_cmd = parts[0]

    # Extract command name (handle paths like ./script.py)
    if "/" in base_cmd:
        base_cmd = base_cmd.split("/")[-1]

    # Commands that should be kept as-is (simple, no args)
    simple_commands = {"git", "ls", "pwd", "whoami", "date"}

    # git subcommands that should be kept
    if base_cmd == "git" and len(parts) > 1:
        git_subcmd = parts[1]
        if git_subcmd in {"status", "log", "diff", "show"}:
            return f"git {git_subcmd}"

    # For simple commands, check if they have meaningful subcommands
    if base_cmd in simple_commands:
        if len(parts) == 1:
            return base_cmd
        return f"{base_cmd} *"

    # For all other commands, collapse to pattern
    return f"{base_cmd} *"


def _estimate_useful_portion(output: str, command: str) -> int:
    """Estimate the useful portion of output.

    Strategy:
    - pytest output: count lines with "passed", "failed", "error"
    - grep output: just the match count
    - git status: full output is useful
    - Large file reads: likely only a few lines matter
    - Default: if output > 2000 chars, estimate 20% is useful

    Args:
        output: The tool output string
        command: The command that was run

    Returns:
        Estimated number of useful characters
    """
    if not output:
        return 0

    output_size = len(output)
    command_lower = command.lower() if isinstance(command, str) else ""

    # pytest output: extract summary lines
    if "pytest" in command_lower:
        useful_lines = []
        for line in output.split("\n"):
            if any(p.search(line) for p in _PYTEST_SUMMARY_PATTERNS):
                useful_lines.append(line)

        if useful_lines:
            useful_text = "\n".join(useful_lines)
            # Return useful portion, but at least a few lines
            return max(200, len(useful_text))

        # Fallback: if no summary found, return 20% estimate
        return max(200, int(output_size * 0.2))

    # grep output: extract match count
    if "grep" in command_lower:
        # Usually just interested in the count of matches
        lines = output.split("\n")
        # In most cases, only the last few lines matter (summary)
        # Be conservative: return estimate if many lines
        if len(lines) > 10:
            # Many lines -> probably padded output, return 20% estimate
            return max(100, int(output_size * 0.2))
        useful_lines = lines[-3:] if len(lines) > 3 else lines
        useful_text = "\n".join(useful_lines)
        return max(100, len(useful_text))

    # git status: full output is typically useful
    if "git" in command_lower and "status" in command_lower:
        return output_size

    # git log/show: usually only first few entries matter
    if "git" in command_lower and ("log" in command_lower or "show" in command_lower):
        lines = output.split("\n")
        # First few commit entries (usually ~20-50 lines useful)
        useful_lines = lines[:50]
        useful_text = "\n".join(useful_lines)
        return min(output_size, len(useful_text))

    # cat/file read: typically only first/last few lines matter
    if any(cmd in command_lower for cmd in {"cat", "head", "tail", "less", "more"}):
        lines = output.split("\n")
        # Usually only 5-20 lines matter
        useful_lines = lines[:20] if len(lines) > 20 else lines
        useful_text = "\n".join(useful_lines)
        return len(useful_text)

    # ls output: directory listings are usually useful in full
    if "ls" in command_lower:
        return output_size

    # Default: if output is large, estimate 20% is useful
    if output_size > 2000:
        return int(output_size * 0.2)

    # For smaller outputs, assume most is useful
    return output_size


def _generate_summary_hint(pattern: str, avg_output_size: int, avg_useful_size: int) -> str:
    """Generate a human-readable hint for an output pattern.

    Args:
        pattern: Normalized command pattern
        avg_output_size: Average output size
        avg_useful_size: Average useful portion size

    Returns:
        Human-readable hint string
    """
    if "pytest" in pattern:
        return f"Test output: full output ~{avg_output_size}B, useful summary ~{avg_useful_size}B (pass/fail lines)"
    elif "grep" in pattern:
        return f"Grep output: full output ~{avg_output_size}B, useful summary ~{avg_useful_size}B (match count)"
    elif "git log" in pattern:
        return f"Git log: full output ~{avg_output_size}B, useful portion ~{avg_useful_size}B (first few commits)"
    elif "git" in pattern:
        return f"Git output: ~{avg_output_size}B, useful ~{avg_useful_size}B"
    elif "cat" in pattern or "head" in pattern or "tail" in pattern:
        return f"File read: full output ~{avg_output_size}B, useful ~{avg_useful_size}B (first/last lines)"
    elif "ls" in pattern:
        return f"Directory listing: ~{avg_output_size}B"
    else:
        efficiency = int(100 * (avg_useful_size / avg_output_size)) if avg_output_size > 0 else 0
        return f"Command '{pattern}': output ~{avg_output_size}B, useful ~{avg_useful_size}B ({efficiency}% useful)"


def generate_output_hints(patterns: list[OutputPattern]) -> list[dict]:
    """Convert patterns into knowledge entries for Forge.

    Only includes patterns where avg_useful_size < avg_output_size * 0.3
    (less than 30% useful).

    Args:
        patterns: List of OutputPattern objects

    Returns:
        List of dicts with: title, content, tags for insertion as Knowledge
    """
    hints: list[dict] = []

    for pattern in patterns:
        # Only include patterns with significant waste
        if pattern.avg_output_size == 0 or not pattern.scriptable:
            continue

        efficiency = pattern.avg_useful_size / pattern.avg_output_size
        if efficiency >= 0.3:
            continue

        # Build knowledge entry
        title = f"Output Pattern: {pattern.command_pattern}"
        content = (
            f"**Command Pattern:** {pattern.command_pattern}\n\n"
            f"**Observations:** {pattern.occurrences} occurrences\n\n"
            f"**Output Size:** ~{pattern.avg_output_size} chars (average)\n\n"
            f"**Useful Portion:** ~{pattern.avg_useful_size} chars ({int(efficiency*100)}% of output)\n\n"
            f"**Hint:** {pattern.summary_hint}\n\n"
            f"**Recommendation:** Capture only the summary/useful portion to reduce context pollution."
        )
        tags = ["output-pattern", "scriptable", pattern.command_pattern.split()[0]]

        hints.append({"title": title, "content": content, "tags": tags})

    return hints
