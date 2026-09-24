# Per-Card Skill Audit Rubric — 2026-09-24

A reusable checklist for auditing a skill card-by-card, distilled from the
tumor-presence audit (24 issues, see tracking #1506). That audit did not find
24 independent problems — it found **~6 recurring failure modes**, most of them
several times. This rubric turns those modes into mechanical probes so the next
skill is *checked against a list* rather than re-investigated from scratch.

**Relationship to other docs.** `DEFINITION_OF_DONE.md` is the author's
done-checklist for a change. This is the *auditor's* rubric for an existing
skill: what to interrogate per card, and the signature of each way it goes
wrong. Where a probe restates a CI guard, that's noted — a green guard is
necessary, not sufficient — a card can be green for the wrong reason.

## How to run it

For each **card** in the skill, and for each **field** that card emits, walk
the nine probes below (Probes 1–6 from the tumor-presence audit; 7–8 added from
the on-target-safety-liability dry-run; 5–8 refined by the immune-context and
differentiation-landscape dry-runs; 9 added from the genomic-alteration-profile
dry-run). Three disciplines wrap the whole pass:

- **Tag every finding** `DEFECT` (wrong verdict/label/gate) · `DATA-UTILIZATION`
  (datum right but under-used / display-only / verdict-inert) · `PIPELINE`
  (CI/ledger/plumbing) · `ARCHITECTURE`. They need different reviewers and
  urgency; in the tumor-presence set ~9 were defects and ~10 were utilization
  gaps, and mixing them muddied triage.
- **Route findings by consumer, not by where you found them.** Auditing one
  skill surfaces defects in its *downstream consumers* and in *shared helpers*
  (`_skills_common`, `risk_projection.py`, and often a sibling repo — the
  **resolver YAMLs and conditioning vocabularies in `target-contracts`**, where
  the actual verdict logic frequently lives). ~5 of the 24 tumor-presence issues
  were not tumor-presence bugs at all. File against the owner, cross-link the audit.
- **Read SKILL.md / changelog against the code, not as ground truth.** On a
  heavily-narrated skill the changelog is a consumer-facing artifact; a stale
  "Known, not fixed" note whose bug was since fixed is green-for-the-wrong-reason
  adjacent (immune-context SKILL.md still listed an abstention gap that
  `subgroup_derivation.py` had already closed). Verify prose claims against
  current code; a doc-drift finding is `PIPELINE`-tagged. *(immune-context dry-run, G4.)*
  This extends to **consumer-coupling claims embedded in the producer's own code
  comments/docstrings**, checked against the *sibling-repo* vocab they describe:
  differentiation-landscape's `run.py` justifies a caveat with "the cooccurrence
  rules inflate a nomination," but the nomination gate wires only
  `strong_mutually_exclusive` as a positive — the co-occurrence classes reach the
  gate as no positive, so the comment's premise is stale. That's where the real
  green-for-the-wrong-reason risk sat. *(differentiation-landscape dry-run, gap 2.)*

**Static vs corpus-dependent probes.** Probes 2, 4, 5, 7, 8, 9 are answerable
from a **static read** of cards + resolver + consumers. Probes 1 and 3 need
**runtime instruments** — the field-disposition ledger (#1506) / reach
classifier (#1509) for 1, and a **corpus run counting fires-vs-verdict-deltas**
for 3. Budget a corpus run up front, or scope those two probes to
wiring-confirmation only and mark findings `needs-verification`.

**The golden may be blind to the rungs you are auditing — do not trust
"byte-stable / verdict-inert" until you check.** On a verdict-driving skill the
resolver golden snapshot often covers only a subset of the resolver's rungs
(the gap is tracked as rule-id coverage debt). In genomic-alteration-profile the
golden's `rule_ids` cover 18 of 29 rungs, and the 11-id gap *contains the
dependency-gate rungs at priorities 0–11 and the indication-scoped-context rules*
— exactly what Probe 8 most wants to test. Editing those rungs produces **no
golden diff**, so "verdict-inert" is unfalsifiable there. Before trusting a
byte-stability claim, diff the golden's rule-id coverage against the rungs in
scope; if they are in the debt gap, the golden is not the instrument — a corpus
run is. *(genomic-alteration-profile dry-run, gap 3.)*

---

## Probe 1 — Consumer-reads-field  *(the dominant mode, ~half of findings)*

For every field the card computes, **name the downstream consumer** (verdict /
display card / risk rollup / claim-vector / another skill) and confirm it
*reads that field* — not merely that the field exists.

- **Instrument:** the field-disposition ledger (#1506) + reach classifier
  (#1509). `test_field_disposition_complete.py` tells you a field is *declared*;
  it does not tell you a consumer *reads the grade*.
- **Signature:** a graded field exists but the consumer keys on a blunter
  sibling — e.g. risk rollup gates on `sc_normal_expression_class` (94%
  saturated) instead of `sc_normal_essential_veto_grade` (#1531); a headline
  never projects the field that *drove* the verdict (#1530); a first-match
  `*_class` selector means the graded field can *never* win (#1531
  `_primary_class_value`).
- **Fix shape:** point the consumer at the graded field, and add a guard so a
  *new* consumer can't reintroduce the gap. **Fix the pattern, not the
  instance** — see the note below.

## Probe 2 — Grade-not-boolean

Where a field has both a blunt class and a graded/veto version, verify **no**
consumer gates on the blunt one.

- **Signature:** a boolean/HIGH-LIABILITY class stands in for a 0–N veto grade,
  over- or under-penalizing (validated ADC antigens over-penalized, #1531).
- Special case of Probe 1; called out separately because the blunt field is
  often *also* read correctly elsewhere, so the bug hides among green reads.

## Probe 3 — Fire-rate ≠ verdict-rate

For every label/flag/rule, measure **how often it fires** vs **how often it
moves a verdict**.

- **Signature:** a `verdict_bearing` tag that actually means "fired ≥1 rule"
  rather than "changed the verdict" (#1526-F1 — a cell-line card tagged
  verdict-bearing though absent from every `_MEASUREMENT_RANK`); a conjunctive
  label that is inert-by-corpus (green because it never fires, not because it's
  right).
- **Instrument:** run the corpus and count fires vs verdict deltas per rule.
  A predicate that fires 468× and drives 69× is not a verdict.

## Probe 4 — Absence direction

For every guard, ask: does missing / null / underpowered fall **open** (pass,
full-weight, confident) or **closed**?

- **Signature:** underpowered → *confident* is the trap — narrow-purity data
  yields a confident `purity_independent` scored as clean agreement instead of
  ABSENT (#1523); a `malignant_subset_detected` that fires no ladder rung reads
  as `data_unavailable` (#1516-F2); an EPMC-only retriever collapses to
  unverified on a transient outage (#1003).
- **Cross-check the four card states** (`DEFINITION_OF_DONE.md`):
  `informative` / `data_unavailable` / `measured_negative` / `not_in_scope`
  must not be conflated — a real negative silently becoming "unavailable" is a
  fail-open.
- **State the fail-open *direction* per gate — it is not always "demote."** The
  selectivity/safety examples above fail open by *passing a HOLD*. But a skill
  whose risk concentrates at the **top** of the ladder and has no clamp layer
  (genomic-alteration-profile) fails open by *promoting* — an unhandled absence
  can lift a target rather than clear a veto. Ask which direction is dangerous
  for *this* gate before judging the absence handling. *(genomic-alteration-profile dry-run, gap 4.)*

## Probe 5 — Datum fully used

For every *accurate* datum: is it read **symmetrically** (not one-way rescue),
and does it feed a **verdict** or only a display?

- **Signature:** ProCan protein used only as an upward rescue, so
  Gygi-high/ProCan-low discordance is invisible (#1514); CPTAC tumor-protein
  consumed for display but excluded from the abundance floor (#1512);
  `tce_antigen_escape_class` surfaced in the claim vector but read by no
  downstream verdict (#979); `rna_high_protein_low_fraction` computed and read
  by nobody (#1526-F3).
- The deliverable is an accurate, fully-utilized **data package**, not just a
  verdict: "verdict-inert" is not "skip it" — ask *is this datum right, and used
  to its fullest?*
- **Triage first — most verdict-inert fields are by design.** A skill's display
  surface (question table, narrative, headline, context axes) is legitimately
  verdict-inert. Before flagging, ask: *is the verdict-inertness declared and
  justified in the card/SKILL, or is a verdict-relevant datum silently stranded
  in display?* Only the latter is a finding. On a data-package-heavy skill this
  probe over-fires without the triage step. Genuine hits look like an
  asymmetry (RNA critical-organ liability verdict-inert while its protein
  sibling is verdict-bearing) or a datum that catches an archetype the verdict
  spine misses. Compare sibling *facets* too, not only sibling *modalities* —
  three prognostic cards can each get a first-class claim axis while a fourth
  gets none.
- **Sub-probe — dispatched card with no structured surface (narrator-only).**
  "Declared verdict-inert" is not the end of triage: for every card in
  `cards_used`, name the *structured* surface that carries its key field — a
  claim axis, a question-table row, a synthesis-facet key, or a subgroup input.
  A card that is loaded and dispatched (paying real cost) but whose only
  consumer is the LLM **narrator's free-text raw-summary** read is a utilization
  gap even when inertness is declared. In differentiation-landscape,
  `stemness-context` / `alteration-clinical-association` /
  `subtype-survival-association` are dispatched and declared inert, yet their
  fields reach no claim axis / question row / facet key — only narrator prose,
  while sibling prognostic facets each get a first-class axis. The triage
  clause above waves these through; this sub-probe catches them. *(differentiation-landscape dry-run, gap 1.)*
  - *Tie-break for flat headline lifts:* a card whose field lands only as a flat
    `_HEADLINE_FIELDS` scalar (structured, but not a claim axis / question row /
    facet key) is a **weak** surface — treat it as narrator-adjacent and lean on
    the sibling-asymmetry test rather than the surface list to decide if it's a
    gap. *(genomic-alteration-profile dry-run, gap 2.)*
- **Cost note — on data-package-heavy skills, spot-check, don't exhaust.** A
  mostly-display skill (immune-context: ~20 loudly-declared verdict-inert
  fields, zero hits) makes a field-by-field Probe 5 pass expensive for near-zero
  yield. Scan for *asymmetries* (a field verdict-bearing in one modality/sibling
  but not another) rather than walking every inert field. *(immune-context dry-run, G5.)*

## Probe 6 — Anchor / floor validity

For any level, floor, threshold, or anchor: is it **biased for the prioritized
target class**?

- **Signature:** Gygi whole-cell-lysate TMT systematically under-reads
  membrane/secreted proteins — exactly the ADC/TCE class the framework
  prioritizes (EPCAM 8.6%ile, CEACAM5 3.75%ile, #980); a single-cohort negative
  scored at full weight because concordance ignores `n_cohorts_tested`
  (#1513-F1); a flat matched-adjacent RNA arm downgrading selectivity where
  normal tissue also expresses the target (#978).
- **Discipline:** validate on a **panel/backtest**, never a single motivating
  example (don't overfit to a single motivating case). A floor from
  truncated data is *biased*, not noisy, when truncation correlates with the
  measurand.
- **Mitigation triage (mirror of Probe 5) — a biased anchor is only a finding
  if the bias is *unhandled*.** Before flagging, ask: *is the bias disclosed and
  counter-instrumented?* immune-context's CD8-fraction Q1/Q3 anchors are
  biased-by-construction but disclosed + countered by a reference-frame scalar,
  a rank caveat, and the corroboration ruler — so the signature fires cosmetically
  but there is no defect. Distinguish "biased and hidden" (finding) from "biased,
  disclosed, and countered" (by design). *(immune-context dry-run, G2.)*

## Probe 7 — Display-projection internal correctness

Probes 1–6 treat display code as a *wiring endpoint* ("does the verdict read
it?"). But a verdict-inert projection can still be **internally wrong** — and
because it moves no verdict, no golden/parity guard catches it.

- **Signature:** a claim-vector corroboration whose docstring promises a cap
  ("cap at `moderate` — a black-box hit is never high-corroboration") while the
  code never calls the cap (OTS `safety_claims.py` `_pharmacovigilance_corr`);
  harmless today only because the values happen to rank below the cap, so a
  future edit relying on the promised behavior breaks silently.
- **Check:** where a display projection has non-trivial internal logic
  (caps, fallbacks, precedence, order-dependent first-match), verify the code
  matches its own stated contract — the same read-the-consumer discipline as
  Probe 1, applied to the projection's *own* logic, not its inputs.
- **Sub-clause — display-vs-display drift (one-source rule).** Enumerate every
  surface that *recomputes a shared fact* and assert they derive it from one
  source. immune-context's confirmation-caveat `reason` tiers off TIL only,
  while the confidence ruler treats spatial `excluded` as a contradiction — so
  a TIL-corroborated / spatially-excluded case shows `orthogonally_corroborated`
  next to a `weak+conflict` confidence. A skill that added a "cannot drift"
  guard for some surfaces can still reintroduce drift on a *new* parallel
  surface the guard doesn't cover. *(immune-context dry-run, G1.)*
- *(Base probe added from the on-target-safety-liability dry-run.)*

## Probe 8 — Multiple verdict spines & conjunctive gates

Probes 1–6 implicitly assume **one** verdict per skill. Skills often carry a
**second spine** (e.g. a scalar resolver verdict *and* a parallel
`*_by_modality` verdict), each reading a *different* field set — a field wired
into one spine can be orphaned in the other.

- **Enumerate every spine and its field set separately.** In OTS the scalar
  resolver reads 8 fired rule_ids; `modality_safety.py` reads a disjoint
  concern/protective/eligibility/disqualifier set from a conditioning
  vocabulary. A card can drive one and be invisible to the other (F2: GTEx
  critical-organ liability drives neither).
- **Audit conjunctive gates for fall-open.** A per-modality eligibility gate of
  the form *eligibility-rule AND all required co-gates AND no disqualifier* can
  fall open when a mislabeled input clears a HOLD (a spurious "activating" role
  on a TSG clearing a WT-loss hold). A conjunctive label may only fire where
  *both* facts hold; the conservative value belongs on the fall-through, or the
  alarming state is reachable by the least evidence.
- **Second shape — same input, divergent *encoding* across spines.** Beyond a
  field orphaned in one spine, watch for the same verdict/input mapped into two
  vocabularies that disagree. immune-context maps a `cold` verdict to
  `bite_tce: opposing` on the rule-signal ordinal surface but to favorability
  `conditional` on the modality-scope surface, so a reader of both cross-skill
  facets sees opposing-vs-conditional for one verdict. Reconcile the encodings
  or route both consumers through one mapping. *(immune-context dry-run, G3.)*
- **Third shape — exact-token gate match makes superset evidence score lower.**
  When a downstream gate (e.g. the nomination gate) keys on an *exact* verdict
  token and the resolver uses priority ordering, a higher-priority token can
  shadow the gate-positive one so that *stronger* evidence earns *less* credit.
  In differentiation-landscape the gate credits only `strong_mutually_exclusive`;
  a target with both strong co-occurring **and** strong mutually-exclusive
  partners resolves to the higher-priority `both_patterns_present` and gets **no**
  supportive credit, while a strictly-weaker mutex-only target does. Check every
  exact-token gate against the resolver's priority order for this superset-penalty.
  *(differentiation-landscape dry-run, B-2.)*
- **Descriptive / forced-single-polarity skills:** if a skill forces one verdict
  polarity always (differentiation is always `neutral`), the polarity-drift arms
  of Probes 7–8 are structurally inert — skip them and focus Probe 8 on
  token-routing into the nomination gate (above). *(differentiation-landscape dry-run, gap 4.)*
- *(Base probe added from the on-target-safety-liability dry-run.)*

## Probe 9 — Verdict-token-set completeness  *(dominant mode on verdict-driving skills)*

Probe 1 asks whether a consumer reads a *field*. Probe 9 asks whether every
consumer that switches on the resolver's **verdict tokens** handles the *whole
vocabulary*. A verdict-driving skill duplicates its token vocabulary across many
consumer-side sets (Python frozensets, gate `when_verdict_in` lists,
selection-verdict maps) — and a token silently omitted from one of them is a
gap that never shows up field-by-field.

- **Method:** enumerate the resolver's full verdict vocabulary once, then
  enumerate **every downstream set keyed on those tokens** and diff each against
  the full vocabulary. A token present in the resolver but absent from a
  consumer set is the finding.
- **Signature:** in genomic-alteration-profile the 19-token vocabulary is
  duplicated across ≥6 sets (`_GA_GOF_DRIVER_VERDICTS`, `_SNV_SELECTION_VERDICTS`,
  `_CN_FUSION_SELECTION_VERDICTS`, the gate's `when_genomic_verdict_in`, …). The
  GoF-veto-escape gate lists only `confirmed_driver`/`multi_class_driver`, so a
  `splice_exon_skip_driver` (a GoF class — the skill's own METex14 motivating
  case) does not get the escape (B-1); recurrent-SNV/splice selection verdicts
  are absent from the addressable-population sets, so those targets fall to
  `undetermined` instead of a stratified prevalence read (B-2).
- **Why it's separate from Probe 8:** Probe 8's superset-penalty is about
  priority *ordering*; this is about set *membership*. On a display-heavy skill
  it never surfaces — there is one thin verdict vocabulary and few consumer
  sets. On a verdict-heavy skill it is the dominant hazard, and a natural place
  for a guard: a test that asserts each consumer set is a deliberate
  (documented) subset of the resolver vocabulary catches the next omission.
- *(Added from the genomic-alteration-profile dry-run, gap 1 — the verdict-driving archetype.)*

---

## The meta-lesson: fix the pattern, not the instance

Two tumor-presence clusters are the *same fix re-filed per consumer/card*:

- **graded-veto bypass** ×3 — fixed for tumor-selectivity (PR#1475), then
  recurred as #1530 (surface headline) and #1531 (cross-evidence rollup).
- **axis-quality grade not honored** ×3 — #1518 fixed it but hardwired
  `is_powered_axis()` to the RNA card_id, so #1519 (cell-line RNA) and #1521
  (protein cousin) had to follow.

When a probe finds a defect: **generalize the fix** (a shared helper, not a
card-id branch) and **add a guard** so the next consumer/card can't reintroduce
it. A recurrence across consumers is the signal that the fix was scoped too
narrowly the first time.

## Scaling checklist per skill

1. Enumerate cards × emitted fields.
2. Run Probes 1–8 per field; tag each finding (DEFECT / DATA-UTILIZATION /
   PIPELINE / ARCHITECTURE) and route by consumer/owner.
3. Cluster findings by probe before filing — file one issue per *pattern×owner*,
   not one per card, when a fix generalizes.
4. If a card forces open-ended investigation not covered by a probe, **add the
   probe to this rubric** rather than investigating from scratch next time.
5. Feed the resulting fixes through `/issue-batch`.

Expect ~30% of a skill's findings to land in *other* skills or shared helpers.
