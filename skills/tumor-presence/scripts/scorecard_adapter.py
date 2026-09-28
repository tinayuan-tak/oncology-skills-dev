#!/usr/bin/env python
"""tumor-presence scorecard adapter (#1988, A0c) — the NORMATIVE example the sibling adapters
(#1989-#1993) copy.

Epic #1985's component scorecard (A0a, `_skills_common.component_scorecard`) records ONE cell per
``(skill x layer)`` with four independent criteria — accuracy / utilization / fail_open /
panel_consistency, each GREEN|RED|NULL — plus a cell-level ``built`` flag. This script is the ENTIRE
adapter write surface for tumor-presence: it builds the shard in memory and calls
``write_skill_shard``, which touches exactly ``scorecard/tumor-presence.json``.

## Layer mapping (this skill's own architecture, not a generic guess)

The generic ``L1/L2a/L2b/L3/L4`` grain maps onto tumor-presence's landed evidence-property layers
(``_skills_common.evidence_frame.ClaimType`` + the reference-vertical epic #1938):

  L1  — the 17 cards themselves (OBSERVATIONAL_PROPERTY): raw per-card measurements + their
        disposition ledger (``field_disposition.yaml``).
  L2a — ``source_properties`` (SK#1941 EXPORTED section): the per-source observational properties,
        formalized as a named, reconstructable export.
  L2b — ``integrated_properties`` (SK#1941 EXPORTED section): the concordance ISLANDS built earlier
        (coverage #1517/#1578, abundance #1589/#1594, subtype_restriction #1830/#1840).
  L3  — ``l3d`` (SK#1940, DOMAIN_INTERPRETATION): the "tumor-expression biology story" — a
        within-domain, claim-ID-traceable synthesis over the L2b islands.
  L4  — SYNTHESIS / decision views. Epic #1938 explicitly puts this OUT OF SCOPE for the tumor-presence
        reference vertical ("L4 facet synthesis + decision views (deferred horizontal epic)") — so
        ``built=False`` (NOT_BUILT), not a defect.

## What "accuracy" means at each layer (and why L2a/L2b/L3 are honestly NULL there)

Only L1 carries genuine raw-substrate re-derivation in this shard: L2a/L2b/L3 are DETERMINISTIC
re-projections/aggregations over L1's already-validated card summaries (no new arithmetic over raw
substrate) — independently re-deriving them from S3 would just re-run L1's own accuracy check under a
different name. Per the directive ("leave a criterion NULL rather than fabricate a reading you cannot
support"), their accuracy criterion is NULL with that reasoning recorded in evidence, not a fabricated
GREEN riding on L1's coattails.

## Panel-consistency is COMPUTED, not hand-typed (the teeth)

`collect_panel_rows()` is the live function that makes the L1 panel_consistency GREEN a property of
the package BYTES, not an author's claim: it loads (or live-emits + caches, via `_load_package`) each
of the 5 roster pairs' tumor-presence decision.json, extracts two verdict-bearing card classes, and
computes three non-vacuity checks (classes aren't constant across the roster; the thin-coverage
control genuinely degrades relative to the others). `skills/tumor-presence/tests/test_scorecard_shard.py`
monkeypatches `_load_package` with a doctored (constant-class / all-missing) panel and asserts the
checks go RED — proving the checks have teeth, independent of live data or network access.

NOTE ON PROVENANCE (a genuine finding worth carrying forward to A0b + the sibling adapters):
`eval/run_scorecard_panel.py --emit` (the A0b #2000 harness, which drives target-profile's full
15-subskill `--full-package`) TIMED OUT at 900s for BOTH EPCAM and HTR1D in this environment (see
`eval/scorecard_panel_report.json`, generated 2026-09-28T19:13:30Z) — the full composition is too slow
for that timeout on a richly- or thinly-covered target alike. `_load_package` therefore drives
tumor-presence's OWN, much lighter entrypoint directly (`scripts/run.py --target <T> --indication <I>`,
no `--full-package` fan-out), which finishes in well under a minute per target and reads the identical
cards.

## Evidence recipe siblings should copy

Every evidence dict below either (a) names a COMMITTED, currently-green test (accuracy/utilization/
fail_open — re-run before trusting the shard) or (b) is COMPUTED live from real per-target packages
(panel_consistency), never a static claim with no test/artifact behind it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
REPO_ROOT = SKILLS_ROOT.parent
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common import component_scorecard as cs  # noqa: E402

SKILL = "tumor-presence"

# ── L1 evidence: accuracy / utilization / fail_open (test-backed, static evidence dicts) ──────────

_L1_ACCURACY_EVIDENCE = {
    "method": (
        "Independent raw-substrate re-derivation, reusing analysis-methods' T3 recomputation anchors "
        "(plan foamy-bird Stage I) one step further than analysis-methods' own tests: asserts the "
        "re-derived number ALSO equals the tumor-presence golden's card summary for the same "
        "target/indication, so two repos' independent captures must agree at full float64 precision."
    ),
    "test": "skills/tumor-presence/tests/test_scorecard_l1_accuracy_rederivation.py",
    "cards_covered": ["cellline-rna-distribution", "tumor-scrna-celltype-expression"],
    "cards_not_yet_covered": [
        "tumor-rna-vs-adjacent",
        "tumor-rna-distribution",
        "tumor-protein-abundance-cptac",
        "cellline-protein-abundance",
        "tumor-elevation-breadth",
    ],
    "raw_substrate": {
        "cellline-rna-distribution": "analysis-methods anchor epcam_26q1.cellline_rna_distribution.json "
        "+ expression_vectors/epcam_26q1.cellline_rna_distribution.parquet (2446-model raw log2(TPM+1) "
        "panel + resolved lineage)",
        "tumor-scrna-celltype-expression": "analysis-methods anchor epcam_coadread.sc_celltype.json + "
        "sc_compartment_rows/sc_pseudobulk__compartment_rows.parquet (raw per-(dataset,donor,"
        "compartment) pseudobulk rows)",
    },
    "reconciliation": (
        "fraction_expressed, fraction_highly_expressed, expression_class (cellline-rna-distribution) "
        "and sc_expression_class, malignant_detection_fraction, malignant_abundance_log1p_cp10k, "
        "malignant_n_donors, malignant_n_cells, top_microenvironment_compartment "
        "(tumor-scrna-celltype-expression) all match at full precision between the independent "
        "recompute and tests/fixtures/epcam_coadread_decision.json"
    ),
    "teeth": (
        "test_cellline_rna_distribution_teeth_mutated_input_breaks_the_golden_match and "
        "test_sc_celltype_teeth_dropping_malignant_rows_breaks_the_golden_match mutate the raw input "
        "and assert the match breaks — proving the reconciliation is a live function of substrate, "
        "not a self-echo"
    ),
    "status_as_of": "2026-09-28",
}

_L1_UTILIZATION_EVIDENCE = {
    "method": (
        "field_disposition.yaml ledger: every emitted summary_field of all 17 cards carries an "
        "explicit disposition (signal|context|provenance|display); the REACH tier further requires "
        "every role:signal field be reached by a declared reader or carry a waived_because."
    ),
    "tests": [
        "skills/tumor-presence/tests/test_field_disposition_complete.py::test_ledger_wellformed (always runs)",
        "skills/tumor-presence/tests/test_field_disposition_complete.py"
        "::test_ledger_matches_emitted (ratchet vs run.py CARDS' emitted summary_fields)",
        "skills/tumor-presence/tests/test_field_disposition_complete.py"
        "::test_the_reach_measurement_is_not_vacuous (>= 60 role:signal rows measured)",
        "skills/tumor-presence/tests/test_field_disposition_complete.py"
        "::test_signal_fields_are_reader_reached_or_waived (zero un-reached, un-waived signal fields)",
    ],
    "coverage": "all 17 cards ledgered; ledger's own card set == run.py CARDS (test-enforced equality)",
    "status_as_of": "2026-09-28",
}

_L1_FAIL_OPEN_EVIDENCE = {
    "method": (
        "the shared open-world invariant (`_skills_common.claim_record`, 'ignorance != negation'): "
        "a data_unavailable/unreachable bucket forces state=unknown, direction=neutral, "
        "magnitude.level=none — never a manufactured directional finding."
    ),
    "tests": [
        "skills/tumor-presence/tests/test_claim_record_shadow.py::test_data_unavailable_open_world "
        "(ordinary path, pre-existing)",
        "skills/tumor-presence/tests/test_scorecard_l1_fail_open_probe.py"
        "::test_data_unavailable_degrades_conservatively_ordinary_path (ordinary path, re-asserted "
        "locally for this shard)",
        "skills/tumor-presence/tests/test_scorecard_l1_fail_open_probe.py"
        "::test_teeth_defeating_the_open_world_guard_lets_the_raw_token_leak (TEETH — monkeypatches "
        "claim_record.OPEN_WORLD_AVAILABILITY to frozenset() and shows finding.state leaks the raw "
        "'data_unavailable' token instead of 'unknown'; probe goes RED without the guard, GREEN with it)",
    ],
    "status_as_of": "2026-09-28",
}

# ── L1 panel_consistency: COMPUTED live from real per-target packages ──────────────────────────────

ROSTER: tuple[tuple[str, str], ...] = (
    ("EPCAM", "COADREAD"),
    ("KRAS", "COADREAD"),
    ("ERBB2", "BRCA"),
    ("PLK1", "COADREAD"),
    ("HTR1D", "COADREAD"),
)

RUN_PY = SKILL_DIR / "scripts" / "run.py"
PANEL_CACHE_DIR = SKILL_DIR / "scripts" / ".panel_cache"  # gitignored; see .panel_cache/.gitignore

# Tokens that mean "this bucket read as data-limited/degraded", used to detect whether the
# thin-coverage/abstention roster control (HTR1D) genuinely degrades relative to the others.
_DEGRADED_CELLLINE_CLASSES = frozenset({"lineage_restricted", "broadly_low", "data_unavailable"})
_DEGRADED_SC_CLASSES = frozenset({"broadly_low", "data_unavailable"})


def _load_package(target: str, indication: str, *, timeout: int = 300) -> tuple[dict | None, str | None]:
    """Load tumor-presence's decision.json for one roster pair — from the on-disk cache if present,
    else a live run of this skill's OWN entrypoint (no --full-package fan-out; see module docstring
    for why). Returns (package_dict, source_str), or (None, None) if genuinely unavailable (no
    creds, live run failed/timed out) — absence is reported, never silently substituted."""
    dest = PANEL_CACHE_DIR / f"{target}__{indication.lower()}"
    cached = dest / "decision.json"
    if cached.exists():
        try:
            return json.loads(cached.read_text()), str(cached.relative_to(REPO_ROOT))
        except (OSError, json.JSONDecodeError):
            pass
    dest.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(
            [sys.executable, str(RUN_PY), "--target", target, "--indication", indication, "--out", str(dest)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, None
    if r.returncode != 0 or not cached.exists():
        return None, None
    return json.loads(cached.read_text()), str(cached.relative_to(REPO_ROOT))


def collect_panel_rows() -> tuple[list[dict], dict]:
    """The panel-consistency criterion's live computation: one row per roster pair (its two
    verdict-bearing card classes, or PACKAGE_MISSING) plus non-vacuity checks over the roster."""
    rows: list[dict] = []
    for target, indication in ROSTER:
        pkg, source = _load_package(target, indication)
        if pkg is None:
            rows.append({"target": target, "indication": indication, "status": "PACKAGE_MISSING", "source": None})
            continue
        cards = {c["card_id"]: c.get("summary", {}) for c in pkg.get("cards", [])}
        rows.append(
            {
                "target": target,
                "indication": indication,
                "status": "OK",
                "source": source,
                "cellline_rna_expression_class": cards.get("cellline-rna-distribution", {}).get("expression_class"),
                "sc_expression_class": cards.get("tumor-scrna-celltype-expression", {}).get("sc_expression_class"),
            }
        )

    ok_rows = [r for r in rows if r["status"] == "OK"]
    all_present = len(ok_rows) == len(ROSTER)
    cellline_classes = {r.get("cellline_rna_expression_class") for r in ok_rows} - {None}
    sc_classes = {r.get("sc_expression_class") for r in ok_rows} - {None}

    htr1d = next((r for r in ok_rows if r["target"] == "HTR1D"), None)
    others = [r for r in ok_rows if r["target"] != "HTR1D"]
    thin_coverage_control_degrades = False
    if htr1d is not None and others:
        htr1d_degraded = (
            htr1d.get("cellline_rna_expression_class") in _DEGRADED_CELLLINE_CLASSES
            or htr1d.get("sc_expression_class") in _DEGRADED_SC_CLASSES
        )
        others_not_degraded = any(
            o.get("cellline_rna_expression_class") not in _DEGRADED_CELLLINE_CLASSES
            and o.get("sc_expression_class") not in _DEGRADED_SC_CLASSES
            for o in others
        )
        thin_coverage_control_degrades = htr1d_degraded and others_not_degraded

    checks = {
        "all_roster_rows_present": all_present,
        "cellline_class_not_constant": len(cellline_classes) > 1,
        "sc_class_not_constant": len(sc_classes) > 1,
        "thin_coverage_control_degrades": thin_coverage_control_degrades,
    }
    checks["all_pass"] = all(checks.values())
    return rows, checks


def _panel_consistency_criterion() -> cs.Criterion:
    rows, checks = collect_panel_rows()
    all_present = checks["all_roster_rows_present"]
    evidence = {
        "method": (
            "per-target rows across the whole 5-target roster (not one flagship), COMPUTED live by "
            "collect_panel_rows() (see module docstring) rather than hand-typed: tumor-presence's "
            "verdict-bearing card classes must differ meaningfully across archetypes (flagship "
            "surface, flagship intrinsic driver, amplified surface, pan-essential control, "
            "thin-coverage abstention control) rather than collapsing to one constant reading, and the "
            "thin-coverage control must show the honest degraded/limited reads its archetype predicts."
        ),
        "roster_source": "eval/SCORECARD_PANEL_ROSTER.md",
        "capture_method": (
            "scorecard_adapter.py::_load_package -> skills/tumor-presence/scripts/run.py "
            "--target <T> --indication <I> (direct, no --full-package fan-out; "
            "eval/run_scorecard_panel.py --emit timed out at 900s for EPCAM/HTR1D in this environment)"
        ),
        "rows": rows,
        "checks": checks,
        "status_as_of": time.strftime("%Y-%m-%d", time.gmtime()),
    }
    if not all_present:
        missing = [f"{r['target']}/{r['indication']}" for r in rows if r["status"] == "PACKAGE_MISSING"]
        evidence["null_reason"] = (
            f"package(s) unavailable for {missing} (no cache, and a live run failed/timed out/lacked "
            "credentials) — left NULL rather than scoring a partial roster."
        )
        evidence["packages_missing"] = missing
        return cs.Criterion(status=cs.NULL, evidence=evidence)
    return cs.Criterion(status=(cs.GREEN if checks["all_pass"] else cs.RED), evidence=evidence)


# ── L2a / L2b / L3 evidence (shared rationale) ─────────────────────────────────────────────────

_ACCURACY_NULL_REASON = (
    "deterministic re-projection/aggregation over L1's already-validated card summaries; no new "
    "arithmetic over raw substrate is performed at this layer, so an independent raw-substrate "
    "re-derivation here would duplicate L1's own accuracy check under a different name rather than "
    "add information. Left NULL per directive rather than fabricating a reading this layer's own "
    "logic cannot support; L1's accuracy evidence is the substrate-level proof this layer builds on."
)

_L2A_UTILIZATION_EVIDENCE = {
    "method": "SK#1941 EXPORTED source_properties section reconstructs downward to L1 card_ids.",
    "test": (
        "skills/tumor-presence/tests/test_evidence_package_sections.py"
        "::test_sections_are_named_and_reconstruct_downward_to_l1"
    ),
    "status_as_of": "2026-09-28",
}
_L2A_FAIL_OPEN_EVIDENCE = {
    "method": "no claim vector resolved -> section omitted (byte-stable), never a fabricated empty/zero shape.",
    "test": "skills/tumor-presence/tests/test_evidence_package_sections.py::test_no_claim_vector_yields_no_sections",
    "status_as_of": "2026-09-28",
}

_L2B_UTILIZATION_EVIDENCE = {
    "method": (
        "SK#1941 EXPORTED integrated_properties section; each island's provenance.sources[*] "
        "reconstructs to L1 card_ids."
    ),
    "test": (
        "skills/tumor-presence/tests/test_evidence_package_sections.py"
        "::test_sections_are_named_and_reconstruct_downward_to_l1"
    ),
    "status_as_of": "2026-09-28",
}
_L2B_FAIL_OPEN_EVIDENCE = {
    "method": (
        "never-lift discipline: a stratum/arm with fewer than 2 measured arms yields None (nothing to "
        "reconcile), not a fabricated agree/disagree call; the section itself is omitted when no claim "
        "vector resolves."
    ),
    "tests": [
        "skills/tumor-presence/tests/test_subtype_layer_concordance.py "
        "(single-arm strata resolve to None, not a fabricated concordance call)",
        "skills/tumor-presence/tests/test_evidence_package_sections.py::test_no_claim_vector_yields_no_sections",
    ],
    "status_as_of": "2026-09-28",
}

_L3_UTILIZATION_EVIDENCE = {
    "method": (
        "every l3d chapter cites the L2b claim ID it rests on and names the vector it reconstructs "
        "from; cross_domain_claims is an always-empty, machine-checked floor (the story never "
        "over-claims outside tumor-presence's own scope)."
    ),
    "tests": [
        "skills/tumor-presence/tests/test_l3d_expression_biology_story.py"
        "::test_every_chapter_cites_a_claim_id_present_on_its_named_vector",
        "skills/tumor-presence/tests/test_l3d_expression_biology_story.py::test_story_makes_no_cross_domain_claim",
        "skills/tumor-presence/tests/test_evidence_package_sections.py"
        "::test_sections_are_named_and_reconstruct_downward_to_l1",
    ],
    "status_as_of": "2026-09-28",
}
_L3_FAIL_OPEN_EVIDENCE = {
    "method": "no L2b island resolves -> the l3d key is OMITTED (byte-stable), never an empty-but-present story.",
    "test": (
        "skills/tumor-presence/tests/test_l3d_expression_biology_story.py"
        "::test_no_island_resolves_omits_the_story_byte_stable"
    ),
    "status_as_of": "2026-09-28",
}

_L2_L3_PANEL_NULL_REASON = (
    "the SK#1941 envelope export (source_properties/integrated_properties/l3d) has only been exercised "
    "live for EPCAM/COADREAD (the committed golden `tests/fixtures/epcam_coadread_decision.json` via "
    "--emit-envelope) — extending the --emit-envelope run across the 5-target roster is future work, "
    "not yet measured. Left NULL rather than inferring panel behavior from a single target."
)


def build_shard() -> cs.SkillShard:
    """Build the tumor-presence scorecard shard in memory. Calls `collect_panel_rows()` live (via
    `_panel_consistency_criterion`), so re-running this script re-derives the panel evidence rather
    than replaying a stale table."""
    shard = cs.baseline_shard(SKILL)

    shard.cells["L1"] = cs.Cell(
        built=True,
        criteria={
            "accuracy": cs.Criterion(status=cs.GREEN, evidence=_L1_ACCURACY_EVIDENCE),
            "utilization": cs.Criterion(status=cs.GREEN, evidence=_L1_UTILIZATION_EVIDENCE),
            "fail_open": cs.Criterion(status=cs.GREEN, evidence=_L1_FAIL_OPEN_EVIDENCE),
            "panel_consistency": _panel_consistency_criterion(),
        },
        notes=(
            "L1 = the 17 cards (OBSERVATIONAL_PROPERTY). accuracy measured for 2/7 verdict-bearing "
            "cards with a landed analysis-methods T3 anchor for EPCAM (cellline-rna-distribution, "
            "tumor-scrna-celltype-expression); the other 5 verdict-bearing + 8 display-only + 2 "
            "safety-comparator cards have no anchor yet (see accuracy evidence cards_not_yet_covered)."
        ),
    )

    shard.cells["L2a"] = cs.Cell(
        built=True,
        criteria={
            "accuracy": cs.Criterion(status=cs.NULL, evidence={"reason": _ACCURACY_NULL_REASON}),
            "utilization": cs.Criterion(status=cs.GREEN, evidence=_L2A_UTILIZATION_EVIDENCE),
            "fail_open": cs.Criterion(status=cs.GREEN, evidence=_L2A_FAIL_OPEN_EVIDENCE),
            "panel_consistency": cs.Criterion(status=cs.NULL, evidence={"reason": _L2_L3_PANEL_NULL_REASON}),
        },
        notes="L2a = source_properties (SK#1941 EXPORTED section, --emit-envelope).",
    )

    shard.cells["L2b"] = cs.Cell(
        built=True,
        criteria={
            "accuracy": cs.Criterion(status=cs.NULL, evidence={"reason": _ACCURACY_NULL_REASON}),
            "utilization": cs.Criterion(status=cs.GREEN, evidence=_L2B_UTILIZATION_EVIDENCE),
            "fail_open": cs.Criterion(status=cs.GREEN, evidence=_L2B_FAIL_OPEN_EVIDENCE),
            "panel_consistency": cs.Criterion(status=cs.NULL, evidence={"reason": _L2_L3_PANEL_NULL_REASON}),
        },
        notes=(
            "L2b = integrated_properties (SK#1941 EXPORTED section): the coverage/abundance/"
            "subtype_restriction concordance islands (#1517/#1578, #1589/#1594, #1830/#1840)."
        ),
    )

    shard.cells["L3"] = cs.Cell(
        built=True,
        criteria={
            "accuracy": cs.Criterion(status=cs.NULL, evidence={"reason": _ACCURACY_NULL_REASON}),
            "utilization": cs.Criterion(status=cs.GREEN, evidence=_L3_UTILIZATION_EVIDENCE),
            "fail_open": cs.Criterion(status=cs.GREEN, evidence=_L3_FAIL_OPEN_EVIDENCE),
            "panel_consistency": cs.Criterion(status=cs.NULL, evidence={"reason": _L2_L3_PANEL_NULL_REASON}),
        },
        notes="L3 = l3d, the 'tumor-expression biology story' (SK#1940, DOMAIN_INTERPRETATION).",
    )

    shard.cells["L4"] = cs.Cell(
        built=False,
        criteria={name: cs.Criterion(status=cs.NULL, evidence=None) for name in cs.CRITERIA},
        notes=(
            "L4 (SYNTHESIS / decision views) is explicitly OUT OF SCOPE for the tumor-presence "
            "reference vertical per epic #1938 ('L4 facet synthesis + decision views (deferred "
            "horizontal epic)') — an architecture gap by design, not a defect. built=false; no "
            "criterion may be measured on an unbuilt layer."
        ),
    )

    return shard


def main() -> int:
    scorecard_dir = REPO_ROOT / cs.SCORECARD_DIRNAME
    shard = build_shard()
    path = cs.write_skill_shard(scorecard_dir, shard)
    print(f"[tumor-presence scorecard adapter] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
