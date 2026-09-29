"""Axis-2 (dependency): dependency_controls.yaml structural + inverted-semantics lock.

The dependency analog of test_tumor_presence_controls.py. Validates the curated
control vocabulary's structure (roles, applicability, per-entry provenance + empirical
Chronos figures) and locks the INVERSION that distinguishes it from the presence
controls: positive controls are pan-essential genes (an essentiality CEILING — reading
AT this depth is a tox liability, not a win), negative controls are non-essential genes
(a dependency FLOOR). The empirical-median ordering (pan-essentials clearly more
depleted than non-essentials) is pinned so a mis-curated entry (e.g. a positive listed
with a ~0 Chronos) can't slip in. Live Chronos reads are exercised in the method's
tests; this pins the pure vocab + its ordering invariant (no S3).
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
VOCAB = REPO / "vocabularies" / "dependency_controls.yaml"

_VALID_POS_ROLES = {"pan_essential"}
_VALID_NEG_ROLES = {"non_essential"}


@pytest.fixture(scope="module")
def vocab():
    return yaml.safe_load(VOCAB.read_text())


# ---- structural integrity ----
def test_vocab_has_version_and_chronos_source(vocab):
    assert vocab.get("version")
    src = vocab.get("chronos_source") or {}
    assert src.get("release_pin") == "26q1"
    assert src.get("metric") == "pan_panel_median_chronos"


def test_positive_controls_are_pan_essential(vocab):
    pos = vocab.get("positive_controls") or {}
    assert pos, "must declare positive (pan-essential) controls"
    for sym, spec in pos.items():
        assert spec.get("role") in _VALID_POS_ROLES, f"{sym} bad role"
        assert spec.get("rationale"), f"{sym} missing rationale (curation discipline)"
        assert spec.get("citation"), f"{sym} missing citation"
        # every positive must carry its empirical anchor + read as ESSENTIAL (< -1, the
        # common-essential calibration line) — the inversion's whole point.
        med = spec.get("empirical_median_chronos_26q1")
        assert med is not None, f"{sym} missing empirical_median_chronos_26q1"
        assert med < -1.0, f"{sym} pan-essential control must read < -1.0 Chronos (got {med})"
    # canonical ribosomal/replication anchors must be present
    assert {"RPS11", "PCNA"}.issubset(pos)


def test_negative_controls_are_non_essential(vocab):
    neg = vocab.get("negative_controls") or {}
    assert neg, "must declare negative (non-essential) controls"
    for sym, spec in neg.items():
        assert spec.get("role") in _VALID_NEG_ROLES, f"{sym} bad role {spec.get('role')}"
        assert spec.get("rationale"), f"{sym} missing rationale"
        assert spec.get("applies") == "universal", f"{sym} must be applies:universal"
        med = spec.get("empirical_median_chronos_26q1")
        assert med is not None, f"{sym} missing empirical_median_chronos_26q1"
        # non-essential floor: Chronos near 0 (not a dependency).
        assert med > -0.5, f"{sym} non-essential control must read > -0.5 Chronos (got {med})"


def test_pan_essential_band_spans_a_depth_range(vocab):
    """The positive band must span a RANGE (deep core-essentials AND a shallower
    essential near the -1 line), not collapse to one point — so 'between_controls'
    has a meaningful ceiling edge."""
    meds = [s["empirical_median_chronos_26q1"] for s in vocab["positive_controls"].values()]
    assert min(meds) <= -2.5, "need a deep core-essential anchor (<= -2.5)"
    assert max(meds) >= -1.6, "need a shallower essential anchor near the -1 ceiling edge"


def test_inversion_ordering_positives_below_negatives(vocab):
    """The load-bearing invariant: every pan-essential positive is more depleted
    (more negative Chronos) than every non-essential negative. If this ordering ever
    breaks, the control axis is mis-curated and the classifier bands are meaningless."""
    pos = [s["empirical_median_chronos_26q1"] for s in vocab["positive_controls"].values()]
    neg = [s["empirical_median_chronos_26q1"] for s in vocab["negative_controls"].values()]
    assert max(pos) < min(neg), (
        f"pan-essential ceiling (max {max(pos)}) must sit BELOW the non-essential floor "
        f"(min {min(neg)}) on the Chronos scale — the inversion invariant"
    )


def test_no_shared_genes_between_bands(vocab):
    pos = set(vocab.get("positive_controls") or {})
    neg = set(vocab.get("negative_controls") or {})
    assert not (pos & neg), f"a gene cannot be both a positive and negative control: {pos & neg}"
