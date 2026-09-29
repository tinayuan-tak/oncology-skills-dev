#!/usr/bin/env python3
"""capture_expression_anchor.py — capture a T3 recomputation anchor for the
cellline-rna-distribution card's `expression_class` (+ the fractions it keys on).

WHAT A T3 ANCHOR IS (plan foamy-bird, Stage I / tier T3). Tiers T1/T2 (the emission
ledger in target-contracts) prove a value is *reachable* and *self-consistent*; they
cannot prove the NUMBER is right — that needs re-derivation from the irreproducible
raw input. The calibration snapshots this sits beside store hand-minimized *derived*
values, which by construction can never catch a wrong computation (a fixture asserted
against its own output). T3 fixes that for known anchors: it stores the IRREPRODUCIBLE
INPUT and re-derives the field in-test through the REAL method code.

For `expression_class` the computation is (depmap_expression_distribution/cli.py):

    tpm_by_model, model_metadata, _ = load_expression_files("26q1", GENE)   # <- S3, irreproducible
    summary = compute_summary_stats(tpm_by_model, model_metadata)           # <- PURE function
    summary["expression_class"] / fraction_expressed / fraction_highly_expressed /
    n_lineage_restricted_lineages

`compute_summary_stats` is a pure function of two dicts — the gene's log2(TPM+1) value
per DepMap cell line, and the per-model lineage. Those two dicts ARE the irreproducible
slice (the gene's column of OmicsExpressionTPMLogp1HumanProteinCodingGenes.csv joined to
Model.csv's OncotreeLineage). So the anchor stores, per gene, a lossless parquet of

    (model_id, log2tpm, lineage)

where `lineage` is the lineage the reader RESOLVES per model
(`OncotreeLineage or lineage or PrimaryDisease or "unknown"`) — stored resolved so the
offline test reconstructs `model_metadata={model_id: {"OncotreeLineage": lineage}}` and
`compute_summary_stats` reproduces the live class exactly. The parquet is full float64
(lossless) — DOWNSAMPLING OR ROUNDING IT IS FORBIDDEN, it is the wrong-denominator /
wrong-comparator bug this tier exists to catch (fraction_expressed is a mean over the
whole column; a truncated column silently shifts it).

Round-trip guard: capture re-runs compute_summary_stats on the RECONSTRUCTED dicts and
asserts it equals the live compute over the raw dicts before writing — so a committed
fixture is guaranteed to reproduce the pinned number.

This tool hits S3 and is NOT run in CI. Run it once per gene with live creds:

    cd <analysis-methods repo>
    env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \\
        pixi run python tests/calibration/recomputation/capture_expression_anchor.py EPCAM CEACAM5 PRM1 ...

It writes into tests/calibration/recomputation/{expression_vectors,anchors}/. Commit the outputs.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VECTORS = HERE / "expression_vectors"
ANCHORS = HERE / "anchors"
# analysis-methods repo root (tests/calibration/recomputation -> parents[3])
AM_ROOT = HERE.parents[2]
# target-contracts snapshot dir (sibling repo) for an independent cross-reference class.
TC_SNAPSHOTS = (
    AM_ROOT.parent / "rnd-computational-biology-oncology-target-contracts" / "tests" / "calibration" / "snapshots"
)

RELEASE_PIN = "26q1"  # the release the card + reader pin throughout (read.py:47)


def _json_num(v):
    """Non-finite floats are not valid JSON — store as null. compute_summary_stats returns
    finite floats for a populated panel, so this only ever fires defensively (keeping
    allow_nan=False from raising on a surprise value)."""
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return None
    return float(v)


def _resolve_lineage(meta: dict):
    """Exactly the reader's resolution (cli.py:291). NOTE: a missing OncotreeLineage is a pandas
    float NaN, which is TRUTHY — so the `or`-chain short-circuits and returns NaN (it never falls
    through to lineage/PrimaryDisease). pandas groupby then DROPS those rows. So the resolved value
    is either a real lineage string or float NaN; we must carry both faithfully."""
    return meta.get("OncotreeLineage") or meta.get("lineage") or meta.get("PrimaryDisease") or "unknown"


def _store_lineage(resolved):
    """String lineages stored verbatim; a NaN/None resolution stored as null (parquet string
    columns cannot hold NaN). The offline test maps null back to float('nan') so the real code
    re-resolves and drops exactly the same rows."""
    if isinstance(resolved, str):
        return resolved
    return None


def _sibling_shas() -> dict:
    out = {}
    for name, repo in (
        ("analysis-methods", AM_ROOT),
        ("data-catalog", AM_ROOT.parent / "rnd-computational-biology-oncology-data-catalog"),
    ):
        try:
            sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], text=True).strip()
            out[name] = sha
        except Exception:
            out[name] = "unknown"
    return out


def _snapshot_class(target: str) -> str | None:
    """The expression_class recorded in a target-contracts tumor-presence calibration
    snapshot, if present — an independent record of the same value, for cross-reference.
    This card is pan-cancer, so any indication snapshot for the gene carries the same value."""
    for snap in sorted(TC_SNAPSHOTS.glob(f"{target.lower()}_*.tumor-presence.json")):
        try:
            d = json.loads(snap.read_text())
            cls = (d.get("headline") or {}).get("expression_class")
            if cls:
                return cls
        except Exception:
            continue
    return None


def capture(target: str) -> None:
    sys.path.insert(0, str(AM_ROOT))
    import pyarrow as pa
    import pyarrow.parquet as pq

    from methods.depmap_expression_distribution.cli import compute_summary_stats, load_expression_files

    tpm_by_model, model_metadata, load_errors = load_expression_files(RELEASE_PIN, target)
    if load_errors:
        raise SystemExit(f"{target}: load errors {load_errors}")
    n_models = len(tpm_by_model)
    if n_models < 500:
        # Card warning_predicate low_panel_expression_coverage fires < 500; below that the
        # panel is too thin to be a stable numeric anchor.
        raise SystemExit(
            f"{target}: only {n_models} cell lines with a finite TPM value — panel too thin for a T3 anchor"
        )

    live = compute_summary_stats(tpm_by_model, model_metadata)
    if live.get("_no_data"):
        raise SystemExit(f"{target}: compute_summary_stats returned no-data")

    # Build the lossless fixture rows in the reader's own iteration order.
    model_ids = list(tpm_by_model.keys())
    log2tpm = [float(tpm_by_model[m]) for m in model_ids]
    lineages = [_store_lineage(_resolve_lineage(model_metadata.get(m, {}))) for m in model_ids]  # str or None

    # Round-trip guard: reconstruct the two dicts EXACTLY as the offline test will (null -> NaN so
    # the real resolver drops the same rows) and confirm compute_summary_stats reproduces the live
    # class + fractions before committing anything.
    recon_tpm = dict(zip(model_ids, log2tpm))
    recon_meta = {m: {"OncotreeLineage": (float("nan") if lin is None else lin)} for m, lin in zip(model_ids, lineages)}
    recon = compute_summary_stats(recon_tpm, recon_meta)
    for k in ("expression_class", "fraction_expressed", "fraction_highly_expressed", "n_lineage_restricted_lineages"):
        assert recon[k] == live[k], f"round-trip mismatch on {k}: recon={recon[k]!r} live={live[k]!r}"

    VECTORS.mkdir(parents=True, exist_ok=True)
    ANCHORS.mkdir(parents=True, exist_ok=True)
    vector_name = f"{target.lower()}_{RELEASE_PIN}.cellline_rna_distribution.parquet"
    pq.write_table(
        pa.table(
            {
                "model_id": pa.array(model_ids, type=pa.string()),
                "log2tpm": pa.array(log2tpm, type=pa.float64()),
                "lineage": pa.array(lineages, type=pa.string()),
            }
        ),
        VECTORS / vector_name,
    )

    anchor = {
        "target": target.upper(),
        "release_pin": RELEASE_PIN,
        "skill": "tumor-presence",
        "card_id": "cellline-rna-distribution",
        "class_field": "expression_class",
        "vector_fixture": f"expression_vectors/{vector_name}",
        "n_cell_lines_evaluated": int(live["n_cell_lines_evaluated"]),
        "expected_class": live["expression_class"],
        "expected_fraction_expressed": _json_num(live["fraction_expressed"]),
        "expected_fraction_highly_expressed": _json_num(live["fraction_highly_expressed"]),
        "expected_n_lineage_restricted_lineages": int(live["n_lineage_restricted_lineages"]),
        "snapshot_class_cross_ref": _snapshot_class(target),
        "_captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "_sibling_shas": _sibling_shas(),
        "_provenance": (
            f"live cbg read via load_expression_files({RELEASE_PIN!r}, {target!r}); fixture = gene's "
            f"log2(TPM+1) per DepMap cell line + resolved lineage ({n_models} models); re-derive with "
            f"methods.depmap_expression_distribution.cli.compute_summary_stats."
        ),
    }
    anchor_name = f"{target.lower()}_{RELEASE_PIN}.cellline_rna_distribution.json"
    (ANCHORS / anchor_name).write_text(json.dumps(anchor, indent=2, allow_nan=False) + "\n")
    print(f"wrote anchors/{anchor_name} + expression_vectors/{vector_name}")
    print(
        f"  class={anchor['expected_class']}  frac_expr={anchor['expected_fraction_expressed']:.4f}  "
        f"frac_high={anchor['expected_fraction_highly_expressed']:.4f}  "
        f"n_lineage_restricted={anchor['expected_n_lineage_restricted_lineages']}  n={n_models}"
    )
    print(f"  snapshot cross-ref class={anchor['snapshot_class_cross_ref']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("targets", nargs="+", help="one or more gene symbols to capture")
    args = ap.parse_args(argv)
    failures = []
    for t in args.targets:
        try:
            capture(t)
        except SystemExit as e:
            print(f"SKIP {t}: {e}", file=sys.stderr)
            failures.append(t)
    if failures:
        print(f"\n{len(failures)} gene(s) skipped: {failures}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
