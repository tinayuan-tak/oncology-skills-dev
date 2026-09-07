"""exon_skip_carrier.events — curated registry of exon-skipping / splice-driver events.

Each event is a genomic WINDOW (a target gene locus + a coordinate span covering the
splice acceptor of the preceding intron, the skipped exon, and the splice donor of the
following intron) plus the set of variant classifications that count as splice-disrupting.
A sample is a CARRIER of the event iff it has a splice-classified variant inside the window.

WHY a coordinate window (not `effect == 'splice_site' && exon == N`): the generic
exon-predicate cannot run on data sources whose variant tables drop the exon number
(DepMap's derived somatic parquet exposes only ModelID/VariantType/VariantInfo/
ProteinChange/HugoSymbol — no exon, no position). Splice CLASSIFICATION alone is not
specific either: MET has splice-site variants 1-40 kb from exon 14 that are NOT METex14.
A genomic window is the robust cross-source primitive: it isolates the exon-14 cluster and
excludes the distant splice sites, and it validates against the canonical cell lines.

Coordinates are pinned to a genome build; callers MUST supply build-matched positions
(DepMap 26Q1 + TCGA MC3 + GENIE public are all hg38-aligned).

SCOPE NOTE: this registry is deliberately event-specific, NOT a generic "any exon skip"
heuristic. Distinct exon/isoform oncogenic events arise by distinct mechanisms (EGFRvIII is
a genomic exon 2-7 DELETION; AR-V7 is cryptic-exon splicing) and must each be curated with
their own window + evidence — do not fold them under one predicate.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExonSkipEvent:
    event_id: str
    gene: str
    genome_build: str
    chrom: str  # normalized "chr7"
    window_start: int  # inclusive; covers intron-(N-1) acceptor/branch + exon N + intron-N donor
    window_end: int  # inclusive
    exon_start: int  # canonical skipped-exon bounds (provenance / tightening)
    exon_end: int
    exon_number: int
    # variant classifications (lower-cased) that count as splice-disrupting for this event.
    # Covers both MAF title-case (splice_site/splice_region) and VEP consequence tokens.
    splice_classifications: frozenset = field(default_factory=frozenset)
    # cell lines / samples that are UNIVERSALLY-agreed positives — used as test anchors and
    # as a build-time sanity assertion, NOT as the classification rule.
    canonical_positive_samples: frozenset = field(default_factory=frozenset)
    # hg19/GRCh37 window (patient MAFs — TCGA MC3, GENIE public — are GRCh37-aligned, unlike the
    # hg38 DepMap arm). None when not curated. Same acceptor/exon/donor span, lifted to hg19.
    window_start_hg19: int = None
    window_end_hg19: int = None
    # CURATED oncogenic scope: indications where this exon-skip event is an established DRIVER
    # (OncoTree/framework codes). Drives the genomic-alteration splice-driver characterization.
    oncogenic_indications: frozenset = field(default_factory=frozenset)
    driver_direction: str = ""  # activating | loss_of_function (METex14 = activating/GoF)
    note: str = ""


# hg38 window for MET exon 14 (MANE ENST00000318493 exon 14 = chr7:116,771,849-116,771,989,
# + strand; pinned from gencode-v26-exon-index-v1). The window extends ~250 bp into intron 13
# (splice acceptor + branch point / polypyrimidine tract) and ~60 bp into intron 14 (splice
# donor), matching the clinically-reported METex14 alteration region (Frampton et al.,
# Cancer Discov 2015; 10.1158/2159-8290.CD-15-0285). Validated against DepMap 26Q1: recovers
# EBC-1 (ACH-000616) + Hs746T (ACH-000628) donor variants @116,771,990 and the ACH-000988
# acceptor-side variant @116,771,656; EXCLUDES the five distant MET splice sites at
# 116,731,662 / 116,755,516 / 116,769,792 / 116,774,880 / 116,775,112.
METEX14 = ExonSkipEvent(
    event_id="METex14",
    gene="MET",
    genome_build="hg38",
    chrom="chr7",
    window_start=116_771_600,
    window_end=116_772_050,
    exon_start=116_771_849,
    exon_end=116_771_989,
    exon_number=14,
    splice_classifications=frozenset(
        {
            "splice_site",
            "splice_region",  # MAF title-case (lower-cased)
            "splice_donor_variant",
            "splice_acceptor_variant",
            "splice_region_variant",  # VEP
        }
    ),
    canonical_positive_samples=frozenset({"ACH-000616", "ACH-000628"}),  # EBC-1, Hs746T
    # hg19 window (TCGA MC3 / GENIE public are GRCh37): exon 14 ≈ chr7:116,411,850-116,411,990;
    # cluster empirically observed in MC3 at 116,411,551 (intron-13 acceptor side) + 116,412,042-045
    # (intron-14 donor). Window spans the acceptor/branch → donor, excluding distal MET splice sites
    # (116,397,691 / 116,403,323 / 116,422,041 / 116,423,356 / 116,435,707).
    window_start_hg19=116_411_500,
    window_end_hg19=116_412_100,
    oncogenic_indications=frozenset({"LUAD", "LUSC", "NSCLC"}),  # curated METex14 driver scope
    driver_direction="activating",
    note="MET exon-14 skipping — FDA companion-Dx biomarker for capmatinib/tepotinib; "
    "removes the CBL degron (GAIN-of-function stabilization, not loss).",
)


EXON_SKIP_EVENTS = {e.event_id: e for e in (METEX14,)}
