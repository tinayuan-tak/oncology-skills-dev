"""Threshold adjudication for the protein panel-relative p70 HIGH cut (#2223, epic #2210).

WHAT THIS MODULE IS. It is the *evidence* half of an adjudication, not a regression net for a fix.
The question #2223 asked was whether `HIGH_ABUNDANCE_PERCENTILE = 0.70` (protein, panel-relative)
diverges from the RNA twin's absolute `highly_expressed_threshold = 5.0`, and whether the
panel-relative cut is "stable enough to be a determinant at all". Every assertion below re-derives
its subject from the committed RAW measured values in
`fixtures/gygi_measured_submatrix.csv.gz` (375 real DepMap 26Q1 models x 300 real Gygi protein
columns) through the real `cli` functions. Nothing is imputed and no derived value is asserted
straight out of a fixture — a fixture of derived values can never fail.

IF ONE OF THESE REDS it most likely means the measurement no longer holds (the release changed, or
the cut's axis was repaired). That is a signal to re-read the adjudication recorded on #2223, not a
regression to paper over. Each test says which.

No threshold is changed here and nothing is asserted about any verdict in either direction (SK#2091).
"""

from __future__ import annotations

import gzip
import io
import json
import statistics
from pathlib import Path

import pytest

from onc_methods.depmap_protein_abundance import cli

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SUBMATRIX = FIXTURES / "gygi_measured_submatrix.csv.gz"
LINEAGES = FIXTURES / "gygi_submatrix_lineages.json"
RECORD = FIXTURES / "gygi_panel_composition_flip_matrix.json"

# The two `tumor_presence_controls.yaml` housekeeping entries, curated as
# "ubiquitously high -> the CEILING anchor (universal)".
CEILING_ANCHORS = ("ACTB", "GAPDH")


def _read_submatrix() -> tuple[list[str], list[str], list[list[float | None]]]:
    """Raw fixture reader. Returns (model_ids, accessions, rows-of-values) with None for not-detected.

    Deliberately hand-rolled rather than pandas so the values the tests reason about are the literal
    bytes in the fixture, with no dtype coercion in between.
    """
    with gzip.open(SUBMATRIX, "rb") as fh:
        text = io.TextIOWrapper(fh, encoding="utf-8").read()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    header = lines[0].split(",")
    accessions = header[1:]
    models: list[str] = []
    values: list[list[float | None]] = []
    for ln in lines[1:]:
        parts = ln.split(",")
        models.append(parts[0])
        values.append([None if p == "" else float(p) for p in parts[1:]])
    assert len(accessions) > 0, f"fixture {SUBMATRIX.name} has no protein columns"
    assert all(len(r) == len(accessions) for r in values), "ragged fixture rows"
    return models, accessions, values


def _lineage_map() -> dict:
    return json.loads(LINEAGES.read_text())


def _record() -> dict:
    return json.loads(RECORD.read_text())


def _column(values, j) -> list[float]:
    return [r[j] for r in values if r[j] is not None]


def _all_protein_median_null(values, rowsel) -> tuple:
    """Re-derive cli._all_protein_median_null's documented offline pass (one median per column)."""
    n_cols = len(values[0])
    out = []
    for j in range(n_cols):
        col = [values[i][j] for i in rowsel if values[i][j] is not None]
        out.append(statistics.median(col) if col else float("nan"))
    return tuple(out)


def _summary(values, models, lin, rowsel, j, null):
    col = {models[i]: values[i][j] for i in rowsel if values[i][j] is not None}
    if not col:
        return None
    lb = {models[i]: lin.get(models[i]) or "unknown" for i in rowsel}
    return cli.compute_summary("X", col, lb, n_panel=len(rowsel), all_protein_medians=null)


@pytest.fixture(scope="module")
def panel():
    models, accessions, values = _read_submatrix()
    lin = _lineage_map()
    rowsel = list(range(len(models)))
    null = _all_protein_median_null(values, rowsel)
    cutoff = cli._quantile([float(x) for x in null], cli.HIGH_ABUNDANCE_PERCENTILE)
    return {
        "models": models,
        "accessions": accessions,
        "values": values,
        "lin": lin,
        "rowsel": rowsel,
        "null": null,
        "cutoff": cutoff,
        "record": _record(),
    }


# --------------------------------------------------------------------------------------------- 1
def test_fixture_holds_RAW_values_and_the_recorded_anchor_summaries_RE_DERIVE(panel):
    """Anti-vacuity control + raw-input discipline.

    The recorded per-anchor summaries are NOT trusted as stored numbers: they are rebuilt here from
    the fixture's raw per-cell-line values through the real `cli.compute_summary`. It is also the
    clean unmutated control for every mutant below: if this is red, no other red in this module
    means anything.

    MEASURED LIMIT OF THIS TEST, recorded because it surprised the author: perturbing ONE arbitrary
    raw value by +1.0 log2 leaves this GREEN, and that is correct rather than a hole — every scalar
    it checks (`median`, `fraction_detected`, `n_cell_lines_evaluated`) is a rank or count statistic
    over ~375 values and is robust to a single non-median edit. Whole-column shifts and edits at the
    median DO red it. The teeth that make an arbitrary single-value edit visible live in
    `test_the_committed_raw_matrix_is_byte_for_byte_the_one_the_record_was_measured_over`.
    """
    exp = panel["record"]["fixture_expectations"]["control_anchors"]
    assert len(exp) == 6, f"expected the 6 resolvable control anchors, got {sorted(exp)}"
    idx = {a: i for i, a in enumerate(panel["accessions"])}
    for sym, want in exp.items():
        j = idx[want["accession"]]
        got = _summary(panel["values"], panel["models"], panel["lin"], panel["rowsel"], j, panel["null"])
        assert got is not None, f"{sym} has no detected values in the fixture"
        assert got["protein_expression_class"] == want["protein_expression_class"], sym
        assert got["fraction_detected"] == pytest.approx(want["fraction_detected"], abs=1e-4), sym
        assert got["median_log2_abundance_panel"] == pytest.approx(want["median_log2_abundance_panel"], abs=1e-6), sym
        assert got["n_cell_lines_evaluated"] == want["n_cell_lines_evaluated"], sym


# --------------------------------------------------------------------------------------------- 1b
def test_the_committed_raw_matrix_is_byte_for_byte_the_one_the_record_was_measured_over():
    """Joins the measurement record to the data it was measured over, at single-value resolution.

    Without this, an arbitrary edit to one of the ~800 KB of raw values is invisible to every other
    test in the module (see the measured limit noted above), so the record could silently stop
    describing the committed matrix. What this does NOT prove: that the digest matches the
    production S3 object — the fixture is a documented 300-column stratified sample of it, and
    `_meta.reproduce` is how you rebuild it.
    """
    sub = _record()["fixture_expectations"]["submatrix"]
    import hashlib

    raw = gzip.decompress(SUBMATRIX.read_bytes())
    assert len(raw) == sub["decompressed_bytes"], (
        f"{SUBMATRIX.name} decompresses to {len(raw)} bytes, record says {sub['decompressed_bytes']}"
    )
    assert hashlib.sha256(raw).hexdigest() == sub["sha256_of_decompressed_csv"], (
        f"{SUBMATRIX.name} no longer matches the digest recorded in {RECORD.name} — the measurement "
        "record and the raw matrix have drifted apart; re-run _meta.reproduce, do not edit the digest"
    )


# --------------------------------------------------------------------------------------------- 2
def test_the_class_cutoff_and_the_DISPLAY_reference_line_cut_DIFFERENT_populations(panel):
    """`HIGH_ABUNDANCE_PERCENTILE` is applied to TWO different distributions under one name.

    - the CLASS cutoff (`compute_summary`, cli.py:555) is p70 of ALL proteins' panel medians;
    - the DISPLAY reference line (`_panel_high_cutoff`, cli.py:686, drawn at 758/837/922) is p70 of
      THE TARGET'S OWN detected values.

    `_panel_high_cutoff`'s docstring used to claim it "mirrors compute_summary's high_cutoff". It
    does not, and this pins the difference so the claim cannot come back. Mutant: make
    `_panel_high_cutoff` return `cli._quantile(all_protein_medians, 0.70)` and this reds.
    """
    idx = {a: i for i, a in enumerate(panel["accessions"])}
    class_cut = panel["cutoff"]
    far = 0
    per_anchor = {}
    for sym, want in panel["record"]["fixture_expectations"]["control_anchors"].items():
        vals = _column(panel["values"], idx[want["accession"]])
        display = cli._panel_high_cutoff(vals)
        per_anchor[sym] = (display, class_cut)
        if abs(display - class_cut) > 0.05:
            far += 1
    assert len(per_anchor) == 6, per_anchor
    assert far >= 5, (
        "the display reference line should sit far from the class cutoff for almost every target; "
        f"only {far}/6 anchors were >0.05 log2 apart: {per_anchor}"
    )
    # and the substitution is not cosmetic: it changes at least one anchor's class.
    changed = []
    for sym, want in panel["record"]["fixture_expectations"]["control_anchors"].items():
        j = idx[want["accession"]]
        vals = _column(panel["values"], j)
        s = _summary(panel["values"], panel["models"], panel["lin"], panel["rowsel"], j, panel["null"])
        display = cli._panel_high_cutoff(vals)
        as_if = cli.classify_protein_abundance(
            s["fraction_detected"], s["median_log2_abundance_panel"], s["per_lineage_stats"], display
        )
        if as_if != s["protein_expression_class"]:
            changed.append((sym, s["protein_expression_class"], as_if))
    assert changed, (
        "substituting the display line for the class cutoff changed no anchor's class — the two "
        "cutoffs would then be interchangeable, contradicting this module's premise"
    )


# --------------------------------------------------------------------------------------------- 3
def test_the_DISPLAY_reference_line_leaves_a_CONSTANT_share_of_plotted_points_above_it(panel):
    """Why the display line carries no abundance information, proved on measured values.

    Because it is a quantile OF THE PLOTTED DATA, ~30% of each target's own points sit at or above it
    for EVERY target — regardless of how abundant the protein is. A reader taking the annotation at
    face value reads a classification boundary off a line that cannot be one. Mutant: repoint
    `_panel_high_cutoff` at the all-protein null and the share fans out across [0, 1], reddening the
    spread assertion.
    """
    shares = []
    for j in range(len(panel["accessions"])):
        vals = _column(panel["values"], j)
        if len(vals) < 20:
            continue
        hi = cli._panel_high_cutoff(vals)
        shares.append(sum(1 for v in vals if v >= hi) / len(vals))
    assert len(shares) >= 200, f"too few fixture proteins with >=20 detected lines: {len(shares)}"
    assert min(shares) >= 0.25, f"min share above the display line {min(shares):.4f}"
    assert max(shares) <= 0.40, f"max share above the display line {max(shares):.4f}"
    assert max(shares) - min(shares) <= 0.15, (
        f"share above the display line varied by {max(shares) - min(shares):.4f} across "
        f"{len(shares)} proteins — it is supposed to be pinned near 1 - "
        f"{cli.HIGH_ABUNDANCE_PERCENTILE} by construction"
    )


# --------------------------------------------------------------------------------------------- 4
def test_panel_COMPOSITION_alone_shifts_the_relative_high_cutoff_and_MOVES_class_calls(panel):
    """The issue's question (a): is the relative cut stable enough to be a determinant?

    Arm A = the full fixture roster. Arm B = the SAME rules with one OncotreeLineage dropped — a real
    subset of measured data, nothing imputed. Both arms are re-derived here from raw values. A RED
    means the recorded matrix no longer reproduces; re-read #2223 before changing the numbers.
    Mutant: make `classify_protein_abundance` ignore `high_cutoff` and every arm reports 0 movers.
    """
    arms = panel["record"]["fixture_expectations"]["leave_one_lineage_out_arms"]
    assert len(arms) >= 10, f"only {len(arms)} leave-one-lineage-out arms recorded"
    base = [
        _summary(panel["values"], panel["models"], panel["lin"], panel["rowsel"], j, panel["null"])
        for j in range(len(panel["accessions"]))
    ]
    base_cls = [None if s is None else s["protein_expression_class"] for s in base]
    lin = panel["lin"]
    checked = 0
    for arm in arms:
        if arm["n_movers"] == 0:
            continue
        dropped = arm["dropped_lineage"]
        rowsel = [i for i, m in enumerate(panel["models"]) if (lin.get(m) or "unknown") != dropped]
        assert len(rowsel) == arm["n_models"], (dropped, len(rowsel), arm["n_models"])
        null_b = _all_protein_median_null(panel["values"], rowsel)
        cut_b = cli._quantile([float(x) for x in null_b], cli.HIGH_ABUNDANCE_PERCENTILE)
        assert cut_b == pytest.approx(arm["cutoff"], abs=1e-8), dropped
        assert cut_b != panel["cutoff"], f"dropping {dropped} left the cutoff untouched"
        movers = []
        for j in range(len(panel["accessions"])):
            s = _summary(panel["values"], panel["models"], lin, rowsel, j, null_b)
            k = None if s is None else s["protein_expression_class"]
            if k != base_cls[j]:
                movers.append(panel["accessions"][j])
        assert len(movers) == arm["n_movers"], (dropped, len(movers), arm["n_movers"])
        for rec in arm["movers"]:
            assert rec["accession"] in movers, (dropped, rec)
        checked += 1
        if checked == 2:  # two arms fully re-derived is enough; the rest are recorded
            break
    assert checked == 2, f"expected >=2 recorded arms with movers to re-derive, got {checked}"


# --------------------------------------------------------------------------------------------- 5
def test_the_gygi_scale_is_per_protein_CENTRED_so_cross_protein_rank_carries_less_than_noise(panel):
    """The load-bearing premise of the adjudication, re-derived from the fixture.

    The harmonized Gygi value is a per-protein-centred TMT log2 ratio, so the BETWEEN-protein spread
    of panel medians (the distribution `HIGH_ABUNDANCE_PERCENTILE` cuts) is far smaller than the
    WITHIN-protein spread across cell lines (the measurement's own scatter). A percentile on that
    distribution therefore separates proteins by less than the noise it is separating them through.

    Falsifiability is demonstrated in-test rather than asserted: the same statistic is recomputed on
    a de-centred copy of the very same values, where it must come out the other way.
    """

    def ratio(values):
        meds, sds = [], []
        for j in range(len(values[0])):
            col = [r[j] for r in values if r[j] is not None]
            if len(col) < 10:
                continue
            meds.append(statistics.median(col))
            sds.append(statistics.pstdev(col))
        return statistics.pstdev(meds) / statistics.median(sds), len(meds)

    r, n = ratio(panel["values"])
    assert n >= 200, f"too few usable columns: {n}"
    assert r < 0.5, (
        f"between-protein sd / within-protein sd = {r:.4f} over {n} proteins; the adjudication on "
        "#2223 rests on this being well below 1 — if it is not, re-read the issue"
    )
    # de-centred control: restore a cross-protein dynamic range and the statistic must invert.
    decentred = [[None if v is None else v + 3.0 * ((j % 7) - 3) for j, v in enumerate(row)] for row in panel["values"]]
    r2, _ = ratio(decentred)
    assert r2 > 1.0, f"the de-centred control did not invert the statistic (got {r2:.4f}) — test is vacuous"


# --------------------------------------------------------------------------------------------- 6
def test_the_two_declared_CEILING_anchors_STRADDLE_the_relative_high_bar(panel):
    """The adjudication's sharpest single measurement, pinned to the curated controls.

    `contracts/vocabularies/tumor_presence_controls.yaml` curates ACTB and GAPDH together as
    "housekeeping: ubiquitously high -> the CEILING anchor (universal)". On the relative bar they
    land on OPPOSITE sides while their panel medians differ by a few hundredths of a log2 unit. That
    is the evidence #2223 is adjudicated on. A RED here means the axis moved — go re-read #2223's
    adjudication comment before editing this number.
    """
    exp = panel["record"]["fixture_expectations"]["control_anchors"]
    classes = {s: exp[s]["protein_expression_class"] for s in CEILING_ANCHORS}
    medians = {s: exp[s]["median_log2_abundance_panel"] for s in CEILING_ANCHORS}
    idx = {a: i for i, a in enumerate(panel["accessions"])}
    for s in CEILING_ANCHORS:  # re-derive, never trust the stored class
        j = idx[exp[s]["accession"]]
        got = _summary(panel["values"], panel["models"], panel["lin"], panel["rowsel"], j, panel["null"])
        assert got["protein_expression_class"] == classes[s], s
        assert got["median_log2_abundance_panel"] == pytest.approx(medians[s], abs=1e-6), s
    assert len(set(classes.values())) == 2, f"the two curated ceiling anchors no longer straddle the bar: {classes}"
    gap = abs(medians["ACTB"] - medians["GAPDH"])
    assert gap < 0.05, f"ACTB/GAPDH panel medians are {gap:.4f} log2 apart, not the recorded hair's breadth"
