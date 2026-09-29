# Decision Record — Literature 6-Dimension Risk Assessment × the v2 Framework

**Status:** Decided 2026-07-17. **Decision:** literature-based risk assessment
stays in the LLM **synthesis-context layer** — it does NOT become a card, rule,
sub-verdict, or nomination-gate input. This record exists so the tempting
"wire literature into the verdict" integration is not re-proposed without
clearing the bar in §5.

Portable GFM per the `README.md` format rules (no Mermaid/HTML).

---

## 1. What prompted this

`workflow-target-evaluation-onc` (on `main`) produces a literature-based
**6-dimension risk assessment** for a (target, indication) — Biological,
Druggability, Translational, Clinical, Safety, Commercial — each rated
LOW/MED/HIGH, via **ScholarEval** (a deterministic 1–5 scorer over an
LLM-assembled `risk_assessment_facts.yaml`). The question: how should this fit
the v2 compositional framework, whose nomination verdict is rule-gated and
deterministic?

An initial recommendation ("phased A1-starting-as-C": surface literature as a
context lens now, then let the deterministic ScholarEval score fire a hold-only
gate rule once facts.yaml is provenance-tagged) was **pressure-tested by three
independent adversarial reviewers** (decision-science, framework-purity,
provenance/reproducibility). It was **refuted**. This record captures the
corrected conclusion and the rationale.

## 2. The seam that made it tempting

`skills/target-profile/scripts/run.py :: _risk_by_category_from_sub_verdicts`
already renders the same 6 categories, and **4 of 6 (translational, clinical,
safety, commercial) are hardcoded `insufficient_evidence` placeholders** — 3 of
which (translational, clinical, commercial) have *no possible primary-data
source*. Literature looks like the obvious way to fill them. It is not.

## 3. Why literature must NOT enter the verdict (the refutation)

Five findings, each grounded in code, converged across the reviewers:

1. **Factual disqualifier — the "deterministic score" for the target categories
   does not exist.** ScholarEval scores 8 dimensions
   (`scoring_engine.py::evaluate_target`, ~L646-723;
   `configs/scoring_rules.yaml:212-260`). **`commercial` and `translational` are
   not among them.** Their LOW/MED/HIGH comes solely from an LLM-authored
   free-text field in facts.yaml. So "wire the deterministic score for the
   categories primary data can't reach" rests on a score that isn't computed.

2. **Provenance ≠ reproducibility.** The facts.yaml-producing LLM calls run at
   **temperature 1.0 with no seed** (`synthesize_facts.py:452`,
   `extract_claims.py:183`). A `_prompt_hash` (invariant over
   system+user+tool+model) therefore decorates a value that **drifts run-to-run**,
   manufacturing the *appearance* of the framework's byte-identical determinism
   contract (`schemas/target.schema.json:93`) while delivering none of it. Tagging
   records *who said it*, not that it is reproducible.

3. **The framework already has a governance gate for this, and literature fails
   it.** `vocabularies/data_mode.enum.yaml` defines `citable_in_nominations`.
   Literature is unpinnable — the PubMed query (`pubmed_search.py:149-161`) has no
   date bound, no corpus lockfile, and `sort=relevance` drifts server-side. In the
   framework's own taxonomy that is **`exploratory`-grade →
   `citable_in_nominations: false`**. Gating on it routes around the control built
   for exactly this tension.

4. **The decision was already made, in writing, in the target file.**
   `_risk_by_category_from_sub_verdicts`'s docstring: *"the v1 risk-assessment
   framing lives here as an output convention, **not as a re-derivation via
   literature**."*

5. **"Context lens, no verdict impact" is a fig-leaf (the F2 attention-mediated
   shift the framework already named).** Placing LLM-authored LOW/MED/HIGH in the
   6-category table — which sits above the recommendation and is fed to the
   synthesis LLM (`_build_user_prompt`) — moves both committee conviction and the
   LLM narrative through a channel the deterministic gate does not record. Guard
   rails #4/#5 (`FRAMEWORK_OVERVIEW.md`) forbid conflating data and judgment in one
   verdict-adjacent artifact.

Additional decision-science findings: **hold-only is miscalibrated both ways** —
too weak for a genuine clinical de-validation (a real NO-GO) and too strong for
commercial (an asset/program property, not target biology, LLM-guessed from a
market with no data feed — `run.py` placeholder literally notes "Cortellis/IQVIA
not licensed"); and the **null-as-MEDIUM** fallback (`scoring_engine.py:711-723`)
scores absence-of-literature as a measured 3.0/MEDIUM at ~35% of the total,
violating the measured-negative-vs-null discipline.

## 4. The decision

- **Literature risk assessment → LLM synthesis-context layer only.** Feed the
  ScholarEval summary into `target-profile`'s `_build_user_prompt` as a labeled
  context block. The synthesis LLM may *reason about* literature risk in the
  narrative; the deterministic nomination gate stays literature-blind. This is a
  one-file, invariant-preserving change (deferred; not built by this record).
- **Do NOT merge LLM-authored levels into the deterministic 6-category table.**
  Keep the honest `insufficient_evidence` placeholders. If literature risk is
  displayed, render it in a **visually separate, explicitly-labeled "literature
  context (non-reproducible, as-of-DATE)" block** — never under the deterministic
  grid's uniform grammar.
- **No card, no rule, no sub-verdict, no gate entry for literature** at this time.

## 5. The bar to ever make literature verdict-affecting

If verdict-impact is later pursued, the ONLY defensible candidate is a
**`clinical_validation` NO-GO** (it is deterministically scored; a well-powered
mechanistic de-validation in the exact indication is a legitimate cross-target
veto). `commercial` and `translational` are permanently out of the gate. And ALL
of these preconditions must first be met:

1. **Pin the corpus** — PMID set + `mindate/maxdate` + a lockfile-equivalent, so
   facts.yaml earns a real content-pin (a `date` stamp is not a pin).
2. **Determinism at the source** — temperature 0 + fixed seed (or capture the
   sampled output as the pinned artifact) so `_prompt_hash` and the value co-vary.
3. **Null ≠ MEDIUM** — route the placeholder dimensions to an explicit
   `not_assessed`/inadmissible state the gate refuses, mirroring the subtype-fit
   `subgroup_n_floor_met` floor.
4. **Drop commercial + translational** from any gate path until a real,
   licensed market/translational data source is ingested.
5. **Staleness TTL** — a refresh/expiry mechanism so a nomination cannot cite a
   silently-stale literature assessment.

Absent all five, a literature "score" is deterministic arithmetic over an
irreproducible, drifting, partly-unsourced input — and a `_prompt_hash` makes
that harder to see, not easier.

## 6. What this does NOT preclude

- Running the standalone `workflow-target-evaluation-onc` risk assessment as its
  own deliverable (it is a valid, self-contained artifact with its own audit
  trail).
- Feeding its summary into the synthesis prompt as context (§4) when that
  one-line change is prioritized.
- Fixing two incidental issues found during review: (a)
  `_risk_by_category_from_sub_verdicts` hardcodes `safety → insufficient_evidence`
  even though the safety sub-skill (gnomAD) is wired and feeds the gate — the
  reshape is stale relative to the gate; (b) the ScholarEval null-as-MEDIUM
  fallback should map to `insufficient` regardless of integration.

## Cross-references
- `FRAMEWORK_OVERVIEW.md` — the framework invariants this record upholds
  (determinism-to-the-gate, signal grammar, guard rails, LLM synthesis layer).
- `vocabularies/data_mode.enum.yaml` — the `citable_in_nominations` control.
- `vocabularies/nomination_verdict_gate.yaml` — the one-directional gate + curation
  principle (why subtype/killer signals are hold/veto-only).
- `skills/workflow-target-evaluation-onc/` (on `main`) — the literature risk
  assessment + ScholarEval scorer described here.
