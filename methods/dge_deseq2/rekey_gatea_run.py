"""GATE-A driver for the gene-id re-key VERDICT backtest (#761 S4, issue #844).

The S4 library (``rekey_backtest.py``, PR #843) is a set of composable functions
with no CLI. This module is the end-to-end DRIVER a human runs to produce the
GATE-A verdict-diff report: it emits shadow products, bridges them to be
symbol-readable, snapshots baseline vs shadow verdicts through the composite
reader, and attributes every moved verdict to a gene-id-authority cause.

It is VERDICT-NEUTRAL and LOCAL-SCRATCH-ONLY: every emit goes through the
library's ``assert_scratch_prefix`` guard, so it can never write a production
product. Do not point ``--scratch`` at ``s3://`` or the data-catalog derived
tree; the guard refuses it.

--------------------------------------------------------------------------------
TWO METHODOLOGY FACTS this driver encodes (both discovered running the harness
end-to-end at GATE A; see the issue #844 report):

  (1) STEM-KEYED SHADOW IS NOT SYMBOL-READABLE.  A ``--collapse-key gene_stem``
      loader + the native four-cell driver emit a product whose ``gene_symbol``
      COLUMN holds the unversioned Ensembl STEM (``deseq2_fit`` sets
      ``gene_symbol = rownames(res)`` and the stem loader's rownames ARE the
      stems).  The composite verdict reader filters ``gene_symbol == <HGNC
      target>``, so it matches ZERO rows on a raw stem product -> every target
      reads ``data_unavailable`` -> ``diff_verdicts`` raises ``RekeyJoinError``
      (the degenerate-join teeth).  To measure anything the stem product must be
      RELABELLED stem -> HGNC symbol.  That relabel is the VERDICT-NEUTRAL half
      of the S5 projection; the ambiguous-symbol PICK-POLICY (which stem
      represents a symbol backed by >1 stem) is the verdict-affecting half S5
      owns.  This driver does the relabel and DELIBERATELY DOES NOT PICK: a
      symbol backed by >1 stem is left stem-labelled, so it reads
      ``data_unavailable`` in the shadow and its verdict move is ATTRIBUTED to
      ``ensg_ambiguous`` (quantifying the pick-policy blast radius) rather than
      silently resolved to an arbitrary stem.

  (2) THE PUBLISHED PRODUCTS ARE A STALE PATCHWORK.  The shipped
      ``*-dge-tumor-vs-normal-sensitivity-v1`` products are a mix of pipeline
      vintages (most July-2026 with a cell-B ComBat column removed since #727;
      laml/skcm re-materialized 2026-09-25 for #734; none carry the #835 gene-id
      columns).  Diffing a published baseline against a CURRENT-pipeline stem
      shadow therefore confounds the re-key with cell-B removal + the #734
      normal-cohort changes.  To ISOLATE the re-key this driver generates BOTH
      arms with the CURRENT pipeline: a ``gene_symbol`` CONTROL arm (byte-
      identical to production's collapse) and a ``gene_stem`` TREATMENT arm, and
      diffs control vs treatment.  ``--baseline published`` is offered for the
      brief's literal (confounded) comparison, but ``current-symbol`` is the
      default and the sound one.

Usage (from the analysis-methods repo root, with the pixi env):

    AWS_PROFILE=cbg PYTHONPATH=$PWD pixi run python \
        methods/dge_deseq2/rekey_gatea_run.py \
        --indications ACC CESC BRCA LAML \
        --scratch /home/sagemaker-user/rekey-backtest-scratch/run \
        --jobs 3

    # population-at-risk only (no DESeq2), all 28 published indications:
    AWS_PROFILE=cbg PYTHONPATH=$PWD pixi run python \
        methods/dge_deseq2/rekey_gatea_run.py --tier1-only
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from methods.dge_deseq2 import read as _read
from methods.dge_deseq2 import rekey_backtest as rb
from methods.gene_id_authority.loader import load_gene_id_authority

DC_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")
CONFIG_DIR = DC_REPO / "indication-configs"
SUBSTRATE = "recount3"


# --- indication roster ------------------------------------------------------
def published_indications() -> list[str]:
    """The 28 published indications (config.published_indications), sorted."""
    from methods.dge_deseq2 import config as _cfg

    return list(_cfg.published_indications())


def config_path(indication: str) -> str:
    p = CONFIG_DIR / f"{indication}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"no indication config at {p}")
    return str(p)


def manifest_id_for(indication: str) -> str:
    return f"{indication.lower()}-dge-tumor-vs-normal-sensitivity-v1"


# --- authority-derived stem<->symbol maps (recount3 namespace) --------------
def build_stem_maps(authority: pd.DataFrame) -> tuple[dict, set]:
    """From the authority: unversioned-stem -> HGNC symbol, and the set of
    HGNC symbols backed by >1 authority gene in the recount3 namespace
    (``ensg_ambiguous``).

    The authority ``gene_id`` is the unversioned Ensembl stem (verified: no
    version suffix).  ``symbol_hgnc`` is the recount3 collapse key.  A stem whose
    symbol is absent (symbol-less) maps to None."""
    sub = authority[authority["symbol_hgnc"].notna()]
    stem_to_symbol = dict(zip(sub["gene_id"].astype(str), sub["symbol_hgnc"].astype(str)))
    n_genes = sub.groupby("symbol_hgnc")["gene_id"].nunique()
    ambiguous_symbols = set(n_genes[n_genes > 1].index.astype(str))
    return stem_to_symbol, ambiguous_symbols


def relabel_stem_product(stem_sensitivity: Path, stem_to_symbol: dict, ambiguous_symbols: set) -> Path:
    """Rewrite a stem-keyed sensitivity.parquet so ``gene_symbol`` carries the
    HGNC symbol for symbols backed by EXACTLY ONE stem (the verdict-neutral
    relabel).  A symbol backed by >1 stem is LEFT stem-labelled (no pick) so it
    reads ``data_unavailable`` and its move is attributed to ``ensg_ambiguous``.
    Symbol-less stems are left stem-labelled too (they had no baseline verdict).

    Writes ``sensitivity.symbolized.parquet`` next to the input and returns it.
    Verdict-neutral: only the ``gene_symbol`` label is rewritten; every numeric
    column (log2fc/padj/...) is untouched."""
    tbl = pq.read_table(str(stem_sensitivity))
    df = tbl.to_pandas()
    stems = df["gene_symbol"].astype(str)  # in the stem arm this column IS the stem

    def _label(stem: str) -> str:
        sym = stem_to_symbol.get(stem)
        if sym is None or sym in ambiguous_symbols:
            return stem  # symbol-less OR ambiguous -> keep stem (unreadable by symbol)
        return sym

    df["gene_stem"] = stems
    df["gene_symbol"] = [_label(s) for s in stems]
    out = stem_sensitivity.with_name("sensitivity.symbolized.parquet")
    df.to_parquet(str(out), index=False)
    return out


# --- one arm's compute (module-level for ProcessPoolExecutor) ---------------
def _emit_arm(args) -> tuple[str, str, str]:
    """(indication, collapse_key, scratch_root) -> (indication, key, products_dir|ERROR)."""
    indication, key, scratch_root = args
    try:
        scratch = Path(scratch_root) / f"{indication}__{key}"
        sens = Path(scratch) / "products" / "sensitivity.parquet"
        if sens.exists():
            return (indication, key, str(Path(scratch) / "products"))
        out = rb.emit_shadow_products(
            config=config_path(indication), scratch_dir=str(scratch), collapse_key=key, check=True
        )
        return (indication, key, str(out))
    except Exception as e:  # noqa: BLE001 — per-arm isolation; one failure must not abort the roster
        return (indication, key, f"ERROR: {type(e).__name__}: {e}")


# --- snapshot / diff / attribute one indication -----------------------------
def _universe(sensitivity_path: str) -> list[str]:
    tbl = pq.read_table(sensitivity_path, columns=["gene_symbol"])
    return sorted({str(s) for s in tbl.column("gene_symbol").to_pylist() if s is not None})


def backtest_indication(
    indication: str,
    control_sens: str,
    treatment_sens_symbolized: str,
    authority: pd.DataFrame,
) -> dict:
    """Diff CONTROL (gene_symbol arm) vs TREATMENT (gene_stem arm, relabelled)
    for one indication over the full control target universe; attribute moves."""
    manifest_id = manifest_id_for(indication)
    targets = _universe(control_sens)
    pairs = [(t, indication) for t in targets]

    with rb.reader_pointed_at_local({manifest_id: control_sens}, read_module=_read):
        baseline = rb.snapshot_verdicts(pairs, read_module=_read)
    with rb.reader_pointed_at_local({manifest_id: treatment_sens_symbolized}, read_module=_read):
        shadow = rb.snapshot_verdicts(pairs, read_module=_read)

    report = rb.build_verdict_delta_report(baseline, shadow, authority=authority, substrate=SUBSTRATE)
    summary = rb.summarize_report(report)
    summary["indication"] = indication
    summary["n_targets_universe"] = len(targets)
    summary["n_baseline_real_verdicts"] = int(
        sum(
            1
            for v in baseline["selectivity_class"]
            if v not in (None, "data_unavailable", "not_applicable") and not pd.isna(v)
        )
    )
    return {"summary": summary, "report": report}


# --- tier 1: population-at-risk over published products (no DESeq2) ---------
def tier1_population(indications: list[str], authority: pd.DataFrame) -> pd.DataFrame:
    """Per published product: how many gene_symbols are ensg_ambiguous /
    symbol_drift / symbol_reuse_conflict in the recount3 namespace.  Robust,
    read-only, no compute — the population that COULD move under the re-key."""
    import pyarrow.fs as pafs

    from methods.gene_id_authority.product import resolve_symbols_to_gene_ids

    fs = pafs.S3FileSystem(region="us-east-1")
    rows = []
    for ind in indications:
        key = f"onc-compbio/data-catalog/derived/{manifest_id_for(ind)}/sensitivity.parquet"
        try:
            tab = pq.read_table(key, filesystem=fs, columns=["gene_symbol"])
            syms = sorted({str(s) for s in tab.column("gene_symbol").to_pylist() if s is not None})
            res = resolve_symbols_to_gene_ids(syms, SUBSTRATE, authority)
            rows.append(
                {
                    "indication": ind,
                    "n_symbols": len(syms),
                    "n_mapped": int(res["mapped"].sum()),
                    "n_ensg_ambiguous": int(res["ensg_ambiguous"].sum()),
                    "n_symbol_drift": int(res["symbol_drift"].fillna(False).sum()),
                    "n_symbol_reuse_conflict": int(res["symbol_reuse_conflict"].fillna(False).sum()),
                }
            )
        except Exception as e:  # noqa: BLE001
            rows.append({"indication": ind, "error": f"{type(e).__name__}: {e}"})
    return pd.DataFrame(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GATE-A gene-id re-key verdict backtest driver (#761 S4)")
    ap.add_argument("--indications", nargs="*", default=None, help="subset; default = all 28 published")
    ap.add_argument("--scratch", default="/home/sagemaker-user/rekey-backtest-scratch/run")
    ap.add_argument("--jobs", type=int, default=3, help="parallel R arms (<=4; host has no swap)")
    ap.add_argument("--tier1-only", action="store_true", help="population-at-risk only, no DESeq2")
    ap.add_argument("--out", default=None, help="results dir (default <scratch>/_results)")
    args = ap.parse_args(argv)

    if args.jobs > 4:
        raise SystemExit("--jobs must be <= 4 (host has no swap; 6-wide reboots it)")

    indications = args.indications or published_indications()
    authority = load_gene_id_authority()
    out_dir = Path(args.out or (Path(args.scratch) / "_results"))
    out_dir.mkdir(parents=True, exist_ok=True)

    # Tier 1 — always cheap, always run.
    t1 = tier1_population(indications, authority)
    t1.to_csv(out_dir / "tier1_population.csv", index=False)
    print("=== TIER 1: population-at-risk (published products, recount3 namespace) ===", flush=True)
    print(t1.to_string(index=False), flush=True)
    if args.tier1_only:
        return 0

    # Tier 2 — dual-arm current-pipeline backtest.
    Path(args.scratch).mkdir(parents=True, exist_ok=True)
    jobs = [(ind, key, args.scratch) for ind in indications for key in ("gene_symbol", "gene_stem")]
    products: dict[tuple[str, str], str] = {}
    print(
        f"\n=== TIER 2: emitting {len(jobs)} arms ({len(indications)} indications x2), jobs={args.jobs} ===", flush=True
    )
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(_emit_arm, j): j for j in jobs}
        for fut in as_completed(futs):
            ind, key, res = fut.result()
            products[(ind, key)] = res
            print(f"  [{ind} {key}] -> {res}", flush=True)

    stem_to_symbol, ambiguous_symbols = build_stem_maps(authority)
    all_summaries = []
    all_moves = []
    for ind in indications:
        ctrl = products.get((ind, "gene_symbol"), "")
        trt = products.get((ind, "gene_stem"), "")
        if ctrl.startswith("ERROR") or trt.startswith("ERROR") or not ctrl or not trt:
            print(f"  [{ind}] SKIP diff — arm error (control={ctrl!r} treatment={trt!r})", flush=True)
            all_summaries.append({"indication": ind, "error": f"control={ctrl}; treatment={trt}"})
            continue
        try:
            ctrl_sens = str(Path(ctrl) / "sensitivity.parquet")
            trt_sens = str(Path(trt) / "sensitivity.parquet")
            trt_symbolized = relabel_stem_product(Path(trt_sens), stem_to_symbol, ambiguous_symbols)
            res = backtest_indication(ind, ctrl_sens, str(trt_symbolized), authority)
            res["report"].to_csv(out_dir / f"moves_{ind}.csv", index=False)
            all_summaries.append(res["summary"])
            # diff_verdicts already carries an ``indication`` column, so append as-is
            # (do not re-insert it — that raises "cannot insert indication, already exists").
            all_moves.append(res["report"])
            print(
                f"  [{ind}] moved_fields={res['summary']['n_moved_fields']} "
                f"by_cause={res['summary']['moves_by_cause']}",
                flush=True,
            )
        except Exception as e:  # noqa: BLE001
            print(f"  [{ind}] DIFF ERROR: {e}\n{traceback.format_exc()}", flush=True)
            all_summaries.append({"indication": ind, "error": f"diff: {type(e).__name__}: {e}"})

    pd.DataFrame(all_summaries).to_csv(out_dir / "summary.csv", index=False)
    if all_moves:
        pd.concat(all_moves, ignore_index=True).to_csv(out_dir / "all_moves.csv", index=False)
    with open(out_dir / "summary.json", "w") as fh:
        json.dump(all_summaries, fh, indent=2, default=str)
    print(f"\n=== results in {out_dir} ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
