# kinome_atlas_pwm_lookup

Per-kinase substrate-specificity PWM lookup, derived from the Johnson 2023
+ Yaron-Barir 2024 kinome-atlas Nature-supplementary Excel workbooks.
Produces one row per `(kinase, position, amino_acid)` with the norm_scaled
log-odds enrichment value.

## Coverage

- **396 canonical kinases**: 303 Ser/Thr (Johnson 2023) + 93 Tyr canonical
  + non-canonical (Yaron-Barir 2024)
- **10 positions per Tyr kinase (-5..-1, +1..+5)**; 9 positions per Ser/Thr
  kinase (-5..-1, +1..+4). Position 0 (phospho-acceptor) is by definition
  S/T/Y and is NOT stored in this table.
- **23 amino acids per position**: 20 standard + 3 phospho (`s`, `t`, `y`
  lowercase = phospho-Ser/Thr/Tyr elsewhere in the substrate window)
- **~84,111 total rows** (303 × 207 Ser/Thr + 93 × 230 Tyr), ~240 KB
  snappy Parquet

## Data-catalog artifacts

| Artifact | Location | Manifest |
|----------|----------|----------|
| Source xlsx workbooks | `s3://onc-compbio/data-catalog/sources/kinome-atlas/nature-supplementary-snapshot-2026-07-10/` | `sources/kinome-atlas-nature-supplementary-snapshot-2026-07-10` |
| Derived Parquet | `s3://onc-compbio/data-catalog/derived/kinome-atlas-pwm-lookup-v1/pwm_lookup_v1.parquet` | `derived/kinome-atlas-pwm-lookup-v1` |

## Usage

```python
from methods.kinome_atlas_pwm_lookup.loader import load_pwm_lookup

df = load_pwm_lookup()
# columns: family, kinase, position, amino_acid,
#          norm_scaled_value, matrix_type, source_paper

# Example: score a phospho-Tyr candidate site against ABL PWM
abl = df[(df.kinase == 'ABL') & (df.family == 'tyrosine')]
# ...score sequence window YXXPXXY by looking up per-position values
```

## Rebuild (catalog maintainers only)

```bash
python -m methods.kinome_atlas_pwm_lookup.build \
  --ser-thr-xlsx /path/to/johnson_2023_serthr_pwms.xlsx \
  --tyr-xlsx /path/to/yaron_barir_2024_tyr_pwms.xlsx \
  --out-parquet pwm_lookup_v1.parquet
```

Then update:
- `methods/kinome_atlas_pwm_lookup/loader.py` — `S3_MD5_PARQUET` pin
- `manifests/derived/kinome-atlas-pwm-lookup-v1.yaml` (data-catalog repo) —
  `md5`, `size_bytes`, `git_commit`

## Scope caveats

- **norm_scaled matrix only**: this v1 emits the `norm_scaled` matrix
  (paper's downstream scorer default). Raw densitometry + row-normalized
  matrices are also in the source xlsx (sheets 1-2) but not exposed here.
  If a downstream method needs them, extend `build.py` to emit an
  additional `matrix_type` value.
- **Position 0 not included**: the phospho-acceptor slot is constrained
  by definition (S/T/Y). Not a PWM entry.
- **Kinase names as published** in the xlsx first column. Some entries
  carry qualifier suffixes (e.g. `TESK1_TYR`, `WEE1_TYR`, `BMPR2_TYR`) —
  preserved verbatim from the source. These are dual-specificity or
  pseudo-kinases in the non-canonical Tyr set.
