"""Tests for forge/core/hashing.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.core.hashing import compute_combined_doc_hash, compute_config_hash, compute_doc_hashes
from forge.config import ForgeConfig


class TestComputeConfigHash:
    def test_deterministic(self):
        config = ForgeConfig()
        h1 = compute_config_hash(config)
        h2 = compute_config_hash(config)
        assert h1 == h2

    def test_length_12(self):
        h = compute_config_hash(ForgeConfig())
        assert len(h) == 12

    def test_different_config_different_hash(self):
        h1 = compute_config_hash(ForgeConfig(alpha=0.1))
        h2 = compute_config_hash(ForgeConfig(alpha=0.2))
        assert h1 != h2

    def test_hex_characters(self):
        h = compute_config_hash(ForgeConfig())
        assert all(c in "0123456789abcdef" for c in h)


class TestComputeDocHashes:
    def test_empty_workspace(self, tmp_path):
        hashes = compute_doc_hashes(tmp_path)
        # No project CLAUDE.md or SKILL.md → empty or only global files
        assert isinstance(hashes, dict)

    def test_with_claude_md(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Project Rules")
        hashes = compute_doc_hashes(tmp_path)
        assert "claude_md_project" in hashes
        assert len(hashes["claude_md_project"]) == 12

    def test_with_skill_md(self, tmp_path):
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Skill")
        hashes = compute_doc_hashes(tmp_path)
        skill_keys = [k for k in hashes if k.startswith("skill_md_")]
        assert len(skill_keys) >= 1

    def test_deterministic(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("same content")
        h1 = compute_doc_hashes(tmp_path)
        h2 = compute_doc_hashes(tmp_path)
        assert h1 == h2

    def test_content_change_changes_hash(self, tmp_path):
        f = tmp_path / "CLAUDE.md"
        f.write_text("version 1")
        h1 = compute_doc_hashes(tmp_path)
        f.write_text("version 2")
        h2 = compute_doc_hashes(tmp_path)
        assert h1["claude_md_project"] != h2["claude_md_project"]

    def test_none_workspace(self):
        hashes = compute_doc_hashes(None)
        assert isinstance(hashes, dict)


class TestComputeCombinedDocHash:
    def test_empty_dict(self):
        h = compute_combined_doc_hash({})
        assert h == "000000000000"

    def test_deterministic(self):
        hashes = {"a": "abc123", "b": "def456"}
        h1 = compute_combined_doc_hash(hashes)
        h2 = compute_combined_doc_hash(hashes)
        assert h1 == h2

    def test_order_independent(self):
        h1 = compute_combined_doc_hash({"a": "123", "b": "456"})
        h2 = compute_combined_doc_hash({"b": "456", "a": "123"})
        assert h1 == h2  # sorted keys

    def test_length_12(self):
        h = compute_combined_doc_hash({"x": "hash1"})
        assert len(h) == 12
