"""Presence CLAIM VECTOR + KEY SIGNALS — a modality-blind, verdict-INERT integration of the
tumor-presence card evidence into (signal × corroboration) per claim, plus a brief cited read.

WHAT THIS IS: an additive projection over the ALREADY-computed presence headline + card summaries.
It stacks heterogeneous card evidence into four ORTHOGONAL claims —
  A abundance · B tumor-elevation · C malignant-intrinsic · D generality —
each with a signal tier and a corroboration tier, following the combination discipline:
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

# Presence builds its claims MANUALLY (the signal/corroboration/conflict for a claim are legitimately
# COUPLED — e.g. the abundance-floor downgrades corroboration AND raises a conflict together — so the
# ClaimSpec signal_fn/corroboration_fn split does not fit cleanly). But it shares the core PRIMITIVES
# (ordinal scale, card indexer, number formatter) so those can never drift from the fleet contract.
from _skills_common.claim_vector_core import SIGNAL_ORD as _SIG_ORD
from _skills_common.claim_vector_core import cards_by_id as _by_id
from _skills_common.claim_vector_core import fmt as _f

CLAIM_NAME = {"A": "abundance", "B": "tumor-elevation", "C": "malignant-intrinsic", "D": "generality"}
# light-touch routing (which downstream lens each claim informs) — NOT a gate.
CLAIM_INFORMS = {
    "A": "abundance — informs every modality (a degrader/SM needs the protein present)",
    "B": "tumor-elevation — context for the selectivity / therapeutic-window lens",
    "C": "malignant-cell-intrinsic — informs tumor-cell-targeted modalities (ADC/TCE/CAR)",
    "D": "generality/breadth — patient-population & pan-cancer framing",
}


from _skills_common.claim_vector_core import build_summary_atom  # shared atom builder (Group D)


def _patom(card_id, summary, keys, entity, read):
    """Citable evidence atom for a presence claim: bind the load-bearing card VALUES to {card_id,
    fields} + entity keys. Presence builds its claims MANUALLY (not via ClaimSpec.atom_fn), so this is
    called inline in each _claim_*. Returns None when the source card is absent → the claim stays
    byte-stable (no evidence_atom key), matching the other axes' atom discipline."""
    return build_summary_atom(card_id=card_id, summary=summary, keys=keys, read=read, entity=entity)


# ── the four claims (each returns {signal, corroboration, evidence, conflict}) ───────────────────
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
            # B3 DE-CAP / Delta-2: `within positives` is a conservative control-anchor FLOOR, not a
            # ceiling. A top-percentile antigen that lands here sits below only the very highest curated
            # antigen — that is still STRONG abundance, and the old flat `moderate` understated every
            # top-pct within-positives target (e.g. EPCAM: 99.7th all-gene pct → was capped at moderate).
            # Let the calibrated all-gene percentile LEAD when it is stronger than the anchor; the anchor
            # remains the floor for mid/low percentiles. VERDICT-INERT (claim_vector never feeds the spine).
            if isinstance(pct, (int, float)) and pct >= 95:
                band, sig = f"within positives ({npos}/{mpos}); {pct:.0f}th all-gene pct (percentile-led)", "strong"
            else:
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
        return {
            "signal": "unmeasured",
            "corroboration": "unmeasured",
            "evidence": "no abundance anchor",
            "conflict": None,
            "informs": CLAIM_INFORMS["A"],
        }
    proxy = h.get("bulk_rna_proxy_quality")
    rel = (
        "high"
        if proxy == "rna_confirmed_by_protein"
        else "moderate"
        if proxy == "rna_positive_proxy_partial"
        else "low"
    )
    conflict = None
    note = None
    # LEVEL != breadth (Principle 2): if a level anchor reads bottom-decile while the abundance claim is
    # positive, cap corroboration and surface it — a `broadly_moderate` presence class can sit on a
    # bottom-decile absolute abundance (e.g. a protein detected everywhere but low-abundance). QUORUM-AWARE
    # (P0): only a HARD floor caps corroboration + raises the tension; a single-lens floor that upstream
    # demoted (orthogonally contradicted by IHC / 2nd platform / a top-decile anchor) is a soft NOTE, not a
    # corroboration-capping conflict — so a lone MS-panel artifact no longer leads the headline.
    _lenses = h.get("abundance_floor_low_lenses") or []
    if h.get("abundance_floor_flag") == "present_low_abundance":
        low = ", ".join(x.get("lens", "?") for x in _lenses)
        conflict = f"abundance-level floor: bottom-decile in {low} (breadth-positive but low absolute level)"
        rel = "low"
    elif h.get("abundance_floor_flag") == "present_low_abundance_single_lens":
        low = ", ".join(x.get("lens", "?") for x in _lenses)
        opp = ", ".join((_lenses[0].get("overridden_by") or [])) if _lenses else ""
        note = (
            f"single-lens low-abundance ({low}) overridden by orthogonal protein-present evidence"
            + (f" ({opp})" if opp else "")
            + " — not read as low"
        )
    # P1: antibody-IHC (HPA Pathology) is the MS-INDEPENDENT protein-in-tumor leg. When protein presence is
    # IHC-confirmed high it corroborates abundance (and lifts a proxy-floored corroboration off the floor),
    # resolving the "protein magnitude unsettled" read a bottom-decile MS panel would otherwise leave.
    if (c.get("hpa-pathology-cancer-ihc", {}) or {}).get("protein_presence_class") == "ihc_detected_high":
        note = ((note + "; ") if note else "") + "protein-present (HPA-IHC detected_high, MS-independent)"
        if rel == "low":
            rel = "moderate"
    # Corroboration for A (the RNA→protein proxy quality) comes from a DIFFERENT card than the signal
    # (tumor-rna-distribution): the RNA↔protein-concordance card for whichever arm the proxy was read
    # from (tumor CPTAC vs cell-line). Record it as a role-tagged corr_cite so the chip's corroboration
    # is traceable to its own source card, not silently attributed to the signal card.
    _proxy_src = h.get("bulk_rna_proxy_quality_source")
    _corr_card = (
        "rna-protein-concordance-tumor"
        if _proxy_src == "tumor"
        else "cellline-rna-protein-concordance"
        if _proxy_src == "cell_line"
        else None
    )
    corr_cite = {"card_id": _corr_card, "fields": ["rna_as_biomarker"]} if (_corr_card and proxy) else None
    return {
        "signal": sig,
        "corroboration": rel,
        "conflict": conflict,
        "informs": CLAIM_INFORMS["A"],
        "corr_cite": corr_cite,
        "evidence": f"anchored: {band}"
        + (f", {pct:.0f}th pct" if isinstance(pct, (int, float)) else "")
        + f"; proxy={proxy}"
        + (f"; {note}" if note else ""),
        "evidence_atom": _patom(
            "tumor-rna-distribution",
            trd,
            (
                "tumor_expression_class",
                "control_position_class",
                "allgene_percentile",
                "median_log2tpm",
                "p95_log2tpm",
                "distribution_pattern",
            ),
            {"measurement_type": "tumor_rna_expression", "sample_context": "tumor"},
            trd.get("tumor_expression_class"),
        ),
    }


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
    tva = c.get("tumor-rna-vs-adjacent", {})
    cp = c.get("tumor-protein-abundance-cptac", {})
    dge = _dir(tva.get("expression_call_class"))
    cpt = _dir(cp.get("protein_expression_class"))
    arms = []
    if dge:
        arms.append(("RNA-DGE", dge, tva.get("log2_fc"), tva.get("q_value")))
    if cpt:
        arms.append(("CPTAC", cpt, cp.get("protein_effect_size"), cp.get("protein_bh_q_value")))
    if not arms:
        return {
            "signal": "unmeasured",
            "corroboration": "unmeasured",
            "evidence": "no tumor-vs-normal arm",
            "conflict": None,
            "informs": CLAIM_INFORMS["B"],
        }
    ups = [a for a in arms if a[1][0] == "up"]
    downs = [a for a in arms if a[1][0] == "down"]
    flats = [a for a in arms if a[1][0] == "flat"]
    conflict = None
    if ups and downs:
        conflict, sig, rel = "RNA/protein DISAGREE on direction", "weak", "low"
    elif ups:
        sig = "strong" if max(a[1][1] for a in ups) == 3 else "moderate"
        rel = "high" if len(ups) >= 2 else "moderate"
        # comparator/post-transcriptional discordance: one arm elevated, another measured-FLAT (e.g.
        # CEACAM5 — RNA vs adjacent-colon flat, but CPTAC protein vs population-normal up). Surface it
        # (the elevation is real but not corroborated across arms/comparators) without moving the tier;
        # corroboration is capped since the arms don't agree. See P1 calibration finding (2026-08-18).
        if flats:
            up_names = "/".join(a[0] for a in ups)
            flat_names = "/".join(a[0] for a in flats)
            conflict = f"comparator discordance: {up_names} elevated but {flat_names} flat"
            rel = "moderate" if rel == "high" else rel
    else:
        sig, rel = "absent", "moderate"
    ev = "; ".join(
        f"{n}:{d[0]}(fc/eff={_f(fc)},q={q:.0e})" if isinstance(q, (int, float)) else f"{n}:{d[0]}"
        for n, d, fc, q in arms
    )
    # TWO-COMPARATOR surfacing (P1): the primary tier stays the MATCHED-adjacent (+CPTAC) call, but the DGE
    # card also carries a population/GTEx-normal contrast + the fraction of tumours above matched-normal p95
    # that a flat-vs-adjacent read silently drops. A flat-vs-adjacent with strong-vs-population elevation is
    # the signature of a target whose ADJACENT tissue already expresses it (the comparator, not the biology);
    # surface both comparators so the signal is legible and the narrator/question-table can cite it.
    gtex_fc, gtex_q = tva.get("gtex_log2_fc"), tva.get("gtex_q_value")
    frac_p95 = c.get("tumor-rna-distribution", {}).get("fraction_tumor_above_normal_p95")
    _cbits = []
    if isinstance(tva.get("log2_fc"), (int, float)):
        _cbits.append(f"vs matched-adjacent {_f(tva['log2_fc'], 2)} log2FC")
    if isinstance(gtex_fc, (int, float)):
        _cbits.append(
            f"vs GTEx-population {_f(gtex_fc, 2)} log2FC"
            + (f" (q={gtex_q:.0e})" if isinstance(gtex_q, (int, float)) else "")
        )
    if isinstance(frac_p95, (int, float)):
        _cbits.append(f"{_f(frac_p95 * 100, 0)}% tumours > matched-normal p95")
    comparator_detail = "; ".join(_cbits) or None
    if sig == "absent" and isinstance(gtex_fc, (int, float)) and gtex_fc >= 1.0:
        ev += " [flat vs adjacent but elevated vs GTEx-population — comparator-dependent]"
    return {
        "signal": sig,
        "corroboration": rel,
        "evidence": ev,
        "conflict": conflict,
        "informs": CLAIM_INFORMS["B"],
        "comparator_detail": comparator_detail,
        # cite the DGE arm (tumor-rna-vs-adjacent) with its values; the CPTAC protein arm is
        # corroboration (in the tier + evidence string), not double-cited under one card_id.
        "evidence_atom": _patom(
            "tumor-rna-vs-adjacent",
            tva,
            ("expression_call_class", "log2_fc", "q_value", "n_tumor"),
            {"measurement_type": "tumor_rna_dge_vs_adjacent", "sample_context": "tumor"},
            tva.get("expression_call_class"),
        ),
    }


def _claim_C(h, c):
    cls = h.get("sc_expression_class") or c.get("tumor-scrna-celltype-expression", {}).get("sc_expression_class")
    # INV-4: the malignant detection fraction is computed over the MALIGNANT-compartment donors
    # (malignant_n_donors), NOT the union donor-groups across all 5 compartments (n_donor_groups) —
    # cite the denominator that matches the fraction, and the field the evidence_atom below lists.
    frac, n = h.get("sc_malignant_detection_fraction"), h.get("sc_malignant_n_donors")
    if not cls or cls == "data_unavailable":
        return {
            "signal": "unmeasured",
            "corroboration": "unmeasured",
            "evidence": "no single-cell for indication",
            "conflict": None,
            "informs": CLAIM_INFORMS["C"],
        }
    sig = {
        "malignant_broadly_detected": "strong",
        "malignant_subset_detected": "weak",
        "microenvironment_dominant": "negative",
        "broadly_low": "absent",
    }.get(cls, "weak")
    rel = "high" if isinstance(n, int) and n >= 100 else "moderate" if isinstance(n, int) and n >= 20 else "low"
    # P2: the single-cell card carries antigen-ESCAPE risk + inter-donor consistency + the fraction of donors
    # broadly detecting — decision-critical for a TCE/CAR read but collapsed to one `homogeneity` string
    # elsewhere. Surface them here as a homogeneity_detail so the malignant-intrinsic claim is not read as a
    # bare detection fraction (89% detected + escape_risk_low + consistent across donors is a very different
    # antigen than 89% detected + high escape risk).
    scd = c.get("tumor-scrna-celltype-expression", {})
    escape = h.get("sc_tce_antigen_escape_class") or scd.get("tce_antigen_escape_class")
    consistency = h.get("sc_inter_donor_consistency_class") or scd.get("inter_donor_consistency_class")
    frac_broad = h.get("sc_fraction_donors_broadly_detecting")
    if frac_broad is None:
        frac_broad = scd.get("fraction_donors_broadly_detecting")
    _hbits = []
    if escape:
        _hbits.append(f"antigen-escape:{escape}")
    if consistency:
        _hbits.append(f"inter-donor:{consistency}")
    if isinstance(frac_broad, (int, float)):
        _hbits.append(f"{_f(frac_broad * 100, 0)}% donors broadly detecting")
    homogeneity_detail = "; ".join(_hbits) or None
    # Tier-1 sc utilization (#984): the reader also emits an ambient soup-leakage QC flag + the
    # malignant-annotation provenance + entity purity — signals that temper how much a malignant-detection
    # call should be TRUSTED but which no skill consumed. Fold them into claim-C CORROBORATION (a possible-
    # soup or phenotype-proxy call is less trustworthy) + surface a qc_detail caveat. VERDICT-INERT — this
    # only moves the claim-vector corroboration + adds a caveat; the sc ladder / presence_verdict is untouched.
    _CORR_DOWN = {"high": "moderate", "moderate": "low", "low": "low"}
    ambient = scd.get("ambient_contamination_risk")
    annot = scd.get("malignant_annotation_method")
    purity = scd.get("entity_purity")
    _qc = []
    if ambient == "possible":
        _qc.append("ambient-contamination:possible")
        rel = _CORR_DOWN.get(rel, rel)
    if annot in ("phenotype_proxy", "unspecified"):
        _qc.append(f"malignant-annotation:{annot}")
        rel = _CORR_DOWN.get(rel, rel)
    elif annot:
        _qc.append(f"malignant-annotation:{annot}")  # curated/infercnv — provenance note, no downgrade
    if purity == "multi_entity_pooled":
        _qc.append("entity:multi_entity_pooled")
    qc_detail = "; ".join(_qc) or None
    return {
        "signal": sig,
        "corroboration": rel,
        "conflict": None,
        "informs": CLAIM_INFORMS["C"],
        "homogeneity_detail": homogeneity_detail,
        "qc_detail": qc_detail,
        "evidence": f"{cls} (malignant frac {_f(frac)}, n={n} donors)"
        + (f"; {homogeneity_detail}" if homogeneity_detail else "")
        + (f"; QC[{qc_detail}]" if qc_detail else ""),
        "evidence_atom": _patom(
            "tumor-scrna-celltype-expression",
            c.get("tumor-scrna-celltype-expression", {}),
            (
                "sc_expression_class",
                "malignant_detection_fraction",
                "malignant_n_donors",
                "caf_vs_malignant_class",
                "top_microenvironment_compartment",
            ),
            {"measurement_type": "sc_tumor_celltype_expression", "sample_context": "tumor", "grain": "single_cell"},
            cls,
        ),
    }


def _claim_D(h, c):
    br = h.get("tumor_elevation_breadth_class") or h.get("rna_tumor_elevation_breadth_class")
    dist = c.get("tumor-rna-distribution", {}).get("distribution_pattern")
    sig = {
        "broadly_tumor_elevated": "strong",
        "multi_tumor_elevated": "moderate",
        "single_tumor_elevated": "weak",
        "not_tumor_elevated": "absent",
    }.get(br, "unmeasured")
    # Corroboration scales with HOW MANY cohorts/indications the breadth was tested over (was hardcoded
    # `moderate`, which over-stated a 2-cohort breadth). Uses the larger of the protein-cohort and
    # RNA-indication test counts the breadth card reports.
    n_tested = max(
        h.get("tumor_elevation_n_cohorts_tested") or 0, h.get("rna_tumor_elevation_n_indications_tested") or 0
    )
    # A corroboration tier for a claim we DECLINED TO STATE is not a coverage statement, it is a tier
    # attached to nothing — so the tier INHERITS the signal's unmeasured state. `n_tested` is a property of
    # the breadth card's cohort ROSTER, not of this target's measurement: it read 26 on 502 of 504 corpus
    # pairs, including 30 whose breadth was `data_unavailable`, which emitted the self-contradictory pair
    # (signal `unmeasured`, corroboration `high`) = "tested over 26 cohorts, answer withheld". The atlas
    # encodes `unmeasured` -> None (CLAIM_CORR_ORD) and already carries nulls in the sibling ::signal
    # column, so nulling here is representable and is what the sd/z machinery expects for an unmade claim.
    # Measured consequence of NOT doing this: the 1 corpus row whose roster was small (n_tested=3) became
    # the lone minority class of an otherwise-constant column, min_class_fraction 1/297, and a one-rung
    # displacement of 1/sqrt(p(1-p)) = 17.2 sigma -- 61% of that row's entire squared z-norm across 122
    # measured features, on a claim never made. Post-fix the column is honestly CONSTANT (n_classes 1,
    # every target's breadth genuinely tested over the same roster) instead of deceptively near-constant.
    # `_homogeneity` below normalises the identical `data_unavailable` sentinel; this is the same move.
    rel = (
        "unmeasured"
        if sig == "unmeasured"
        else "high"
        if n_tested >= 10
        else "moderate"
        if n_tested >= 5
        else "low"
        if n_tested >= 1
        else "unmeasured"
    )
    return {
        "signal": sig,
        "corroboration": rel,
        "evidence": f"breadth={br}; dist={dist}; tested over {n_tested} cohorts/indications",
        "conflict": None,
        "informs": CLAIM_INFORMS["D"],
        "evidence_atom": _patom(
            "tumor-elevation-breadth",
            c.get("tumor-elevation-breadth", {}),
            (
                "tumor_elevation_breadth_class",
                "rna_tumor_elevation_breadth_class",
                "n_cohorts_elevated",
                "n_cohorts_tested",
                "rna_n_indications_elevated",
                "rna_n_indications_tested",
            ),
            {"measurement_type": "tumor_elevation_breadth", "grain": "target"},
            br,
        ),
    }


def _homogeneity(h, c):
    # Emit the string sentinel "unmeasured" (NOT null) when the indication has no single-cell card
    # (SCLC/BRCA-pair scRNA = data_unavailable). null fails the evidence_package claim_vector schema
    # (oneOf[string, object]) and aborts the envelope emit for every scRNA-less indication; "unmeasured"
    # is schema-valid and honest (unmeasured != null). Consumers below treat it as absent.
    hc = h.get("sc_tce_homogeneity_class") or c.get("tumor-scrna-celltype-expression", {}).get("tce_homogeneity_class")
    return hc if hc and hc != "data_unavailable" else "unmeasured"


def presence_claim_vector(headline: dict, cards: list) -> dict:
    """The modality-blind claim vector: {A,B,C,D: {signal, corroboration, evidence, informs}, homogeneity}.
    Verdict-inert projection over the computed headline + card summaries."""
    c = _by_id(cards)
    vec = {
        "A": _claim_A(headline, c),
        "B": _claim_B(headline, c),
        "C": _claim_C(headline, c),
        "D": _claim_D(headline, c),
        "homogeneity": _homogeneity(headline, c),
        "_disclaimer": (
            "Modality-blind, verdict-INERT projection of the presence cards into orthogonal "
            "claims (A abundance / B tumor-elevation / C malignant-intrinsic / D generality), "
            "each signal×corroboration. Claims are NOT additive; a weak C does not degrade a "
            "strong B. Never feeds the presence_verdict."
        ),
    }
    # OMIT a None evidence_atom (source card absent) so an unmeasured claim stays byte-stable — matching
    # the ClaimSpec axes, where build_claim_vector only attaches the key when the atom is non-None.
    for k in ("A", "B", "C", "D"):
        if isinstance(vec[k], dict) and vec[k].get("evidence_atom") is None:
            vec[k].pop("evidence_atom", None)
    return vec


# ── key signals: a brief, direct, CITED read (deterministic; available without the LLM) ────────
def presence_key_signals(headline: dict, cards: list) -> dict:
    c = _by_id(cards)
    vec = presence_claim_vector(headline, cards)
    trd = c.get("tumor-rna-distribution", {})
    tva = c.get("tumor-rna-vs-adjacent", {})
    cp = c.get("tumor-protein-abundance-cptac", {})
    br = c.get("tumor-elevation-breadth", {})

    def support(k):
        cl = vec[k]
        if _SIG_ORD.get(cl["signal"]) is None or _SIG_ORD[cl["signal"]] < 2:
            return None
        if k == "A":
            pos, pct = trd.get("control_position", ""), trd.get("allgene_percentile")
            anchor = (
                pos
                if isinstance(pos, str) and "positive" in pos
                else f"median {_f(trd.get('median_log2tpm'), 1)} log2TPM"
            )
            lead = f"{pct:.0f}th percentile ({anchor})" if isinstance(pct, (int, float)) else anchor
            return f"Abundant in tumors — {lead} [tumor-rna-distribution]"
        if k == "B":
            bits = []
            if isinstance(tva.get("log2_fc"), (int, float)) and tva["log2_fc"] > 0.4:
                # A present-but-None q_value (DESeq2 emits null padj on independent-filtered / Cook's-cutoff
                # rows, alongside a finite log2FoldChange) must NOT reach `:.0e` — that raises TypeError and,
                # unwrapped, aborts the whole run. Guard the q clause exactly like the sibling at line ~145.
                _q = tva.get("q_value")
                _qs = f", q={_q:.0e}" if isinstance(_q, (int, float)) else ""
                bits.append(f"{2 ** tva['log2_fc']:.1f}x vs adjacent (log2FC {_f(tva['log2_fc'], 1)}{_qs})")
            # `or 1` fold a genuine 0.0 q-value to 1.0 and DROPPED the protein-confirmed bit for the STRONGEST
            # signals; test membership explicitly so a maximally-significant 0.0 is kept.
            _pq = cp.get("protein_bh_q_value")
            if (
                isinstance(cp.get("protein_effect_size"), (int, float))
                and isinstance(_pq, (int, float))
                and _pq < 0.05
                and cp["protein_effect_size"] > 0.3
            ):
                bits.append(f"protein-confirmed (CPTAC effect {_f(cp['protein_effect_size'])}, q={_pq:.0e})")
            return ("Tumor-elevated vs normal — " + "; ".join(bits) + " [DGE + CPTAC]") if bits else None
        if k == "C":
            return f"Expressed in cancer cells — {_f((headline.get('sc_malignant_detection_fraction') or 0) * 100, 0)}% of malignant cells (n={headline.get('sc_malignant_n_donors')} donors) [single-cell]"
        if k == "D":
            ne, nt = br.get("n_cohorts_elevated"), br.get("n_cohorts_tested")
            return (
                f"Broad — protein-elevated in {ne}/{nt} cancer cohorts [tumor-elevation-breadth]"
                if isinstance(ne, int) and isinstance(nt, int)
                else None
            )
        return None

    ranked = sorted("ABCD", key=lambda k: -(_SIG_ORD.get(vec[k]["signal"]) or -1))
    supports = [s for s in (support(k) for k in ranked) if s][:3]
    # one key caveat = weakest measured decision-critical claim, cited
    crit = [(k, _SIG_ORD[vec[k]["signal"]]) for k in "ABC" if _SIG_ORD.get(vec[k]["signal"]) is not None]
    caveat = None
    if crit:
        k, tier = min(crit, key=lambda kv: kv[1])
        if k == "A" and tier <= 1:
            caveat = f"Mid-tier abundance — {trd.get('control_position', '')} [tumor-rna-distribution]"
        elif k == "C" and tier <= 1:
            caveat = f"Antigen-heterogeneous — only {_f((headline.get('sc_malignant_detection_fraction') or 0) * 100, 0)}% of malignant cells express it [single-cell]"
        elif k == "B" and tier <= 1:
            caveat = "Tumor-vs-normal elevation not established (contrast flat/unavailable) [DGE + CPTAC]"
    # Breadcrumb (not an adjudication): presence carries the normal comparators but the therapeutic-window
    # VERDICT is owned by tumor-selectivity / on-target-safety. Surface the hand-off when EITHER the HPA
    # normal-tissue breadth is broad OR the single-cell normal footprint reads HIGH_LIABILITY.
    if caveat is None and (
        "broad" in str(headline.get("normal_tissue_ihc_breadth_class") or "")
        or headline.get("sc_normal_expression_class") == "HIGH_LIABILITY"
    ):
        # #984 Tier-2: sharpen the hand-off with normal-tissue ABUNDANCE — a low-abundance normal liability
        # (FOLR1-class) implies a workable window despite broad detection; high-abundance (EPCAM/CEA-class)
        # is the real concern. Still just a breadcrumb — the window VERDICT is owned by tumor-selectivity.
        _ab = headline.get("sc_normal_abundance_class")
        _ab_note = {
            "low_abundance": " — but LOW normal abundance (window may be workable; FOLR1-class)",
            "moderate_abundance": " — at moderate normal abundance",
            "high_abundance": " — at HIGH normal abundance (real window concern)",
        }.get(_ab, "")
        caveat = (
            "Broadly expressed in normal tissue → therapeutic-window liability"
            + _ab_note
            + "; the window VERDICT is owned by tumor-selectivity / on-target-safety [normal comparators]"
        )
    # deterministic headline from the vector (NOT the LLM)
    sa, sb = vec["A"]["signal"], vec["B"]["signal"]
    if _SIG_ORD.get(sa) and _SIG_ORD.get(sb) and _SIG_ORD[sa] >= 2 and _SIG_ORD[sb] >= 2:
        head = "Abundant and tumor-elevated."
    elif supports:
        head = "Present, with caveats."
    else:
        head = "Presence largely unmeasured or not distinguishing."
    # presence_state OVERRIDES for the decisive cases the signal-only head/caveat misses: a protein↔RNA
    # CONFLICT (ALB), a STROMAL-only signal (PECAM1), or a measured NOT-present. These are the exact
    # reads the collapsed word buries, so they win the headline + set the caveat.
    st = derive_presence_state(headline)
    p, mal = st.get("present"), st.get("malignant_intrinsic")
    if st.get("conflict") or p in ("no", "untested") or mal == "stroma":
        head = presence_state_phrase(st)
        if mal == "stroma":
            caveat = (
                "Signal is STROMAL — expressed in the tumor microenvironment, not the malignant cells [single-cell]"
            )
        elif st.get("conflict"):
            caveat = (
                "Protein↔RNA CONFLICT — confirm the target in the disagreeing modality before any "
                "dependent read [protein vs RNA/single-cell]"
            )
    return {"headline": head, "supports": supports, "caveat": caveat}


# ── TYPED presence_state — a structured re-projection of the claim vector + facets ──────────────
# The one-word presence_verdict is a rank-ordered collapse that can (a) disagree with the signal
# package (an ALB-style single tumor-vs-adjacent contrast reads `strongly_upregulated_in_tumor` while
# abundance + single-cell say not-present) and (b) structurally cannot carry the B/C/protein axes. This
# projects the ALREADY-computed claim_vector (A/B/C/D) + the verdict-inert facets into a typed object so
# each biological question is answered in its own field. VERDICT-INERT: reads NO presence_verdict, feeds
# no rule; the collapsed spine + per-bucket matrix are byte-identical with or without it. The one word
# can then be a pure `render_presence_label(state)` (Phase 2) rather than an independent computation.
#
# `present` names BOTH conflicted states rather than collapsing them to yes/no (symmetric with the
# spine's existing present_rna_only_protein_absent token):
#   yes                     — abundance-positive AND protein confirmed
#   rna_only                — abundance-positive AND protein untested
#   rna_only_protein_absent — abundance-positive AND protein measured-absent
#   protein_only_rna_absent — abundance measured-ABSENT but protein measured-PRESENT (CONFLICT: protein
#                             detected in bulk lysate / IHC while RNA + single-cell say not in the cells —
#                             investigate contamination / post-transcriptional; NOT a clean absence call)
#   protein_only            — abundance UNMEASURED but protein measured-present
#   no                      — abundance measured-absent AND protein not confirmed
#   untested                — abundance unmeasured AND protein not confirmed
_PS_POS_SIG = frozenset({"strong", "moderate", "weak"})


def _ps_sig(vec, ax):
    return ((vec or {}).get(ax) or {}).get("signal")


def derive_presence_state(headline: dict) -> dict:
    """Typed, VERDICT-INERT projection of the presence signal package. Reads headline['claim_vector']
    (A/B/C/D) + the facets already on the headline (protein_confirmation_state, abundance_floor_flag,
    sc_expression_class, tumor_elevation_breadth_class). Never reads presence_verdict."""
    vec = headline.get("claim_vector") or {}
    A, B, C = _ps_sig(vec, "A"), _ps_sig(vec, "B"), _ps_sig(vec, "C")
    pcs = headline.get("protein_confirmation_state")  # confirmed|measured_absent|untested|not_applicable
    floor = headline.get("abundance_floor_flag")  # present_low_abundance|adequate_abundance|None
    scc = headline.get("sc_expression_class")
    bc = headline.get("tumor_elevation_breadth_class")

    # `confirmed_cell_line_only` (tumor protein untested, cell-line MS present) is treated as a protein
    # confirmation for the coarse present-state (keeps present='yes' → no phrase/label cascade); the
    # cell-line-only qualifier is carried by the protein_confirmation_state facet itself (INV-8).
    _confirmed = pcs in ("confirmed", "confirmed_cell_line_only")
    # A cell-line-ONLY protein confirmation that is orthogonally CONTRADICTED — bottom-decile abundance
    # floor AND HPA-IHC `ihc_not_detected` — is too thin to mint a `protein_only_rna_absent` CONFLICT
    # against an RNA-absent target (the MLANA case: a bottom-~0.3-percentile Gygi read, IHC not-detected,
    # sc broadly_low). A tumor/full `confirmed` still counts; only the cell-line-only-AND-contradicted
    # combination is demoted, and ONLY in the RNA-absent branch (surgical — the RNA-present branch is
    # untouched, so no present='yes' target changes). VERDICT-INERT projection.
    _thin_cellline_only = (
        pcs == "confirmed_cell_line_only"
        and floor == "present_low_abundance"
        and headline.get("hpa_ihc_protein_presence_class") == "ihc_not_detected"
    )
    if A in _PS_POS_SIG:
        present = "yes" if _confirmed else "rna_only_protein_absent" if pcs == "measured_absent" else "rna_only"
    elif A in ("absent", "negative"):
        present = "protein_only_rna_absent" if (_confirmed and not _thin_cellline_only) else "no"
    else:  # abundance unmeasured
        present = "protein_only" if _confirmed else "untested"

    abundance_level = (
        "low"
        if floor == "present_low_abundance"
        else "high"
        if A == "strong"
        else "moderate"
        if A in ("moderate", "weak")
        else "untested"
    )
    elevated = "yes" if B in ("strong", "moderate") else "no" if B in ("absent", "negative") else "untested"
    malignant = (
        "stroma"
        if (C == "negative" or scc == "microenvironment_dominant")
        else "yes"
        if C in _PS_POS_SIG
        else "no"
        if C == "absent"
        else "untested"
    )
    breadth = {
        "broadly_tumor_elevated": "broad",
        "multi_tumor_elevated": "multi",
        "single_tumor_elevated": "single",
        "not_tumor_elevated": "none",
    }.get(bc, "untested")

    return {
        "present": present,
        "conflict": present in ("rna_only_protein_absent", "protein_only_rna_absent"),
        "abundance_level": abundance_level,
        "elevated_vs_normal": elevated,
        "malignant_intrinsic": malignant,
        "breadth": breadth,
        "_basis": (
            "typed projection of claim_vector A/B/C/D + protein_confirmation_state + "
            "abundance_floor_flag + sc_expression_class; VERDICT-INERT, reads no presence_verdict"
        ),
    }


# Re-based signal STRENGTH for the certainty-discounted composite. Keyed on the INTEGRATED claim vector
# (peak positive signal across A/B/C/D) floored by presence_state — NOT on the collapsed one-word verdict.
# Fixes the ALB-style false-strong: a single tumor-vs-adjacent contrast wins the ladder (verdict
# `strongly_upregulated_in_tumor` → the old verdict-keyed strength read `strong_positive`) while the
# integrated signal package is weak (A=absent, C=absent). EPCAM is UNHARMED (peak A=strong → strong).
# Verdict-INERT: feeds only the composite ranking sidecar, never presence_verdict.
_STRENGTH_BY_ORD = {3: "strong_positive", 2: "moderate_positive", 1: "weak_positive", 0: "weak_positive"}


def presence_strength_from_state(presence_state: dict, claim_vector: dict) -> str:
    """Signal strength for the composite, from the claim vector's PEAK positive signal, floored by
    presence_state. `no`→negative, `untested`/absent→none, a protein↔RNA conflict caps at weak_positive."""
    p = (presence_state or {}).get("present")
    if p == "no":
        return "negative"
    if p in (None, "untested"):
        return "none"
    ords = [
        o
        for ax in ("A", "B", "C", "D")
        for o in [_SIG_ORD.get(((claim_vector or {}).get(ax) or {}).get("signal"))]
        if isinstance(o, int) and o >= 1
    ]
    strength = _STRENGTH_BY_ORD.get(max(ords), "weak_positive") if ords else "weak_positive"
    if (presence_state or {}).get("conflict"):  # protein↔RNA disagreement is never strong
        strength = "weak_positive"
    return strength


# Human-facing PHRASE from the typed state — the honest headline every surface shows instead of the raw
# collapsed word (which can read "strongly up-regulated" for an ALB contamination artifact or
# "broadly expressed" for a PECAM1 stromal signal). Verdict-INERT display text.
def presence_state_phrase(state: dict) -> str:
    if not isinstance(state, dict) or not state.get("present"):
        return "Presence not assessed"
    p, mal = state.get("present"), state.get("malignant_intrinsic")
    ab, el = state.get("abundance_level"), state.get("elevated_vs_normal")
    if p == "no":
        return "Not present in tumor"
    if p == "untested":
        return "Presence untested"
    if p == "protein_only_rna_absent":
        return (
            "Conflicting — protein detected but RNA / single-cell absent; investigate "
            "(contamination or post-transcriptional) before any read"
        )
    if p == "rna_only_protein_absent":
        return "RNA-present but protein measured-absent — confirm protein before a biologics read"
    if p == "protein_only":
        return "Protein present (RNA abundance unmeasured)"
    # present == yes | rna_only
    if mal == "stroma":
        return "Present in the tumor microenvironment (stromal, not malignant-cell-intrinsic)"
    lead = {"high": "Abundantly present", "low": "Present (low absolute abundance)"}.get(ab, "Present")
    tail = " and tumor-elevated" if el == "yes" else "; not elevated vs normal" if el == "no" else ""
    proxy = " — RNA-only, protein untested" if p == "rna_only" else ""
    return f"{lead} in tumor{tail}{proxy}"


# The one WORD as a pure render of the typed object (Phase 2 will point presence_verdict at this).
def render_presence_label(state: dict) -> str:
    p = (state or {}).get("present")
    if p == "no":
        return "absent"
    if p == "untested":
        return "presence_untested"
    if p == "rna_only_protein_absent":
        return "present_rna_only_protein_absent"
    if p == "protein_only_rna_absent":
        return "conflicted_protein_present_rna_absent"
    if p == "protein_only":
        return "present_protein_only"
    tier = {"high": "broadly", "moderate": "moderately", "low": "sparsely", "untested": "moderately"}.get(
        state.get("abundance_level"), "moderately"
    )
    stub = "protein_confirmed" if p == "yes" else "rna_only"
    elev = "_tumor_elevated" if state.get("elevated_vs_normal") == "yes" else ""
    return f"present_{tier}{elev}_{stub}"


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


# Multiplicity-aware certainty (Phase 3): a per-stratum signal is one of k strata scanned, so the
# false-positive surface grows with k. Apply a conservative 1-tier certainty HAIRCUT when several
# strata are tested (k >= 5). This is the honest calibration that lets the per-stratum vector surface
# subtype-conditional POSITIVES (e.g. CD274/MSI-H) instead of the old never-mint-positive suppression:
# the burden moves from "suppress the signal" to "discount its certainty". NOT a p-value correction — a
# certainty discount, and it composes with the n-based power tier (a small-n stratum already reads low).
_CERT3 = {"low": 0, "moderate": 1, "high": 2}
_CERT3_INV = {0: "low", 1: "moderate", 2: "high"}


def _multiplicity_discount(rel: str, k) -> str:
    if rel not in _CERT3 or not isinstance(k, int) or k < 5:
        return rel
    return _CERT3_INV[max(0, _CERT3[rel] - 1)]


def presence_claim_vector_by_subtype(cards: list) -> Optional[dict]:
    """Per-stratum claim vector (A abundance + distributional B) from per_subgroup_metrics. Returns
    None when the indication has no subtype axis. C / protein remain indication-grain (flagged)."""
    c = _by_id(cards)
    s = c.get("tumor-rna-distribution-by-subtype", {})
    if not isinstance(s, dict) or not s.get("subtype_axis_available"):
        return None
    strata = {}
    # k = strata scanned (multiple-testing surface) — the tested count, else the count with data.
    k_tested = s.get("n_subtypes_measured")
    if not isinstance(k_tested, int):
        k_tested = sum(1 for r in (s.get("per_subgroup_metrics") or []) if isinstance(r, dict) and r.get("stratum_id"))
    for r in s.get("per_subgroup_metrics") or []:
        if not isinstance(r, dict):  # tolerate simplified/frozen fixtures where rows aren't full dicts
            continue
        sid = r.get("stratum_id")
        if not sid:
            continue
        med, fa, n = r.get("median_log2tpm"), r.get("fraction_tumor_above_normal_p95"), r.get("n_tumor_samples")
        rel_base = (
            "high" if isinstance(n, int) and n >= 100 else "moderate" if isinstance(n, int) and n >= 30 else "low"
        )
        rel = _multiplicity_discount(rel_base, k_tested)  # multiplicity haircut
        fb = "moderate" if isinstance(fa, (int, float)) else "unmeasured"
        strata[sid] = {
            "A": {
                "signal": _tier_from_median(med),
                "corroboration": rel,
                "evidence": f"stratum median {_f(med, 1)} log2TPM, n={n}"
                + (f" (certainty {rel_base}→{rel}: 1 of {k_tested} strata scanned)" if rel != rel_base else ""),
            },
            "B": {
                "signal": _tier_from_fraction_above_normal(fa),
                "corroboration": _multiplicity_discount(fb, k_tested),
                "evidence": (
                    f"{_f((fa or 0) * 100, 0)}% of stratum tumours > GTEx-normal p95 (distributional, not the DEG)"
                    if isinstance(fa, (int, float))
                    else "no per-stratum normal window"
                ),
            },
            "n_tumor_samples": n,
        }
    # ENRICHED-SUBTYPE IDENTITIES (verdict-INERT legibility): the reader computes a per-stratum
    # subtype_signal (subtype_enriched / subtype_restricted) but the rollup previously surfaced only the
    # COUNT (n_subtypes_enriched) + the single argmax-ε² axis (which_subtypes_separate) — so a consumer of
    # the spine could not answer "which subtype(s) is the target enriched in?" without reaching into
    # per_subgroup_metrics (cf. CD274/COADREAD: n_subtypes_enriched=3 but the identities MSI_H/CMS1/CIMP_High
    # were unnamed, and spotlight_subtype is a --subtype query-echo, None on a whole-cohort run). Project the
    # positive-selection identities here, ranked by stratum median (highest = most enriched). `top_enriched_subtype`
    # is the DATA-DRIVEN highlight, distinct from the query-echo `spotlight_subtype`.
    _POS_SELECTION_SIGNALS = ("subtype_enriched", "subtype_restricted")
    enriched_subtypes = sorted(
        (
            {
                "stratum": r.get("stratum_id"),
                "subtype_signal": r.get("subtype_signal"),
                "median_log2tpm": r.get("median_log2tpm"),
                "n_tumor_samples": r.get("n_tumor_samples"),
            }
            for r in (s.get("per_subgroup_metrics") or [])
            if isinstance(r, dict)
            and r.get("stratum_id")
            and r.get("subtype_signal") in _POS_SELECTION_SIGNALS
            and r.get("evidence_state") == "measured"
        ),
        key=lambda e: (e["median_log2tpm"] is None, -(e["median_log2tpm"] or 0.0)),
    )
    return {
        "stratification_class": s.get("subtype_stratification_class"),
        "subtype_variance_explained": s.get("subtype_variance_explained"),
        "subtype_effect_size_class": s.get("subtype_effect_size_class"),
        "which_subtypes_separate": s.get("which_subtypes_separate"),
        "n_subtypes_measured": s.get("n_subtypes_measured"),
        # the enriched/restricted stratum IDENTITIES (ranked), + the data-driven top pick
        "enriched_subtypes": enriched_subtypes,
        "top_enriched_subtype": (enriched_subtypes[0]["stratum"] if enriched_subtypes else None),
        "multiplicity_strata_tested": k_tested,
        "strata": strata,
        "_indication_grain_claims": "C (single-cell malignant) and protein-confirmation are NOT stratified "
        "(single-cell pooled; CPTAC whole-cohort) — read them from the pooled claim_vector.",
        "_disclaimer": (
            "Per-stratum claim vector — verdict-INERT (the pooled presence_verdict is byte-stable). "
            "Only claims A (abundance) and a distributional B (fraction > GTEx-normal p95) are live per "
            "subtype (from per_subgroup_metrics); a pooled indication read can flatten a subtype-"
            "concentrated signal (cf. CD274/MSI-H), so a per-stratum POSITIVE is surfaced here rather "
            f"than suppressed. Certainty is MULTIPLICITY-AWARE: with {k_tested} strata scanned, each "
            "per-stratum corroboration takes a 1-tier haircut (k>=5) so a single stratum is not over-"
            "trusted; small-n strata are additionally low by power. Read certainty, not just signal."
        ),
    }


__all__ = [
    "presence_claim_vector",
    "presence_claim_vector_by_subtype",
    "presence_key_signals",
    "derive_presence_state",
    "render_presence_label",
    "presence_strength_from_state",
    "presence_state_phrase",
    "CLAIM_NAME",
    "CLAIM_INFORMS",
]
