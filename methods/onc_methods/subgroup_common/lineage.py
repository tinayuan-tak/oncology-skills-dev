"""Indication → DepMap lineage/organ/population scoping for the subgroup-assigner lane.

This is a LEAF module on purpose. The canonical indication→OncotreeLineage literal
lives in methods/depmap_chronos/cli.py::INDICATION_LINEAGE (re-exported as
depmap_chronos.read.INDICATION_TO_DEPMAP_LINEAGE), but `depmap_chronos` itself imports
`subgroup_common.iteration`, which imports `subgroup_common.scoping` — so aliasing the
canonical from `scoping` closes an import cycle. Keeping the alias here, in a module
nothing in the depmap_chronos chain imports, breaks it.

Why alias at all: the framework historically forked this map across ~6 modules, and
this lane held two more forks — an 8-entry scalar dict in
subgroup_assigner_directly_tagged (exempted from the single-source guard for its
INDICATION_TO_DEPMAP_ORGAN sibling) and a ONE-entry copy in
scripts/prefetch_source_maf.py ({"COADREAD": "Bowel"}) that made every non-COADREAD
DepMap prefetch exit 1 with "No DepMap lineage mapping", blocking the
ESCA/HNSC/NSCLC/PAAD depmap measurements outright. Aliasing the canonical gives this
lane all 42 codes plus the guards in
tests/methods/depmap_chronos/test_lineage_map_single_source.py (values validated
against DepMap 26Q1's 34-lineage Model.csv set, completeness validated against the
target-contracts crosswalk, no fabricated lineage for THYM which DepMap lacks).

NOTE the target-contracts crosswalk `depmap_lineage` lane is NOT safe to read
directly even though it is 34/35 filled: it spells HNSC `Head_and_Neck` while DepMap's
real OncotreeLineage is `Head and Neck`, which matches ZERO of 96 HNSC models —
silently. 33 of its 34 filled values are verbatim-correct.
"""

from __future__ import annotations

from dataclasses import dataclass

from onc_methods.depmap_chronos.read import INDICATION_TO_DEPMAP_LINEAGE

# For lineages DepMap collapses across organs, a second filter on OncotreeSubtype
# separates the indication. "Esophagus/Stomach" holds both gastric (Stomach*) and
# esophageal (Esophageal*) models; the substring is matched case-insensitively against
# OncotreeSubtype. Indications absent here use the lineage filter alone. This map has
# no canonical home elsewhere — it exists only for subgroup scoping.
#
# SUPERSEDED as a mechanism by INDICATION_TO_DEPMAP_ONCOTREE_CODES below, but RETAINED
# because subgroup_assigner_directly_tagged/cli.py still reads it and its contents are
# asserted by that method's own tests. The two are held in lockstep by
# test_code_sets_reproduce_the_production_organ_substrings — a substring and a code set
# that select different models is the `two files route the same axis` drift, so the
# equivalence is guarded rather than assumed.
INDICATION_TO_DEPMAP_ORGAN = {
    "STAD": "stomach",  # Stomach Adenocarcinoma, Tubular/Diffuse/Signet-Ring Stomach, ...
    "ESCA": "esophageal",  # Esophageal Adenocarcinoma, Esophageal Squamous Cell Carcinoma
}

# ---------------------------------------------------------------------------------
# POPULATION narrowing: OncotreeLineage is NOT the indication
# ---------------------------------------------------------------------------------
# An OncotreeLineage filter alone returns a population that merges DISTINCT catalogued
# diseases, because DepMap's lineage is one level coarser than the indication:
#
#   Lung              293 models = NSCLC (196) + SCLC (83)  + 10 null-code
#   Myeloid           109 models = AML   (79)  + CML (20)   + ALAL/MPAL (6) + 4 null-code
#   Esophagus/Stomach 189 models = ESCA  (98)  + STAD (91)
#
# Measured consequence 2026-09-14: of the 27 landed `maf_filter x depmap` expected_n
# cells, all 27 replay EXACTLY but three counted members of a DIFFERENT catalogued
# indication — NSCLC HER2_mut 16 (4 SCLC models), AML TP53_mut 26 (6 CMLBCRABL1 + 1
# ALAL), ESCA TP53_mut 51 (17 STAD + 1 DSTAD).
#
# ★ Why the defect stayed invisible: every INDICATION-SPECIFIC driver cell was clean by
# construction (EGFR/KRAS/BRAF for NSCLC; FLT3_ITD/NPM1/IDH for AML all 100% on-
# indication), because a driver specific enough to be diagnostic of an indication cannot
# be carried by the contaminant disease. Only PAN-CANCER strata (TP53, HER2) were wrong.
# Probe population purity with the marker carrying the LEAST indication information.
#
# ★ Why an OncotreeSubtype SUBSTRING cannot be the mechanism (measured, not assumed):
# no substring selects NSCLC while excluding SCLC — LUAD is spelled "Lung
# Adenocarcinoma" so `lung` also matches "Small Cell Lung Cancer", while `non-small
# cell` matches only 15 of the 196 non-small-cell models. Same for Myeloid: `acute
# myeloid` misses AMOL/AMKL/AMML/AMLMRC. Esophagus/Stomach is the ONE lineage the
# substrings happen to partition cleanly, which is why the organ map stopped there.
# A substring also makes curation decisions nobody made: "Adenocarcinoma of the
# Gastroesophageal Junction" lands in ESCA because "Gastroesophageal" CONTAINS
# "esophageal". That call is preserved below, but now explicitly, as GEJ.
#
# Values are verbatim DepMap Model.csv OncotreeCode strings. NSCLC matches the
# target-contracts crosswalk `depmap_oncotree_codes` lane exactly (incl. its deliberate
# exclusion of LUCA, Lung Carcinoid — a neuroendocrine tumour, not NSCLC). ESCA
# deliberately does NOT: that lane holds ['ESCA'] alone, which would drop the 30 ESCC
# models the production organ substring has always included, silently narrowing the
# population 1.46x. The crosswalk lane is under-curated for ESCA; fix it there rather
# than importing it here.
INDICATION_TO_DEPMAP_ONCOTREE_CODES: dict[str, frozenset[str]] = {
    # --- Lung: NSCLC vs SCLC ---
    "NSCLC": frozenset({"LUAD", "LUSC", "NSCLC", "LCLC", "LUAS", "LUMEC", "GCLC", "NUTCL", "NSCLCPD"}),
    "SCLC": frozenset({"SCLC"}),
    # --- Myeloid: AML vs CML. Excludes ALAL and MPALKMT2A, which are acute leukaemias
    # of AMBIGUOUS/mixed lineage by definition and therefore neither. ---
    "AML": frozenset({"AML", "AMLNOS", "AMLMRC", "AMOL", "MLADS", "AMLMD", "AMKL", "AMML"}),
    "CML": frozenset({"CMLBCRABL1"}),
    # --- Esophagus/Stomach: exactly reproduces the production organ substrings ---
    "ESCA": frozenset({"ESCA", "ESCC", "GEJ"}),
    "STAD": frozenset({"STAD", "TSTAD", "DSTAD", "SSRCC", "MSTAD", "STAS", "STSC"}),
    # --- Lineages that merge no catalogued PEER but are still not pure. Both sets are
    # the governed crosswalk lane adopted VERBATIM, so neither is a curation call made
    # here; both were simply never read on the prefetch path.
    #
    # `Bowel` 146 -> COADREAD 133: excludes 3 anal squamous, 2 duodenal, 1 small bowel,
    # 1 small intestinal, 2 appendiceal, 1 colorectal high-grade neuroendocrine, and 3
    # BENIGN lesions (tubular adenoma, sessile serrated adenoma, tubulovillous adenoma)
    # — a benign adenoma in a carcinoma denominator is not a borderline call.
    "COADREAD": frozenset({"COAD", "COADREAD", "READ", "MACR"}),
    # `Eye` 29 -> UVM 16, the largest RELATIVE over-count measured (1.8x): 6
    # retinoblastoma (a distinct paediatric RB1-driven disease) plus 7 immortalized
    # retinal/corneal lines. No MAF-backed catalog today, so no expected_n moves — added
    # so the next one authored does not inherit the defect.
    "UVM": frozenset({"UM"}),
}

# Models whose OncotreeCode is NULL are UNCLASSIFIABLE by the code sets above and are
# therefore excluded from every indication — with a counted, logged disposition, never a
# silent drop. That default is right for 13 of the 14 null-code models in the three
# collapsed lineages (6 immortalized non-tumour lines, 4 SMARCA4-deficient
# undifferentiated tumours, 2 immortalized blood, 1 spherocytosis) and WRONG for one:
# "Acute Promyelocytic Leukemia" is definitionally AML (FAB M3). Claimed back here by
# EXACT OncotreeSubtype string — not a substring — so the claim cannot widen silently.
#
# ★ This is the mirror hazard of the coarse lineage, and the more dangerous one: a code
# set that drops null-code models SHRINKS the denominator, and a smaller denominator
# reads as a more careful cohort. Silent exclusion hides better than silent inclusion.
INDICATION_TO_DEPMAP_SUBTYPE_CLAIMS: dict[str, frozenset[str]] = {
    "AML": frozenset({"Acute Promyelocytic Leukemia"}),
}

# Indications served by a lineage that merges >= 2 distinct diseases but for which no
# code set is declared, so they still receive the WHOLE lineage. Declared, not derived:
# deriving from INDICATION_TO_DEPMAP_LINEAGE multiplicity would count ALIASES (LUAD and
# LUSC are aliases of NSCLC, not peers), inflating `Lung` to 4-way. Asserted EXACTLY by
# test_unnarrowed_shared_lineage_roster_is_exact, so this list cannot grow in silence.
# None of these has a MAF-backed subgroup catalog today, so none carries an expected_n.
SHARED_LINEAGE_NOT_NARROWED: frozenset[str] = frozenset(
    {"ACC", "PCPG", "GBM", "LGG", "KICH", "KIRC", "KIRP", "BCC", "MELANOMA", "SKCM", "UCEC", "UCS"}
)

# ★ A SECOND, WEAKER failure that the roster above does NOT cover, and that the first
# draft of this module actively concealed: a lineage can merge no catalogued PEER and
# still not be PURE. These three carry a MAF-backed catalog, a null `depmap_oncotree_codes`
# lane, and measurable off-indication residue in DepMap 26Q1:
#
#   BRCA  `Breast`         130 -> 126 carcinoma  (4 immortalized breast lines)
#   HNSC  `Head and Neck`   96 ->  91 squamous   (2 salivary-gland: adenoid cystic +
#                                                 mucoepidermoid; 2 NUT midline; 1 "other")
#   PAAD  `Pancreas`       126 -> 124            (1 pancreatic neuroendocrine tumour,
#                                                 1 immortalized stromal line)
#
# They are deliberately NOT narrowed here. Every code set above is the governed
# target-contracts lane adopted verbatim; inventing one for these three would make a
# CURATION decision in analysis-methods that belongs in the vocabulary, which is exactly
# how INDICATION_TO_DEPMAP_ORGAN's "Gastroesophageal contains esophageal" call got made
# by accident. The lane is null for all three — flagged there, not fixed here.
#
# The roster exists so the un-narrowed path can say "not narrowed" WITHOUT implying
# "verified pure". The first draft's note read "lineage X is not declared as merging
# indications", which a reader would reasonably take as a purity claim it had not earned.
LINEAGE_NOT_VERIFIED_PURE: frozenset[str] = frozenset({"BRCA", "HNSC", "PAAD"})


@dataclass(frozen=True)
class DepMapPopulation:
    """The model set for one indication, with every excluded model accounted for.

    `kept + off_indication + unclassifiable == lineage_total` always holds, so a silent
    inclusion and a silent exclusion are both arithmetic errors rather than judgement
    calls. `narrowed=False` means the lineage was returned whole.
    """

    indication: str
    lineage: str
    model_ids: frozenset[str]
    lineage_total: int
    off_indication: int
    unclassifiable: int
    claimed_by_subtype: int
    narrowed: bool
    note: str

    @property
    def kept(self) -> int:
        return len(self.model_ids)


def depmap_population_for(indication: str, model_df) -> DepMapPopulation:
    """Return the DepMap model set for `indication`, narrowed within its lineage.

    `model_df` is Model.csv as a DataFrame (ModelID, OncotreeLineage, OncotreeCode,
    OncotreeSubtype). Deliberately takes the frame rather than reading it, so this
    module stays pandas-free at import time — `--help` on the prefetch script must
    stay fast.

    Raises KeyError (never returns a default) when the indication has no lineage, for
    the same reason depmap_lineage_for does: a missing mapping must be loud, not a
    silently pan-cancer cohort.
    """
    key = (indication or "").upper()
    lineage = depmap_lineage_for(key)
    in_lineage = model_df[model_df["OncotreeLineage"] == lineage]
    total = len(in_lineage)

    codes = INDICATION_TO_DEPMAP_ONCOTREE_CODES.get(key)
    if not codes:
        # Three distinct reasons, ranked by how wrong the resulting population is. None
        # of them asserts the lineage is PURE — that claim requires a code set.
        if key in SHARED_LINEAGE_NOT_NARROWED:
            why = f"lineage {lineage!r} MERGES >=2 catalogued indications and {key} declares no code set"
        elif key in LINEAGE_NOT_VERIFIED_PURE:
            why = (
                f"lineage {lineage!r} merges no catalogued peer but is NOT verified pure "
                f"for {key} (governed depmap_oncotree_codes lane is null)"
            )
        else:
            why = f"no code set is declared for {key}, so purity of {lineage!r} is UNVERIFIED"
        return DepMapPopulation(
            indication=key,
            lineage=lineage,
            model_ids=frozenset(in_lineage["ModelID"]),
            lineage_total=total,
            off_indication=0,
            unclassifiable=0,
            claimed_by_subtype=0,
            narrowed=False,
            note=f"NOT NARROWED: {why}; population is the whole lineage ({total} models)",
        )

    code_col = in_lineage["OncotreeCode"]
    by_code = in_lineage[code_col.isin(codes)]
    claims = INDICATION_TO_DEPMAP_SUBTYPE_CLAIMS.get(key) or frozenset()
    claimed = in_lineage[code_col.isna() & in_lineage["OncotreeSubtype"].isin(claims)]

    kept_ids = frozenset(by_code["ModelID"]) | frozenset(claimed["ModelID"])
    null_code = int(code_col.isna().sum()) - len(claimed)
    off = total - len(kept_ids) - null_code
    return DepMapPopulation(
        indication=key,
        lineage=lineage,
        model_ids=kept_ids,
        lineage_total=total,
        off_indication=off,
        unclassifiable=null_code,
        claimed_by_subtype=len(claimed),
        narrowed=True,
        note=(
            f"narrowed {lineage!r} {total} -> {len(kept_ids)} models "
            f"({off} other-indication, {null_code} null-OncotreeCode excluded"
            + (f", {len(claimed)} claimed by exact OncotreeSubtype" if len(claimed) else "")
            + ")"
        ),
    )


def depmap_lineage_for(indication: str) -> str:
    """Return the DepMap OncotreeLineage for `indication`, or raise.

    Raises KeyError (never returns a default) so a missing mapping is a loud failure
    rather than a silently pan-cancer or silently empty cohort.
    """
    key = (indication or "").upper()
    try:
        return INDICATION_TO_DEPMAP_LINEAGE[key]
    except KeyError:
        raise KeyError(
            f"No DepMap lineage mapping for indication {indication!r}. Add it to the "
            f"CANONICAL map methods/depmap_chronos/cli.py::INDICATION_LINEAGE (value must "
            f"be a verbatim DepMap Model.csv OncotreeLineage string); do not fork a copy "
            f"here. DepMap 26Q1 genuinely has no lineage for THYM."
        ) from None
