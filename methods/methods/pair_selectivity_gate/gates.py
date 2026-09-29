"""pair_selectivity_gate.gates — AND/OR/NOT bispecific antigen-pair selectivity (pure, no S3).

Ports the biologics-target-discovery bstrat.gates logic-gate + coexpression math onto the framework's
per-sample TPM long products. A NET-NEW capability: the v2 framework has no two-antigen selectivity
anywhere — this scores, for an antigen PAIR {A, B}, how tumor-selective a logic-gated bispecific
(AND / OR / NOT) construct would be, per the biologics repo's clean-antigen physics.

  AND — engage where BOTH present: raises selectivity when each antigen alone is too broad.
  OR  — engage where EITHER present: heterogeneity backstop (an OR gate is only as clean as its
        dirtiest arm — watch normal-tissue breadth).
  NOT — engage where A present AND veto antigen B ABSENT: on-target/off-tumor rescue (B marks the
        normal tissue to spare); veto uses a stricter "truly off" threshold.

Per-sample positivity → per-group (TCGA study / GTEx tissue) positive-FRACTION → selectivity.
THEME-1 FIX (carried from the source repo's own audit): emit BOTH max_essential_normal_fraction AND
max_any_normal_fraction, so a pair that fires in a NON-essential normal tissue (skin/salivary) is not
scored clean just because no life-critical organ trips. Coverage gate + resolution floor mirror the
source (below).

THE HONEST LIMITATION (stated on every result): bulk co-expression in a SAMPLE is necessary but NOT
sufficient for same-CELL co-expression, which is what an AND-gate bispecific actually requires
(avidity). Same-cell confirmation needs single-cell / spatial (CELLxGENE Census) — a documented gap.
This scorer is candidate GENERATION: it nominates pairs to confirm, it does not confirm avidity.
"""

from __future__ import annotations

from typing import Optional

# --- thresholds (linear TPM), ported from the biologics ScoringConfig ---
GATE_POSITIVE_THRESHOLD_TPM = 10.0  # a sample counts as antigen-positive at/above this (linear TPM)
NOT_GATE_VETO_ABSENT_TPM = 5.0  # stricter "truly off" bar for the NOT veto arm
AND_GATE_MIN_COFRACTION = 0.30  # AND/NOT pairs below this tumor coverage are low-value (score 0)
ESSENTIAL_FRACTION_RESOLUTION_FLOOR = 0.01  # 1/n_min statistical-resolution floor → caps selectivity ~100x

# Essential normal GTEx tissues (life-critical). Shared intent with the window arc's essential set;
# GTEx `tissue` labels in the long product. ⚠️ A COPY, not the source of truth — it must track
# `essential_organs.GTEX_CROSSWALK`, and the essential-organ coverage guard now pins it there (see
# the longer note in exon_window/classify.py for why the duplication was invisible until 2026-09-18).
ESSENTIAL_GTEX_TISSUES = frozenset(
    {
        "ADRENAL_GLAND",
        "BLOOD",
        "BLOOD_VESSEL",
        "BONE_MARROW",
        "BRAIN",
        "COLON",  # + 2026-09-18 with the `gut` promotion in CANONICAL_VITAL_ORGANS
        "HEART",
        "KIDNEY",
        "LIVER",
        "LUNG",
        "MUSCLE",
        "NERVE",
        "PANCREAS",
        "PITUITARY",
        # + 2026-09-18 with `small_intestine` in CANONICAL_VITAL_ORGANS. GTEx COLON pools mucosa with
        # muscularis, so it is the LESS sensitive intestinal-epithelium detector; see window.py.
        "SMALL_INTESTINE",
        "SPLEEN",
        "THYROID",
    }
)

_GATES = ("AND", "OR", "NOT")


def _positive_fraction_by_group(a_by_group: dict, b_by_group: dict, gate: str) -> dict:
    """Given per-group lists of per-sample (a_tpm, b_tpm) pairs, compute the gate-positive FRACTION
    per group. a_by_group / b_by_group: {group: [tpm, ...]} aligned by sample within a group.

    Returns {group: positive_fraction}. A group needs both arms measured; groups missing either are
    skipped (honest — a gate needs both antigens observed in that group)."""
    out = {}
    for group, pairs in _iter_aligned(a_by_group, b_by_group):
        n = len(pairs)
        if n == 0:
            continue
        pos = 0
        for a_tpm, b_tpm in pairs:
            if gate == "AND":
                hit = (a_tpm >= GATE_POSITIVE_THRESHOLD_TPM) and (b_tpm >= GATE_POSITIVE_THRESHOLD_TPM)
            elif gate == "OR":
                hit = (a_tpm >= GATE_POSITIVE_THRESHOLD_TPM) or (b_tpm >= GATE_POSITIVE_THRESHOLD_TPM)
            else:  # NOT: A present AND veto B truly absent
                hit = (a_tpm >= GATE_POSITIVE_THRESHOLD_TPM) and (b_tpm < NOT_GATE_VETO_ABSENT_TPM)
            if hit:
                pos += 1
        out[group] = pos / n
    return out


def _iter_aligned(a_by_group: dict, b_by_group: dict):
    """Yield (group, [(a_tpm, b_tpm), ...]) for groups where BOTH arms have per-sample values aligned
    by sample_id. Inputs are {group: {sample_id: tpm}}."""
    for group in a_by_group:
        if group not in b_by_group:
            continue
        a_samples, b_samples = a_by_group[group], b_by_group[group]
        common = a_samples.keys() & b_samples.keys()
        pairs = [(a_samples[s], b_samples[s]) for s in common]
        if pairs:
            yield group, pairs


def reduce_gate(gate: str, tumor_frac_by_study: dict, normal_frac_by_tissue: dict, tumor_study: str) -> dict:
    """Reduce per-group positive-fractions to a GateScanResult-shaped dict for one tumor study.

    Mirrors the biologics coexpression_scan._reduce_pair_from_fractions: tumor_fraction / max-essential-
    normal denominator (floored), with the AND/NOT coverage gate zeroing sub-threshold pairs. Emits
    BOTH essential + any-normal maxima (Theme-1)."""
    tumor_fraction = tumor_frac_by_study.get(tumor_study)
    ess = {t: f for t, f in normal_frac_by_tissue.items() if t in ESSENTIAL_GTEX_TISSUES}
    max_ess_organ, max_ess_frac = max(ess.items(), key=lambda kv: kv[1]) if ess else ("none", 0.0)
    max_any_organ, max_any_frac = (
        max(normal_frac_by_tissue.items(), key=lambda kv: kv[1]) if normal_frac_by_tissue else ("none", 0.0)
    )

    if tumor_fraction is None:
        selectivity = None
    elif gate in ("AND", "NOT") and tumor_fraction < AND_GATE_MIN_COFRACTION:
        selectivity = 0.0  # coverage gate — a rare-in-tumor gate is low-value regardless of ratio
    else:
        ess_denom = max(max_ess_frac, ESSENTIAL_FRACTION_RESOLUTION_FLOOR)
        selectivity = tumor_fraction / ess_denom

    return {
        "gate": gate,
        "tumor_study": tumor_study,
        "tumor_fraction": round(tumor_fraction, 4) if tumor_fraction is not None else None,
        "max_essential_normal_fraction": round(max_ess_frac, 4),
        "max_essential_normal_tissue": max_ess_organ,
        "max_any_normal_fraction": round(max_any_frac, 4),  # THEME-1: full-normal panel
        "max_any_normal_tissue": max_any_organ,
        "selectivity": round(selectivity, 2) if selectivity is not None else None,
        "call": _call(gate, tumor_fraction, max_ess_frac, max_any_frac, selectivity),
    }


def classify_and_selectivity(
    tumor_frac: Optional[float], max_ess_frac: float, max_any_frac: float, selectivity: Optional[float]
) -> str:
    """Categorical companion to the free-text AND-gate `call` (2026-08-24 druggability audit).

    best_and_call is a human-readable string, so the categorical-only rules engine could not key on
    it — the bispecific-necessity signal reached only the LLM narrative. This distils the SAME AND-gate
    logic in `_call` into a rule-matchable class (mirrors the {tumor, essential, any}-fraction cuts):
      selective_and_pair                     tumor-selective AND clean on non-essential normal too
      selective_but_broad_tissue_liability   tumor-selective vs ESSENTIAL normal, but fires broadly in
                                             NON-essential normal (THEME-1 broad-tissue liability)
      not_selective                          AND-gate also fires in essential normal tissue
      no_selective_pair                      co-expression too rare in tumor (< coverage floor) — low value
      data_unavailable                       no tumor samples / no scored AND pair
    """
    if tumor_frac is None or selectivity is None:
        return "data_unavailable"
    if tumor_frac < AND_GATE_MIN_COFRACTION:
        return "no_selective_pair"
    if max_ess_frac >= AND_GATE_MIN_COFRACTION:
        return "not_selective"
    if max_any_frac >= AND_GATE_MIN_COFRACTION:
        return "selective_but_broad_tissue_liability"
    return "selective_and_pair"


def _call(
    gate: str, tumor_frac: Optional[float], max_ess_frac: float, max_any_frac: float, selectivity: Optional[float]
) -> str:
    if tumor_frac is None:
        return "no tumor samples for this study — cannot evaluate"
    if gate == "AND":
        if tumor_frac < AND_GATE_MIN_COFRACTION:
            return f"AND-gate co-expression too rare in tumor ({tumor_frac:.0%}) — low value"
        if max_ess_frac >= AND_GATE_MIN_COFRACTION:
            return f"AND-gate also fires in essential normal tissue ({max_ess_frac:.0%}) — not selective"
        note = f"AND-gate tumor-selective ({tumor_frac:.0%} tumor vs {max_ess_frac:.0%} essential-normal, {selectivity:.0f}x)"
        if max_any_frac >= AND_GATE_MIN_COFRACTION:
            note += f"; CAUTION non-essential normal fires {max_any_frac:.0%} — broad-tissue liability"
        return note
    if gate == "NOT":
        if tumor_frac < AND_GATE_MIN_COFRACTION:
            return f"NOT-gate fires rarely in tumor ({tumor_frac:.0%}) — low coverage"
        return f"NOT-gate: antigen present w/ veto absent in {tumor_frac:.0%} of tumor; veto-arm must mark a normal tissue to spare"
    return f"OR-gate coverage {tumor_frac:.0%} of tumor (heterogeneity backstop; OR is only as clean as its dirtiest arm — check normal breadth {max_any_frac:.0%})"


# The mandatory avidity caveat, attached to every scan result (candidate-generation discipline).
AVIDITY_CAVEAT = (
    "Bulk co-expression in a tumor SAMPLE is necessary but NOT sufficient for same-CELL co-expression, "
    "which is what an AND-gate bispecific requires (avidity). Two antigens can be high in a sample yet "
    "on different cells. This scan NOMINATES pairs to confirm; same-cell / co-localization confirmation "
    "needs single-cell (CELLxGENE Census same-cell coexpression) or spatial data — a documented gap."
)
