"""Presence CLAIM VECTOR + KEY SIGNALS — a modality-blind, verdict-INERT integration of the
tumor-presence card evidence into (signal × reliability) per claim, plus a brief cited read.

WHAT THIS IS: an additive projection over the ALREADY-computed presence headline + card summaries.
It stacks heterogeneous card evidence into four ORTHOGONAL claims —
  A abundance · B tumor-elevation · C malignant-intrinsic · D generality —
each with a signal tier and a reliability tier, following the combination discipline:
evidence corroborates WITHIN a claim (sub-additively), conflicts penalize, and claims are kept
SEPARATE across (a weak C never degrades a strong B — they are not averaged).

WHAT THIS IS NOT (the honesty discipline):
  * NOT a verdict input. This is a one-way VIEW over decision['headline']; it never feeds a rule,
    resolver, gate, or the collapsed presence_verdict. The verdict spine is byte-identical with or
    without it (frozen by the golden-spine test).
  * NOT calibrated. Tiers preserve ORDER (strong>moderate>weak>absent); gaps are not metric.
  * gap ≠ negative. `unmeasured` (data_unavailable) is distinct from `absent` (measured negative).
  * modality-BLIND. Modality gating is a CROSS-lens (target-profile) concern; here each claim only
    carries a light `informs` routing tag, never a gate.

Consumed by tumor-presence run.py (_headline) and surfaced in the _synthesis_facet package that the
composed target-profile fan-out reads.
"""
from __future__ import annotations
import re
from typing import Optional

CLAIM_NAME = {"A": "abundance", "B": "tumor-elevation", "C": "malignant-intrinsic", "D": "generality"}
# light-touch routing (which downstream lens each claim informs) — NOT a gate.
CLAIM_INFORMS = {
    "A": "abundance — informs every modality (a degrader/SM needs the protein present)",
    "B": "tumor-elevation — context for the selectivity / therapeutic-window lens",
    "C": "malignant-cell-intrinsic — informs tumor-cell-targeted modalities (ADC/TCE/CAR)",
    "D": "generality/breadth — patient-population & pan-cancer framing",
}
_SIG_ORD = {"strong": 3, "moderate": 2, "weak": 1, "absent": 0, "negative": 0, "unmeasured": None}


def _by_id(cards):
    return {c["card_id"]: (c.get("summary") or {}) for c in (cards or [])}


def _f(v, nd=2):
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else "n/a"


# ── the four claims (each returns {signal, reliability, evidence, conflict}) ───────────────────
def _claim_A(h, c):
    trd = c.get("tumor-rna-distribution", {})
    cp, pct, med = trd.get("control_position"), trd.get("allgene_percentile"), trd.get("median_log2tpm")
    npos = mpos = None
    if isinstance(cp, str):
        m = re.search(r"above (\d+)/(\d+) positive", cp)
        if m:
            npos, mpos = int(m.group(1)), int(m.group(2))
    if npos is not None:
        if npos == mpos and mpos:
            band, sig = "at/above ALL positive antigens", "strong"
        elif npos > 0:
            band, sig = f"within positives ({npos}/{mpos})", "moderate"
        elif isinstance(pct, (int, float)) and pct >= 60:
            band, sig = "mid (above negatives, below positives)", "weak"
        else:
            band, sig = "floor", "absent"
    elif isinstance(pct, (int, float)):
        sig = "strong" if pct >= 95 else "moderate" if pct >= 75 else "weak"
        band = f"{pct:.0f}th all-gene pct"
    elif isinstance(med, (int, float)):
        sig = "strong" if med >= 5 else "moderate" if med >= 3.46 else "weak"
        band = f"raw median {med:.1f} log2TPM (anchor n/a)"
    else:
        return {"signal": "unmeasured", "reliability": "unmeasured", "evidence": "no abundance anchor", "conflict": None, "informs": CLAIM_INFORMS["A"]}
    proxy = h.get("bulk_rna_proxy_quality")
    rel = "high" if proxy == "rna_confirmed_by_protein" else "moderate" if proxy == "rna_positive_proxy_partial" else "low"
    return {"signal": sig, "reliability": rel, "conflict": None, "informs": CLAIM_INFORMS["A"],
            "evidence": f"anchored: {band}" + (f", {pct:.0f}th pct" if isinstance(pct, (int, float)) else "") + f"; proxy={proxy}"}


def _dir(cls):
    if not cls:
        return None
    if "strong_up" in cls:
        return ("up", 3)
    if "modest_up" in cls or "modest_upregulation" in cls:
        return ("up", 2)
    if "not_informative" in cls or cls in ("ns", "not_significant", "small_effect"):
        return ("flat", 0)
    if "down" in cls:
        return ("down", -2)
    return None


def _claim_B(h, c):
    tva = c.get("tumor-rna-vs-adjacent", {}); cp = c.get("tumor-protein-abundance-cptac", {})
    dge = _dir(tva.get("expression_call_class")); cpt = _dir(cp.get("protein_expression_class"))
    arms = []
    if dge:
        arms.append(("RNA-DGE", dge, tva.get("log2_fc"), tva.get("q_value")))
    if cpt:
        arms.append(("CPTAC", cpt, cp.get("protein_effect_size"), cp.get("protein_bh_q_value")))
    if not arms:
        return {"signal": "unmeasured", "reliability": "unmeasured", "evidence": "no tumor-vs-normal arm", "conflict": None, "informs": CLAIM_INFORMS["B"]}
    ups = [a for a in arms if a[1][0] == "up"]; downs = [a for a in arms if a[1][0] == "down"]
    conflict = None
    if ups and downs:
        conflict, sig, rel = "RNA/protein DISAGREE on direction", "weak", "low"
    elif ups:
        sig = "strong" if max(a[1][1] for a in ups) == 3 else "moderate"
        rel = "high" if len(ups) >= 2 else "moderate"
    else:
        sig, rel = "absent", "moderate"
    ev = "; ".join(f"{n}:{d[0]}(fc/eff={_f(fc)},q={q:.0e})" if isinstance(q, (int, float)) else f"{n}:{d[0]}" for n, d, fc, q in arms)
    return {"signal": sig, "reliability": rel, "evidence": ev, "conflict": conflict, "informs": CLAIM_INFORMS["B"]}


def _claim_C(h, c):
    cls = h.get("sc_expression_class") or c.get("tumor-scrna-celltype-expression", {}).get("sc_expression_class")
    frac, n = h.get("sc_malignant_detection_fraction"), h.get("sc_n_donor_groups")
    if not cls or cls == "data_unavailable":
        return {"signal": "unmeasured", "reliability": "unmeasured", "evidence": "no single-cell for indication", "conflict": None, "informs": CLAIM_INFORMS["C"]}
    sig = {"malignant_broadly_detected": "strong", "malignant_subset_detected": "weak",
           "microenvironment_dominant": "negative", "broadly_low": "absent"}.get(cls, "weak")
    rel = "high" if isinstance(n, int) and n >= 100 else "moderate" if isinstance(n, int) and n >= 20 else "low"
    return {"signal": sig, "reliability": rel, "conflict": None, "informs": CLAIM_INFORMS["C"],
            "evidence": f"{cls} (malignant frac {_f(frac)}, n={n} donors)"}


def _claim_D(h, c):
    br = h.get("tumor_elevation_breadth_class") or h.get("rna_tumor_elevation_breadth_class")
    dist = c.get("tumor-rna-distribution", {}).get("distribution_pattern")
    sig = {"broadly_tumor_elevated": "strong", "multi_tumor_elevated": "moderate",
           "single_tumor_elevated": "weak", "not_tumor_elevated": "absent"}.get(br, "unmeasured")
    return {"signal": sig, "reliability": "moderate", "evidence": f"breadth={br}; dist={dist}", "conflict": None, "informs": CLAIM_INFORMS["D"]}


def _homogeneity(h, c):
    hc = h.get("sc_tce_homogeneity_class") or c.get("tumor-scrna-celltype-expression", {}).get("tce_homogeneity_class")
    return hc if hc and hc != "data_unavailable" else None


def presence_claim_vector(headline: dict, cards: list) -> dict:
    """The modality-blind claim vector: {A,B,C,D: {signal, reliability, evidence, informs}, homogeneity}.
    Verdict-inert projection over the computed headline + card summaries."""
    c = _by_id(cards)
    return {"A": _claim_A(headline, c), "B": _claim_B(headline, c), "C": _claim_C(headline, c),
            "D": _claim_D(headline, c), "homogeneity": _homogeneity(headline, c),
            "_disclaimer": ("Modality-blind, verdict-INERT projection of the presence cards into orthogonal "
                            "claims (A abundance / B tumor-elevation / C malignant-intrinsic / D generality), "
                            "each signal×reliability. Claims are NOT additive; a weak C does not degrade a "
                            "strong B. Never feeds the presence_verdict.")}


# ── key signals: a brief, direct, CITED read (deterministic; available without the LLM) ────────
def presence_key_signals(headline: dict, cards: list) -> dict:
    c = _by_id(cards); vec = presence_claim_vector(headline, cards)
    trd = c.get("tumor-rna-distribution", {}); tva = c.get("tumor-rna-vs-adjacent", {}); cp = c.get("tumor-protein-abundance-cptac", {}); br = c.get("tumor-elevation-breadth", {})

    def support(k):
        cl = vec[k]
        if _SIG_ORD.get(cl["signal"]) is None or _SIG_ORD[cl["signal"]] < 2:
            return None
        if k == "A":
            pos, pct = trd.get("control_position", ""), trd.get("allgene_percentile")
            anchor = pos if isinstance(pos, str) and "positive" in pos else f"median {_f(trd.get('median_log2tpm'),1)} log2TPM"
            lead = f"{pct:.0f}th percentile ({anchor})" if isinstance(pct, (int, float)) else anchor
            return f"Abundant in tumors — {lead} [tumor-rna-distribution]"
        if k == "B":
            bits = []
            if isinstance(tva.get("log2_fc"), (int, float)) and tva["log2_fc"] > 0.4:
                bits.append(f"{2**tva['log2_fc']:.1f}x vs adjacent (log2FC {_f(tva['log2_fc'],1)}, q={tva.get('q_value',0):.0e})")
            if isinstance(cp.get("protein_effect_size"), (int, float)) and (cp.get("protein_bh_q_value") or 1) < 0.05 and cp["protein_effect_size"] > 0.3:
                bits.append(f"protein-confirmed (CPTAC effect {_f(cp['protein_effect_size'])}, q={cp['protein_bh_q_value']:.0e})")
            return ("Tumor-elevated vs normal — " + "; ".join(bits) + " [DGE + CPTAC]") if bits else None
        if k == "C":
            return f"Expressed in cancer cells — {_f((headline.get('sc_malignant_detection_fraction') or 0)*100,0)}% of malignant cells (n={headline.get('sc_n_donor_groups')} donors) [single-cell]"
        if k == "D":
            ne, nt = br.get("n_cohorts_elevated"), br.get("n_cohorts_tested")
            return f"Broad — protein-elevated in {ne}/{nt} cancer cohorts [tumor-elevation-breadth]" if isinstance(ne, int) and isinstance(nt, int) else None
        return None

    ranked = sorted("ABCD", key=lambda k: -(_SIG_ORD.get(vec[k]["signal"]) or -1))
    supports = [s for s in (support(k) for k in ranked) if s][:3]
    # one key caveat = weakest measured decision-critical claim, cited
    crit = [(k, _SIG_ORD[vec[k]["signal"]]) for k in "ABC" if _SIG_ORD.get(vec[k]["signal"]) is not None]
    caveat = None
    if crit:
        k, tier = min(crit, key=lambda kv: kv[1])
        if k == "A" and tier <= 1:
            caveat = f"Mid-tier abundance — {trd.get('control_position','')} [tumor-rna-distribution]"
        elif k == "C" and tier <= 1:
            caveat = f"Antigen-heterogeneous — only {_f((headline.get('sc_malignant_detection_fraction') or 0)*100,0)}% of malignant cells express it [single-cell]"
        elif k == "B" and tier <= 1:
            caveat = "Tumor-vs-normal elevation not established (contrast flat/unavailable) [DGE + CPTAC]"
    if caveat is None and "broad" in str(headline.get("normal_tissue_ihc_breadth_class") or ""):
        caveat = "Broadly expressed in normal tissue -> therapeutic-window liability [normal comparators]"
    # deterministic headline from the vector (NOT the LLM)
    sa, sb = vec["A"]["signal"], vec["B"]["signal"]
    if _SIG_ORD.get(sa) and _SIG_ORD.get(sb) and _SIG_ORD[sa] >= 2 and _SIG_ORD[sb] >= 2:
        head = "Abundant and tumor-elevated."
    elif supports:
        head = "Present, with caveats."
    else:
        head = "Presence largely unmeasured or not distinguishing."
    return {"headline": head, "supports": supports, "caveat": caveat}


# ── SUBTYPE-scoped claim vector (per stratum) ─────────────────────────────────────────────────
# When a (target, indication, SUBTYPE) is the question, the pooled indication vector flattens the
# per-stratum signal (e.g. CD274 is broadly-low pooled in COADREAD but a strong MSI-H signal). This
# projects the strata-varying claims per molecular subtype from the ALREADY-resolved
# tumor-rna-distribution-by-subtype card's per_subgroup_metrics (LIVE): Claim A (abundance) and a
# distributional Claim B (fraction of stratum tumours above GTEx-normal p95) are computable per
# stratum NOW. Claim C (single-cell) and protein-confirmation stay INDICATION-grain (whole-cohort /
# pooled) — carried + labelled, never faked per stratum. Verdict-inert, like the pooled vector.
def _tier_from_median(med):
    if not isinstance(med, (int, float)):
        return "unmeasured"
    return "strong" if med >= 5 else "moderate" if med >= 3.46 else "weak" if med >= 1 else "absent"


def _tier_from_fraction_above_normal(fa):
    if not isinstance(fa, (int, float)):
        return "unmeasured"
    return "strong" if fa >= 0.5 else "moderate" if fa >= 0.2 else "weak" if fa >= 0.05 else "absent"


def presence_claim_vector_by_subtype(cards: list) -> Optional[dict]:
    """Per-stratum claim vector (A abundance + distributional B) from per_subgroup_metrics. Returns
    None when the indication has no subtype axis. C / protein remain indication-grain (flagged)."""
    c = _by_id(cards)
    s = c.get("tumor-rna-distribution-by-subtype", {})
    if not isinstance(s, dict) or not s.get("subtype_axis_available"):
        return None
    strata = {}
    for r in (s.get("per_subgroup_metrics") or []):
        if not isinstance(r, dict):   # tolerate simplified/frozen fixtures where rows aren't full dicts
            continue
        sid = r.get("stratum_id")
        if not sid:
            continue
        med, fa, n = r.get("median_log2tpm"), r.get("fraction_tumor_above_normal_p95"), r.get("n_tumor_samples")
        rel = "high" if isinstance(n, int) and n >= 100 else "moderate" if isinstance(n, int) and n >= 30 else "low"
        strata[sid] = {
            "A": {"signal": _tier_from_median(med), "reliability": rel,
                  "evidence": f"stratum median {_f(med, 1)} log2TPM, n={n}"},
            "B": {"signal": _tier_from_fraction_above_normal(fa), "reliability": "moderate" if isinstance(fa, (int, float)) else "unmeasured",
                  "evidence": (f"{_f((fa or 0) * 100, 0)}% of stratum tumours > GTEx-normal p95 (distributional, not the DEG)"
                               if isinstance(fa, (int, float)) else "no per-stratum normal window")},
            "n_tumor_samples": n,
        }
    return {
        "stratification_class": s.get("subtype_stratification_class"),
        "subtype_variance_explained": s.get("subtype_variance_explained"),
        "subtype_effect_size_class": s.get("subtype_effect_size_class"),
        "which_subtypes_separate": s.get("which_subtypes_separate"),
        "n_subtypes_measured": s.get("n_subtypes_measured"),
        "strata": strata,
        "_indication_grain_claims": "C (single-cell malignant) and protein-confirmation are NOT stratified "
                                    "(single-cell pooled; CPTAC whole-cohort) — read them from the pooled claim_vector.",
        "_disclaimer": ("Per-stratum claim vector — verdict-INERT. Only claims A (abundance) and a distributional "
                        "B (fraction > GTEx-normal p95) are live per subtype (from per_subgroup_metrics); a pooled "
                        "indication read can flatten a subtype-concentrated signal (cf. CD274/MSI-H). ε² negligible "
                        "→ subtype is NOT a useful selection axis; small-n strata are underpowered."),
    }


__all__ = ["presence_claim_vector", "presence_claim_vector_by_subtype", "presence_key_signals",
           "CLAIM_NAME", "CLAIM_INFORMS"]
