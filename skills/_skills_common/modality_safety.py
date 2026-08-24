"""modality_safety — Layer-2 CORE transform of VERDICT_REPRESENTATION.md.

Produces a PER-MODALITY safety verdict from the fired safety rules, by crossing each
WT-loss-of-function safety concern (vocabularies/wt_loss_safety_conditioning.yaml) against
each modality channel's WT-engagement (vocabularies/modality.enum.yaml::wt_engagement).

This is the honest replacement for the GoF-role-proxy heuristic in safety.resolver.yaml,
which fakes allele-selectivity from alteration-role and emits a single modality-AGNOSTIC
verdict. A WT-loss concern (gnomAD constraint, gene-burden, ClinGen dominant-loss, ClinVar
pathogenic, mouse-KO-lethal, pan-essential broad-tox, essential-normal-tissue protein) applies
to an agent ONLY insofar as the agent depletes/fully-inhibits WILD-TYPE protein:

    engages_wt      (degrader, RNA)         -> concern APPLIES              -> hold
    conditional     (small_molecule)        -> applies to WT-engaging agents;
                                               allele-selective (G12C) spares WT -> conditional
    not_applicable  (adc/bite_tce/antibody) -> concern does not apply       -> n/a

protective_rules invert: an LoF-population-protective signal DE-RISKS a full knockout, so it is
`supportive` for engages_wt channels.

PURE + DETERMINISTIC: a function of (fired rule_ids, two versioned contract files). No I/O beyond
reading the contracts, no ML, no arithmetic on measured values. NOT yet wired into decision.json
(the wire-in + retirement of the 6 role-proxy rungs is a separate reblessed change — it fans out
into the safety golden suite).
"""
from __future__ import annotations
import functools
import os
from pathlib import Path

import yaml

_CONTRACTS = Path(os.environ.get(
    "TARGET_CONTRACTS_ROOT",
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))

# Action per (concern present) x (channel wt_engagement). Ordered worst->best for reduction.
_ACTIONS = ("hold", "conditional", "supportive", "not_applicable", "no_concern")


@functools.lru_cache(maxsize=None)
def _load(contracts_root: str | None):
    root = Path(contracts_root) if contracts_root else _CONTRACTS
    cond = yaml.safe_load((root / "vocabularies" / "wt_loss_safety_conditioning.yaml").read_text())
    mod = yaml.safe_load((root / "vocabularies" / "modality.enum.yaml").read_text())
    wt_engagement = {v["value"]: v.get("wt_engagement") for v in mod["values"]}
    return (frozenset(cond.get("concern_rules") or []),
            frozenset(cond.get("protective_rules") or []),
            frozenset(cond.get("allele_selective_eligibility_rules") or []),
            frozenset(cond.get("allele_selective_disqualifier_rules") or []),
            wt_engagement)


def safety_verdict_by_modality(fired, contracts_root: str | None = None) -> dict:
    """Return {channel: {action, wt_engagement, driving_rules}} over every modality.

    `fired` is the shared fired-rules list ([{rule_id, ...}, ...]). `action` is:
      hold         — a WT-loss concern applies (channel engages WT)
      conditional  — concern applies to WT-engaging agents; allele-selective spares WT (SM)
      supportive   — protective genetics de-risks a full knockout (engages_wt only)
      not_applicable — WT-loss is not this modality's operative safety axis
      no_concern   — no WT-loss concern or protective signal fired
    """
    concern_rules, protective_rules, eligibility_rules, disqualifier_rules, wt_engagement = _load(contracts_root)
    fired_ids = {f.get("rule_id") for f in fired}
    concern_hits = sorted(fired_ids & concern_rules)
    protective_hits = sorted(fired_ids & protective_rules)
    # allele-selective escape requires an eligibility signal (activating GoF role) AND the absence of a
    # disqualifier (amplification-driven / rarely-altered GoF — no selectable point mutation, so a small
    # molecule engages WT). Preserves the retired resolver's amplification (GROUP-0) + rarely-altered
    # (GROUP-0b) guards: an amplified oncogene (ERBB2) is NOT allele-selective-eligible → small_molecule=hold.
    allele_selective_eligible = bool(fired_ids & eligibility_rules) and not bool(fired_ids & disqualifier_rules)

    out = {}
    for channel, eng in wt_engagement.items():
        driving = []
        if eng == "not_applicable":
            action = "not_applicable"
        elif concern_hits:
            driving = concern_hits
            if eng == "engages_wt":
                action = "hold"                       # degrader / RNA deplete total WT protein
            else:  # eng == "conditional" (small_molecule): allele-selectivity is AGENT-level
                # conditional escape ONLY if the target admits a mutant-selective agent (GoF/activating
                # role fired); else a pan small-molecule inhibitor ENGAGES WT and the concern stands.
                action = "conditional" if allele_selective_eligible else "hold"
        elif protective_hits and eng == "engages_wt":
            driving = protective_hits
            action = "supportive"
        else:
            action = "no_concern"
        out[channel] = {"action": action, "wt_engagement": eng, "driving_rules": driving}
    return out
