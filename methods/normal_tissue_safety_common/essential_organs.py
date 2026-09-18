"""Single source of truth for the SAFETY-ESSENTIAL normal-organ set shared by the FOUR normal-tissue
substrates crosswalked below (GTEx bulk RNA, HPA protein IF, sc-normal Census, TPHP DIA-MS).

SEVEN downstream sites, in TWO kinds — the distinction matters, because only the first kind
follows a change here automatically:
  IMPORT it (4, these track this file for free):
    `tcga_gtex_expression_distribution.stats`, `hpa_normal_tissue_liability.cli`,
    `sc_normal_expression.read`, `tphp_normal_protein.read`
  HARDCODE their own copy (3, these must be edited BY HAND and are CI-guarded, never trusted):
    `tcga_gtex_tpm_quantiles.window.ESSENTIAL_GTEX_TISSUES`,
    `exon_window.classify.ESSENTIAL_GTEX_TISSUES`,
    `pair_selectivity_gate.gates.ESSENTIAL_GTEX_TISSUES`
  ⇒ `tests/methods/normal_tissue_safety_common/test_essential_organ_coverage.py` pins all three
  copies against `GTEX_ESSENTIAL_TISSUES`, which is the only reason a promotion here cannot
  silently leave them behind.

(Header said "three cards" until 2026-09-18; measured, it was two short. My first correction then
said "five consuming modules" and named `tcga_gtex_tpm_quantiles.window` among them, which is ALSO
wrong in the same direction: window.py holds a HARDCODED copy and imports nothing from here. A
grep for this module's name conflates three different relationships — import, hardcoded copy, and
bare comment mention — so count the IMPORT STATEMENTS, not the mentions.)

Motivation: the three normal-tissue cards that existed then each maintained their
OWN essential/critical-organ list, and they DIVERGED. `tcga_gtex_expression_distribution.stats.
CRITICAL_NORMAL_TISSUES` (the safety-comparator card) OMITTED THYROID / ADRENAL_GLAND / PITUITARY /
BLOOD_VESSEL — and carried a dead `ARTERY` entry that never matches the recount3/GTEx vocabulary
(GTEx groups the arteries under `BLOOD_VESSEL`). So a thyroid-/adrenal-/vascular-restricted target
(e.g. TSHR, ~159 TPM in thyroid) read `restricted_normal` — a FAVORABLE signal — and its TCE
liability reached the composed surface-modality verdict as `both_viable`. Meanwhile the GTEx
*window* card (`tcga_gtex_tpm_quantiles.window.ESSENTIAL_GTEX_TISSUES`) already used the correct
set — 15 tissues at the time, 17 today (+COLON, +SMALL_INTESTINE with the 2026-09-18 gut promotion).
BOTH counts already include SPLEEN, which that card carries as the one legitimate extra over the
canonical set, so the running arithmetic is canonical + 1: 14 + 1 = 15 then, 16 + 1 = 17 now.
So the framework held two divergent GTEx essential sets at once.

Fix: declare the canonical vital-organ set ONCE and crosswalk it to each card's native tissue
vocabulary. `None` in a crosswalk USUALLY means the organ is NOT representable in that source's
vocabulary (e.g. HPA's 16-name grouped-intensity field has no thyroid / adrenal / pituitary group — a
DATA SUBSTRATE gap, not a list omission; closing it requires a new normal-tissue proteomics source) —
but NOT in SC_NORMAL_CROSSWALK, where it is a policy claim. See convention 3 below before reading any
`None` as a substrate gap.

THREE CONVENTIONS THAT LOOK LIKE DETAILS AND ARE NOT:

  * SCALAR ANCHOR. A crosswalk value is ONE source-native name, even where the source splits the
    organ into several real parts (muscle -> `skeletal muscle` not smooth muscle; vasculature ->
    `artery` not vein/lymph vessel; gut -> the colonic part, not stomach/esophagus/appendix).
    The anchor is the canonical DOSE-LIMITING representative. Non-anchors are named in the comment
    beside each entry so that "not listed" is never ambiguous between "absent from the source" and
    "present but deliberately not the anchor". Do NOT make a value a tuple/list to cover several
    parts: every derived set below is built with `frozenset(v for v in CROSSWALK.values() if v)`, so
    a container value would be placed INTO the frozenset and every downstream `.isin(...)` /
    `in` test would silently stop matching — a fail-open with no error.
      THE ESCAPE HATCH, when one anchor genuinely cannot cover the organ: promote a SECOND CANONICAL
    ORGAN (as `small_intestine` was on 2026-09-18), which keeps every value scalar and forces the
    second organ to be justified PER SOURCE. Use it only when a source's own reduction makes the first
    anchor insensitive — e.g. a source that reduces on a MEDIAN over a POOLED group, where no choice of
    single name recovers the signal. Do NOT use it to enumerate an organ's parts.

  * `None` IS A MEASURED CLAIM about a source's vocabulary, so it must be measured against that
    source's real labels, with the full aperture. Reading a per-gene slice and concluding "the panel
    has no X" measures the gene's detection, not the panel (see the TPHP note below). An unmeasured
    `None` is the same defect class as an inert cell-type prefix: it reads as a documented substrate
    gap while actually being an unexamined organ.

  * `None` DOES NOT MEAN THE SAME THING IN ALL FOUR CROSSWALKS, and reading it uniformly will produce
    a false defect report or hide a real one. GTEX / HPA / TPHP `None` is a VOCABULARY claim: the
    source has no label for the organ. SC_NORMAL `None` is a POLICY claim — its own header says "None
    where the organ has no dedicated ALWAYS-ON single-cell normal shard" — and a Census shard may
    exist for an organ that is `None` here, because the always-on panel is a per-run COST decision
    (every member is queried on EVERY run, indication-independent). `small_intestine` is exactly this
    case and carries its measurement inline. Consequence: an audit that flags a SC_NORMAL `None` by
    checking `TISSUE_TO_PRODUCT` is asking the wrong question; ask instead whether the organ is
    reachable as an ORIGIN tissue, and whether holding it origin-only was measured.

SPLEEN is intentionally EXCLUDED from the canonical set: immunologically important but not a
classic dose-limiting vital organ, and its inclusion is a judgment call reserved for review.
The CI guard asserts COVERAGE (each source covers the canonical organs
its vocab supports), NOT equality — so a source that ADDITIONALLY lists SPLEEN (the GTEx window
card does) is fine, and promoting spleen to canonical later is a one-line change here.
"""

from __future__ import annotations

# Canonical vital / dose-limiting organs: on-target expression here is a therapeutic-window red
# flag regardless of tumor abundance. Semantic tokens (source-vocab-independent).
CANONICAL_VITAL_ORGANS = frozenset(
    {
        "heart",
        "brain",
        "liver",
        "lung",
        "kidney",
        "nerve",
        "muscle",
        "blood",
        "bone_marrow",
        "pancreas",
        "adrenal_gland",
        "pituitary",
        "thyroid",
        "vasculature",
        # GUT / intestinal epithelium — PROMOTED 2026-09-18. GI toxicity (diarrhoea, mucositis,
        # colitis) is the classic dose-limiting event for GI-directed TCEs and for antimitotic ADC
        # payloads, so on-target expression in intestinal epithelium is a therapeutic-window red flag
        # on exactly the footing as the other members of this set. It was absent, and its absence was
        # a MEASURED fail-open, not a judgment call: with no `gut` key, CDH17-ESCA (an intestinal
        # antigen in a non-intestinal indication) graded `not_applicable` — the veto never looked.
        # See each crosswalk below for the per-source anchor and its measured non-anchors.
        "gut",
        # SMALL INTESTINE — PROMOTED 2026-09-18, as a SECOND gut organ rather than a `gut` non-anchor.
        # It is NOT a redundant duplicate of `gut`, and the reason is a SUBSTRATE property of GTEx that
        # no amount of anchor-choosing inside a single key can fix:
        #   GTEx's `COLON` group POOLS two subtissues (arm size n=822 ~= Colon-Sigmoid 373 +
        #   Colon-Transverse 406). Sigmoid is muscularis, Transverse is mucosa. The window arm reduces
        #   on the MEDIAN, and for a MUCOSAL antigen the median lands in the trough BETWEEN the two
        #   modes: COLON IQR span is 3.44 log2 for the gut-epithelial gene subset vs 0.76 panel-wide
        #   (4.5x wider; CDH17 6.46, CEACAM5 7.51, EPCAM 7.34 -- a 90-180x LINEAR span).
        #   `SMALL_INTESTINE` (terminal ileum, n=193) is a SINGLE mucosa-only subtissue with no trough.
        # Measured SMALL_INTESTINE/COLON median fold: DPEP1 816x, MUC17 451x, CDH17 28.6x, GUCY2C 26.8x,
        # EPCAM 25.8x. Consequence on the 504-pair corpus, live: `gut`->COLON alone moves the GTEx
        # window arm's `window_class` for ZERO pairs, while SMALL_INTESTINE moves 2 and
        # `therapeutic_window_class` 3 -- GUCY2C-COADREAD and MUC17-STAD `clean_window` ->
        # `essential_tissue_liability`, CDH17-COADREAD `clean_window` -> `narrow_window`. GUCY2C is an
        # active GI TCE/ADC antigen with documented GI toxicity; the colonic anchor does NOT close that
        # fail-open and this one does.
        # ⚠️ NOT uniformly promoted across the four sources, and that is measured, not lazy -- the
        # pooled-median mechanism is GTEx-specific and has no analogue in a source that resolves cell
        # types directly. See each crosswalk below; the sc-normal entry carries the 2/262 measurement.
        "small_intestine",
        # "spleen": HELD — see module docstring (pending review).
    }
)

# The endocrine / vascular / CNS organs whose ABSENCE from a source's essential set WAS the S1-3
# safety false-negative. The CI guard REQUIRES every source that can represent one of these to
# include it (the load-bearing safety invariant this module exists to enforce).
S1_3_REQUIRED_ORGANS = frozenset({"adrenal_gland", "pituitary", "thyroid", "vasculature", "brain"})

# --- Per-source crosswalks: canonical organ -> that source's native tissue name (None if the
#     organ is not representable in the source's vocabulary). ---

# recount3 / GTEx `tissue` column (UPPERCASE). All 16 canonical organs exist in the GTEx vocab — it is
# the only one of the four sources with no substrate gap, which is why it carries both gut organs.
# vasculature -> BLOOD_VESSEL (GTEx groups Artery-Aorta/Coronary/Tibial here; the old bare `ARTERY`
# was never a GTEx tissue label and silently never matched).
GTEX_CROSSWALK = {
    "heart": "HEART",
    "brain": "BRAIN",
    "liver": "LIVER",
    "lung": "LUNG",
    "kidney": "KIDNEY",
    "nerve": "NERVE",
    "muscle": "MUSCLE",
    "blood": "BLOOD",
    "bone_marrow": "BONE_MARROW",
    "pancreas": "PANCREAS",
    "adrenal_gland": "ADRENAL_GLAND",
    "pituitary": "PITUITARY",
    "thyroid": "THYROID",
    "vasculature": "BLOOD_VESSEL",
    # gut -> COLON. MEASURED (all 31 gtex_normal `group` labels, gene-invariant — CDH17 and MSLN
    # return byte-identical sets): the GI compartment is split across COLON / SMALL_INTESTINE /
    # STOMACH / ESOPHAGUS. COLON is the anchor (largest surface, the colitis/diarrhoea organ); the
    # other three are real GI tissues that are deliberately NOT anchors, exactly as `smooth muscle` /
    # `vein` are not the anchors for muscle / vasculature in TPHP_CROSSWALK below.
    "gut": "COLON",
    # small_intestine -> SMALL_INTESTINE. MEASURED (n=193, one GTEx subtissue: Terminal Ileum, mucosa
    # only). THIS is the sensitive intestinal-EPITHELIUM detector in GTEx, and COLON is not, because
    # COLON pools mucosa with muscularis and the arm reduces on the median — see the long note on
    # `small_intestine` in CANONICAL_VITAL_ORGANS for the measurement and the three pairs it moves.
    # Both organs are carried on purpose: COLON still raises the essential max for 12 of the 262
    # corpus genes, so this is ADDITIVE coverage, not a replacement anchor.
    "small_intestine": "SMALL_INTESTINE",
}

# HPA closed 16-name grouped-intensity vocabulary. None = no group for that organ (substrate gap).
HPA_CROSSWALK = {
    "heart": "heart muscle",
    "brain": "cerebral cortex",
    "liver": "liver",
    "lung": "lung",
    "kidney": "kidney",
    "pancreas": "pancreas",
    "bone_marrow": "bone marrow",
    "vasculature": "blood vessel",
    # gut -> "intestine". MEASURED against the real intensity column: HPA's closed vocabulary is
    # EXACTLY 16 names and contains precisely two GI names, `intestine` and `stomach`. `intestine` is
    # the anchor; `stomach` is a real non-anchor GI tissue.
    #
    # ⚠️ THIS CHANGES HPA'S SAFETY SEMANTICS DELIBERATELY (authorised in the 2026-09-18 scope round).
    # `intestine` was previously held OUT of the essential set and carried only by the separate,
    # modality-dependent `gi_tract` flag (cli.py GI_TISSUES) on the reasoning that a non-cleavable ADC
    # may tolerate GI epithelium where a BiTE will not. It now ALSO enters ESSENTIAL_TISSUES, so an
    # intestine-enriched antigen fires the strict-modality (BiTE/TCE/cell) killer. `gi_tract` is kept
    # rather than narrowed: it still carries WHICH organ class is implicated, information the boolean
    # essential flag does not — LABEL, do not DROP. The overlap is intentional; see the note on
    # GI_TISSUES in hpa_normal_tissue_liability/cli.py.
    "gut": "intestine",
    # Not in HPA's 16-name grouped-intensity field (data-substrate gap, NOT a list omission):
    # small_intestine: HPA's closed vocabulary was re-measured from the real intensity column on
    # 2026-09-18 (exactly 16 names) and its ONLY GI names are `intestine` and `stomach`. `intestine` is
    # undivided — there is no small-vs-large split to anchor — and it is already the `gut` anchor above.
    # So this None is "the source cannot represent the organ SEPARATELY", measured with the full
    # aperture, and the organ is NOT thereby unguarded in HPA: `intestine` covers it.
    "small_intestine": None,
    "nerve": None,
    # ⚠️ KNOWN DEFECT, MEASURED 2026-09-18, deliberately NOT fixed here. This `None` is FALSE: the
    # closed vocabulary was re-measured from the real intensity column (exactly 16 names, confirming
    # the count) and it CONTAINS `skeletal muscle` — the same name TPHP_CROSSWALK below uses as its
    # muscle anchor. So HPA can represent muscle, and a skeletal-muscle-enriched antigen escapes
    # HPA's essential-tissue killer under a claim of substrate absence that is not true. It is the
    # `None`-as-unmeasured-claim failure mode named in the module docstring above.
    #   Not fixed in this change because it is an INDEPENDENT semantic change to the HPA arm, and
    #   folding it in would make this change's HPA backtest unattributable between two causes.
    #   It also needs a test edit, not just this line:
    #   test_essential_organ_coverage.py::test_tphp_fills_endocrine_vascular_and_flags_pituitary_gap
    #   ASSERTS `HPA_CROSSWALK.get("muscle") is None`, i.e. the suite currently pins the false claim.
    "muscle": None,
    "blood": None,
    "adrenal_gland": None,
    "pituitary": None,
    "thyroid": None,
}

# Single-cell normal-tissue ALWAYS-ON shard slug (must be a `TISSUE_TO_PRODUCT` key). None where the
# organ has no dedicated always-on single-cell normal shard. brain + adrenal_gland were promoted first
# (S1-3 CNS + endocrine holes); lung + pancreas promoted 2026-08-19 — a target expressed in normal
# pneumocytes (the ADC-pneumonitis organ) or pancreatic islet is a cross-indication safety liability
# previously visible only for NSCLC/PAAD (indication-matched). Safe to promote now that the sc-normal
# critical-organ arm produces a NAMED-organ liability FLAG (selective_with_normal_liability), not the
# blunt selective_but_broadly_normal kill (Phase S).
SC_NORMAL_CROSSWALK = {
    "heart": "heart",
    "liver": "liver",
    "kidney": "kidney",
    "bone_marrow": "bone_marrow",
    "brain": "brain",
    "adrenal_gland": "adrenal_gland",
    "lung": "lung",
    "pancreas": "pancreas",  # PROMOTED to always-on (pneumonitis / islet safety) 2026-08-19
    # gut -> "colon". PROMOTED to always-on 2026-09-18, taking the always-on panel from 8 shards to 9.
    # THE ANCHOR CHOICE IS MEASURED, not nominal: `TISSUE_TO_PRODUCT` carries THREE candidate GI
    # shards, and `colon` strictly dominates `large_intestine` on breadth — 156 distinct cell-type
    # labels vs 93, with only 6 of large_intestine's 93 absent from colon. `small_intestine` (179
    # labels), `stomach` and `esophagus` stay origin-only: they are real GI tissues that are
    # deliberately NOT anchors, so their coverage grades origin_tissue_liability and never drives a
    # cross-indication veto.
    #
    # ⚠️ PAIRED WITH A CELL-TYPE CHANGE, and neither half works alone. `SAFETY_ESSENTIAL_CELL_TYPE_
    # PREFIXES` previously matched only the DIFFERENTIATED absorptive lineage (enterocyte /
    # colonocyte), so promoting this shard on its own would have queried the gut while leaving its
    # crypt, transit-amplifying, Paneth and goblet compartments — the ones a payload actually
    # depletes — unflagged. See the GUT block in sc_normal_expression/stats.py.
    "gut": "colon",
    # small_intestine -> None, and this None is a POLICY claim, not a vocabulary claim. ⚠️ A
    # `small_intestine` shard DOES exist in TISSUE_TO_PRODUCT (179 cell-type labels, the broadest GI
    # shard) — so read under the module docstring's "not representable in the source's vocabulary" this
    # None would be FALSE, the same defect class as HPA's `muscle`. It is true under THIS crosswalk's
    # own declared semantics ("None where the organ has no dedicated ALWAYS-ON shard"), which is a
    # different predicate. The divergence is named as convention 3 in the module docstring.
    #
    # HELD ORIGIN-ONLY ON MEASURED EVIDENCE, not for convenience. Marginal value over the 9-shard
    # always-on panel with `colon` already in, computed live over all 262 corpus genes with the real
    # matcher and the real `_essential_severity`: small_intestine flags a safety-essential hit for
    # 257/262 genes ON ITS OWN, yet improves the panel's WORST severity for exactly TWO (MUC17
    # moderate->high via `colonocyte`, PRDM1 moderate->high via `endothelial cell of arteriole`). Both
    # were already `moderate_severity`, hence already critical_organ_liability, so the CLASS moves for
    # ZERO genes. `colon` already supplies the worst grade for 260/262 — the shards are near-redundant
    # at cell-type grain, exactly because the GTEx pooled-MEDIAN mechanism cannot arise here.
    # A 10th always-on shard is ~11% more Census reads on EVERY run of the skill; 2 genes of grade
    # movement does not buy that. Kept as an ORIGIN tissue, so GI indications (STAD/COADREAD/ESCA)
    # still query it — only the cross-indication veto declines to.
    "small_intestine": None,
    "nerve": None,
    "muscle": None,
    "blood": None,
    "pituitary": None,
    "thyroid": None,
    "vasculature": None,
}

# TPHP DIA-MS pan-tissue proteome `tissue` column (SDRF organism-part, lowercase). None = the organ
# has no organism-part in the 70-tissue adult TPHP panel. TPHP's value for SAFETY is that DIA-MS
# PROTEIN resolves the endocrine/vascular/CNS organs HPA-IHC's 16-name grouped field is BLIND to:
# it covers nerve / muscle / blood / adrenal_gland / thyroid (all None in HPA_CROSSWALK) and 4 of the
# 5 S1_3_REQUIRED_ORGANS (adrenal_gland, thyroid, vasculature, brain) — missing ONLY pituitary, which
# is absent from the TPHP panel (a data-substrate gap, like HPA's). Scalar convention (one
# representative organism-part per organ) matches GTEX/HPA/SC; muscle->skeletal muscle and
# vasculature->artery pick the canonical dose-limiting representative among TPHP's finer parts
# (smooth muscle / vein / lymph vessel also present but not the crosswalk anchor).
TPHP_CROSSWALK = {
    "heart": "heart",
    "brain": "brain",
    "liver": "liver",
    "lung": "lung",
    "kidney": "kidney",
    "nerve": "nerve",
    "muscle": "skeletal muscle",
    "blood": "blood",
    "bone_marrow": "bone marrow",
    "pancreas": "pancreas",
    "adrenal_gland": "adrenal gland",
    "thyroid": "thyroid gland",
    "vasculature": "artery",
    # gut -> "large intestine". MEASURED against the FULL 70-part adult panel (the `tissue` column
    # read with NO gene filter — reading it through one gene's pushdown would have measured only the
    # tissues that gene was DETECTED in, and an absence claim from a gene-filtered aperture is not an
    # absence claim): the panel has NO literal "colon". Its GI parts are `large intestine`,
    # `small intestine`, `stomach`, `esophagus` and `vermiform appendix`; `large intestine` is the
    # anchor (the colonic mucosa the GTEx/HPA/sc anchors also name), the other four are non-anchors.
    "gut": "large intestine",
    # small_intestine -> "small intestine". MEASURED on the FULL panel with NO gene filter (a 3-column
    # projection of tissue / tissue_class / n_samples): the adult_normal arm is 10 samples, above
    # MIN_SAMPLES_MEASURABLE = 3, so this organ is MEASURABLE and not an unmeasurable-count regression.
    # GI arm sizes for the record: stomach 16, large intestine 13, small intestine 10, esophagus 8,
    # vermiform appendix 2 (the appendix falls BELOW the floor and is not an anchor anyway).
    # Paired with the VITAL_ORGAN_N_SAMPLES entry in tphp_normal_protein/read.py — the cache and this
    # crosswalk must gain the organ TOGETHER or the arm falls to `cached_panel_arm_size` misses.
    "small_intestine": "small intestine",
    # Not in the 70-tissue adult TPHP panel (data-substrate gap, NOT a list omission):
    "pituitary": None,
}

# --- Derived per-source essential sets (what each card imports). ---
GTEX_ESSENTIAL_TISSUES = frozenset(v for v in GTEX_CROSSWALK.values() if v)
HPA_ESSENTIAL_TISSUES = frozenset(v for v in HPA_CROSSWALK.values() if v)
# order-stable list (sc-normal queries + de-dups against indication-matched tissues in insertion order)
SC_NORMAL_ESSENTIAL_TISSUES = [v for v in SC_NORMAL_CROSSWALK.values() if v]
TPHP_ESSENTIAL_TISSUES = frozenset(v for v in TPHP_CROSSWALK.values() if v)


def required_names(crosswalk: dict) -> set:
    """The source-native names a source MUST cover for the S1-3 safety invariant: every
    S1_3_REQUIRED_ORGANS organ that the source's vocabulary can represent (non-None crosswalk)."""
    return {crosswalk[o] for o in S1_3_REQUIRED_ORGANS if crosswalk.get(o)}
