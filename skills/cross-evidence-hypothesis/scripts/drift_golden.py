#!/usr/bin/env python3
"""drift_golden — shared helpers for the WS4 offline golden-set drift-CI (roadmap §9).

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
deterministic spine the roadmap requires to be run-to-run stable.
"""
from __future__ import annotations

import json
from pathlib import Path

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
            "sub_verdicts": syn.get("sub_verdicts", {}),           # full: verdict + fired_rule_ids
            "recommendation_gate": syn.get("recommendation_gate", {}),  # full: fired/hard_gates/...
        },
        "cards": [{k: c.get(k) for k in _CARD_KEEP if k in c}
                  for c in pkg.get("cards", []) if isinstance(c, dict) and c.get("card_id")],
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
        "was_clamped": v["was_clamped"],
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
        "limiting_dimension": u["limiting_dimension"],
        "data_gaps": sorted(u["data_gaps"]),
        "correlated_evidence_discounted": ei["correlated_evidence_discounted"],
        "correlated_groups": {k: sorted(vv) for k, vv in ei["correlated_groups"].items()},
        "n_independent_units": ei["n_independent_units"],
        # --- provenance PINS (drift on prompt/model flips these) ---
        "prompt_template_hash": prov["prompt_template_hash"],
        "model_id": prov["model_id"],
        "llm_mode": prov["llm_mode"],
    }


def load_golden_case(case_dir: Path) -> dict:
    """Read a golden case dir → the inputs + the frozen expected spine subset."""
    def _opt(name):
        p = case_dir / name
        return str(p) if p.exists() else None
    return {
        "pkg": str(case_dir / "evidence_package.json"),
        "risk": _opt("risk.json"),
        "dossier": _opt("dossier.json"),
        "replay": json.loads((case_dir / "llm_replay.json").read_text()),
        "meta": json.loads((case_dir / "meta.json").read_text()),
        "expected": json.loads((case_dir / "expected_spine.json").read_text()),
    }
