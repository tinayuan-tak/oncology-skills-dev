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

import math
from typing import Optional

from _skills_common.question_table_core import _SIG_META
from _skills_common.question_table_core import cbyid as _cbyid
from _skills_common.question_table_core import conf as _conf
from _skills_common.question_table_core import row as _row
from _skills_common.question_table_core import sig as _sig
from _skills_common.subtype_axis import SUBTYPE_DIFFERENTIAL_CLASSES, is_differential_axis


def _top_labels(rows, key: str, k: int = 3, rank_by: str | None = None) -> list:
    """The ``k`` most important labels from a LIST-valued summary field.

    A question row is the only surface that can show these at all. Every generic capsule selector
    either skips containers outright (``_sibling_caveats`` drops ``list``/``dict``) or requires a
    scalar (``_numeric_anchors``/``_n_basis`` need ``int``/``float``, ``_provenance_keys`` needs
    ``str``/``int``/``float``); the one list-capable path, ``_categorical_anchors``, fires only for
    CONTRACT-DECLARED fields. So an undeclared list-valued field is unreachable by every hint scan no
    matter how many hints its name matches — which is why the fields carrying WHICH cohort and WHICH
    tissue were populated on every run and shown on none.

    ``rank_by`` exists because truncating a list asserts that its head is its most important part, and
    only the PRODUCER knows whether that is true. The card contracts state the order where there is
    one, and the split is not cosmetic:

      * ``most_elevated_cohorts`` — "effect-desc, elevated-only"  ⟶ pre-ranked, pass no ``rank_by``
      * ``rna_most_elevated_indications`` — "lfc-desc, elevated-only"  ⟶ pre-ranked, likewise
      * ``specific_tissues`` — "parsed from the intensity field", and the card names NO order  ⟶ the
        producer is a bare ``split(";")`` over an HPA string, so its head is an artefact of HPA's
        formatting. Measured on the tacstd2 fixture: ``lung`` (2.2e7) precedes ``salivary gland``
        (2.4e7). Taking ``[:3]`` of that would show the alphabetically-first tissues and hide the most
        abundant one — substituting NAMING for CONTENT on a SAFETY row, the same defect as the
        ``sorted(...)[:4]`` starvation this census already found in the capsule hint scan.

    Rows whose ``rank_by`` value is missing, ``None``, non-numeric or NON-FINITE sort LAST, so neither
    an unparseable intensity nor an ``inf`` can displace a measured one — ``inf`` is the case a
    truthiness or ``isna`` guard would admit, and it wins every comparison it enters. Ordering is
    otherwise stable, so ties keep emission order. Tolerates a list of plain strings as well as the dict-per-row shape, and de-duplicates, so a
    card that changes its row shape degrades to fewer labels rather than to a traceback in a
    verdict-inert display path.
    """
    rows = list(rows or [])
    if rank_by:

        def _rank(r):
            v = r.get(rank_by) if isinstance(r, dict) else None
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                return (1, 0.0)
            return (0, -float(v))

        rows = sorted(rows, key=_rank)
    out: list = []
    for r in rows:
        label = r.get(key) if isinstance(r, dict) else r
        if isinstance(label, str) and label and label not in out:
            out.append(label)
        if len(out) >= k:
            break
    return out


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
    return _row(
        "Q1",
        "Expressed in cancers at all?",
        primary,
        support,
        _sig(tier, tier),
        _conf(corr, f"RNA→protein proxy: {corr}"),
    )


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
    bits = [f"RNA↔protein breadth {conc}" if conc else "single-layer breadth"]
    # The row asks "vs OTHER cancers?" and the primary line answers only HOW MANY (4/9 cohorts, 5/13
    # indications). These name WHICH — the support clause this module's own docstring has always
    # declared for Q2. Read off an alias so the census resolves them to THIS card, not by name.
    teb = c.get("tumor-elevation-breadth", {})
    prot = _top_labels(teb.get("most_elevated_cohorts"), "cohort")
    rna = _top_labels(teb.get("rna_most_elevated_indications"), "indication")
    if prot:
        bits.append("top protein: " + ", ".join(prot))
    if rna:
        bits.append("top RNA: " + ", ".join(rna))
    support = " · ".join(bits)
    return _row("Q2", "This indication vs other cancers?", primary, support, _sig(tier, tier), _conf("moderate"))


def _q3_vs_normal(h, c, cv):
    b = cv.get("B", {})
    tier, corr = b.get("signal", "unmeasured"), b.get("corroboration", "unmeasured")
    primary = b.get("evidence", "no tumor-vs-normal arm")
    caveats = []
    if b.get("conflict"):
        caveats.append(b["conflict"])
    # Aliased rather than chained inline so the census binds both reads to THIS card. `specific_tissues`
    # names the normal tissues behind the breadth class — for a GI target in COADREAD that is `intestine`,
    # the tumour's own organ of origin and the whole safety point of the row. Mirrors the `(max: ...)`
    # shape the single-cell caveat below already uses: class, then the evidence that names it.
    ntl = c.get("normal-tissue-liability", {})
    nl = ntl.get("normal_tissue_breadth_class")
    if nl:
        # rank_by: this list is parse-ordered, NOT intensity-ordered (see `_top_labels`), so the cap has
        # to rank it or it would name the alphabetically-first tissues and hide the most abundant one.
        tissues = _top_labels(ntl.get("specific_tissues"), "tissue", rank_by="intensity")
        caveats.append(f"HPA normal: {nl}" + (f" (specific: {', '.join(tissues)})" if tissues else ""))
    scn = h.get("sc_normal_expression_class") or c.get("sc-normal-celltype-expression", {}).get(
        "sc_normal_expression_class"
    )
    scct = h.get("sc_normal_max_det_cell_type") or c.get("sc-normal-celltype-expression", {}).get(
        "max_detection_cell_type"
    )
    if scn:
        caveats.append(f"normal single-cell: {scn}" + (f" (max: {scct})" if scct else ""))
    support = " · ".join(caveats) if caveats else "no normal comparator"
    # polarity: an up signal supports elevation; but surface the window caveat via the support line.
    label = tier + (" ⚠ window" if b.get("conflict") or (nl and "broad" in str(nl)) else "")
    return _row("Q3", "Elevated vs normals (adjacent + GTEx)?", primary, support, _sig(tier, label), _conf(corr))


def _q4_subtype(h, c, cv, sv=None):
    s = c.get("tumor-rna-distribution-by-subtype", {})
    cls = s.get("subtype_stratification_class") or h.get("subtype_stratification_class")
    nmeas = s.get("n_subtypes_measured") or h.get("n_subtypes_measured")
    nenr = s.get("n_subtypes_enriched") or h.get("n_subtypes_enriched")
    # WHICH stratum. `spotlight_subtype` on THIS card is a `--subtype` QUERY ECHO — the methods reader
    # assigns the caller's requested stratum verbatim (`base["spotlight_subtype"] = subtype`), so it is
    # None on every whole-cohort run. Measured None in 937 of 937 corpus packages across four corpora
    # (2026-08-26 .. 2026-09-14), and no batch driver passes `--subtype`, so gating the identity on it
    # alone made this naming branch DEAD IN EVERY PRODUCTION RUN: of 504 runs, 32 had 1-4 ENRICHED
    # strata and Q4 printed the COUNT while withholding every identity (CDKN2A/HNSC: "4/11 enriched",
    # the top stratum being `site_oropharyngeal` — the HPV-associated site, i.e. exactly the fact the
    # row exists to deliver). The by-subtype claim vector already ranks the enriched identities, so
    # fall back to its data-driven pick.
    #
    # The two are LABELLED APART on purpose and must never collapse into one word: a SPOTLIGHT is what
    # the CALLER asked to foreground, a TOP is what the DATA says. The same field name already means
    # the other thing on the sibling cell-line card (a genuine argmax over enriched strata), which is
    # how one token came to carry two meanings across two cards in the first place.
    spot = s.get("spotlight_subtype") or h.get("spotlight_subtype")
    sv = sv or {}
    named, named_kind = (spot, "spotlight") if spot else (sv.get("top_enriched_subtype"), "top")
    # HONEST capability grade first: an underpowered/empty axis must NOT read as a differential, even
    # when a single stratum happens to clear the enrichment delta (NSCLC KRAS_G12C / DepMap STAD-PAAD).
    quality = s.get("subtype_axis_quality") or h.get("subtype_axis_quality")
    if quality in ("unavailable", None) and (
        not cls or cls in ("data_unavailable", "subtype_axis_unavailable", "no_subtype_axis")
    ):
        sig, primary = _sig("unmeasured", "no subtype axis"), "no molecular-subtype axis for this indication"
    elif quality in ("empty", "underpowered"):
        # axis is DEFINED but not usable — say so; never assert a cross-subtype contrast here.
        detail = "all strata empty" if quality == "empty" else f"only {nenr or 0}/{nmeas or 0} powered — underpowered"
        sig = _sig("unmeasured", f"axis {quality}")
        primary = f"subtype axis present but {quality} ({detail}); not a usable selection axis"
    elif cls in SUBTYPE_DIFFERENTIAL_CLASSES:
        if is_differential_axis(quality):
            sig = _sig("moderate", f"enriched: {named}" if named else "subtype-differential")
            primary = f"{cls}" + (f" ({named_kind} {named})" if named else "") + f"; {nenr}/{nmeas} enriched"
        else:
            # The class is derived from MEASURED strata only, so a single measured-enriched stratum in
            # an `exploratory` (or weaker) family yields `subtype_enriched` while the axis-quality grade
            # says the axis is not powered. That is a HYPOTHESIS, not a usable cross-subtype selection
            # axis — exactly what the comment above (:189-190) intends to block. Say the grade; never
            # assert a differential here. (`quality` is exploratory/unevaluable/None on this branch;
            # empty/underpowered were handled above.)
            grade = quality or "ungraded"
            sig = _sig("unmeasured", f"axis {grade}")
            primary = (
                f"subtype axis {grade} — {cls} in a single stratum is hypothesis-grade, "
                f"not a usable selection axis ({nenr}/{nmeas} enriched)"
            )
    else:  # pan_subtype_uniform (on a powered axis)
        sig = _sig("uniform", "uniform across subtypes")
        primary = f"pan-subtype uniform ({nenr or 0}/{nmeas} enriched)"
    clcard = c.get("cellline-rna-distribution-by-subtype", {})
    clsub = clcard.get("subtype_stratification_class")
    # Card 9's capsule class is derived from MEASURED strata only, so a single measured-enriched
    # cell-line stratum in an `exploratory` (or weaker) DepMap family yields `subtype_enriched` while
    # its own `subtype_axis_quality` says the genotype axis is not powered — no routed family reaches
    # `powered` today (ledger: powered never emitted; observed exploratory/underpowered/unevaluable).
    # Gate on that grade (same predicate as the tumour axis above) so the support bit never surfaces a
    # hypothesis-grade class as a bare differential fact. Card 9 is display-only (feeds no ladder),
    # so this stays verdict-inert.
    clsub_quality = clcard.get("subtype_axis_quality") or h.get("cellline_subtype_axis_quality")
    hom = h.get("sc_tce_homogeneity_class")
    support_bits = []
    # The full RANKED enriched set, when there is more than one. `primary` names the single best pick;
    # a bare count ("4/11 enriched") cannot tell a reader whether that is one stratum or four, and the
    # identities are what decides whether the axis is a usable selection handle. Already ranked by
    # stratum median in the claim vector, so pass no `rank_by`.
    enriched_names = _top_labels(sv.get("enriched_subtypes"), "stratum", k=3)
    if len(enriched_names) > 1:
        support_bits.append("enriched: " + ", ".join(enriched_names))
    if quality == "powered":
        support_bits.append("axis powered")
    if clsub:
        if is_differential_axis(clsub_quality):
            support_bits.append(f"cell-line (genotype axis): {clsub}")
        elif clsub in SUBTYPE_DIFFERENTIAL_CLASSES:
            grade = clsub_quality or "ungraded"
            support_bits.append(f"cell-line (genotype axis, {grade}): {clsub} — hypothesis-grade")
        else:
            # pan_subtype_uniform / data_unavailable etc. carry no differential claim; show verbatim.
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
_PCT_TIER = {
    "top_1pct": "strong",
    "top_decile": "moderate",
    "mid": "weak",
    "bottom_decile": "absent",
    "data_unavailable": "unmeasured",
}


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


# `rna_as_biomarker`'s class cuts, mirrored from the producer for ONE read-only purpose: saying when
# the other correlation would have landed in a different class. Nothing here re-classifies anything —
# the verdict shown is always the producer's own.
_PROXY_R_CUTS = ((0.7, "adequate_proxy"), (0.4, "partial_proxy"))


def _proxy_class(r) -> Optional[str]:
    """Which `rna_as_biomarker` class a correlation falls in; ``None`` when it is not a real number."""
    if isinstance(r, bool) or not isinstance(r, (int, float)) or r != r:
        return None
    for cut, name in _PROXY_R_CUTS:
        if r >= cut:
            return name
    return "poor_proxy"


def _fmt_r(r) -> str:
    """A correlation at 2 dp, widened only as far as it takes to stop MISSTATING ITS OWN CLASS.

    Rounding is a second way for this row to argue with itself: a Spearman of 0.6972 prints as "0.70",
    which is the `adequate_proxy` cut, directly beside a `partial_proxy` verdict — and 0.3954 prints as
    "0.40" beside `poor_proxy`. Measured on the n=504 corpus: of 1140 emitted correlations, 36 round
    across a class cut at 2 dp; 15 of those are the number a row actually SHOWS (15/570 = 2.6%) and 5
    more are the Pearson printed in the divergence caveat. Precision widens only for those, so the
    common case stays 2 dp and the boundary case stops contradicting the label beside it.

    WHY A LADDER RATHER THAN A FIXED 3 dp. 3 dp happens to suffice for all 36 (measured), but that is
    luck, not a property: any value in [0.6995, 0.7) still rounds up to "0.700". The producer emits
    `round(spear, 4)` / `round(pear, 4)` at both call sites (`depmap_rna_protein_concordance/read.py`),
    so 4 dp is a STRUCTURAL bound, not an observed one — trying 2 → 3 → 4 makes the last rung the
    identity on anything the producer can emit, so the ladder terminates on a faithful class by
    construction rather than by luck.
    """
    for dp in (2, 3, 4):
        if _proxy_class(round(r, dp)) == _proxy_class(r):
            return f"{r:.{dp}f}"
    return f"{r:.4f}"


def _proxy_corr(spearman, pearson) -> tuple:
    """``(rendered_text, divergence_note)`` for the correlation behind an `rna_as_biomarker` class.

    SHOW THE CORRELATION THAT ACTUALLY CLASSIFIED. The producer classifies on SPEARMAN — its G10 note
    records why: the mRNA↔protein relation is monotonic-but-nonlinear and outlier-prone, so the rank
    correlation is the consensus proteogenomics metric and is less flip-prone at the same n — and it
    deliberately keeps `rna_protein_r` as PEARSON. This row printed the Pearson r beside the
    Spearman-derived verdict, so the displayed number's OWN class contradicted the label next to it in
    113 of 375 cell-line rows (30.1%) and 31 of 195 tumor rows (15.9%) of the n=504 corpus. Worst case
    ALK/NSCLC rendered "poor_proxy (r=0.86)" against a Spearman of 0.14, which reads as a row arguing
    with itself. All 570 of those rows carried `rna_proxy_classified_on == "spearman"`, so the shown
    metric was never once the deciding one.

    The divergence is surfaced, not hidden: a wide Pearson↔Spearman gap IS the outlier-driven linearity
    the rank metric was chosen to resist, so it belongs on the caveat line as evidence about the
    correlation rather than being dropped as disagreement.

    When Spearman is absent the producer fell back to Pearson, and then Pearson IS the classifier — so
    it renders unlabelled. The label tracks WHAT DECIDED, never a fixed metric name.
    """
    if isinstance(spearman, (int, float)) and not isinstance(spearman, bool) and spearman == spearman:
        pear_class = _proxy_class(pearson)
        note = None
        if pear_class and pear_class != _proxy_class(spearman):
            note = f"Pearson r={_fmt_r(pearson)} would read {pear_class} — outlier-driven linearity"
        return f" (ρ={_fmt_r(spearman)})", note
    if isinstance(pearson, (int, float)) and not isinstance(pearson, bool) and pearson == pearson:
        return f" (r={_fmt_r(pearson)})", None
    return "", None


def _q6_concordance(h, c, cv):
    tum = c.get("rna-protein-concordance-tumor", {})
    clc = c.get("cellline-rna-protein-concordance", {})
    bio = tum.get("rna_as_biomarker") or h.get("rna_as_biomarker_tumor")
    n = tum.get("n_paired_tumors") or h.get("rna_protein_n_paired_tumors")
    # Both correlations are fetched HERE, at the card-aliased `.get()`, and passed to the renderer as
    # VALUES. The field-disposition census recovers an exact (card, field) pair only from a statically
    # bound read site (`cp = c.get("card-id") ... cp.get("field")`), so a field pulled through a
    # helper's parameter is a real read the instrument cannot see. Fetching here keeps both
    # `rna_protein_spearman` pairs visibly REACHED rather than silently counted as orphans.
    tum_spear, tum_pear = tum.get("rna_protein_spearman"), tum.get("rna_protein_r")
    cl_spear, cl_pear = clc.get("rna_protein_spearman"), clc.get("rna_protein_r")
    # The card's most decision-relevant proxy-reliability datum (#1526 F3): the fraction of
    # RNA-expressed cell lines whose PROTEIN sits in the bottom decile — i.e. the population where a
    # high RNA read MISLEADS as a protein proxy (don't select those patients on RNA). Fetched at the
    # card-aliased `.get()` (see the census note above) so the read is visible, then surfaced as a
    # caveat. The sibling `protein_detection_fraction` / `rna_expressed_fraction` are panel-coverage
    # bookkeeping, not proxy-reliability, so this row deliberately keeps them minimal (not surfaced here).
    cl_rna_high_prot_low = clc.get("rna_high_protein_low_fraction")
    tier = {"adequate_proxy": "strong", "partial_proxy": "moderate", "poor_proxy": "weak"}.get(bio, "unmeasured")
    rtxt, rnote = _proxy_corr(tum_spear, tum_pear if tum_pear is not None else h.get("rna_protein_r_tumor"))
    primary = f"tumor: {bio or 'n/a'}" + rtxt
    clbio = clc.get("rna_as_biomarker")
    cltxt, clnote = _proxy_corr(cl_spear, cl_pear)
    bits = [f"cell-line: {clbio}{cltxt}"] if clbio else []
    bits += [f"⚠ {arm} {note}" for note, arm in ((rnote, "tumor"), (clnote, "cell-line")) if note]
    if (
        isinstance(cl_rna_high_prot_low, (int, float))
        and not isinstance(cl_rna_high_prot_low, bool)
        and cl_rna_high_prot_low > 0
    ):
        bits.append(f"⚠ RNA misleads in {cl_rna_high_prot_low:.0%} of cell lines (RNA-high, protein-low)")
    support = " · ".join(bits) if bits else "—"
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
    from _skills_common.presence_claims import presence_claim_vector, presence_claim_vector_by_subtype

    cv = claim_vector or headline.get("claim_vector") or presence_claim_vector(headline, cards)
    c = _cbyid(cards)
    # The BY-SUBTYPE vector is resolved separately because the pooled `cv` is letter-keyed (A..D) and
    # carries no stratum identities; the enriched-stratum names live only here. Composed rather than
    # re-derived so the ranking stays in ONE place — a second copy of "which stratum is most enriched"
    # is the two-files-route-the-same-axis drift trap. `None` (no by-subtype card) degrades to `{}`,
    # and every consumer below treats an absent identity as "not named", never as "none enriched".
    sv = presence_claim_vector_by_subtype(cards) or {}
    return [
        _q1_abundance(headline, c, cv),
        _q2_generality(headline, c, cv),
        _q3_vs_normal(headline, c, cv),
        _q4_subtype(headline, c, cv, sv),
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


def render_question_table_html(
    rows: list,
    verdict: Optional[str] = None,
    include_css: bool = True,
    title: str = "Presence",
    signal_header: str = "Signal — supports presence →",
) -> str:
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
            f'<tr><td class="qid">{esc(str(r.get("id", "")))}</td>'
            f'<td class="qq">{esc(str(r.get("question", "")))}</td>'
            f'<td class="qd"><div>{esc(str(r.get("primary", "")))}</div>'
            f'<div class="qsupport">{esc(str(r.get("support", "")))}</div></td>'
            f'<td class="qsig"><span class="meter">{meter}</span>'
            f'<span class="siglab {pol}">{esc(str(s.get("label", "")))}</span></td>'
            f'<td class="qconf"><span class="dots">{dots}</span></td></tr>'
        )
    cap = (
        f'<div class="qtcap">{esc(title)} at a glance'
        + (f' · verdict <span class="verdict">{esc(str(verdict))}</span>' if verdict else "")
        + ' <span class="hint">— Signal (strength · polarity) &amp; Confidence '
        "(corroboration), computed from the claim-vector; verdict-inert.</span></div>"
    )
    head = f"<tr><th>Q</th><th>Question</th><th>Data / read</th><th>{esc(signal_header)}</th><th>Conf</th></tr>"
    css = f"<style>{QUESTION_TABLE_CSS}</style>" if include_css else ""
    return f'{css}{cap}<table class="qtable"><thead>{head}</thead><tbody>{"".join(trs)}</tbody></table>'


__all__ = ["presence_question_table", "render_question_table_html", "QUESTION_TABLE_CSS"]
