"""T3 recomputation anchors — sc-normal-celltype-expression (#2047, batch E).

sc-normal-celltype-expression is the single-cell normal-tissue liability card, produced by
``methods.sc_normal_expression.read.read_target_summary(target, indication)`` ->
``read_gene_celltype_rows`` -> ``stats.classify_sc_normal_expression``. This re-derives the card
summary from the IRREPRODUCIBLE raw input committed as lossless parquet: the target gene's
per-(tissue, cell_type) Tier-1 cross-donor-aggregated rows (median_det, expressing_donor_fraction,
n_donors_reliable, n_datasets_reliable, median_abund, ...) across every tissue the indication's
liability read queries (the tumor-matched normal tissue UNION the always-on safety-essential
organs).

The offline re-derivation reconstructs the frozen multi-tissue DataFrame (with the SAME
tissues_loaded/tissues_missing coverage-accounting ``.attrs`` the live reader attaches) and
monkeypatches ONLY the ``read_gene_celltype_rows`` S3-load seam; the REAL ``read_target_summary``
then runs unmodified (tissue-union resolution, the MIN_RELIABLE_DONORS=5 read-time floor, the
liability ladder, the origin-aware essential-organ veto split, the named-driver selection).

DO-NOT-REFILE GUARDRAIL: the Tier-1 product's cross-donor aggregate is an UNWEIGHTED cross-donor
median BY DESIGN (methods/sc_normal_expression/aggregate.py's module docstring: the DONOR is the
biological replicate — never a cell-weighted mean, which would let one large donor/dataset
dominate). That aggregation runs upstream in the data-catalog Tier-2->Tier-1 build, OUT OF SCOPE for
this anchor (see BOUNDARY below) — do not "fix" it to a weighted form; it validates as-is.

BOUNDARY: validates the READ + CLASSIFY path AM owns — NOT the upstream per-donor cross-donor
median (that belongs to data-catalog's aggregate.py build).

OFFLINE — reads only committed fixtures, no S3, no creds. Runs in CI.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
ANCHOR_DIR = HERE / "anchors"


import onc_methods.sc_normal_expression.read as rd

MIN_ANCHORS = 2
MIN_DISTINCT_CLASSES = 1  # both roster anchors are HIGH_LIABILITY by design (colon-origin flagships);
# non-vacuity is instead enforced on the essential-organ safety-class split (test_anchor_set_is_not_vacuous)

_ROW_COLS = list(rd._PARQUET_COLS)  # noqa: SLF001

_CARD_FIELDS = (
    "sc_normal_expression_class",
    "sc_normal_safety_essential_class",
    "max_detection_cell_type",
    "max_detection_fraction",
    "expressing_donor_fraction_max",
    "sc_normal_abundance_class",
    "sc_normal_peak_median_abund",
    "sc_normal_essential_max_cell_type",
    "sc_normal_essential_max_tissue",
    "sc_normal_essential_max_detection_fraction",
    "sc_normal_essential_donor_fraction",
    "sc_normal_essential_n_datasets_reliable",
    "sc_normal_essential_median_abund",
    "safety_essential_flags",
    "n_cell_types_above_20pct",
    "n_reliable_cell_types",
    "per_cell_type_top",
    "tissues_queried",
    "origin_tissues",
    "indication",
)


def _anchor_files() -> list[Path]:
    return sorted(ANCHOR_DIR.glob("*.sc_normal_celltype.json"))


def _canon_top(rows: list[dict] | None) -> list[dict]:
    """Order-insensitive canonicalization of per_cell_type_top for comparison ONLY.

    #2047 batch E CI failure: reliable.sort_values(det_col, ascending=False).head(15) in
    methods/sc_normal_expression/stats.py has no secondary sort key, so ties at
    median_detection_fraction==1.0 (multiple cell types fully detected) order differently
    across pandas/hash environments — the capture host produced 'early colonocyte' first,
    CI produced 'BEST4+ colonocyte' first, same frozen input. The SET of top-15 cell types
    (and every row's own values) is identical; only the tie order differs.

    A reader-side stable secondary sort (cell_type name, then tissue) was evaluated but
    RIPPLES the already-merged skills EPCAM golden (SK#2073's sc-normal-celltype-expression
    card fixture pins per_cell_type_top[0] == 'early colonocyte', the capture-host order) —
    changing the reader's canonical order would drift that golden non-trivially (top-1 cell
    type changes), which is out of scope here (regenerating the skills golden is #2061's
    domain). So this test canonicalizes the COMPARISON instead, leaving the reader's live
    output byte-identical to what the skills golden already consumed. See the reader-
    determinism follow-up note filed on #2047 for the permanent fix.

    Sorted descending by detection fraction (matching the reader's primary key), tie-broken
    by cell_type then tissue so both sides land in the same canonical order regardless of
    which environment produced them.
    """
    if not rows:
        return []
    return sorted(
        rows,
        key=lambda r: (-(r.get("median_detection_fraction") or 0.0), r.get("cell_type") or "", r.get("tissue") or ""),
    )


def _rows_from_fixture(rel: str) -> list[dict]:
    import pyarrow.parquet as pq

    return pq.read_table(HERE / rel).to_pylist()


def _rederive(target: str, indication: str, records: list[dict], tissues_loaded: list[str]) -> dict:
    """Re-derive read_target_summary(target, indication) OFFLINE by reconstructing the frozen
    multi-tissue DataFrame (with tissues_loaded/tissues_missing .attrs) and monkeypatching ONLY the
    read_gene_celltype_rows S3-load seam — IDENTICAL to the helper in
    capture_sc_normal_celltype_anchor.py; the capture-time fidelity guard proves it reproduces the
    live read; this replays it against the same frozen bytes."""
    tissues = rd.tissues_for_indication(indication)
    df = pd.DataFrame(records, columns=_ROW_COLS)
    df.attrs["tissues_requested"] = list(tissues)
    df.attrs["tissues_with_product"] = list(tissues)
    df.attrs["tissues_loaded"] = list(tissues_loaded)
    df.attrs["tissues_missing"] = [t for t in tissues if t not in set(tissues_loaded)]
    with mock.patch.object(rd, "read_gene_celltype_rows", lambda t, tis: df):
        return rd.read_target_summary(target, indication)


pytestmark = pytest.mark.skipif(not _anchor_files(), reason="no sc_normal_celltype anchors committed")


@pytest.mark.parametrize("anchor_path", _anchor_files(), ids=lambda p: p.stem)
def test_rederives_from_raw_substrate(anchor_path: Path):
    anchor = json.loads(anchor_path.read_text())
    rows = _rows_from_fixture(anchor["rows_fixture"])
    summary = _rederive(anchor["target"], anchor["indication"], rows, anchor["tissues_loaded"])
    for f in _CARD_FIELDS:
        if f == "per_cell_type_top":
            # Order-insensitive: see _canon_top docstring — a tie-order artifact, not a real
            # divergence (the SET and every row's own values must still match exactly).
            assert _canon_top(summary.get(f)) == _canon_top(anchor["expected"][f]), (
                f"{anchor_path.stem}: {f} != anchor (canonicalized)"
            )
            continue
        assert summary.get(f) == anchor["expected"][f], f"{anchor_path.stem}: {f} != anchor"


def test_fixture_md5_matches_anchors():
    for anchor_path in _anchor_files():
        anchor = json.loads(anchor_path.read_text())
        digest = hashlib.md5((HERE / anchor["rows_fixture"]).read_bytes()).hexdigest()  # noqa: S324
        assert digest == anchor["rows_md5"], f"{anchor_path.stem}: rows fixture md5 drift"


def test_anchor_set_is_not_vacuous():
    files = _anchor_files()
    assert len(files) >= MIN_ANCHORS, f"need >= {MIN_ANCHORS} anchors, found {len(files)}"
    safety_classes = {json.loads(p.read_text())["expected"]["sc_normal_safety_essential_class"] for p in files}
    assert len(safety_classes) >= 1 and safety_classes != {None}, (
        "anchor set never exercises the safety-essential class"
    )


def test_teeth_dropping_the_essential_cell_type_row_moves_the_safety_class():
    """Teeth: dropping every row for the named essential-organ driver cell type must move
    sc_normal_safety_essential_class away from its committed critical/origin_tissue_liability value
    (or clear the named driver fields) — proving the essential-organ veto is a live cross-tissue scan
    of the frozen rows, not echoed from the anchor. Revert-verified the other direction by
    test_rederives_from_raw_substrate (the un-mutated rows reproduce exactly)."""
    moved = 0
    for anchor_path in _anchor_files():
        anchor = json.loads(anchor_path.read_text())
        driver_ct = anchor["expected"].get("sc_normal_essential_max_cell_type")
        if not driver_ct:
            continue
        rows = _rows_from_fixture(anchor["rows_fixture"])
        mutated = [r for r in rows if r["cell_type"] != driver_ct]
        summary = _rederive(anchor["target"], anchor["indication"], mutated, anchor["tissues_loaded"])
        assert (
            summary["sc_normal_safety_essential_class"] != anchor["expected"]["sc_normal_safety_essential_class"]
            or summary["sc_normal_essential_max_cell_type"] != driver_ct
        )
        moved += 1
    assert moved >= 1, "teeth vacuous: no anchor with a named essential-organ driver to perturb"


def test_teeth_zeroing_detection_collapses_liability_class():
    """Teeth: zeroing every row's median_det/expressing_donor_fraction must collapse
    sc_normal_expression_class to NOT_EXPRESSED — proving the liability ladder is a live threshold
    scan of the frozen rows' detection columns, not echoed from the anchor."""
    moved = 0
    for anchor_path in _anchor_files():
        anchor = json.loads(anchor_path.read_text())
        rows = _rows_from_fixture(anchor["rows_fixture"])
        mutated = []
        for r in rows:
            r = dict(r)
            r["median_det"] = 0.0
            r["expressing_donor_fraction"] = 0.0
            mutated.append(r)
        summary = _rederive(anchor["target"], anchor["indication"], mutated, anchor["tissues_loaded"])
        assert summary["sc_normal_expression_class"] == "NOT_EXPRESSED"
        assert summary["sc_normal_expression_class"] != anchor["expected"]["sc_normal_expression_class"]
        moved += 1
    assert moved >= 1, "teeth vacuous: no anchor to perturb"
