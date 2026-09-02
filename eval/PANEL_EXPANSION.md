# Known-target panel — expansion design

How the backtest's truth-set (`known_target_calibration_set.yaml` `reference_profiles`) and the
signals it extracts should grow. The panel is the instrument the improvement loop optimizes against,
so expansion is about **sharpening measurement**, never about tuning toward a hit-rate.

## Principles (carry through every addition)
- **Labels falsify, they do not optimize.** Add entries to *test coverage*, never to train. Approved-
  drug labels are POSITIVE CONTROLS, not signal — `ot_approved ≈ Tclin` is a known leakage trap.
- **Negatives are the scarce, high-value class.** A panel that is mostly approved winners cannot
  measure specificity. Prioritize declined/failed programs + decoys over more positives.
- **Balance per blind-axis family.** Enough anchors per family (SL, cell-state-window, GoF, surface-
  antigen, subtype) that per-family capture-rate is a real metric, not 1–2-target noise.
- **Every entry carries outcome provenance + `deciding_axis`** (the existing curation discipline).
- **Verify each new entry with a live emit before trusting its label** (the CASE-001/005 lesson —
  curated labels drift; the framework may already read it differently).

## Priority order

### Tier-S — SUBTYPE-PRIMARY targets (TOP priority, user-directed)
Targets whose nomination signal is **subtype-conditional** — the call hinges on a molecular subtype,
and the subtype signal must be **extracted and HEADLINED**, not buried. These exercise the framework's
subtype axis (`--subtypes` → `subtype_fit` tier + `subtype_facet` + `subgroup-stratified` cards),
which the panel emitted subtype-BLIND until now (so the subtype signal was never scored).

Candidate anchors (target · indication · defining subtype axis · known outcome):
| target | indication | subtype axis | outcome |
|---|---|---|---|
| KRAS | LUAD/COADREAD | G12C vs other RAS | approved (sotorasib/adagrasib) — G12C-specific |
| EGFR | LUAD | ex19del/L858R vs ex20ins vs WT | approved — subtype determines TKI |
| BRAF | COADREAD vs SKCM | V600E; CRC needs combo | approved SKCM / conditional CRC — subtype+lineage |
| ERBB2 | BRCA/STAD | amplified vs mutant | approved (amp) — alteration-class subtype |
| PIK3CA | BRCA | mutant (HR+) | approved (alpelisib) — mutation subtype |
| IDH1 | AML/glioma | R132 neomorphic | approved — (coordinate: GoF, parallel session) |
| KRAS(non-G12C) | PAAD | MSS/RAS context | active — negative-ish subtype control |

Panel requirements for Tier-S (see "Extraction" below): emit each with its `--subtypes` axis, then
extract + headline `subtype_fit` (the negative-selection verdict: a measured non-dependent subtype →
hold) + the `subtype_facet` (which stratum carries the signal) + `subtype_resolved`.

### Tier-2 — NEGATIVES + DECOYS (fills the scarce class)
~10–15 **declined/failed** oncology programs (terminated ct.gov trials, published Ph2/3 failures) +
a handful of **decoy true-negatives** (housekeeping / undruggable genes) to test the framework does
not nominate noise. Existing negatives to build on: CEACAM5 (Ph3 fail), MUC13, GRIN2D, RBM39
(correctly-declined validated_lane). Sharpens specificity — the biggest cheap gain.

### Tier-1 — MULTI-INDICATION (mechanical breadth)
Run existing targets across several indications (KRAS in COADREAD/LUAD/PAAD; ERBB2 in BRCA/STAD; MET
in LUAD). Tests context-sensitivity of the signal vector. Needs a curated outcome per new
(target, indication) but no new targets.

### Tier-3 — Takeda internal portfolio (~55 ONC, gated)
Real advanced/declined program outcomes — the best signal (includes real negatives), needs internal
curation. Hold until the public tiers are in and the internal truth-set is available.

## Extraction — the panel must EXTRACT + HEADLINE the subtype signal
`run_known_target_panel.py` changes (this workstream):
1. **Emit subtype-aware:** carry an optional `subtypes` per profile → pass `--subtypes` to the emit
   (subtype_fit is opt-in; without it the subtype signal is absent — that is why it was unscored).
2. **Extract:** add `subtype_fit` verdict + `subtype_facet` (stratum carrying the signal) +
   `subtype_resolved` strata to the per-target signal vector.
3. **Headline:** surface a subtype line in the panel rollup — how many subtype-primary targets had a
   subtype signal CAPTURED vs blind, and whether `subtype_fit` correctly flagged the deciding stratum.
   Subtype capture becomes a first-class fidelity metric alongside deciding-axis capture.

## Where entries land
New `reference_profiles` go in `target-contracts/vocabularies/known_target_calibration_set.yaml`
(the single source of truth the panel reads), each with `indication`, `modality`, `subtype` (new,
for Tier-S), `outcome`, `deciding_axis`, `agreement`, `severity`, and an outcome-provenance `note`.
Coordinate with any parallel session touching genomic-alteration / GoF before adding GoF-subtype
entries (IDH1, KRAS-G12C overlap the mutation-stratified path).
