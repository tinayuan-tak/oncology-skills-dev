"""Tests for the git-tracked profiles catalog (publish_profile → data-products) + registry link.
CI-safe: no target-profile run, no S3/gh."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

import publish_profile as PP  # noqa: E402
import build_output_registry as R  # noqa: E402


def test_upsert_and_load_roundtrip(tmp_path):
    e1 = {
        "target": "KRAS",
        "indication": "COADREAD",
        "cell": "KRAS-COADREAD",
        "date": "2026-08-20",
        "verdict": "nominate",
        "positive_tier": "high",
        "release_url": "https://gh/releases/tag/profile-kras-coadread-2026-08-20",
        "s3_prefix": "s3://onc-compbio/framework-profiles/KRAS-COADREAD",
    }
    n = PP.upsert_profiles_catalog(tmp_path, e1)
    assert n == 1
    assert (tmp_path / "profiles.index.json").exists()
    assert (tmp_path / "profiles.INDEX.md").exists()
    # registry reads it, keyed by cell
    loaded = R._load_profiles(str(tmp_path))
    assert loaded["KRAS-COADREAD"]["release_url"].endswith("2026-08-20")


def test_upsert_is_keyed_by_cell(tmp_path):
    base = {"target": "KRAS", "indication": "COADREAD", "cell": "KRAS-COADREAD", "date": "2026-08-20"}
    PP.upsert_profiles_catalog(tmp_path, {**base, "verdict": "v1"})
    PP.upsert_profiles_catalog(tmp_path, {**base, "verdict": "v2"})  # same cell → replace
    PP.upsert_profiles_catalog(
        tmp_path, {"target": "MET", "indication": "COADREAD", "cell": "MET-COADREAD", "date": "2026-08-20"}
    )
    rows = json.loads((tmp_path / "profiles.index.json").read_text())["profiles"]
    assert len(rows) == 2  # KRAS deduped, MET added
    kras = next(r for r in rows if r["cell"] == "KRAS-COADREAD")
    assert kras["verdict"] == "v2"  # latest wins


def test_load_profiles_absent(tmp_path):
    assert R._load_profiles(str(tmp_path)) == {}  # no catalog → empty
