"""Tests for directive extraction, classification, and ablation."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from forge.core.directive import Directive
from forge.extras.directive_extractor import (
    build_dependency_graph,
    classify_directive,
    extract_directives,
)
from forge.extras.ablation import (
    AblationCandidate,
    apply_ablation,
    generate_ablation_candidates,
)


class TestClassifyDirective:
    def test_rule_detection(self):
        assert classify_directive("Type hints required on all functions") == "rule"
        assert classify_directive("Never use raw SQL") == "rule"
        assert classify_directive("Always run tests before commit") == "rule"

    def test_threshold_detection(self):
        assert classify_directive("N_parallel >= 3 AND N_files >= 5") == "threshold"
        assert classify_directive("Hard cap: 5 agents") == "threshold"
        assert classify_directive("max_tokens = 3000") == "threshold"

    def test_workflow_detection(self):
        assert classify_directive("Step 1: Parse input → Step 2: Validate") == "workflow"
        assert classify_directive("Then flow through the pipeline: ingest to measure to report") == "workflow"

    def test_description_detection(self):
        assert classify_directive("This module handles database operations") == "description"
        assert classify_directive("Q-value tracks experience utility") == "description"

    def test_constraint_detection(self):
        assert classify_directive("| SIMPLE | haiku:2 | 0.9 |") == "constraint"


class TestExtractDirectives:
    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.md"
        f.write_text("")
        result = extract_directives(f)
        assert result == []

    def test_nonexistent_file(self, tmp_path):
        result = extract_directives(tmp_path / "nope.md")
        assert result == []

    def test_bullet_list_extraction(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text(textwrap.dedent("""\
            ## Rules
            - Type hints required on all functions
            - Never use raw SQL directly
        """))
        directives = extract_directives(f)
        rules = [d for d in directives if d.directive_type == "rule"]
        assert len(rules) >= 2
        assert any("Type hints" in d.content for d in rules)

    def test_code_block_extraction(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text(textwrap.dedent("""\
            ## Config
            ```python
            max_tokens = 3000
            ```
        """))
        directives = extract_directives(f)
        code_dirs = [d for d in directives if "max_tokens" in d.content]
        assert len(code_dirs) >= 1

    def test_section_tracking(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text(textwrap.dedent("""\
            ## Section A
            - Must validate inputs in A
            ## Section B
            - Never skip tests in B
        """))
        directives = extract_directives(f)
        sections = {d.section for d in directives if d.directive_type == "rule"}
        assert len(sections) == 2

    def test_directive_id_stability(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("## Rules\n- Always test your code\n")
        d1 = extract_directives(f)
        d2 = extract_directives(f)
        assert d1[0].directive_id == d2[0].directive_id  # same content → same ID

    def test_token_estimation(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("## Rules\n- A short rule\n")
        directives = extract_directives(f)
        assert all(d.tokens > 0 for d in directives)

    def test_table_extraction(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text(textwrap.dedent("""\
            ## Configs
            | Name | Value |
            |------|-------|
            | alpha | 0.1 |
            | beta  | 0.2 |
        """))
        directives = extract_directives(f)
        constraints = [d for d in directives if d.directive_type == "constraint"]
        assert len(constraints) >= 2


class TestDependencyGraph:
    def test_empty_directives(self):
        graph = build_dependency_graph([])
        assert graph == {}

    def test_no_dependencies(self):
        directives = [
            Directive("f.md", "## A", "f.md:A:abc", "some rule", "rule"),
            Directive("f.md", "## B", "f.md:B:def", "other rule", "rule"),
        ]
        graph = build_dependency_graph(directives)
        assert all(len(deps) == 0 for deps in graph.values())

    def test_cross_section_reference(self):
        directives = [
            Directive("f.md", "## Coding Rules", "f.md:CR:abc", "See Coding Rules for details", "rule"),
            Directive("f.md", "## Coding Rules", "f.md:CR:def", "Type hints required", "rule"),
            Directive("f.md", "## Overview", "f.md:OV:ghi", "Follow Coding Rules section", "description"),
        ]
        graph = build_dependency_graph(directives)
        # Overview directive should reference Coding Rules directives
        overview_deps = graph["f.md:OV:ghi"]
        assert len(overview_deps) > 0


class TestAblationCandidates:
    def test_systematic_generates_remove(self):
        directives = [
            Directive("f.md", "## R", "f.md:R:abc", "A rule", "rule", tokens=5),
        ]
        candidates = generate_ablation_candidates(directives, strategy="systematic")
        removes = [c for c in candidates if c.action == "remove"]
        assert len(removes) == 1
        assert removes[0].estimated_token_delta == -5

    def test_systematic_generates_simplify_for_long(self):
        long_content = "This is a very long rule with (parenthetical explanation) that should be simplified"
        directives = [
            Directive("f.md", "## R", "f.md:R:abc", long_content, "rule", tokens=25),
        ]
        candidates = generate_ablation_candidates(directives, strategy="systematic")
        simplifies = [c for c in candidates if c.action == "simplify"]
        assert len(simplifies) >= 1

    def test_targeted_only_low_impact_types(self):
        directives = [
            Directive("f.md", "## R", "f.md:R:abc", "A rule", "rule", tokens=5),
            Directive("f.md", "## D", "f.md:D:def", "A description", "description", tokens=5),
        ]
        candidates = generate_ablation_candidates(directives, strategy="targeted")
        # Only description should be targeted
        assert all(
            any(d.directive_type in ("description", "constraint") for d in directives if d.directive_id == c.directive_id)
            for c in candidates
        )


class TestApplyAblation:
    def test_remove_directive(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("## Rules\n- Rule one\n- Rule two\n")
        directives = extract_directives(f)
        assert len(directives) >= 2

        # Remove first rule
        target = directives[0]
        candidates = [AblationCandidate(
            directive_id=target.directive_id,
            action="remove",
            variant_content="",
            estimated_token_delta=-target.tokens,
        )]
        result = apply_ablation(f, candidates, directives)
        assert target.content not in result
        # Other rule should remain
        assert directives[1].content in result

    def test_simplify_directive(self, tmp_path):
        f = tmp_path / "test.md"
        original = "- Must validate (including edge cases) all inputs"
        f.write_text(f"## Rules\n{original}\n")
        directives = extract_directives(f)
        assert len(directives) >= 1

        target = directives[0]
        candidates = [AblationCandidate(
            directive_id=target.directive_id,
            action="simplify",
            variant_content="- Must validate all inputs",
            estimated_token_delta=-3,
        )]
        result = apply_ablation(f, candidates, directives)
        assert "Must validate all inputs" in result

    def test_nonexistent_file(self, tmp_path):
        result = apply_ablation(tmp_path / "nope.md", [], [])
        assert result == ""
