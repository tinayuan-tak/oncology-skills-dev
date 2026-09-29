#!/usr/bin/env python
"""multi_anchor_report.py — rebuilt-metric report for the multi-anchor re-run.

The Stage-1 k=2 study (ruvg_calibration.py --report) scored cells with
whole-genome Spearman ρ, which is dominated by ~30k near-null genes and blind to
the sign-flips / significance-inflation that actually matter. The four-agent
review (2026-09-20) required a rebuilt metric. This script implements it and
writes a SEPARATE artifact so it never clobbers the hand-authored NEGATIVE
verdict in outputs/calibration_report.md.

For each (substrate, indication), scored against the within-TCGA cell-A anchor
at the SHIPPED effect gate (|log2FC| >= log2(1.5), s-value<0.005 with padj
fallback), for each cross-cohort method M in {C (naive), Cr (RUVg)}:

  * FPR-vs-anchor-null : among genes A calls clearly NULL (padj_A>0.5 AND
    |lfc_A|<gate), the fraction M calls significant. This is the significance-
    inflation confound the correction exists to remove. Lower is better; a
    method that recovers A drives this toward the nominal rate.
  * sign-concordance   : among A-significant genes, fraction where sign(lfc_M)
    == sign(lfc_A). Higher is better.
  * effect-size corr   : Pearson(lfc_A, lfc_M) over A-significant genes. Higher
    is better.

Every statistic carries a gene-bootstrap 95% CI, and the RUVg uplift (Cr - C) is
reported with a PAIRED gene-bootstrap CI (same resampled genes score both arms),
so "does RUVg help" is answered with uncertainty, not a 3rd-decimal point
estimate. A uplift CI straddling 0 == no evidence RUVg moves the arm toward A.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import pearsonr

WORK = Path(os.environ.get("DGE_CALIB_WORK", "/home/sagemaker-user/dge_calib_work"))
HERE = Path(__file__).resolve().parent
OUT = Path(os.environ.get("DGE_MA_OUT", HERE.parent / "outputs" / "multi_anchor"))
OUT.mkdir(parents=True, exist_ok=True)

SUBSTRATES = tuple(s for s in os.environ.get("DGE_CALIB_SUBSTRATES", "recount3").split(",") if s)
INDICATIONS = tuple(i for i in os.environ.get("DGE_CALIB_INDICATIONS", "brca,kirc,luad,lusc,prad,coad").split(",") if i)

LFC_GATE = math.log2(1.5)  # 0.585 — apeglm lfcThreshold
SVAL_Q = 0.005
PADJ_Q = 0.05
NULL_PADJ = 0.5  # A "clearly null": high padj ...
NULL_LFC = LFC_GATE  # ... and sub-threshold effect
N_BOOT = 1000
RNG = np.random.default_rng(20260920)


def load_cell(cell_dir: Path, label: str) -> pd.DataFrame | None:
    p = cell_dir / f"cell_{label}.tsv"
    if not p.exists():
        return None
    return pd.read_csv(p, sep="\t").set_index("gene_symbol")


def sig_mask(df: pd.DataFrame) -> pd.Series:
    """Shipped gate: s-value<0.005 & |lfc|>=gate, padj fallback where svalue NA."""
    lfc = df["log2fc"]
    sval = df["svalue"] if "svalue" in df else pd.Series(np.nan, index=df.index)
    by_s = sval.notna() & (sval < SVAL_Q)
    by_p = sval.isna() & df["padj"].notna() & (df["padj"] < PADJ_Q)
    return (by_s | by_p) & lfc.notna() & (lfc.abs() >= LFC_GATE)


def null_mask(A: pd.DataFrame) -> pd.Series:
    return A["padj"].notna() & (A["padj"] > NULL_PADJ) & A["log2fc"].notna() & (A["log2fc"].abs() < NULL_LFC)


def boot_ci(stat_fn, n: int, reps: int = N_BOOT) -> tuple[float, float]:
    """Percentile 95% CI of stat_fn over gene-index bootstrap resamples."""
    if n < 10:
        return (float("nan"), float("nan"))
    vals = []
    for _ in range(reps):
        idx = RNG.integers(0, n, n)
        v = stat_fn(idx)
        if v == v:
            vals.append(v)
    if len(vals) < reps // 2:
        return (float("nan"), float("nan"))
    return (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5)))


def _fpr(m_sig: np.ndarray, idx: np.ndarray) -> float:
    return float(m_sig[idx].mean()) if len(idx) else float("nan")


def _sign_conc(sa: np.ndarray, sm: np.ndarray, idx: np.ndarray) -> float:
    return float((sa[idx] == sm[idx]).mean()) if len(idx) else float("nan")


def _corr(a: np.ndarray, m: np.ndarray, idx: np.ndarray) -> float:
    aa, mm = a[idx], m[idx]
    if len(aa) < 3 or np.std(aa) == 0 or np.std(mm) == 0:
        return float("nan")
    return float(pearsonr(aa, mm)[0])


def score(cells: dict) -> dict:
    A = cells.get("A")
    out: dict = {"cells_ran": sorted(cells)}
    if A is None:
        out["note"] = "no cell-A anchor"
        return out
    a_sig = A.index[sig_mask(A)]
    a_null = A.index[null_mask(A)]
    out["n_A_sig"] = int(len(a_sig))
    out["n_A_null"] = int(len(a_null))

    for label in ("C", "Cr"):
        M = cells.get(label)
        if M is None:
            continue
        m_is_sig = sig_mask(M)

        # --- FPR vs anchor-null ---
        null_shared = a_null.intersection(M.index)
        msig = m_is_sig.reindex(null_shared).fillna(False).to_numpy()
        n = len(null_shared)
        out[f"fpr_{label}"] = _fpr(msig, np.arange(n)) if n else float("nan")
        lo, hi = boot_ci(lambda ix: _fpr(msig, ix), n)
        out[f"fpr_{label}_ci"] = [lo, hi]
        out[f"n_null_shared_{label}"] = n

        # --- sign-concordance on A-sig ---
        sig_shared = a_sig.intersection(M.index)
        sa = np.sign(A.loc[sig_shared, "log2fc"].to_numpy())
        sm = np.sign(M.loc[sig_shared, "log2fc"].to_numpy())
        both = (sa != 0) & (sm != 0)
        sa_b, sm_b = sa[both], sm[both]
        nb = len(sa_b)
        out[f"sign_conc_{label}"] = _sign_conc(sa_b, sm_b, np.arange(nb)) if nb else float("nan")
        lo, hi = boot_ci(lambda ix: _sign_conc(sa_b, sm_b, ix), nb)
        out[f"sign_conc_{label}_ci"] = [lo, hi]
        out[f"n_A_sig_shared_{label}"] = nb

        # --- effect-size correlation on A-sig ---
        la = A.loc[sig_shared, "log2fc"].to_numpy()
        lm = M.loc[sig_shared, "log2fc"].to_numpy()
        fin = np.isfinite(la) & np.isfinite(lm)
        la_f, lm_f = la[fin], lm[fin]
        nf = len(la_f)
        out[f"eff_corr_{label}"] = _corr(la_f, lm_f, np.arange(nf)) if nf else float("nan")
        lo, hi = boot_ci(lambda ix: _corr(la_f, lm_f, ix), nf)
        out[f"eff_corr_{label}_ci"] = [lo, hi]

    # --- RUVg uplift (Cr - C) with PAIRED gene-bootstrap CIs ---
    C, Cr = cells.get("C"), cells.get("Cr")
    if C is not None and Cr is not None:
        c_sig, cr_sig = sig_mask(C), sig_mask(Cr)
        # FPR uplift on genes null-in-A and present in BOTH arms (paired)
        ns = a_null.intersection(C.index).intersection(Cr.index)
        cm = c_sig.reindex(ns).fillna(False).to_numpy()
        crm = cr_sig.reindex(ns).fillna(False).to_numpy()
        n = len(ns)
        if n >= 10:
            out["fpr_uplift_Cr_minus_C"] = float(crm.mean() - cm.mean())
            diffs = []
            for _ in range(N_BOOT):
                ix = RNG.integers(0, n, n)
                diffs.append(float(crm[ix].mean() - cm[ix].mean()))
            out["fpr_uplift_ci"] = [float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))]
        # sign-concordance uplift on A-sig genes present in BOTH arms (paired)
        ss = a_sig.intersection(C.index).intersection(Cr.index)
        saa = np.sign(A.loc[ss, "log2fc"].to_numpy())
        sc = np.sign(C.loc[ss, "log2fc"].to_numpy())
        scr = np.sign(Cr.loc[ss, "log2fc"].to_numpy())
        both = (saa != 0) & (sc != 0) & (scr != 0)
        saa, sc, scr = saa[both], sc[both], scr[both]
        n = len(saa)
        if n >= 10:
            agree_c = saa == sc
            agree_cr = saa == scr
            out["sign_conc_uplift_Cr_minus_C"] = float(agree_cr.mean() - agree_c.mean())
            diffs = []
            for _ in range(N_BOOT):
                ix = RNG.integers(0, n, n)
                diffs.append(float(agree_cr[ix].mean() - agree_c[ix].mean()))
            out["sign_conc_uplift_ci"] = [float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))]
    return out


def fmt(v) -> str:
    if isinstance(v, float):
        return "n/a" if v != v else f"{v:.3f}"
    return str(v)


def ci(d: dict, key: str) -> str:
    c = d.get(key)
    if not c or any(x != x for x in c):
        return ""
    return f" [{c[0]:.3f},{c[1]:.3f}]"


def straddles_zero(d: dict, key: str) -> bool | None:
    c = d.get(key)
    if not c or any(x != x for x in c):
        return None
    return c[0] <= 0 <= c[1]


def main() -> None:
    rows, prov = {}, {}
    for sub in SUBSTRATES:
        for ind in INDICATIONS:
            cd = WORK / f"cells__{sub}__{ind}"
            cells = {lab: load_cell(cd, lab) for lab in ("A", "C", "Cr")}
            cells = {k: v for k, v in cells.items() if v is not None}
            if not cells:
                continue
            rows[f"{sub}/{ind}"] = score(cells)
            p = cd / "provenance.json"
            if p.exists():
                prov[f"{sub}/{ind}"] = json.loads(p.read_text())

    summary = {
        "metric_defs": {
            "gate": f"|log2FC|>={LFC_GATE:.3f} & (svalue<{SVAL_Q} | padj<{PADJ_Q} fallback)",
            "anchor_null": f"A padj>{NULL_PADJ} & |lfc_A|<{NULL_LFC:.3f}",
            "n_boot": N_BOOT,
            "substrates": list(SUBSTRATES),
            "indications": list(INDICATIONS),
        },
        "per_cell": rows,
        "provenance": prov,
    }
    (OUT / "multi_anchor_summary.json").write_text(json.dumps(summary, indent=2, default=str))

    L = [
        "# Multi-anchor RUVg calibration — rebuilt metric (recount3)\n",
        "Authorized re-run after the 2026-09-20 four-agent review found the k=2 "
        "study's whole-genome Spearman ρ metric insensitive to the sign-flips and "
        "significance-inflation that matter. Scored vs the within-TCGA cell-A anchor "
        "at the shipped effect gate; every statistic carries a gene-bootstrap 95% CI; "
        "the RUVg uplift (Cr−C) uses a PAIRED bootstrap.\n",
        f"- gate: |log2FC|≥{LFC_GATE:.3f} & svalue<{SVAL_Q} (padj<{PADJ_Q} fallback)  ·  "
        f"anchor-null: padj_A>{NULL_PADJ} & |lfc_A|<{NULL_LFC:.3f}  ·  boot={N_BOOT}\n",
    ]

    L.append("\n## Anchor power (cell A)\n")
    L.append("| substrate/ind | n_tumor | n_adjacent | n_gtex | n A-sig | n A-null |")
    L.append("|---|--:|--:|--:|--:|--:|")
    for key, r in rows.items():
        pv = prov.get(key, {})
        L.append(
            f"| {key} | {pv.get('n_tumor', '?')} | {pv.get('n_adjacent', '?')} | "
            f"{pv.get('n_gtex', '?')} | {fmt(r.get('n_A_sig'))} | {fmt(r.get('n_A_null'))} |"
        )

    L.append("\n## FPR vs anchor-null (lower = less confound inflation)\n")
    L.append("| substrate/ind | FPR C [95% CI] | FPR Cr [95% CI] | uplift Cr−C [95% CI] | RUVg helps? |")
    L.append("|---|--:|--:|--:|:--|")
    for key, r in rows.items():
        up = r.get("fpr_uplift_Cr_minus_C")
        sz = straddles_zero(r, "fpr_uplift_ci")
        # for FPR, "helps" = uplift significantly < 0
        verdict = "no (CI⊃0)" if sz else ("yes" if (up is not None and up < 0) else "worse") if sz is False else "n/a"
        L.append(
            f"| {key} | {fmt(r.get('fpr_C'))}{ci(r, 'fpr_C_ci')} | "
            f"{fmt(r.get('fpr_Cr'))}{ci(r, 'fpr_Cr_ci')} | "
            f"{fmt(up)}{ci(r, 'fpr_uplift_ci')} | {verdict} |"
        )

    L.append("\n## Sign-concordance on A-significant genes (higher = better)\n")
    L.append("| substrate/ind | sign-conc C [95% CI] | sign-conc Cr [95% CI] | uplift Cr−C [95% CI] | RUVg helps? |")
    L.append("|---|--:|--:|--:|:--|")
    for key, r in rows.items():
        up = r.get("sign_conc_uplift_Cr_minus_C")
        sz = straddles_zero(r, "sign_conc_uplift_ci")
        verdict = "no (CI⊃0)" if sz else ("yes" if (up is not None and up > 0) else "worse") if sz is False else "n/a"
        L.append(
            f"| {key} | {fmt(r.get('sign_conc_C'))}{ci(r, 'sign_conc_C_ci')} | "
            f"{fmt(r.get('sign_conc_Cr'))}{ci(r, 'sign_conc_Cr_ci')} | "
            f"{fmt(up)}{ci(r, 'sign_conc_uplift_ci')} | {verdict} |"
        )

    L.append("\n## Effect-size correlation on A-significant genes (Pearson, higher = better)\n")
    L.append("| substrate/ind | eff-corr C [95% CI] | eff-corr Cr [95% CI] |")
    L.append("|---|--:|--:|")
    for key, r in rows.items():
        L.append(
            f"| {key} | {fmt(r.get('eff_corr_C'))}{ci(r, 'eff_corr_C_ci')} | "
            f"{fmt(r.get('eff_corr_Cr'))}{ci(r, 'eff_corr_Cr_ci')} |"
        )

    L.append(
        "\n_Generated by `scripts/multi_anchor_report.py`. Companion to the "
        "hand-authored NEGATIVE verdict in `outputs/calibration_report.md`; this "
        "file quantifies that verdict across adequately-powered anchors._\n"
    )

    (OUT / "multi_anchor_calibration.md").write_text("\n".join(L))
    print(f"wrote {OUT / 'multi_anchor_calibration.md'} and multi_anchor_summary.json")
    print("\n".join(L))


if __name__ == "__main__":
    main()
