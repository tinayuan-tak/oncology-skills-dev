"""gdc_dr45_pancohort — per-aliquot MAF aggregator for the GDC DR45 pan-cohort ensemble.

The GDC Data Release 45 somatic ensemble (gdc-pancohort-somatic-dr45-0) is 21,300 individual
per-aliquot masked-MAF.gz files across 14 programs, hg38, NOT a single consolidated MAF (contrast
TCGA-MC3's one mc3.v0.2.8.PUBLIC.maf.gz). Its value for the framework is the NON-TCGA programs —
net-new patient-mutation coverage the MC3/GENIE substrates don't have.

SCOPE (2026-08-06, targeted slice): ALCHEMIST-ALCH → NSCLC only. ALCHEMIST is a whole-program
NSCLC-adjuvant trial (no per-case disease-join needed — every case is NSCLC), so it is the clean
data-in-hand DR45 slice. CPTAC-3 (which spans CRC/LUAD/PDAC and needs a per-case disease mapping
from the CPTAC clinical XLSXs) + the new-indication programs (MMRF/TARGET/BEATAML) are deferred.

Emits the SAME two shapes as methods/gdc_somatic_hotspot so DR45 is a drop-in second MAF source:
  - aggregate: per-(indication, gene) frequency + hotspots (read_hotspot_summary contract)
  - per-sample: per-(case, gene, protein_change) rows (panorama substrate)

METHOD_VERSION 0.1.0.
"""
from __future__ import annotations

METHOD_VERSION = "0.1.0"

# Program → framework indication. Only whole-program-single-disease mappings live here (no
# per-case disease-join). CPTAC-3 is deliberately ABSENT (multi-disease; needs the clinical join).
PROGRAM_TO_INDICATION = {
    "ALCHEMIST-ALCH": "NSCLC",   # NCI ALCHEMIST adjuvant trial — all NSCLC
}
