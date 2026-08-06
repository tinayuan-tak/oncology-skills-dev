---
name: bispecific-pair-scan
description: |
  Logic-gated AND / OR / NOT antigen-PAIR tumor-selectivity scan — the NET-NEW
  two-antigen (bispecific) capability the v2 framework did not have. Given a
  target antigen + a partner set, scores each pair under a logic gate over
  per-sample TCGA-tumor vs GTEx-normal TPM and emits a RANKED pair list.

    AND — engage where BOTH antigens present: raises selectivity when each alone
          is too broad (HER2xHER3 archetype).
    NOT — engage where A present AND a veto antigen ABSENT: on-target/off-tumor
          rescue (the veto marks the normal tissue to spare).
    OR  — engage where EITHER present: heterogeneity backstop (only as clean as
          its dirtiest arm).

  SCAN-HOOK skill (like surfaceome-cohort-ranking), NOT a per-target card: the
  framework's card/resolver/run_plan spine is single-target (no target_pair
  grain), so pair selectivity is emitted as a ranked derived list + the canonical
  wired-skill decision.json, OUTSIDE the per-target verdict spine. Candidate
  GENERATION — nominates pairs to confirm, handed to a human.

  Ports the biologics-target-discovery bstrat.gates physics; compute lives in
  analysis-methods/methods/pair_selectivity_gate.

  HONEST LIMITATION: bulk co-expression in a SAMPLE is necessary but NOT
  sufficient for same-CELL co-expression (avidity — what an AND-gate bispecific
  actually needs). Same-cell confirmation needs single-cell / spatial (CELLxGENE
  Census) — a documented gap; every result carries this caveat. Also a BOUNDED
  BACKGROUND job (~60-90s per pair — the GTEx per-sample read dominates), NOT an
  interactive per-target lookup; keep the partner set to dozens.

  Use for questions like "what antigen pairs AND-selectively with EPCAM in
  COADREAD?", "is there a NOT-gate veto that rescues CEACAM5 in colon?"

metadata:
  version: 1.0.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: batch_compute
  phase: [F]
  cards_used:
    - bispecific-pair-scan
  rules_scope:
    - bispecific-pair-scan
  synthesis:
    - none
  output_shape:
    - data_package
  steps_covered: [1, 2]
  status: partial      # runnable on COADREAD/NSCLC-mapped indications; a background scan, not interactive
---

# bispecific-pair-scan

## What this skill does

- For a `--target` antigen + a partner set (`--partners` or the ~40 clinical-seed
  surface antigens), scans each pair under `--gate` (AND / OR / NOT).
- Reads per-sample TCGA-tumor + GTEx-normal TPM (the `*-tpm-recount3-long-v1`
  products) via `methods/pair_selectivity_gate`, computes per-group gate-positive
  fractions, and ranks pairs by selectivity (tumor-fraction ÷ max-essential-normal-
  fraction, with the AND/NOT coverage gate + resolution floor).
- Emits **both** the essential-normal AND the full-normal-panel denominator
  (Theme-1 fix — a pair that fires in a non-essential normal tissue like small
  intestine / skin is flagged, not hidden).
- Writes the canonical data-package (`decision.json` + ranked-pairs summary +
  provenance). No card verdict, no resolver rung — a scan output, not a per-target call.

## How Claude invokes this skill

```
export AWS_PROFILE=cbg && \
python3 .../skills/bispecific-pair-scan/scripts/run.py \
  --target EPCAM --indication COADREAD --gate AND --out <OUT_DIR>
# optional: --partners CEACAM5,ERBB2,MET   (else the clinical-seed set)
```

Because each pair is ~60-90s, run larger partner-set scans as a BACKGROUND job
and keep the partner set bounded (dozens; a surfaceome/clinical-seed subset).

## Verified (live, real data)

`AND(EPCAM, CEACAM5)` / COADREAD → 100% tumor vs 20% essential-normal (lung),
**5× selectivity**, tumor-selective — reproducing the biologics-repo worked
example. The Theme-1 denominator correctly CAUTIONS that the pair also co-expresses
in 63% of normal small intestine (GI-epithelial breadth) — the exact non-essential
liability an essential-only scorer would miss.

## Status: partial

Runnable today on indications that map to a TCGA study (COADREAD, NSCLC, BRCA, …);
others resolve `data_unavailable` (honest — the scan is TCGA-cohort-based). The
same-cell avidity confirmation (CELLxGENE Census same-cell coexpression) is the
documented next layer; until then every AND-gate result carries the bulk-≠-same-cell
caveat.
