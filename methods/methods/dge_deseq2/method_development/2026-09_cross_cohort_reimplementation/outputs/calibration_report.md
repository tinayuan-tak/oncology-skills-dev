# RUVg cross-cohort calibration — Stage 1 (piped-whistling-conway B4)

**Anchor:** within-TCGA cell A (tumor vs TCGA adjacent-normal, confound-free). **Question:** does RUVg-Cr move the cross-cohort contrast toward A vs naive-C, and does it agree across substrates?

- substrates: recount3, xena-toil  ·  indications: brca, paad  ·  RUVg k=2  ·  sig q<0.05

RIN/ischemic arm dropped (GTEx-only / non-identifiable — see `rin_symmetry_probe.json`).


## Concordance vs cell-A anchor

| substrate/ind | cells | n A-sig | ρ(A,C) | ρ(A,Cr) | ρ uplift | sign-agree C | sign-agree Cr | agree uplift | sig% A | sig% C | sig% Cr |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| recount3/brca | A+C+Cr | 22798 | 0.656 | 0.604 | -0.052 | 0.809 | 0.783 | -0.026 | 0.741 | 0.902 | 0.899 |
| recount3/paad | A+C+Cr | 694 | 0.159 | 0.198 | 0.039 | 0.632 | 0.657 | 0.026 | 0.023 | 0.878 | 0.798 |
| xena-toil/brca | A+C+Cr | 17875 | 0.710 | 0.739 | 0.029 | 0.810 | 0.829 | 0.019 | 0.818 | 0.903 | 0.904 |
| xena-toil/paad | A+C+Cr | 563 | 0.174 | 0.194 | 0.019 | 0.663 | 0.692 | 0.029 | 0.026 | 0.887 | 0.852 |

## Cross-substrate Cr agreement (recount3 vs Xena/Toil)

| indication | shared genes | ρ(Cr recount3, Cr xena) |
|---|--:|--:|
| brca | 16941 | 0.881 |
| paad | 16688 | 0.942 |

## Calibration verdict — NEGATIVE (do not use Cr as a verdict input)

Reviewed 2026-09-20 by four independent lenses (statistical methodology, cancer-genomics
domain, adversarial data-integrity/QC, decision/process). **Unanimous: RUVg-Cr does not
recover the within-TCGA anchor, and the failure is structural, not a tuning miss.** The
plan's premise (RUVg-in-GLM makes the cross-cohort TCGA-vs-GTEx contrast trustworthy) is
**refuted** on the only trustworthy anchor.

**Why (the numbers above, read honestly):**

- **Cr ≈ C.** Pearson(log2FC_C, log2FC_Cr) = 0.96–0.98 in all four cells. RUVg k=2 shifts
  LFCs by only ~0.2–0.5 log2 units; its net effect on concordance-to-anchor is at the
  metric's noise floor (|ρ uplift| ≤ 0.05) and **flips sign by substrate** on brca
  (−0.052 recount3 / +0.029 xena). On the designated PRIMARY substrate (recount3) with the
  only adequate anchor (brca, n=114 adjacent normals) **Cr is WORSE than naive C** (ρ falls;
  sign-flips rise 4335→4919).

- **The significance-inflation confound is only PARTIALLY corrected — and the residual is
  disqualifying.** The multi-anchor re-run (6 recount3 anchors, rebuilt metric below) shows
  RUVg *does* lower the false-positive rate against the anchor's clearly-null genes on 5/6
  cohorts (paired uplift −0.02 to −0.14, largest on coad 0.593→0.457), but the **residual FPR
  under Cr stays 0.35–0.47 on every anchor** — roughly 45% of genes the confound-free anchor
  calls clearly-null are still called significant. RUVg moves Cr a fraction of the way from
  naive C toward the anchor and stops far above any usable level. (An earlier brca-centric
  read called this "essentially uncorrected / 76–82%" and "36–46% made *more* significant";
  the rebuilt metric — strict anchor-null `padj_A>0.5 & |lfc_A|<gate`, scored at the shipped
  s-value gate, with bootstrap CIs — is the authoritative number and the more precise story:
  partial reduction, disqualifying residual.)

- **RETRACTED: high cross-substrate ρ does NOT mean "biology, not artifact."** recount3 and
  Xena/Toil reprocess the SAME raw reads and carry the IDENTICAL TCGA-vs-GTEx confound, so
  agreement measures reproducibility of the confound, not validity. In fact RUVg *degrades*
  cross-substrate reproducibility: naive C reproduces at ρ≈0.964 (brca) but Cr only 0.881.
  A reproducible artifact looks exactly like this.

- **paad cannot adjudicate anything: its anchor (cell A) rests on n=4 adjacent normals.**
  apeglm collapses the LFC distribution (median |log2FC| = 0.03) → a no-power reference, not
  a confound-free truth. Every paad metric is correlation against noise; no paad conclusion
  is supportable. paad should NOT have been used as the "low" calibration bound.

- **Structural cause:** every tumor is TCGA and every normal is GTEx, so cohort/platform is
  perfectly aliased with `group`. RUVg's latent factors capture the TCGA/GTEx axis = the
  group axis; `~ W + group` is near-collinear and can only apportion the shared variance by
  *assuming* the empirical controls are not truly DE — an untestable assumption, not
  identification. (Empirical controls are additionally circular: ~54% of the control set are
  also anchor-significant genes; housekeeping is ~99.5% diluted out.) This is the same
  non-identifiability that retired cross-cohort ComBat (cell D). No counts-only latent-factor
  method or choice of k can resolve it.

**Disposition (user sign-off 2026-09-20):**
- Ship the anchor-independent v2 wins (baseMean carry-through, apeglm s-values,
  comparator-family de-dup, no-Welch) — these are sound and independent of the RUVg question.
- Ship Cr **diagnostic-only**, tagged with this negative-calibration verdict; it must NOT
  feed the classifier or any ranker. Classifier stays on cell A + naive C (as the plan
  already architects). The surfaceome `_cell_pairs` allowlist fix is a hard prerequisite.
- Do NOT extend RUVg-Cr to the 7 GTEx-only cohorts: RUVg failing where we CAN check removes
  any basis to trust it where we cannot. That goal is unsupportable by this method, not
  merely deferred.

**Multi-anchor confirmation (re-run DONE 2026-09-20 — see `multi_anchor/multi_anchor_calibration.md`).**
The k=2 study scored cells with whole-genome Spearman ρ, which is dominated by ~30k near-null
genes and insensitive to the sign-flips/inflation that matter (uplifts were also reported to 3
decimals with no uncertainty, sig% from raw-Wald padj not the shipped gate, and k=2 was
hardcoded). The authorized re-run fixed all of that: it **rebuilt the metric** (FPR-vs-anchor-null
+ sign-concordance on anchor-significant genes + effect-size correlation, each with a
gene-bootstrap 95% CI and a *paired* Cr−C uplift CI, scored at the shipped s-value gate) and ran
it **recount3-only on 6 anchors with adequate adjacent-normal power** (brca/kirc/luad/lusc/prad/coad,
n_adjacent 41–114; paad dropped as n=4). Findings:
- **The disqualifying fact is invariant across all six anchors:** residual FPR under Cr is
  0.35–0.47 — Cr never approaches the confound-free anchor on any indication.
- **RUVg's effect on the concordance metrics is COHORT-DEPENDENT, not uniformly harmful.** It
  degrades sign-concordance / effect-correlation on the high-baseline cohorts
  (brca/kirc/luad/lusc, all uplift CIs below 0) but *marginally* improves them on the two
  lower-baseline cohorts (prad +0.007 [.001,.013], coad +0.019 [.014,.025]). Every improvement
  is tiny beside the residual FPR.
- That mixed, baseline-dependent direction is itself the signature of non-identifiability: with
  cohort aliased to `group`, RUVg apportions shared variance in a way that helps or hurts by
  accident of each cohort's baseline, never converging on the anchor. k-selection was not
  pursued — the failure is structural, not k-dependent (the k-scan was killed as moot).

Net: the NEGATIVE verdict holds across a diverse panel and the premise is closed — **Cr is not
a verdict input on any indication.**


_Generated by `scripts/ruvg_calibration.py --report`; verdict + multi-anchor confirmation
added after the 2026-09-20 four-agent review, user sign-off, and the authorized multi-anchor
re-run (`scripts/multi_anchor_report.py`)._
