"""T3 recomputation anchors — single-cell tumor expression by cell type (compartment).

Plan foamy-bird, Stage I / tier T3 (the ONLY tier that proves a NUMBER is right), seventh skill.
Re-derives the sc-tumor-expression-celltype card's headline fields — sc_expression_class,
malignant_detection_fraction, malignant_abundance_log1p_cp10k, malignant_n_donors/n_cells,
caf_vs_malignant_class, caf_detection_fraction, top-microenvironment readout, n_compartments_measured —
from the IRREPRODUCIBLE raw input (the per-(dataset, donor, compartment) pseudobulk rows for a gene)
through the REAL methods.sc_tumor_expression_celltype.read.read_sc_expression_presence pipeline
(compartment_summary -> classify_sc_expression + caf_readout). See capture_sc_celltype_anchor.py for how
an anchor is made.

Why this is not the green-for-the-wrong-reason trap the calibration snapshots fall into: a snapshot stores
a DERIVED value and asserts the code reproduces its own output — it can never catch a wrong computation.
Here the fixture is the raw per-donor rows; the cross-donor MEDIAN detection fraction is re-reduced over
the reliable donors, the malignant cell/donor floors are re-applied, and sc_expression_class is
re-classified through the real ladder. The teeth below prove the assertions bite: lower the malignant
detection fraction and the re-derived median must fall; drop the reliable malignant donors below the floor
and the class must collapse to data_unavailable; remove the malignant compartment and it must collapse too.

Anchors span the classifier's branches: APC/MET/MSLN/TACSTD2 (malignant_subset_detected), CEACAM5/EPCAM/
FOLR1 (malignant_broadly_detected), DLL3-SCLC (data_unavailable — no landed sc pseudobulk product; an
honest absence anchor with no rows to re-derive). All are tumor-selectivity roster pairs carrying an
sc_tumor_expression_class headline, so each anchor's class + malignant_detection_fraction +
caf_vs_malignant_class is cross-checked against that independently-captured record.

OFFLINE — reads only committed fixtures, monkeypatches the single per-gene reader, no creds. Runs in CI.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

HERE = Path(__file__).resolve().parent
ANCHOR_DIR = HERE / "anchors"

# The pipeline module does absolute `from onc_methods.…` imports at module scope; they resolve through
# the editable install from any cwd, so nothing has to be put on sys.path first (skills#2237 deleted the
# insert this used to need). We test the REAL card code — re-deriving through it is what makes T3 a real
# test, not a self-echo.

import onc_methods.sc_tumor_expression_celltype.read as rd

MIN_ANCHORS = 6  # anti-vacuity floor below the current 8; a zeroed dir must never read as green
MIN_DISTINCT_CLASSES = 3  # the set must span classifier branches, not all sit in one
MIN_MALIGNANT_DONORS = 5  # a measured anchor rests on >= MIN_RELIABLE_DONORS reliable malignant donors
# The roster snapshot's continuous malignant_detection_fraction is an older independent capture that drifts
# with the pseudobulk product vintage (categorical class/CAF are stable); cross-check it within a sanity
# band, not exactly. The EXACT numeric proof is test_rederives_from_raw_rows over the frozen input.
MDF_VINTAGE_TOL = 0.05
_ROW_COLS = [
    "gene_symbol",
    "dataset_id",
    "donor_id",
    "compartment",
    "n_cells",
    "detection_fraction",
    "abundance_log1p_cp10k",
]

_FIELDS_EXACT = (
    ("sc_expression_class", "expected_sc_expression_class"),
    ("malignant_detection_fraction", "expected_malignant_detection_fraction"),
    ("malignant_abundance_log1p_cp10k", "expected_malignant_abundance_log1p_cp10k"),
    ("malignant_compartment_available", "expected_malignant_compartment_available"),
    ("malignant_n_donors", "expected_malignant_n_donors"),
    ("malignant_n_cells", "expected_malignant_n_cells"),
    ("n_compartments_measured", "expected_n_compartments_measured"),
    ("top_microenvironment_compartment", "expected_top_microenvironment_compartment"),
    ("top_microenvironment_detection_fraction", "expected_top_microenvironment_detection_fraction"),
    ("caf_vs_malignant_class", "expected_caf_vs_malignant_class"),
    ("caf_detection_fraction", "expected_caf_detection_fraction"),
)


def _anchor_files() -> list[Path]:
    return sorted(ANCHOR_DIR.glob("*.sc_celltype.json"))


def _load_anchor(path: Path) -> dict:
    return json.loads(path.read_text())


def _load_rows(anchor: dict):
    """The frozen per-(dataset, donor, compartment) rows for this anchor as a DataFrame, or None when the
    anchor records a no-product indication (rows_kind == 'none') — the irreproducible input slice."""

    if anchor["rows_kind"] == "none":
        return None
    table = pq.read_table(HERE / anchor["rows_fixture"]).to_pandas()
    sub = table[(table["anchor_target"] == anchor["target"]) & (table["anchor_indication"] == anchor["indication"])]
    return sub[_ROW_COLS].reset_index(drop=True)


def _rederive(monkeypatch, rows, target: str, indication: str) -> dict:
    """Force the pipeline down the frozen-rows path: read_gene_compartment_rows -> the frozen DataFrame
    (or None). Then call the REAL library entry point, which re-computes every field over those rows."""
    monkeypatch.setattr(rd, "read_gene_compartment_rows", lambda t, i: rows)
    return rd.read_sc_expression_presence(target, indication)


ANCHOR_FILES = _anchor_files()
ANCHOR_PARAMS = [pytest.param(p, id=p.name.replace(".sc_celltype.json", "")) for p in ANCHOR_FILES]
# Measured anchors only (a real frozen-row slice, not a no-product absence) — the numeric teeth are defined
# on the anchors that HAVE rows.
MEASURED_PARAMS = [
    pytest.param(p, id=p.name.replace(".sc_celltype.json", ""))
    for p in ANCHOR_FILES
    if _load_anchor(p)["rows_kind"] == "rows"
]


def test_anchor_set_is_not_vacuous():
    # A silently-empty anchor dir is indistinguishable from a passing suite — the trap this tier removes.
    assert len(ANCHOR_FILES) >= MIN_ANCHORS, (
        f"expected >= {MIN_ANCHORS} recomputation anchor(s), found {len(ANCHOR_FILES)} in {ANCHOR_DIR}"
    )
    classes = {_load_anchor(p)["expected_sc_expression_class"] for p in ANCHOR_FILES}
    assert len(classes) >= MIN_DISTINCT_CLASSES, (
        f"anchors must exercise >= {MIN_DISTINCT_CLASSES} classifier branches; found {sorted(classes)}"
    )


def test_fixture_md5_matches_anchors():
    # Every anchor pins the same source-slice md5; the committed parquet must still hash to it, or a
    # re-derivation is running against a different (possibly hand-edited) input than was captured.
    for path in ANCHOR_FILES:
        anchor = _load_anchor(path)
        fixture = HERE / anchor["rows_fixture"]
        md5 = hashlib.md5(fixture.read_bytes()).hexdigest()
        assert md5 == anchor["_source"]["rows_fixture_md5"], f"{path.name}: fixture md5 drift"


@pytest.mark.parametrize("anchor_path", MEASURED_PARAMS)
def test_rows_are_full_not_truncated(anchor_path: Path):
    # The compartment medians summarize the WHOLE donor panel; a truncated slice would silently change
    # every field. Assert the frozen rows still hold the row count + the reliable-malignant-donor count.
    anchor = _load_anchor(anchor_path)
    rows = _load_rows(anchor)
    assert len(rows) == anchor["n_rows"], "frozen row count drifted from captured n"
    assert anchor["expected_malignant_n_donors"] >= MIN_MALIGNANT_DONORS, (
        "a measured anchor must rest on >= MIN_RELIABLE_DONORS reliable malignant donors"
    )


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_rederives_from_raw_rows(monkeypatch, anchor_path: Path):
    """The pinned class, fractions, counts and CAF readout must re-derive from the raw per-donor rows via
    the REAL pipeline — exact reproduction, not a stored echo."""
    anchor = _load_anchor(anchor_path)
    rows = _load_rows(anchor)
    r = _rederive(monkeypatch, rows, anchor["target"], anchor["indication"])
    for field, expected_key in _FIELDS_EXACT:
        assert r.get(field) == anchor[expected_key], (
            f"{field}: re-derived {r.get(field)!r} != pinned {anchor[expected_key]!r}"
        )


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_agrees_with_roster_snapshot(anchor_path: Path):
    """Every anchor is a tumor-selectivity roster pair; its re-derived categorical fields
    (sc_expression_class / caf_vs_malignant_class) must equal the snapshot's independently-captured headline
    EXACTLY, and the continuous malignant_detection_fraction must fall within the vintage-drift sanity band
    (the snapshot fraction is an older independent capture; the exact numeric proof is test_rederives)."""
    anchor = _load_anchor(anchor_path)
    cross = anchor.get("snapshot_cross_ref")
    if cross is None:
        pytest.skip("pair not in the tumor-selectivity roster")
    assert cross["sc_tumor_expression_class"] == anchor["expected_sc_expression_class"]
    assert cross["sc_caf_vs_malignant_class"] == anchor["expected_caf_vs_malignant_class"]
    snap_mdf = cross["sc_malignant_detection_fraction"]
    exp_mdf = anchor["expected_malignant_detection_fraction"]
    if snap_mdf is not None and exp_mdf is not None:
        assert abs(snap_mdf - exp_mdf) <= MDF_VINTAGE_TOL, (
            f"malignant_detection_fraction {exp_mdf} is > {MDF_VINTAGE_TOL} off snapshot {snap_mdf} — "
            "too far to be a product-vintage refresh"
        )


def test_at_least_one_roster_cross_ref_present():
    # test_agrees_with_roster_snapshot pytest.skips when a pair is not in the roster; guard against ALL of
    # them skipping (which would make that assertion vacuously green — the missing-sibling trap).
    assert any(_load_anchor(p).get("snapshot_cross_ref") for p in ANCHOR_FILES), (
        "no anchor carries a roster snapshot_cross_ref — the cross-repo assertion is vacuous"
    )


# ---------------------------------------------------------------------------
# Teeth: the assertions above must FAIL when the input moves. If they don't, the test is comparing a
# derived fixture to itself. Each mutation runs on a COPY of the frozen rows.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("anchor_path", MEASURED_PARAMS)
def test_teeth_lowering_malignant_detection_moves_the_fraction(monkeypatch, anchor_path: Path):
    """Subtracting a constant from the malignant compartment's per-donor detection_fraction (clamped >= 0)
    must strictly LOWER the re-derived cross-donor median — proving the median is re-reduced live over the
    frozen rows, not echoed from the pin."""
    anchor = _load_anchor(anchor_path)
    rows = _load_rows(anchor).copy()
    is_mal = rows["compartment"] == "malignant"
    rows.loc[is_mal, "detection_fraction"] = (rows.loc[is_mal, "detection_fraction"] - 0.4).clip(lower=0.0)
    r = _rederive(monkeypatch, rows, anchor["target"], anchor["indication"])
    assert r["malignant_detection_fraction"] < anchor["expected_malignant_detection_fraction"]


@pytest.mark.parametrize("anchor_path", MEASURED_PARAMS)
def test_teeth_dropping_reliable_donors_collapses_to_data_unavailable(monkeypatch, anchor_path: Path):
    """Keeping only 4 malignant donors (below MIN_RELIABLE_DONORS=5) must collapse sc_expression_class to
    data_unavailable — proving the cross-donor reliability floor is load-bearing for the class, not a
    decoration. Non-malignant compartments are left intact so the ONLY cause is the malignant donor floor."""
    anchor = _load_anchor(anchor_path)
    rows = _load_rows(anchor).copy()
    is_mal = rows["compartment"] == "malignant"
    keep_donors = list(dict.fromkeys(rows.loc[is_mal, "donor_id"].tolist()))[:4]
    kept = rows[(~is_mal) | (rows["donor_id"].isin(keep_donors))]
    r = _rederive(monkeypatch, kept.reset_index(drop=True), anchor["target"], anchor["indication"])
    assert r["sc_expression_class"] == "data_unavailable"
    assert r["sc_expression_class"] != anchor["expected_sc_expression_class"]


@pytest.mark.parametrize("anchor_path", MEASURED_PARAMS)
def test_teeth_removing_malignant_compartment_collapses_to_data_unavailable(monkeypatch, anchor_path: Path):
    """Removing the malignant compartment rows entirely must collapse sc_expression_class to
    data_unavailable — the malignant compartment is what the class is anchored on. Other compartments
    remain (so comp_summary is non-empty), isolating the malignant-anchoring guard."""
    anchor = _load_anchor(anchor_path)
    rows = _load_rows(anchor).copy()
    non_mal = rows[rows["compartment"] != "malignant"].reset_index(drop=True)
    if non_mal.empty:
        pytest.skip("anchor has only a malignant compartment; the empty-comp_summary path is a different guard")
    r = _rederive(monkeypatch, non_mal, anchor["target"], anchor["indication"])
    assert r["sc_expression_class"] == "data_unavailable"
    assert r["malignant_compartment_available"] is False
