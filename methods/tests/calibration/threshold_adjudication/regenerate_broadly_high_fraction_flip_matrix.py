#!/usr/bin/env python
"""Regenerate `broadly_high_fraction_flip_matrix.json` — the #2273 counterfactual evidence.

Epic claude-oncology-skills#2210, flip-matrix protocol #809 phase 3b. Sibling of
`regenerate_broadly_low_flip_matrix.py` (#2222) and `../high_anchor_flip_matrix/regenerate.py`
(#2221); this one adjudicates the `broadly_high_fraction` cut the issue title spells three ways.

THE QUANTITY, established BEFORE any number is compared (this is the whole method — #2220 was closed
as a NON-divergence precisely because two `0.3`s cut different things):

  * site A  `depmap_expression_distribution/cli.py::_classify_expression` `broadly_high_fraction`
            = 0.30. Cuts `fraction_highly_expressed` (fraction of the panel with log2(TPM+1) >= 5.0),
            over the WHOLE pan-cancer DepMap panel. GUARDED: it only decides broadly_high vs
            broadly_moderate INSIDE the `frac_expressed >= 0.70` band.
  * site B  `expression_properties/resolve.py::_BROADLY_HIGH_FRACTION_MIN` = 0.50. Cuts the
            IDENTICAL `fraction_highly_expressed` field, on the IDENTICAL summary dict site A
            produces (same panel, same 5.0 floor). UNGUARDED: `_prevalence`'s first rung
            (`fh >= 0.5 -> broad`), and one of three OR-conditions in `_magnitude` (`fh >= 0.5 ->
            high`).
  * site C  `tcga_gtex_expression_distribution/read.py::_classify_tumor_expression` inline `0.5`.
            Cuts `high_fraction` — the SAME concept, but a DIFFERENT denominator (one indication's
            tumour patients, not a pan-cancer panel) and a DIFFERENT high floor
            (`HIGH_LOG2TPM = 5.6724`, the #2221 anchor divergence). UNGUARDED first rung.

So A and B are a REAL same-quantity, same-panel, same-floor divergence (0.30 vs 0.50). C is the same
quantity on another panel and another floor. All three feed a `broadly_high`/`broad` word.

OUTCOME: DOCUMENTED-INTENTIONAL, no threshold moved. See `adjudication`.

OFFLINE. Every input is a measured artifact ALREADY COMMITTED to this repo (identical fixture set to
the #2222 sibling):
  * `../recomputation/expression_vectors/*.cellline_rna_distribution.parquet` — per-cell-line
    log2(TPM+1) + resolved OncotreeLineage for curated targets over DepMap 26q1 models. The
    IRREPRODUCIBLE raw input; the matrix stores what RE-DERIVES from it, never a value with no source.
  * `../recomputation/anchors/*.tumor_rna_distribution.json` — live-captured tumour fraction triples
    with a COMPLETE (detectable, moderate, high, pattern) input record.
  * `skills/tumor-presence/tests/fixtures/subset_high_live_flip_matrix.json` — 59 live-measured
    tumour reads; `det`/`high`/`pat` are the measured columns.

NOTHING here fabricates an input to manufacture a flip (protocol rule 2). A row whose stored inputs
cannot decide its arm is listed under `excluded` WITH ITS REASON, never dropped silently.

Run:  pixi run python methods/tests/calibration/threshold_adjudication/regenerate_broadly_high_fraction_flip_matrix.py
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
REC = HERE.parent / "recomputation"
# methods/tests/calibration/threshold_adjudication -> methods/ (the import root) and the repo root.
_METHODS_ROOT = HERE.parents[2]
_REPO_ROOT = _METHODS_ROOT.parent

MODULE_NAMES = {
    "DEP_READ": "onc_methods.depmap_expression_distribution.read",
    "DEP_CLI": "onc_methods.depmap_expression_distribution.cli",
    "TUM_READ": "onc_methods.tcga_gtex_expression_distribution.read",
    "TUM_STATS": "onc_methods.tcga_gtex_expression_distribution.stats",
    "RESOLVE": "onc_methods.expression_properties.resolve",
}


@contextlib.contextmanager
def _worktree_methods_first():
    """Bind `onc_methods.*` to THIS tree for the duration of the block, then restore.

    ⚠️ Why this is not just `sys.path.insert`. `oncology-analysis-methods` is installed EDITABLE and
    its finder points at the PRIMARY CHECKOUT; `methods/conftest.py` imports
    `onc_methods._common.live_data_skip` during COLLECTION, binding the `onc_methods` package object (with
    `__path__` on the primary checkout) into `sys.modules` before any test module runs. From that
    point `sys.path.insert(0, ...)` is INERT: `import onc_methods.x` is served out of `sys.modules`. So a
    `methods/` test run from a `/tmp` worktree silently exercises TRUNK. This shim (copied verbatim
    from the #2222 sibling, where its removal let six independent constant mutations ALL survive at
    green) makes `_loaded_from()` a red instead of a silent pass.
    """
    saved_mods = {k: v for k, v in sys.modules.items() if k == "onc_methods" or k.startswith("onc_methods.")}
    saved_path = list(sys.path)
    for key in saved_mods:
        del sys.modules[key]
    sys.path.insert(0, str(_METHODS_ROOT))
    try:
        yield
    finally:
        for key in [k for k in sys.modules if k == "onc_methods" or k.startswith("onc_methods.")]:
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
OUT = HERE / "broadly_high_fraction_flip_matrix.json"

# The site-A default and the two candidate harmonisation bars. Arm B is always "adopt a sibling's
# bar", never a number invented for this exercise.
SITE_A_BAR = 0.30  # depmap cli `broadly_high_fraction`
SITE_BC_BAR = 0.50  # resolve `_BROADLY_HIGH_FRACTION_MIN` and the tumour twin's inline 0.5


# ---------------------------------------------------------------------------------------------
# Counterfactual ladders. Each is the REAL classifier with EXACTLY ONE bar re-based, and each is
# required (by the test's parity clause) to reproduce production bit-for-bit at its status-quo bar.
# ---------------------------------------------------------------------------------------------
# Site A's classifier ALREADY takes `broadly_high_fraction` as a keyword, so its counterfactual is a
# direct call to the production function with a different bar — no re-implementation, parity is exact.
def cellline_class(fe, fh, n_lin, broadly_high_fraction):
    """`_classify_expression` with the status-quo of every OTHER knob (compute_summary_stats
    defaults) and `broadly_high_fraction` parameterised."""
    return DEP_CLI._classify_expression(fe, fh, n_lin, 0.70, broadly_high_fraction, 0.10, 0.70)


def resolve_prevalence(summary, bar):
    """Copy of `resolve._prevalence` with the broadly_high fraction bar parameterised; every other
    rung and the rung ORDER copied verbatim (the order is load-bearing — the broad rung pre-empts the
    subset rungs)."""
    fe = summary.get("fraction_expressed")
    fh = summary.get("fraction_highly_expressed")
    pattern = summary.get("distribution_pattern")
    if fe is None and fh is None:
        return "unmeasured"
    fe0 = fe if fe is not None else 0.0
    fh0 = fh if fh is not None else 0.0
    if fh is not None and fh0 >= bar:
        return "broad"
    if pattern in RESOLVE._BIMODAL_PATTERNS and fh0 >= RESOLVE._SUBSET_HIGH_FRACTION_MIN:
        return "subset"
    if fe is not None and fe0 >= RESOLVE._BROAD_EXPRESSED_FRACTION:
        return "broad"
    if fe is not None and fe0 < RESOLVE._RARE_FRACTION:
        return "rare"
    if fh is not None and fh0 >= RESOLVE._SUBSTANTIAL_SUBSET_HIGH_FRACTION:
        return "subset"
    return "subset"


def resolve_magnitude(summary, presence_value, bar):
    """Copy of `resolve._magnitude` with the broadly_high fraction bar (one of three OR-conditions
    for `high`) parameterised."""
    if presence_value == "absent":
        return "unmeasured"
    med = summary.get("median_log2tpm_panel")
    pct = summary.get("control_target_percentile")
    if pct is None:
        pct = summary.get("allgene_percentile")
    fh = summary.get("fraction_highly_expressed")
    if med is None and pct is None:
        return "unmeasured"
    if (
        (pct is not None and pct >= RESOLVE._MAGNITUDE_HIGH_PERCENTILE)
        or (med is not None and med >= RESOLVE._HIGHLY_EXPRESSED_LOG2TPM)
        or (fh is not None and fh >= bar)
    ):
        return "high"
    if (pct is not None and pct >= RESOLVE._MAGNITUDE_MODERATE_PERCENTILE) or (
        med is not None and med >= RESOLVE._EXPRESSED_LOG2TPM
    ):
        return "moderate"
    return "low"


def tumour_high_ladder(detectable_fraction, high_fraction, pattern, moderate_fraction, high_bar):
    """`_classify_tumor_expression` with ONLY the broadly_high bar parameterised. Every other rung,
    and the rung ORDER, copied verbatim."""
    if detectable_fraction is None:
        return "data_unavailable"
    if high_fraction is not None and high_fraction >= high_bar:
        return "broadly_high"
    if pattern in ("bimodal", "long_tail") and (high_fraction or 0.0) >= 0.1:
        return "subset_high"
    if detectable_fraction >= 0.7:
        if moderate_fraction is None or moderate_fraction >= TUM_READ.BROADLY_DETECTED_MODERATE_FRACTION_MIN:
            return "broadly_detected"
        return "broadly_moderate"
    if detectable_fraction < 0.3:
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
    """Grain P — the pan-cancer DepMap panel. ONE summary dict feeds site A (`expression_class`) and
    site B (`_magnitude`/`_prevalence`) on the IDENTICAL `fraction_highly_expressed` — the cleanest
    statement that the 0.30 and the 0.50 cut the SAME quantity."""
    rows = []
    for v in vectors:
        tpm, meta, _, _ = _load_vector(v)
        s = DEP_CLI.compute_summary_stats(tpm, meta)
        presence = RESOLVE._presence(s)
        rows.append(
            {
                "target": _target_of(v),
                "vector_fixture": f"../recomputation/expression_vectors/{v.name}",
                "n_cell_lines": len(tpm),
                "median_log2tpm_panel": s["median_log2tpm_panel"],
                "fraction_expressed": s["fraction_expressed"],
                "fraction_highly_expressed": s["fraction_highly_expressed"],
                "n_lineage_restricted_lineages": s["n_lineage_restricted_lineages"],
                # site A, production + counterfactual at the sibling bar 0.50.
                "siteA_expression_class": s["expression_class"],
                "siteA_at_0_50": cellline_class(
                    s["fraction_expressed"],
                    s["fraction_highly_expressed"],
                    s["n_lineage_restricted_lineages"],
                    SITE_BC_BAR,
                ),
                # site B, production (bar 0.50) + counterfactual at the sibling bar 0.30.
                "siteB_presence": presence,
                "siteB_magnitude": resolve_magnitude(s, presence, SITE_BC_BAR),
                "siteB_prevalence": resolve_prevalence(s, SITE_BC_BAR),
                "siteB_magnitude_at_0_30": resolve_magnitude(s, presence, SITE_A_BAR),
                "siteB_prevalence_at_0_30": resolve_prevalence(s, SITE_A_BAR),
            }
        )
    rows.sort(key=lambda r: r["target"])

    siteA_movers = [r for r in rows if r["siteA_at_0_50"] != r["siteA_expression_class"]]
    siteB_prev_movers = [r for r in rows if r["siteB_prevalence_at_0_30"] != r["siteB_prevalence"]]
    siteB_mag_movers = [r for r in rows if r["siteB_magnitude_at_0_30"] != r["siteB_magnitude"]]
    # Structural, not numeric: at the SAME 0.50 bar, does site A's guarded broadly_high agree with
    # site B's unguarded prevalence=broad? Count where they disagree in DIRECTION (one says the top
    # word, the other does not).
    same_bar_disagree = [
        r["target"] for r in rows if (r["siteA_at_0_50"] == "broadly_high") != (r["siteB_prevalence"] == "broad")
    ]
    return {
        "what": "site A (guarded cell-line expression_class) vs site B (unguarded expression_property "
        "magnitude/prevalence) on the IDENTICAL committed per-cell-line vector, reading the SAME "
        "`fraction_highly_expressed` field. Establishes the same-quantity claim and measures both "
        "harmonisation directions on the pan-cancer grain.",
        "measured": {
            "targets": len(rows),
            "siteA_broadly_high_today": sum(1 for r in rows if r["siteA_expression_class"] == "broadly_high"),
            "siteA_movers_up_to_0_50": len(siteA_movers),
            "siteA_mover_ids": [
                f"{r['target']}:{r['siteA_expression_class']}->{r['siteA_at_0_50']}" for r in siteA_movers
            ],
            "siteB_prevalence_broad_today": sum(1 for r in rows if r["siteB_prevalence"] == "broad"),
            "siteB_prevalence_movers_down_to_0_30": len(siteB_prev_movers),
            "siteB_prevalence_mover_ids": [
                f"{r['target']}:{r['siteB_prevalence']}->{r['siteB_prevalence_at_0_30']}" for r in siteB_prev_movers
            ],
            "siteB_magnitude_movers_down_to_0_30": len(siteB_mag_movers),
            "siteB_magnitude_mover_ids": [
                f"{r['target']}:{r['siteB_magnitude']}->{r['siteB_magnitude_at_0_30']}" for r in siteB_mag_movers
            ],
            "targets_where_guarded_A_and_unguarded_B_disagree_at_the_same_0_50_bar": same_bar_disagree,
        },
        "rows": rows,
    }


def build_tumour():
    """Grain T — site C's grain. Two sub-panels (identical construction to the #2222 sibling):

      `anchors`  live-captured pairs with a COMPLETE (det, moderate, high, pattern) record, so
                 re-derivation must reproduce the pinned class exactly.
      `panel`    the pairs of the #809 subset_high live matrix. Some carry `high: null`; a pair whose
                 stored record cannot decide the broadly_high rung is EXCLUDED BY NAME.

    Arm B lowers site C's bar to the cell-line sibling's 0.30 — the FORBIDDEN direction (it moves
    tumour classes and so needs the tumour-presence golden, owned by #2061 / #1984 PR-B). Measured as
    a COST, never applied."""
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
            "B_0.30": tumour_high_ladder(*inputs, high_bar=SITE_A_BAR),
        }
        anchors.append(row)

    fm = json.loads(SUBSET_HIGH_MATRIX.read_text())
    panel, excluded = [], []
    for p in fm["pairs"]:
        det, high, pat = p.get("det"), p.get("high"), p.get("pat")
        # The broadly_high rung reads `high_fraction`. A null high cannot decide it, so a pair with a
        # null high is UNDECIDABLE for this adjudication and excluded by name.
        if high is None:
            excluded.append(
                {
                    "target": p["target"],
                    "code": p["code"],
                    "det": det,
                    "reason": "high_fraction not captured; the broadly_high rung this adjudication "
                    "turns on is undecidable from the stored record",
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
            "A": TUM_READ._classify_tumor_expression(det, high, pat),
            "B_0.30": tumour_high_ladder(det, high, pat, None, high_bar=SITE_A_BAR),
        }
        panel.append(row)
    panel.sort(key=lambda r: (r["high"] if r["high"] is not None else -1.0, r["target"]))

    movers = [r for r in panel + anchors if r["B_0.30"] != r["A"]]
    return {
        "what": "site C's grain: tumour-patient (target, indication) reads. Arm B lowers site C's "
        f"broadly_high bar to the cell-line sibling's {SITE_A_BAR:.2f} — the FORBIDDEN direction "
        "(moves tumour classes -> needs the tumour-presence golden). Measured, not applied.",
        "measured": {
            "anchors": len(anchors),
            "anchors_reproducing_their_pinned_class": sum(1 for r in anchors if r["A"] == r["pinned_class"]),
            "panel_pairs": len(panel),
            "panel_pairs_excluded": len(excluded),
            "arm_a_broadly_high": sum(1 for r in panel + anchors if r["A"] == "broadly_high"),
            "movers_down_to_0_30": len(movers),
            "mover_ids": [f"{r['target']}/{r['code']}:{r['A']}->{r['B_0.30']}" for r in movers],
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
            "what": "Counterfactual for the `broadly_high_fraction` cut (claude-oncology-skills#2273, "
            "epic #2210), under the #809 phase-3b flip-matrix protocol. Sibling of #2222 "
            "(broadly_low) and #2221 (the high anchor).",
            "verdict": "DOCUMENTED-INTENTIONAL. No threshold moved. Two of the three harmonisation "
            "directions touch the FORBIDDEN tumour-presence golden; the third reverses a "
            "deliberate documented arm-mirror and is an owner call. See `adjudication`.",
            "ground_truth": "MEASURED: the per-cell-line log2(TPM+1) vectors and the tumour anchor "
            "fraction triples. DERIVED and re-derived by the test rather than trusted: "
            "every summary scalar, arm-A class and arm-B class. Arm A is the PRODUCTION "
            "call (compute_summary_stats / _classify_expression / _classify_tumor_expression "
            "/ resolve._magnitude / resolve._prevalence); the counterfactual ladders are "
            "required to reproduce it bit-for-bit at their status-quo bar.",
            "offline": "No S3, no credentials. Every input is a committed artifact of this repo.",
            "regenerated_by": "methods/tests/calibration/threshold_adjudication/regenerate_broadly_high_fraction_flip_matrix.py",
            "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "repo_sha": _git_sha(),
            "release_pin": "26q1 (cell line) / recount3 TCGA slice (tumour)",
            "line_numbers_are_informational": "The `sites` entries carry a `source` path but no pinned "
            "line number: the test pins each cut BEHAVIOURALLY by driving the real "
            "classifier across it, so a moved line never reds and a moved CONSTANT always does.",
        },
        "sites": SITES(),
        "adjudication": ADJUDICATION(),
        "grain_pan_cancer": build_pan_cancer(vectors),
        "grain_tumour": build_tumour(),
    }
    OUT.write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n")
    print(f"wrote {OUT}")
    m = doc["grain_pan_cancer"]["measured"]
    print("  pan-cancer targets            :", m["targets"])
    print("  siteA broadly_high today      :", m["siteA_broadly_high_today"])
    print("  siteA movers up to 0.50       :", m["siteA_movers_up_to_0_50"], m["siteA_mover_ids"])
    print("  siteB prevalence broad today  :", m["siteB_prevalence_broad_today"])
    print(
        "  siteB prevalence movers to 0.30:", m["siteB_prevalence_movers_down_to_0_30"], m["siteB_prevalence_mover_ids"]
    )
    print(
        "  siteB magnitude movers to 0.30 :", m["siteB_magnitude_movers_down_to_0_30"], m["siteB_magnitude_mover_ids"]
    )
    print(
        "  A/B disagree at same 0.50 bar :", m["targets_where_guarded_A_and_unguarded_B_disagree_at_the_same_0_50_bar"]
    )
    t = doc["grain_tumour"]["measured"]
    print(
        "  tumour anchors / panel        :", t["anchors"], "/", t["panel_pairs"], "excluded:", t["panel_pairs_excluded"]
    )
    print("  tumour movers down to 0.30    :", t["movers_down_to_0_30"], t["mover_ids"])
    return 0


def SITES() -> list[dict]:
    """The three sites the issue names, each with the QUANTITY IT CUTS. Establishing the quantity
    BEFORE comparing numbers is the whole method — sibling #2220 was closed as a non-divergence
    because two constants that both spelled `0.3` cut different things."""
    import inspect

    sig = inspect.signature(DEP_CLI._classify_expression).parameters
    return [
        {
            "site_id": "siteA_cellline_expression_class_broadly_high",
            "source": "methods/onc_methods/depmap_expression_distribution/cli.py::_classify_expression",
            "token": "broadly_high",
            "constant": sig["broadly_high_fraction"].default,
            "constant_form": "keyword default `broadly_high_fraction`",
            "quantity": "fraction_highly_expressed",
            "unit": "fraction of samples with log2(TPM+1) >= highly_expressed_threshold",
            "high_floor_log2tpm": 5.0,
            "denominator": "the WHOLE pan-cancer DepMap panel, every lineage (2446 models at 26q1)",
            "predicate": "frac_highly >= broadly_high_fraction (= 0.30) AND frac_expressed >= 0.70",
            "ladder_position": "a GUARDED sub-decision: reached ONLY inside the `frac_expressed >= 0.70` "
            "(broadly-expressed) band, where it splits broadly_high from broadly_moderate. A target "
            "below the breadth gate is never broadly_high no matter how high frac_highly is.",
        },
        {
            "site_id": "siteB_expression_property_magnitude_and_prevalence",
            "source": "methods/onc_methods/expression_properties/resolve.py::_BROADLY_HIGH_FRACTION_MIN",
            "token": "prevalence=broad / magnitude=high",
            "constant": RESOLVE._BROADLY_HIGH_FRACTION_MIN,
            "constant_form": "module constant `_BROADLY_HIGH_FRACTION_MIN`",
            "quantity": "fraction_highly_expressed",
            "unit": "fraction of samples with log2(TPM+1) >= _HIGHLY_EXPRESSED_LOG2TPM",
            "high_floor_log2tpm": RESOLVE._HIGHLY_EXPRESSED_LOG2TPM,
            "denominator": "the SAME pan-cancer DepMap summary dict site A reads",
            "predicate": "fraction_highly_expressed >= 0.50",
            "ladder_position": "UNGUARDED. `_prevalence`'s FIRST rung (`fh >= 0.5 -> broad`), and one of "
            "three OR-conditions in `_magnitude` (`fh >= 0.5 -> high`). No breadth gate precedes it.",
            "note": "This reads the IDENTICAL `fraction_highly_expressed` key site A's classifier reads, "
            "at the IDENTICAL 5.0 floor (_HIGHLY_EXPRESSED_LOG2TPM mirrors the cli default). Same "
            "quantity, same panel, same floor — a REAL divergence, 0.30 vs 0.50.",
            "magnitude_redundancy": "In `_magnitude` the `fh >= 0.5` OR-condition is SUBSUMED by "
            "`med >= 5.0`: fh >= 0.5 forces both central order statistics >= 5.0, hence median >= 5.0. "
            "So today the 0.50 bites ONLY in `_prevalence`; lowering it to 0.30 would newly bite in "
            "`_magnitude` for a target with fh in [0.30, 0.50) and median < 5.0.",
        },
        {
            "site_id": "siteC_tumour_broadly_high",
            "source": "methods/onc_methods/tcga_gtex_expression_distribution/read.py::_classify_tumor_expression",
            "token": "broadly_high",
            "constant": 0.5,
            "constant_form": "inline literal (no module-level name)",
            "quantity": "high_fraction",
            "unit": "fraction of samples with log2(TPM+1) >= HIGH_LOG2TPM",
            "high_floor_log2tpm": TUM_STATS.HIGH_LOG2TPM,
            "denominator": "the tumour patients of ONE indication (recount3 TCGA slice) — NOT a pan-cancer panel",
            "predicate": "high_fraction >= 0.5",
            "ladder_position": "UNGUARDED first rung -> broadly_high, pre-empting every other rung.",
            "note": "Same CONCEPT as sites A/B but a DIFFERENT denominator (one indication) and a "
            "DIFFERENT high floor (HIGH_LOG2TPM = 5.6724 = log2(51), vs the cell-line 5.0 — the #2221 "
            "anchor divergence, already adjudicated documented-intentional). Move FORBIDDEN this arc "
            "(#2061 / #1984 PR-B own the tumour-presence golden).",
        },
        {
            "site_id": "not_a_broadly_high_cut__presence_supported_fraction",
            "source": "methods/onc_methods/expression_properties/resolve.py::_PRESENCE_SUPPORTED_FRACTION",
            "token": "presence=supported",
            "constant": RESOLVE._PRESENCE_SUPPORTED_FRACTION,
            "quantity": "fraction_expressed",
            "why_listed": "A `0.50` in the same module, but on a DIFFERENT quantity — fraction_EXPRESSED "
            "(detection floor log2(TPM+1) >= 1.0), not fraction_HIGHLY_EXPRESSED (floor 5.0). Listed to "
            "forestall the #2220 error of treating a shared numeral as a shared bar.",
        },
    ]


def ADJUDICATION() -> dict:
    return {
        "protocol": "#809 phase 3b flip matrix; arc policy document-all / adjudicate-flagged.",
        "outcome": "DOCUMENTED-INTENTIONAL — no threshold changed.",
        "finding_1_the_three_values_confirmed_same_quantity_two_panels": (
            "Sites A and B read the IDENTICAL `fraction_highly_expressed` field off the SAME "
            "compute_summary_stats dict over the SAME pan-cancer vector at the SAME 5.0 floor, so "
            "0.30 (A) vs 0.50 (B) is a genuine same-quantity, same-panel divergence — NOT the #2220 "
            "shared-numeral illusion. Site C cuts the same CONCEPT (fraction highly-expressing) but on "
            "a different denominator (one indication's tumour patients) and a different high floor "
            "(HIGH_LOG2TPM = 5.6724 vs 5.0 — the #2221 divergence). Verified by construction and on "
            "the committed panel."
        ),
        "finding_2_the_divergence_is_structural_not_only_numeric": (
            "Site A's 0.30 is a GUARDED sub-decision reached only inside `frac_expressed >= 0.70`; "
            "sites B and C fire UNGUARDED as a first rung. So the number alone does not make the words "
            "converge: at a shared 0.50 bar site A (guarded) and site B (unguarded `_prevalence`) still "
            "disagree on the measured panel wherever a target clears 0.50 highly-expressed but sits "
            "below the 0.70 breadth gate. Harmonising the NUMBER without reconciling the LADDER "
            "POSITION would leave the words no closer — the same shape of finding as #2221's 'moving "
            "the anchor pushes the two broadly_high words further apart'."
        ),
        "finding_3_what_each_harmonisation_costs_on_measured_data": (
            "Direction A-up (0.30 -> 0.50): demotes cell-line broadly_high -> broadly_moderate for the "
            "targets recorded in grain_pan_cancer.measured.siteA_mover_ids. expression_class feeds "
            "tumor-presence `model_expression_structure`, so this MOVES THE TUMOUR-PRESENCE GOLDEN — "
            "FORBIDDEN this arc (#2061 / #1984 PR-B). Direction C-down (0.50 -> 0.30): promotes the "
            "tumour reads in grain_tumour.measured.mover_ids to broadly_high; also golden-touching, "
            "FORBIDDEN. Direction B-down (0.50 -> 0.30): moves the prevalence/magnitude reads in "
            "siteB_*_mover_ids; does NOT touch expression_class, but reverses resolve.py's OWN "
            "documented arm-mirror (`_BROADLY_HIGH_FRACTION_MIN` comment: 'Mirrors read.py:860 "
            "high_fraction >= 0.5')."
        ),
        "finding_4_the_magnitude_or_condition_is_redundant_today": (
            "In `_magnitude`, `fh >= 0.5` is subsumed by `med >= 5.0` (fh >= 0.5 forces median >= 5.0 by "
            "the central-order-statistic bound), so the 0.50 bites only in `_prevalence` today. That is "
            "an argument for care, not for a move: lowering B to 0.30 would make the fraction bite in "
            "`_magnitude` too (fh in [0.30, 0.50) with median < 5.0), broadening the change beyond "
            "prevalence."
        ),
        "why_no_change_here": (
            "Two of the three harmonisation directions (A-up, C-down) move a `broadly_high` word that "
            "the tumour-presence golden captures, and regenerating that golden is out of scope for this "
            "arc (#2061 / #1984 PR-B; #2227 is filed blocked for exactly this). The only golden-safe "
            "direction, B-down, is not a mechanical fix: it turns on whether resolve.py's pan-cancer "
            "prevalence/magnitude bar should mirror the tumour twin's NUMBER (0.50, arm-agreement by "
            "value, the current deliberate choice) or the cell-line classifier's DENOMINATOR-appropriate "
            "bar (0.30, since a pan-cancer panel dilutes a target broadly-high in its relevant "
            "lineages). Because sites A/B/C read three different (panel, floor, guard) contexts, "
            "'agreement' is not simply a shared number, and picking a direction is an owner call about "
            "what the pan-cancer `broad` word should MEAN — routed up, not guessed here. Same posture "
            "and same answer as #2221 and #2222."
        ),
        "direction_routed_up": (
            "OWNER CALL: should `expression_properties/resolve.py::_BROADLY_HIGH_FRACTION_MIN` keep "
            "mirroring the tumour twin's 0.50 (agreement-by-value across arms) or adopt the cell-line "
            "classifier's 0.30 (agreement-by-denominator, since it reads the pan-cancer panel A reads)? "
            "The measurement cannot decide it — neither bar is calibrated against a curated panel, and "
            "the honest gap is the same panel-composition NOISE FLOOR #2221 flagged as unmeasured for "
            "this panel."
        ),
        "catalog_write": (
            "This PR writes this adjudication (rationale + non-null `calibration.flip_matrix`) onto the "
            "`broadly_high_fraction` determinant of tumor_presence.yaml's `model_expression_structure` "
            "(where #2218 declared it — the issue's dispatch said expression.yaml, but the determinant "
            "is in tumor_presence.yaml; overridden), superseding #2218's placeholder flag."
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
