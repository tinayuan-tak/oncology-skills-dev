"""T3 recomputation anchors — DepMap paralog-buffering (dual-KO synthetic lethality).

Plan foamy-bird, Stage I / tier T3 (the ONLY tier that proves a NUMBER is right), fifth skill.
Re-derives the paralog-buffering card's headline fields — paralog_buffering_class, strongest_paralog_symbol,
strongest_paralog_delta, n_paralogs_annotated, n_paralogs_functionally_buffering — from the IRREPRODUCIBLE raw
input (a column slice of the ~69 MB ParalogGeneEffect.csv holding each anchor target's dual-KO pair columns and
the single-KO baseline columns for the genes involved, across all cell-line rows) through the REAL
methods.depmap_paralog_aggregator.read pipeline. See capture_paralog_anchor.py for how an anchor is made.

Why this is not the green-for-the-wrong-reason trap the calibration snapshots fall into: a snapshot stores a
DERIVED value and asserts the code reproduces its own output — it can never catch a wrong computation. Here the
fixture is the raw per-cell-line dual-KO and single-KO SCORES; the per-pair median dual-KO effect is re-reduced
over them, the buffering delta is re-derived as min(single_a, single_b) - median_dual (the CORRECTED metric — a
max() baseline manufactured buffering on essential members, see read.py), and the class is re-classified by the
0.5/0.2 cuts. The reader prefers a pre-computed derived product; that path serves stored deltas, so the raw-CSV
recompute (product forced off) is what a "prove the number" anchor pins. The teeth below prove the assertions
bite: shift the dual-KO scores down and the delta must rise; truncate the panel and the delta must move; drop
every single-KO baseline and the class must collapse to data_unavailable (no baseline → no buffering call).

Anchors span all four class branches: VPS4A/ASF1A/KRAS/CDK4 (strong), ARID1A/RPL22 (partial), ME2/SMARCA4
(none), DDX3X (data_unavailable — absent from the paralog screens). KRAS additionally carries the
functional-requirement roster's own paralog headline, so its re-derivation is cross-checked against that record.

OFFLINE — reads only committed fixtures, monkeypatches the CSV cache + derived-product seams, no creds. Runs in CI.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ANCHOR_DIR = HERE / "anchors"

# The pipeline module does absolute `from methods.…` imports at module scope, so the analysis-methods root
# must be importable. Insert it explicitly (the sibling recomputation tests import the same way). We test the
# REAL card code — re-deriving through it is what makes T3 a real test, not a self-echo.
_AM_ROOT = HERE.parents[2]
if str(_AM_ROOT) not in sys.path:
    sys.path.insert(0, str(_AM_ROOT))

import methods.depmap_paralog_aggregator.read as rd  # noqa: E402

MIN_ANCHORS = 6  # anti-vacuity floor below the current 9; a zeroed dir must never read as green
MIN_DISTINCT_CLASSES = 3  # the set must span class branches, not all sit in one
MIN_MODEL_ROWS = 200  # a truncated slice would silently change every median the fields summarize
_CONTROL_MARKERS = {"AAVS1", "CHR2", "NONTARGET", "SAFE"}
_FIELDS = (
    "paralog_buffering_class",
    "strongest_paralog_symbol",
    "strongest_paralog_delta",
    "n_paralogs_annotated",
    "n_paralogs_functionally_buffering",
)


def _anchor_files() -> list[Path]:
    return sorted(ANCHOR_DIR.glob("*.paralog_buffering.json"))


def _load_anchor(path: Path) -> dict:
    return json.loads(path.read_text())


def _col_kind(col_name: str) -> str | None:
    """'pair' | 'single' | None — the same header classification read._load_paralog_indexed uses, replicated
    here only to build the mutation teeth (which pair/single columns to perturb)."""
    tokens = [t.strip().upper() for t in col_name.strip().split("_")]
    if len(tokens) == 1:
        return "single" if tokens[0] and tokens[0] not in _CONTROL_MARKERS else None
    if len(tokens) != 2:
        return None
    a, b = tokens
    if not a or not b or a in _CONTROL_MARKERS or b in _CONTROL_MARKERS or a == b:
        return None
    return "pair"


def _read_slice(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _rederive(monkeypatch, csv_path: Path, target: str) -> dict:
    """Force the pipeline down the frozen-slice raw-CSV recompute: _ensure_paralog_cached → the slice CSV,
    the parse cache cleared, the derived-product path forced off. Then call the REAL library entry point."""
    monkeypatch.setattr(rd, "_ensure_paralog_cached", lambda: csv_path)
    monkeypatch.setattr(rd, "_read_from_derived_product", lambda t: None)
    rd._load_paralog_indexed.cache_clear()
    return rd.read_target_summary(target)


ANCHOR_FILES = _anchor_files()
ANCHOR_PARAMS = [pytest.param(p, id=p.name.replace(".paralog_buffering.json", "")) for p in ANCHOR_FILES]
MEASURED_PARAMS = [
    pytest.param(p, id=p.name.replace(".paralog_buffering.json", ""))
    for p in ANCHOR_FILES
    if _load_anchor(p)["expected_strongest_paralog_delta"] is not None
]


def test_anchor_set_is_not_vacuous():
    # A silently-empty anchor dir is indistinguishable from a passing suite — the trap this tier removes.
    assert len(ANCHOR_FILES) >= MIN_ANCHORS, (
        f"expected >= {MIN_ANCHORS} recomputation anchor(s), found {len(ANCHOR_FILES)} in {ANCHOR_DIR}"
    )
    classes = {_load_anchor(p)["expected_paralog_buffering_class"] for p in ANCHOR_FILES}
    assert len(classes) >= MIN_DISTINCT_CLASSES, (
        f"anchors must exercise >= {MIN_DISTINCT_CLASSES} class branches; found {sorted(classes)}"
    )


def test_fixture_md5_matches_anchors():
    # Every anchor pins the same source-slice md5; the committed slice must still hash to it, or a
    # re-derivation is running against a different (possibly hand-edited) input than was captured.
    for path in ANCHOR_FILES:
        anchor = _load_anchor(path)
        fixture = HERE / anchor["counts_fixture"]
        md5 = hashlib.md5(fixture.read_bytes()).hexdigest()
        assert md5 == anchor["_source"]["counts_fixture_md5"], f"{path.name}: fixture md5 drift"


def test_panel_is_full_not_truncated():
    # The medians the deltas are built on summarize the WHOLE cell-line panel; a truncated slice would silently
    # change them. Assert the frozen slice still holds the full row count it was captured over.
    fixture = HERE / _load_anchor(ANCHOR_FILES[0])["counts_fixture"]
    _, rows = _read_slice(fixture)
    assert len(rows) >= MIN_MODEL_ROWS, f"slice too small ({len(rows)} model rows) — fixture truncated?"


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_rederives_from_raw_scores(monkeypatch, anchor_path: Path):
    """The pinned class, strongest partner, delta and counts must re-derive from the raw per-cell-line dual-KO
    and single-KO scores via the REAL pipeline — exact float64 reproduction, not a stored echo."""
    anchor = _load_anchor(anchor_path)
    fixture = HERE / anchor["counts_fixture"]
    r = _rederive(monkeypatch, fixture, anchor["target"])
    assert r["paralog_buffering_class"] == anchor["expected_paralog_buffering_class"]
    assert r["strongest_paralog_symbol"] == anchor["expected_strongest_paralog_symbol"]
    assert r["strongest_paralog_delta"] == anchor["expected_strongest_paralog_delta"]
    assert r["n_paralogs_annotated"] == anchor["expected_n_paralogs_annotated"]
    assert r["n_paralogs_functionally_buffering"] == anchor["expected_n_paralogs_functionally_buffering"]


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_agrees_with_roster_snapshot(anchor_path: Path):
    """Where the functional-requirement calibration roster independently recorded this gene's paralog headline
    (class + strongest partner), the anchor's expected values must equal it — two records of the same result
    that must not diverge. Anchors the roster does not cover carry a null cross_ref and are skipped here."""
    anchor = _load_anchor(anchor_path)
    cross = anchor.get("snapshot_cross_ref")
    if cross is None:
        pytest.skip("gene not in the roster paralog headline set")
    assert cross["paralog_buffering_class"] == anchor["expected_paralog_buffering_class"]
    assert cross["strongest_paralog_symbol"] == anchor["expected_strongest_paralog_symbol"]


def test_at_least_one_roster_cross_ref_present():
    # test_agrees_with_roster_snapshot pytest.skips when a gene is not in the roster; guard against ALL of them
    # skipping (which would make that cross-repo assertion vacuously green — the chronos-arc missing-symlink trap).
    assert any(_load_anchor(p).get("snapshot_cross_ref") for p in ANCHOR_FILES), (
        "no anchor carries a roster snapshot_cross_ref — the cross-repo assertion is vacuous"
    )


# ---------------------------------------------------------------------------
# Teeth: the assertions above must FAIL when the input moves. If they don't, the test is comparing a derived
# fixture to itself. Each mutation runs on a COPY of the frozen slice written to tmp_path.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("anchor_path", MEASURED_PARAMS)
def test_teeth_shifting_dual_ko_down_raises_the_delta(monkeypatch, tmp_path, anchor_path: Path):
    """Subtracting a constant from every DUAL-KO score (only) makes each dual KO more lethal, so the buffering
    delta = min(single) - median_dual must rise strictly — proving median_dual is re-reduced live over the frozen
    scores, not echoed. Singles are left untouched (shifting both would cancel in the difference)."""
    anchor = _load_anchor(anchor_path)
    header, rows = _read_slice(HERE / anchor["counts_fixture"])
    pair_cols = [i for i, name in enumerate(header) if i > 0 and _col_kind(name) == "pair"]
    mutated = [list(r) for r in rows]
    for r in mutated:
        for i in pair_cols:
            if i < len(r) and r[i].strip():
                r[i] = repr(float(r[i]) - 2.0)
    out = tmp_path / "shifted.csv"
    _write_csv(out, header, mutated)
    res = _rederive(monkeypatch, out, anchor["target"])
    assert res["strongest_paralog_delta"] > anchor["expected_strongest_paralog_delta"]


@pytest.mark.parametrize("anchor_path", MEASURED_PARAMS)
def test_teeth_truncating_the_panel_moves_the_delta(monkeypatch, tmp_path, anchor_path: Path):
    """Keeping only a handful of cell lines re-medians the pair effect, so the delta must MOVE off the pinned
    value — proving the delta is re-reduced from the frozen rows, not read back from the pin."""
    anchor = _load_anchor(anchor_path)
    header, rows = _read_slice(HERE / anchor["counts_fixture"])
    out = tmp_path / "truncated.csv"
    _write_csv(out, header, rows[:30])
    res = _rederive(monkeypatch, out, anchor["target"])
    assert res["strongest_paralog_delta"] != anchor["expected_strongest_paralog_delta"]


@pytest.mark.parametrize("anchor_path", MEASURED_PARAMS)
def test_teeth_dropping_single_ko_baselines_collapses_the_class(monkeypatch, tmp_path, anchor_path: Path):
    """Removing every single-KO baseline column leaves the delta = min(single) - median_dual undefined (no
    baseline to measure against), so a measured anchor must re-route to data_unavailable — proving the single-KO
    baseline JOIN (not just the dual-KO effect) is load-bearing for the buffering call, the exact quantity the
    2026-09-12 min()-baseline fix corrected."""
    anchor = _load_anchor(anchor_path)
    header, rows = _read_slice(HERE / anchor["counts_fixture"])
    keep = [i for i, name in enumerate(header) if i == 0 or _col_kind(name) != "single"]
    new_header = [header[i] for i in keep]
    new_rows = [[r[i] if i < len(r) else "" for i in keep] for r in rows]
    out = tmp_path / "no_singles.csv"
    _write_csv(out, new_header, new_rows)
    res = _rederive(monkeypatch, out, anchor["target"])
    assert res["paralog_buffering_class"] == "data_unavailable"
    assert res["paralog_buffering_class"] != anchor["expected_paralog_buffering_class"]
