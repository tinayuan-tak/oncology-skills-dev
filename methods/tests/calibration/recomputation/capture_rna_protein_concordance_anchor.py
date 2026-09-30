#!/usr/bin/env python3
"""capture_rna_protein_concordance_anchor.py — T3 recomputation anchors for the RNA↔protein
concordance card PAIR (#2046, batch D): cellline-rna-protein-concordance (cell-line grain) and
rna-protein-concordance-tumor (CPTAC tumor grain). Both live in
methods/depmap_rna_protein_concordance/read.py and share the same classify/CI helpers.

WHAT A T3 ANCHOR IS (plan foamy-bird, Stage I / tier T3): it stores the IRREPRODUCIBLE raw INPUT
and re-derives the field in-test through the REAL reader — never a fixture of derived values.

## cell-line grain — read.read_rna_protein_concordance(target, release_pin)

The reader assembles two per-ModelID dicts via read._paired_rna_protein(target, release_pin):
  rna_by_model  = {ModelID: rna_log2tpm}          (DepMap card4 RNA matrix, release-pinned)
  prot_by_model = {ModelID: protein_log2abundance} (Gygi TMT MS column)
then correlates the COMMON models (Pearson + Spearman), classifies rna_as_biomarker on the SPEARMAN
value (G10; Pearson only when scipy is unavailable), and emits the Fisher-z CI of the classifying
correlation. protein_detection_fraction = len(prot_by_model)/len(rna_by_model), so BOTH full dicts
(not just the common intersection) are the irreproducible slice. The anchor stores two lossless
parquet vectors (the two full dicts); the offline test reconstructs them and monkeypatches
_paired_rna_protein — the ONLY S3-load seam — so the whole reader runs offline.

RELEASE PIN: captured at 26q1 (the DepMap vintage the committed tumor-presence golden
tests/fixtures/epcam_coadread_decision.json was built on, matching the batch-A
cellline-rna-distribution anchor's epcam_26q1 pin). The reader's build_summary DEFAULT_RELEASE_PIN
has since advanced to 26q3 (a separate live data-vintage the committed golden does not yet reflect);
pinning 26q1 here reconciles the anchor with the committed golden's substrate exactly.

## CPTAC tumor grain — read.read_tumor_rna_protein_concordance(target, indication)

The reader reads the matched product cptac-rna-protein-matched-per-sample-v1 PER leaf cohort via
read._read_matched_cohort(cohort, target) -> DataFrame[patient_id, gene, rna_log2tpm,
protein_log2abundance], concatenates, correlates, classifies on Spearman, and emits the same CI +
boundary-fragility quartet. The anchor stores one lossless parquet of the matched rows (with a
`cohort` column added so the per-cohort map reconstructs); the offline test monkeypatches
_read_matched_cohort — the ONLY S3-load seam.

Round-trip guard: capture re-runs the reader through the reconstructed dicts/frames (the exact mock
the offline test uses) and asserts it equals the live compute before writing.

Hits S3, NOT run in CI. Run once with live creds:

    cd <analysis-methods repo>
    env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \\
        pixi run python tests/calibration/recomputation/capture_rna_protein_concordance_anchor.py \\
        --cellline EPCAM KRAS --tumor EPCAM/COADREAD KRAS/COADREAD

Writes into tests/calibration/recomputation/{rna_protein_concordance_vectors,anchors}/. Commit them.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import sys
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
VECTORS = HERE / "rna_protein_concordance_vectors"
ANCHORS = HERE / "anchors"

CELLLINE_RELEASE_PIN = "26q1"

# Fields re-derived through the reader and pinned in the anchor (the reconciliation surface).
_CELLLINE_FIELDS = (
    "rna_protein_r",
    "rna_protein_spearman",
    "n_paired_models",
    "protein_detection_fraction",
    "rna_expressed_fraction",
    "rna_high_protein_low_fraction",
    "rna_as_biomarker",
    "rna_proxy_classified_on",
    "rna_protein_r_ci95_low",
    "rna_protein_r_ci95_high",
    "rna_proxy_class_boundary_fragile",
)
_TUMOR_FIELDS = (
    "cptac_cohort",
    "substrate",
    "rna_protein_r",
    "rna_protein_spearman",
    "n_paired_tumors",
    "rna_as_biomarker",
    "rna_proxy_classified_on",
    "rna_protein_r_ci95_low",
    "rna_protein_r_ci95_high",
    "rna_proxy_class_boundary_fragile",
)


def _json_num(v):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return None
    return float(v)


def _expected(summary: dict, fields) -> dict:
    return {k: (_json_num(summary[k]) if isinstance(summary.get(k), float) else summary.get(k)) for k in fields}


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324 — fixture drift guard, not security


def _read_module():
    import onc_methods.depmap_rna_protein_concordance.read as mod  # noqa: PLC0415

    return mod


def capture_cellline(target: str) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    rd = _read_module()
    rna_by_model, prot_by_model, note = rd._paired_rna_protein(target, release_pin=CELLLINE_RELEASE_PIN)  # noqa: SLF001
    if not rna_by_model or not prot_by_model:
        raise SystemExit(f"{target}: no paired RNA/protein ({note})")
    n_common = len(set(rna_by_model) & set(prot_by_model))
    if n_common < 50:
        raise SystemExit(f"{target}: only {n_common} paired models — too thin for a T3 anchor")

    live = rd.read_rna_protein_concordance(target, release_pin=CELLLINE_RELEASE_PIN)
    if live.get("rna_as_biomarker") in (None, "data_unavailable", "insufficient_paired_models"):
        raise SystemExit(f"{target}: cell-line concordance not measurable ({live.get('rna_as_biomarker')})")

    VECTORS.mkdir(parents=True, exist_ok=True)
    ANCHORS.mkdir(parents=True, exist_ok=True)
    rna_models = list(rna_by_model.keys())
    prot_models = list(prot_by_model.keys())
    rna_name = f"{target.lower()}_{CELLLINE_RELEASE_PIN}.cellline_rna_protein_concordance.rna.parquet"
    prot_name = f"{target.lower()}_{CELLLINE_RELEASE_PIN}.cellline_rna_protein_concordance.protein.parquet"
    pq.write_table(
        pa.table(
            {
                "model_id": pa.array(rna_models, type=pa.string()),
                "rna_log2tpm": pa.array([float(rna_by_model[m]) for m in rna_models], type=pa.float64()),
            }
        ),
        VECTORS / rna_name,
    )
    pq.write_table(
        pa.table(
            {
                "model_id": pa.array(prot_models, type=pa.string()),
                "protein_log2abundance": pa.array([float(prot_by_model[m]) for m in prot_models], type=pa.float64()),
            }
        ),
        VECTORS / prot_name,
    )

    # Round-trip guard: reconstruct the two dicts EXACTLY as the offline test will and mock the
    # ONLY S3-load seam (_paired_rna_protein), then confirm the reader reproduces the live numbers.
    recon_rna = {m: float(v) for m, v in rna_by_model.items()}
    recon_prot = {m: float(v) for m, v in prot_by_model.items()}
    with mock.patch.object(rd, "_paired_rna_protein", lambda t, release_pin="26q3": (recon_rna, recon_prot, None)):
        recon = rd.read_rna_protein_concordance(target, release_pin=CELLLINE_RELEASE_PIN)
    for k in _CELLLINE_FIELDS:
        assert recon[k] == live[k], f"{target}: cell-line round-trip mismatch on {k}: {recon[k]!r} != {live[k]!r}"

    anchor = {
        "target": target.upper(),
        "release_pin": CELLLINE_RELEASE_PIN,
        "skill": "tumor-presence",
        "card_id": "cellline-rna-protein-concordance",
        "class_field": "rna_as_biomarker",
        "rna_vector_fixture": f"rna_protein_concordance_vectors/{rna_name}",
        "protein_vector_fixture": f"rna_protein_concordance_vectors/{prot_name}",
        "rna_vector_md5": _md5(VECTORS / rna_name),
        "protein_vector_md5": _md5(VECTORS / prot_name),
        "n_rna_models": len(rna_by_model),
        "n_protein_models": len(prot_by_model),
        "n_paired_models": int(live["n_paired_models"]),
        "expected": _expected(live, _CELLLINE_FIELDS),
        "_captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "_provenance": (
            f"live cbg read via _paired_rna_protein({target!r}, release_pin={CELLLINE_RELEASE_PIN!r}); fixtures = "
            "the gene's full per-ModelID DepMap RNA log2(TPM+1) dict + the full Gygi TMT protein log2-abundance "
            "dict; re-derive with methods.depmap_rna_protein_concordance.read.read_rna_protein_concordance "
            "(mock _paired_rna_protein)."
        ),
    }
    anchor_name = f"{target.lower()}_{CELLLINE_RELEASE_PIN}.cellline_rna_protein_concordance.json"
    (ANCHORS / anchor_name).write_text(json.dumps(anchor, indent=2, allow_nan=False) + "\n")
    print(f"wrote anchors/{anchor_name} + 2 vectors")
    print(
        f"  class={anchor['expected']['rna_as_biomarker']}  r={anchor['expected']['rna_protein_r']}  "
        f"spearman={anchor['expected']['rna_protein_spearman']}  n={anchor['n_paired_models']}  "
        f"classified_on={anchor['expected']['rna_proxy_classified_on']}"
    )


def capture_tumor(target: str, indication: str) -> None:
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    rd = _read_module()
    cohorts = rd._cptac_cohorts_for(indication)  # noqa: SLF001
    if not cohorts:
        raise SystemExit(f"{target}/{indication}: no CPTAC cohort")
    frames_by_cohort = rd._read_matched_cohorts_map(cohorts, target)  # noqa: SLF001

    live = rd.read_tumor_rna_protein_concordance(target, indication)
    if live.get("rna_as_biomarker") in (None, "data_unavailable", "insufficient_paired_tumors"):
        raise SystemExit(f"{target}/{indication}: tumor concordance not measurable ({live.get('rna_as_biomarker')})")

    VECTORS.mkdir(parents=True, exist_ok=True)
    ANCHORS.mkdir(parents=True, exist_ok=True)
    # One lossless parquet of the matched rows across cohorts, with a cohort column so the per-cohort
    # map reconstructs exactly. Only the columns the reader consumes are stored.
    parts = []
    for c, f in frames_by_cohort.items():
        if f.empty:
            continue
        g = f[["patient_id", "gene", "rna_log2tpm", "protein_log2abundance"]].copy()
        g["cohort"] = c
        parts.append(g)
    rows = (
        pd.concat(parts, ignore_index=True)
        if parts
        else pd.DataFrame(columns=["patient_id", "gene", "rna_log2tpm", "protein_log2abundance", "cohort"])
    )
    if len(rows) == 0:
        raise SystemExit(f"{target}/{indication}: matched product returned no rows")
    vec_name = f"{target.lower()}_{indication.lower()}.tumor_rna_protein_concordance.parquet"
    pq.write_table(pa.Table.from_pandas(rows, preserve_index=False), VECTORS / vec_name)

    # Round-trip guard: mock the ONLY S3-load seam (_read_matched_cohort) with the stored per-cohort
    # frames and confirm the reader reproduces the live numbers.
    recon_map = {c: rows[rows["cohort"] == c].drop(columns=["cohort"]).reset_index(drop=True) for c in cohorts}

    def _fake_read_matched_cohort(cohort, target=None):
        df = recon_map.get(cohort)
        return (
            df
            if df is not None
            else pd.DataFrame(columns=["patient_id", "gene", "rna_log2tpm", "protein_log2abundance"])
        )

    with mock.patch.object(rd, "_read_matched_cohort", _fake_read_matched_cohort):
        recon = rd.read_tumor_rna_protein_concordance(target, indication)
    for k in _TUMOR_FIELDS:
        assert recon[k] == live[k], (
            f"{target}/{indication}: tumor round-trip mismatch on {k}: {recon[k]!r} != {live[k]!r}"
        )

    anchor = {
        "target": target.upper(),
        "indication": indication.upper(),
        "skill": "tumor-presence",
        "card_id": "rna-protein-concordance-tumor",
        "class_field": "rna_as_biomarker",
        "matched_rows_fixture": f"rna_protein_concordance_vectors/{vec_name}",
        "matched_rows_md5": _md5(VECTORS / vec_name),
        "cohorts": list(cohorts),
        "n_matched_rows": int(len(rows)),
        "n_paired_tumors": int(live["n_paired_tumors"]),
        "expected": _expected(live, _TUMOR_FIELDS),
        "_captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "_provenance": (
            f"live cbg read via _read_matched_cohorts_map({cohorts!r}, {target!r}) over "
            "cptac-rna-protein-matched-per-sample-v1; fixture = the matched per-tumor "
            "(patient_id, gene, rna_log2tpm, protein_log2abundance, cohort) rows; re-derive with "
            "onc_methods.depmap_rna_protein_concordance.read.read_tumor_rna_protein_concordance "
            "(mock _read_matched_cohort)."
        ),
    }
    anchor_name = f"{target.lower()}_{indication.lower()}.tumor_rna_protein_concordance.json"
    (ANCHORS / anchor_name).write_text(json.dumps(anchor, indent=2, allow_nan=False) + "\n")
    print(f"wrote anchors/{anchor_name} + rna_protein_concordance_vectors/{vec_name}")
    print(
        f"  class={anchor['expected']['rna_as_biomarker']}  r={anchor['expected']['rna_protein_r']}  "
        f"spearman={anchor['expected']['rna_protein_spearman']}  n={anchor['n_paired_tumors']}  "
        f"cohort={anchor['expected']['cptac_cohort']}"
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cellline", nargs="*", default=[], help="gene symbols for the cell-line anchor")
    ap.add_argument("--tumor", nargs="*", default=[], help="TARGET/INDICATION pairs for the tumor anchor")
    args = ap.parse_args(argv)
    failures = []
    for t in args.cellline:
        try:
            capture_cellline(t)
        except SystemExit as e:
            print(f"SKIP cellline {t}: {e}", file=sys.stderr)
            failures.append(f"cellline:{t}")
    for pair in args.tumor:
        try:
            target, indication = pair.split("/", 1)
            capture_tumor(target, indication)
        except SystemExit as e:
            print(f"SKIP tumor {pair}: {e}", file=sys.stderr)
            failures.append(f"tumor:{pair}")
    if failures:
        print(f"\n{len(failures)} capture(s) skipped: {failures}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
