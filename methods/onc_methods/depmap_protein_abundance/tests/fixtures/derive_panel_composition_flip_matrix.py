"""Build the committed fixture + measurement record for #2223."""

import gzip
import json
import os
import subprocess

import numpy as np
import pandas as pd

from onc_methods.depmap_protein_abundance import cli

OUT = "methods/onc_methods/depmap_protein_abundance/tests/fixtures"
os.makedirs(OUT, exist_ok=True)

df = pd.read_csv("/tmp/p2223/gygi.csv", index_col=0)
mdl = pd.read_csv("/tmp/p2223/Model.csv", usecols=["ModelID", "OncotreeLineage"])
lin_map = dict(zip(mdl["ModelID"], mdl["OncotreeLineage"]))
X = df.to_numpy(dtype=float)
cols = list(df.columns)
rows = list(df.index)
lineages = np.array([lin_map.get(m) or "unknown" for m in rows])
null_full = np.nanmedian(X, axis=0)

ANCHOR_ACC = {
    "CEACAM5": "P06731",
    "EPCAM": "P16422",
    "ERBB2": "P04626",
    "ACTB": "P60709",
    "GAPDH": "P04406",
    "GYPA": "P02724",
}
colidx = {c: i for i, c in enumerate(cols)}

# stratified-by-median sample so the fixture's own all-protein null keeps the real shape
order = np.argsort(null_full)
step = max(1, len(order) // 294)
sample = list(order[::step][:294])
keep = sorted(set(sample) | {colidx[a] for a in ANCHOR_ACC.values()})
sub_cols = [cols[j] for j in keep]
sub = df[sub_cols]
print("fixture shape", sub.shape)

buf = sub.to_csv(index=True, float_format="%.6g").encode()
with open(f"{OUT}/gygi_measured_submatrix.csv.gz", "wb") as raw:
    with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=9, mtime=0) as fh:
        fh.write(buf)
print("submatrix bytes", os.path.getsize(f"{OUT}/gygi_measured_submatrix.csv.gz"))
json.dump(
    {m: (lin_map.get(m) or "unknown") for m in rows},
    open(f"{OUT}/gygi_submatrix_lineages.json", "w"),
    indent=1,
    sort_keys=True,
)

# ---- re-read the committed fixture and derive the ORACLE block from it (round-trip safe)
fx = pd.read_csv(f"{OUT}/gygi_measured_submatrix.csv.gz", index_col=0)
FX = fx.to_numpy(dtype=float)
fx_rows = list(fx.index)
fx_lin = np.array([lin_map.get(m) or "unknown" for m in fx_rows])
fx_null = [float(v) for v in np.nanmedian(FX, axis=0)]
fx_cut = cli._quantile(fx_null, cli.HIGH_ABUNDANCE_PERCENTILE)
print("fixture cutoff p70 =", fx_cut, " production =", cli._quantile([float(v) for v in null_full], 0.70))


def summary_for(j, rowsel, cutoff):
    v = FX[rowsel, j]
    m = ~np.isnan(v)
    if m.sum() == 0:
        return None
    ab = {fx_rows[rowsel[i]]: float(v[i]) for i in np.nonzero(m)[0]}
    lb = {fx_rows[rowsel[i]]: fx_lin[rowsel[i]] for i in range(len(rowsel))}
    return cli.compute_summary(
        "X",
        ab,
        lb,
        n_panel=len(rowsel),
        all_protein_medians=tuple(float(x) for x in np.nanmedian(FX[rowsel, :], axis=0)),
    )


ALLR = np.arange(len(fx_rows))
fx_ci = {c: i for i, c in enumerate(fx.columns)}
anchors_fx = {}
for sym, accn in ANCHOR_ACC.items():
    s = summary_for(fx_ci[accn], ALLR, fx_cut)
    anchors_fx[sym] = {
        "accession": accn,
        "protein_expression_class": s["protein_expression_class"],
        "fraction_detected": s["fraction_detected"],
        "median_log2_abundance_panel": s["median_log2_abundance_panel"],
        "n_cell_lines_evaluated": s["n_cell_lines_evaluated"],
    }
    print(sym, anchors_fx[sym])

# which leave-one-lineage-out arm moves the most fixture proteins?
lc = pd.Series(fx_lin).value_counts()
base_cls = []
for j in range(FX.shape[1]):
    s = summary_for(j, ALLR, fx_cut)
    base_cls.append(None if s is None else s["protein_expression_class"])
loo = []
for L, n in lc.items():
    if n < 10:
        continue
    idx = np.nonzero(fx_lin != L)[0]
    nl = [float(x) for x in np.nanmedian(FX[idx, :], axis=0)]
    c = cli._quantile(nl, cli.HIGH_ABUNDANCE_PERCENTILE)
    mv = []
    for j in range(FX.shape[1]):
        s = summary_for(j, idx, c)
        k = None if s is None else s["protein_expression_class"]
        if k != base_cls[j]:
            mv.append({"accession": fx.columns[j], "from": base_cls[j], "to": k})
    loo.append(
        {
            "dropped_lineage": L,
            "n_dropped": int(n),
            "n_models": int(len(idx)),
            "cutoff": round(float(c), 8),
            "n_movers": len(mv),
            "movers": mv[:12],
        }
    )
    print(loo[-1]["dropped_lineage"], loo[-1]["n_movers"], loo[-1]["cutoff"])

prod = json.load(open("/tmp/p2223/result.json"))
prod2 = json.load(open("/tmp/p2223/result2.json"))
script = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

record = {
    "_meta": {
        "issue": "#2223",
        "epic": "#2210",
        "purpose": (
            "Flip matrix for the protein panel-relative p70 HIGH cut (HIGH_ABUNDANCE_PERCENTILE=0.70) "
            "vs the RNA twin's absolute cuts. Arm A = status-quo rules on the full live panel; arm B = "
            "the SAME rules on a re-composed panel (the issue's explicit ask: run the matrix across "
            "PANEL COMPOSITIONS, not just targets), plus two rule counterfactuals. "
            "NO THRESHOLD WAS CHANGED by this matrix -- see the adjudication on #2223."
        ),
        "source": {
            "bucket": "onc-compbio",
            "matrix_key": cli.MATRIX_KEY,
            "model_key": cli.MODEL_KEY,
            "target_resolution_key": cli.SIDECAR_KEY,
            "release": "DepMap 26Q1 (harmonized Gygi TMT MS)",
            "matrix_bytes": 63756333,
            "n_models": 375,
            "n_proteins": 12558,
        },
        "repo_commit_at_measurement": script,
        "measured": "2026-09-30",
        "reproduce": (
            "aws s3 cp the three keys above to /tmp/p2223/, then "
            "`pixi run python methods/onc_methods/depmap_protein_abundance/tests/fixtures/"
            "derive_panel_composition_flip_matrix.py`"
        ),
        "production_block_is_a_test_oracle": False,
        "production_block_note": (
            "`production_measurement` records a LIVE measurement over data too large to commit; no test "
            "asserts on it (a fixture of derived values can never fail). The oracle is "
            "`fixture_expectations`, which the test RE-DERIVES from the committed RAW values in "
            "gygi_measured_submatrix.csv.gz through the real cli functions."
        ),
    },
    "production_measurement": {
        "what_each_constant_cuts": {
            "protein_class_cutoff": {
                "constant": "HIGH_ABUNDANCE_PERCENTILE = 0.70",
                "site": "methods/onc_methods/depmap_protein_abundance/cli.py:87,555",
                "quantity": "rank position (dimensionless) of the target's PANEL-MEDIAN log2 abundance "
                "within the distribution of ALL 12558 proteins' panel medians",
                "unit_of_the_distribution_cut": "harmonized Gygi TMT log2 ratio",
                "measured_cut_level_log2": prod2["cut_A"],
            },
            "protein_display_reference_line": {
                "constant": "HIGH_ABUNDANCE_PERCENTILE = 0.70 (same constant, different population)",
                "site": "methods/onc_methods/depmap_protein_abundance/cli.py:686 (_panel_high_cutoff); "
                "drawn at cli.py:758, 837, 922",
                "quantity": "rank position of ONE cell line within THE TARGET'S OWN detected values",
                "share_of_plotted_points_at_or_above_it": prod["display_line_share_above"],
            },
            "rna_twin_absolute_cut": {
                "constant": "highly_expressed_threshold = 5.0",
                "site": "methods/onc_methods/depmap_expression_distribution/cli.py:243,346",
                "quantity": "an ABSOLUTE level in log2(TPM+1) applied per cell line, then fractioned "
                "at frac_highly >= 0.30",
                "unit": "log2_tpm_plus_1",
            },
        },
        "gygi_scale_is_per_protein_centred": {
            "sd_of_per_protein_means": 0.125811,
            "sd_of_per_protein_medians": prod2["null_sd"],
            "median_within_protein_sd_across_cell_lines": prod2["within_protein_median_sd"],
            "ratio_between_over_within": round(prod2["null_sd"] / prod2["within_protein_median_sd"], 4),
            "share_of_proteins_with_abs_median_le_0_01": 0.1046,
            "share_of_proteins_with_abs_median_le_0_05": 0.4513,
            "null_quantiles_log2": prod2["null_quantiles"],
        },
        "published_null_sidecar_agrees_with_matrix_pass": {
            "sidecar_p70": prod2["cut_live_sidecar"],
            "matrix_column_median_pass_p70": prod2["cut_A"],
            "delta": 0.0,
        },
        "arm_A": prod["arm_A"],
        "panel_composition_arms": prod["panel_composition_arms"],
        "rule_counterfactuals": prod["rule_counterfactuals"],
        "control_anchors_arm_A": prod2["anchors_arm_A"],
        "control_anchor_flips_across_18_panel_arms": prod2["anchor_flips"],
    },
    "fixture_expectations": {
        "_note": "Derived FROM the committed raw sub-matrix (its own 300-protein all-protein null), not "
        "from the production null. These ARE oracles; the test re-derives them.",
        "submatrix": {
            "file": "gygi_measured_submatrix.csv.gz",
            "lineage_map": "gygi_submatrix_lineages.json",
            "n_models": int(FX.shape[0]),
            "n_proteins": int(FX.shape[1]),
            "sha256_of_decompressed_csv": __import__("hashlib").sha256(buf).hexdigest(),
            "decompressed_bytes": len(buf),
            "sampling": "stratified every-Nth by production panel-median so the fixture's own "
            "all-protein null keeps the real distribution shape, plus the 6 "
            "resolvable tumor_presence_controls anchors",
        },
        "arm_A_cutoff_p70": float(fx_cut),
        "control_anchors": anchors_fx,
        "leave_one_lineage_out_arms": loo,
    },
}
json.dump(record, open(f"{OUT}/gygi_panel_composition_flip_matrix.json", "w"), indent=2, sort_keys=False)
print(
    "wrote",
    f"{OUT}/gygi_panel_composition_flip_matrix.json",
    os.path.getsize(f"{OUT}/gygi_panel_composition_flip_matrix.json"),
)
