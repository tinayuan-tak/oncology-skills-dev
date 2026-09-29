# Match-All-Then-Reduce Fold — Design (M4d, ready-to-execute; NOT yet executed)

Status: **DESIGN, unexecuted** (2026-08-25). Companion to
[VERDICT_REPRESENTATION.md](VERDICT_REPRESENTATION.md) (move #6 / R6) and
[VERDICT_REPRESENTATION_MIGRATION.md](VERDICT_REPRESENTATION_MIGRATION.md) (phase M4d). This is the ONE
migration move deliberately delivered as a plan rather than executed inline: it rewrites the shared
verdict engine (`resolvers/*.resolver.yaml` + the interpreter `_skills_common/resolver.py` that BOTH
target-profile and compose-dashboard call, guarded by ~300 golden + golden-oracle tests), so it must
land as a deliberate, one-resolver-at-a-time, calibration-reviewed workstream — not an autopilot sweep.

Everything M0–M2 + the three M4 consumers are already landed and byte-stable; this move changes the
engine's *form*, not (by construction) its *output*.

---

## 1. What the Fold fixes

Today each resolver is an **ordered first-match ladder**: the earliest rung whose fired-set predicate
holds wins. The order is IMPLICIT (positional) and load-bearing — the audit's R6 defect: a rung can be
**silently masked** by an earlier one, and reordering the YAML can silently change a verdict. The
first-match ladder also cannot be reasoned about compositionally (you must read top-to-bottom).

**Goal (R6 → 0):** make precedence EXPLICIT DATA and the evaluation **order-independent** — reordering
rungs must not change any verdict — while producing the *identical* verdict on every input.

## 2. The key that makes it safe — an explicit-priority lattice, byte-equivalent by construction

The Fold does NOT invent a new precedence. It re-encodes the EXISTING one as data:

- Assign each rung an explicit **priority** = its current index in the ladder (0 = highest).
- Evaluation becomes **match-all-then-reduce**: evaluate every rung's predicate against the fired set
  (no early exit), collect the matching rungs, and `reduce` = the matching rung of **minimum
  priority**. Ties are impossible (priorities are a total order by construction).
- `argmin(priority)` over the matching set === the first-match winner of the original ladder. So the
  Fold is **byte-equivalent to the resolver by construction** — not by luck, by algebra.

Order-independence falls out: priority is carried on the rung, so the YAML rung ORDER no longer
affects the result. A reviewer edits *priorities* (visible, diffable) instead of *positions* (silent).

This deliberately preserves the bespoke biology precedence each ladder encodes (e.g. dependency's
"CRISPR beats RNAi", safety's "suppressor before veto", every gate's "killer-first"): those become
explicit priority values, not positional accidents. A naive `max`/`set-union` Fold that *flattened*
precedence would silently change verdicts and is REJECTED for exactly this reason.

## 3. Schema + interpreter changes

- **`schemas/resolver.schema.json`**: add an optional `priority: integer` to each `resolve[]` rung,
  and a resolver-level `evaluation: first_match | match_all_reduce` (default `first_match` for
  back-compat). A `match_all_reduce` resolver MUST give every rung a unique `priority`.
- **`_skills_common/resolver.py`** (skills repo — the shared interpreter both engines call): when
  `evaluation == match_all_reduce`, evaluate all rungs, filter to matches, return the min-priority
  match's verdict (+ its rule_id as `driving_rule_id`); else the existing first-match path. The
  interpreter stays deliberately non-Turing (still only when_fired / when_any_fired / when_all_fired).
- The legacy first-match path is RETAINED as the **oracle** (see §4), not deleted.

## 4. The equivalence proof (the gate, per-resolver)

The resolver golden-oracle tests already **enumerate every rule-combination** against a legacy oracle
(e.g. `skills/_skills_common/tests/test_tractability_sm_resolver_oracle.py`). The Fold migration reuses
that harness verbatim as its acceptance gate:

> for every fired-set combination the oracle enumerates, `match_all_reduce(fired) == first_match(fired)`
> byte-for-byte (verdict AND driving_rule_id).

Because priority = index, this passes by construction; the test makes any hand-edit that breaks it a
hard failure. **No calibration-set replay is needed for equivalence** (it is exhaustive over the rung
combinatorics), but run the ~40-target calibration set anyway to confirm decision.json hashes do not
move.

## 5. Migration — one resolver at a time

Strangler-fig, mirroring the M-phases:

1. **Interpreter + schema** land first (additive; `evaluation` defaults to `first_match`, so no
   resolver behaves differently yet). Gate: full skills suite green.
2. **Per resolver** (10 PRs, any order, independent): add `priority` to every rung + flip
   `evaluation: match_all_reduce`; regenerate the resolver golden; the oracle-enumeration test proves
   equivalence. One reviewed PR each — a domain reviewer confirms the priorities faithfully transcribe
   the biology precedence (this is the only human-judgement step; it is mechanical to check).
3. **Retire the first-match path** to a test-only oracle once all 10 resolvers are `match_all_reduce`.

Rollback at any step: flip `evaluation` back to `first_match` (the path is retained until step 3).

## 6. Cost / value

- **Value:** R6 → 0 (order-independence proven by a permutation test; silent-masking impossible);
  precedence becomes reviewable data. Enables later moves (a resolver could, in principle, emit the
  full matched-set for the factored record's provenance, not just the winner).
- **Cost:** cross-repo (contracts schema/resolvers + skills interpreter), touches the golden-tested
  core, 10 reviewed PRs + interpreter PR. ~1–2 focused sessions.
- **Verdict:** worth doing when order-independence / precedence-auditability is a priority; it is the
  natural precursor to any future FOLD that computes the record's `finding.state` from rules directly
  (the true "retire the ladder"). Until then, the three landed M4 consumers already deliver the
  audit's decision-facing value, so this is **correctly deferred, not abandoned**.

## 7. Non-goals

- No new precedence, no learned combiner, no flattening of biology precedence into a generic
  `max`/`set-union` (would silently change verdicts — see §2).
- Does not change the factored record's shape or any consumer; `render_verdict` is unaffected
  (finding.state is still the winning verdict).
