"""Presence QUESTION TABLE — the 7-question × (data · signal · confidence) summary that LEADS the
tumor-presence dashboard, computed deterministically from the already-emitted claim_vector + the
answer-key card fields. Verdict-INERT: a one-way projection over decision['headline'] + card summaries;
it never feeds a rule, resolver, gate, or the collapsed presence_verdict.

The presence question (user's model): presence is a ladder of relative comparisons, absolutized by
all-gene rank, plus modality + cellular-attribution checks. The 4-claim claim_vector
(A abundance / B tumor-elevation / C malignant-intrinsic / D generality) covers ~half the cards; the
other cards carry clear supporting/caveat signals, so each row is a PRIMARY read (drives the Signal)
plus a SUPPORTING/caveat sub-line drawn from the remaining cards:

  Q1 expressed at all?        primary claim A          support: cell-line proxy (lineage/protein)
  Q2 vs other cancers?        primary claim D          support: most-elevated cohorts, breadth concordance
  Q3 vs normals?              primary claim B          support: HPA + sc-normal (the window caveat)
  Q4 subtype variation?       primary by-subtype card  support: cell-line subtype, sc homogeneity
  Q5 absolute vs all genes?   primary allgene ranks    (level vs effect, aggregated across cards)
  Q6 RNA↔protein?             primary concordance      support: breadth-layer concordance
  Q7 malignant-intrinsic?     primary claim C          support: bulk purity, sc-normal caveat

Signal reuses the claim_vector tier vocabulary (strong>moderate>weak>absent/negative, unmeasured);
Confidence reuses the corroboration vocabulary (high>moderate>low, unmeasured). No new scoring model.
"""
from __future__ import annotations
from typing import Optional

from _skills_common.question_table_core import cbyid as _cbyid, conf as _conf, row as _row, sig as _sig, _SIG_META

# Signal tier → (meter fill 0-5, polarity). Polarity: supports / opposes / neutral / none.
# ── per-question builders ────────────────────────────────────────────────────────────────────────
def _q1_abundance(h, c, cv):
    a = cv.get("A", {})
    tier, corr = a.get("signal", "unmeasured"), a.get("corroboration", "unmeasured")
    cl = c.get("cellline-rna-distribution", {})
    clp = c.get("cellline-protein-abundance", {})
    primary = a.get("evidence", "abundance anchor unavailable")
    support = f"cell-line RNA: {cl.get('expression_class', 'n/a')}"
    if clp.get("protein_expression_class"):
        support += f" · cell-line protein: {clp.get('protein_expression_class')}"
    return _row("Q1", "Expressed in cancers at all?", primary, support,
                _sig(tier, tier), _conf(corr, f"RNA→protein proxy: {corr}"))


def _q2_generality(h, c, cv):
    d = cv.get("D", {})
    tier = d.get("signal", "unmeasured")
    br = h.get("tumor_elevation_breadth_class") or h.get("rna_tumor_elevation_breadth_class")
    ne, nt = h.get("tumor_elevation_n_cohorts_elevated"), h.get("tumor_elevation_n_cohorts_tested")
    rne, rnt = h.get("rna_tumor_elevation_n_indications_elevated"), h.get("rna_tumor_elevation_n_indications_tested")
    primary = f"breadth {br}"
    if ne is not None:
        primary += f" · protein {ne}/{nt} cohorts"
    if rne is not None:
        primary += f" · RNA {rne}/{rnt} indications"
    conc = h.get("breadth_layer_concordance")
    support = f"RNA↔protein breadth {conc}" if conc else "single-layer breadth"
    return _row("Q2", "This indication vs other cancers?", primary, support,
                _sig(tier, tier), _conf("moderate"))


def _q3_vs_normal(h, c, cv):
    b = cv.get("B", {})
    tier, corr = b.get("signal", "unmeasured"), b.get("corroboration", "unmeasured")
    primary = b.get("evidence", "no tumor-vs-normal arm")
    caveats = []
    if b.get("conflict"):
        caveats.append(b["conflict"])
    nl = c.get("normal-tissue-liability", {}).get("normal_tissue_breadth_class")
    if nl:
        caveats.append(f"HPA normal: {nl}")
    scn = h.get("sc_normal_expression_class") or c.get("sc-normal-celltype-expression", {}).get("sc_normal_expression_class")
    scct = h.get("sc_normal_max_det_cell_type") or c.get("sc-normal-celltype-expression", {}).get("max_detection_cell_type")
    if scn:
        caveats.append(f"normal single-cell: {scn}" + (f" (max: {scct})" if scct else ""))
    support = " · ".join(caveats) if caveats else "no normal comparator"
    # polarity: an up signal supports elevation; but surface the window caveat via the support line.
    label = tier + (" ⚠ window" if b.get("conflict") or (nl and "broad" in str(nl)) else "")
    return _row("Q3", "Elevated vs normals (adjacent + GTEx)?", primary, support,
                _sig(tier, label), _conf(corr))


def _q4_subtype(h, c, cv):
    s = c.get("tumor-rna-distribution-by-subtype", {})
    cls = s.get("subtype_stratification_class") or h.get("subtype_stratification_class")
    nmeas = s.get("n_subtypes_measured") or h.get("n_subtypes_measured")
    nenr = s.get("n_subtypes_enriched") or h.get("n_subtypes_enriched")
    spot = s.get("spotlight_subtype") or h.get("spotlight_subtype")
    # HONEST capability grade first: an underpowered/empty axis must NOT read as a differential, even
    # when a single stratum happens to clear the enrichment delta (NSCLC KRAS_G12C / DepMap STAD-PAAD).
    quality = s.get("subtype_axis_quality") or h.get("subtype_axis_quality")
    if quality in ("unavailable", None) and (not cls or cls in (
            "data_unavailable", "subtype_axis_unavailable", "no_subtype_axis")):
        sig, primary = _sig("unmeasured", "no subtype axis"), "no molecular-subtype axis for this indication"
    elif quality in ("empty", "underpowered"):
        # axis is DEFINED but not usable — say so; never assert a cross-subtype contrast here.
        detail = "all strata empty" if quality == "empty" else f"only {nenr or 0}/{nmeas or 0} powered — underpowered"
        sig = _sig("unmeasured", f"axis {quality}")
        primary = f"subtype axis present but {quality} ({detail}); not a usable selection axis"
    elif cls in ("subtype_enriched", "subtype_restricted", "subtype_differential"):
        sig = _sig("moderate", f"enriched: {spot}" if spot else "subtype-differential")
        primary = f"{cls}" + (f" (spotlight {spot})" if spot else "") + f"; {nenr}/{nmeas} enriched"
    else:  # pan_subtype_uniform (on a powered axis)
        sig = _sig("uniform", "uniform across subtypes")
        primary = f"pan-subtype uniform ({nenr or 0}/{nmeas} enriched)"
    clsub = c.get("cellline-rna-distribution-by-subtype", {}).get("subtype_stratification_class")
    hom = h.get("sc_tce_homogeneity_class")
    support_bits = []
    if quality == "powered":
        support_bits.append("axis powered")
    if clsub:
        support_bits.append(f"cell-line (genotype axis): {clsub}")
    if hom and hom != "data_unavailable":
        support_bits.append(f"single-cell homogeneity: {hom}")
    # Purity confounder flag: a large across-stratum purity spread means an "enrichment" may be stromal.
    spread = s.get("subtype_purity_spread") or h.get("subtype_purity_spread")
    if isinstance(spread, dict) and isinstance(spread.get("delta"), (int, float)) and spread["delta"] >= 0.15:
        support_bits.append(f"⚠ purity varies across strata (Δ={spread['delta']:.2f}) — enrichment may be stromal")
    support = " · ".join(support_bits) if support_bits else "—"
    # Confidence keyed on the capability grade, not just the measured count.
    if quality == "powered":
        conf = "high" if isinstance(nmeas, int) and nmeas >= 5 else "moderate"
    elif quality in ("empty", "underpowered"):
        conf = "unmeasured"
    else:
        conf = "high" if isinstance(nmeas, int) and nmeas >= 5 else "moderate" if nmeas else "unmeasured"
    return _row("Q4", "Do subtypes differ (from each other / normals)?", primary, support, sig, _conf(conf))


# allgene percentile class → signal tier (LEVEL ranks); effect ranks are supporting only.
_PCT_TIER = {"top_1pct": "strong", "top_decile": "moderate", "mid": "weak",
             "bottom_decile": "absent", "data_unavailable": "unmeasured"}


def _q5_absolute(h, c, cv):
    trd = c.get("tumor-rna-distribution", {})
    cl = c.get("cellline-rna-distribution", {})
    tva = c.get("tumor-rna-vs-adjacent", {})
    cptac = c.get("tumor-protein-abundance-cptac", {})
    level_bits, effect_bits = [], []
    # LEVEL ranks (the Q5-intended "how highly expressed vs all genes")
    lvl_tier = "unmeasured"
    for card, lbl in ((trd, "tumor RNA"), (cl, "cell-line RNA")):
        pct, klass = card.get("allgene_percentile"), card.get("allgene_percentile_class")
        if isinstance(pct, (int, float)):
            level_bits.append(f"{lbl} {pct:.0f}%ile ({klass})")
            t = _PCT_TIER.get(klass, "weak")
            if _SIG_META[t][0] > _SIG_META.get(lvl_tier, (0, ""))[0]:
                lvl_tier = t
    # EFFECT ranks (rank of the tumor-vs-normal CONTRAST — labeled distinctly, supporting)
    for card, lbl in ((tva, "RNA-vs-adjacent FC"), (cptac, "CPTAC protein effect")):
        pct, klass = card.get("allgene_percentile"), card.get("allgene_percentile_class")
        if isinstance(pct, (int, float)):
            effect_bits.append(f"{lbl} {pct:.0f}%ile ({klass})")
    primary = "level: " + ("; ".join(level_bits) if level_bits else "unavailable")
    support = ("effect: " + "; ".join(effect_bits)) if effect_bits else "no effect-rank"
    conf = "high" if level_bits else ("moderate" if effect_bits else "unmeasured")
    return _row("Q5", "Absolute abundance vs all genes?", primary, support, _sig(lvl_tier, lvl_tier), _conf(conf))


def _q6_concordance(h, c, cv):
    tum = c.get("rna-protein-concordance-tumor", {})
    clc = c.get("cellline-rna-protein-concordance", {})
    bio = tum.get("rna_as_biomarker") or h.get("rna_as_biomarker_tumor")
    r = tum.get("rna_protein_r") or h.get("rna_protein_r_tumor")
    n = tum.get("n_paired_tumors") or h.get("rna_protein_n_paired_tumors")
    tier = {"adequate_proxy": "strong", "partial_proxy": "moderate", "poor_proxy": "weak"}.get(bio, "unmeasured")
    primary = f"tumor: {bio or 'n/a'}" + (f" (r={r:.2f})" if isinstance(r, (int, float)) else "")
    clbio, clr = clc.get("rna_as_biomarker"), clc.get("rna_protein_r")
    support = f"cell-line: {clbio}" + (f" (r={clr:.2f})" if isinstance(clr, (int, float)) else "") if clbio else "—"
    conf = "high" if isinstance(n, int) and n >= 50 else "moderate" if n else "unmeasured"
    return _row("Q6", "Do RNA and protein agree?", primary, support, _sig(tier, tier), _conf(conf))


def _q7_intrinsic(h, c, cv):
    cc = cv.get("C", {})
    tier, corr = cc.get("signal", "unmeasured"), cc.get("corroboration", "unmeasured")
    primary = cc.get("evidence", "no single-cell for indication")
    pur = c.get("expression-purity-confound", {}).get("purity_confound_class") or h.get("purity_confound_class")
    support_bits = []
    if pur:
        support_bits.append(f"bulk purity: {pur}")
    scnorm = h.get("sc_normal_safety_essential_class")
    if scnorm and scnorm != "data_unavailable":
        support_bits.append(f"normal single-cell: {scnorm}")
    support = " · ".join(support_bits) if support_bits else "—"
    return _row("Q7", "Is the tumor signal malignant-cell-intrinsic?", primary, support, _sig(tier, tier), _conf(corr))


def presence_question_table(headline: dict, cards: list, claim_vector: Optional[dict] = None) -> list:
    """The 7 question rows (each: id, question, primary read, supporting/caveat line, signal, confidence).
    Verdict-inert. `claim_vector` defaults to the one on the headline (`headline['claim_vector']`)."""
    from _skills_common.presence_claims import presence_claim_vector
    cv = claim_vector or headline.get("claim_vector") or presence_claim_vector(headline, cards)
    c = _cbyid(cards)
    return [
        _q1_abundance(headline, c, cv),
        _q2_generality(headline, c, cv),
        _q3_vs_normal(headline, c, cv),
        _q4_subtype(headline, c, cv),
        _q5_absolute(headline, c, cv),
        _q6_concordance(headline, c, cv),
        _q7_intrinsic(headline, c, cv),
    ]


# ── shared HTML renderer (so the example-gallery page AND the composed target-profile dashboard render
#    the identical table from the same rows — the gallery computes rows live; target-profile reads them
#    off the carried presence facet) ───────────────────────────────────────────────────────────────
import html as _html

_POL_CLASS = {"supports": "pos", "opposes": "neg", "neutral": "neu", "none": "none"}

QUESTION_TABLE_CSS = (
    ".qtcap{margin:18px 0 6px;font-size:13px;color:#334;font-weight:600}"
    ".qtable{width:100%;border-collapse:collapse;font-size:13px;margin:2px 0 8px;background:#fff;"
    "border:1px solid #e3e6ea;border-radius:8px;overflow:hidden}"
    ".qtable th{background:#f5f6f8;text-align:left;padding:7px 10px;border-bottom:2px solid #e3e6ea;"
    "font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:#556}"
    ".qtable td{padding:9px 10px;border-top:1px solid #eef0f3;vertical-align:top}"
    ".qtable .qid{font-weight:700;color:#1e3a8a;white-space:nowrap}"
    ".qtable .qq{font-weight:600;min-width:170px} .qtable .qd{color:#333;max-width:340px}"
    ".qtable .qsupport{color:#8a94a0;font-size:11.5px;margin-top:3px}"
    ".meter{display:inline-flex;gap:2px;vertical-align:middle;margin-right:8px}"
    ".meter .seg{width:13px;height:10px;border-radius:2px;background:#eceef1}"
    ".meter .seg.on.pos{background:#166534} .meter .seg.on.neg{background:#b45309}"
    ".meter .seg.on.neu{background:#6366f1} .meter .seg.on.none{background:#cbd0d6}"
    ".siglab{font-size:11.5px} .siglab.pos{color:#166534} .siglab.neg{color:#b45309}"
    ".siglab.neu{color:#3730a3} .siglab.none{color:#889}"
    ".dots{display:inline-flex;gap:3px} .dots .dot{width:8px;height:8px;border-radius:50%;background:#e3e6ea}"
    ".dots .dot.on{background:#475569}"
)


def render_question_table_html(rows: list, verdict: Optional[str] = None, include_css: bool = True,
                               title: str = "Presence",
                               signal_header: str = "Signal — supports presence →") -> str:
    """Render a question × (data · Signal meter · Confidence dots) table to self-contained HTML. Shared
    across skills: `title` sets the "<X> at a glance" caption (Presence / Selectivity / Dependency) and
    `signal_header` the Signal column header — both default to presence (back-compat). `include_css`
    emits the <style> block (set False when the host page already ships QUESTION_TABLE_CSS)."""
    if not rows:
        return ""
    esc = _html.escape
    trs = []
    for r in rows:
        s, cf = r["signal"], r["confidence"]
        pol = _POL_CLASS.get(s.get("polarity"), "none")
        meter = "".join(f'<span class="seg{(" on " + pol) if i < s.get("fill", 0) else ""}"></span>' for i in range(5))
        dots = "".join(f'<span class="dot{" on" if i < cf.get("dots", 0) else ""}"></span>' for i in range(3))
        trs.append(
            f'<tr><td class="qid">{esc(str(r.get("id","")))}</td>'
            f'<td class="qq">{esc(str(r.get("question","")))}</td>'
            f'<td class="qd"><div>{esc(str(r.get("primary","")))}</div>'
            f'<div class="qsupport">{esc(str(r.get("support","")))}</div></td>'
            f'<td class="qsig"><span class="meter">{meter}</span>'
            f'<span class="siglab {pol}">{esc(str(s.get("label","")))}</span></td>'
            f'<td class="qconf"><span class="dots">{dots}</span></td></tr>')
    cap = (f'<div class="qtcap">{esc(title)} at a glance'
           + (f' · verdict <span class="verdict">{esc(str(verdict))}</span>' if verdict else "")
           + ' <span class="hint">— Signal (strength · polarity) &amp; Confidence '
             '(corroboration), computed from the claim-vector; verdict-inert.</span></div>')
    head = (f'<tr><th>Q</th><th>Question</th><th>Data / read</th>'
            f'<th>{esc(signal_header)}</th><th>Conf</th></tr>')
    css = f"<style>{QUESTION_TABLE_CSS}</style>" if include_css else ""
    return f'{css}{cap}<table class="qtable"><thead>{head}</thead><tbody>{"".join(trs)}</tbody></table>'


__all__ = ["presence_question_table", "render_question_table_html", "QUESTION_TABLE_CSS"]
