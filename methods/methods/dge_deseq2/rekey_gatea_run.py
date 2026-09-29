"""GATE-A driver for the gene-id re-key VERDICT backtest (#761 S4, issues #844/#847).

The S4 library (``rekey_backtest.py``, PR #843) is a set of composable functions
with no CLI. This module is the end-to-end DRIVER a human runs to produce the
GATE-A verdict-diff report: it emits shadow products, bridges them to be
symbol-readable, snapshots baseline vs shadow verdicts through the composite
reader, and attributes every moved verdict to a gene-id-authority cause.

#847 (GATE-A v2) re-expresses the backtest on the CORRECTED basis: recount3 is
already gene-level per versioned ENSG, so the shipped symbol-collapse is a WRONG
extra step (it drops symbol-less ENSGs and SUMS biologically distinct genes that
merely share a symbol). The re-key = fit DESeq2 at the ENSG grain; symbol becomes
annotation. To separate the two distinct causes of the total verdict movement the
driver now runs THREE arms per indication and reports the halves SEPARATELY:

  * C0 (control / shipped): gene_symbol collapse + drop-symbol-less.
  * C1 (identity arm): gene_stem grain restricted to the SAME has-symbol gene set
    as C0, distinct genes NO LONGER summed. Diff C0->C1 = the PURE IDENTITY
    correction (un-summing + ENSG relabel; ambiguous symbols lose their verdict
    under the no-pick re-key).
  * C2 (universe arm = proposed prod): gene_stem grain + symbol-less genes
    retained. Diff C1->C2 = the gene-universe / normalization effect.

The C1 arm is reached by the #847 verdict-neutral ``--gene-universe has_symbol``
toggle on the stem path (default ``all`` preserves the shipped stem behaviour).

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
      normal-cohort changes.  To ISOLATE the re-key this driver generates ALL
      THREE arms (C0/C1/C2) with the CURRENT pipeline and diffs them against each
      other, so every reported move is a within-current-pipeline re-key effect
      (never a vintage confound).

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

# Portable sibling default (env DATA_CATALOG_ROOT override), same resolution as
# methods.dge_deseq2.read.DATA_CATALOG — never a hardcoded /home/sagemaker-user literal
# (SK#2137: that literal is the ARCHIVED pre-merge clone location, a stale-read hazard).
DC_REPO = _read.DATA_CATALOG
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


# --- the three arms (#847 GATE-A v2 identity-vs-universe decomposition) ------
# Each arm = (label, collapse_key, gene_universe, scratch_key). The scratch_key
# is the on-disk directory suffix; C0/C2 reuse the #844 directory names so their
# products (if already emitted) are reused, and only the NEW C1 arm computes.
#   C0 (control / shipped): gene_symbol collapse + drop-symbol-less.
#   C1 (identity arm):      gene_stem grain restricted to the has-symbol set
#                           (distinct genes NO LONGER summed). C0->C1 = identity.
#   C2 (universe arm):      gene_stem grain + symbol-less retained (proposed
#                           prod). C1->C2 = gene-universe / normalization effect.
ARMS: tuple[tuple[str, str, str, str], ...] = (
    ("C0", "gene_symbol", "all", "gene_symbol"),
    ("C1", "gene_stem", "has_symbol", "gene_stem__has_symbol"),
    ("C2", "gene_stem", "all", "gene_stem"),
)
ARM_BY_LABEL = {a[0]: a for a in ARMS}


# --- one arm's compute (module-level for ProcessPoolExecutor) ---------------
def _emit_arm(args) -> tuple[str, str, str]:
    """(indication, scratch_key, collapse_key, gene_universe, scratch_root)
    -> (indication, scratch_key, products_dir|ERROR)."""
    indication, scratch_key, collapse_key, gene_universe, scratch_root = args
    try:
        scratch = Path(scratch_root) / f"{indication}__{scratch_key}"
        sens = Path(scratch) / "products" / "sensitivity.parquet"
        if sens.exists():
            return (indication, scratch_key, str(Path(scratch) / "products"))
        out = rb.emit_shadow_products(
            config=config_path(indication),
            scratch_dir=str(scratch),
            collapse_key=collapse_key,
            gene_universe=gene_universe,
            check=True,
        )
        return (indication, scratch_key, str(out))
    except Exception as e:  # noqa: BLE001 — per-arm isolation; one failure must not abort the roster
        return (indication, scratch_key, f"ERROR: {type(e).__name__}: {e}")


# --- snapshot / diff / attribute one indication -----------------------------
def _universe(sensitivity_path: str) -> list[str]:
    tbl = pq.read_table(sensitivity_path, columns=["gene_symbol"])
    return sorted({str(s) for s in tbl.column("gene_symbol").to_pylist() if s is not None})


def _snapshot_arm(sens_path: str, indication: str, pairs) -> pd.DataFrame:
    """Snapshot verdicts for one arm's (relabelled) sensitivity product."""
    manifest_id = manifest_id_for(indication)
    with rb.reader_pointed_at_local({manifest_id: sens_path}, read_module=_read):
        return rb.snapshot_verdicts(pairs, read_module=_read)


def _n_real(df: pd.DataFrame) -> int:
    return int(
        sum(
            1
            for v in df["selectivity_class"]
            if v not in (None, "data_unavailable", "not_applicable") and not pd.isna(v)
        )
    )


def decompose_indication(
    indication: str,
    c0_sens: str,
    c1_sens_symbolized: str,
    c2_sens_symbolized: str,
    authority: pd.DataFrame,
) -> dict:
    """3-arm decomposition for one indication over the C0 target universe.

    Produces TWO separated verdict-diff reports on the shared (target, indication)
    keys:
      * IDENTITY  (C0 -> C1): the pure identity correction (un-summing distinct
        genes that shared a symbol + ENSG relabel; ambiguous symbols lose their
        verdict under the no-pick re-key).
      * UNIVERSE  (C1 -> C2): the gene-universe / normalization effect of
        re-admitting symbol-less genes into the DESeq2 fit.
    Also computes the TOTAL (C0 -> C2) for the additivity check. Each report is
    attributed by gene-id-authority cause and carries selectivity_class
    transition counts (appear/disappear/change_class)."""
    targets = _universe(c0_sens)
    pairs = [(t, indication) for t in targets]

    c0 = _snapshot_arm(c0_sens, indication, pairs)
    c1 = _snapshot_arm(c1_sens_symbolized, indication, pairs)
    c2 = _snapshot_arm(c2_sens_symbolized, indication, pairs)

    identity = rb.build_verdict_delta_report(c0, c1, authority=authority, substrate=SUBSTRATE)
    universe = rb.build_verdict_delta_report(c1, c2, authority=authority, substrate=SUBSTRATE)
    total = rb.build_verdict_delta_report(c0, c2, authority=authority, substrate=SUBSTRATE)

    def _pack(label: str, rep: pd.DataFrame) -> dict:
        s = rb.summarize_report(rep)
        s["cause"] = label
        return s

    summary = {
        "indication": indication,
        "n_targets_universe": len(targets),
        "n_c0_real_verdicts": _n_real(c0),
        "n_c1_real_verdicts": _n_real(c1),
        "n_c2_real_verdicts": _n_real(c2),
        "identity_C0_to_C1": _pack("identity", identity),
        "universe_C1_to_C2": _pack("universe", universe),
        "total_C0_to_C2": _pack("total", total),
    }
    return {
        "summary": summary,
        "identity": identity,
        "universe": universe,
        "total": total,
    }


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

    # Tier 2 — THREE-arm current-pipeline decomposition (C0 / C1 / C2).
    Path(args.scratch).mkdir(parents=True, exist_ok=True)
    jobs = [
        (ind, scratch_key, collapse_key, gene_universe, args.scratch)
        for ind in indications
        for (_label, collapse_key, gene_universe, scratch_key) in ARMS
    ]
    products: dict[tuple[str, str], str] = {}  # (indication, scratch_key) -> dir|ERROR
    print(
        f"\n=== TIER 2: emitting {len(jobs)} arms ({len(indications)} indications x3), jobs={args.jobs} ===",
        flush=True,
    )
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(_emit_arm, j): j for j in jobs}
        for fut in as_completed(futs):
            ind, scratch_key, res = fut.result()
            products[(ind, scratch_key)] = res
            print(f"  [{ind} {scratch_key}] -> {res}", flush=True)

    stem_to_symbol, ambiguous_symbols = build_stem_maps(authority)
    all_summaries = []
    all_identity, all_universe, all_total = [], [], []
    for ind in indications:
        arm_dirs = {lbl: products.get((ind, ARM_BY_LABEL[lbl][3]), "") for lbl in ("C0", "C1", "C2")}
        bad = {lbl: d for lbl, d in arm_dirs.items() if not d or d.startswith("ERROR")}
        if bad:
            print(f"  [{ind}] SKIP decompose — arm error(s): {bad}", flush=True)
            all_summaries.append({"indication": ind, "error": f"arm(s) failed: {bad}"})
            continue
        try:
            c0_sens = str(Path(arm_dirs["C0"]) / "sensitivity.parquet")
            c1_symbolized = relabel_stem_product(
                Path(arm_dirs["C1"]) / "sensitivity.parquet", stem_to_symbol, ambiguous_symbols
            )
            c2_symbolized = relabel_stem_product(
                Path(arm_dirs["C2"]) / "sensitivity.parquet", stem_to_symbol, ambiguous_symbols
            )
            res = decompose_indication(ind, c0_sens, str(c1_symbolized), str(c2_symbolized), authority)
            res["identity"].to_csv(out_dir / f"identity_C0_to_C1_{ind}.csv", index=False)
            res["universe"].to_csv(out_dir / f"universe_C1_to_C2_{ind}.csv", index=False)
            res["total"].to_csv(out_dir / f"total_C0_to_C2_{ind}.csv", index=False)
            all_summaries.append(res["summary"])
            # diff_verdicts already carries an ``indication`` column; append as-is.
            all_identity.append(res["identity"])
            all_universe.append(res["universe"])
            all_total.append(res["total"])
            s = res["summary"]
            print(
                f"  [{ind}] identity(C0->C1) moved={s['identity_C0_to_C1']['n_moved_fields']} "
                f"cause={s['identity_C0_to_C1']['moves_by_cause']} | "
                f"universe(C1->C2) moved={s['universe_C1_to_C2']['n_moved_fields']} "
                f"cause={s['universe_C1_to_C2']['moves_by_cause']}",
                flush=True,
            )
        except Exception as e:  # noqa: BLE001
            print(f"  [{ind}] DECOMPOSE ERROR: {e}\n{traceback.format_exc()}", flush=True)
            all_summaries.append({"indication": ind, "error": f"decompose: {type(e).__name__}: {e}"})

    pd.DataFrame(all_summaries).to_csv(out_dir / "summary.csv", index=False)
    if all_identity:
        pd.concat(all_identity, ignore_index=True).to_csv(out_dir / "all_identity_C0_to_C1.csv", index=False)
    if all_universe:
        pd.concat(all_universe, ignore_index=True).to_csv(out_dir / "all_universe_C1_to_C2.csv", index=False)
    if all_total:
        pd.concat(all_total, ignore_index=True).to_csv(out_dir / "all_total_C0_to_C2.csv", index=False)
    with open(out_dir / "summary.json", "w") as fh:
        json.dump(all_summaries, fh, indent=2, default=str)
    print(f"\n=== results in {out_dir} ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
