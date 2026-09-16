# Authoring a Skill

The end-to-end path for adding a new skill to this framework, written for someone who has not
worked in it before. [DEVELOPMENT_GUIDELINES.md](../DEVELOPMENT_GUIDELINES.md) is the reference for
layout and conventions; this document is the order to do things in and the traps in between.

Read [The mental model](#1-the-mental-model) before writing code. Most first-PR review comments in
this repo are not style — they are one of the four ownership rules in that section being crossed.

---

## 0. Day-one setup (do this first, it fails confusingly otherwise)

This repo is one of four siblings that must sit **next to each other on disk**:

```
<parent>/
├── rnd-computational-biology-oncology-claude-oncology-skills   ← you are here
├── rnd-computational-biology-oncology-target-contracts         ← cards, rules, resolvers
├── rnd-computational-biology-oncology-analysis-methods         ← the code that computes numbers
└── rnd-computational-biology-oncology-data-catalog             ← dataset manifests + id resolver
```

```bash
git clone https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills.git
git clone https://github.com/oneTakeda/rnd-computational-biology-oncology-target-contracts.git
git clone https://github.com/oneTakeda/rnd-computational-biology-oncology-analysis-methods.git
git clone https://github.com/oneTakeda/rnd-computational-biology-oncology-data-catalog.git
pixi install   # in claude-oncology-skills; ONE env for the whole repo, siblings as editable path deps
```

> ⚠️ **The sibling roots are hard-coded to `/home/sagemaker-user/…`.**
> [`skills/_skills_common/paths.py`](../skills/_skills_common/paths.py) defines
> `TARGET_CONTRACTS_ROOT_DEFAULT` and `ANALYSIS_METHODS_ROOT_DEFAULT` as absolute paths under
> `/home/sagemaker-user`. If your clones live anywhere else, export the overrides **before** running
> anything, or every verdict lookup fails:
>
> ```bash
> export TARGET_CONTRACTS_ROOT=/your/path/rnd-computational-biology-oncology-target-contracts
> export ANALYSIS_METHODS_ROOT=/your/path/rnd-computational-biology-oncology-analysis-methods
> ```
>
> The symptom is `RuntimeError: <gate> resolver spec missing
> (target-contracts/resolvers/<gate>.resolver.yaml) — the verdict source of truth is absent.` That
> message names the contracts repo, so it reads like a missing spec. Nine times out of ten on a
> fresh machine it is an unset env var pointing `load_resolver` at a directory that does not exist.
> Check `python -c "from _skills_common.paths import target_contracts_root as r; print(r().exists())"`
> first.

Also: after a SageMaker restart, `gh` (`~/.local/bin`) and `pixi` (`~/.pixi/bin`) drop off `PATH`.
Re-export both before running a gate.

---

## 1. The mental model

A skill answers **one** focused biology question about a target in an indication, from evidence it
does not itself produce. Four things own four different jobs, and a skill owns only the last:

| Job | Owner | A skill must NOT |
|---|---|---|
| Compute a **number** | `analysis-methods` (`methods/<name>/`) | do arithmetic on raw data, or add `boto3`/`s3fs` reads |
| Attach a **label** to a number (a threshold, a class) | an **evidence card** in `target-contracts` | hard-code a cutoff |
| Turn fired rules into a **verdict** | a declarative resolver spec, `target-contracts/resolvers/<gate>.resolver.yaml` | hand-roll an `if`-chain |
| **Compose + present**: which cards, which axis, what headline | the skill (this repo) | — |

That split is the whole design. It exists because a threshold buried in a skill's Python is
invisible to review and drifts between skills, whereas a card field and a resolver rung are
PR-reviewable objects that every consumer reads identically. When you feel the urge to write
`if tpm > 5:` in a skill, the answer is a card field.

The resolver is deliberately **not Turing-complete** — see the guardrail note at the top of
[`skills/_skills_common/resolver.py`](../skills/_skills_common/resolver.py). A spec may only
pattern-match over the *set of fired rule IDs* (`when_fired` / `when_any_fired` / `when_all_fired`,
in precedence order). No arithmetic, no thresholds, no lookups. If your verdict needs something the
resolver cannot express, that is the design telling you the missing piece belongs in a card (a
label) or a method (a number).

**Two invariants a newcomer will otherwise break:**

- **Honest absence.** A card that was read but yielded no usable value emits `DATA_UNAVAILABLE` —
  a *decision-useful measured null*. That is a different fact from a card that was never wired, and
  a different fact again from a real biological negative. There are **four** distinct states, and
  conflating any two of them is a correctness bug, not a cosmetic one:
  `informative` / `data_unavailable` / `measured_negative` / `not_in_scope`
  (see [DEFINITION_OF_DONE.md](DEFINITION_OF_DONE.md#cards--skills)). The failure mode is always the
  same direction: "we could not measure it" silently reads as "there is none," which flatters the
  target. Ask of every fall-through branch you write: *if the data were simply missing, which class
  does this land in, and is that the conservative one?*
- **Biology-first verdicts.** The primary output — verdict plus driving `rule_id` — is
  **modality-independent**. Modality (small molecule / ADC / TCE …) is a post-hoc lens applied via
  `--modality`, not an input to the verdict. Exactly one skill is modality-aware in its verdict
  (`tumor-selectivity`, via `verdict_modality_aware=True`) and it is aware because target-contracts
  *declares* per-modality signals on the relevant rules. Do not follow that example without the
  same declaration.

---

## 2. What files a skill actually needs

Copy the **modal** set, not the maximal one. Measured across the 22 skills on the trunk
(2026-09-16):

| File | Skills carrying it | Verdict |
|---|---|---|
| `SKILL.md` | **22 / 22** | **Required.** A directory with a `SKILL.md` *is* a skill — that is what the marketplace-sync guard enumerates. |
| `scripts/run.py` | 19 / 22 | Required for anything that runs. The 3 without are doc-only/dispatch skills. |
| `tests/` | 20 / 22 | Required in practice — CI collects them and `test_ci_covers_all_test_files.py` fails a test file that no CI root covers. |
| `DATA_PRODUCT.md` | 17 / 22 | Required if you emit a data package. The 5 exceptions emit no evidence of their own. |
| `question_hierarchy.yaml` + `questions.yaml` | 13 / 22 (2 more carry `questions.yaml` alone) | Required if your skill is question-scored. **See the trap in §6.** |
| `README.md` | 3 / 22 | Optional. Put the prose in `SKILL.md`. |
| `CONTRACT.md` | **1 / 22** | Optional — `tumor-presence` only. |
| `field_disposition.yaml` | **1 / 22** | Optional — `tumor-presence` only. |

> ★ **Do not copy `tumor-presence` as your template.** It is the most complete skill (2253-line
> `run.py`, 30 test files, plus the two files nothing else has), which makes it the best *reference*
> and the worst *starting point*: you would ship six files no other skill has and a structure you
> cannot justify in review.
>
> **Start from [`skills/immune-context/`](../skills/immune-context/)** — 797-line `run.py`, 11 test
> files, exactly the modal file set. Read `tumor-presence` when you need a specific advanced feature
> (subtype panoramas, claim records, field-disposition ledgers) and copy only that feature.

---

## 3. The path, in order

The order matters: steps 1–2 are in a **different repo** and must land first, because this repo's CI
reads target-contracts' `main`. A skill PR that references a card not yet declared there cannot go
green. (The exception is a SHA-pinned atomic change — ask before attempting it.)

**1 — Declare the evidence card** (`target-contracts`). The card is the contract: its
`outputs.summary_fields` are the *only* field names your skill may read, enforced by
`test_card_field_conformance.py`. Check `~/.claude/wip-registry.md` for an in-flight card refactor
before extending an existing card.

**2 — Declare the verdict as a resolver spec** (`target-contracts/resolvers/<gate>.resolver.yaml`):
an ordered ladder of rungs over fired rule IDs. Precedence *is* the biology — the first matching
rung wins, so put the vetoes above the promotions.

**3 — Create the skill directory** and write `SKILL.md`. Frontmatter needs `name`, `description`
(include the natural-language trigger phrases users will actually type — this is how Claude selects
your skill), and a `composition:` block validated by
[`_skills_common/composition_schema.py`](../skills/_skills_common/composition_schema.py). Its
enumerations are closed sets, so a typo is a hard failure rather than a silent default:

```yaml
composition:
  data_mode: derived_read          # live_read | derived_read | batch_compute | catalog_read
  phase: [A, C]                    # A–K
  cards_used:                      # MUST be a superset of what run.py consumes
    - my-new-card
  rules_scope:
    - my-gate
  synthesis: [rule_engine]         # none | rule_engine | structured_llm
  output_shape: [data_package]     # data_package | target_profile | evidence_package | text_report
  steps_covered: [1, 2, 3, 4, 6]   # ints 1–6
  optional_lenses: [modality]      # modality | therapeutic_hypothesis | subgroup
  status: wired                    # wired | not_wired | partial | deprecated
```

**4 — Write `scripts/run.py` as a thin wiring layer.** Delegate to `run_wired_skill` in
[`_skills_common/dispatcher.py`](../skills/_skills_common/dispatcher.py); it single-sources argument
parsing, card resolution, rule firing, packaging, provenance, and synthesis dispatch. Your file
should be little more than constants plus callbacks:

```python
from _skills_common.dispatcher import run_wired_skill
from _skills_common.resolver import resolve_or_raise

SKILL_NAME = "my-skill"
SKILL_VERSION = "1.0.0"          # must equal the version stamped into provenance (test_version_parity)
CARDS = ["my-new-card"]          # must equal SKILL.md composition.cards_used (test_cards_used_declares_consumed)
QUESTION = "Is {target} ... in {indication}?"

def _verdict(fired):
    return resolve_or_raise(fired, "my_gate")   # never an if-chain

def _headline(cards, fired, verdict_pair):
    ...

if __name__ == "__main__":
    raise SystemExit(
        run_wired_skill(
            skill_name=SKILL_NAME,
            skill_version=SKILL_VERSION,
            cards=CARDS,
            axis="intracellular_intrinsic",
            question=QUESTION,
            verdict_fn=_verdict,
            headline_fn=_headline,
        )
    )
```

Every other `run_wired_skill` parameter is optional and defaults to inert. Add them one at a time,
each with a comment saying why — `immune-context`'s call site is a good model of that style.

**5 — Write the per-skill tests.** Cover the verdict ladder (one test per rung, including the
fall-through), the four absence states, and the headline shape. A resolver or shared-harness change
fans out into golden snapshots across skill dirs, so run the **full** suite, never a `-k` subset.

**6 — Register the skill in `.claude-plugin/marketplace.json` in the same PR.** Append the path to
the `skills:` array of the entry whose `source` is `"./"`.
`skills/tests/test_marketplace_registry_sync.py` asserts *exact set equality* between that array and
the on-disk dirs carrying a `SKILL.md`, so a new skill without a registry line reds the gate —
by design. (Do not add a `skills:` array to the archived `oncology-skills-v1` entry; it resolves its
own from the `legacy/v1` ref.)

**7 — Gate, then land** (§7).

---

## 4. The cross-skill guards *are* the specification

[`skills/tests/`](../skills/tests/) holds 19 framework-level guards. They are more useful than any
prose checklist, because they are the thing that will actually stop your PR. Read the module
docstring of any that fires.

| Guard | What it demands of your skill |
|---|---|
| `test_composition_declarations.py` | `SKILL.md` carries a valid `composition:` block (closed enums). |
| `test_cards_used_declares_consumed.py` | Every card `run.py` consumes is declared in `composition.cards_used`. |
| `test_card_field_conformance.py` | Every summary field you read is declared in the card's `outputs.summary_fields`. Kills silent-`None` drift. |
| `test_resolver_verdict_consumers.py` | Every verdict a resolver can emit is classified by every Python consumer. A *new verdict value* is a fleet-wide change. |
| `test_version_parity.py` | `SKILL_VERSION` equals the version stamped into provenance. |
| `test_graduated_skills_run_wired.py` | `SKILL.md` ↔ `scripts/` have not drifted apart. |
| `test_marketplace_registry_sync.py` | The skill is registered (and plugin/marketplace versions agree). |
| `test_questions_yaml_schema.py`, `test_questions_yaml_hierarchy_agreement.py`, `test_question_hierarchy_drift.py` | The two question files are schema-valid **and agree with each other** (§6). |
| `test_data_product_lock_coverage.py` | Emitted data-product fields are covered by the lock. |
| `test_evidence_graph_invariants.py` | Structural invariants over any `evidence_graph` fixture you ship. |
| `test_ci_covers_all_test_files.py` | Every `test_*.py` lives under a root CI actually collects — a test in an uncollected directory is invisible, not passing. |
| `test_no_reference_drift.py` | Renames are complete: no dangling references to the old name. |
| `test_field_disposition_ledgers.py`, `test_reference_frame_governance.py`, `test_cross_evidence_spine_contract.py`, `test_target_profile_envelope_conformance.py`, `test_reviewer_driven_upgrades.py`, `card_behavior_matrix/` | Apply once you touch shared spine / integrator / reference-frame surfaces. |

---

## 5. Reading data

Skills read **derived products** (gene-sorted parquet, predicate pushdown) through the
`methods/<name>/read.py` readers in `analysis-methods`, which resolve dataset locations via the
data-catalog manifests and the target-id resolver sidecar. Do not add ad-hoc `boto3` / `s3fs`
clients — and never a `verify=False` one — inside a skill. Single-sourcing the readers is what makes
provenance (data source + manifest + method git-SHA) resolvable at all, which
`DEFINITION_OF_DONE.md` requires of every emitted card.

---

## 6. ⚠️ The dual-routing trap: `question_hierarchy.yaml` vs `questions.yaml`

If your skill is question-scored it carries two YAML files that describe the **same** axis:

- **`question_hierarchy.yaml`** — the **scored** structure. What the engine evaluates.
- **`questions.yaml`** — the **displayed** registry. What a reader sees.

Nothing forces a single edit to update both, and they have drifted before — in 9 of 13 skills at
once. Treat them as one edit with two files. Three guards
(`test_questions_yaml_hierarchy_agreement.py`, `test_question_hierarchy_drift.py`,
`test_questions_yaml_schema.py`) exist specifically because of this.

Do **not** file a mismatch as cosmetic on the grounds that it is "display-only." A mis-routed
question has inverted a scored band in this repo before: the displayed text was right, the scored
hierarchy pointed at the wrong rung, and the number moved. If the two disagree, one of them is
wrong and you cannot tell which from the diff alone — check the engine.

---

## 7. Gate it, then land it

Run pytest under `pixi` **from your home checkout**, never from a `/tmp` worktree (pixi deep-copies
a multi-GB environment there → `ENOSPC` and a wedged `/tmp`). To gate code that lives in a worktree,
run from the home checkout against the worktree's paths.

```bash
pixi run pytest skills/<your-skill>/tests/ -q --import-mode=importlib
pixi run pytest skills/_skills_common/tests/ -q
pixi run pytest skills/tests/ -q --import-mode=importlib
```

Then the two gates that actually decide the merge. `main` requires exactly two status checks:
`pytest` (`skills-validate.yml`) and `ruff` (`ruff.yml`).

> ★ **`scripts/preland.sh` mirrors only ONE of the two.** It transcribes the `pytest` job and runs
> **no lint gate at all**, so a green `ALL GATES PASS` does not mean your PR will go green. Run both
> ruff gates yourself, as printed in that script's header — and note `ruff format --check .` is
> **whole-tree**, so it can fail on a file you never touched.
>
> ★ **Redirect `preland.sh` to a file; never pipe it to `tail`.** A piped invocation reports success
> on a failing run. `bash scripts/preland.sh > /tmp/preland.log 2>&1; echo "rc=$?"` then read the log.

Two more counting traps, both of which have produced a false green here:

- **A skipped test is not a passing test.** Run with `-rs` and reconcile the `skipped` column, not
  just `passed`. Live-S3 tests self-skip without credentials by design — but a test that skips
  because of a broken import looks identical in the summary.
- **A baseline is a collected count plus a named list of expected failures**, never a remembered
  total. Collection counts here move without any commit of yours.

Landing:

```bash
~/.claude/git-hooks/new-worktree claude-oncology-skills feat/my-skill --scope skills/my-skill/
# ...work in the printed /tmp/wt/... dir...
git push -u origin feat/my-skill        # ALWAYS -u origin <branch>; never git's suggested HEAD:main
gh pr create --draft --base main --fill
~/.claude/git-hooks/land-pr <pr#> --repo claude-oncology-skills
```

Work in **your own worktree** off `main`, declare `.claude/branch-scope` before the first commit,
open the PR **draft-first**, and claim the workstream in `~/.claude/wip-registry.md` — parallel
Claude sessions run against these repos, and the registry is how they avoid each other. The full
ritual is in [CLAUDE.md](../CLAUDE.md); the completion checklist is
[DEFINITION_OF_DONE.md](DEFINITION_OF_DONE.md).

---

## Further reading

| Document | For |
|---|---|
| [DEVELOPMENT_GUIDELINES.md](../DEVELOPMENT_GUIDELINES.md) | Layout, skill anatomy, branch/test/data conventions |
| [DEFINITION_OF_DONE.md](DEFINITION_OF_DONE.md) | The completion checklist, incl. verdict-bearing changes |
| [UNIFIED_OUTPUT_CONTRACT.md](UNIFIED_OUTPUT_CONTRACT.md) | What an emitted package must contain |
| [HEADLINE_CONTRACT.md](HEADLINE_CONTRACT.md) | Headline block shape |
| [TARGET_PROFILE_WALKTHROUGH.md](TARGET_PROFILE_WALKTHROUGH.md) | How sub-skill verdicts compose into a profile |
| [CLAUDE.md](../CLAUDE.md) | Cross-session coordination, worktrees, landing discipline |
| [`skills/_skills_common/resolver.py`](../skills/_skills_common/resolver.py) | The resolver's guardrails, in its module docstring |
| [`skills/immune-context/`](../skills/immune-context/) | Your starting template |
| [`skills/tumor-presence/`](../skills/tumor-presence/) | Advanced-feature reference — copy features, not the whole shape |
