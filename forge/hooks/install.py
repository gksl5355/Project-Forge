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

# Forge's recommended env values
_RECOMMENDED_ENV = {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
}


def install_hooks(dry_run: bool = False) -> list[str]:
    """Install Forge hooks into Claude Code settings.json + copy scripts.

    Merge strategy:
    - Hooks: append-only (existing hooks preserved, Forge hooks added)
    - Env vars: set if missing, WARN if existing value differs
    - TEAMMATE_COMMAND: always points to Forge-managed version
    - Backup: settings.json.bak created before any changes

    Returns list of changes/warnings.
    """
    changes: list[str] = []

    # --- Hook scripts ---
    if not dry_run:
        _HOOKS_DIR.mkdir(parents=True, exist_ok=True)

    for script_name in ("resume.sh", "writeback.sh", "detect.sh", "teammate.sh"):
        src = _HOOK_TEMPLATES / script_name
        dst = _HOOKS_DIR / script_name
        if src.exists():
            if not dry_run:
                shutil.copy2(src, dst)
                dst.chmod(0o755)
            changes.append(f"  + {dst}")

    # --- settings.json ---
    if _SETTINGS_PATH.exists():
        try:
            original_text = _SETTINGS_PATH.read_text(encoding="utf-8")
            settings = json.loads(original_text)
        except (json.JSONDecodeError, OSError):
            settings = {}
            original_text = "{}"
    else:
        settings = {}
        original_text = ""
        if not dry_run:
            _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Hooks: append-only (never remove existing)
    hooks = settings.setdefault("hooks", {})
    hook_configs = [
        ("SessionStart", str(_HOOKS_DIR / "resume.sh"), ""),
        ("SessionEnd", str(_HOOKS_DIR / "writeback.sh"), ""),
        ("PostToolUse", str(_HOOKS_DIR / "detect.sh"), "Bash"),
    ]
    for event, cmd, matcher in hook_configs:
        event_list = hooks.setdefault(event, [])
        if not _entry_exists(event_list, cmd):
            event_list.append({
                "matcher": matcher,
                "hooks": [{"type": "command", "command": cmd}],
            })
            changes.append(f"  + hooks.{event}: {Path(cmd).name}")
        else:
            changes.append(f"  = hooks.{event}: {Path(cmd).name} (already set)")

    # Env: set + warn on conflict
    env = settings.setdefault("env", {})
    teammate_path = str(_HOOKS_DIR / "teammate.sh")

    for key, recommended in _RECOMMENDED_ENV.items():
        current = env.get(key)
        if current is None:
            env[key] = recommended
            changes.append(f"  + env.{key} = {recommended}")
        elif current != recommended:
            changes.append(
                f"  ! env.{key} = {current} (Forge recommends: {recommended})"
            )
        else:
            changes.append(f"  = env.{key} = {current} (ok)")

    # TEAMMATE_COMMAND: always set to Forge path
    current_teammate = env.get("CLAUDE_CODE_TEAMMATE_COMMAND", "")
    env["CLAUDE_CODE_TEAMMATE_COMMAND"] = teammate_path
    if current_teammate and current_teammate != teammate_path:
        changes.append(f"  ~ env.TEAMMATE_COMMAND: {current_teammate} -> {teammate_path}")
    elif not current_teammate:
        changes.append(f"  + env.TEAMMATE_COMMAND = {teammate_path}")
    else:
        changes.append(f"  = env.TEAMMATE_COMMAND (ok)")

    # Write with backup
    new_text = json.dumps(settings, indent=2, ensure_ascii=False)
    if new_text != original_text and not dry_run:
        if original_text:
            backup = _SETTINGS_PATH.with_suffix(".json.bak")
            backup.write_text(original_text, encoding="utf-8")
            changes.append(f"  ~ backup: {backup}")
        _SETTINGS_PATH.write_text(new_text, encoding="utf-8")

    return changes


def install_skills(dry_run: bool = False) -> list[str]:
    """Install bundled SKILL.md files to ~/.claude/skills/.

    Always overwrites with Forge's bundled version (skills are Forge-managed).
    Returns list of installed skill paths.
    """
    installed: list[str] = []
    if not _SKILL_SOURCES.is_dir():
        return installed

    for skill_dir in sorted(_SKILL_SOURCES.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        dst_dir = _SKILLS_DIR / skill_dir.name
        dst = dst_dir / "SKILL.md"
        if not dry_run:
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill_file, dst)
        installed.append(f"  + ~/.claude/skills/{skill_dir.name}/")

    return installed


def _entry_exists(hook_list: list, command: str) -> bool:
    for e in hook_list:
        if not isinstance(e, dict):
            continue
        for hook in e.get("hooks", []):
            if isinstance(hook, dict) and hook.get("command") == command:
                return True
    return False
