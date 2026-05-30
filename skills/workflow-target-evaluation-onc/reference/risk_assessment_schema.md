# Risk Assessment Markdown Schema

**Status:** Authoritative. Version 1.0.0. As of 2026-05-28.

This document defines the **required structure** for any
`{GENE}_risk_assessment_{disease}.md` file consumed by the
target-evaluation workflow.

Hand-written compliance is enforced by `scripts/lint_risk_assessment.py`.
Future versions of this workflow (v1.3.0+) will generate this markdown
from a structured `risk_assessment_facts.yaml` input — at which point the
schema becomes a programmatic contract rather than a hand-author guide.

## Required structure

Every risk-assessment markdown MUST contain the following sections in
order. Sections marked **REQUIRED** are linter-enforced; their absence
fails the workflow before downstream tools run.

### Header (REQUIRED)

```markdown
# {GENE} Drug Target Risk Assessment — {Disease}

**Date:** YYYY-MM-DD
**Disease:** {Disease full name}
**Target:** {GENE} ({HGNC ID or alias})
**Modality candidates:** {comma-separated list}
```

### `## Background` (RECOMMENDED, not enforced)

Free-text introduction to the target. Optional but improves the
generated integrated report.

### `## Strategic Alignment Assessment` (REQUIRED)

Must include a `**Whitespace Alignment:**` line listing checkbox-style
selections (`[x]` / `[ ]`) for the disease's iDAS priority whitespaces.

### `## Executive Risk Summary` (REQUIRED)

Must contain a markdown table with EXACTLY these columns:

```markdown
| Risk Factor | Risk Level | Key Considerations |
|---|---|---|
| Biological | **LOW** | ... |
| Druggability | **MEDIUM** | ... |
| Translational | **MEDIUM** | ... |
| Clinical | **MEDIUM** | ... |
| Safety | **MEDIUM** | ... |
| Commercial | **LOW** | ... |
```

**All 6 categories MUST appear** (Biological, Druggability,
Translational, Clinical, Safety, Commercial).

**Risk Level format:** `LOW` / `MEDIUM` / `HIGH` or compound forms
(`LOW-MEDIUM`, `MEDIUM-HIGH`). Bold markers (`**LOW**`) are accepted.
En/em dashes are normalized to hyphens.

After the table, an **Overall risk profile statement** is REQUIRED:

```markdown
**Overall Target Risk Profile: LOW-MEDIUM**
```

### `## 1. Biological Risk Assessment` through `## 6. Commercial / Competitive Risk Assessment` (REQUIRED)

Each of the 6 numbered category sections MUST exist. Each section
SHOULD include:

- A `### Risk Level Criteria` table (optional, copied from template)
- A `### Evidence Documentation` block with structured fields
- A `**Risk Level Assigned:** [x] LOW/MEDIUM/HIGH` checkbox line (RECOMMENDED for cross-validation against Executive Risk Summary)
- A `**Justification:**` line (optional)
- One or more PMID citations in the form `PMID: {6-9 digits}` or `(PMID: {6-9 digits})`

PMIDs in these sections are extracted by the integrated-report parser
to populate the §3.1 Risk Assessment table's "Key Evidence (PMID)"
column.

### `## iDAS Strategic Alignment Assessment` (REQUIRED)

Must contain a `### Whitespace Alignment Score` table:

```markdown
| Priority Whitespace | Alignment | Rationale |
|---|---|---|
| 2L Non-AGA (IO-experienced) | Strong | ... |
| 2L EGFR Mutant (post-TKI) | Strong | ... |
| 1L/2L KRAS Mutant | Strong | ... |
```

Alignment values: `Strong` / `Moderate` / `Weak` / `None`.
Whitespace labels MUST match those defined in
`risk_assessment_template_{disease}.md` for the disease.

### `## Tempus Real-World Evidence (RWE) Analysis` (RECOMMENDED, not enforced)

May include LOT, biomarker, mutation-status sub-tables. Optional —
the integrated-report generator pulls Tempus data directly from the
auto-generated `idas.yaml` and `suitability.csv`.

### `## Subgroup Suitability Analysis` (RECOMMENDED, not enforced)

Same rationale as Tempus RWE — auto-generated outputs are the
authoritative source for the integrated report.

### `## Risk Mitigation Strategies` (REQUIRED)

Must contain EITHER a markdown table OR a numbered list of mitigation
strategies. Table format preferred:

```markdown
| Risk | Risk Level | Mitigation Strategy |
|---|---|---|
| ... | LOW/MEDIUM/HIGH | ... |
```

Numbered list is also accepted (legacy format from earlier templates):

```markdown
1. **Risk title** — Mitigation strategy text
2. **Another risk** — Strategy text
```

### `## Recommendation` or `## Recommendations` (REQUIRED)

Must contain a bolded recommendation phrase that begins with one of:
`GO`, `NO-GO`, `CONDITIONAL`, or `CONDITIONAL NO-GO`. May include a
priority qualifier (`PRIORITY`, `HIGH PRIORITY`, `MEDIUM PRIORITY`,
`LOW PRIORITY`, `MEDIUM-HIGH PRIORITY`).

Examples (any of these is valid):

```markdown
### Overall Recommendation: **GO — MEDIUM-HIGH PRIORITY**
```

```markdown
### Overall: **CONDITIONAL** — biomarker dependent
```

```markdown
**Recommendation:** **NO-GO** — significant safety risks identified
```

The first bolded phrase containing a valid recommendation token is
extracted by the integrated-report parser.

## Common deviations the linter rejects

These are the failure modes observed across PCDH7 and CRBN markdowns:

| Deviation | Linter error |
|---|---|
| Missing `## Executive Risk Summary` table | `[required] Section "Executive Risk Summary" not found` |
| Risk levels only in per-category sections, no summary table | Same as above |
| Summary table missing one of the 6 categories | `[required] Executive Risk Summary missing category: {name}` |
| `## 1. Biological Risk Assessment` heading misspelled or missing number | `[required] Per-category section #N for "{category}" not found` |
| Mitigations section missing entirely | `[required] Section "Risk Mitigation Strategies" not found` |
| No bolded recommendation phrase in Recommendation section | `[required] Recommendation phrase not parseable; expected GO/NO-GO/CONDITIONAL` |
| Whitespace Alignment table missing or malformed | `[required] iDAS Whitespace Alignment table not found` |

## Migration path for legacy markdowns

For any pre-schema markdown that fails lint:

1. Run the linter to see line-level errors
2. Add the missing required sections (typically just the Executive Risk Summary table)
3. Verify lint passes
4. The integrated-report generator can then consume the file

Existing markdowns we know about:
- `PCDH7_risk_assessment_nsclc.md` — schema-compliant as of 2026-05-22
- `CRBN_risk_assessment_crc.md` — needs Executive Risk Summary table added (~10 lines)

## Forward path: v1.3.0+ generator

Once the Step 1 markdown generator lands:

- Analysts populate `{GENE}_risk_assessment_facts.yaml` with structured
  evidence (PMIDs, risk-level votes, iDAS alignment scores, mitigation
  strategies)
- Generator renders schema-compliant markdown deterministically
- Linter remains as a backstop for any legacy/manual edits
- Schema-compliance becomes a property of the generator, not a burden
  on hand-writers
