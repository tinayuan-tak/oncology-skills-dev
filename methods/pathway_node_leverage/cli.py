#!/usr/bin/env python3
"""pathway_node_leverage — is the target the best NODE to hit, or is it dominated by a more-dependent /
more-tractable member of its neighbourhood?

A COMPARATIVE (not target-intrinsic) facet: every other card asks "is X dependent/altered/tractable?";
this asks "given the biology, is X the best intervention point, or a dominated node?" (the MARK2/3 vs
YAP/TAZ motivating case). SOFT, verdict-INERT context: never a killer, never raises certainty (it is
DepMap-Chronos-derived, correlated with the dependency cards). Feeds the differentiation axis.

Node-set is a LENS (precision/recall gradient); this module implements two, all sources pinned:
  - complex : CORUM 5.3 co-complex members            (tightest; "wrong subunit?"; robust)
  - pathway : MSigDB C2.CP curated canonical pathway PREFERRED (Reactome/KEGG/WP/BioCarta/PID),
              MSigDB C5 GO:BP fallback                 (functional; high recall / NOISY heuristic)
  - ppi     : BioGRID physical interactors (top-N by publications)  REPORT-ONLY (broadest/hairball;
              surfaced per-lens but EXCLUDED from the headline min-across-lenses — see read_node_leverage)
Paralog/combinatorial correction (spec §6): single_ko_leverage_understated flags a paralog-BUFFERED
target (reuses the pre-computed dual-KO buffering product) whose single-KO leverage understates its
dependency — additive/verdict-inert. Deferred: directed acts-through (SIGNOR/OmniPath) — not yet
needed (this method makes no directional 'acts-through' claim).

PATHWAY-LENS SELECTION IS HEURISTIC (panel-validated, not exact): gene<->gene-set membership is
many-to-many, so no auto-selector is clean across targets. We prefer curated C2.CP over GO:BP and the
smallest set within a size band (avoids niche sets like GOBP_RESPONSE_TO_IONOMYCIN AND generic
machinery); the selected set NAME is surfaced so the consumer can judge relevance. The complex lens is
the mechanistically trustworthy one. Do NOT tune this selector to a single motivating example.

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
from methods.depmap_paralog_aggregator.read import read_target_summary as _read_paralog_buffering
from methods.depmap_common.parquet import (
    _find_gene_column, _remote_schema_names, _remote_uri, _stream_table,
)

METHOD_VERSION = "0.1.0"

_DMC = "data-catalog/sources/depmap-consortium/dmc-26q1/"
_SRC_CHRONOS = _DMC + "CRISPRGeneEffect.csv"
_SRC_MODEL = _DMC + "Model.csv"
_SRC_COMMON_ESS = _DMC + "CRISPRInferredCommonEssentials.csv"
_SRC_TDL = "data-catalog/sources/pharos-idg-tcrd/snapshot-2026-08-10/pharos_tdl_per_gene.parquet"
_SRC_CORUM = "data-catalog/sources/corum/release-5.3-snapshot-2026-07-14/corum_complete.json"
_SRC_BIOGRID = ("data-catalog/derived/biogrid-physical-interactions-per-gene-v1/"
                "biogrid_physical_edges_per_gene.parquet")
_SRC_MSIGDB_ZIP = ("data-catalog/sources/msigdb/human-v2026-1-hs/"
                   "msigdb_v2026.1.Hs_files_to_download_locally.zip")
_MSIGDB_GMT_DIR = "msigdb_v2026.1.Hs_files_to_download_locally/msigdb_v2026.1.Hs_GMTs/"
# Pathway-lens gene-set collections, in spec-§3 PRECEDENCE order (curated first, functional second):
#   C2.CP  = curated canonical pathways (Reactome / KEGG / WikiPathways / BioCarta / PID) — tightest
#   C5.GOBP = GO biological-process gene sets — higher recall, noisier (peripheral regulators)
_MSIGDB_GMT_C2CP = _MSIGDB_GMT_DIR + "c2.cp.v2026.1.Hs.symbols.gmt"
_MSIGDB_GMT_C5BP = _MSIGDB_GMT_DIR + "c5.go.bp.v2026.1.Hs.symbols.gmt"
_BUCKET = "onc-compbio"

DEP_FLOOR = -0.5          # a node must clear this median Chronos to be dependency-relevant
MIN_SEP = 0.15           # min median-Chronos separation to call one node stronger (vs screen noise)
MIN_COHORT = 15          # min lineage cell lines before we trust lineage-scoped medians; else pan-lineage
PPI_TOP_N = 25           # cap the BioGRID interaction neighbourhood to the best-evidenced partners
                         # (the PPI lens is the broadest/hairball per spec §3 — bounded + REPORT-ONLY)
# Pathway node-set size band. A gene sits in MANY gene sets; the smallest containing set is almost always
# a niche/incidental one (e.g. CDK4 -> GOBP_RESPONSE_TO_IONOMYCIN), and the largest is generic machinery.
# Prefer the smallest set WITHIN [MIN,MAX] as a coarse "specific-but-not-niche" heuristic. This is a
# HEURISTIC, not a correctness guarantee — pathway-lens set-selection is inherently noisy (many-to-many
# gene<->set membership); the CORUM complex lens is the mechanistically robust one. Validated on a
# diverse target panel (CDK4/KRAS/EGFR/BRAF/MET/SMARCA4/TP53/AURKA): the band+curated-preference is
# materially less noisy than smallest-overall, but still imperfect — hence the pathway-lens caveat.
MIN_PATHWAY_SET = 15
MAX_PATHWAY_SET = 200
# MSigDB C2.CP subfamilies that are DISEASE-PERTURBATION cascades (host-pathogen signaling, oncogenic
# variant activation), NOT canonical "same signaling cassette" neighbourhoods — exclude by name prefix
# so a RAS-pathway target lands on KEGG_MEDICUS_REFERENCE_..._RAS_ERK_SIGNALING rather than
# KEGG_MEDICUS_PATHOGEN_HBV_.... Panel-validated (KRAS/EGFR/BRAF improve; nothing else regresses).
# This is a principled subfamily exclusion, not per-target tuning.
_PATHWAY_SET_EXCLUDE_PREFIXES = ("KEGG_MEDICUS_PATHOGEN", "KEGG_MEDICUS_VARIANT")
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
def _chronos_parquet_meta() -> tuple:
    """(uri, schema_names) of the gene-sorted CRISPRGeneEffect parquet product. Footer read once."""
    uri = _remote_uri("CRISPRGeneEffect.parquet")
    return uri, _remote_schema_names(uri)


def _chronos_subframe(genes) -> pd.DataFrame:
    """Chronos scores for `genes`, indexed by ModelID, with BARE-symbol columns (matching the
    whole-CSV loader's column labels).

    Column-projected read of the CRISPRGeneEffect parquet product: only the requested genes'
    column-chunks transit the wire, replacing the 563 MB whole-CSV download for a node set of
    ~15-200 genes (`get_chronos_column`-style pushdown, generalized to many columns). Falls back
    to slicing the whole-CSV loader when the parquet product is unreachable — preserving the
    sibling parquet-primary / CSV-fallback discipline (a transient/creds error there still routes
    to the CSV path, byte-identical to the old behavior)."""
    genes = set(genes)
    try:
        uri, schema = _chronos_parquet_meta()
        id_col = "ModelID" if "ModelID" in schema else schema[0]
        colmap = {}                                          # parquet 'GENE (id)' col -> bare 'GENE'
        for g in genes:
            c = _find_gene_column(schema, g)
            if c is not None and c not in colmap:
                colmap[c] = g
        if not colmap:
            return pd.DataFrame()
        tbl = _stream_table(uri, columns=[id_col, *colmap]).to_pandas()
        return tbl.set_index(id_col).rename(columns=colmap)
    except ImportError:
        raise
    except Exception:                                        # parquet product unreachable -> CSV fallback
        df = _chronos()
        return df[[g for g in genes if g in df.columns]]


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


def _parse_gmt(gmt_in_zip: str) -> dict:
    """gene_set_name -> [member symbols], from a named GMT inside the pinned MSigDB bundle zip."""
    zf = zipfile.ZipFile(io.BytesIO(_get(_SRC_MSIGDB_ZIP)))
    out = {}
    with zf.open(gmt_in_zip) as fh:
        for line in io.TextIOWrapper(fh, "utf-8"):
            f = line.rstrip("\n").split("\t")
            if len(f) > 2:
                out[f[0]] = f[2:]
    return out


@lru_cache(maxsize=1)
def _c2cp_gmt() -> dict:
    """MSigDB C2.CP curated canonical pathways (Reactome/KEGG/WikiPathways/BioCarta/PID)."""
    return _parse_gmt(_MSIGDB_GMT_C2CP)


@lru_cache(maxsize=1)
def _go_bp_gmt() -> dict:
    """MSigDB C5 GO:BP biological-process gene sets."""
    return _parse_gmt(_MSIGDB_GMT_C5BP)


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


def _select_in_band(gmt: dict, target: str) -> Optional[tuple]:
    """Smallest gene set containing `target` whose size is within [MIN,MAX] (specific-but-not-niche).
    Falls back to the smallest containing set of ANY size only if none lands in the band (so a target
    that lives only in tiny/huge sets still gets a node-set rather than nothing). Returns (name, members)
    or None if the target is in no set of this collection."""
    hits = [(name, members) for name, members in gmt.items()
            if target in members and not name.startswith(_PATHWAY_SET_EXCLUDE_PREFIXES)]
    if not hits:
        return None
    in_band = [h for h in hits if MIN_PATHWAY_SET <= len(h[1]) <= MAX_PATHWAY_SET]
    pool = in_band or hits
    return min(pool, key=lambda x: len(x[1]))


def _pathway_node_sets(target: str) -> list:
    """The single pathway node-set for the target, per spec §3 precedence: prefer a CURATED canonical
    pathway (MSigDB C2.CP: Reactome/KEGG/WikiPathways/BioCarta/PID), fall back to the functional GO:BP
    collection. Within each collection, pick the smallest set inside the size band (see MIN/MAX_PATHWAY_SET
    — the old 'smallest overall' grabbed niche/incidental sets like GOBP_RESPONSE_TO_IONOMYCIN). HEURISTIC:
    pathway-lens membership is many-to-many and noisy; the returned node-set's NAME is surfaced so the
    consumer can judge relevance, and the complex (CORUM) lens remains the mechanistically robust one."""
    sel = _select_in_band(_c2cp_gmt(), target) or _select_in_band(_go_bp_gmt(), target)
    return [{"name": sel[0], "members": sel[1]}] if sel else []


def _ppi_node_sets(target: str) -> list:
    """The PPI (interaction-neighbourhood) lens: the target's top-N physical interactors by publication
    evidence (BioGRID physical edges). Spec §3's BROADEST/hairball lens — bounded to PPI_TOP_N and
    REPORT-ONLY (see read_node_leverage: excluded from the headline min-across-lenses, because a raw
    interaction neighbourhood [~94 partners/gene] under worst-across-lenses aggregation would spuriously
    inflate 'dominated' calls). FAIL-SOFT: any read error yields an empty lens (never takes down the
    headline complex/pathway lenses). Pushdown on the symbol-sorted gene_symbol column."""
    try:
        df = pd.read_parquet(io.BytesIO(_get(_SRC_BIOGRID)),
                             columns=["gene_symbol", "partner_symbol", "n_publications"],
                             filters=[("gene_symbol", "==", target)])
    except Exception:  # absence-discipline: exempt -- PPI is a REPORT-ONLY lens (excluded from the headline); a transient/creds/absent BioGRID read must degrade to 'no PPI lens this run', NOT propagate — re-raising would couple a non-verdict-bearing lens to the whole node_leverage read (fail the verdict on a BioGRID blip). The verdict-bearing complex/pathway lenses have their own read paths.
        return []
    if df.empty:
        return []
    partners = (df.sort_values("n_publications", ascending=False)
                  .head(PPI_TOP_N)["partner_symbol"].tolist())
    members = sorted(set(partners) | {target})
    if len(members) < 2:
        return []
    return [{"name": f"BioGRID physical interactors (top {PPI_TOP_N} by publications)",
             "members": members}]


# --- lineage-scoped comparison ----------------------------------------------------------------------
def _model_ids_for_lineage(lineage: Optional[str]) -> Optional[list]:
    if not lineage:
        return None
    lm = _model_lineage()
    ids = [mid for mid, ln in lm.items() if ln == lineage]
    return ids if len(ids) >= MIN_COHORT else None


def _stats(genes: list, target: str, model_ids: Optional[list]) -> pd.DataFrame:
    sub = _chronos_subframe(set(genes) | {target})           # column-projected (only these genes)
    if model_ids:
        sub = sub.loc[sub.index.isin(model_ids)]
    rows = []
    for g in sub.columns:
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


# --- paralog / combinatorial correction (spec §6) ---------------------------------------------------
def _paralog_buffering(target: str) -> dict:
    """The paralog/combinatorial correction: a paralog-BUFFERED target's single-KO Chronos is
    SUPPRESSED (the paralog compensates), so its single-KO node-leverage verdict UNDERSTATES its true
    dependency — a buffered `weak_and_uncontested` / `dominated_node` can be a false-negative masked by
    redundancy. We reuse the pre-computed dual-KO buffering product (depmap_paralog_aggregator) — that
    IS the combinatorial signal, already summarized — and flag understatement. GENERAL (fires for any
    buffered target: MARK2/MARK3, SMARCA4/SMARCA2, …), NOT a single-example patch. Additive context:
    it qualifies but does not change node_leverage_class. FAIL-SOFT — a paralog-read failure must never
    kill the verdict (the correction is context, not verdict-bearing)."""
    try:
        s = _read_paralog_buffering(target=target) or {}
    except Exception:  # absence-discipline: exempt -- paralog buffering is ADDITIVE context (qualifies but does not set node_leverage_class); a transient/creds/absent paralog-product read must degrade to 'data_unavailable', NOT propagate and fail the whole node_leverage verdict (which the complex/pathway lenses own).
        s = {}
    cls = s.get("paralog_buffering_class", "data_unavailable")
    return {"paralog_buffering_class": cls,
            "strongest_buffering_paralog": s.get("strongest_paralog_symbol") or "",
            "single_ko_leverage_understated": cls in ("strong", "partial")}


# --- headline aggregation ---------------------------------------------------------------------------
_HEADLINE_ORDER = {"dominated_node": 0, "dominated_but_tractability_edge": 1,
                   "weak_and_uncontested": 2, "dominant_node": 3}


def _headline_class(lenses: dict) -> str:
    """Headline = the WORST (most-dominated) reachable verdict across the CURATED lenses (soft context).
    The `ppi` lens is REPORT-ONLY — EXCLUDED here — because a raw interaction neighbourhood
    (~94 partners/gene) under worst-across-lenses aggregation would spuriously crown a more-dependent
    bystander and inflate 'dominated'. PPI is surfaced per-lens for inspection, not for the verdict."""
    verdicts = [p["verdict"] for ln, lp in lenses.items() if ln != "ppi"
                for p in lp if p.get("verdict") in _HEADLINE_ORDER]
    return min(verdicts, key=lambda v: _HEADLINE_ORDER[v]) if verdicts else "no_node_set"


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
                                     ("pathway", _pathway_node_sets(target)),
                                     ("ppi", _ppi_node_sets(target))):
            per = [{"node_set": ns["name"], "n_members": len(ns["members"]),
                    **_classify(target, _stats(ns["members"], target, model_ids))} for ns in node_sets]
            lenses[lens_name] = per
    except ImportError:
        raise
    except Exception as e:
        return {"node_leverage_class": "data_unavailable",
                "_live_read_error": f"{type(e).__name__}: {e}"}

    headline = _headline_class(lenses)
    buffering = _paralog_buffering(target)
    return {
        "node_leverage_class": headline,          # soft, verdict-inert context (no veto, no certainty lift)
        "evidence_scope": scope,
        # paralog/combinatorial correction (spec §6): a buffered target's single-KO leverage UNDERSTATES
        # its dependency — qualifies node_leverage_class (esp. a buffered weak_and_uncontested/dominated
        # is a candidate false-negative), does NOT change it. Additive, verdict-inert.
        "paralog_buffering_class": buffering["paralog_buffering_class"],
        "strongest_buffering_paralog": buffering["strongest_buffering_paralog"],
        "single_ko_leverage_understated": buffering["single_ko_leverage_understated"],
        "lenses": lenses,
        "_method_version": METHOD_VERSION,
        "_caveats": ["SOFT context: no veto, never raises certainty",
                     "complex (CORUM) lens is the robust one; pathway-lens node-set selection is a "
                     "HEURISTIC (C2.CP-preferred, size-banded) over many-to-many gene<->set membership "
                     "— judge the selected node_set NAME for relevance",
                     "ppi lens (BioGRID physical interactors, top-N by publications) is REPORT-ONLY — "
                     "surfaced for inspection but EXCLUDED from the headline (an interaction hairball "
                     "under worst-across-lenses aggregation would inflate 'dominated'); fail-soft",
                     "no directed acts-through check (SIGNOR/OmniPath) — DEFERRED, and not yet needed: "
                     "this method makes a relative fitness-rank comparison, NOT a directional "
                     "'X acts through Y' claim, so there is no directional assertion to ground yet",
                     "paralog/combinatorial correction: single_ko_leverage_understated flags when the "
                     "target is paralog-BUFFERED (strong/partial, from the dual-KO buffering product) — "
                     "its single-KO Chronos, hence its leverage verdict, UNDERSTATES its dependency; a "
                     "buffered weak_and_uncontested/dominated call is a candidate false-negative masked "
                     "by redundancy (assess dual-KO / combinatorial leverage). Additive, fail-soft. NOTE "
                     "the paralog-MEDIATED-effector case (target whose PARALOG sits in the effector "
                     "pathway, e.g. MARK2 via MARK3) is surfaced as this buffering flag, not as a "
                     "node-set membership edge (which the pinned lenses cannot ground)"],
    }
