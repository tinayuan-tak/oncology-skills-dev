#!/usr/bin/env python
"""ruvg_calibration.py — the Stage-1 substrate × method calibration study.

Answers the question the Stage-1 sign-off gate turns on: **does RUVg-correcting
the cross-cohort TCGA-vs-GTEx contrast (cell Cr) move it toward the confound-free
within-TCGA anchor (cell A), and does that hold across two independent count
substrates (recount3, Xena/Toil)?**

Matrix: substrate ∈ {recount3, xena-toil} × indication ∈ {brca, paad}
        × method ∈ {naive-C, RUVg-Cr}, all scored against the cell-A anchor.
(The RUVg+RIN-Cr arm the plan sketched was dropped after the RIN symmetry probe
found RIN GTEx-only / non-identifiable — see outputs/rin_symmetry_probe.json.)

Two phases, both resumable:
  --compute   run the loaders + run_calibration_cells.R for each (substrate,
              indication); skips a step whose output already exists on disk.
  --report    (always) read every cell TSV present, compute concordance metrics
              vs the A anchor + cross-substrate Cr agreement, write
              outputs/calibration_report.md + outputs/summary.json.

Heavy live compute (S3 + DESeq2/RUVg over ~1e3 samples) — intended to run once,
serially, in the background. Not a unit test (the conftest guard keeps it out of
collection); a light invariant test lives in the package's real tests/ dir.

Credentials: SageMaker container creds outrank AWS_PROFILE, so we drop the
container-cred env var and force AWS_PROFILE=cbg for every child (the R loader's
`aws s3 cp` inherits this).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
DEV_HOME = HERE.parent
STEPS = (DEV_HOME.parent.parent / "steps").resolve()
REPO_ROOT = DEV_HOME.parents[3]  # methods/dge_deseq2/method_development/<slug> -> repo root
OUT_DIR = Path(os.environ.get("DGE_QC_OUT", DEV_HOME / "outputs"))
WORK = Path(os.environ.get("DGE_CALIB_WORK", "/home/sagemaker-user/dge_calib_work"))

# SUBSTRATES / INDICATIONS are env-overridable so the same resumable compute
# driver can run the original brca+paad k=2 study OR the authorized multi-anchor
# re-run (recount3-only, 6 adequately-powered anchors). Defaults reproduce the
# original 2x2 matrix. TCGA study code defaults to the uppercased indication.
SUBSTRATES = tuple(s for s in os.environ.get("DGE_CALIB_SUBSTRATES", "recount3,xena-toil").split(",") if s)
INDICATIONS = tuple(i for i in os.environ.get("DGE_CALIB_INDICATIONS", "brca,paad").split(",") if i)
TCGA_STUDY = {"brca": "BRCA", "paad": "PAAD"}


def tcga_study(indication: str) -> str:
    return TCGA_STUDY.get(indication, indication.upper())


SIG_Q = 0.05
K_RUVG = int(os.environ.get("DGE_CALIB_K", "2"))
MIN_NORMALS = int(os.environ.get("DGE_CALIB_MIN_NORMALS", "3"))
XENA_MATRIX_CACHE = "/home/sagemaker-user/xena_toil_gene_expected_count.gz"


def child_env() -> dict:
    env = dict(os.environ)
    env.pop("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", None)
    env.setdefault("AWS_PROFILE", "cbg")
    return env


def run(cmd: list[str], log: Path) -> None:
    print(f"[calib] $ {' '.join(cmd)}\n[calib]   log -> {log}", flush=True)
    with open(log, "w") as fh:
        proc = subprocess.run(cmd, cwd=REPO_ROOT, env=child_env(), stdout=fh, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        tail = "\n".join(Path(log).read_text().splitlines()[-25:])
        raise SystemExit(f"[calib] FAILED ({proc.returncode}): {' '.join(cmd)}\n{tail}")


def pixi(*args: str) -> list[str]:
    return ["pixi", "run", "--environment", "default", *args]


# --------------------------------------------------------------------------- #
# compute phase
# --------------------------------------------------------------------------- #
def load_rds(substrate: str, indication: str) -> Path:
    rds = WORK / f"{substrate}__{indication}.rds"
    if rds.exists() and rds.stat().st_size > 0:
        print(f"[calib] reuse {rds.name}", flush=True)
        return rds
    log = WORK / f"load__{substrate}__{indication}.log"
    if substrate == "recount3":
        cfg = WORK / f"cfg_{indication}.yaml"
        cfg.write_text(f"tcga_cohorts: [{tcga_study(indication)}]\n")
        run(pixi("Rscript", str(STEPS / "00_load_recount3.R"), "--config", str(cfg), "--out", str(rds)), log)
    elif substrate == "xena-toil":
        run(
            pixi(
                "Rscript",
                str(STEPS / "00_load_xena_toil.R"),
                "--indication",
                indication,
                "--matrix-cache",
                XENA_MATRIX_CACHE,
                "--out",
                str(rds),
            ),
            log,
        )
    else:
        raise ValueError(substrate)
    return rds


def compute_cells(substrate: str, indication: str) -> Path:
    cell_dir = WORK / f"cells__{substrate}__{indication}"
    prov = cell_dir / "provenance.json"
    if prov.exists():
        print(f"[calib] reuse cells {cell_dir.name}", flush=True)
        return cell_dir
    cell_dir.mkdir(parents=True, exist_ok=True)
    rds = load_rds(substrate, indication)
    log = WORK / f"cells__{substrate}__{indication}.log"
    run(
        pixi(
            "Rscript",
            str(DEV_HOME / "scripts" / "run_calibration_cells.R"),
            "--in",
            str(rds),
            "--out-dir",
            str(cell_dir),
            "--substrate",
            substrate,
            "--indication",
            indication,
            "--min-normals",
            str(MIN_NORMALS),
            "--k",
            str(K_RUVG),
        ),
        log,
    )
    return cell_dir


def do_compute() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    for substrate in SUBSTRATES:
        for indication in INDICATIONS:
            print(f"\n[calib] === {substrate} / {indication} ===", flush=True)
            compute_cells(substrate, indication)


# --------------------------------------------------------------------------- #
# report phase
# --------------------------------------------------------------------------- #
def read_cell(cell_dir: Path, label: str) -> pd.DataFrame | None:
    p = cell_dir / f"cell_{label}.tsv"
    if not p.exists():
        return None
    df = pd.read_csv(p, sep="\t")
    return df.set_index("gene_symbol")


def _spearman(a: pd.Series, b: pd.Series) -> float:
    m = a.notna() & b.notna()
    if m.sum() < 10:
        return float("nan")
    return float(spearmanr(a[m], b[m]).statistic)


def concordance(cells: dict[str, pd.DataFrame]) -> dict:
    """Metrics for one (substrate, indication) vs the cell-A anchor."""
    out: dict = {"cells_ran": sorted(cells)}
    A = cells.get("A")
    for label in ("A", "C", "Cr"):
        df = cells.get(label)
        if df is None:
            continue
        tested = df["padj"].notna()
        out[f"n_tested_{label}"] = int(tested.sum())
        out[f"sig_frac_{label}"] = float((df.loc[tested, "padj"] < SIG_Q).mean()) if tested.any() else float("nan")
        out[f"median_abs_lfc_{label}"] = float(df["log2fc"].abs().median())
    if A is None:
        out["note"] = "no cell-A anchor (cohort lacks TCGA adjacent-normal); Cr/C reported unanchored"
        return out

    a_sig_genes = A.index[(A["padj"] < SIG_Q) & A["log2fc"].notna()]
    out["n_A_sig"] = int(len(a_sig_genes))
    for label in ("C", "Cr"):
        df = cells.get(label)
        if df is None:
            continue
        shared = A.index.intersection(df.index)
        rho_all = _spearman(A.loc[shared, "log2fc"], df.loc[shared, "log2fc"])
        out[f"rho_A_{label}_all"] = rho_all
        sub = a_sig_genes.intersection(df.index)
        out[f"rho_A_{label}_Asig"] = _spearman(A.loc[sub, "log2fc"], df.loc[sub, "log2fc"])
        # sign agreement / sign-flip on A-sig genes where both LFCs are nonzero
        sa, sb = np.sign(A.loc[sub, "log2fc"]), np.sign(df.loc[sub, "log2fc"])
        both = (sa != 0) & (sb != 0)
        n_both = int(both.sum())
        out[f"n_A_sig_shared_{label}"] = n_both
        out[f"sign_agree_frac_{label}"] = float((sa[both] == sb[both]).mean()) if n_both else float("nan")
        out[f"sign_flip_n_{label}"] = int((sa[both] != sb[both]).sum()) if n_both else 0
    # uplift = how much closer to A does RUVg get vs naive C
    if "rho_A_Cr_all" in out and "rho_A_C_all" in out:
        out["rho_uplift_all"] = out["rho_A_Cr_all"] - out["rho_A_C_all"]
    if "sign_agree_frac_Cr" in out and "sign_agree_frac_C" in out:
        out["sign_agree_uplift"] = out["sign_agree_frac_Cr"] - out["sign_agree_frac_C"]
    return out


def cross_substrate(all_cells: dict) -> dict:
    """recount3-Cr vs xena-Cr agreement per indication (biology vs artifact)."""
    xs = {}
    for ind in INDICATIONS:
        r = all_cells.get(("recount3", ind), {}).get("Cr")
        x = all_cells.get(("xena-toil", ind), {}).get("Cr")
        if r is None or x is None:
            continue
        shared = r.index.intersection(x.index)
        xs[ind] = {
            "n_shared_genes": int(len(shared)),
            "rho_Cr_recount3_vs_xena": _spearman(r.loc[shared, "log2fc"], x.loc[shared, "log2fc"]),
        }
    return xs


def fmt(v) -> str:
    if isinstance(v, float):
        return "n/a" if (v != v) else f"{v:.3f}"
    return str(v)


def do_report() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_cells: dict = {}
    provenance: dict = {}
    for substrate in SUBSTRATES:
        for ind in INDICATIONS:
            cell_dir = WORK / f"cells__{substrate}__{ind}"
            cells = {lab: read_cell(cell_dir, lab) for lab in ("A", "C", "Cr")}
            cells = {k: v for k, v in cells.items() if v is not None}
            all_cells[(substrate, ind)] = cells
            prov = cell_dir / "provenance.json"
            if prov.exists():
                provenance[f"{substrate}/{ind}"] = json.loads(prov.read_text())

    rows = {}
    for (substrate, ind), cells in all_cells.items():
        if cells:
            rows[f"{substrate}/{ind}"] = concordance(cells)
    xs = cross_substrate(all_cells)

    summary = {
        "matrix": {
            "substrates": list(SUBSTRATES),
            "indications": list(INDICATIONS),
            "methods": ["naive-C", "RUVg-Cr"],
            "anchor": "cell A (within-TCGA)",
            "k_ruvg": K_RUVG,
            "sig_q": SIG_Q,
        },
        "per_cell": rows,
        "cross_substrate_Cr": xs,
        "provenance": provenance,
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    # ---- markdown report ----
    L = []
    L.append("# RUVg cross-cohort calibration — Stage 1 (piped-whistling-conway B4)\n")
    L.append(
        "**Anchor:** within-TCGA cell A (tumor vs TCGA adjacent-normal, confound-free). "
        "**Question:** does RUVg-Cr move the cross-cohort contrast toward A vs naive-C, "
        "and does it agree across substrates?\n"
    )
    L.append(
        f"- substrates: {', '.join(SUBSTRATES)}  ·  indications: {', '.join(INDICATIONS)}  "
        f"·  RUVg k={K_RUVG}  ·  sig q<{SIG_Q}\n"
    )
    L.append("RIN/ischemic arm dropped (GTEx-only / non-identifiable — see `rin_symmetry_probe.json`).\n")

    L.append("\n## Concordance vs cell-A anchor\n")
    L.append(
        "| substrate/ind | cells | n A-sig | ρ(A,C) | ρ(A,Cr) | ρ uplift | "
        "sign-agree C | sign-agree Cr | agree uplift | sig% A | sig% C | sig% Cr |"
    )
    L.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for key, r in rows.items():
        L.append(
            "| {k} | {cr} | {nas} | {rc} | {rcr} | {up} | {sac} | {sacr} | {sau} | {sa} | {sc} | {scr} |".format(
                k=key,
                cr="+".join(r.get("cells_ran", [])),
                nas=fmt(r.get("n_A_sig")),
                rc=fmt(r.get("rho_A_C_all")),
                rcr=fmt(r.get("rho_A_Cr_all")),
                up=fmt(r.get("rho_uplift_all")),
                sac=fmt(r.get("sign_agree_frac_C")),
                sacr=fmt(r.get("sign_agree_frac_Cr")),
                sau=fmt(r.get("sign_agree_uplift")),
                sa=fmt(r.get("sig_frac_A")),
                sc=fmt(r.get("sig_frac_C")),
                scr=fmt(r.get("sig_frac_Cr")),
            )
        )

    L.append("\n## Cross-substrate Cr agreement (recount3 vs Xena/Toil)\n")
    if xs:
        L.append("| indication | shared genes | ρ(Cr recount3, Cr xena) |")
        L.append("|---|--:|--:|")
        for ind, d in xs.items():
            L.append(f"| {ind} | {d['n_shared_genes']} | {fmt(d['rho_Cr_recount3_vs_xena'])} |")
    else:
        L.append("_(no indication has Cr on both substrates yet)_")

    L.append("\n## How to read this\n")
    L.append(
        "- **ρ uplift > 0** and **agree uplift > 0** ⇒ RUVg pulls the cross-cohort contrast "
        "toward the confound-free anchor (the intended effect). paad is the stress case "
        "(v1 A-vs-C Pearson ≈0.14); brca is the easy case.\n"
    )
    L.append(
        "- **sig% Cr between sig% A and sig% C** ⇒ RUVg is deflating naive-C's significance "
        "inflation toward the anchor rather than over-shrinking.\n"
    )
    L.append(
        "- **cross-substrate ρ high** ⇒ the corrected signal is biology, not a substrate artifact — "
        "the precondition for trusting Cr on GTEx-only cohorts / a substrate swap (both DEFERRED).\n"
    )
    L.append("\n_Generated by `scripts/ruvg_calibration.py --report`._\n")

    (OUT_DIR / "calibration_report.md").write_text("\n".join(L))
    print(f"[calib] wrote {OUT_DIR / 'calibration_report.md'} and summary.json", flush=True)
    print("\n".join(L))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--compute", action="store_true", help="run loaders + cell fits (heavy, live)")
    ap.add_argument("--report", action="store_true", help="build report from existing cell TSVs")
    args = ap.parse_args()
    if not args.compute and not args.report:
        ap.error("pass --compute and/or --report")
    if args.compute:
        do_compute()
    if args.report or args.compute:
        do_report()


if __name__ == "__main__":
    main()
