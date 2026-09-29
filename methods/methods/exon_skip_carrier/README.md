# exon_skip_carrier

Identify samples carrying a curated **exon-skipping / splice-driver** event. The missing
primitive for biomarker-conditional splice drivers — seeded with **METex14** (MET exon-14
skipping), the FDA companion-Dx biomarker for capmatinib / tepotinib.

## Why this exists

METex14 is a ~3–4 % splice-site subset of NSCLC. It is invisible to the SNV/hotspot-centric
genomics and to the pan-line dependency distribution, so gene-level MET reads pan-line
`non_dependent` in `functional-requirement` even though it is an approved TKI/ADC target
(the CASE-002 / MET-LUAD `known_gap` false-negative). This module produces the **carrier
sample set** a downstream consumer needs to stratify a dependency / prevalence signal.

## Method

- `events.py` — curated `ExonSkipEvent` registry: gene locus + genomic **window** + splice
  classifications. `METex14` = hg38 `chr7:116,771,600–116,772,050` (exon 14 =
  116,771,849–116,771,989 from `gencode-v26-exon-index-v1`, extended into the intron-13
  acceptor/branch and intron-14 donor per Frampton et al. 2015).
- `classify.py` — pure, source-agnostic classifier. A sample carries an event iff it has a
  splice-classified variant **positioned inside the window**. Position is required.
- `read.py` — `depmap_carriers(event_id, release_pin)` streams the **raw** DepMap somatic MAF
  (`OmicsSomaticMutationsMAF.maf`), the position-bearing source; `carriers_from_observations`
  is the source-agnostic wrapper for MC3/GENIE.

### Why a genomic window, not `effect=='splice_site' && exon==14`

The exon predicate cannot run on DepMap — its derived somatic parquet exposes only
`ModelID/VariantType/VariantInfo/ProteinChange/HugoSymbol` (no exon, no position). Splice
classification alone is not exon-specific: MET has splice-site variants 1–40 kb from exon 14.
The genomic window is the robust cross-source primitive.

## Validation (DepMap 26Q1, live 2026-09-02)

`depmap_carriers("METex14")` → **3 carriers**: `ACH-000616` (EBC-1), `ACH-000628` (Hs746T) —
the universally-agreed METex14 lines — and `ACH-000988` (intron-13 acceptor side). The five
distant MET splice sites (`ACH-001306/001321/001653/001864/000755`, 116,731,662 /
116,755,516 / 116,769,792 / 116,774,880 / 116,775,112) are correctly excluded.

## Scope

`METEX14` only. Other exon/isoform oncogenic events (EGFRvIII genomic deletion, AR-V7 cryptic
splicing) arise by distinct mechanisms and must each be curated — do not fold them under one
predicate. Verdict wiring (dependency stratification / patient prevalence / resolver rung)
lands as **backtested follow-ups**; this PR is the classifier primitive only.
