"""Small-molecule tractability QUESTION TABLE — the LEADING hero for the tractability-small-molecule
skill (the chemical-genetic analog of the presence / genomic / surface heroes).

Canonical question (target_profiling_axes.yaml → home_skill tractability-small-molecule): "Is the
target druggable by a small molecule (a compound exists AND agrees with the genetic dependency)?"
decomposes into:
  Potency      — is there MEASURED binding potency (a potent ChEMBL/BindingDB ligand series)?
  Compound     — is there an active small-molecule compound (PRISM)?
  Concordance  — does compound-kill agree with the CRISPR/RNAi dependency (chemical-genetic)?
  Structure    — is there a ligandable pocket (PDB / AlphaFold coverage)?
  Known-drug   — known-drug / druggable-genome prior (Finan / Open Targets)?
Signal maps each contributing card's OWN class vocabulary via an EXPLICIT map. Verdict-INERT: a
one-way projection over decision['headline']; reuses the shared Signal/Confidence vocab + renderer.

Potency is the FIRST DECLARED CRITICAL axis (run.py `critical_axes=("POTENCY","ACTIVITY")`): ~16% of
SM verdicts (measured_potent_ligand / clinical_precedent_only over the 504-dir corpus) are minted by a
measured-binding/ChEMBL rung, so the hero must surface the `measured_bioactivity_class` leg or a
potency-driven positive verdict shows no explaining leg (display↔spine parity, #1646 / cf. #1574, #1569).
"""

from __future__ import annotations

from typing import Optional

from _skills_common.question_table_core import conf as _conf
from _skills_common.question_table_core import row as _row
from _skills_common.question_table_core import sig as _sig  # shared Signal/Confidence vocab

# POTENCY axis — measured binding potency (ChEMBL / BindingDB), `measured_bioactivity_class` from the
# measured-potency-tractability card (vocab: methods/measured_potency_tractability). The FIRST declared
# critical axis; its rungs (measured_potent_ligand / clinical_precedent_only) mint the SM verdict.
_POTENCY = {
    "potent_measured_ligand": "strong",
    "weak_measured_ligand": "moderate",
    "no_measured_activity": "absent",
    "data_unavailable": "unmeasured",
}
_PRISM = {
    "clinically_active": "strong",
    "clinical_precedent_only": "strong",
    "tool_compound_only": "moderate",
    "weakly_active": "weak",
    "no_compounds_found": "absent",
    "data_unavailable": "unmeasured",
}
_CONCORD = {
    "triangulated_target_engaged": "strong",
    "crispr_confirmed_engagement": "strong",
    "rnai_confirmed_engagement": "moderate",
    "mixed_engagement": "weak",
    "discordant_off_target_likely": "absent",
    "thin_evidence": "unmeasured",
    "data_unavailable": "unmeasured",
}
_STRUCT = {"strong": "strong", "partial": "moderate", "af_only": "weak", "none": "absent"}
_KNOWN = {
    "approved_drug_tractable": "strong",
    "clinically_actionable": "strong",
    "druggable_genome": "moderate",
    "interaction_only": "weak",
    "category_only": "weak",
    "no_known_drug_evidence": "absent",
}

# (row id, sub-question, headline field, value→tier map)
_ROWS = [
    (
        "Potency",
        "Is there measured binding potency (a compound that binds the target)?",
        "measured_bioactivity_class",
        _POTENCY,
    ),
    ("Compound", "Is there an active small-molecule compound (PRISM)?", "prism_activity_class", _PRISM),
    (
        "Concordance",
        "Does compound-kill agree with the genetic dependency (chemical-genetic)?",
        "prism_crispr_concord",
        _CONCORD,
    ),
    ("Structure", "Is there a ligandable pocket (PDB / AlphaFold)?", "pdb_coverage_class", _STRUCT),
    ("Known-drug", "Known-drug / druggable-genome prior?", "known_drug_tractability", _KNOWN),
]


def _tier(mapping: dict, val) -> str:
    if val in (None, "", "data_unavailable", "unmeasured"):
        return "unmeasured"
    return mapping.get(str(val), "weak")


def tractability_sm_question_table(headline: dict, cards: Optional[list] = None) -> list:
    """Per-sub-question rows from the tractability-small-molecule headline class fields. Verdict-inert;
    an absent field → an unmeasured row (never omitted), so the hero always shows the full
    Potency / Compound / Concordance / Structure / Known-drug ladder + which leg is a named gap."""
    h = headline or {}
    rows = []
    for qid, question, field, mapping in _ROWS:
        val = h.get(field)
        tier = _tier(mapping, val)
        rows.append(
            _row(
                qid,
                question,
                str(val if val not in (None, "") else "—"),
                "",
                _sig(tier, "not measured" if tier == "unmeasured" else str(val)),
                _conf("unmeasured" if tier == "unmeasured" else "moderate"),
            )
        )
    return rows


__all__ = ["tractability_sm_question_table"]
