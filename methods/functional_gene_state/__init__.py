"""functional_gene_state — the harmonized two-hit / biallelic-inactivation primitive.

For a (target, indication): classify each sample's FUNCTIONAL GENE STATE — how many alleles of the
target are inactivated, and by what mechanism — harmonized across the SNV/indel + copy-number axes
into ONE per-(sample, gene) call. Answers the question the descriptive frequency/CN cards cannot:
"is this gene BIALLELICALLY inactivated (a completed two-hit event → true loss of function), or only
monoallelically hit (one allele still intact)?" — the distinction that separates a driver LoF event
from a passenger heterozygous variant, and the substrate for synthetic-lethality / TSG reasoning.

The GENETIC-ONLY vocabulary (no new ingestion):
    {wt, monoallelic, biallelic-genetic, uncertain}
  built from mutation + allele-specific copy number, both patient (TCGA) and model (DepMap) sides.
A planned extension adds the epigenetic second hit
    {epigenetic, biallelic+epigenetic}
  once patient DNA-methylation (PanCanAtlas HM450) is ingested + collapsed to promoter methylation
  (DepMap RRBS already covers the model side). The genetic-only states are a strict subset — additive, no rework.

Two-hit logic (genetic-only), identical shape on both sides:
  - biallelic-genetic : homozygous deletion (both copies gone), OR a mutation on a single-copy /
                        LOH background (mutation + loss-of-the-other-allele → both alleles hit).
  - monoallelic       : exactly one hit — a heterozygous mutation on a copy-neutral non-LOH
                        background, OR single-copy loss with no mutation.
  - wt                : no mutation and no copy loss.
  - uncertain         : signals present but the second-hit call is ambiguous (e.g. mutation on a
                        copy-neutral-LOH background we cannot confirm, or below the coverage floor).

Substrate (all LANDED + verified readable; no new ingestion):
  PATIENT
    - MC3 mutations (`mc3.v0.2.8.PUBLIC.maf.gz`, hg19): Hugo_Symbol, Chromosome, Start_Position,
      Variant_Classification, Tumor_Sample_Barcode, t_alt_count/t_ref_count.
    - PanCanAtlas ABSOLUTE segments (`TCGA_mastercalls.abs_segtabs.fixed.txt`, hg19, SNP6-era):
      per-(sample, chrom, start, end) Modal_HSCN_1/2, Modal_Total_CN, LOH, Homozygous_deletion.
      Build-consistent with MC3 (both hg19) → a POINT-IN-INTERVAL lookup at the mutation's own locus
      reads the covering segment's LOH/homdel flag WITHOUT any gene-coordinate resource.
    - GISTIC per-gene discrete CN (`all_thresholded.by_genes_whitelisted.tsv`): −2 homdel / −1 loss —
      the per-gene homdel call for the NO-mutation case (has a target-resolver sidecar).
    - Barcode→indication: `merged_sample_quality_annotations.tsv` (patient_barcode → `cancer type`).
  MODEL (DepMap 26q1)
    - OmicsSomaticMutationsMatrixDamaging.csv / *Hotspot.csv (model × gene boolean).
    - OmicsCNGeneWGS.csv (per-gene RELATIVE CN → homdel / single-copy-loss thresholds).
    - Model-side per-gene LOH is NOT currently loaded (unwired): OmicsGlobalSignatures.csv holds only
      a genome-wide LoHFraction (a per-model background, not per-gene) and the read layer does not
      consume it, so model loh_at_locus is always None.

Model-side caveat (documented, not silently dropped): DepMap ships RELATIVE per-gene CN +
GENOME-WIDE LoH, not per-gene allele-specific CN. So the model arm calls homdel + copy-loss cleanly
but cannot confirm copy-NEUTRAL per-gene LOH → those samples resolve `uncertain` rather than a false
biallelic. The dominant biallelic mechanisms (homdel; mutation + copy loss) are unaffected.

Modules:
    classify — pure two-hit classifier (structured evidence → state); no I/O, fully unit-testable.
    read     — read_functional_gene_state(target, indication): patient + model arms, bounded live
               reads (single gene × single indication slices — never the full matrix on the read
               path); prefers a precomputed derived product when present (an accelerator).
"""
from __future__ import annotations

from .read import read_functional_gene_state, read_model_states_per_model
from .classify import (
    classify_functional_state,
    FUNCTIONAL_STATES,
)

METHOD_VERSION = "0.2.0"      # +read_model_states_per_model public accessor (for the model-match assembler); arm output byte-stable

__all__ = [
    "read_functional_gene_state",
    "read_model_states_per_model",
    "classify_functional_state",
    "FUNCTIONAL_STATES",
    "METHOD_VERSION",
]
