"""Hook 설치: ~/.claude/settings.json 패치."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
_HOOKS_DIR = Path.home() / ".forge" / "hooks"

_HOOK_TEMPLATES = Path(__file__).parent / "templates"


def install_hooks() -> None:
    """Claude Code settings.json에 hook 설정 추가 + 스크립트 복사."""
    _HOOKS_DIR.mkdir(parents=True, exist_ok=True)

    # 스크립트 복사
    for script_name in ("resume.sh", "writeback.sh", "detect.sh"):
        src = _HOOK_TEMPLATES / script_name
        dst = _HOOKS_DIR / script_name
        if src.exists():
            shutil.copy2(src, dst)
            dst.chmod(0o755)

    # settings.json 로드 또는 새로 생성
    if _SETTINGS_PATH.exists():
        try:
            settings = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            settings = {}
    else:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        settings = {}

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

    # PostToolUse → detect.sh (Bash 툴에만 매칭)
    post_tool = hooks.setdefault("PostToolUse", [])
    detect_cmd = str(_HOOKS_DIR / "detect.sh")
    if not _entry_exists(post_tool, detect_cmd):
        post_tool.append({
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": detect_cmd}],
        })

    try:
        _SETTINGS_PATH.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as e:
        print(f"[forge] Warning: Failed to write settings.json: {e}")
        raise


def _entry_exists(hook_list: list, command: str) -> bool:
    for e in hook_list:
        if not isinstance(e, dict):
            continue
        for hook in e.get("hooks", []):
            if isinstance(hook, dict) and hook.get("command") == command:
                return True
    return False
