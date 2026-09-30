#!/usr/bin/env python
"""Regenerate `broadly_low_flip_matrix.json` — the #2222 two-arm counterfactual evidence.

Epic claude-oncology-skills#2210 wave 3d, flip-matrix protocol #809 phase 3b. Reference artifact:
`skills/tumor-presence/tests/fixtures/subset_high_live_flip_matrix.json`.

OFFLINE. Every input is a measured artifact ALREADY COMMITTED to this repo:

  * `../recomputation/expression_vectors/*.cellline_rna_distribution.parquet` — per-cell-line
    log2(TPM+1) + resolved OncotreeLineage for 11 curated targets over 2446 DepMap 26q1 models
    (live cbg capture, `../recomputation/capture_expression_anchor.py`). This is the IRREPRODUCIBLE
    raw input; the matrix stores what RE-DERIVES from it, never a value with no source.
  * `../recomputation/anchors/*.tumor_rna_distribution.json` — 10 live-captured tumour fraction
    triples with a COMPLETE (detectable, moderate, high, pattern) input record.
  * `skills/tumor-presence/tests/fixtures/subset_high_live_flip_matrix.json` — 59 live-measured
    (target, indication) tumour reads; `det`/`high`/`pat` are the measured columns.

NOTHING here fabricates or imputes an input to manufacture a flip (protocol rule 2). A row whose
stored inputs cannot decide its arm is listed under an `excluded` key WITH ITS REASON, never dropped
silently — an unexplained shrink in a row count is indistinguishable from a coverage loss.

Run:  pixi run python methods/tests/calibration/threshold_adjudication/regenerate_broadly_low_flip_matrix.py
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import importlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
REC = HERE.parent / "recomputation"
# methods/tests/calibration/threshold_adjudication -> methods/ (the import root) and the repo root.
_METHODS_ROOT = HERE.parents[2]
_REPO_ROOT = _METHODS_ROOT.parent

MODULE_NAMES = {
    "DEP_READ": "methods.depmap_expression_distribution.read",
    "DEP_CLI": "methods.depmap_expression_distribution.cli",
    "TUM_READ": "methods.tcga_gtex_expression_distribution.read",
    "TUM_STATS": "methods.tcga_gtex_expression_distribution.stats",
    "RESOLVE": "methods.expression_properties.resolve",
}


@contextlib.contextmanager
def _worktree_methods_first():
    """Bind `methods.*` to THIS tree for the duration of the block, then restore.

    ⚠️ Why this is not just `sys.path.insert`. `oncology-analysis-methods` is installed EDITABLE,
    and its finder points at the PRIMARY CHECKOUT (`~/rnd-.../methods/methods`), not at the tree the
    test file lives in. `methods/conftest.py` imports `methods._common.live_data_skip` during
    COLLECTION, which binds the `methods` package object — with its `__path__` on the primary
    checkout — into `sys.modules` before any test module executes. From that point a
    `sys.path.insert(0, ...)` is INERT: `import methods.x` is served out of `sys.modules`. So a
    `methods/` test run from a `/tmp` worktree silently exercises TRUNK, and a suite that is green
    on the branch proves nothing about the branch. (CI is unaffected — there the checkout IS the
    primary tree — so this is a LOCAL-GATE blindness, invisible from CI in either direction.)

    Measured 2026-09-30: with this shim removed, six independent mutations of the constants pinned
    in `test_broadly_low_threshold_adjudication.py` ALL SURVIVED at 42/42 green. `_loaded_from()`
    below turns that failure mode into a red instead of a silent pass.
    """
    saved_mods = {k: v for k, v in sys.modules.items() if k == "methods" or k.startswith("methods.")}
    saved_path = list(sys.path)
    for key in saved_mods:
        del sys.modules[key]
    sys.path.insert(0, str(_METHODS_ROOT))
    try:
        yield
    finally:
        for key in [k for k in sys.modules if k == "methods" or k.startswith("methods.")]:
            del sys.modules[key]
        sys.modules.update(saved_mods)
        sys.path[:] = saved_path


with _worktree_methods_first():
    _MODULES = {alias: importlib.import_module(name) for alias, name in MODULE_NAMES.items()}

DEP_READ = _MODULES["DEP_READ"]
DEP_CLI = _MODULES["DEP_CLI"]
TUM_READ = _MODULES["TUM_READ"]
TUM_STATS = _MODULES["TUM_STATS"]
RESOLVE = _MODULES["RESOLVE"]


def _loaded_from() -> dict[str, str]:
    """Alias -> resolved `__file__`. Asserted against THIS tree by the test module."""
    return {alias: mod.__file__ for alias, mod in _MODULES.items()}


SUBSET_HIGH_MATRIX = _REPO_ROOT / "skills/tumor-presence/tests/fixtures/subset_high_live_flip_matrix.json"
OUT = HERE / "broadly_low_flip_matrix.json"

# The two candidate harmonisation bars, i.e. the OTHER sites' cuts. Arm B is always "adopt a
# sibling's bar", never a number invented for this exercise.
SITE3_BAR = 0.10  # depmap cli `lineage_restricted_min_fraction`
SITE1_BAR = 0.30  # tcga_gtex `detectable_fraction < 0.3`


# ---------------------------------------------------------------------------------------------
# The counterfactual ladders. Each is the REAL ladder with EXACTLY ONE rung re-based, and each is
# required (by the test's parity clause) to reproduce the real classifier bit-for-bit in its
# status-quo configuration. Without that parity clause an arm-B number means nothing.
# ---------------------------------------------------------------------------------------------
def stratified_ladder(median, fraction_expressed, low_basis):
    """`depmap_expression_distribution.read._expression_class` with the LOW rung parameterised.

    low_basis ("median", None)  -> the status quo: broadly_low is the fall-through of a median ladder.
    low_basis ("fraction", bar) -> broadly_low only when the stratum's expressed FRACTION is < bar;
                                   otherwise the stratum keeps the next rung up.
    """
    if median is None:
        return "insufficient"
    if median >= DEP_READ._HIGHLY_EXPRESSED:
        return "broadly_high"
    if median >= DEP_READ._EXPRESSED:
        return "broadly_detected"
    kind, bar = low_basis
    if kind == "median":
        return "broadly_low"
    if fraction_expressed is None:
        return "broadly_low"
    return "broadly_low" if fraction_expressed < bar else "broadly_detected"


def tumour_ladder(detectable_fraction, high_fraction, pattern, moderate_fraction, low_bar):
    """`tcga_gtex_expression_distribution.read._classify_tumor_expression` with the broadly_low bar
    parameterised. Every other rung, and the rung ORDER, is copied verbatim — the order is
    load-bearing: the shape rung pre-empts the low bar, so a pair can sit below the bar and still
    never be broadly_low."""
    if detectable_fraction is None:
        return "data_unavailable"
    if high_fraction is not None and high_fraction >= 0.5:
        return "broadly_high"
    if pattern in ("bimodal", "long_tail") and (high_fraction or 0.0) >= 0.1:
        return "subset_high"
    if detectable_fraction >= 0.7:
        if moderate_fraction is None or moderate_fraction >= TUM_READ.BROADLY_DETECTED_MODERATE_FRACTION_MIN:
            return "broadly_detected"
        return "broadly_moderate"
    if detectable_fraction < low_bar:
        return "broadly_low"
    return "broadly_moderate"


# ---------------------------------------------------------------------------------------------
def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001 — provenance is best-effort; never block a regen
        return "unknown"


def _load_vector(path: Path):
    t = pq.read_table(path, columns=["model_id", "log2tpm", "lineage"])
    mids = t.column("model_id").to_pylist()
    log2 = t.column("log2tpm").to_pylist()
    lins = t.column("lineage").to_pylist()
    meta = {m: {"OncotreeLineage": (float("nan") if lin is None else lin)} for m, lin in zip(mids, lins)}
    return dict(zip(mids, log2)), meta, lins, mids


def _target_of(path: Path) -> str:
    return path.name.split("_26q1")[0].upper()


def build_pan_cancer(vectors):
    """Grain P — the pan-cancer DepMap panel. ONE summary dict feeds site 3 (`expression_class`)
    and site 4 (`presence`), and site 2's median ladder can be evaluated on the SAME median, so
    all three cuts are observable on one identical input."""
    rows = []
    for v in vectors:
        tpm, meta, _, _ = _load_vector(v)
        s = DEP_CLI.compute_summary_stats(tpm, meta)
        rows.append(
            {
                "target": _target_of(v),
                "vector_fixture": f"../recomputation/expression_vectors/{v.name}",
                "n_cell_lines": len(tpm),
                "median_log2tpm_panel": s["median_log2tpm_panel"],
                "fraction_expressed": s["fraction_expressed"],
                "fraction_highly_expressed": s["fraction_highly_expressed"],
                "n_lineage_restricted_lineages": s["n_lineage_restricted_lineages"],
                "site3_expression_class": s["expression_class"],
                "site2_median_ladder_class": DEP_READ._expression_class(s["median_log2tpm_panel"]),
                "site4_presence": RESOLVE._presence(s),
            }
        )
    rows.sort(key=lambda r: r["target"])
    site2_low_site3_not = [
        r["target"]
        for r in rows
        if r["site2_median_ladder_class"] == "broadly_low" and r["site3_expression_class"] != "broadly_low"
    ]
    site3_low_site2_not = [
        r["target"]
        for r in rows
        if r["site3_expression_class"] == "broadly_low" and r["site2_median_ladder_class"] != "broadly_low"
    ]
    return {
        "what": "site 2 (median basis) vs site 3 (fraction basis) vs site 4 (presence floor) on the "
        "IDENTICAL committed per-cell-line vector — the cleanest statement of the unit mismatch.",
        "measured": {
            "targets": len(rows),
            "site2_vs_site3_disagreements": sum(
                1 for r in rows if r["site2_median_ladder_class"] != r["site3_expression_class"]
            ),
            "site2_broadly_low_where_site3_is_not": site2_low_site3_not,
            "site3_broadly_low_where_site2_is_not": site3_low_site2_not,
            "site3_low_iff_site4_absent": sum(
                1 for r in rows if (r["site3_expression_class"] == "broadly_low") == (r["site4_presence"] == "absent")
            ),
        },
        "rows": rows,
    }


def build_stratified(vectors):
    """Grain S — site 2's own grain. Every (target, lineage) stratum clearing SUBGROUP_N_FLOOR,
    driven through the REAL `read_stratified_expression` with `_cached_tpm` bound to the committed
    vector (the reader's only I/O). Arm A is therefore the production call, not a re-implementation."""
    n_floor = DEP_READ.SUBGROUP_N_FLOOR
    rows = []
    original = DEP_READ._cached_tpm
    try:
        for v in vectors:
            target = _target_of(v)
            tpm, _meta, lins, mids = _load_vector(v)
            DEP_READ._cached_tpm = lambda _t, _p=None, _tpm=tpm: (_tpm, False)  # noqa: E731
            by: dict[str, set] = {}
            for lin, m in zip(lins, mids):
                if lin is not None:
                    by.setdefault(lin, set()).add(m)
            for lin, members in sorted(by.items()):
                if len(members) < n_floor:
                    continue
                rec = DEP_READ.read_stratified_expression(
                    target, lin, _sample_id_filter=members, _stratum_evaluated=True, release_pin="26q1"
                )
                row = {
                    "target": target,
                    "stratum": lin,
                    "vector_fixture": f"../recomputation/expression_vectors/{v.name}",
                    "subgroup_n": rec["subgroup_n"],
                    "median_log2tpm": rec["median_log2tpm"],
                    "fraction_expressed": rec["fraction_expressed"],
                    "evidence_state": rec["evidence_state"],
                    "A": rec["expression_class"],
                }
                for bar in (SITE3_BAR, SITE1_BAR):
                    row[f"B_{bar:.2f}"] = stratified_ladder(
                        rec["median_log2tpm"], rec["fraction_expressed"], ("fraction", bar)
                    )
                rows.append(row)
    finally:
        DEP_READ._cached_tpm = original
    rows.sort(key=lambda r: (r["target"], r["stratum"]))

    n_low_a = sum(1 for r in rows if r["A"] == "broadly_low")
    arms = {}
    for bar in (SITE3_BAR, SITE1_BAR):
        k = f"B_{bar:.2f}"
        movers = [r for r in rows if r[k] != r["A"]]
        arms[k] = {
            "what": f"adopt the sibling bar `fraction_expressed < {bar:.2f}` for the LOW rung; every "
            f"other rung byte-identical",
            "bar_source": (
                "depmap_expression_distribution.cli lineage_restricted_min_fraction"
                if bar == SITE3_BAR
                else "tcga_gtex_expression_distribution broadly_low bar"
            ),
            "movers": len(movers),
            "byte_identical": len(rows) - len(movers),
            "leave_broadly_low": sum(1 for r in movers if r["A"] == "broadly_low"),
            "enter_broadly_low": sum(1 for r in movers if r[k] == "broadly_low"),
            "mover_ids": [f"{r['target']}/{r['stratum']}" for r in movers],
        }
    return {
        "what": "site 2's own grain: per-(target, lineage) DepMap strata clearing SUBGROUP_N_FLOOR, "
        "arm A = the production median ladder, arm B = the same ladder with ONLY the low rung "
        "re-based on the expressed fraction at a sibling's bar.",
        "n_floor": n_floor,
        "measured": {
            "strata": len(rows),
            "targets": len({r["target"] for r in rows}),
            "lineages": len({r["stratum"] for r in rows}),
            "arm_a_classes": dict(sorted(Counter(r["A"] for r in rows).items())),
            "arm_a_broadly_low": n_low_a,
        },
        "arms": arms,
        "rows": rows,
    }


def build_tumour():
    """Grain T — site 1's grain. Two sub-panels, kept separate because their input records differ
    in completeness:

      `anchors`  10 live-captured pairs with a COMPLETE (det, moderate, high, pattern) record, so
                 re-derivation must reproduce the pinned class exactly.
      `panel`    the 59 pairs of the #809 subset_high live matrix. 34 carry `high: null` — that
                 fixture never captured `high_fraction` for a pair the split did not turn on, and it
                 captured no `moderate_fraction` at all. A null `high` cannot hide a broadly_high in
                 the low band (high_fraction <= detectable_fraction, since the high cutoff is the
                 stricter one) but it CAN hide a subset_high, so a null-high pair inside the band
                 under adjudication is UNDECIDABLE and is excluded BY NAME.
    """
    anchors = []
    for p in sorted((REC / "anchors").glob("*.tumor_rna_distribution.json")):
        a = json.loads(p.read_text())
        inputs = (
            a["expected_detectable_fraction"],
            a["expected_high_fraction"],
            a["expected_distribution_pattern"],
            a["expected_moderate_fraction"],
        )
        row = {
            "target": a["target"],
            "code": a["indication"],
            "anchor": p.name,
            "det": inputs[0],
            "high": inputs[1],
            "pat": inputs[2],
            "mod": inputs[3],
            "pinned_class": a["expected_tumor_expression_class"],
            "A": TUM_READ._classify_tumor_expression(*inputs),
        }
        row[f"B_{SITE3_BAR:.2f}"] = tumour_ladder(*inputs, low_bar=SITE3_BAR)
        anchors.append(row)

    fm = json.loads(SUBSET_HIGH_MATRIX.read_text())
    panel, excluded = [], []
    for p in fm["pairs"]:
        det, high, pat = p.get("det"), p.get("high"), p.get("pat")
        a = TUM_READ._classify_tumor_expression(det, high, pat)
        in_band = det is not None and det < 0.7
        if in_band and high is None:
            excluded.append(
                {
                    "target": p["target"],
                    "code": p["code"],
                    "det": det,
                    "reason": "high_fraction not captured; the shape rung that pre-empts the "
                    "low bar is undecidable from the stored record",
                }
            )
            continue
        row = {
            "target": p["target"],
            "code": p["code"],
            "det": det,
            "high": high,
            "pat": pat,
            "live_measured_class": p["cls"],
            "A": a,
        }
        row[f"B_{SITE3_BAR:.2f}"] = tumour_ladder(det, high, pat, None, low_bar=SITE3_BAR)
        panel.append(row)
    panel.sort(key=lambda r: (r["det"] if r["det"] is not None else -1.0, r["target"]))

    k = f"B_{SITE3_BAR:.2f}"
    movers = [r for r in panel + anchors if r[k] != r["A"]]
    return {
        "what": "site 1's grain: tumour-patient (target, indication) reads. Arm B adopts the "
        f"cell-line sibling's bar (detectable_fraction < {SITE3_BAR:.2f}).",
        "measured": {
            "anchors": len(anchors),
            "anchors_reproducing_their_pinned_class": sum(1 for r in anchors if r["A"] == r["pinned_class"]),
            "panel_pairs": len(panel),
            "panel_pairs_excluded": len(excluded),
            "rows_in_the_det_lt_0_7_band": sum(1 for r in panel if r["det"] is not None and r["det"] < 0.7),
            "arm_a_broadly_low": sum(1 for r in panel + anchors if r["A"] == "broadly_low"),
            "movers": len(movers),
            "mover_ids": [f"{r['target']}/{r['code']}" for r in movers],
            "byte_identical": len(panel) + len(anchors) - len(movers),
            "high_fraction_never_exceeds_detectable_fraction": all(
                p["high"] <= p["det"] + 1e-12
                for p in fm["pairs"]
                if p.get("high") is not None and p.get("det") is not None
            ),
        },
        "excluded": excluded,
        "anchors": anchors,
        "panel": panel,
    }


def main() -> int:
    vectors = sorted((REC / "expression_vectors").glob("*.cellline_rna_distribution.parquet"))
    if not vectors:
        raise SystemExit(f"no committed expression vectors under {REC / 'expression_vectors'}")

    doc = {
        "_meta": {
            "what": "Two-arm counterfactual for the `broadly_low` cut (claude-oncology-skills#2222, "
            "epic #2210 wave 3d), under the #809 phase-3b flip-matrix protocol.",
            "verdict": "DOCUMENTED-INTENTIONAL for the NUMBERS; one REAL divergence isolated in the BASIS. "
            "No threshold moved. See `adjudication`.",
            "ground_truth": "MEASURED: the per-cell-line log2(TPM+1) vectors, the tumour anchor fraction "
            "triples, and the subset_high matrix's det/high/pat columns. DERIVED and "
            "re-derived by the test rather than trusted: every median, fraction, arm-A "
            "class and arm-B class in this file. Arm A is the PRODUCTION call "
            "(read_stratified_expression / _classify_tumor_expression / "
            "compute_summary_stats), not a re-implementation; the counterfactual ladders "
            "are required to reproduce it bit-for-bit in their status-quo configuration.",
            "offline": "No S3, no credentials. Every input is a committed artifact of this repo.",
            "regenerated_by": "methods/tests/calibration/threshold_adjudication/regenerate_broadly_low_flip_matrix.py",
            "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "repo_sha": _git_sha(),
            "release_pin": "26q1 (cell line) / recount3 TCGA slice (tumour)",
            "line_numbers_are_informational": "The `sites` entries carry a `source` path but NO pinned "
            "line number: the test pins each cut BEHAVIOURALLY by "
            "driving the real classifier across it, so a moved line "
            "never reds and a moved CONSTANT always does.",
        },
        "sites": SITES(),
        "adjudication": ADJUDICATION(),
        "grain_pan_cancer": build_pan_cancer(vectors),
        "grain_stratified": build_stratified(vectors),
        "grain_tumour": build_tumour(),
    }
    OUT.write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n")
    print(f"wrote {OUT}")
    print("  pan-cancer targets :", doc["grain_pan_cancer"]["measured"]["targets"])
    print("  stratified strata  :", doc["grain_stratified"]["measured"]["strata"])
    for k, v in doc["grain_stratified"]["arms"].items():
        print(f"    {k}: movers={v['movers']} leave_low={v['leave_broadly_low']} enter_low={v['enter_broadly_low']}")
    print("  tumour anchors     :", doc["grain_tumour"]["measured"]["anchors"])
    print(
        "  tumour panel pairs :",
        doc["grain_tumour"]["measured"]["panel_pairs"],
        "excluded:",
        doc["grain_tumour"]["measured"]["panel_pairs_excluded"],
    )
    return 0


def SITES() -> list[dict]:
    """The four sites the issue names, each with the QUANTITY IT CUTS. Establishing the quantity
    BEFORE comparing numbers is the whole method here: sibling #2220 was closed as a non-divergence
    precisely because two constants both spelled `0.3`/`0.30` turned out to cut different things."""
    import inspect

    sig = inspect.signature(DEP_CLI._classify_expression).parameters
    summary_sig = inspect.signature(DEP_CLI.compute_summary_stats).parameters
    return [
        {
            "site_id": "site1_tumour_detectable_fraction",
            "source": "methods/methods/tcga_gtex_expression_distribution/read.py::_classify_tumor_expression",
            "token": "broadly_low",
            "constant": 0.3,
            "constant_form": "inline literal (no module-level name)",
            "quantity": "detectable_fraction",
            "unit": "fraction of samples with log2(TPM+1) >= DETECTABLE_LOG2TPM",
            "detection_floor_log2tpm": TUM_STATS.DETECTABLE_LOG2TPM,
            "denominator": "the tumour patients of ONE indication (recount3 TCGA slice)",
            "predicate": "detectable_fraction < 0.3   (STRICT `<`)",
            "ladder_position": "a GUARDED branch, 5th of 6; the fall-through is broadly_moderate. The "
            "shape rung (bimodal|long_tail AND high_fraction >= 0.1 -> subset_high) "
            "PRE-EMPTS it, so a pair below 0.3 need not be broadly_low.",
            "correction": "issue #2220's closing record transcribed this as `detectable_fraction <= 0.3` "
            "at read.py:927. The operator is STRICT `<`, so detectable_fraction == 0.3 "
            "reads broadly_moderate, not broadly_low. Pinned behaviourally below.",
        },
        {
            "site_id": "site2_cellline_stratum_median",
            "source": "methods/methods/depmap_expression_distribution/read.py::_expression_class",
            "token": "broadly_low",
            "constant": DEP_READ._EXPRESSED,
            "constant_form": "module constant `_EXPRESSED`",
            "quantity": "median_log2tpm of the stratum",
            "unit": "log2(TPM+1) LEVEL — not a fraction",
            "denominator": "one (lineage | driver | molecular-subtype) stratum of DepMap cell lines",
            "predicate": "median_log2tpm < _EXPRESSED (= 1.0)",
            "ladder_position": "the TRUE fall-through of a 3-rung median ladder "
            "{broadly_high, broadly_detected, broadly_low} + insufficient. "
            "The card declares exactly these 4 tokens for per_subgroup_metrics.class, "
            "so there is no middle token to land in.",
            "note": "The reader COMPUTES and EMITS `fraction_expressed` on the same record (and the card "
            "declares it) but does not feed it to the classifier.",
        },
        {
            "site_id": "site3_cellline_pancancer_fraction",
            "source": "methods/methods/depmap_expression_distribution/cli.py::_classify_expression",
            "token": "broadly_low",
            "constant": sig["lineage_restricted_min_fraction"].default,
            "constant_form": "keyword default `lineage_restricted_min_fraction`",
            "quantity": "fraction_expressed",
            "unit": "fraction of samples with log2(TPM+1) >= expressed_threshold",
            "detection_floor_log2tpm": summary_sig["expressed_threshold"].default,
            "denominator": "the WHOLE pan-cancer DepMap panel, every lineage (2446 models at 26q1)",
            "predicate": "frac_expressed < lineage_restricted_min_fraction (= 0.10)",
            "ladder_position": "a GUARDED branch, 3rd of 4. It is NOT a free knob: it is the LOWER EDGE "
            "of the lineage_restricted band [0.10, 0.70]. Raising it does not add rows "
            "to broadly_low from the fall-through — it TAKES them from "
            "lineage_restricted.",
            "dead_fall_through": "the final `return broadly_moderate`, commented '70-90% range fallback', "
            "is unreachable for any frac_expressed in [0, 1] (the >= 0.70 branch "
            "already claims that band). It is reachable ONLY for a NaN fraction, "
            "which would launder an unmeasured panel into a measured middling call — "
            "INERT today because the sole caller returns early on an empty panel. "
            "Recorded as a finding, not fixed here.",
        },
        {
            "site_id": "site4_expression_property_presence_floor",
            "source": "methods/methods/expression_properties/resolve.py::_presence",
            "token": "presence=absent   (NOT broadly_low)",
            "constant": RESOLVE._PRESENCE_FLOOR_FRACTION,
            "constant_form": "module constant `_PRESENCE_FLOOR_FRACTION`",
            "quantity": "fraction_expressed",
            "unit": "fraction of samples with log2(TPM+1) >= _EXPRESSED_LOG2TPM",
            "denominator": "the same pan-cancer DepMap summary dict site 3 reads",
            "predicate": "fraction_expressed < 0.10 AND median < _EXPRESSED_LOG2TPM",
            "ladder_position": "a different VOCABULARY (expression_property `presence`), not a rung of "
            "expression_class. It is not a twin of broadly_low.",
            "note": "This 0.10 and site 3's 0.10 are ONE bar on ONE quantity over ONE panel, by design "
            "(resolve.py's header says it mirrors the cli knobs). Measured to agree on 11/11 "
            "committed anchors. A CONVERGENCE, not a divergence.",
        },
        {
            "site_id": "not_a_broadly_low_cut__broadly_high_fraction",
            "source": "methods/methods/depmap_expression_distribution/cli.py::_classify_expression",
            "token": "broadly_high",
            "constant": sig["broadly_high_fraction"].default,
            "quantity": "fraction_highly_expressed",
            "unit": "fraction of samples with log2(TPM+1) >= highly_expressed_threshold",
            "why_listed": "This is the only `0.30` in the four scoped files' classifier code, and it sits "
            "THREE LINES above the `lineage_restricted_min_fraction: float = 0.10` in the "
            "SAME defaults block. It is the origin of the issue title's third number. Its "
            "polarity is OPPOSITE: it promotes to broadly_high. Pinned by construction below.",
        },
        {
            "site_id": "not_a_broadly_low_cut__presence_supported_median_fraction",
            "source": "methods/methods/expression_properties/resolve.py",
            "token": "presence=supported",
            "constant": RESOLVE._PRESENCE_SUPPORTED_MEDIAN_FRACTION,
            "quantity": "fraction_expressed (conditional on an expressing median)",
            "why_listed": "the only other `0.30` in the scoped files; also OPPOSITE polarity — it RESCUES "
            "a subset-level fraction UP to `supported`.",
        },
    ]


def ADJUDICATION() -> dict:
    return {
        "protocol": "#809 phase 3b flip matrix; arc policy document-all / adjudicate-flagged.",
        "outcome": "DOCUMENTED-INTENTIONAL — no threshold changed.",
        "finding_1_the_title_s_triple_is_not_three_settings_of_one_bar": (
            "Exhaustive grep of the four scoped files: the only `broadly_low` cuts are site 1's 0.3 "
            "(a within-indication tumour fraction) and site 3's 0.10 (a pan-cancer cell-line fraction). "
            "There is NO third `broadly_low` number. The title's `0.30` is `broadly_high_fraction=0.30` "
            "(or `_PRESENCE_SUPPORTED_MEDIAN_FRACTION=0.30`) — both OPPOSITE in polarity, and the former "
            "sits three lines above the 0.10 in the same defaults block. The title's `0.10` "
            "(`_PRESENCE_FLOOR_FRACTION`) governs `presence=absent` in a DIFFERENT vocabulary and is "
            "measured to AGREE with site 3 on 11/11 anchors. Second instance of exactly the error that "
            "closed #2220."
        ),
        "finding_2_0_3_vs_0_10_is_commensurable_and_the_spread_is_required": (
            "Same unit, same detection floor (log2(TPM+1) >= 1.0 on both arms), DIFFERENT denominator: "
            "one indication's patients vs 2446 cell lines spanning every lineage. Both harmonisations "
            "are refuted by the measured arms. Harmonising site 1 DOWN to 0.10 empties the tumour "
            "panel's broadly_low class (3 of 3 leave), promoting TERT/SKCM at det=0.117 to "
            "broadly_moderate. Harmonising site 3 UP to 0.30 does not fill broadly_low from the "
            "fall-through — it eats the lineage_restricted band from below, re-labelling CEACAM5 "
            "(pan-cancer fraction 0.2625, with an enriched lineage) from lineage_restricted to "
            "broadly_low. A pan-cancer panel DILUTES a lineage-restricted target, so its minority floor "
            "must sit BELOW a within-indication one and the band above it is where lineage restriction "
            "is expressed; the tumour arm has no lineage_restricted token because within one indication "
            "the concept is vacuous. NO CHANGE."
        ),
        "finding_3_the_unit_mismatch_is_real_but_RESOLVABLE_and_the_divergence_is_0_5_vs_0_3_vs_0_10": (
            "The median floor is not incommensurable with a fraction — it has an EXACT fraction "
            "equivalent. By the definition of the median, fraction_expressed > 0.5 forces both central "
            "order statistics above the floor, hence median >= floor; so site 2's broadly_low can fire "
            "ONLY when fraction_expressed <= 0.5, and can fire ANYWHERE in (0, 0.5]. Converted, the "
            "three bars are 0.5 (site 2) / 0.3 (site 1) / 0.10 (site 3) — a 5x spread in ONE unit, with "
            "the DESCRIPTIVE per-stratum arm carrying the MOST GENEROUS bar. Measured on 220 real strata: "
            "0 counter-examples to the bound in either direction, and re-basing site 2's low rung on the "
            "expressed fraction moves strata in ONE direction only (0 ever ENTER broadly_low)."
        ),
        "finding_4_what_that_costs_on_measured_data": (
            "109 of 220 strata read broadly_low today. 31 of those (14.1% of the panel) have "
            "fraction_expressed >= 0.10 and 14 have >= 0.30 — up to 0.476 (CEACAM5 / Lung, n=250: 48% of "
            "lung cell lines express CEACAM5 above the detection floor and the stratum is called "
            "broadly_low). On the identical pan-cancer vector the median ladder calls CEACAM5, MSLN and "
            "TACSTD2 broadly_low where the fraction ladder calls them lineage_restricted — i.e. it "
            "converts a positive, patient-selection-relevant signal into the lowest tier. broadly_low is "
            "site 2's TRUE fall-through, so the basis puts the LEAST-evidenced label at the MOST "
            "reachable position — the wrong direction for a fall-through."
        ),
        "why_no_change_here": (
            "Site 2's defect is a change of BASIS, not a threshold move, so the flip-matrix protocol "
            "('change the threshold only if the matrix supports it') does not authorise it. Re-basing "
            "needs a home for a stratum at fraction 0.45 / median 0.4, and honestly that is neither "
            "broadly_low nor broadly_detected but a SUBSET token this card deliberately does not declare "
            "(cellline-rna-distribution-by-subtype declares exactly 4 tokens for "
            "per_subgroup_metrics.class). Adding one is a cards/ vocabulary change — blast radius, and "
            "out of this issue's additive-only scope. The card's OWN precedent (2026-09-18, the "
            "subtype_enrich_log2_delta divergence: 1.0 here vs 0.585 on the tumour arm) chose to EMIT the "
            "applied cut rather than align the constants, explicitly because aligning would silently move "
            "every live stratum between the two values. That is the same shape of problem and the same "
            "answer. Routed up as a follow-up rather than guessed at here."
        ),
        "catalog_write_deferred": (
            "The protocol's step 7 (property_catalog `calibration.last_flip_matrix` + `rationale`) is NOT "
            "written by this PR: #2221 owns rationale writes to contracts/vocabularies/property_catalog* "
            "for this wave and racing it would conflict. Filed as a follow-up; this file is the evidence "
            "the catalog entry will cite."
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
