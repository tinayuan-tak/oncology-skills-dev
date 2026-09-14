---
name: snapshot-generator
description: |
  Generate topic-focused PowerPoint snapshots from target-profile outputs.
  Consumes figures and tables from a completed target-profile run and produces
  presentation-ready PPTX files using a Takeda template. Each snapshot is a
  single slide with multiple panels, where each panel can contain a figure
  (SVG/PNG) and/or a data table (CSV/Parquet).

  NOT a composed skill / not wired into target-profile — a standalone post-processing tool.

metadata:
  version: 0.2.0
  owner: tina.yuan@takeda.com
  environment:
    - DYLD_LIBRARY_PATH=/opt/homebrew/lib  # macOS cairo library path
status: development
---

# snapshot-generator

## Overview

Generates PowerPoint presentation snapshots from target-profile figure outputs. Each snapshot
is a single slide with configurable panels containing figures and data tables, designed for
inclusion in scientific presentations.

## Data Source

### Path Structure

Target-profile outputs are stored in this directory structure:

```
/Users/lhl2999/Library/CloudStorage/OneDrive-Takeda/Documents/ONC_skills/target-profile/
└── {GENE}-{INDICATION}/
    └── {date}__{version}__{hash}/
        └── figures/
            ├── target_profile_at_a_glance.svg
            ├── target_profile_at_a_glance.png
            ├── cards/
            │   └── {card-name}/
            │       ├── figure_*.svg
            │       └── plot_data.parquet
            └── subskills/
                └── {topic}/
                    ├── hero.svg
                    └── tables/
                        └── *.csv
```

### Gene and Indication

The gene and indication are automatically parsed from the path. For example:

- Path: `.../KRAS-COADREAD/2026-09-10__2.0.0__23ad0c5/figures`
- Gene: `KRAS`
- Indication: `COADREAD`

These values are available as placeholders `{gene}` and `{indication}` in slide titles and subtitles.

### Available Figures

Common figure paths (relative to `figures/` directory):

**Overview:**
- `target_profile_at_a_glance.svg`

**Subskill Heroes:**
- `subskills/dependency/hero.svg`
- `subskills/genomic_alteration/hero.svg`
- `subskills/expression/hero.svg`
- `subskills/selectivity/hero.svg`
- `subskills/safety/hero.svg`
- `subskills/mechanism/hero.svg`
- `subskills/tractability_sm/hero.svg`
- `subskills/surface_modality/hero.svg`
- `subskills/differentiation/hero.svg`
- `subskills/immune_context/hero.svg`
- `subskills/cis_coherence/hero.svg`
- `subskills/combination_vulnerability/hero.svg`
- `subskills/literature_context/hero.svg`
- `subskills/target_intrinsic/hero.svg`
- `subskills/translational_readiness/hero.svg`

**Card Figures (examples):**
- `cards/pan-cancer-crispr-dependency-distribution/figure_waterfall.svg`
- `cards/pan-cancer-crispr-dependency-distribution/figure_histogram_kde.svg`
- `cards/mutation-stratified-dependency/figure_mut_vs_wt_strip.svg`
- `cards/mutation-stratified-dependency/figure_per_hotspot_chronos.svg`
- `cards/mutation-type-counts/figure_mutation_class_bar.svg`
- `cards/copy-number-distribution/figure_waterfall_cn.svg`
- `cards/tumor-rna-distribution/figure_expression_distribution.svg`
- `cards/tumor-vs-normal-selectivity/figure_tumor_vs_normal_selectivity_4panel.svg`
- `cards/normal-tissue-liability-gtex/figure_normal_tissue_liability.svg`

---

## Configuration YAML Reference

### Basic Structure

```yaml
# Slide metadata
title: "{gene} Dependency in {indication}"    # Required. Supports {gene}, {indication} placeholders
subtitle: "CRISPR functional dependency"      # Optional
layout: "1x2"                                  # Panel layout: "rows x cols"

# Panel definitions
panels:
  - figure: "path/to/figure.svg"
    table: "path/to/data.parquet"
    caption: "Panel caption"
```

### Layout Options

The `layout` field defines panel arrangement as `"rows x cols"`:

| Layout | Description |
|--------|-------------|
| `"1x2"` | 1 row, 2 columns (side by side) |
| `"2x1"` | 2 rows, 1 column (stacked) |
| `"2x2"` | 2 rows, 2 columns (grid) |
| `"1x3"` | 1 row, 3 columns |
| `"2x3"` | 2 rows, 3 columns |
| `"3x2"` | 3 rows, 2 columns |

### Panel Options

Each panel can contain a figure, a table, or both.

```yaml
panels:
  - # Figure (optional)
    figure: "cards/card-name/figure.svg"      # Path relative to figures/ directory
    
    # Table (optional)
    table: "cards/card-name/plot_data.parquet"  # Supports .csv and .parquet
    
    # Caption (optional)
    caption: "Description of this panel"
```

### Table Configuration

#### Column Selection

Select and order specific columns to display:

```yaml
panels:
  - table: "data.parquet"
    table_columns: ["cell_line_name", "chronos_score", "lineage"]
```

#### Row Selection by Value

Select rows where a column matches specific values:

```yaml
panels:
  - table: "data.parquet"
    table_row_select:
      column: "cell_line_name"
      values: ["PANFR0233", "PANFR0368", "CCLF_CORE_0001_T"]
```

#### Row Filtering with Query

Filter rows using pandas query syntax:

```yaml
panels:
  - table: "data.parquet"
    table_filter: "is_hotspot_mutant == True"
```

More complex filters:

```yaml
# Multiple conditions (AND)
table_filter: "is_hotspot_mutant == True and lineage == 'Bowel'"

# OR conditions
table_filter: "lineage == 'Bowel' or lineage == 'Pancreas'"

# Numeric comparisons
table_filter: "chronos_score < -0.5"

# String contains (use backticks for column names with spaces)
table_filter: "`cell_line_name`.str.contains('PANFR')"
```

#### Sorting

Sort rows by a column before display:

```yaml
panels:
  - table: "data.parquet"
    table_sort_by: "chronos_score"
    table_sort_ascending: true       # true (default) or false
```

#### Row Limit

Limit the number of rows displayed (applied after filtering and sorting):

```yaml
panels:
  - table: "data.parquet"
    table_max_rows: 10               # Default: 10
```

### Complete Panel Example

```yaml
panels:
  - figure: "cards/mutation-stratified-dependency/figure_mut_vs_wt_strip.svg"
    table: "cards/mutation-stratified-dependency/plot_data.parquet"
    table_columns: ["cell_line_name", "chronos_score", "lineage", "is_hotspot_mutant"]
    table_row_select:
      column: "lineage"
      values: ["Bowel", "Pancreas"]
    table_sort_by: "chronos_score"
    table_sort_ascending: true
    table_max_rows: 8
    caption: "Top dependent cell lines by Chronos score"
```

---

## Usage

### Prerequisites

```bash
# macOS: Set library path for cairo (SVG rendering)
export DYLD_LIBRARY_PATH="/opt/homebrew/lib:$DYLD_LIBRARY_PATH"
```

Required Python packages:
- `python-pptx`
- `cairosvg`
- `Pillow`
- `pandas`
- `pyarrow` (for parquet support)
- `PyYAML`

### Command

```bash
python skills/snapshot-generator/scripts/generate_panel_snapshot.py \
    --figures-dir "/path/to/{GENE}-{INDICATION}/{date}__{version}__{hash}/figures" \
    --snapshot-config "path/to/config.yaml" \
    --template "/path/to/Oncology_Takeda_Simple_Template_EN.potx" \
    --output "output.pptx"
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--figures-dir`, `-f` | Yes | Path to figures directory |
| `--snapshot-config`, `-c` | Yes | Path to snapshot configuration YAML |
| `--template`, `-t` | Yes | Path to PowerPoint template (.potx or .pptx) |
| `--output`, `-o` | No | Output path (default: `{gene}-{indication}-panel-snapshot.pptx`) |

---

## Example Configurations

### Dependency Snapshot (1x2 layout)

```yaml
title: "{gene} Dependency in {indication}"
subtitle: "CRISPR functional dependency analysis"
layout: "1x2"

panels:
  - figure: "cards/pan-cancer-crispr-dependency-distribution/figure_waterfall.svg"
    caption: "Pan-cancer CRISPR dependency"

  - figure: "cards/mutation-stratified-dependency/figure_mut_vs_wt_strip.svg"
    table: "cards/mutation-stratified-dependency/plot_data.parquet"
    table_columns: ["cell_line_name", "chronos_score", "is_hotspot_mutant"]
    table_filter: "is_hotspot_mutant == True"
    table_sort_by: "chronos_score"
    table_max_rows: 6
    caption: "Hotspot mutant dependency"
```

### Genomic Alterations Snapshot (2x2 layout)

```yaml
title: "{gene} Genomic Alterations in {indication}"
subtitle: "Mutation and copy number landscape"
layout: "2x2"

panels:
  - figure: "cards/mutation-type-counts/figure_mutation_class_bar.svg"
    caption: "Mutation class distribution"

  - figure: "cards/mutation-type-counts/figure_mutation_lineage_bar.svg"
    caption: "Mutations by lineage"

  - figure: "cards/copy-number-distribution/figure_waterfall_cn.svg"
    caption: "Copy number waterfall"

  - figure: "cards/alteration-role/figure_alteration_role.svg"
    caption: "Alteration role"
```

### Expression Snapshot (2x1 layout)

```yaml
title: "{gene} Expression in {indication}"
layout: "2x1"

panels:
  - figure: "cards/tumor-rna-distribution/figure_expression_distribution.svg"
    caption: "Tumor RNA expression"

  - figure: "cards/tumor-vs-normal-selectivity/figure_tumor_vs_normal_selectivity_4panel.svg"
    caption: "Tumor vs normal selectivity"
```

---

## Template Requirements

The script expects a PowerPoint template with these slide layouts:
- **Layout index 1**: Title slide
- **Layout index 8**: Content slide (Standard 1-Column Text)

Use the simplified Takeda template:
```
/Users/lhl2999/Library/CloudStorage/OneDrive-Takeda/Documents/ONC_skills/Oncology_Takeda_Simple_Template_EN.potx
```
