"""Single-cell normal-tissue cell-type presence primitives (numpy/pandas-only, no S3).

Reads the Tier-1 cross-donor aggregation product (sc-normal-celltype-expression-{tissue}-v1)
and classifies the gene's normal-tissue liability across all cell types. The Tier-1 product
already has cross-donor statistics (median_det, expressing_donor_fraction, n_donors_reliable)
— this module does NO further donor-level aggregation; it classifies across cell types.

LIABILITY LADDER (mirrors the F5 rules in surface-intrinsic.rules.yaml):
  HIGH_LIABILITY:      any cell type has median_det > 0.50 AND expressing_donor_fraction > 0.70
  MODERATE_LIABILITY:  any cell type has median_det > 0.20 OR expressing_donor_fraction > 0.30
  LOW_LIABILITY:       detected but below MODERATE thresholds
  NOT_EXPRESSED:       all cell types have median_det < 0.01
  data_unavailable:    no Tier-1 product, or all n_donors_reliable < MIN_RELIABLE_DONORS

Both HIGH thresholds must be met (AND): requiring BOTH magnitude and consistency prevents a
high-variance gene in one small-n donor from triggering a killer rule. MODERATE uses OR:
either consistent detection or high fraction is enough to warrant a safety flag.
"""

from __future__ import annotations

import re

import pandas as pd

# --- Thresholds (match the card's thresholds block in sc-normal-celltype-expression.card.yaml) ---
HIGH_LIABILITY_DET_THRESHOLD = 0.50
HIGH_LIABILITY_DONOR_FRACTION = 0.70
MODERATE_LIABILITY_DET = 0.20
MODERATE_DONOR_FRACTION = 0.30
NOT_EXPRESSED_CEILING = 0.01
MIN_RELIABLE_DONORS = 5

# Normal-tissue ABUNDANCE bands (#984 Tier-2): the liability ladder above is DETECTION-only, so a normal
# cell detected at trivial vs high abundance reads the same liability — yet detection >0.2 spans a ~25x
# abundance range (median_abund log1p_cp10k). These fixed bands are the p25/p75 of the detected-abundance
# distribution, VALIDATED as tissue-invariant across colon/lung/kidney/liver/brain/pancreas (p25≈0.20-0.26,
# p75≈0.61-0.66), so fixed constants are tissue-robust. Classified at the LIABILITY-anchor cell type.
# VERDICT-INERT (display/confidence): a low_abundance normal liability (e.g. FOLR1/ERBB2-class) is a
# candidate veto down-weight, but that is a SEPARATE backtest-gated change in tumor-selectivity.
NORMAL_ABUND_HIGH = 0.64
NORMAL_ABUND_MODERATE = 0.24

# --- REPLICATION-DOMINANT severity path (see _essential_severity) ---
# The severity ladder's high rung is a CONJUNCTION over det x donor-fraction x atlas count, so a hit
# that misses the single detection line grades `moderate_severity` no matter how many independent
# atlases agree. Measured live over all 504 corpus-20260914 pairs, MSLN-PAAD is the clean case: a
# pulmonary alveolar type 1 cell at det 0.413 / donor 0.881 across **26 atlases** — the strongest
# replication in the corpus — graded `moderate_severity` and therefore relieved the dominant BiTE/TCE
# killer, while a 2-atlas hit at det 0.51 fires it.
#
# The relaxation is deliberately BOUNDED, and only the DETECTION line is tradeable:
#   * det >= 0.40 — within 0.10 of HIGH_LIABILITY_DET_THRESHOLD. An open-ended path gated only at the
#     moderate floor (0.30) promotes 350/504 (69.4%); bounding it at 0.40 promotes 284 (56.3%), i.e.
#     the bound is doing the work, not the atlas count.
#   * >= 15 atlases — the corpus p90 of n_datasets_reliable over accessible essential hits
#     (measured min 1 / p25 2 / median 6 / p75 10 / p90 15 / p95 17 / max 30). A floor of 5 would sit
#     BELOW the median, so "heavy replication" would describe a TYPICAL hit: that variant promotes
#     364/504 (72.2%).
#   * donor consistency is NOT tradeable — HIGH_LIABILITY_DONOR_FRACTION still applies. Replication
#     tells you a signal is REAL; it does not tell you it is CONSISTENT ACROSS DONORS, and those are
#     different claims.
#   * the low band (det < 0.30) is NOT rescuable. Replication makes a weak signal credible, not large.
# Live effect of this path ALONE, on top of the worst-hit fix: +2 pairs (MSLN-PAAD, NOTCH2-HNSC). It is
# a scalpel, not a broadening — which is the point.
REPLICATION_DOMINANT_DET_FLOOR = 0.40
REPLICATION_DOMINANT_N_DATASETS = 15

# --- COMPARTMENT split of the always-on safety-essential organs (veto-grade instrument) ---
# WHY THIS EXISTS. sc_normal_safety_essential_class == critical_organ_liability fires on 468 of the 504
# (target, indication) pairs in corpus-20260914 — a 92.9% base rate — and its single largest driver is
# the BRAIN shard (259 of 468, 55.3%; cortical/forebrain neurons, medium spiny neurons and astrocytes
# together ~45% of all firings). Two mechanisms compound: neurons carry the broadest transcriptome of
# any cell type, so median_det > 0.20 in a cortical neuron is close to the null expectation for any
# expressed gene; and brain is the largest shard in the always-on set (36M cells / 172 cell types), so
# the ANY-quantifier runs over more candidates there than anywhere else (median 150 cell types clear
# the floor across the corpus, max 831).
#
# The consumer is what makes that a defect rather than a curiosity: the class drives
# `sc-normal-high-liability-bite-killer`, which is `dominant: true` and signals bite_tce ONLY. A
# systemically dosed T-cell engager is the modality LEAST able to reach brain parenchyma, so the
# dominant driver of a BiTE-specific killer is its least relevant compartment. The framework's own
# validated case proves the cost: DLL3/SCLC — tarlatamab's target, an APPROVED TCE — is vetoed today
# with `brain` as its named driver organ.
#
# ★ BUT THE ARGMAX ORGAN IS NOT THE COMPARTMENT, AND MEASURING IT LIVE MOVED THE ANSWER BY 6x.
# The 55.3% brain figure above is the share of firings whose NAMED DRIVER (the argmax over the pool) is
# brain. It is NOT the share that is brain-ONLY. Re-measured by running this method live against S3 for
# all 504 corpus pairs — exact, no truncation — **230 of those 259 brain-argmax calls (88.8%) ALSO carry
# an above-floor essential hit in a systemically accessible organ**, so only 29 of 468 (6.2%) are truly
# brain-only. (An earlier estimate of 37.1% was computed from the stored top-15 `per_cell_type_top`
# footprint, which truncates exactly the broad targets that drive the base rate — some carry 80-143 cell
# types above 0.20. It was a floor, and a very loose one.)
#
# TWO CONSEQUENCES, both load-bearing:
#   1. The fail-closed partition below is MORE necessary than the estimate suggested: an argmax-based
#      compartment call would have mislabelled 230 targets `bbb_protected`, i.e. relieved a dominant
#      safety killer on real lung/liver/marrow liabilities. The pool scan is not belt-and-braces.
#   2. The COMPARTMENT axis is NOT what repairs the base rate — it is worth only 29 targets. Keep it for
#      its correctness role (and because brain-only genuinely should not take a systemic-TCE killer), but
#      do not credit it with the base-rate repair; the SEVERITY rung does the bulk of the work.
#
# ⚠️ RETRACTED 2026-09-18 (#660): this block previously claimed the severity rung "works better here
# than a naive read predicts precisely BECAUSE it grades the worst ACCESSIBLE hit rather than the
# argmax ... so argmax-based severity systematically OVER-graded". BOTH halves were wrong.
#   * The code did NOT grade the worst accessible hit — it took a detection ARGMAX and graded that
#     (the prose described the intent, the code did something else). #660 made them agree.
#   * The argmax did not OVER-grade, it systematically UNDER-graded, and the direction is measured:
#     110 of 439 pairs with an accessible hit (25.1%) graded BELOW their worst accessible hit, 59 of
#     them escaping the dominant killer entirely; ZERO pairs graded higher. The mechanism is that a
#     single-atlas detection fraction is unshrunk and therefore wins a max over detection, while
#     _essential_severity sends n_ds <= 1 to low_confidence — the selection criterion was
#     ANTI-CORRELATED with the grading criterion (argmax hit was single-atlas in 104 of the 110
#     under-graded pairs, 94.5%, vs 8.2% of correctly-graded pairs).
#
# LIVE, EXACT, all 504 pairs. Two distributions — do not conflate them:
#   PRE-#660 (detection argmax): accessible_high_severity 223 (44.2%) / accessible_low_confidence 145
#     (28.8%) / accessible_moderate_severity 71 (14.1%) / bbb_protected 29 / not_applicable 29 /
#     origin_tissue 7 / accessible_ungraded 0.
#   POST-#660 (worst-grade + the replication path above): accessible_high_severity 284 (56.3%) /
#     accessible_moderate_severity 114 / accessible_low_confidence 41 / bbb_protected 29 /
#     not_applicable 29 / origin_tissue 7 / accessible_ungraded 0. Note where the 61 promotions came
#     FROM: low_confidence collapses 145 -> 41 while moderate RISES 71 -> 114, because grading the
#     worst hit lifts a low_confidence pool to whatever its worst member actually is, which is usually
#     moderate rather than high.
#   CURRENT (the above, plus this PR's essential-VOCABULARY fix): accessible_high_severity 292 (57.9%)
#     / accessible_moderate_severity 111 / accessible_low_confidence 40 / bbb_protected 25 /
#     not_applicable 29 / origin_tissue 7 / accessible_ungraded 0. bbb_protected falls 29 -> 25
#     because 4 pairs whose only above-floor off-origin hits were brain parenchyma turn out to have a
#     renal-tubule hit that no entry could match.
#
# ⚠️ A DRAFT of the POST-#660 line above read "95 / 60" for the moderate/low_confidence split. That was
# never measured by this code: it came from a harness that REIMPLEMENTED _essential_severity rather than
# calling it. The totals happened to reconcile (95+60 == 114+41 == 155), which is exactly why it was not
# obvious. Numbers in this block must come from calling classify_sc_normal_expression itself.
# `sc_normal_safety_essential_class` is BYTE-IDENTICAL across the two (468 critical / 29 bbb / 7
# origin): #660 moved only the grade, and only upward. The grade is a strict REFINEMENT of the class:
# every non-critical arm maps 1:1 (none→not_applicable, origin_tissue_liability→origin_tissue), so the
# LABEL-not-DROP property is verified on live data, not just asserted.
#
# RAISING THE DETECTION FLOOR CANNOT FIX THIS, and that is measured exactly (the named driver is the
# argmax over above-floor off-origin hits, so the counterfactual is computable rather than simulated):
# floors of 0.30/0.50/0.70/0.90 leave base rates of 89.3/81.0/67.5/42.9%. Even 0.90 leaves a coin flip,
# and the observed minimum is 0.219 — nothing sits near the current floor. Detection fraction is a
# SATURATING statistic (corpus median 0.871, p75 0.970): it has run out of headroom, which is the same
# axis-not-threshold failure recorded for the abundance bands above.
#
# So the compartment is graded as a separate dimension and composed into
# `sc_normal_essential_veto_grade` (below), leaving sc_normal_safety_essential_class BYTE-IDENTICAL.
# Nothing is reclassified to the favourable `none`: this LABELS the veto's basis, it does not DROP it.
BBB_PROTECTED_TISSUES = frozenset({"brain"})

# Safety-essential normal cell types: any detection in these types forces a dedicated flag.
# These map to Census Cell Ontology labels (raw, no synonymy). WHOLE-TOKEN matching is used so a
# lineage token matches its subtypes wherever the token appears as a standalone word (e.g. "neuron"
# → "dopaminergic neuron", "cardiac neuron", "central nervous system neuron"), WITHOUT matching a
# different word that merely CONTAINS the token as a substring (e.g. "neuron" must NOT match
# "non-neuronal cell" / "neuronal-restricted precursor"). See _is_safety_essential.
SAFETY_ESSENTIAL_CELL_TYPE_PREFIXES = (
    "cardiomyocyte",
    "cardiac muscle cell",
    "hepatocyte",
    "neuron",
    # --- RENAL TUBULE (2026-09-18). Three entries here were measured against the real 670-label
    # shard vocabulary and two of them were silently under-calling. See the CONJUNCTIVE entry form
    # documented at _SAFETY_ESSENTIAL_PATTERNS: a tuple means "all of these runs, in any order".
    #
    # `"kidney proximal tubule"` matched ZERO of 670 labels: Census names this compartment with an
    # of-INVERSION ("epithelial cell of proximal tubule"), so the contiguous phrase could never fire
    # and the nephron's most drug-exposed segment was UNFLAGGED. A conjunction rather than the head
    # noun "proximal tubule", because one real label ALSO interposes a word
    # ("kidney proximal CONVOLUTED tubule epithelial cell"). Measured: ("proximal","tubule") matches
    # exactly the 4 proximal labels and nothing else — every label in the vocabulary containing
    # "proximal" is a proximal-tubule label, so the conjunction cannot over-reach.
    ("proximal", "tubule"),
    # DISTAL nephron, previously unflagged in its entirety. The list already covered loop of Henle and
    # (partially) collecting duct, so omitting the distal convoluted and connecting tubules was an
    # inconsistency rather than a decision: they are segments of the same functional unit and the same
    # nephrotoxicity compartment. Measured 3 + 2 labels. One of the 3 ("epithelial cell of distal
    # tubule") is present ONLY in the LUNG shard, which is Census annotation leakage rather than a
    # real ectopic nephron — see the note on "nephron" below for why flagging it is the safe side.
    ("distal", "tubule"),
    ("connecting", "tubule"),
    # `"kidney collecting duct"` matched only 4 of the 7 kidney collecting-duct labels. The other 3
    # INTERPOSE an anatomical qualifier ("kidney CORTEX collecting duct epithelial cell", "kidney
    # INNER MEDULLA ...", "kidney OUTER MEDULLA ..."), breaking contiguity. Loosening to a bare
    # "collecting duct" would have been wrong in the other direction — it flags the lung's
    # "airway submucosal gland collecting duct epithelial cell", which is not renal. The conjunction
    # drops the ADJACENCY requirement while keeping the KIDNEY restriction: 7 of 7, no lung hit.
    ("kidney", "collecting duct"),
    "kidney loop of henle",
    # NEPHRON generic parents — the terms Census uses when the atlas did not resolve the segment
    # ("epithelial cell of nephron", "nephron tubule epithelial cell", "mesonephric nephron tubule
    # epithelial cell"). All 3 were unflagged. NB two of them also appear in the liver and skin
    # shards, which is Census annotation leakage rather than real ectopic nephron; flagging them
    # there is fail-CLOSED and the veto reports the (tissue, cell_type) pair, so the oddity is
    # visible in the named driver rather than hidden.
    "nephron",
    # `"pneumocyte"` matches ZERO of 670 labels (measured 2026-09-18) — Census uses
    # "pulmonary alveolar type 1/2 cell", never "pneumocyte". Its former comment ("# alveolar type
    # I/II") asserted coverage it did not provide: AT1/AT2 were in fact caught by the NEXT entry, so
    # the arm worked by accident. KEPT deliberately (a disjunct that matches nothing is inert, and
    # "type I pneumocyte" is a live CL synonym that a future Census release could adopt) but now
    # DECLARES its own inertness so the next reader does not re-derive the same false assurance.
    "pneumocyte",  # MEASURED INERT today — AT1/AT2 coverage comes from the two entries below
    # `"alveolar type"` was wrong in BOTH directions:
    #   * FALSE POSITIVE — it matched "alveolar type 1 FIBROBLAST cell", putting a stromal
    #     fibroblast into a vital-organ veto (it reaches shipped fixtures: erbb2_coadread carries it).
    #   * FALSE NEGATIVE — it missed the generic epithelial parents "pulmonary alveolar epithelial
    #     cell" and "fetal pre-type II pulmonary alveolar epithelial cell".
    # Requiring "pulmonary" excludes the fibroblast (which carries no such token) while keeping all
    # 3 AT1/AT2 labels; the conjunction picks up the 2 generic epithelial parents.
    "pulmonary alveolar type",
    ("alveolar", "epithelial cell"),
    # --- GUT / INTESTINAL EPITHELIUM (2026-09-18, backtest-gated). `enterocyte` + `colonocyte`
    # covered only the DIFFERENTIATED ABSORPTIVE lineage. Measured against the real 670-label shard
    # vocabulary, that left every compartment that actually drives dose-limiting GI toxicity
    # unflagged: the CRYPT is the proliferative compartment an antimitotic ADC payload or a TCE
    # depletes, and the resulting mucositis / diarrhoea — not loss of mature enterocytes — is the
    # classic dose-limiting event. Added together with `gut -> "colon"` in SC_NORMAL_CROSSWALK,
    # because promoting the organ WITHOUT extending this list would ship an always-on shard whose
    # most drug-exposed cell type no entry matches: coverage that reads as coverage and is not (the
    # same fail-open the renal block above closes, in the same file, for the same reason).
    "enterocyte",
    "colonocyte",
    # CRYPT stem cell — 4 labels (bare + `of colon` / `of large intestine` / `of small intestine`),
    # all previously unflagged. The bare run "crypt" is used rather than the full
    # "intestinal crypt stem cell": MEASURED, every label in the vocabulary containing "crypt" IS an
    # intestinal crypt stem cell, so the two select identically today, and the shorter run also
    # catches a future crypt-base-columnar / crypt-progenitor label. Known theoretical over-reach:
    # Cell Ontology also has tonsillar-crypt epithelium, which NO landed shard contains — and
    # over-flagging is the fail-CLOSED direction, with the (tissue, cell_type) pair visible in the
    # named driver rather than hidden.
    "crypt",
    # TRANSIT AMPLIFYING cells — 3 labels. The rapidly dividing crypt daughters; the compartment an
    # antiproliferative payload depletes first, and the reason GI tox is dose-limiting rather than
    # cumulative.
    "transit amplifying cell",
    # PANETH cells — 3 labels. Antimicrobial secretory; Paneth-cell loss is a recognised readout of
    # gut injury (GVHD, ADC enteropathy).
    "paneth cell",
    # GOBLET / mucin barrier, restricted to the GI labels by CONJUNCTION. A bare "goblet cell" was
    # measured to match 11 labels, FIVE of them AIRWAY (bronchial / lung / nasal mucosa / respiratory
    # tract / tracheobronchial). Flagging those would change the LUNG arm's semantics — not this
    # change's subject, and it would make this change's backtest unattributable. The bare
    # `goblet cell` label is additionally shard-promiscuous (present in adrenal_gland and liver,
    # i.e. Census annotation leakage). `ileal goblet cell` is small_intestine-ONLY, hence
    # on-origin-only, and is left out for the same attribution reason.
    ("goblet", "intestine"),
    ("goblet", "colon"),
    # GENERIC EPITHELIAL PARENTS — the terms Census uses when an atlas did not resolve the lineage,
    # exactly the class the nephron block above covers. Each matches exactly ONE label:
    # "intestinal epithelial cell", "colon epithelial cell", "epithelial cell of small intestine",
    # "gut absorptive cell". Without them an atlas that annotated only to the parent contributes
    # NOTHING to the veto while looking like it was examined.
    ("intestinal", "epithelial cell"),
    ("colon", "epithelial cell"),
    ("intestine", "epithelial cell"),
    "gut absorptive cell",
    # DELIBERATELY EXCLUDED, measured, so the next reader does not read the omission as an oversight:
    # "tuft cell" (4 labels) and "enteroendocrine" (12) are not the dose-limiting GI compartment, and
    # a bare "enteroendocrine" reaches PANCREAS / lung / liver / spleen labels — it would silently
    # re-grade those arms rather than the gut's.
    "hematopoietic stem cell",
    "erythroid progenitor",
    # S1-3 (cards review 2026-08-17): CNS glia + adrenal endocrine cells, so the newly always-on
    # brain + adrenal_gland shards actually flag their essential cell types ("neuron" already covers
    # CNS neurons; adrenal cortical/medullary + chromaffin were previously unflagged).
    "astrocyte",
    "oligodendrocyte",
    "adrenal",  # adrenal cortical / gland cells
    "chromaffin",  # adrenal medulla
    # --- W3b (2026-09-04, backtest-gated): essential cell types the always-on shards contained but
    # no prefix matched — so the veto silently under-called them. Labels are the RAW Census Cell
    # Ontology strings actually present in the shards (verified via a reader-level probe); a naive
    # "beta"/"islet" prefix would be INERT because Census uses "type B pancreatic cell" etc.
    #
    # Pancreatic ISLET ENDOCRINE — the headline gap: the pancreas shard was promoted always-on
    # "for islet safety" (SC_NORMAL_CROSSWALK, 2026-08-19) but NO islet prefix existed, so that
    # promotion was inert. β-cell loss → diabetes is the catastrophic islet liability; the other
    # endocrine islet cells (α/δ/PP/ε) round out the functional unit. A β-restricted target (e.g.
    # SLC30A8/INS/IAPP) now correctly flips to critical_organ_liability for a NON-pancreatic
    # indication (origin_tissue_liability for PAAD, where the islet is on-tissue).
    "type b pancreatic cell",  # β-cell (insulin) — CL:0000169
    "pancreatic a cell",  # α-cell (glucagon)
    "pancreatic d cell",  # δ-cell (somatostatin)
    "pancreatic pp cell",  # PP/γ-cell (pancreatic polypeptide)
    "pancreatic epsilon cell",  # ε-cell (ghrelin)
    # Kidney PODOCYTE — glomerular filtration barrier; loss → proteinuria/nephrotic syndrome
    # (well replicated: n_datasets_reliable=17 in the kidney shard).
    "podocyte",
    # SCHWANN cell — peripheral-nerve glia; loss → peripheral neuropathy (a recognised on-target
    # liability class). Present across multiple shards (colon/pancreas/lung/heart/skin).
    "schwann cell",
    # Basal KERATINOCYTE / epidermal basal layer — skin regenerative compartment. Skin is queried
    # only for its origin indication (SKCM), so this reads as origin_tissue_liability there rather
    # than a cross-indication veto; added for correctness + forward use if skin becomes off-origin.
    "keratinocyte",
    "basal cell of epidermis",
    # CORNEAL / LIMBAL epithelium — FOLR1's real dose-limiting toxicity is OCULAR (keratopathy).
    # SUBSTRATE-PENDING: there is currently NO eye/cornea shard in TISSUE_TO_PRODUCT, so these
    # prefixes match nothing today (INERT). Listed so the ocular liability activates automatically
    # when a corneal/limbal normal shard lands, and to document the known FOLR1 ocular gap.
    "corneal epithelial cell",
    "limbal stem cell",
    # Pancreatic ACINAR (exocrine) — loss → exocrine pancreatic insufficiency. Well-replicated in
    # the pancreas shard (n_datasets_reliable=7); "pancreatic acinar cell" is used rather than bare
    # "acinar cell" because the only non-pancreatic "acinar cell" label in the shards is a
    # single-atlas (n_datasets_reliable=1) lung airway-gland hit whose det=0.92 would otherwise
    # become the NAMED driver of a validated antigen off one dataset.
    "pancreatic acinar cell",
    # CHOLANGIOCYTE / biliary epithelium — loss → cholestatic / biliary injury. Well-replicated in
    # the liver shard (cholangiocyte n_datasets_reliable=10; "intrahepatic cholangiocyte" matched by
    # the same token). A recognised epithelial-antigen off-target (TROP2/HER2-class ADCs).
    "cholangiocyte",
    # ENDOTHELIUM — vascular endothelium is a dose-limiting organ (VEGF-axis / vascular-antigen
    # toxicity). BROAD by construction: "endothelial cell" whole-token-matches every endothelial
    # subtype ("glomerular endothelial cell", "vein endothelial cell", "endothelial cell of
    # sinusoid", ...), so a target with off-origin endothelial detection above the 0.20 floor now
    # flags critical_organ_liability. This is a DELIBERATE re-baseline (2026-09-04) — endothelium is
    # near-ubiquitous, so this widens the veto; it is offset by the modality-conditional rescue
    # (adc/bite_tce) in the per-modality selectivity lens, not by suppressing the honest scalar.
    "endothelial cell",
)


# Precompiled whole-token matchers, one per entry. `\b...\b` requires a word boundary on BOTH sides,
# so a token matches its subtypes ("neuron" → "dopaminergic neuron") but NOT a longer word that merely
# embeds it ("neuron" ∉ "neuronal-restricted precursor" — the trailing \b fails because "neuron" is
# followed by "al"). This replaces a former `pfx in ct` substring test, whose mid-word matches
# produced false essential flags.
#
# TWO ENTRY FORMS (the tuple form added 2026-09-18):
#   * str   — one CONTIGUOUS whole-token run ("kidney loop of henle", "type b pancreatic cell").
#   * tuple — a CONJUNCTION: every run must appear somewhere in the label, in ANY order or position.
#
# Why the tuple form exists. The str form can only say "these words, ADJACENT", and the two defects
# it could not express are both cases where the required words are present but NOT adjacent:
#   * of-INVERSION      Census "epithelial cell OF proximal tubule" vs a "kidney proximal tubule" entry
#   * INTERPOSED word   Census "kidney CORTEX collecting duct ..." vs a "kidney collecting duct" entry
# Both read as a clean no-match, i.e. a SILENT FAIL-OPEN in a safety veto — an inert disjunct looks
# exactly like a cell type that is genuinely absent from every shard. The conjunction relaxes only
# ADJACENCY while keeping every required word, which is strictly more precise than the tempting
# alternative of loosening to a bare head noun: a bare "collecting duct" would flag the lung's
# "airway submucosal gland collecting duct epithelial cell", which is not renal at all.
#
# MAINTENANCE CONTRACT: an entry that matches nothing is INDISTINGUISHABLE from an absent cell type,
# so every entry's live match count is asserted by
# tests/methods/sc_normal_expression/test_essential_prefix_vocabulary.py against a pinned snapshot of
# the real shard vocabulary, and any entry that is inert must say so IN ITS COMMENT (see
# "pneumocyte" / "corneal epithelial cell"). Do not add an entry without measuring it.
_SAFETY_ESSENTIAL_PATTERNS = tuple(
    tuple(re.compile(r"\b" + re.escape(run) + r"\b") for run in ((entry,) if isinstance(entry, str) else entry))
    for entry in SAFETY_ESSENTIAL_CELL_TYPE_PREFIXES
)


def _is_safety_essential(cell_type: str) -> bool:
    ct = cell_type.lower()
    # any ENTRY matches, and an entry matches only when ALL of its runs are present (a 1-run entry is
    # the old contiguous-phrase behaviour, unchanged).
    return any(all(pat.search(ct) for pat in runs) for runs in _SAFETY_ESSENTIAL_PATTERNS)


def _norm_tissue(tissue) -> str:
    """Canonicalize a tissue label so the SHARD-KEY vocabulary and the CENSUS `tissue` COLUMN compare
    equal. These are two different vocabularies that were being compared raw:

      * read.py's TISSUE_TO_PRODUCT / INDICATION_TO_TISSUES keys are the hyphen-free, UNDERSCORED
        shard names required to build the S3 product id ("prostate_gland" → the
        sc-normal-celltype-expression-prostate-gland-v1 product), and those same keys are what the
        caller hands us as `origin_tissues`.
      * the per-row `tissue` column carries the raw CELLxGENE Census value, which is SPACED
        ("prostate gland", "bladder organ", "bone marrow", "adrenal gland", "small intestine").

    So `row_tissue in origin` never matched for ANY multi-word origin tissue and the tumor's OWN organ
    was scored as an OFF-ORIGIN critical-organ liability — the hard-veto class. Measured on the
    36-target panel: KLK3/PRAD fired the veto on "prostate gland endothelial cell", i.e. prostate
    endothelium read as a critical off-target for prostate cancer. Reachable affected indications via
    INDICATION_TO_TISSUES are PRAD (prostate_gland) and BLCA (bladder_organ); every single-word origin
    (colon/lung/liver/kidney/brain/...) compared fine, which is why every existing test passed.

    Normalizing at COMPARISON time (not by respelling the shard keys) keeps the S3 product lookup intact.
    It is monotonic in the HARD-VETO direction only: reclassifying a hit as origin can only REMOVE an
    off-origin contribution, so it can never create or sustain a critical_organ_liability. It is NOT
    globally monotonic, because origin hits keep the lower 0.05 flag floor while off-origin hits need
    0.20 — so a 0.05–0.20 hit in the tumor's own organ moves `none` → origin_tissue_liability (the
    honest, window-arbitrated class). Measured: UPK1B/BLCA, where bladder urothelial expression of a
    uroplakin was previously invisible because the origin comparison failed and the hit then fell into
    the off-origin ambient band."""
    return re.sub(r"[\s_-]+", " ", str(tissue).lower()).strip()


def _essential_compartment(tissue) -> str:
    """`bbb_protected` | `systemically_accessible` for one essential-cell hit's organ.

    UNKNOWN TISSUE IS ACCESSIBLE, not protected. A None/blank tissue (older Tier-1 callers with no
    `tissue` column) must never earn the modality-relieving compartment — that would make a coverage
    gap look like a safety argument. Mirrors the existing origin split, which treats unknown tissue as
    off-origin for the same reason."""
    if tissue is None or not str(tissue).strip():
        return "systemically_accessible"
    return "bbb_protected" if _norm_tissue(tissue) in BBB_PROTECTED_TISSUES else "systemically_accessible"


# Severity ordering used to take the WORST grade over a pool of accessible essential hits.
# Ordered by VETO CONSEQUENCE first, then by measurement strength — see _essential_veto_grade. Keyed
# exhaustively on _essential_severity's return values so an added rung fails loudly (KeyError) rather
# than sorting silently as "lowest", which would be the fail-open direction.
_ESSENTIAL_SEVERITY_RANK = {
    "low_confidence": 0,
    "moderate_severity": 1,
    "ungraded": 2,  # killer-eligible: MUST outrank moderate, or a missing column relaxes the killer
    "high_severity": 3,  # same veto consequence as ungraded, but a MEASURED claim — prefer it as the label
}


def _essential_severity(rec: dict) -> str:
    """Grade ONE essential-cell hit by magnitude x consistency x replication.

    Thresholds are PORTED VERBATIM from the existing W3c grader at
    claude-oncology-skills skills/tumor-selectivity/scripts/run.py `_sc_normal_essential_severity`
    (det >= 0.50 AND donor >= 0.70 AND >= 2 atlases → high; det < 0.30 OR <= 1 atlas → low), so the
    method and that skill cannot disagree about the same hit. The skill computes this locally and
    VERDICT-INERTLY; promoting it here is what lets a rule read it, since the rule grammar admits only
    one (card_id, field) predicate and therefore cannot conjoin severity with compartment itself.

    `ungraded` is NOT a low rung. It means the fields needed to grade are ABSENT (an older product with
    no n_datasets_reliable / expressing_donor_fraction column), and it must stay veto-eligible: grading
    a missing replication column as `low_confidence` would let thinner data RELAX the killer, which is
    the fail-open direction. Confirmed absent by a LIVE run over all 504 corpus pairs (0 occurrences of
    `accessible_ungraded`) — inert by corpus, but INERT BY CORPUS IS NOT SAFE BY CONTRACT, and the
    contract has to hold anyway.

    REPLICATION-DOMINANT PATH. The high rung above is a pure conjunction, so REPLICATION cannot
    compensate for a detection miss however overwhelming it is: MSLN-PAAD's alveolar type 1 hit agrees
    across 26 independent atlases at donor fraction 0.881 and still graded `moderate_severity` at det
    0.413, relieving a dominant killer that a 2-atlas hit at det 0.51 fires. The second rung repairs
    that ONE asymmetry under a bounded relaxation of the detection line only — see
    REPLICATION_DOMINANT_DET_FLOOR for why each bound sits where it does, all measured live."""
    det = rec.get("median_detection_fraction")
    n_ds = rec.get("n_datasets_reliable")
    if not isinstance(det, (int, float)) or not isinstance(n_ds, int):
        return "ungraded"
    frac = rec.get("expressing_donor_fraction")
    if not isinstance(frac, (int, float)):
        return "ungraded"
    if det >= HIGH_LIABILITY_DET_THRESHOLD and frac >= HIGH_LIABILITY_DONOR_FRACTION and n_ds >= 2:
        return "high_severity"
    if (
        det >= REPLICATION_DOMINANT_DET_FLOOR
        and frac >= HIGH_LIABILITY_DONOR_FRACTION
        and n_ds >= REPLICATION_DOMINANT_N_DATASETS
    ):
        return "high_severity"
    if det < 0.30 or n_ds <= 1:
        return "low_confidence"
    return "moderate_severity"


def _essential_veto_grade(veto_pool: list[dict], essential_origin_only: bool) -> str:
    """Compose compartment x severity into the single categorical a rule can key on.

    `veto_pool` is the ABOVE-FLOOR OFF-ORIGIN essential hits — exactly the set that fired
    critical_organ_liability, so this grades the veto's own basis and cannot disagree with it.

    FAIL-CLOSED ON THE PARTITION, NOT THE ARGMAX. The compartment is decided over the WHOLE pool: if ANY
    above-floor off-origin hit sits in a systemically accessible organ, the grade is `accessible_*`, and
    severity is taken from the worst ACCESSIBLE hit — never from the global argmax. Grading on the argmax
    instead would be a LARGE fail-open, measured live against S3 over all 504 corpus pairs: **230 of the
    259 brain-argmax critical calls (88.8%)** ALSO carry an accessible-organ essential hit above 0.20, so
    an argmax rule would stamp `bbb_protected` on 230 real lung/liver/marrow liabilities and relieve a
    dominant safety killer on every one of them. AKT1 is the clean example — brain wins the argmax while
    cycling pulmonary AT2 sits at det 0.615. Only 29 of 468 (6.2%) are genuinely brain-only.
    Only when EVERY above-floor off-origin hit is BBB-protected does the grade become `bbb_protected`.

    ★ AND THE SAME APPLIES TO SEVERITY: GRADE EVERY ACCESSIBLE HIT, THEN TAKE THE WORST GRADE.
    This function used to pick the accessible hit by DETECTION ARGMAX and grade only that one — the
    very trap the paragraph above warns about, one layer down. It is not a near-equivalence, because
    `_essential_severity` is a CONJUNCTION over det x donor-fraction x atlas count, so detection is not
    a monotone proxy for the grade.
    Measured live over all 504 corpus-20260914 pairs: **110 of the 439 pairs with an accessible hit
    (25.1%) had their pool UNDER-GRADED by the argmax, and 59 of those were relieved of the dominant
    BiTE/TCE killer entirely.**
    The mechanism is sharper than "argmax != worst", and it is systematic rather than incidental:
    **the argmax hit was measured in exactly ONE atlas in 104 of those 110 pairs (94.5%), against
    8.2% in the pairs the argmax grades correctly.** A single-dataset detection fraction is unshrunk
    and noisy, so it WINS a maximum over detection — while `_essential_severity` sends `n_ds <= 1`
    straight to `low_confidence`. The selection criterion is ANTI-CORRELATED with the grading
    criterion: choosing by detection preferentially chooses the hit the grader is about to distrust.
    FOLR1-OV is the case that makes it concrete: a 1-atlas kidney hit at det 0.708 shadowed pulmonary
    alveolar type 2 at det 0.626 / donor 0.884 across **30 atlases** plus a kidney collecting duct
    principal cell at det 0.610 / donor 0.799 across 8, so a real, heavily replicated lung AND kidney
    liability graded `accessible_low_confidence` and fired nothing. EPCAM-COADREAD is the same shape
    (lung det 0.990 in 1 atlas shadowing liver det 0.693 / donor 0.943 in 10).
    Fixing THIS function alone moves the killer's base rate 223 -> 282 of 504 (44.2% -> 56.0%). Do not
    read 282 as the shipped rate: #660 also added the replication-dominant rung to `_essential_severity`
    (2 further pairs), so the rate actually shipped by #660 is **284 (56.3%)** and 282 is the isolated
    contribution of the worst-grade change. The direction of this change is
    strictly one-way: over all 504 pairs, **0 pairs grade LOWER** than before, and none crosses out of
    `bbb_protected` / `not_applicable` / `origin_tissue`, so the compartment partition and the
    class x grade strict-refinement invariant are untouched.

    Ranking, when a pool mixes grades: rank by VETO CONSEQUENCE FIRST, then by measurement strength.
    `ungraded` therefore outranks `moderate_severity` (it is killer-eligible and moderate is not, so
    ranking it lower would let a missing column RELAX the killer — the fail-open direction), while
    `high_severity` outranks `ungraded` (both are killer-eligible, so the veto consequence is
    identical and the MEASURED statement is the more informative label to carry downstream)."""
    if not veto_pool:
        return "origin_tissue" if essential_origin_only else "not_applicable"
    accessible = [e for e in veto_pool if _essential_compartment(e.get("tissue")) == "systemically_accessible"]
    if not accessible:
        return "bbb_protected"
    worst = max((_essential_severity(e) for e in accessible), key=_ESSENTIAL_SEVERITY_RANK.__getitem__)
    return f"accessible_{worst}"


def classify_sc_normal_expression(rows: pd.DataFrame, origin_tissues=None) -> dict:
    """Classify normal-tissue liability from a Tier-1 gene rows DataFrame.

    `rows` is a DataFrame with columns: cell_type, n_donors_reliable,
    median_detection_fraction (or median_det), expressing_donor_fraction.
    Returned keys match the card's summary_fields.
    """
    if rows is None or rows.empty:
        return _data_unavailable_class()

    # Normalize column name (Tier-1 schema uses median_det, keep compat)
    det_col = "median_det" if "median_det" in rows.columns else "median_detection_fraction"
    frac_col = "expressing_donor_fraction"

    # Only trust rows with enough donors
    reliable = rows[rows["n_donors_reliable"] >= MIN_RELIABLE_DONORS].copy()
    if reliable.empty:
        return _data_unavailable_class(
            note="All cell types have n_donors_reliable < MIN_RELIABLE_DONORS — insufficient donor coverage"
        )

    # --- Safety-essential cell types ---
    # Floor at 0.05: the Tier-1 WHERE median_det > 0.01 filter lets near-zero values through;
    # below 0.05 is within census annotation noise (cell-type contaminants, misassignments).
    SAFETY_FLAG_FLOOR = 0.05
    # OFF-ORIGIN critical-organ floor (0.20, backtest-gated 2026-09-04): a hit in a NON-origin critical
    # organ only flips the verdict to critical_organ_liability if its detection clears this higher bar.
    # 0.05–0.20 in an off-origin organ is the scRNA ambient-contamination / marginal-annotation band — a
    # single-atlas det=0.156 "L4/5 cortical neuron" hit for a GI cadherin (CDH17) is not a real CNS
    # liability, yet under the 0.05 floor it flipped CDH17/COADREAD to critical via off-origin-dominates.
    # Aligns with MODERATE_LIABILITY_DET (0.20). Backtest: separates the CDH17 false positive (0.156) from
    # every true positive — DLL3 0.815 / FOLR1 0.708 / ERBB2 0.607 / MSLN 0.413. Origin-tissue essential
    # hits keep the 0.05 floor (they are window-arbitrated, not a hard veto). Sub-floor off-origin hits are
    # still recorded in safety_essential_flags for transparency; they simply do not flip the class.
    CRITICAL_ORGAN_OFF_ORIGIN_DET_FLOOR = 0.20
    safety_flags: dict[str, float] = {}
    # ORGAN-AWARE split (axis-D best-practice, 2026-08-07): a safety-essential-cell hit in a
    # NON-tissue-of-origin CRITICAL organ (heart/liver/kidney/marrow) is the hard-veto disqualifier
    # (the HER2-CAR-lung / MAGE-A3-cardiac / CEA-colitis failure class); a hit ONLY in the tumor's
    # OWN tissue-of-origin (e.g. FOLR1 in lung pneumocytes for NSCLC) is on-tissue and arbitrated by
    # the therapeutic-window axis, NOT vetoed. Requires the per-row `tissue` column + the caller's
    # origin_tissues; if tissue info is absent (older callers), we degrade to the un-split behavior.
    has_tissue = "tissue" in reliable.columns
    has_datasets = "n_datasets_reliable" in reliable.columns
    _e_abund_col = "median_abund" if "median_abund" in reliable.columns else None
    _e_frac = frac_col in reliable.columns
    # NORMALIZED on both sides — `origin_tissues` are UNDERSCORED shard keys, the `tissue` column is
    # SPACED Census values. See _norm_tissue for the defect this closes (PRAD/BLCA read their own organ
    # as an off-origin critical liability).
    origin = {_norm_tissue(t) for t in (origin_tissues or []) if str(t).strip()}
    essential_off_origin = False  # a hit in a critical organ that is NOT the tumor's tissue-of-origin
    essential_origin_only = False  # essential hits, but ALL in the tissue-of-origin
    # Per-essential-cell records so the veto's NAMED driver (organ/cell/detection/atlas-count) can be
    # surfaced downstream — the pooled max_detection_cell_type below is the argmax over ALL cell types
    # and can name a NON-essential epithelial cell while the veto actually fired on an essential one
    # (the anonymous-verdict gap: the skill/headline never named the organ that drove the clamp).
    essential_records: list[dict] = []
    for _, row in reliable.iterrows():
        det_val = float(row[det_col])
        if _is_safety_essential(str(row["cell_type"])) and det_val > SAFETY_FLAG_FLOOR:
            safety_flags[str(row["cell_type"])] = det_val
            row_tissue = _norm_tissue(row["tissue"]) if has_tissue else None
            is_origin = bool(row_tissue is not None and origin and row_tissue in origin)
            if is_origin:
                essential_origin_only = True
            elif det_val > CRITICAL_ORGAN_OFF_ORIGIN_DET_FLOOR:
                # non-origin critical organ (or tissue unknown → treat as off-origin, conservative),
                # ABOVE the ambient-contamination floor → the hard-veto class.
                essential_off_origin = True
            # else: off-origin but sub-floor (0.05–0.20) → recorded in flags/records for transparency,
            # does NOT flip to critical_organ_liability (marginal single-atlas / ambient-noise band).
            essential_records.append(
                {
                    "cell_type": str(row["cell_type"]),
                    "tissue": str(row["tissue"]) if has_tissue else None,
                    "median_detection_fraction": det_val,
                    "expressing_donor_fraction": float(row[frac_col]) if _e_frac else None,
                    "n_datasets_reliable": int(row["n_datasets_reliable"]) if has_datasets else None,
                    "median_abund": float(row[_e_abund_col])
                    if _e_abund_col is not None and pd.notna(row[_e_abund_col])
                    else None,
                    "is_off_origin": not is_origin,
                }
            )

    # --- Liability classification ---
    # HIGH: any cell type exceeds both magnitude AND consistency thresholds (AND gate)
    high_mask = (reliable[det_col] > HIGH_LIABILITY_DET_THRESHOLD) & (
        reliable[frac_col] > HIGH_LIABILITY_DONOR_FRACTION
    )
    if high_mask.any():
        liability = "HIGH_LIABILITY"
        # Report the triggering cell type (highest det among AND-gate passers), not the
        # global argmax: a cell at det=0.85/frac=0.40 (MODERATE only) must not shadow a
        # cell at det=0.55/frac=0.80 that actually fired the HIGH rule.
        anchor_rows = reliable[high_mask]
        anchor_row = anchor_rows.loc[anchor_rows[det_col].idxmax()]
    elif (reliable[det_col] > MODERATE_LIABILITY_DET).any() or (reliable[frac_col] > MODERATE_DONOR_FRACTION).any():
        liability = "MODERATE_LIABILITY"
        anchor_row = reliable.loc[reliable[det_col].idxmax()]
    elif (reliable[det_col] > NOT_EXPRESSED_CEILING).any():
        liability = "LOW_LIABILITY"
        anchor_row = reliable.loc[reliable[det_col].idxmax()]
    else:
        liability = "NOT_EXPRESSED"
        anchor_row = reliable.loc[reliable[det_col].idxmax()]

    max_det_ct = str(anchor_row["cell_type"])
    max_det_val = float(anchor_row[det_col])
    max_frac_val = float(anchor_row[frac_col]) if frac_col in reliable.columns else None

    # #984 Tier-2: ABUNDANCE at the liability-anchor cell type — how MUCH the target is expressed in the
    # normal cell that drives the liability, not just whether it is detected. Tissue-robust fixed bands.
    _abund_col = "median_abund" if "median_abund" in reliable.columns else None
    peak_abund = float(anchor_row[_abund_col]) if _abund_col is not None and pd.notna(anchor_row[_abund_col]) else None
    if peak_abund is None:
        abundance_class = "data_unavailable"
    elif peak_abund >= NORMAL_ABUND_HIGH:
        abundance_class = "high_abundance"
    elif peak_abund >= NORMAL_ABUND_MODERATE:
        abundance_class = "moderate_abundance"
    else:
        abundance_class = "low_abundance"

    n_above_20 = int((reliable[det_col] > 0.20).sum())

    # NAMED essential-cell driver: the worst essential cell the veto actually keyed on. When an
    # off-origin critical-organ hit fired (→ critical_organ_liability), name the argmax-detection cell
    # AMONG the ABOVE-FLOOR off-origin essential hits (the veto driver, not a sub-floor ambient hit); when
    # only origin-tissue essential hits fired, name the origin cell; when NO liability class fired (only
    # sub-floor off-origin hits), name nothing. This lets the verdict/headline name an organ and cell type
    # instead of an anonymous flag — and never names a sub-floor hit that did not move the class.
    # (This comment used to illustrate the output as "kidney proximal tubule, 3 atlases". No shard
    # contains that label — Census writes "epithelial cell of proximal tubule" — and until this PR no
    # entry matched any proximal-tubule label at all, so the example was doubly unreachable.)
    if essential_off_origin:
        _driver_pool = [
            e
            for e in essential_records
            if e["is_off_origin"] and e["median_detection_fraction"] > CRITICAL_ORGAN_OFF_ORIGIN_DET_FLOOR
        ]
    elif essential_origin_only:
        # ON-ORIGIN records ONLY. This branch used to pool ALL essential_records, so an argmax over the
        # sub-floor OFF-ORIGIN hits (the 0.05–0.20 ambient band that deliberately did NOT flip the class)
        # could out-rank the origin hit that DID fire it — naming a cell in the wrong organ for an
        # origin_tissue_liability. Measured live: CD274/LUAD reported "brain L5 extratelencephalic
        # projecting glutamatergic cortical neuron (det 0.140)" as the driver of a LUNG-origin liability,
        # and UPK1B/BLCA named the same brain neuron (0.167) for bladder urothelium. Contradicted this
        # block's own comment ("name the origin cell") and the whole point of the named-driver field.
        _driver_pool = [e for e in essential_records if not e["is_off_origin"]]
    else:
        _driver_pool = []
    # ⚠️ KNOWN DEFECT, MEASURED 2026-09-18, deliberately NOT fixed here. This is a DETECTION ARGMAX —
    # the same selection rule #660 removed from `_essential_veto_grade` one layer down, still live in the
    # field that tells a human WHICH organ is implicated. A single-atlas detection fraction is unshrunk
    # and therefore high, so it wins a max over detection; measured on trunk over 468 pairs with an
    # off-origin driver: 65 (13.9%) name a SINGLE-ATLAS cell type, and in 411 (87.8%) the pool contains a
    # hit that is both better replicated AND at least as severe.
    #
    # Why the obvious fix is REFUTED and must not be applied casually: ranking by replication instead
    # names `oligodendrocyte` (n_datasets_reliable = 177) for most brain-containing pools. Brain
    # parenchyma is exactly what `bbb_protected` exists to DISCOUNT for a systemically dosed modality, so
    # a replication-ranked driver would confidently name the one compartment the grade deliberately
    # distrusts. Selection needs all three axes (compartment, severity, replication) and a decision about
    # their order — a design question, not a one-line change, and out of scope for a vocabulary PR.
    #
    # What THIS PR does to it, measured: 25 of 504 pairs are re-attributed (3 to a better-replicated
    # driver, 21 to a worse one, 1 unchanged), and single-atlas drivers rise 65 -> 74. That is a real cost
    # and it is accepted knowingly: the same change closes a detection fail-open worth 8 killer-eligible
    # pairs and un-protects 4 falsely brain-only pairs, and it moves ZERO verdict classes. The generic
    # Cell Ontology parents this PR adds ("nephron tubule epithelial cell") are precisely the
    # few-atlas/high-detection shape that wins an argmax, so the two defects interact — which is the
    # argument for fixing the selector next, not for narrowing the vocabulary back.
    essential_driver = max(_driver_pool, key=lambda e: e["median_detection_fraction"]) if _driver_pool else None

    # The veto's OWN basis: the above-floor OFF-ORIGIN essential hits, i.e. exactly the set whose
    # non-emptiness IS `essential_off_origin`. Recomputed unconditionally (rather than reusing
    # _driver_pool) because _driver_pool switches to ORIGIN records on the origin-only branch, and
    # grading the critical-organ veto off origin hits would describe a different question.
    _veto_pool = [
        e
        for e in essential_records
        if e["is_off_origin"] and e["median_detection_fraction"] > CRITICAL_ORGAN_OFF_ORIGIN_DET_FLOOR
    ]
    veto_grade = _essential_veto_grade(_veto_pool, essential_origin_only)

    # Normal cell-type DETECTION CEILING across ALL reliable cell types — the honest denominator for a
    # single-cell tumor-vs-normal WINDOW (the positive use of the atlas, not only the safety veto). This
    # is the true global max, distinct from max_detection_fraction (the liability-anchor cell, which for
    # HIGH is the AND-gate argmax, not necessarily the global max).
    ceiling_det = float(reliable[det_col].max())

    # Ranked per-cell-type footprint (top by detection) — the normal analogue of the tumor card's
    # per_compartment vector. Surfaces the full liability landscape (not just the argmax cell type)
    # for the summary and the normal-tissue liability figure. Safety-essential cell types are flagged.
    _has_tissue = "tissue" in reliable.columns
    _has_frac = frac_col in reliable.columns
    _pct_abund_col = "median_abund" if "median_abund" in reliable.columns else None
    _has_datasets = "n_datasets_reliable" in reliable.columns
    per_cell_type_top = []
    for _, r in reliable.sort_values(det_col, ascending=False).head(15).iterrows():
        per_cell_type_top.append(
            {
                "cell_type": str(r["cell_type"]),
                "tissue": str(r["tissue"]) if _has_tissue else None,
                "median_detection_fraction": float(r[det_col]),
                "expressing_donor_fraction": float(r[frac_col]) if _has_frac else None,
                "n_donors_reliable": int(r["n_donors_reliable"]),
                # median_abund (magnitude, not just detection breadth) + n_datasets_reliable (independent-atlas
                # replication) were read from Tier-1 but dropped from the footprint — surface them so a
                # confidence/abundance gate and the narrator can weight each cell type, not just the argmax.
                "median_abund": float(r[_pct_abund_col])
                if _pct_abund_col is not None and pd.notna(r[_pct_abund_col])
                else None,
                "n_datasets_reliable": int(r["n_datasets_reliable"]) if _has_datasets else None,
                "is_safety_essential": _is_safety_essential(str(r["cell_type"])),
            }
        )

    return {
        "sc_normal_expression_class": liability,
        # CATEGORICAL companion to the safety_essential_flags dict, so the categorical rule engine can
        # fire on it (the raw dict is not rule-addressable). ORGAN-AWARE three-tier (2026-08-07):
        #   critical_organ_liability — essential-cell expression in a NON-origin critical organ
        #       (heart/liver/kidney/marrow). The axis-D HARD-veto instrument (TNNT2→cardiomyocyte).
        #   origin_tissue_liability  — essential-cell expression ONLY in the tumor's tissue-of-origin
        #       (FOLR1→lung pneumocytes for NSCLC). On-tissue; arbitrated by the therapeutic-window
        #       axis, NOT a hard veto — a validated ADC target must survive this.
        #   none                     — no safety-essential expression above floor.
        # This is DISTINCT from sc_normal_expression_class (HIGH_LIABILITY fires on ANY high normal
        # cell type incl. tissue-of-origin epithelium — too blunt to veto a validated ADC target).
        # off_origin dominates: any critical-organ hit → critical_organ_liability even if origin also hit.
        "sc_normal_safety_essential_class": (
            "critical_organ_liability"
            if essential_off_origin
            else "origin_tissue_liability"
            if essential_origin_only
            else "none"
        ),
        "max_detection_cell_type": max_det_ct,
        "max_detection_fraction": max_det_val,
        "expressing_donor_fraction_max": max_frac_val,
        # #984 Tier-2: normal-tissue abundance at the liability-anchor cell type (verdict-inert)
        "sc_normal_abundance_class": abundance_class,
        "sc_normal_peak_median_abund": peak_abund,
        # NAMED essential-cell driver of the safety-essential class — de-anonymizes the veto (organ +
        # cell type + detection + independent-atlas count + abundance). None when no essential hit fired.
        "sc_normal_essential_max_cell_type": essential_driver["cell_type"] if essential_driver else None,
        "sc_normal_essential_max_tissue": essential_driver["tissue"] if essential_driver else None,
        "sc_normal_essential_max_detection_fraction": essential_driver["median_detection_fraction"]
        if essential_driver
        else None,
        "sc_normal_essential_donor_fraction": essential_driver["expressing_donor_fraction"]
        if essential_driver
        else None,
        "sc_normal_essential_n_datasets_reliable": essential_driver["n_datasets_reliable"]
        if essential_driver
        else None,
        "sc_normal_essential_median_abund": essential_driver["median_abund"] if essential_driver else None,
        # GRADED veto instrument: compartment x severity over the SAME above-floor off-origin pool that
        # sets sc_normal_safety_essential_class, collapsed into one rule-addressable categorical because
        # the interpretation-rule grammar admits exactly one (card_id, field) predicate per rule and so
        # cannot conjoin the two dimensions itself. Purpose: give the `dominant: true` BiTE/TCE killer a
        # discriminating rung instead of a 92.9%-base-rate boolean. See BBB_PROTECTED_TISSUES for the
        # measurement, _essential_veto_grade for the fail-closed partition.
        #   accessible_high_severity / accessible_ungraded  → veto-eligible (ungraded = fields ABSENT,
        #       which must not relieve the veto: missing replication data is not a safety argument)
        #   accessible_moderate_severity / accessible_low_confidence → real but not maximal
        #   bbb_protected  → EVERY above-floor off-origin hit is brain parenchyma; still a liability for
        #       BBB-crossing modalities (small molecule / degrader), weak for a systemically dosed TCE
        #   origin_tissue  → origin-only essential hits (window-arbitrated, unchanged)
        #   not_applicable → no essential hit above floor
        "sc_normal_essential_veto_grade": veto_grade,
        # Normal cell-type detection ceiling across all reliable cell types (single-cell window denominator).
        "sc_normal_ceiling_detection_fraction": ceiling_det,
        "safety_essential_flags": safety_flags,
        "n_cell_types_above_20pct": n_above_20,
        "n_reliable_cell_types": int(len(reliable)),
        "per_cell_type_top": per_cell_type_top,
    }


def _data_unavailable_class(note: str = "") -> dict:
    return {
        "sc_normal_expression_class": "data_unavailable",
        "sc_normal_safety_essential_class": "data_unavailable",
        "max_detection_cell_type": None,
        "max_detection_fraction": None,
        "expressing_donor_fraction_max": None,
        "sc_normal_abundance_class": "data_unavailable",
        "sc_normal_peak_median_abund": None,
        "sc_normal_essential_max_cell_type": None,
        "sc_normal_essential_max_tissue": None,
        "sc_normal_essential_max_detection_fraction": None,
        "sc_normal_essential_donor_fraction": None,
        "sc_normal_essential_n_datasets_reliable": None,
        "sc_normal_essential_median_abund": None,
        # `data_unavailable`, NOT `not_applicable`: no product / no reliable donors is a coverage gap,
        # and a gap must not be spelled the same way as a measured absence of liability.
        "sc_normal_essential_veto_grade": "data_unavailable",
        "sc_normal_ceiling_detection_fraction": None,
        "safety_essential_flags": {},
        "n_cell_types_above_20pct": 0,
        "n_reliable_cell_types": 0,
        "per_cell_type_top": [],
        "_data_note": note or "No Tier-1 normal-tissue product available or insufficient donor coverage",
    }
