#!/usr/bin/env python3
"""drift_golden — shared helpers for the offline golden-set drift-CI.

Both `freeze_drift_golden.py` (regenerate the frozen golden) and `tests/test_drift_guard.py`
(assert no drift) import from here so the trim projection + the frozen deterministic-spine subset are
single-sourced.

The drift-CI is OFFLINE and DETERMINISTIC: it runs the integrator with a CANNED two-call LLM response
(`llm_replay.json`, frozen once from a real Bedrock run) against a TRIMMED evidence package
(integrator-relevant fields only, so the fixture is a few KB not multiple MB). It then freezes only
the DETERMINISTIC SPINE outputs — the clamped verdict, the gate ceiling / clamp tension, the
clause-traceability score, the computed certainty + its caps, the data gaps, the substrate-discount
decision, the intra-package coherence result, and the two provenance PINS (prompt_template_hash +
model_id). The LLM PROSE (edge rationales, clause statements) is deliberately NOT frozen — only the
deterministic spine required to be run-to-run stable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# The evidence-package fields the integrator actually reads (assemble + gate_ceiling +
# parse_subtype_resolved + substrate_independence). Trimming to these keeps the golden fixture small
# while producing byte-identical deterministic outputs (guarded by test_trim_projection_is_faithful).
_CARD_KEEP = ("card_id", "interpretation_call", "evidence_substrate")


def trim_evidence_package(pkg: dict) -> dict:
    """Project a full target-profile evidence_package down to the integrator-relevant fields."""
    syn = pkg.get("synthesis") or {}
    out = {
        "schema_version": pkg.get("schema_version"),
        "framework_version": pkg.get("framework_version"),
        "context": pkg.get("context", {}),
        "synthesis": {
            "sub_verdicts": syn.get("sub_verdicts", {}),  # full: verdict + fired_rule_ids
            "recommendation_gate": syn.get("recommendation_gate", {}),  # full: fired/hard_gates/...
            "claim_vectors": syn.get("claim_vectors", {}),  # Stage 2a: signal facets + citable atoms
            # decision_facets drives certainty_by_axis / composed_modality / cross_gate_shared_evidence /
            # fragility / competitor_crossref — all declared in SKILL.md reads_spine_fields. The trim used
            # to DROP the whole block, so the drift golden could not see any of it (the frozen fixtures
            # predate the facets, so nothing failed — a vacuous pass).
            "decision_facets": syn.get("decision_facets", {}),
            # #1310 UNIFIED_OUTPUT_CONTRACT: the per-axis ROLE view. Without it the integrator falls back
            # to treating a gateless descriptive lens as a data gap, so it must be in the trim for the
            # golden to pin role-aware gaps / certainty.
            "skill_reports": syn.get("skill_reports", {}),
            "skill_report_rollup": syn.get("skill_report_rollup", {}),
            "confidence_tier": syn.get("confidence_tier", {}),
        },
        "cards": [
            {k: c.get(k) for k in _CARD_KEEP if k in c}
            for c in pkg.get("cards", [])
            if isinstance(c, dict) and c.get("card_id")
        ],
    }
    if isinstance(pkg.get("subtype_resolved"), dict):
        out["subtype_resolved"] = pkg["subtype_resolved"]
    return out


def deterministic_spine_subset(r: dict) -> dict:
    """The frozen subset of a run() result — every field here MUST be run-to-run deterministic
    offline. Excludes all LLM prose and the non-deterministic provenance.generated_at timestamp."""
    v, d, u = r["verdict"], r["defensibility"], r["uncertainty"]
    ei, prov = r["evidence_independence"], r["provenance"]
    return {
        # --- clamped verdict + gate ---
        "computed_verdict": v["computed"],
        "gate_ceiling": v["gate_ceiling"],
        "gate_reason": v["gate_reason"],
        # the two demotion mechanisms frozen APART: a regression that re-conflates the promotion cap with
        # the gate clamp moves `was_clamped` without moving `verdict_after_gate`, and the guard sees it.
        "was_clamped": v["was_clamped"],
        "promotion_capped": v["promotion_capped"],
        "verdict_after_gate": v["verdict_after_gate"],
        "gate_clamp_tension_present": bool(v["gate_clamp_tension"]),
        "gate_fail_closed": v["gate_fail_closed"],
        "hard_gates_present": v["hard_gates_present"],
        "active_vetoes": sorted(v["active_vetoes"]),
        "blind_gates": sorted(v["blind_gates"]),
        "opposing_gates": sorted(v["opposing_gates"]),
        "modality_excluded_gates": sorted(v["modality_excluded_gates"]),
        # --- defensibility (teeth) ---
        "clause_traceability": d["clause_traceability"],
        "promotable": d["promotable"],
        "promotion_blockers": sorted(d["promotion_blockers"]),
        "n_coherence_violations": d["n_coherence_violations"],
        "coherence_violation_clauses": sorted(d["coherence_violations"].keys()),
        # --- certainty + gaps + substrate discount ---
        "overall_certainty": u["overall_certainty"],
        "base_certainty": u["base_certainty"],
        "certainty_capped": u["certainty_capped"],
        "cap_reasons": u["cap_reasons"],
        "cap_ceiling": u["cap_ceiling"],
        "spine_tier_divergence_present": bool(u["spine_tier_divergence"]),
        "limiting_dimension": u["limiting_dimension"],
        "limiting_dimension_scope": u["limiting_dimension_scope"],
        "data_gaps": sorted(u["data_gaps"]),
        # role-aware gap/certainty split (#1310): which axes are GATELESS BY DESIGN, and the per-axis
        # certainty histogram behind the weakest-link scalar. Frozen so a role-read regression is visible.
        "not_scored_axes": sorted(u["not_scored_axes"]),
        "axis_roles_present": u["axis_roles_present"],
        "n_axes_by_level": u["n_axes_by_level"],
        "n_gating_axes_by_level": u["n_gating_axes_by_level"],
        "correlated_evidence_discounted": ei["correlated_evidence_discounted"],
        "correlated_groups": {k: sorted(vv) for k, vv in ei["correlated_groups"].items()},
        "n_independent_substrate_units": ei["n_independent_substrate_units"],
        "effective_independent_units": ei["effective_independent_units"],
        "independence_unit_kind": ei["independence_unit_kind"],
        "substrate_tagged_fraction": ei["substrate_tagged_fraction"],
        "tagging_sparse": ei["tagging_sparse"],
        # abstention and cap-binding frozen APART — see the emit block. Freezing only one of them let a
        # view that spoke and capped nothing be indistinguishable from a view that capped.
        "independence_view_authoritative": ei["independence_view_authoritative"],
        "independence_cap_binding": ei["independence_cap_binding"],
        # --- UNIFIED_OUTPUT_CONTRACT skill_report: the deterministic parts (prose-free) ---
        "skill_report_role": r["skill_report"]["role"],
        "skill_report_call": r["skill_report"]["call"],
        "skill_report_polarity": r["skill_report"]["polarity"],
        "skill_report_chip_signals": {c["key"]: c["signal"] for c in r["skill_report"]["claim_chips"]},
        # --- provenance PINS (drift on prompt/model flips these) ---
        "prompt_template_hash": prov["prompt_template_hash"],
        "model_id": prov["model_id"],
        "llm_mode": prov["llm_mode"],
    }


def load_golden_substrate(case_dir: Path) -> Optional[dict]:
    """`substrate/<axis>.json` → the axis→ground_axis-block dict run() takes, or None if absent.

    A case WITHOUT a substrate dir exercises the bare-package path; a case WITH one exercises the
    grounded chain production actually runs (ground_axis → risk_rollup → integrator). Both matter, so
    this is per-case rather than global."""
    d = case_dir / "substrate"
    if not d.is_dir():
        return None
    blocks = {p.stem: json.loads(p.read_text()) for p in sorted(d.glob("*.json"))}
    return blocks or None


def load_golden_case(case_dir: Path) -> dict:
    """Read a golden case dir → the inputs + the frozen expected spine subset."""

    def _opt(name):
        p = case_dir / name
        return str(p) if p.exists() else None

    return {
        "pkg": str(case_dir / "evidence_package.json"),
        "risk": _opt("risk.json"),
        "dossier": _opt("dossier.json"),
        "substrate": load_golden_substrate(case_dir),
        "replay": json.loads((case_dir / "llm_replay.json").read_text()),
        "meta": json.loads((case_dir / "meta.json").read_text()),
        "expected": json.loads((case_dir / "expected_spine.json").read_text()),
    }
