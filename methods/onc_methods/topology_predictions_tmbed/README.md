# onc_methods/topology_predictions_tmbed

Produces the `topology-predictions-tmbed-v1` derived-manifest artifact
for the oncology data-catalog. Per-gene predicted membrane topology +
extracellular domain (ECD) boundary + signal peptide + orientation,
computed by TMbed (Bernhofer & Rost 2022, Apache-2.0) against the
catalog's UniProt SwissProt human snapshot.

**Companion spec**: `oneTakeda/rnd-computational-biology-oncology-data-catalog:specs/topology-predictions-tmbed-v1.md`
carries the full manifest schema, downstream-consumer conventions, and
license posture.

## Layout

| File | Purpose |
|---|---|
| `prepare_fasta.py` | UniProt DAT → cleaned FASTA (Biopython SwissProt parser + selenocysteine cleanup). Reusable for any future ProtT5/ESM/AlphaFold3 batch job over the human proteome. |
| `reduce_predictions.py` | TMbed `.pred` (format 3) → 15-column per-gene topology Parquet. TMbed-format-specific. |
| `launch.sh` | End-to-end orchestration: catalog-fetch → extract → predict → reduce → S3 upload. Supports `--pilot N` for benchmark runs. |

## Prerequisites

- **TMbed** installed in a Python venv:
  ```
  python -m venv .venv
  source .venv/bin/activate
  pip install git+https://github.com/BernhoferM/TMbed.git 'transformers>=4.30,<5' \
              'tokenizers<0.22' tiktoken sentencepiece biopython pandas pyarrow
  python -m tmbed download   # one-time ProtT5-XL-U50 encoder download (~3 GB)
  ```
- **AWS profile** `cbg` configured (catalog reads + derived-manifest writes)
- **Compute**: 16-vCPU CPU is workable (~11-13 hr wall-clock for 20K human
  proteins at ~2.4 s/protein); a single A10G/V100 GPU cuts this to ~15-30 min

## Usage

Pilot benchmark (100 seqs, ~7 min CPU):
```
bash launch.sh --pilot 100
```

Full run (20,329 seqs, ~11-13 hr CPU):
```
nohup bash launch.sh > launch.log 2>&1 &
disown
```

Or invoke each stage individually via `python -m onc_methods.topology_predictions_tmbed.<module>`.

## Known limitations

Documented in the catalog spec at `specs/topology-predictions-tmbed-v1.md`:

1. **~89% TMH-count accuracy** (per Bernhofer & Rost 2022 benchmark); multi-TM
   SLC transporter families are weak (LAT1/SLC3A2 came back as 1-TM instead
   of 4-TM in pilot).
2. **ECD extraction is heuristic** — the longest 'o' (outside) run, or the
   longest 'i' run as fallback. First-pass filter for downstream cards, not
   engineering-grade coordinate.
3. **β-barrel calls will be sparse in human** — pilot saw 0 β-barrels in the
   first 100; expect ~0-1% of the full 20K.
4. **No isoform coverage** — one row per canonical UniProt accession.
