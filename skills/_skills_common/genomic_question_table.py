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

from _skills_common.question_table_core import conf as _conf
from _skills_common.question_table_core import row as _row
from _skills_common.question_table_core import sig as _sig  # shared Signal/Confidence vocab

# Per-class row: (display id, sub-question). Order mirrors the alteration-class ladder.
_CLASS_Q = [
    ("snv_indel", ("SNV", "Recurrent SNV/indel driver, or biomarker-stratified dependency?")),
    ("copy_number", ("CN", "Copy-number driver — focal amplification or deletion?")),
    ("fusion", ("Fusion", "Recurrent fusion / rearrangement driver?")),
    ("splice", ("Splice", "Recurrent exon-skipping driver (e.g. METex14)?")),
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
    for k in (
        "recurrence_class",
        "patient_class",
        "stratified_dependency_class",
        "amp_expr_dependency_class",
        "genie_sv_recurrence_class",
        "event_id",
        "n_depmap_carriers",
    ):  # splice-class support fields
        val = (entry or {}).get(k)
        if val and val != "data_unavailable":
            bits.append(f"{k.replace('_class', '').replace('_', ' ')}: {val}")
    return " · ".join(bits)


def _recurrence_concordance_integrated_signal(claim: dict) -> dict:
    """Project the L2b `recurrence_concordance` claim (genomic_claims.py) into the SNV row's
    `integrated_signal` surface — a verdict-INERT, two-directional presentation payload. Surfaces both
    directions (the encouraging cross-cohort recurrent-driver agreement + the panel/exome-masking or
    single-source caveat), the honest corroboration/boundary-sensitivity annotation, and the uniform
    per-cohort source_support list so a consumer renders the integrated cross-source read WITHOUT
    prose-parsing. Carries NO signal tier / polarity / fill — it never routes the verdict; it is the
    answer's cross-source annotation, not a meter cell. Mirrors the coverage (#1578) / abundance (#1594)
    / normal-liability (#1584) surface-consumption precedents.

    PASS-THROUGH on `corroboration`: the token is copied VERBATIM into the annotation (no map, nothing to
    keep in step) — see `_CORROBORATION_READERS` in test_claim_ladder_vocabulary_coverage.py (#1643)."""
    qual = claim.get("qualifying_signal")
    pos = claim.get("positive_signal") or {}
    boundary = bool(claim.get("boundary_sensitive"))
    # A one-line human headline that always names BOTH directions (or the concordant confirmation),
    # flagged boundary-sensitive when the class rests on a lone uncorroborated cohort arm.
    if qual:
        headline = f"{pos.get('statement', '')} However — {qual.get('statement', '')}"
    else:
        headline = (
            f"{pos.get('statement', '')} MC3 exome and GENIE panel AGREE on the driver-recurrence call "
            "(no cross-cohort split)."
        )
    if boundary:
        headline += f" [boundary-sensitive: {claim.get('boundary_note', '')}]"
    return {
        "kind": "recurrence_concordance",
        "concordance_class": claim.get("concordance_class"),
        "corroboration": claim.get("corroboration"),
        "grain": claim.get("grain"),
        "corroborating_independent_arm_count": claim.get("corroborating_independent_arm_count"),
        "resolved_source_count": claim.get("resolved_source_count"),
        "boundary_sensitive": boundary,
        "boundary_note": claim.get("boundary_note"),
        "positive_signal": pos or None,
        "qualifying_signal": qual,
        "source_support": claim.get("source_support"),
        "headline": headline,
        "provenance_ref": "claim_vector.recurrence_concordance",
    }


def genomic_question_table(headline: dict, cards: Optional[list] = None) -> list:
    """Per-alteration-class question rows from headline.genomic_alteration_by_class. Verdict-inert;
    tolerant of an absent/partial by_class map (an absent class → an unmeasured row, never omitted, so
    the hero always shows the full SNV/CN/fusion ladder + which class is a named gap)."""
    by_class = (headline or {}).get("genomic_alteration_by_class") or {}
    rows = []
    for cls, (qid, question) in _CLASS_Q:
        entry = by_class.get(cls) or {}
        rows.append(
            _row(
                qid,
                question,
                str(entry.get("verdict") or "—"),
                _support(entry),
                _class_signal(entry),
                _class_conf(entry),
            )
        )
    # SK#1750 L2b→L3: SURFACE the L2b-5 recurrence_concordance claim (built by #1637, read by nothing
    # until now) as a first-class cross-source annotation on the SNV / driver-recurrence question row.
    # Attached only when the claim resolves (key omitted otherwise → row byte-stable). Reads only the
    # ALREADY-BUILT claim_vector on the headline (built in run.py before this table), so it perturbs no
    # census aperture and no verdict. Verdict-inert: the row's signal/confidence meter cells are UNCHANGED
    # — this adds an annotation, never a tier. Mirrors the presence/safety G3.1/G3.2 surface pattern.
    rec = ((headline or {}).get("claim_vector") or {}).get("recurrence_concordance")
    if rec:
        for r in rows:
            if r.get("id") == "SNV":
                r["integrated_signal"] = _recurrence_concordance_integrated_signal(rec)
                break
    return rows


__all__ = ["genomic_question_table"]
