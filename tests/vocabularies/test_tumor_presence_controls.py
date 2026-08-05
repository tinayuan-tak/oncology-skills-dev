"""Phase 2: tumor_presence_controls.yaml structural + indication-swap lock (no S3).

Validates the curated controls vocabulary's structure (roles, applicability scopes,
per-entry provenance) and locks the load-bearing indication-matching rule: a
lineage_marker negative must be EXCLUDED in its own lineage and APPLICABLE elsewhere.
The percentile reads are exercised live elsewhere; this pins the vocab + the pure
applicability logic that governs which negatives are valid per indication.
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
VOCAB = REPO / "vocabularies" / "tumor_presence_controls.yaml"
CROSSWALK = REPO / "vocabularies" / "indication_crosswalk.yaml"

_VALID_POS_ROLES = {"tumor_antigen"}
_VALID_NEG_ROLES = {"housekeeping", "lineage_marker", "silent"}


@pytest.fixture(scope="module")
def vocab():
    return yaml.safe_load(VOCAB.read_text())


@pytest.fixture(scope="module")
def crosswalk_tissues():
    data = yaml.safe_load(CROSSWALK.read_text())
    return {str(i["canonical_code"]).upper(): i.get("gtex_normal_tissue")
            for i in data.get("indications", [])}


# ---- structural integrity ----
def test_vocab_has_version_and_percentile_source(vocab):
    assert vocab.get("version")
    src = vocab.get("percentile_source") or {}
    assert src.get("tumor") == "allgene-tumor-rank-v1"
    assert src.get("cell_line") == "allgene-depmap-rank-26q1-v1"


def test_positive_controls_wellformed(vocab):
    pos = vocab.get("positive_controls") or {}
    assert pos, "must declare positive controls"
    for sym, spec in pos.items():
        assert spec.get("role") in _VALID_POS_ROLES, f"{sym} bad role"
        assert spec.get("rationale"), f"{sym} missing rationale (curation discipline)"
        assert spec.get("citation"), f"{sym} missing citation"
    # the canonical antigen anchors must be present
    assert {"CEACAM5", "EPCAM"}.issubset(pos)


def test_negative_controls_wellformed(vocab):
    neg = vocab.get("negative_controls") or {}
    assert neg, "must declare negative controls"
    for sym, spec in neg.items():
        role = spec.get("role")
        assert role in _VALID_NEG_ROLES, f"{sym} bad role {role}"
        assert spec.get("rationale"), f"{sym} missing rationale"
        # a lineage_marker MUST declare which lineage it is the marker for; universal ones must NOT.
        if role == "lineage_marker":
            assert spec.get("negative_except_lineage"), f"{sym} lineage_marker needs negative_except_lineage"
        else:
            assert spec.get("applies") == "universal", f"{sym} non-lineage negative must be applies:universal"


def test_has_housekeeping_ceiling_and_silent_floor(vocab):
    roles = {spec.get("role") for spec in (vocab.get("negative_controls") or {}).values()}
    assert "housekeeping" in roles   # a ceiling anchor
    assert "silent" in roles          # a floor anchor
    assert "lineage_marker" in roles  # the indication-matching case


# ---- indication-matching lock (the load-bearing rule) ----
def test_lineage_marker_lineages_resolve_in_crosswalk(vocab, crosswalk_tissues):
    """Every lineage_marker's negative_except_lineage must be a REAL gtex_normal_tissue in
    the crosswalk — otherwise the exclusion can never fire (a silent mis-config)."""
    valid_tissues = {t for t in crosswalk_tissues.values() if t}
    for sym, spec in (vocab.get("negative_controls") or {}).items():
        if spec.get("role") == "lineage_marker":
            lin = spec.get("negative_except_lineage")
            assert lin in valid_tissues, (
                f"{sym} negative_except_lineage={lin!r} is not a gtex_normal_tissue in "
                f"indication_crosswalk.yaml ({sorted(valid_tissues)}) — exclusion can never fire")


def test_sftpc_is_lung_lineage_marker(vocab):
    """The plan's canonical indication-swap case: SFTPC negative-in-colon, excluded-in-lung."""
    sftpc = (vocab.get("negative_controls") or {}).get("SFTPC")
    assert sftpc is not None and sftpc.get("role") == "lineage_marker"
    assert sftpc.get("negative_except_lineage") == "Lung"
