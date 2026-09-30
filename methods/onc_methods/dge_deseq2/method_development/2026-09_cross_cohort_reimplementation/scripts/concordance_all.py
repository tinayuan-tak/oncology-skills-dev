"""Panel-wide within-cohort (A) vs cross-cohort (C) concordance for every fused
sensitivity product that has both arms live. Quantifies how systematic the
TCGA-vs-GTEx confound is. Read-only.

Writes concordance_all.json to <OUT> (DGE_QC_OUT, default this arc's outputs/).
Resolves the data-catalog manifests from DATA_CATALOG_ROOT (default the canonical
sibling clone). Run on demand, NOT a unit test."""

import glob
import io
import os
from pathlib import Path

os.environ.pop("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", None)
import boto3
import numpy as np
import pandas as pd
import yaml

cli = boto3.Session(profile_name="cbg").client("s3")
BUCKET = "onc-compbio"
OUT = os.environ.get("DGE_QC_OUT") or str(Path(__file__).resolve().parent.parent / "outputs")
os.makedirs(OUT, exist_ok=True)
# Portable sibling default (env DATA_CATALOG_ROOT override) — never a hardcoded
# /home/sagemaker-user literal (SK#2137: that literal is the ARCHIVED pre-merge clone
# location). methods.roots.data_catalog_root() is anchored from its own location, so this
# script's own depth under method_development/.../scripts/ no longer needs its own parents[6].
from onc_methods.roots import data_catalog_root

base = str(data_catalog_root())

rows = []
for f in sorted(glob.glob(base + "/manifests/derived/*.yaml")):
    m = yaml.safe_load(open(f).read())
    if not isinstance(m, dict):
        continue
    mid = m.get("id", "")
    if "dge-tumor-vs-normal-sensitivity" not in mid:
        continue
    if "by-subgroup" in mid:
        continue  # stratified, different grain
    uri = m.get("s3_uri")
    if not uri:
        continue
    key = uri.replace(f"s3://{BUCKET}/", "")
    try:
        df = pd.read_parquet(io.BytesIO(cli.get_object(Bucket=BUCKET, Key=key)["Body"].read()))
    except Exception as e:
        rows.append({"id": mid, "err": str(e)[:60]})
        continue
    have_A = "log2fc_A" in df and df["log2fc_A"].notna().any()
    have_C = "log2fc_C" in df and df["log2fc_C"].notna().any()
    r = dict(
        id=mid.replace("-dge-tumor-vs-normal-sensitivity-v1", ""),
        n=len(df),
        sig_A=round(float((df["padj_A"] < 0.05).mean()), 3) if "padj_A" in df and have_A else None,
        sig_C=round(float((df["padj_C"] < 0.05).mean()), 3) if "padj_C" in df and have_C else None,
        medlfc_C=round(float(np.nanmedian(df["log2fc_C"].abs())), 3) if have_C else None,
    )
    if have_A and have_C:
        m2 = df["log2fc_A"].notna() & df["log2fc_C"].notna()
        a, c = df["log2fc_A"][m2], df["log2fc_C"][m2]
        r["pearson_AC"] = round(float(np.corrcoef(a, c)[0, 1]), 3)
        # sign-discordance among genes significant in EITHER arm
        sigeither = ((df["padj_A"] < 0.05) | (df["padj_C"] < 0.05)) & m2
        r["signflip_sig"] = (
            round(float((np.sign(a[sigeither]) != np.sign(c[sigeither])).mean()), 3) if sigeither.sum() else None
        )
    else:
        r["pearson_AC"] = None
        r["signflip_sig"] = None
    rows.append(r)

tab = pd.DataFrame(rows)
tab = tab.sort_values("pearson_AC", na_position="last")
pd.set_option("display.width", 160)
pd.set_option("display.max_rows", 60)
print(tab.to_string(index=False))
tab.to_json(f"{OUT}/concordance_all.json", orient="records", indent=2)

both = tab[tab.pearson_AC.notna()]
print("\n--- both-comparators products (n=%d) ---" % len(both))
print("median Pearson A-vs-C:", round(both.pearson_AC.median(), 3))
print("median sig_C:", round(both.sig_C.median(), 3), " median sig_A:", round(both.sig_A.median(), 3))
print("products with r<0.5:", list(both[both.pearson_AC < 0.5].id))
print("\n--- gtex-only / adjacent-only (no within-cohort control) ---")
print(tab[tab.pearson_AC.isna()][["id", "n", "sig_A", "sig_C", "medlfc_C"]].to_string(index=False))
