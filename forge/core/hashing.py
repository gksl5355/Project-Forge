"""Config and document hashing for experiment tracking."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from forge.config import ForgeConfig


def compute_config_hash(config: ForgeConfig) -> str:
    """ForgeConfig -> JSON -> SHA256[:12]."""
    data = asdict(config)
    canonical = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def compute_doc_hashes(workspace_path: Path | None = None) -> dict[str, str]:
    """Compute per-file hashes for tracked documents.

    Targets: CLAUDE.md (project), CLAUDE.md (global), SKILL.md files, config.yml
    """
    targets: dict[str, Path] = {}

    # Global CLAUDE.md
    global_claude = Path.home() / ".claude" / "CLAUDE.md"
    if global_claude.exists():
        targets["claude_md_global"] = global_claude

    # Global config.yml
    config_yml = Path.home() / ".forge" / "config.yml"
    if config_yml.exists():
        targets["config_yml"] = config_yml

    # Project-level files
    if workspace_path and workspace_path.is_dir():
        project_claude = workspace_path / "CLAUDE.md"
        if project_claude.exists():
            targets["claude_md_project"] = project_claude

        # Look for SKILL.md files
        for skill_file in workspace_path.glob("**/SKILL.md"):
            rel = skill_file.relative_to(workspace_path)
            targets[f"skill_md_{rel.parent}"] = skill_file

    hashes: dict[str, str] = {}
    for key, path in targets.items():
        try:
            content = path.read_bytes()
            hashes[key] = hashlib.sha256(content).hexdigest()[:12]
        except OSError:
            continue

    return hashes


def compute_combined_doc_hash(doc_hashes: dict[str, str]) -> str:
    """Combine individual document hashes into a single hash."""
    if not doc_hashes:
        return "000000000000"
    combined = "|".join(f"{k}={v}" for k, v in sorted(doc_hashes.items()))
    return hashlib.sha256(combined.encode()).hexdigest()[:12]
