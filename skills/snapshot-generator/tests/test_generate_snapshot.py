"""Tests for snapshot-generator."""

from pathlib import Path

import pytest

from skills.snapshot_generator.scripts.generate_snapshot import (
    load_topics_config,
    parse_run_dir,
    substitute_placeholders,
)


SKILL_DIR = Path(__file__).parent.parent


class TestParseRunDir:
    def test_standard_format(self, tmp_path):
        run_dir = tmp_path / "KRAS-COADREAD" / "2026-09-10__2.0.0__abc123"
        run_dir.mkdir(parents=True)
        gene, indication = parse_run_dir(run_dir)
        assert gene == "KRAS"
        assert indication == "COADREAD"

    def test_case_insensitive(self, tmp_path):
        run_dir = tmp_path / "kras-coadread" / "2026-09-10__2.0.0__abc123"
        run_dir.mkdir(parents=True)
        gene, indication = parse_run_dir(run_dir)
        assert gene == "KRAS"
        assert indication == "COADREAD"

    def test_invalid_format(self, tmp_path):
        run_dir = tmp_path / "invalid" / "path"
        run_dir.mkdir(parents=True)
        with pytest.raises(ValueError, match="Could not parse"):
            parse_run_dir(run_dir)


class TestSubstitutePlaceholders:
    def test_gene_substitution(self):
        result = substitute_placeholders("{gene} Dependency", "KRAS", "COADREAD")
        assert result == "KRAS Dependency"

    def test_indication_substitution(self):
        result = substitute_placeholders("Profile in {indication}", "KRAS", "COADREAD")
        assert result == "Profile in COADREAD"

    def test_both_placeholders(self):
        result = substitute_placeholders("{gene} in {indication}", "EGFR", "NSCLC")
        assert result == "EGFR in NSCLC"

    def test_no_placeholders(self):
        result = substitute_placeholders("Static text", "KRAS", "COADREAD")
        assert result == "Static text"


class TestLoadTopicsConfig:
    def test_load_default_config(self):
        config_path = SKILL_DIR / "topics.yaml"
        if config_path.exists():
            topics = load_topics_config(config_path)
            assert "dependency" in topics
            assert topics["dependency"].display_name == "Functional Dependency"

    def test_topic_structure(self):
        config_path = SKILL_DIR / "topics.yaml"
        if config_path.exists():
            topics = load_topics_config(config_path)
            dep = topics.get("dependency")
            if dep:
                assert dep.hero
                assert len(dep.slides) > 0
                assert dep.slides[0].title
                assert len(dep.slides[0].figures) > 0
