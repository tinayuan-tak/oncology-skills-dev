"""Regression (burndown P3, PR #361): _load_brca_pam50_from_curated reads a curated LOCAL CSV whose
existence is checked first. A parse failure of an EXISTING file is corruption and must PROPAGATE
(rather than silently collapse every BRCA patient to a null PAM50 stratum); a genuinely-missing file
still returns None (strata self-degrade to null), unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.subgroup_assigner_directly_tagged import cli as sub  # noqa: E402


def _curated_path(root: Path) -> Path:
    return root / "framework-tcga-marker-paper" / "pancan_atlas_subtypes_curated.csv"


def test_missing_file_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(sub, "cache_root", lambda: tmp_path)  # file does not exist
    assert sub._load_brca_pam50_from_curated() is None


def test_corrupt_existing_file_reraises(monkeypatch, tmp_path):
    p = _curated_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("garbage,not,a,valid\ncurated,csv\n")
    monkeypatch.setattr(sub, "cache_root", lambda: tmp_path)

    def _boom(*a, **k):
        raise RuntimeError("corrupt curated CSV")

    monkeypatch.setattr(sub.pd, "read_csv", _boom)
    with pytest.raises(RuntimeError):
        sub._load_brca_pam50_from_curated()
