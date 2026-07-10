"""depmap_paralog_aggregator.read — DepMap paralog CRISPR gene-effect reader.

Consumer: paralog-buffering evidence card (Phase C-adjacent) via
functional-requirement skill. Emits per-target paralog-buffering summary
from DepMap 26Q1 dual-paralog CRISPR knockout screens.

Data: dmc-26q1-paralogs/ParalogGeneEffect.csv (Chronos-style gene-effect
scores per (paralog-pair, cell-line) dual knockout, ~69MB CSV).

Runtime discipline (Sprint 2 patterns):
  - @lru_cache(maxsize=1) on parse-and-index
  - Module-level negative cache on S3-absent
  - Per-target reads O(k) where k = paralog-pairs-involving-target

License: DepMap Consortium Member Data Use Agreement — Takeda institutional
access. Not redistributable outside Takeda.

Companion: data-catalog:manifests/sources/depmap-consortium-26q1-paralogs.yaml
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional


DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
PARALOG_SOURCE_MANIFEST_ID = "depmap-consortium-26q1-paralogs"
PARALOG_GENE_EFFECT_S3_KEY = (
    "data-catalog/sources/depmap-consortium/dmc-26q1-paralogs/ParalogGeneEffect.csv"
)

CACHE_DIR = Path.home() / ".cache" / "framework-depmap-paralog"
CACHE_CSV = CACHE_DIR / "ParalogGeneEffect.csv"

# Module-level negative cache
_PARALOG_STATUS: Optional[bool] = None


def _boto3_client():
    import boto3
    return boto3.Session(profile_name=DEFAULT_AWS_PROFILE).client("s3")


def _ensure_paralog_cached() -> Optional[Path]:
    """Fetch ParalogGeneEffect.csv to local cache. Returns None if S3 fetch
    fails (network / auth / missing object). Negative-cached module-level.
    """
    global _PARALOG_STATUS
    if _PARALOG_STATUS is False:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHE_CSV.exists() and CACHE_CSV.stat().st_size > 0:
        _PARALOG_STATUS = True
        return CACHE_CSV
    if _PARALOG_STATUS is None:
        try:
            s3 = _boto3_client()
            s3.download_file(S3_BUCKET, PARALOG_GENE_EFFECT_S3_KEY, str(CACHE_CSV))
            _PARALOG_STATUS = True
            return CACHE_CSV
        except Exception:
            _PARALOG_STATUS = False
            return None
    return None


@lru_cache(maxsize=1)
def _load_paralog_indexed() -> tuple[dict, dict]:
    """Parse ParalogGeneEffect ONCE and index by gene symbol.

    ParalogGeneEffect.csv column layout (DepMap 26Q1 convention):
      First column: ModelID (cell-line accession)
      Subsequent columns: "GENE_A;GENE_B (SgRNA_A;SgRNA_B)" — dual-knockout label
      Values: Chronos gene-effect score for the dual KO

    We aggregate to per-paralog-pair median gene-effect across the panel:
        pair_effect[(A, B)] = median across cell lines
    Downstream reasoning: strong-buffering pairs have very negative dual-KO
    effect (essential when both paralogs are knocked out) but each single
    KO is neutral.

    Iter-1 approximation: we compute the median dual-KO effect from
    ParalogGeneEffect only (single-KO baselines from ParalogGeneEffectUncorrected
    or the separate single-KO screens can be added in a Sprint 2 follow-up).

    Returns:
      (pair_effect_index, per_gene_pair_index)
      - pair_effect_index: dict[(gene_a_upper, gene_b_upper) -> median_effect]
      - per_gene_pair_index: dict[gene_upper -> list[(other_gene, pair_median_effect)]]
    """
    path = _ensure_paralog_cached()
    if path is None:
        return {}, {}

    import csv
    import statistics

    pair_effects: dict[tuple, list[float]] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return {}, {}
        # First column is ModelID; rest are single-KO or dual-KO labels.
        # Format observed in DepMap 26Q1 ParalogGeneEffect.csv:
        #   single-KO: "A3GALT2" (just gene symbol)
        #   dual-KO:   "A3GALT2_GLT6D1" (underscore-joined gene symbols)
        #   controls:  "AAVS1_AAVS1", "AAVS1_chr2", "AAVS1_nonTarget", etc.
        # We only index dual-KO columns where BOTH tokens look like real
        # gene symbols and neither is a control marker.
        pair_labels: list[tuple[Optional[tuple[str, str]], int]] = []
        CONTROL_MARKERS = {"AAVS1", "CHR2", "NONTARGET", "SAFE"}
        for idx, col_name in enumerate(header):
            if idx == 0:
                pair_labels.append((None, idx))
                continue
            # Skip single-gene columns (no underscore or 1 token)
            tokens = [t.strip().upper() for t in col_name.strip().split("_")]
            if len(tokens) != 2:
                # Not a canonical 2-gene dual-KO label; skip
                # (also covers 3+ token controls like "AAVS1_chr2_extra")
                pair_labels.append((None, idx))
                continue
            gene_a, gene_b = tokens
            if not gene_a or not gene_b:
                pair_labels.append((None, idx))
                continue
            # Skip AAVS1-anything and other control combinations
            if gene_a in CONTROL_MARKERS or gene_b in CONTROL_MARKERS:
                pair_labels.append((None, idx))
                continue
            if gene_a == gene_b:
                pair_labels.append((None, idx))
                continue
            key = tuple(sorted([gene_a, gene_b]))
            pair_labels.append((key, idx))

        # Stream rows: for each pair-column with a valid key, collect effects
        for row in reader:
            for key, idx in pair_labels:
                if key is None or idx >= len(row):
                    continue
                val = row[idx].strip()
                if not val:
                    continue
                try:
                    fval = float(val)
                except ValueError:
                    continue
                pair_effects.setdefault(key, []).append(fval)

    # Aggregate to median per pair
    pair_effect_index: dict[tuple, float] = {}
    for key, values in pair_effects.items():
        if values:
            pair_effect_index[key] = statistics.median(values)

    # Reverse index: per gene → list of (partner, median_effect)
    per_gene_pair_index: dict[str, list[tuple[str, float]]] = {}
    for (a, b), med in pair_effect_index.items():
        per_gene_pair_index.setdefault(a, []).append((b, med))
        per_gene_pair_index.setdefault(b, []).append((a, med))

    return pair_effect_index, per_gene_pair_index


def _classify_buffering(median_effect: float) -> str:
    """Coarse buffering strength classification from median dual-KO effect.

    Chronos-scale: negative = fitness cost; -1.0 is a common "essential"
    threshold. Strong buffering = dual KO is essential (median_effect < -1.0)
    while single KOs are viable (approximated by absence in DepMap single-KO
    essential list; iter-1 skips that check).
    """
    if median_effect is None:
        return "unknown"
    if median_effect < -1.5:
        return "strong"
    if median_effect < -1.0:
        return "moderate"
    if median_effect < -0.5:
        return "weak"
    return "none"


def read_target_summary(target: str, indication: str = None) -> dict:
    """Per-target paralog-buffering summary.

    Args:
        target: HGNC gene symbol (paralog data keys on symbol directly).
        indication: unused (paralog buffering is indication-agnostic;
            accepted for dispatcher signature consistency).

    Returns:
        dict with paralog-buffering summary:
          - paralog_buffering_class ('strong' | 'moderate' | 'weak' | 'none' | 'data_unavailable')
          - n_paralogs_annotated: count of paired genes in DepMap
          - n_paralogs_functionally_buffering: count with strong/moderate class
          - functional_paralogs: list<{partner_gene_symbol, median_dual_ko_effect, buffering_class}>
          - strongest_paralog_symbol: partner with lowest median (strongest buffering)
          - strongest_paralog_effect: numeric
    """
    try:
        pair_effect_index, per_gene_pair_index = _load_paralog_indexed()
    except Exception as e:
        return _empty_result(f"paralog_load_failed: {type(e).__name__}: {e}")

    if not pair_effect_index:
        return _empty_result("paralog_data_unavailable")

    target_upper = target.upper().strip()
    pairs = per_gene_pair_index.get(target_upper, [])

    if not pairs:
        return _empty_result("target_not_in_paralog_screens")

    functional_paralogs = []
    for partner, med_effect in pairs:
        b_class = _classify_buffering(med_effect)
        functional_paralogs.append({
            "partner_gene_symbol": partner,
            "median_dual_ko_effect": med_effect,
            "buffering_class": b_class,
        })

    # Sort by effect (most-negative-first; strongest buffering first)
    functional_paralogs.sort(key=lambda x: x["median_dual_ko_effect"])

    n_annotated = len(functional_paralogs)
    n_buffering = sum(1 for p in functional_paralogs
                       if p["buffering_class"] in ("strong", "moderate"))

    # Skill-level paralog_buffering_class from the strongest partner
    strongest = functional_paralogs[0] if functional_paralogs else None
    if strongest is None:
        paralog_buffering_class = "none"
        strongest_symbol = ""
        strongest_effect = None
    else:
        paralog_buffering_class = strongest["buffering_class"]
        strongest_symbol = strongest["partner_gene_symbol"]
        strongest_effect = strongest["median_dual_ko_effect"]

    return {
        "paralog_buffering_class": paralog_buffering_class,
        "n_paralogs_annotated": n_annotated,
        "n_paralogs_functionally_buffering": n_buffering,
        "functional_paralogs": functional_paralogs[:20],  # top 20 for compact output
        "strongest_paralog_symbol": strongest_symbol,
        "strongest_paralog_effect": strongest_effect,
        "method_version": "0.1.0",
        "_data_source": "depmap-paralog-buffering-per-gene-v1",
        "_data_source_upstream": PARALOG_SOURCE_MANIFEST_ID,
    }


def _empty_result(note: str) -> dict:
    return {
        "paralog_buffering_class": "data_unavailable",
        "n_paralogs_annotated": 0,
        "n_paralogs_functionally_buffering": 0,
        "functional_paralogs": [],
        "strongest_paralog_symbol": "",
        "strongest_paralog_effect": None,
        "method_version": "0.1.0",
        "_data_note": note,
    }
