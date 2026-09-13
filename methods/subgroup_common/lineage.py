"""Indication → DepMap lineage/organ scoping for the subgroup-assigner lane.

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

from methods.depmap_chronos.read import INDICATION_TO_DEPMAP_LINEAGE

# For lineages DepMap collapses across organs, a second filter on OncotreeSubtype
# separates the indication. "Esophagus/Stomach" holds both gastric (Stomach*) and
# esophageal (Esophageal*) models; the substring is matched case-insensitively against
# OncotreeSubtype. Indications absent here use the lineage filter alone. This map has
# no canonical home elsewhere — it exists only for subgroup scoping.
INDICATION_TO_DEPMAP_ORGAN = {
    "STAD": "stomach",  # Stomach Adenocarcinoma, Tubular/Diffuse/Signet-Ring Stomach, ...
    "ESCA": "esophageal",  # Esophageal Adenocarcinoma, Esophageal Squamous Cell Carcinoma
}


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
