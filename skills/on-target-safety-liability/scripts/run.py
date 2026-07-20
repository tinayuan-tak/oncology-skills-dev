#!/usr/bin/env python3
"""on-target-safety-liability — Phase-G partial skill (graduated 2026-07-08).

Germline LoF-constraint safety signal from gnomAD.

W4c refactor (2026-07-09): calls the shared run_wired_skill dispatcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.dispatcher import run_wired_skill
from _skills_common.resolver import resolve_verdict_for_gate


SKILL_NAME = "on-target-safety-liability"
SKILL_VERSION = "1.2.0"

CARDS = ["gnomad-lof-constraint"]

QUESTION = ("Is {target} highly constrained against loss-of-function "
            "variants in the gnomAD population, and what does this imply "
            "for on-target safety of full-KO modalities (degrader, RNA "
            "therapeutic, full-inhibition SM) in {indication}?")

PARTIAL_STATUS_NOTE = (
    "on-target-safety-liability is status: partial; this skill reflects only the "
    "gnomAD GERMLINE constraint signal (modality-agnostic / SM-relevant). The "
    "normal-tissue-liability HPA-IHC signal (biologics on-target-off-tumor safety) "
    "is now WIRED, but on the surface_intrinsic axis — it is consumed by the "
    "surface-modality-fit skill (adc/bite_tce/antibody channels), not here. "
    "protein-surface-evidence card remains unwired."
)


def _verdict(fired: list[dict]) -> tuple[str, str | None]:
    """Verdict — DELEGATES to the shared declarative resolver (gap #5, 2026-07-20).
    The former if-chain now lives in resolvers/safety.resolver.yaml (target-contracts),
    evaluated by the ONE interpreter both engines call. Proven byte-for-byte equivalent to
    the former if-chain by the golden-oracle test. A missing spec raises (the resolver is
    the source of truth — no silent fallback to a stale copy, which would reintroduce drift)."""
    result = resolve_verdict_for_gate(fired, "safety")
    if result is None:
        raise RuntimeError(
            "safety resolver spec missing (target-contracts/resolvers/safety.resolver.yaml) "
            "— the verdict source of truth is absent.")
    return result

def _headline(cards, fired, verdict_pair):
    def _get(cid: str, key: str):
        for c in cards:
            if c["card_id"] == cid:
                return (c["summary"] or {}).get(key)
        return None

    v, drv = verdict_pair or ("insufficient", None)
    return {
        "safety_verdict":   v,
        "driving_rule_id":  drv,
        "constraint_class": _get("gnomad-lof-constraint", "constraint_class"),
        "pli_score":        _get("gnomad-lof-constraint", "pli_score"),
        "loeuf_score":      _get("gnomad-lof-constraint", "loeuf_score"),
        "mis_z_score":      _get("gnomad-lof-constraint", "mis_z_score"),
        "syn_z_score":      _get("gnomad-lof-constraint", "syn_z_score"),
        "obs_lof_count":    _get("gnomad-lof-constraint", "obs_lof_count"),
        "exp_lof_count":    _get("gnomad-lof-constraint", "exp_lof_count"),
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
        partial_status_note=PARTIAL_STATUS_NOTE,
    ))
