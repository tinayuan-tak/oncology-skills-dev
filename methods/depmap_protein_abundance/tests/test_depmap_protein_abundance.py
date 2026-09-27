"""Synthetic-data tests for depmap_protein_abundance (no S3).

Validates: (1) the distribution classifier at each band (broadly_low keyed off
detection fraction — the MS-sparse axis; the mid-band lineage split, where a lineage
token requires a non-empty per_lineage and an absent breakdown yields the claim-free
sub_broad_detection; broadly_high needs detection AND panel-relative high abundance);
(2) accession resolution via the
sidecar, incl. isoform-suffixed matrix columns; (3) the data_unavailable path
(target not resolved / absent from matrix) vs graceful read failure; (4) card-contract
fields; (5) fraction_detected uses the true panel size (denominator = total MS lines),
not detected-only. Classifier is pure; matrix tests use a tiny synthetic CSV + parquet.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Portable repo root: was hardcoded to the author's /home/sagemaker-user checkout, so every
# path guard below read as "data missing" on a CI runner or in a worktree.
METHODS_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(METHODS_REPO))
from methods.depmap_protein_abundance import cli as pc  # noqa: E402
from methods.depmap_protein_abundance import read as pc_read  # noqa: E402

# --- classifier (pure) ----------------------------------------------------


def test_broadly_low_when_detection_sparse():
    # detected in <30% of the panel → broadly_low (MS-absent across most lines)
    assert pc.classify_protein_abundance(0.20, 0.5, [], high_cutoff=0.4) == "broadly_low"


# Middle band [LOW_DETECTION_FRACTION, LINEAGE_RESTRICTED_MAX]. The lineage tokens are claims ABOUT
# lineage, so all three cases below are keyed on what per_lineage actually contains. This block used to
# be a single test asserting `classify(0.35, 0.1, [], ...) == "lineage_restricted"` — i.e. it pinned the
# defect: an empty breakdown returned the mechanistic label, and `broadly_moderate` was unreachable in
# this band for any caller without a lineage map (all 343 ProCan corpus cards).
_CONCENTRATED = [{"lineage": "LUNG", "n": 8}, {"lineage": "SKIN", "n": 6}]  # <= MAX_LINEAGES → concentrated
_SPREAD = [{"lineage": lg, "n": 5} for lg in ("LUNG", "SKIN", "BREAST", "COLON")]  # 4 lineages, top share 0.25


def test_mid_band_with_no_lineage_breakdown_makes_no_lineage_claim():
    """The regression this branch exists for: absent stratification must not mint a lineage claim."""
    assert pc.classify_protein_abundance(0.35, 0.1, [], high_cutoff=0.2) == "sub_broad_detection"
    assert pc.classify_protein_abundance(0.6512, 0.1, [], high_cutoff=0.2) == "sub_broad_detection"


def test_mid_band_lineage_restricted_needs_real_concentration():
    """lineage_restricted is still reachable — but now only on positive evidence."""
    assert pc.classify_protein_abundance(0.35, 0.1, _CONCENTRATED, high_cutoff=0.2) == "lineage_restricted"


def test_mid_band_broadly_moderate_is_reachable_on_measured_spread():
    """Falsifier for the vacuity: with a REAL spread breakdown the middle band reaches broadly_moderate.

    Before the fix no input could produce this token in this band, so the concentration predicate
    contributed zero bits and the band and the label were the same set.
    """
    assert pc.classify_protein_abundance(0.35, 0.1, _SPREAD, high_cutoff=0.2) == "broadly_moderate"


def test_lineage_claim_never_rests_on_an_empty_breakdown():
    """GUARD: sweep the whole detection range — no lineage token may be emitted with no lineage evidence.

    Fails loudly if the empty-per_lineage fallback is ever reintroduced anywhere in the band structure,
    including via _is_lineage_concentrated returning True for a falsy/zero-total breakdown. Swept rather
    than spot-checked because the original defect lived in ONE sub-band of a multi-band ladder.
    """
    lineage_tokens = {"lineage_restricted"}
    for i in range(0, 101):
        f = i / 100.0
        for empty in ([], [{"lineage": "LUNG", "n": 0}]):
            got = pc.classify_protein_abundance(f, 0.1, empty, high_cutoff=0.2)
            assert got not in lineage_tokens, f"lineage claim from empty breakdown at fraction_detected={f}: {got}"


def test_empty_breakdown_is_not_evidence_of_concentration():
    """The root-cause predicate itself: absence must not read as a positive."""
    assert pc._is_lineage_concentrated([]) is False
    assert pc._is_lineage_concentrated([{"lineage": "LUNG", "n": 0}]) is False
    assert pc._is_lineage_concentrated(_CONCENTRATED) is True
    assert pc._is_lineage_concentrated(_SPREAD) is False


def test_broadly_high_needs_detection_and_high_abundance():
    # detected broadly AND median clears the panel-relative high cutoff
    assert pc.classify_protein_abundance(0.90, 1.5, [], high_cutoff=1.0) == "broadly_high"


def test_broadly_moderate_when_detected_but_not_high():
    # detected broadly but median below the high cutoff (the centered-TMT common case)
    assert pc.classify_protein_abundance(0.90, 0.05, [], high_cutoff=0.5) == "broadly_moderate"


def test_every_distribution_class_has_a_takeaway_phrase():
    """A new class token must not silently lose its one-line takeaway.

    _protein_take does a .get() on _PROTEIN_PHRASE, so a missing entry returns None and the sentence
    just disappears from the output — a fail-open display gap rather than an error. The expected set is
    DERIVED by sweeping the classifier instead of hand-listed, so it tracks the vocabulary by itself.
    data_unavailable is deliberately phrase-less: there is no distribution to describe.
    """
    emitted = {
        pc.classify_protein_abundance(f, m, pl, high_cutoff=0.5)
        for f in (0.05, 0.20, 0.35, 0.50, 0.69, 0.90)
        for m in (0.1, 1.5)
        for pl in ([], _CONCENTRATED, _SPREAD)
    }
    unphrased = emitted - {"data_unavailable"} - set(pc._PROTEIN_PHRASE)
    assert not unphrased, f"class tokens the classifier can emit with no takeaway phrase: {sorted(unphrased)}"
    # Non-vacuity: the sweep must actually reach the new band, or this guard proves nothing about it.
    assert "sub_broad_detection" in emitted, "sweep no longer reaches the lineage-untested band"


# --- accession resolution (synthetic sidecar) -----------------------------


def _write_sidecar(tmp_path, rows):
    import pandas as pd

    p = tmp_path / "sidecar.parquet"
    df = pd.DataFrame(rows, columns=["native_row_key", "hgnc_primary_symbol_at_resolution"])
    df.to_parquet(p)
    return str(p)


def test_resolve_accession_by_symbol(tmp_path):
    sc = _write_sidecar(tmp_path, [("P01116", "KRAS"), ("P04626", "ERBB2")])
    assert pc.resolve_accession("KRAS", sidecar_path=sc) == "P01116"
    assert pc.resolve_accession("kras", sidecar_path=sc) == "P01116"  # case-insensitive
    assert pc.resolve_accession("NOPE", sidecar_path=sc) is None


# --- matrix column load incl. isoform-suffixed columns --------------------


def _write_matrix(tmp_path, cols, rows):
    """cols: accession column names; rows: [(ModelID, val_per_col...), ...]."""
    p = tmp_path / "matrix.csv"
    header = ["ModelID"] + cols
    with open(p, "w") as fh:
        fh.write(",".join(header) + "\n")
        for r in rows:
            fh.write(",".join(str(x) for x in r) + "\n")
    return str(p)


def test_load_column_and_panel_size(tmp_path):
    m = _write_matrix(tmp_path, ["P01116", "P04626"], [("ACH-1", 1.2, ""), ("ACH-2", 0.8, 2.0), ("ACH-3", "", 1.5)])
    col, panel = pc.load_abundance_column("P01116", matrix_path=m)
    assert panel == 3  # 3 ModelID rows total
    assert set(col.keys()) == {"ACH-1", "ACH-2"}  # ACH-3 is NaN for P01116 → dropped
    assert col["ACH-1"] == 1.2


def test_load_column_isoform_suffixed(tmp_path):
    # matrix carries an isoform-suffixed column; base accession must still match
    m = _write_matrix(tmp_path, ["Q8WY21-3"], [("ACH-1", 0.5), ("ACH-2", 0.7)])
    col, panel = pc.load_abundance_column("Q8WY21", matrix_path=m)
    assert col is not None and set(col.keys()) == {"ACH-1", "ACH-2"}


def test_absent_accession_returns_none_with_panel(tmp_path):
    m = _write_matrix(tmp_path, ["P01116"], [("ACH-1", 1.0), ("ACH-2", 1.0)])
    col, panel = pc.load_abundance_column("P99999", matrix_path=m)
    assert col is None and panel == 2


# --- fraction_detected uses true panel size -------------------------------


def test_fraction_detected_uses_panel_denominator():
    # 3 detected out of a 10-line panel → 0.30, NOT 1.0
    abundance = {"ACH-1": 1.0, "ACH-2": 1.1, "ACH-3": 0.9}
    s = pc.compute_summary("X", abundance, {}, n_panel=10)
    assert s["fraction_detected"] == 0.3
    assert s["n_cell_lines_evaluated"] == 3
    assert s["n_cell_lines_in_panel"] == 10


# --- data_unavailable path -------------------------------------------------


def test_unresolved_target_is_data_unavailable():
    s = pc.compute_summary("X", None, {}, n_panel=100)
    assert s["protein_expression_class"] == "data_unavailable"
    assert s["n_cell_lines_evaluated"] == 0


def test_card_contract_fields_present():
    s = pc.compute_summary("X", {"ACH-1": 1.0, "ACH-2": 0.5}, {}, n_panel=4)
    for f in (
        "protein_expression_class",
        "n_cell_lines_evaluated",
        "n_cell_lines_in_panel",
        "fraction_detected",
        "median_log2_abundance_panel",
        "n_lineages_evaluated",
        "per_lineage_stats",
        "method_version",
    ):
        assert f in s, f"missing card-contract field: {f}"
    # protein_effect_size REMOVED (#1853): it was a verbatim duplicate of
    # median_log2_abundance_panel (a tumor-vs-normal contrast name on a normal-arm-less
    # cell-line panel); the summary no longer emits it.
    assert "protein_effect_size" not in s


# --- per-lineage groupby honors min-lineage-size --------------------------


def test_per_lineage_respects_min_size():
    abundance = {f"ACH-{i}": 1.0 for i in range(10)}
    lineage = {f"ACH-{i}": ("Lung" if i < 6 else "Skin") for i in range(10)}  # Lung=6, Skin=4
    s = pc.compute_summary("X", abundance, lineage, n_panel=10)
    lins = {d["lineage"] for d in s["per_lineage_stats"]}
    assert "Lung" in lins  # n=6 >= MIN_LINEAGE_SIZE(5)
    assert "Skin" not in lins  # n=4 < 5 → excluded


# --- graceful degradation (dispatcher entry) ------------------------------


def test_gygi_hit_tags_source_gygi_ms(tmp_path, monkeypatch):
    """A normal Gygi-resolved call tags protein_abundance_source=gygi_ms (and never invokes Olink)."""
    sc = _write_sidecar(tmp_path, [("P01116", "KRAS")])
    m = _write_matrix(tmp_path, ["P01116"], [(f"ACH-{i}", 1.0 + (i % 3)) for i in range(30)])
    monkeypatch.setattr(pc, "load_model_lineage", lambda model_path=None: {})  # no S3 for Model.csv
    # Olink fallback must NOT be called on a Gygi hit — make it explode if it is.
    monkeypatch.setattr(
        pc,
        "load_olink_abundance_column",
        lambda t: (_ for _ in ()).throw(AssertionError("Olink must not be called on a Gygi hit")),
    )
    s = pc.load_and_classify("KRAS", matrix_path=m, sidecar_path=sc, model_path=None)
    assert s["protein_abundance_source"] == "gygi_ms"
    assert s["protein_expression_class"] != "data_unavailable"


def test_olink_fallback_rescues_gygi_absent_target(monkeypatch):
    """G1 follow-up: a target ABSENT from the Gygi matrix (col is None) is rescued via the Olink NPX
    fallback — classified against the Olink panel's own null, tagged protein_abundance_source=olink_npx,
    instead of collapsing to data_unavailable. (MSLN/MUC16-class surface antigens the shotgun-MS misses.)"""
    monkeypatch.setattr(pc, "resolve_accession", lambda t, sidecar_path=None: None)  # Gygi unresolved
    olink_col = {f"ACH-{i}": (3.0 + (i % 4) * 0.5) for i in range(30)}  # detected broadly
    monkeypatch.setattr(pc, "load_olink_abundance_column", lambda t: (olink_col, 30, "Q00000"))
    monkeypatch.setattr(pc, "_all_protein_median_null_olink", lambda: tuple(float(i) for i in range(100)))
    monkeypatch.setattr(pc, "load_model_lineage", lambda model_path=None: {})
    s = pc.load_and_classify("MSLN")
    assert s["protein_abundance_source"] == "olink_npx"
    assert s["protein_expression_class"] != "data_unavailable"
    assert s["fraction_detected"] == 1.0  # 30 detected / 30 panel


def test_both_gygi_and_olink_miss_is_data_unavailable(monkeypatch):
    """Gygi miss AND Olink miss → honest data_unavailable, tagged source=data_unavailable."""
    monkeypatch.setattr(pc, "resolve_accession", lambda t, sidecar_path=None: None)
    monkeypatch.setattr(pc, "load_olink_abundance_column", lambda t: (None, 0, None))
    s = pc.load_and_classify("GHOST")
    assert s["protein_expression_class"] == "data_unavailable"
    assert s["protein_abundance_source"] == "data_unavailable"


def test_read_target_summary_graceful_on_failure(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("s3 down")

    monkeypatch.setattr(pc, "load_and_classify", _boom)
    out = pc_read.read_target_summary(target="KRAS", indication="COADREAD")
    assert out["protein_expression_class"] == "data_unavailable"
    assert out["_live_read_error"] == "depmap_protein_abundance_read_failed"
