#!/usr/bin/env python3
"""capture_protein_abundance_anchor.py — capture a T3 recomputation anchor for the
cellline-protein-abundance card's `protein_expression_class` (+ the distribution fields it keys on).

Clone of capture_expression_anchor.py (the cellline-rna-distribution anchor) — the PROTEIN twin.
For `protein_expression_class` the computation is (depmap_protein_abundance/cli.py):

    acc = resolve_accession(target)                                    # <- S3 sidecar, irreproducible
    abundance_by_model, panel_size = load_abundance_column(acc)        # <- S3, irreproducible
    lineage_by_model = load_model_lineage()                            # <- S3, irreproducible (shared)
    all_protein_medians = _all_protein_median_null()                   # <- S3, irreproducible (shared)
    summary = compute_summary(target, abundance_by_model, lineage_by_model,
                               n_panel=panel_size, all_protein_medians=all_protein_medians)  # <- PURE

`compute_summary` is a pure function of two dicts + a panel size + a tuple of panel-wide medians —
the gene's log2-abundance value per DepMap cell line (Gygi TMT MS), the per-model lineage, the total
MS panel size, and every protein's own median (the all-protein null `broadly_high` classifies
against). Those ARE the irreproducible slice. The anchor stores, per gene, a lossless parquet of
(model_id, log2_abundance, lineage) for the gene's OWN column, plus ONE shared lossless parquet of
the panel-wide all-protein median null (target-independent — captured once, reused by every anchor).

Round-trip guard: capture re-runs compute_summary on the RECONSTRUCTED dicts/tuple and asserts it
equals the live compute before writing — so a committed fixture is guaranteed to reproduce the
pinned number.

This tool hits S3 and is NOT run in CI. Run it once per gene with live creds:

    cd <analysis-methods repo>
    env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \\
        pixi run python tests/calibration/recomputation/capture_protein_abundance_anchor.py EPCAM ERBB2 ...

It writes into tests/calibration/recomputation/{protein_vectors,anchors}/. Commit the outputs.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VECTORS = HERE / "protein_vectors"
ANCHORS = HERE / "anchors"
AM_ROOT = HERE.parents[2]

NULL_FIXTURE_NAME = "depmap_gygi_allgene_median_null.parquet"


def _json_num(v):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return None
    return float(v)


def _write_null_fixture(all_protein_medians: tuple) -> str:
    """Write the shared panel-wide all-protein median null ONCE (target-independent — every gene's
    anchor references the same file rather than re-freezing ~12.5k floats per target)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    VECTORS.mkdir(parents=True, exist_ok=True)
    path = VECTORS / NULL_FIXTURE_NAME
    pq.write_table(
        pa.table({"median_log2_abundance": pa.array([float(v) for v in all_protein_medians], type=pa.float64())}),
        path,
    )
    return NULL_FIXTURE_NAME


def capture(target: str) -> None:
    sys.path.insert(0, str(AM_ROOT))
    import pyarrow as pa
    import pyarrow.parquet as pq

    from methods.depmap_protein_abundance import cli as pa_cli

    acc = pa_cli.resolve_accession(target)
    if acc is None:
        raise SystemExit(f"{target}: not resolvable to a Gygi UniProt accession — absent from the MS sidecar")

    abundance_by_model, panel_size = pa_cli.load_abundance_column(acc)
    if not abundance_by_model:
        raise SystemExit(f"{target}: accession {acc} resolved but absent from the Gygi matrix (no live column)")
    n_models = len(abundance_by_model)
    if n_models < 50:
        raise SystemExit(
            f"{target}: only {n_models} cell lines with a quantified value — panel too thin for a T3 anchor"
        )

    lineage_by_model = pa_cli.load_model_lineage()
    all_protein_medians = pa_cli._all_protein_median_null()  # noqa: SLF001 — capture tool, live path

    live = pa_cli.compute_summary(
        target, abundance_by_model, lineage_by_model, n_panel=panel_size, all_protein_medians=all_protein_medians
    )
    if live.get("protein_expression_class") == "data_unavailable":
        raise SystemExit(f"{target}: compute_summary returned data_unavailable")

    # Build the lossless fixture rows in the reader's own iteration order.
    model_ids = list(abundance_by_model.keys())
    log2_abund = [float(abundance_by_model[m]) for m in model_ids]
    lineages = [lineage_by_model.get(m) for m in model_ids]  # str or None (matches load_model_lineage's own type)

    VECTORS.mkdir(parents=True, exist_ok=True)
    ANCHORS.mkdir(parents=True, exist_ok=True)
    vector_name = f"{target.lower()}_gygi.cellline_protein_abundance.parquet"
    pq.write_table(
        pa.table(
            {
                "model_id": pa.array(model_ids, type=pa.string()),
                "log2_abundance": pa.array(log2_abund, type=pa.float64()),
                "lineage": pa.array(lineages, type=pa.string()),
            }
        ),
        VECTORS / vector_name,
    )
    null_name = (
        _write_null_fixture(all_protein_medians) if not (VECTORS / NULL_FIXTURE_NAME).exists() else NULL_FIXTURE_NAME
    )

    # Round-trip guard: reconstruct the two dicts + the null tuple EXACTLY as the offline test will,
    # and confirm compute_summary reproduces the live class + fields before committing anything.
    recon_abund = dict(zip(model_ids, log2_abund))
    recon_lineage = {m: lin for m, lin in zip(model_ids, lineages) if lin is not None}
    null_table = pq.read_table(VECTORS / null_name).to_pydict()
    recon_null = tuple(float(v) for v in null_table["median_log2_abundance"])
    recon = pa_cli.compute_summary(
        target, recon_abund, recon_lineage, n_panel=panel_size, all_protein_medians=recon_null
    )
    for k in (
        "protein_expression_class",
        "n_cell_lines_evaluated",
        "n_cell_lines_in_panel",
        "fraction_detected",
        "median_log2_abundance_panel",
        "n_lineages_evaluated",
        "n_lineage_restricted_lineages",
    ):
        assert recon[k] == live[k], f"{target}: round-trip mismatch on {k}: recon={recon[k]!r} live={live[k]!r}"

    anchor = {
        "target": target.upper(),
        "accession": acc,
        "skill": "tumor-presence",
        "card_id": "cellline-protein-abundance",
        "class_field": "protein_expression_class",
        "vector_fixture": f"protein_vectors/{vector_name}",
        "null_fixture": f"protein_vectors/{null_name}",
        "n_panel": int(panel_size),
        "n_cell_lines_evaluated": int(live["n_cell_lines_evaluated"]),
        "expected_class": live["protein_expression_class"],
        "expected_fraction_detected": _json_num(live["fraction_detected"]),
        "expected_median_log2_abundance_panel": _json_num(live["median_log2_abundance_panel"]),
        "expected_p5_log2_abundance_panel": _json_num(live.get("p5_log2_abundance_panel")),
        "expected_p95_log2_abundance_panel": _json_num(live.get("p95_log2_abundance_panel")),
        "expected_n_lineages_evaluated": int(live["n_lineages_evaluated"]),
        "expected_n_lineage_restricted_lineages": int(live["n_lineage_restricted_lineages"]),
        "_captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "_provenance": (
            f"live cbg read via resolve_accession({target!r}) -> load_abundance_column({acc!r}); fixture = "
            f"gene's log2-abundance per DepMap cell line (Gygi TMT MS, {n_models} models) + lineage; "
            "re-derive with methods.depmap_protein_abundance.cli.compute_summary."
        ),
    }
    anchor_name = f"{target.lower()}_gygi.cellline_protein_abundance.json"
    (ANCHORS / anchor_name).write_text(json.dumps(anchor, indent=2, allow_nan=False) + "\n")
    print(f"wrote anchors/{anchor_name} + protein_vectors/{vector_name}")
    print(
        f"  class={anchor['expected_class']}  frac_detected={anchor['expected_fraction_detected']:.4f}  "
        f"n_lineages={anchor['expected_n_lineages_evaluated']}  n={n_models}"
    )


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
