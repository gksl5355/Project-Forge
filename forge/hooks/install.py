"""Hook installation and full Forge setup."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
_HOOKS_DIR = Path.home() / ".forge" / "hooks"
_SKILLS_DIR = Path.home() / ".claude" / "skills"
_HOOK_TEMPLATES = Path(__file__).parent / "templates"
_SKILL_SOURCES = Path(__file__).parent.parent / "skills"


def install_hooks() -> None:
    """Install Forge hooks into Claude Code settings.json + copy scripts."""
    _HOOKS_DIR.mkdir(parents=True, exist_ok=True)

    # Copy hook scripts
    for script_name in ("resume.sh", "writeback.sh", "detect.sh", "teammate.sh"):
        src = _HOOK_TEMPLATES / script_name
        dst = _HOOKS_DIR / script_name
        if src.exists():
            shutil.copy2(src, dst)
            dst.chmod(0o755)

    # Load or create settings.json
    if _SETTINGS_PATH.exists():
        try:
            settings = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            settings = {}
    else:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        settings = {}

    # --- Hooks ---
    hooks = settings.setdefault("hooks", {})

    # SessionStart → resume.sh
    session_start = hooks.setdefault("SessionStart", [])
    resume_cmd = str(_HOOKS_DIR / "resume.sh")
    if not _entry_exists(session_start, resume_cmd):
        session_start.append({
            "matcher": "",
            "hooks": [{"type": "command", "command": resume_cmd}],
        })

    # SessionEnd → writeback.sh
    session_end = hooks.setdefault("SessionEnd", [])
    writeback_cmd = str(_HOOKS_DIR / "writeback.sh")
    if not _entry_exists(session_end, writeback_cmd):
        session_end.append({
            "matcher": "",
            "hooks": [{"type": "command", "command": writeback_cmd}],
        })

    # PostToolUse → detect.sh (Bash only)
    post_tool = hooks.setdefault("PostToolUse", [])
    detect_cmd = str(_HOOKS_DIR / "detect.sh")
    if not _entry_exists(post_tool, detect_cmd):
        post_tool.append({
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": detect_cmd}],
        })

    # --- Env vars for Agent Teams ---
    env = settings.setdefault("env", {})
    teammate_path = str(_HOOKS_DIR / "teammate.sh")
    env.setdefault("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
    # Update teammate command to Forge-managed version
    current_teammate = env.get("CLAUDE_CODE_TEAMMATE_COMMAND", "")
    if not current_teammate or "forge" not in current_teammate:
        env["CLAUDE_CODE_TEAMMATE_COMMAND"] = teammate_path

    # Write settings
    try:
        _SETTINGS_PATH.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as e:
        print(f"[forge] Warning: Failed to write settings.json: {e}")
        raise


def install_skills() -> int:
    """Install bundled SKILL.md files to ~/.claude/skills/."""
    if not _SKILL_SOURCES.is_dir():
        return 0
    installed = 0
    for skill_dir in _SKILL_SOURCES.iterdir():
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        dst_dir = _SKILLS_DIR / skill_dir.name
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_file, dst_dir / "SKILL.md")
        installed += 1
    return installed


def _entry_exists(hook_list: list, command: str) -> bool:
    for e in hook_list:
        if not isinstance(e, dict):
            continue
        for hook in e.get("hooks", []):
            if isinstance(hook, dict) and hook.get("command") == command:
                return True
    return False
