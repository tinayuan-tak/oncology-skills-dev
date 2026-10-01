# LOOP.md — running the subskill iteration loop end-to-end

The per-subskill **iteration loop on real data** (epic SK#2303). It constructs a coverage-aware batch of
`target × indication` triples, runs ONE focused subskill fresh (`--emit-envelope`), runs a validated
**triangulation judge** + regression **probes** over the emitted L1→L3 property layers, **containment-
guards** every finding, routes it by **tier** (propose / adjudicate), appends it to a hash-chained
**ledger**, and decides **convergence** on a hash-fixed held-out roster.

This file lets a fresh session run one iteration unaided. Read it top to bottom once; the command block
in §3 is the whole loop. The parts are documented in their own modules' docstrings and tested in
`eval/loop/tests/`.

---

## 0. Hard boundaries (carried from every part — do not relax)

- **Propose-only / STOP-A.** The loop NEVER edits code, moves a threshold, mutates a verdict, or lands a
  change. Its entire output surface is a findings ledger + tier-routed proposals for a human. The
  orchestrator's `teeth_green` flag defaults **False** ⇒ every finding is reported at T2/T3, nothing
  reaches T1 (auto-land) until the judge planted-defect teeth (#2357) + the containment guard (#2356) are
  CI-confirmed green and a reviewer passes `--teeth-green`.
- **Index on the property layers (L2a / L2b / L3), NEVER the verdict** (SK#2091). Nothing keys, diffs,
  gates, or routes on `synthesis.verdict` / `driving_rule_id`. A verdict change is evidence of neither a
  defect nor correctness.
- **NULL-blocking convergence.** A dead/degraded held-out package (`substrate.null_everything` ⇒ the
  judge is `skipped`) or a probe `not_evaluable` can NEVER read as "clean" — SKIP ≠ PASS. A dead package
  emits zero findings, so the NULL-block (not the finding count) is what stops a dead batch from reading
  as converged.
- **Frozen-symbol denylist forces T3.** A finding whose prose or `datum_refs` names a threshold, enum
  value, or identity key in `frozen_symbols.yaml` is forced to adjudication regardless of how additive it
  looks (`tiers.touches_frozen_symbol`).
- **Verdict-blind, confabulation-proof findings.** A finding is a structural L1-L3 proposal that must
  cite the raw datum it rests on; the containment guard re-verifies every `datum_ref` against the RAW
  island + the field's contract before it may route (so a judge misread of a correct-by-contract field,
  e.g. `corroboration:high` = independence-agreement not strength, is DROPPED).

---

## 1. Pick the skill (which skills the loop can run on today)

Pick a skill with a landed L2a `property_catalog` that emits the bounded envelope under
`--emit-envelope`. As of this writing:

| skill (dir) | property_catalog | L2a | L2b island | `l3d`? | applicable probes |
|---|---|---|---|---|---|
| `tumor-presence` | tumor_presence.yaml | ✔ (6) | 5 families | **✔** | C1 **+ CALIB** |
| `functional-requirement` | dependency.yaml | ✔ (6) | `crispr_rnai_essentiality_concordance` | ✗ | C1 |
| `on-target-safety-liability` | safety.yaml | ✔ (8) | `normal_liability_concordance` | ✗ | C1 |

- **The loop's value is on IMMATURE skills gaining L2a/b during Wave-1, not re-auditing mature ones.** The
  pilot proved the deterministic probes yield ~0 on a mature skill (tumor-presence L2b was clean); the LLM
  judge is the discovery core. So the first real iterations target **dependency / safety** (post-L2a),
  not tumor-presence.
- **`cis-feature-coherence` is NOT a loop target** — it deliberately emits no L2a (`source_properties` /
  `local_composites` omitted by design); keep it only as the probe-**applicability** case.
- **Probe applicability (`iterate.applicable_probes`).** **C1** (L2b pair-identity vs the governed enum)
  is generic — it runs on any skill with an `integrated_properties` section. **CALIB** (L2a tumor-
  abundance direction) is **tumor-presence-SPECIFIC**: it reads `patient_tumor_abundance` against the
  curated `tumor_presence_controls.yaml` roster, so running it on another skill reports `not_evaluable`
  on every control gene and spuriously NULL-blocks convergence. The orchestrator applies CALIB only for
  `tumor-presence`.

### ⚠️ Known limitation — the `l3d` / run_batch clause-3 tension (surfaced finding, #2360)

`run_batch`'s 4-clause preflight sentinel (WI-A, #2345) requires **all four** envelope sections
(`source_properties` / `integrated_properties` / `local_composites` / `l3d`). Only tumor-presence emits
`l3d` today; **dependency and safety emit 3 of 4** (no within-domain `l3d` story object yet — dependency's
is Wave-2a, safety has none). So `run_batch` marks **every** dependency/safety package `dead` on
`clause3: missing envelope section(s) ['l3d']` — even though each resolves 14-16 cards, fires 12-14 rules,
and produces a real verdict (measured, iter-001).

This does **not** block the loop: the downstream stages key off **`substrate.assemble`** (whose liveness
gate is `n_cards_resolved > 0` / `run_health`, NOT the 4-section check — `degraded`/3-of-4 is a normal
usable state, plan §5A.6), not off `run_batch`'s advisory `usable` flag. `iterate.py` assembles directly
from the emitted packages regardless of the sentinel. **`run_batch`'s sentinel is left as-is** (its
clause-3 is a deliberate, pinned WI-A decision; changing it is an owner call, not this issue's) — treat
its `dead` verdict on a 3-of-4 skill as a liveness **advisory**, read the manifest's per-triple
`n_cards_resolved` / `verdict` / `fired_rules` instead. **Reconciling clause-3 with the Wave-1 targets
(relax it for skills that legitimately emit no `l3d`, or gate it on a per-skill expected-section set) is a
follow-on for the owner** — see the issue thread.

---

## 2. Prerequisites

- `pixi` + `gh` on PATH (after a SageMaker restart: `export PATH="$HOME/.pixi/bin:$HOME/.local/bin:$PATH"`).
- `AWS_PROFILE=cbg` for the onc-compbio data bucket; unset the SageMaker container-credentials override
  (`env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI`).
- **The judge needs Bedrock**: `BEDROCK_AWS_PROFILE=cmp-dev`. The cmp-dev SSO token expires mid-session —
  if a judge call 400s, `aws sso login --profile cmp-dev` and re-run (the judge is per-package, so
  `iterate.py` can be re-pointed at the same `--run-dir` without re-emitting).
- **Interpreter: use pixi** (`eval/ITERATION_RUNBOOK.md`'s "use /opt/conda" line is stale/inverted —
  conda lacks `onc_methods` post-#2257). Run `run_batch` under pixi; it re-execs itself under
  `pixi run python` unless `RUN_BATCH_SKIP_PIXI_REEXEC=1`.
- **Never run `pixi` with cwd inside a `/tmp` worktree** (it deep-copies a multi-GB env → ENOSPC). To run
  loop code that lives in a worktree, invoke from the **home checkout** against the worktree's script
  path: `cd ~/rnd-computational-biology-oncology-claude-oncology-skills && pixi run python /tmp/wt/<wt>/eval/loop/<script>.py …`.
- Concurrency: `run_batch --jobs` default 3, **ceiling 4** (6-wide reboots the no-swap host).

---

## 3. The loop, end to end (the whole thing)

Three commands: emit a batch, construct the coverage-aware roster + split, run one iteration. (Here with
`$REPO` = the home checkout and `$SKILL = functional-requirement`.)

```bash
cd "$REPO"
export PATH="$HOME/.pixi/bin:$HOME/.local/bin:$PATH"

# ── (A) run_batch — emit one skill's --emit-envelope package per triple (#2345) ──────────────────
# roster.json: [["KRAS","COADREAD"], ...]. Output: <runs-root>/iter-NNN-<sha>/_emit__<t>_<i>/ (package)
env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \
  pixi run python eval/loop/run_batch.py --skill functional-requirement \
    --roster roster.json --jobs 3 --runs-root eval/loop/runs

# ── (B) batch_constructor — coverage-aware roster + deterministic dev/held-out split (#2348) ─────
# coverage.v1.json (candidate_key -> [[family,token],...]) is DERIVED from the (A) packages;
# required_pairs.v1.json is the governed L2b token roster the batch should cover.
pixi run python eval/loop/batch_constructor.py \
  --candidates-tsv eval/loop/batches/dependency/roster.v1.tsv \
  --seed-tsv       eval/loop/batches/dependency/roster.v1.tsv \
  --coverage-json  eval/loop/batches/dependency/coverage.v1.json \
  --required-pairs-json eval/loop/batches/dependency/required_pairs.v1.json \
  --skill functional-requirement --batch-id dependency-001 --salt dependency-2360 \
  --held-out-fraction 0.34 --min-per-stratum 1 --target-min 6 --target-max 6 \
  --out-roster eval/loop/batches/dependency/batch-001.v1.tsv \
  --out-spec   eval/loop/batches/dependency/batch-001.v1.json

# ── (C) iterate — substrate → judge → containment → ledger+tiers (dev); probes → convergence (held) ─
# propose-only (NO --teeth-green) until the teeth + containment guard are CI-green and a human reviews.
env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg BEDROCK_AWS_PROFILE=cmp-dev \
  pixi run python eval/loop/iterate.py --skill functional-requirement \
    --batch-spec eval/loop/batches/dependency/batch-001.v1.json \
    --run-dir eval/loop/runs/iter-NNN-<sha> \
    --out-dir eval/loop/iterations/dependency/iter-001 --iteration-id iter-001
```

`iterate.py` locates each triple's emitted package at `<run-dir>/_emit__<target>_<indication>/`
(`run_batch`'s layout — the `decision.json` carrying `run_health` lives there), so (A) and (C) share the
`--run-dir`. (C) consumes the (B) batch spec for the roster + dev/held-out split; the DEV split feeds the
ledger + tiers, the HELD-OUT split feeds convergence.

### What (C) emits (committed records of the iteration)

- `iterations/<skill>/iter-NNN/findings_ledger.json` — the append-only, hash-chained, deduplicated
  ledger of CONTAINED findings (verify with `python eval/loop/findings.py <ledger>`).
- `iterations/<skill>/iter-NNN/iteration_report.json` — roster split, per-package judge/containment
  counts + probes, the tier report, and the convergence report.

The emitted packages under `runs/` are **gitignored** (large, live-derived, re-emittable from the
committed batch roster). The batch spec + ledger + report ARE committed — a durable, point-in-time record
of the iteration (like `eval/CASE_LOG.md`), **not** a test golden: the judge is an LLM sample and is not
byte-reproducible, so no test asserts against these files.

---

## 4. Reading the outputs / when to act

- **`dev.tiers`** — `{T1_land, T2_propose, T3_adjudicate}`. With `teeth_green=False`, `T1_land` is always
  0. **T2** = propose-only issues a human triages; **T3** = adjudication packets (a frozen symbol, or a
  change-an-existing-read kind: `divergence` / `class_not_supported_by_datum`). **Do NOT auto-apply any
  tier.** A real finding becomes a card/rule/method change only through the normal channel after a human
  adjudicates it (see `eval/ITERATION_RUNBOOK.md` §3).
- **`held_out.convergence.converged`** — True only when, across `hysteresis_n` (default 2) consecutive
  held-out runs on the SAME hash-pinned roster, every package is alive and the judge + probes emit ZERO
  surviving findings. A first iteration on an immature skill is expected to be `False` (findings
  outstanding) — that is the loop WORKING, not failing. `latest_block_reasons` says why.
- **`ledger.chain_ok`** must be True. A False means the ledger was tampered/reordered — stop and
  investigate.
- **probes** — an empty probe list on a held-out package is the regression floor's "true zero" (clean),
  NOT an absence of effort. A `not_evaluable` is a framework-coverage gap and blocks convergence.

To iterate toward convergence: land the adjudicated fixes through the card/rule/method channel, re-emit
(A) at the new SHA, and re-run (C) with the SAME batch spec (so the held-out roster pin is unchanged) and
the SAME `--out-dir` (the ledger RESUMES — a repeat finding collapses by dedup, a fixed one simply stops
reappearing). Convergence is finding-emptiness on the pinned held-out set across the hysteresis window.

---

## 5. iter-001 — the first real iteration (functional-requirement / dependency)

Run 2026-10-01 against trunk `6b6d83b9`, dependency skill 1.11.0 (dependency.yaml L2a landed). The
committed records are under `eval/loop/iterations/dependency/iter-001/`.

- **Roster (`batch-001.v1`)**: 6 triples, coverage **0.75** (3/4 governed
  `crispr_rnai_essentiality_concordance` tokens; `essentiality_assay_discordant` uncovered). Split: dev =
  {KRAS/COADREAD, EGFR/LUAD, MET/LUAD}, held-out = {BRAF/SKCM, WRN/COADREAD, SMARCA2/LUAD}.
- **run_batch**: 6/6 marked `dead` on the clause-3 `l3d` advisory (§1 limitation) — each nevertheless
  resolved 14-16 cards, fired 12-14 rules, produced a real verdict; the loop proceeded via
  `substrate.assemble`.
- **Judge (view A — deterministic L1-L3; no `--literature`/`--synthesize` lanes run)**: **17 findings**
  across 6 packages (9 dev + 8 held-out), **0 dropped, 0 demoted** by containment (no confabulation —
  every finding grounded against the raw island).
- **Tiers (report-only, `teeth_green=False`)**: dev **T2=3, T3=6, T1=0**. Frozen-symbol veto fired as
  designed (findings naming `concordance_class` / `family` / `corroboration` → T3).
- **Ledger**: 9 unique dev entries, hash chain intact.
- **Convergence**: `converged=False` (8 surviving held-out findings) — the honest first-iteration state;
  C1 was clean (`[]`) on every held-out package (governed tokens valid), so convergence blocked on
  judge findings, not on a NULL/`not_evaluable`.

Representative grounded findings (propose-only — recorded, NOT applied):

- **[S1 `class_not_supported_by_datum`] KRAS/COADREAD, `l2a.crispr_essentiality.property`** — the
  `strongly_selective` class rests on `fraction_strongly_dependent=0.0636` (~6% of 1589 lines) and
  `median_chronos_panel=-0.14` (near non-dependent center); propose a human adjudicate whether
  `strongly_selective` overstates a narrow-tail selectivity. *(Touches no frozen symbol → T2.)*
- **[S2 `missing_relationship`] `paralog_buffering` vs essentiality concordance** — a `strong`
  paralog-buffering signal (6/12 paralogs buffering, `strongest_paralog_delta=0.72`) is never related to
  the essentiality concordance island, though strong buffering can attenuate the realized dependency.
  *(Names `family` → T3.)*
- **[S3 `surface_unused_signal`] `dependency_lineage_selectivity` as an unmodeled concordance family** —
  the lineage-selectivity L2a anchors are computed but never surfaced as an L2b family or in an L3
  headline.

These are candidate refinements of the dependency skill's property layers for human adjudication; none
was auto-applied (STOP-A). They are the deliverable of a report-only first run — not a verdict change.
