"""Regression tests for the NSCLC histology merge-suffix collision.

Measured defect (2026-09-13, release-pin 2026-Q3): the NSCLC marker-paper frame
ALREADY carries a complete `histology` column (1026 patients, 100% labelled: 522
adenocarcinoma / 504 squamous). The TCGA-CDR merge added to *fix* all-null histology
— which carries the SAME 1026 patients with the SAME labels, adding nothing — used a
bare `df.merge(cdr, on="patient_id")`, so pandas
suffixed BOTH sides to `histology_x` / `histology_y` and left NO column under the
bare name. `_extract_field_value()` reads rule fields by bare name, so
`clinical.histology == 'adenocarcinoma'` matched nothing and all 1026 rows emitted
is_member=null -- while the run exited 0 and logged it as "null (data-missing)",
indistinguishable from a genuine data gap.

These tests are deliberately DATA-FREE. A test gated on `~/.cache/framework-*`
degrades to a silent skip in CI, which reports success while measuring nothing; the
guard has to be exercised on synthetic frames so it runs everywhere.
"""

from __future__ import annotations

import pandas as pd
import pytest

from onc_methods.subgroup_assigner_directly_tagged.cli import (
    _assert_no_merge_collision,
    _merge_coalescing,
)


def test_bare_merge_produces_the_collision_the_guard_catches():
    """Falsification: reproduce the ORIGINAL bug and confirm the guard fires.

    If this test ever passes without raising, the guard has stopped guarding.
    """
    left = pd.DataFrame({"patient_id": ["p1", "p2"], "histology": ["adenocarcinoma", None]})
    right = pd.DataFrame({"patient_id": ["p1", "p3"], "histology": ["adenocarcinoma", "squamous_cell_carcinoma"]})

    # the old code path, verbatim
    bad = left.merge(right, on="patient_id", how="outer")
    assert "histology" not in bad.columns, "precondition: pandas must suffix the overlap"
    assert {"histology_x", "histology_y"} <= set(bad.columns)

    with pytest.raises(RuntimeError, match="merge-suffix collision"):
        _assert_no_merge_collision(bad, "NSCLC")


def test_coalescing_merge_keeps_the_bare_name_and_fills_gaps():
    """The fix: bare name survives, left wins, right fills the left's nulls."""
    left = pd.DataFrame(
        {
            "patient_id": ["p1", "p2", "p3"],
            "histology": ["adenocarcinoma", None, None],  # a sparser-than-live marker-paper frame
        }
    )
    right = pd.DataFrame(
        {
            "patient_id": ["p1", "p2", "p4"],
            "histology": ["adenocarcinoma", "squamous_cell_carcinoma", "adenocarcinoma"],
        }
    )

    out = _merge_coalescing(left, right, on="patient_id", coalesce=("histology",), tag="cdr")

    assert "histology" in out.columns
    assert not [c for c in out.columns if c.endswith(("_x", "_y"))]
    assert "histology_cdr" not in out.columns
    _assert_no_merge_collision(out, "NSCLC")  # must not raise

    got = dict(zip(out["patient_id"], out["histology"]))
    assert got["p1"] == "adenocarcinoma"  # both agree
    assert got["p2"] == "squamous_cell_carcinoma"  # left null -> filled from right
    assert got["p4"] == "adenocarcinoma"  # right-only row (outer merge)
    assert pd.isna(got["p3"])  # neither source -> stays tri-value null


def test_left_value_wins_when_the_two_sources_disagree():
    """Precedence is explicit: the curated marker-paper label is authoritative.

    (Measured on the real 2026-09-13 data the two sources agree on all 1026
    overlapping rows, so this pins the intended precedence rather than a live
    disagreement.)
    """
    left = pd.DataFrame({"patient_id": ["p1"], "histology": ["adenocarcinoma"]})
    right = pd.DataFrame({"patient_id": ["p1"], "histology": ["squamous_cell_carcinoma"]})

    out = _merge_coalescing(left, right, on="patient_id", coalesce=("histology",), tag="cdr")
    assert out["histology"].tolist() == ["adenocarcinoma"]


def test_coalesce_handles_a_left_frame_with_no_such_column():
    """When the left frame has no `histology` at all, the right's becomes it."""
    left = pd.DataFrame({"patient_id": ["p1", "p2"]})
    right = pd.DataFrame({"patient_id": ["p1", "p2"], "histology": ["adenocarcinoma", None]})

    out = _merge_coalescing(left, right, on="patient_id", coalesce=("histology",), tag="cdr")
    assert out["histology"].tolist()[0] == "adenocarcinoma"
    _assert_no_merge_collision(out, "NSCLC")


def test_guard_is_silent_on_a_clean_frame():
    """The guard must not false-fail on legitimate columns."""
    clean = pd.DataFrame({"patient_id": ["p1"], "histology": ["adenocarcinoma"], "T.stage": ["T1"]})
    _assert_no_merge_collision(clean, "NSCLC")  # no raise


def test_depmap_lineage_map_is_the_canonical_object_not_a_fork():
    """The subgroup lane must share the ONE canonical lineage map, not fork it.

    This lane used to hold two forks: an 8-entry scalar dict in the assigner (exempted
    from the single-source guard for its INDICATION_TO_DEPMAP_ORGAN sibling) and a
    ONE-entry copy in scripts/prefetch_source_maf.py ({"COADREAD": "Bowel"}) that made
    every non-COADREAD DepMap prefetch exit 1 (six indications). Both now alias-import
    depmap_chronos.cli.INDICATION_LINEAGE, so they inherit its 42-code coverage and its
    validation guards (see tests/methods/depmap_chronos/test_lineage_map_single_source.py).
    """
    from onc_methods.depmap_chronos.read import INDICATION_TO_DEPMAP_LINEAGE as canonical
    from onc_methods.subgroup_assigner_directly_tagged import cli
    from onc_methods.subgroup_common import lineage

    assert cli.INDICATION_TO_DEPMAP_LINEAGE is canonical
    assert lineage.INDICATION_TO_DEPMAP_LINEAGE is canonical
    assert cli.INDICATION_TO_DEPMAP_ORGAN is lineage.INDICATION_TO_DEPMAP_ORGAN

    # verbatim DepMap spelling, NOT the crosswalk's underscored variant
    assert lineage.depmap_lineage_for("HNSC") == "Head and Neck"
    assert "_" not in lineage.depmap_lineage_for("HNSC")

    # the SIX indications whose depmap MAF prefetch the one-entry map blocked (all six
    # now emit a non-empty parquet; see tests/scripts/test_prefetch_source_maf.py)
    for ind in ("AML", "BRCA", "ESCA", "HNSC", "NSCLC", "PAAD"):
        assert lineage.depmap_lineage_for(ind)

    assert lineage.depmap_lineage_for("nsclc") == "Lung"  # case-insensitive

    # an unmapped indication raises rather than defaulting to a pan-cancer cohort
    with pytest.raises(KeyError, match="No DepMap lineage mapping"):
        lineage.depmap_lineage_for("THYM")
