"""Genomic-alteration QUESTION TABLE — the LEADING per-alteration-class hero for the
genomic-alteration-profile skill (the genomic analog of presence_question_table / dependency_question_table).

The skill's canonical question (target_profiling_axes.yaml → home_skill genomic-alteration-profile):
"How is the target genomically altered (SNV / CN / fusion), and which class drives?" decomposes into
per-CLASS sub-questions, mirroring the skill's own multi-class verdict
(headline.genomic_alteration_by_class). Each row is one alteration class:
  - Signal      = that class's OWN primary-card call (positive driver/dependency > measured-negative >
                  unmeasured), keyed off the class verdict + its stratified-dependency corroboration;
  - Confidence  = evidence_state (measured vs data_unavailable), lifted by a corroborating stratified
                  dependency.
Verdict-INERT: a one-way projection over decision['headline'] — never a rule / resolver / gate input.
Reuses the shared signal/confidence vocab + renderer so the gallery + target-profile render identically.
"""

from __future__ import annotations

from typing import Optional

from .presence_question_table import _sig, _conf, _row  # shared Signal/Confidence vocab (single source)

# Per-class row: (display id, sub-question). Order mirrors the alteration-class ladder.
_CLASS_Q = [
    ("snv_indel",   ("SNV",    "Recurrent SNV/indel driver, or biomarker-stratified dependency?")),
    ("copy_number", ("CN",     "Copy-number driver — focal amplification or deletion?")),
    ("fusion",      ("Fusion", "Recurrent fusion / rearrangement driver?")),
]

_POSITIVE_STRONG = ("recurrent", "driver", "amplif", "focal_amp", "deletion", "homozygous")
_NEGATIVE = ("passenger", "neutral", "none", "not_", "no_", "absent", "neutral_cn")


def _class_signal(entry: dict) -> dict:
    """Map one alteration class's own call → a Signal tier (shared vocab). Coarse but honest: keyword
    match on the class's primary verdict, with a stratified-dependency corroboration lift."""
    v = (entry or {}).get("verdict")
    ev = (entry or {}).get("evidence_state")
    if ev == "data_unavailable" or v in (None, "data_unavailable"):
        return _sig("unmeasured", "not measured")
    vs = str(v).lower()
    strat = str((entry or {}).get("stratified_dependency_class") or "").lower()
    if any(k in vs for k in _POSITIVE_STRONG):
        return _sig("strong", str(v))
    if "dependency" in vs or "stratified" in vs or "biomarker" in strat or "dependency" in strat:
        return _sig("moderate", str(v))
    if any(k in vs for k in _NEGATIVE):
        return _sig("absent", str(v))
    return _sig("weak", str(v))


def _class_conf(entry: dict) -> dict:
    if (entry or {}).get("evidence_state") != "measured":
        return _conf("unmeasured")
    strat = str((entry or {}).get("stratified_dependency_class") or "").lower()
    if "biomarker" in strat or "dependency" in strat:
        return _conf("high", "measured + stratified-dependency")
    return _conf("moderate", "measured")


def _support(entry: dict) -> str:
    bits = []
    for k in ("recurrence_class", "patient_class", "stratified_dependency_class",
              "amp_expr_dependency_class", "genie_sv_recurrence_class"):
        val = (entry or {}).get(k)
        if val and val != "data_unavailable":
            bits.append(f"{k.replace('_class', '').replace('_', ' ')}: {val}")
    return " · ".join(bits)


def genomic_question_table(headline: dict, cards: Optional[list] = None) -> list:
    """Per-alteration-class question rows from headline.genomic_alteration_by_class. Verdict-inert;
    tolerant of an absent/partial by_class map (an absent class → an unmeasured row, never omitted, so
    the hero always shows the full SNV/CN/fusion ladder + which class is a named gap)."""
    by_class = (headline or {}).get("genomic_alteration_by_class") or {}
    rows = []
    for cls, (qid, question) in _CLASS_Q:
        entry = by_class.get(cls) or {}
        rows.append(_row(qid, question, str(entry.get("verdict") or "—"),
                         _support(entry), _class_signal(entry), _class_conf(entry)))
    return rows


__all__ = ["genomic_question_table"]
