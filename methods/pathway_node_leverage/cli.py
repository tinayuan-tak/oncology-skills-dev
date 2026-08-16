#!/usr/bin/env python3
"""pathway_node_leverage — is the target the best NODE to hit, or is it dominated by a more-dependent /
more-tractable member of its neighbourhood?

A COMPARATIVE (not target-intrinsic) facet: every other card asks "is X dependent/altered/tractable?";
this asks "given the biology, is X the best intervention point, or a dominated node?" (the MARK2/3 vs
YAP/TAZ motivating case). SOFT, verdict-INERT context: never a killer, never raises certainty (it is
DepMap-Chronos-derived, correlated with the dependency cards). Feeds the differentiation axis.

Node-set is a LENS (precision/recall gradient); this module implements two, all sources pinned:
  - complex : CORUM 5.3 co-complex members            (tightest; "wrong subunit?")
  - pathway : MSigDB C5 GO:BP gene set                 (functional; high recall / noisy)
Deferred (spec §7): curated-pathway (C2.CP Reactome/KEGG), PPI (STRING/BioGRID), directed acts-through.

Corrections (spec §2, each validated on live data): common-essential exclusion (else VCP/AARS1 crown
themselves); tractability-yield via Pharos TDL (a druggable dominated node beats an undruggable
rate-limiting one); noise-separation gate. LINEAGE-SCOPED: Chronos is restricted to the indication's
DepMap OncotreeLineage cohort (pan-lineage fallback when the cohort is thin, flagged).

See docs/design/PATHWAY_NODE_LEVERAGE_SPEC.md (target-contracts). tier: comparative.

STATUS: first productionized cut. Loaders are live-read (need cbg); MSigDB reads the GMT bundle zip
(a derived gene-set-membership product would be cleaner — build-order item 5). Card/resolver/skill
wiring + full tests are the continuation.
"""
from __future__ import annotations

import io
import json
import zipfile
from functools import lru_cache
from typing import Optional

import pandas as pd

from methods.target_id_sidecar import s3_client
from methods.depmap_chronos.cli import INDICATION_LINEAGE

METHOD_VERSION = "0.1.0"

_DMC = "data-catalog/sources/depmap-consortium/dmc-26q1/"
_SRC_CHRONOS = _DMC + "CRISPRGeneEffect.csv"
_SRC_MODEL = _DMC + "Model.csv"
_SRC_COMMON_ESS = _DMC + "CRISPRInferredCommonEssentials.csv"
_SRC_TDL = "data-catalog/sources/pharos-idg-tcrd/snapshot-2026-08-10/pharos_tdl_per_gene.parquet"
_SRC_CORUM = "data-catalog/sources/corum/release-5.3-snapshot-2026-07-14/corum_complete.json"
_SRC_MSIGDB_ZIP = ("data-catalog/sources/msigdb/human-v2026-1-hs/"
                   "msigdb_v2026.1.Hs_files_to_download_locally.zip")
_MSIGDB_GMT_IN_ZIP = ("msigdb_v2026.1.Hs_files_to_download_locally/msigdb_v2026.1.Hs_GMTs/"
                      "c5.go.bp.v2026.1.Hs.symbols.gmt")
_BUCKET = "onc-compbio"

DEP_FLOOR = -0.5          # a node must clear this median Chronos to be dependency-relevant
MIN_SEP = 0.15           # min median-Chronos separation to call one node stronger (vs screen noise)
MIN_COHORT = 15          # min lineage cell lines before we trust lineage-scoped medians; else pan-lineage
_TDL_RANK = {"Tclin": 0, "Tchem": 1, "Tbio": 2, "Tdark": 3}


# --- pinned-source loaders (live-read; boto3 via shared client) --------------------------------------
def _get(key: str) -> bytes:
    return s3_client().get_object(Bucket=_BUCKET, Key=key)["Body"].read()


@lru_cache(maxsize=1)
def _chronos() -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(_get(_SRC_CHRONOS)), index_col=0)
    df.columns = [c.split(" ")[0] for c in df.columns]       # 'GENE (id)' -> 'GENE'
    return df


@lru_cache(maxsize=1)
def _model_lineage() -> dict:
    m = pd.read_csv(io.BytesIO(_get(_SRC_MODEL)))
    col = "OncotreeLineage" if "OncotreeLineage" in m.columns else "lineage"
    return dict(zip(m["ModelID"], m[col]))


@lru_cache(maxsize=1)
def _common_essentials() -> frozenset:
    df = pd.read_csv(io.BytesIO(_get(_SRC_COMMON_ESS)))
    return frozenset(df.iloc[:, 0].astype(str).str.split(" ").str[0])


@lru_cache(maxsize=1)
def _tdl() -> dict:
    t = pd.read_parquet(io.BytesIO(_get(_SRC_TDL)))
    return dict(zip(t["gene_symbol"], t["tdl"]))


@lru_cache(maxsize=1)
def _corum() -> list:
    return json.loads(_get(_SRC_CORUM))


@lru_cache(maxsize=1)
def _go_bp_gmt() -> dict:
    """gene_set_name -> [member symbols], from the MSigDB C5 GO:BP GMT inside the pinned bundle zip."""
    zf = zipfile.ZipFile(io.BytesIO(_get(_SRC_MSIGDB_ZIP)))
    out = {}
    with zf.open(_MSIGDB_GMT_IN_ZIP) as fh:
        for line in io.TextIOWrapper(fh, "utf-8"):
            f = line.rstrip("\n").split("\t")
            if len(f) > 2:
                out[f[0]] = f[2:]
    return out


# --- node-set lenses --------------------------------------------------------------------------------
def _complex_node_sets(target: str) -> list:
    out = []
    for c in _corum():
        if c.get("organism") != "Human":
            continue
        members = [(s.get("swissprot") or {}).get("gene_name") for s in (c.get("subunits") or [])]
        members = sorted({m for m in members if m})
        if target in members:
            out.append({"name": c.get("complex_name"), "members": members})
    return out


def _pathway_node_sets(target: str) -> list:
    gmt = _go_bp_gmt()
    hits = [(name, members) for name, members in gmt.items() if target in members]
    hits.sort(key=lambda x: len(x[1]))            # specificity: smallest (most-specific) set first
    return [{"name": n, "members": m} for n, m in hits[:1]]   # most-specific containing set


# --- lineage-scoped comparison ----------------------------------------------------------------------
def _model_ids_for_lineage(lineage: Optional[str]) -> Optional[list]:
    if not lineage:
        return None
    lm = _model_lineage()
    ids = [mid for mid, ln in lm.items() if ln == lineage]
    return ids if len(ids) >= MIN_COHORT else None


def _stats(genes: list, target: str, model_ids: Optional[list]) -> pd.DataFrame:
    df = _chronos()
    cols = [g for g in (set(genes) | {target}) if g in df.columns]
    sub = df[cols]
    if model_ids:
        sub = sub.loc[sub.index.isin(model_ids)]
    rows = []
    for g in cols:
        v = sub[g].dropna()
        if len(v) < 5:
            continue
        rows.append({"gene": g, "median_chronos": float(v.median()),
                     "frac_dependent": float((v < DEP_FLOOR).mean()), "n": int(len(v))})
    stats = pd.DataFrame(rows)
    if stats.empty:
        return stats
    ce = _common_essentials()
    stats = stats[(~stats["gene"].isin(ce)) | (stats["gene"] == target)]
    tdl = _tdl()
    stats["tdl"] = stats["gene"].map(tdl).fillna("unknown")
    stats["trank"] = stats["tdl"].map(_TDL_RANK).fillna(9)
    return stats.sort_values("median_chronos")


def _classify(target: str, stats: pd.DataFrame) -> dict:
    if stats.empty or target not in set(stats["gene"]):
        return {"verdict": "target_not_screenable", "n_nodes": int(len(stats))}
    tgt = stats[stats["gene"] == target].iloc[0]
    stronger = stats[stats["median_chronos"] < tgt["median_chronos"] - MIN_SEP]
    tractable_stronger = stronger[stronger["trank"] <= tgt["trank"]]
    if tgt["median_chronos"] > DEP_FLOOR and stronger.empty:
        verdict = "weak_and_uncontested"
    elif stronger.empty:
        verdict = "dominant_node"
    elif tractable_stronger.empty:
        verdict = "dominated_but_tractability_edge"
    else:
        verdict = "dominated_node"
    return {
        "verdict": verdict, "n_nodes": int(len(stats)),
        "target_median_chronos": round(float(tgt["median_chronos"]), 3),
        "target_tdl": str(tgt["tdl"]), "target_frac_dependent": round(float(tgt["frac_dependent"]), 3),
        "n_stronger": int(len(stronger)), "n_stronger_tractable": int(len(tractable_stronger)),
        "dominant_competitors": [
            {"gene": r["gene"], "median_chronos": round(r["median_chronos"], 3), "tdl": str(r["tdl"])}
            for _, r in stronger.head(6).iterrows()],
    }


# --- public entrypoint ------------------------------------------------------------------------------
def read_node_leverage(target: str, indication: Optional[str] = None) -> dict:
    """Per-lens node-leverage summary for the target, lineage-scoped to the indication's DepMap cohort."""
    if not target:
        return {"node_leverage_class": "data_unavailable", "_note": "target required."}
    lineage = INDICATION_LINEAGE.get(indication) if indication else None
    try:
        model_ids = _model_ids_for_lineage(lineage)
        scope = ("within_indication_lineage" if model_ids else
                 ("pan_lineage_thin_cohort" if lineage else "pan_lineage_no_indication"))
        lenses = {}
        for lens_name, node_sets in (("complex", _complex_node_sets(target)),
                                     ("pathway", _pathway_node_sets(target))):
            per = [{"node_set": ns["name"], "n_members": len(ns["members"]),
                    **_classify(target, _stats(ns["members"], target, model_ids))} for ns in node_sets]
            lenses[lens_name] = per
    except ImportError:
        raise
    except Exception as e:
        return {"node_leverage_class": "data_unavailable",
                "_live_read_error": f"{type(e).__name__}: {e}"}

    # headline class = the WORST (most-dominated) reachable verdict across lenses (soft context)
    order = {"dominated_node": 0, "dominated_but_tractability_edge": 1, "weak_and_uncontested": 2,
             "dominant_node": 3}
    verdicts = [p["verdict"] for lp in lenses.values() for p in lp if p.get("verdict") in order]
    headline = min(verdicts, key=lambda v: order[v]) if verdicts else "no_node_set"
    return {
        "node_leverage_class": headline,          # soft, verdict-inert context (no veto, no certainty lift)
        "evidence_scope": scope,
        "lenses": lenses,
        "_method_version": METHOD_VERSION,
        "_caveats": ["SOFT context: no veto, never raises certainty",
                     "paralog/combinatorial not corrected (TODO)",
                     "no directed acts-through check — undirected membership cannot ground direction (TODO)"],
    }
