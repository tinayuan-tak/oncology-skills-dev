#!/usr/bin/env python3
"""mechanism-and-pharmacology — Phase-D wired skill (graduated 2026-07-08).

Signaling-network mechanism + candidate MoA hooks + PD-marker suggestions.
Consumes the signaling-network-mechanism card (SIGNOR-tagged edges from
OmniPath, classified into a 21-class MoA ontology). Emits a data-package
output tree with rule-derived per-modality signals.

W4c refactor (2026-07-09): now uses the shared
_skills_common.dispatcher.run_wired_skill(...) entry point. Skill-
specific logic (CARDS list + verdict + headline) shrinks to a few
callbacks; boilerplate (arg parsing, resolve_cards, fired_rules,
modality-lens wiring, write_package) moves into the dispatcher. The
previous inline implementation is removed; behavior is equivalent.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common import get_card_field
from _skills_common.resolver import resolve_verdict_for_gate


SKILL_NAME = "mechanism-and-pharmacology"
SKILL_VERSION = "1.2.0"                       # bumped for W4c dispatcher refactor

CARDS = [
    "signaling-network-mechanism",
    # phospho-pathway-activity RE-HOMED here 2026-08-05 (was tumor-presence). Phosphorylation is an
    # ACTIVITY / signaling-STATE readout (CPTAC phosphoproteomics: is the target phosphorylated, at
    # which sites, in how many tumors) — a MECHANISM signal, not a presence/abundance one. DISPLAY-ONLY
    # facet: feeds NO resolver rung, so the mechanism_verdict stays byte-stable (the mechanism resolver
    # keys only on signaling-network-mechanism fields).
    "phospho-pathway-activity",
    "pathway-activity-context",                 # Track PROGENy (2026-08-10): per-indication PROGENy
                                                # pathway-ACTIVITY context (Schubert 2018). VERDICT-INERT
                                                # (like phospho) — upgrades Mechanism from topology-only
                                                # to quantitative activity; keys no resolver rung.
]

QUESTION = ("For {target} in {indication}, what upstream regulators + "
            "downstream effectors are catalogued in SIGNOR, and which MoA "
            "classes are candidate hooks for SM / degrader / molecular-glue "
            "programs?")


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Verdict — DELEGATES to the shared declarative resolver (gap #5, 2026-07-20).
    The former if-chain now lives in resolvers/mechanism.resolver.yaml (target-contracts),
    evaluated by the ONE interpreter both engines call. Proven byte-for-byte equivalent to
    the former if-chain by the golden-oracle test. A missing spec raises (the resolver is
    the source of truth — no silent fallback to a stale copy, which would reintroduce drift)."""
    result = resolve_verdict_for_gate(fired, "mechanism")
    if result is None:
        raise RuntimeError(
            "mechanism resolver spec missing (target-contracts/resolvers/mechanism.resolver.yaml) "
            "— the verdict source of truth is absent.")
    return result

def _headline(cards, fired, verdict_pair):
    """Skill-specific headline: SIGNOR-network descriptive fields."""
    v, drv = verdict_pair or ("insufficient", None)
    return {
        "mechanism_verdict":         v,
        "driving_rule_id":           drv,
        "network_class":             get_card_field(cards, "signaling-network-mechanism",
                                          "network_class"),
        "n_upstream_regulators":     get_card_field(cards, "signaling-network-mechanism",
                                          "n_upstream_regulators"),
        "n_downstream_effectors":    get_card_field(cards, "signaling-network-mechanism",
                                          "n_downstream_effectors"),
        "moa_classes_present":       get_card_field(cards, "signaling-network-mechanism",
                                          "moa_classes_present"),
        "pd_marker_classes_present": get_card_field(cards, "signaling-network-mechanism",
                                          "pd_marker_classes_present"),
        "has_actionable_moa":        get_card_field(cards, "signaling-network-mechanism",
                                          "has_actionable_moa"),
        "has_pd_marker":             get_card_field(cards, "signaling-network-mechanism",
                                          "has_pd_marker"),
        "moa_ontology_version":      get_card_field(cards, "signaling-network-mechanism",
                                          "moa_ontology_version"),
        # Phospho ACTIVITY facet (re-homed 2026-08-05) — CPTAC phosphoproteomics signaling-state
        # readout. Display-only (feeds no resolver); enriches the mechanism picture for kinases/
        # signaling nodes. data_unavailable for indications with no CPTAC cohort or non-phosphoproteins.
        "phospho_activity_class":    get_card_field(cards, "phospho-pathway-activity",
                                          "phospho_activity_class"),
        "n_phosphosites":            get_card_field(cards, "phospho-pathway-activity",
                                          "n_phosphosites"),
        "max_site_detection_fraction": get_card_field(cards, "phospho-pathway-activity",
                                          "max_site_detection_fraction"),
    }


if __name__ == "__main__":
    sys.exit(run_wired_skill(
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        cards=CARDS,
        axis="intracellular_intrinsic",
        question=QUESTION,
        verdict_fn=_verdict,
        headline_fn=_headline,
        isoform_check_target=True,          # arch A3: warn on p95HER2 / AR-V7 / etc.
    ))
