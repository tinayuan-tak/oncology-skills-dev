# target-profile

**"Give me the full biology + tractability + mutation + prevalence picture of target X in
indication Y, with narrative synthesis."**

`target-profile` is the top-level composed skill. It fans out (in parallel, in-process) to the
14 wired question-answering skills, collects each deterministic sub-verdict, then adds a Tier-3
LLM narrative on top. The rule-fired verdict spine is deterministic and auditable; the LLM only
writes narrative + a high-level recommendation. Every LLM field is tagged
(`_source: llm_synthesized`, `_model_id`, `_prompt_hash`) and stored in schema slots distinct
from the sub-verdicts, so the audit spine is invariant even if the narrative drifts between runs.

> This is the v2 compositional framework, on the trunk `main`. See the [repo README](../../README.md)
> for the four-repo ecosystem, phase model, and the shared resolver spine.

---

## Table of contents

1. [What you get](#what-you-get)
2. [Install as a proper Claude skill](#install-as-a-proper-claude-skill) ← start here
3. [Prerequisites](#prerequisites)
4. [Run it directly (CLI)](#run-it-directly-cli)
5. [Parameter reference](#parameter-reference)
6. [Features](#features)
7. [Output artifacts](#output-artifacts)
8. [Troubleshooting](#troubleshooting)

---

## What you get

Running `target-profile` composes these 14 sub-skills:

| Sub-skill | Answers |
|---|---|
| `tumor-presence` | Is the target expressed in the tumor (RNA + protein, cell-line + patient)? |
| `tumor-selectivity` | Is it tumor-selective vs normal tissue? |
| `functional-requirement` | Is it a genetic dependency (CRISPR + RNAi + lineage)? |
| `mechanism-and-pharmacology` | Upstream/downstream signaling + candidate MoA hooks. |
| `genomic-alteration-profile` | How is it altered — SNV, copy-number, fusion — and which class drives? |
| `differentiation-landscape` | Co-mutation / mutual-exclusivity landscape for patient selection. |
| `tractability-small-molecule` | Is it small-molecule druggable (chemical-genetic)? |
| `surface-modality-fit` | Does surface biology support ADC / TCE biologics? |
| `immune-context` | Is the tumor immune-hot enough (CD8) to redirect a TCE? |
| `on-target-safety-liability` | Germline LoF constraint → safety of a full-KO modality. |
| `target-intrinsic` | Indication-independent molecular dossier (gateless, verdict-inert). |
| `cis-feature-coherence` | locus → expression → dependency coherence (gateless). |
| `combination-and-vulnerability` | SL partners, dual-KO, combo co-targets, resistance (gateless). |
| `translational-readiness` | HCMI patient-derived models, genotype-matched models, PDXE in-vivo drug-response (gateless, verdict-inert). |

It then emits an **executive summary**, **tension analysis** (where sub-verdicts disagree),
**arguments for/against**, a deterministic **recommendation** (`nominate` / `hold` / `veto`), and a
**confidence** tier — as `target_profile.md`, `nomination.json`, `target_profile.html`, and figures.

---

## Install as a proper Claude skill

Install `target-profile` into your local Claude in one of two ways — a **personal-skill symlink**
(just this skill; the convention this repo already uses) or the full **plugin bundle** (this skill +
its 14 sub-skills + utilities). Either way it becomes the `/target-profile` skill: you describe the
target in natural language and Claude runs it for you — you never touch the CLI. The skills also ship
as a Claude Code plugin (`oncology-skills`) published through a local marketplace
(`claude-oncology-skills`) for the bundle path.

### 1. Clone the four repos

The skills are **not self-contained** — they read cards, methods, and manifests from three sibling
repos plus S3 (see [Prerequisites](#prerequisites)). Clone all four to the standard layout:

```bash
cd ~
for r in claude-oncology-skills target-contracts analysis-methods data-catalog; do
  git clone https://github.com/oneTakeda/rnd-computational-biology-oncology-$r.git \
    rnd-computational-biology-oncology-$r
done
cd rnd-computational-biology-oncology-claude-oncology-skills
pixi install                   # build the data-card runtime env
```

> If you clone anywhere other than `~/rnd-computational-biology-oncology-*`, set
> `TARGET_CONTRACTS_ROOT`, `ANALYSIS_METHODS_ROOT`, and `DATA_CATALOG_ROOT` — see
> [Prerequisites](#prerequisites).

### 2. Make the skill visible to Claude

Pick **one** of these. Both make `target-profile` appear as a first-class skill that Claude
auto-invokes (and that autocompletes as `/target-profile`); neither changes how a run executes —
the skill still shells out to `scripts/run.py` against your local clone + AWS.

Claude Code discovers skills from three places: **personal** (`~/.claude/skills/`), **project**
(`.claude/skills/` in the cwd), and **installed plugins**. Confirm any of them worked with
`/skills` (or check that `/target-profile` autocompletes).

#### Method A — personal-skill symlink (simplest; the convention this repo already uses)

Link the skill directory into your personal skills folder. A symlink is preferred over a copy so
the skill tracks the repo as you `git pull` (and `scripts/run.py` resolves its own paths via
`__file__`, so a symlink works unchanged):

```bash
mkdir -p ~/.claude/skills
ln -s ~/rnd-computational-biology-oncology-claude-oncology-skills/skills/target-profile \
      ~/.claude/skills/target-profile
```

This installs **only** `target-profile`. It composes 14 sub-skills *in-process* (Python imports,
not the Claude skill registry), so you do **not** need to symlink those for a run to work — but you
may link any you also want to invoke standalone (e.g. `tumor-presence`, `functional-requirement`).
For a project-scoped install instead, symlink into `<your-project>/.claude/skills/` rather than
`~/.claude/skills/`.

#### Method B — install the whole plugin bundle

Registers `target-profile` **plus** its 14 sub-skills and the utility skills in one step, via the
plugin marketplace:

```
/plugin marketplace add ~/rnd-computational-biology-oncology-claude-oncology-skills
/plugin install oncology-skills@claude-oncology-skills
```

- `oncology-skills` is the plugin name (`.claude-plugin/plugin.json`).
- `claude-oncology-skills` is the marketplace name (`.claude-plugin/marketplace.json`).
- Verify with `/plugin` → *Manage plugins*.

> **Local path vs GitHub.** Either works: the framework is now the repo's default branch, so
> `add oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills` pulls v2. A local path
> is still recommended, because a run needs the sibling repos on disk anyway and a local
> marketplace tracks your working tree rather than a fetched snapshot.

> **Restart** Claude Code (or run `/skills`) after either method so the new skill is picked up.

### 3. Configure AWS + Bedrock once per shell/session

```bash
aws sso login --profile cbg        # S3 data reads
aws sso login --profile cmp-dev    # Bedrock LLM synthesis
export AWS_PROFILE=cbg BEDROCK_AWS_PROFILE=cmp-dev AWS_REGION=us-east-1
```

Claude Code inherits the shell environment it was launched from, so these must be exported before
you start Claude (or set in your project/settings env). See [AWS configuration](../../README.md#aws-configuration).

### 4. Invoke it in natural language

Just ask — Claude extracts `target` + `indication` (and any optional lens) and runs the skill:

- *"Profile KRAS in colorectal cancer."*
- *"Give me the full picture on MET in NSCLC, as an ADC."*
- *"Should we nominate TP53 in COADREAD? Focus on 2nd-line."*

Or invoke the slash command directly: `/target-profile KRAS in COADREAD`.

Claude picks an output dir (default `/tmp/target-profile/{target}-{indication}`), runs
`scripts/run.py`, then reads back `target_profile.md` and presents the executive summary inline.

---

## Prerequisites

| Requirement | Why |
|---|---|
| **Four repos cloned** | This repo + `target-contracts` (cards/rules/schemas), `analysis-methods` (`methods.*` modules), `data-catalog` (manifests + `target_id_resolver`). |
| **`cbg` AWS profile** | S3 reads of derived products under `s3://onc-compbio/…` (account `557690623046`). |
| **`cmp-dev` AWS profile** | Bedrock LLM synthesis, region `us-east-1` (account `888307857004`). Only needed for a full/synthesis run — **not** for `--verdict-only`, `--no-synthesis`, or `--emit evidence-package`. |
| **An interpreter with the card stack + `anthropic`** | A synthesis run needs both the data-card deps (`openpyxl`, `lifelines`, `pyreadr`, `gseapy`) **and** `anthropic[bedrock]`. See the interpreter note under [Troubleshooting](#troubleshooting). |

**Sibling-repo location overrides** (each defaults to `~/rnd-computational-biology-oncology-*`):

```bash
export TARGET_CONTRACTS_ROOT=~/path/to/rnd-computational-biology-oncology-target-contracts
export ANALYSIS_METHODS_ROOT=~/path/to/rnd-computational-biology-oncology-analysis-methods
export DATA_CATALOG_ROOT=~/path/to/rnd-computational-biology-oncology-data-catalog
```

---

## Run it directly (CLI)

`--target`, `--indication`, and `--out` are always required.

### Which mode do I want?

| | **Full run** (default) | **Quick pass** (`--verdict-only`) | **Data package** (`--emit evidence-package`) |
|---|---|---|---|
| **Command** | *(no mode flag)* | `--verdict-only` | `--emit evidence-package` |
| **Deterministic sub-verdicts** | ✅ | ✅ | ✅ |
| **LLM narrative** (exec-summary, tension, recommendation) | ✅ | ❌ | ❌ |
| **Figures** (per-card SVG + composite PNG) | ✅ | ❌ | ❌ |
| **`target_profile.html`** dashboard | ✅ interactive | ⚠️ static, no-JS | ❌ |
| **`nomination.json`** | ✅ | ✅ | ❌ |
| **`target_profile.md`** | ✅ narrated | ✅ narrative-free | ❌ |
| **`evidence_package.json`** | ❌ | ❌ | ✅ (schema-validated) |
| **Needs Bedrock (`cmp-dev`)** | ✅ yes | ❌ no | ❌ no |
| **Byte-identical verdict spine** | — (baseline) | ✅ | ✅ |
| **Use it for** | Sharing a profile with a biologist / committee | CI, iteration, re-runs — only the auditable verdict | Feeding a downstream machine consumer |

The **full run is the default** — omit every mode flag and you get figures, the interactive HTML,
the narrated markdown, `nomination.json`, and provenance in one invocation. The quick pass and data
package skip verdict-inert work; the deterministic verdict spine is **byte-identical** across all
three (guarded by `tests/test_verdict_only.py`). `--no-synthesis` and `--no-figures` are the
individual halves of `--verdict-only` if you want to skip only one.

**Full profile** (fan-out + LLM synthesis + figures + HTML):

```bash
export AWS_PROFILE=cbg BEDROCK_AWS_PROFILE=cmp-dev AWS_REGION=us-east-1
export ANTHROPIC_MODEL=us.anthropic.claude-opus-4-8   # strip any [1m] alias suffix

pixi run python skills/target-profile/scripts/run.py \
    --target KRAS --indication COADREAD \
    --out ~/dev/framework-runs/KRAS-COADREAD-target-profile
```

**Fast, deterministic pass** (no Bedrock, no figures — good for CI/iteration; no `cmp-dev` needed):

```bash
export AWS_PROFILE=cbg
pixi run python skills/target-profile/scripts/run.py \
    --target KRAS --indication COADREAD \
    --out ~/scratch/kras-coadread-verdict-only --verdict-only
```

**Machine-facing envelope** (deterministic, LLM-free `evidence_package.json`):

```bash
export AWS_PROFILE=cbg
pixi run python skills/target-profile/scripts/run.py \
    --target KRAS --indication COADREAD \
    --out ~/scratch/kras-coadread-envelope --emit evidence-package
```

> Write `--out` under `~/dev/…` or `~/scratch/` — `/tmp` is invisible in the SageMaker JupyterLab
> file picker and wiped on restart. Confirm synthesis is real (not degraded) via
> `nomination.json` → `llm_synthesis.executive_summary._source == "llm_synthesized"`.

---

## Parameter reference

### Required

| Flag | Description |
|---|---|
| `--target <GENE>` | Target gene symbol (e.g. `KRAS`). |
| `--indication <CODE>` | Indication / OncoTree code (e.g. `COADREAD`). |
| `--out <DIR>` | Output directory. Created if absent. |

### Output shape & fast modes

| Flag | Verdict-affecting? | Description |
|---|---|---|
| `--emit {nomination,evidence-package}` | No | `nomination` (default) = narrated profile (`nomination.json` + md + html + provenance + figures). `evidence-package` = deterministic, LLM-free `evidence_package.json` envelope (compose-dashboard shape); implies `--no-synthesis` + `--no-figures`. |
| `--verdict-only` | No | Umbrella fast mode: implies `--no-synthesis` + `--no-figures`. Emits the auditable nomination with **no Bedrock call** and no figures. Byte-identical verdict spine. |
| `--no-synthesis` | No | Skip only the Tier-3 LLM synthesis tail (keep figures). |
| `--no-figures` | No | Skip only figure/HTML rendering (keep synthesis); emits a static, no-JS HTML. |

### Optional lenses (verdict-inert — reshape narrative only)

| Flag | Description |
|---|---|
| `--modality <M>` | Post-hoc modality lens. Canonical: `small_molecule`, `degrader`, `adc`, `bite_tce`, `antibody`, `bispecific_non_tce`, `cell_therapy`. Common aliases normalized (`bite`/`tce`/`bispecific` → `bite_tce`, `protac`/`glue` → `degrader`, `car-t` → `cell_therapy`); an unknown token warns and is dropped (never a silent no-op). |
| `--therapeutic-hypothesis "<text>"` | Free-text clinical framing (line-of-therapy, patient state, goal). Reshapes exec-summary + argument priority; sub-verdicts unchanged. |

### Verdict-affecting scope

| Flag | Description |
|---|---|
| `--subtypes <ids>` | Comma-separated molecular subgroup ids (e.g. `MSI_H,MSS`). **Can change the recommendation.** Negative-selection only: a measured, floor-cleared subtype that is *not* a dependency fires the subtype-non-dependence rule → `hold`. Omit for a whole-cohort (backward-compatible byte-identical) profile. |

### Grounded-substrate chain — DEFAULT-ON (needs Bedrock + network; verdict-inert)

Since **v1.2.0** a full nomination run auto-runs the whole `ground → risk → hypothesis` chain in-process
(display-only / verdict-inert / best-effort). This makes a default run call **Bedrock + PubMed** and
**non-reproducible**; opt out with `--no-substrate` (restores the offline, byte-identical run). The chain
is auto-skipped in `--no-synthesis` / `--verdict-only` / `--emit evidence-package`.

| Flag | Description |
|---|---|
| `--no-substrate` | Opt OUT of the default-on chain — restores the offline, network-free, byte-identical run. |
| `--no-ground` / `--no-risk` / `--no-hypothesis` | Granular per-leg opt-outs (skip grounding / the two 6-dim risk reads / the cross-evidence hypothesis). |
| `--ground [AXES]` | Explicit grounding override: run `ground_axis` over the assembled evidence-package → per-axis `grounded_<axis>.json` (escalate-only, PMID-cited). Value: `engine` (default: the engine axes), `all` (+ clinical/commercial), or a comma-list (e.g. `safety,dependency`). Best-effort. Also the default axis set when the chain is on. |
| `--ground-indication <TERM>` | Natural-language disease term for grounding + the 6-dim literature risk read's PubMed retrieval (e.g. `"colorectal cancer"`). Defaults to `--indication`. Affects **only** retrieval, not the verdict spine. Pass this when `--indication` is an OncoTree code (which retrieves almost nothing from PubMed). |

The chain auto-produces `grounded_<axis>.json` + `risk_rollup.json` + `risk_assessment.json` +
`hypothesis.json` in `--out`. An explicit `--grounded-dir` / `--risk-rollup` / `--risk-assessment` /
`--hypothesis` file (below) always **wins** over the auto-produced artifact.

### Display-only integration (render pre-computed sibling artifacts)

| Flag | Description |
|---|---|
| `--risk-assessment <path>` | Render a literature-risk-assessment `risk_assessment.json` 6-dim read as a labeled context-tier HTML panel. Never a verdict input. |
| `--grounded-dir <dir>` | Directory of per-axis `grounded_<axis>.json`; each sub-skill section shows its inline literature findings. Display-only. |
| `--risk-rollup <path>` | Render the deterministic "Risk by category" 5R lead table (modality-conditioned bins; a pure function of sub-verdicts). Display-only. |
| `--hypothesis <path>` | A cross-evidence-hypothesis `hypothesis.json` replaces the LLM exec-summary + tension on the HTML dashboard. Display-only; the deterministic recommendation stays the header top-line. |

### Provenance / instrumentation

| Flag | Description |
|---|---|
| `--release-pin <pin>` | Stamp a data `release_pin` into governance/provenance. Pass-through only (not auto-resolved); absent this flag the pin records as `unpinned`. Verdict-inert. |
| `--profile-timers` | Emit per-sub-skill READ vs FIGURE-EMIT wall-clock timings to stderr. Instrumentation only. |
| `--allow-degraded-data` | Escape hatch: skip the data-access STS preflight. By default a run whose AWS identity is **not** the onc-compbio account aborts non-zero (else every card read comes back empty → all-`insufficient`, exit 0). Pass only for an intentional cache-only/offline run. (env `TARGET_PROFILE_SKIP_PREFLIGHT=1` is equivalent.) |
| `--ab-suppress-fragility-prompt` | A/B control arm: suppress the certainty block in the synthesis prompt only. Verdict-inert; not for production. |

---

## Features

- **Deterministic verdict spine.** Every sub-skill resolves its verdict through the shared
  `resolve_verdict_for_gate` resolver reading declarative ladders in `target-contracts`.
  `target-profile` *inherits* those verdicts — it never recomputes. The LLM adds narrative only.
- **Gateless sub-skills.** Five shorts are absent from the kill/hold gate map: `expression`
  (tumor-presence), `immune-context`, `target-intrinsic`, `cis-feature-coherence`,
  `combination-and-vulnerability`. They surface in `sub_verdicts` + synthesis but never force a
  nominate/hold/veto. `target-intrinsic` and `combination-and-vulnerability` are additionally
  descriptive (`verdict=None`).
- **Byte-stable fast modes.** `--verdict-only` / `--no-synthesis` / `--no-figures` skip
  verdict-inert work; the deterministic spine is byte-identical to a full run (guarded by
  `tests/test_verdict_only.py`).
- **Offline figure seam.** During fan-out each card's `plot_data` is persisted under
  `figures/cards/…`; emitters render from saved data, not a second live read. Figures are
  verdict-inert and best-effort (a render failure logs a WARN and continues).

---

## Output artifacts

A full run writes into `--out`:

| File | Contents |
|---|---|
| `target_profile.md` | Narrative report — LLM exec-summary/tension/recommendation + rule-derived sub-verdict tables. |
| `nomination.json` | Structured profile: `sub_verdicts` + LLM output + provenance (the auditable spine). |
| `target_profile.html` | Single-page dashboard: per-sub-skill sections, Plots \| Evidence \| Rules tabs, LLM narrative. |
| `figures/` | Per-card SVG + `.plotly.json`, the composite `target_profile_at_a_glance.png`, provenance. |
| `provenance.yaml` | Audit anchor (inputs, artifacts, release pin). |
| `run.log` | Timestamped tee of stdout+stderr (fan-out, gate firing, Bedrock call, warnings). Always written. |

`--emit evidence-package` instead writes a single `evidence_package.json` (validates against
`target-contracts/schemas/evidence_package.schema.json`); no md/html/nomination.

---

## Troubleshooting

- **Run aborts with a preflight / STS error.** Your AWS identity isn't the onc-compbio (`cbg`)
  account. Run `aws sso login --profile cbg && export AWS_PROFILE=cbg`. For an intentional
  offline run, pass `--allow-degraded-data`.
- **Crashes at the synthesis tail / `anthropic` ImportError.** The CI-tested `pixi` env ships the
  data-card stack but **no `anthropic`**. Either add `anthropic[bedrock]` to the pixi env, or run
  under an interpreter that has both the card stack (`openpyxl`, `lifelines`, `pyreadr`, `gseapy`)
  **and** `anthropic[bedrock]`. A mismatched env silently drops cards and can flip a sub-verdict.
  To skip synthesis entirely, use `--no-synthesis` or `--verdict-only`.
- **Bedrock call 400s.** Export *frozen* credentials (the Bedrock SDK client does not honor
  `AWS_PROFILE`) and strip any `[1m]` alias suffix from `ANTHROPIC_MODEL`.
- **All sub-verdicts come back `insufficient` (exit 0).** Almost always a data-access problem
  masquerading as a real result — check `AWS_PROFILE=cbg` and the preflight; that's exactly what
  the default preflight guards against.
- **Grounding retrieves nothing.** Pass `--ground-indication "<disease name>"` — PubMed searches by
  term, so an OncoTree code (`COADREAD`) matches almost nothing.
- **Output not visible in JupyterLab.** Write `--out` under `~/dev/…` or `~/scratch/`, never `/tmp`.

---

*Owner: ryan.abo@takeda.com · version 1.1.0 · see [SKILL.md](SKILL.md) for the machine-readable
skill manifest and [docs/TARGET_PROFILE_WALKTHROUGH.md](../../docs/TARGET_PROFILE_WALKTHROUGH.md)
for a worked walkthrough.*
