"""paralog_genetic_interaction.read — per-target combinatorial-KO genetic-interaction reader.

Consumer: combinatorial-dependency evidence card (Gate-C adjacent) via the
combinatorial-dependency skill. Answers, for a target gene: "which paralog partner, when
co-knocked-out, kills more (or less) than the additive expectation — and is that interaction
CONSTITUTIVE (broad) or CONTEXT/GENOTYPE-CONDITIONAL (a minority of lines / specific lineages)?"

Data: depmap-paralog-genetic-interaction-per-pair-v1 (derived from DepMap ParalogV2 26Q1
dual-KO screen). Two parquet files at the same prefix:
  - paralog_gi_per_pair_line.parquet   (PRIMARY s3_uri; per gene-pair x cell-line GI rows)
  - paralog_gi_per_pair_summary.parquet (companion; one row per pair, both members)
GI = dual_ko - (single_a + single_b) on the Chronos scale; NEGATIVE = synthetic-lethal / buffering.

This reads the SUMMARY for the per-target partner ranking (cheap pushdown on target_gene), and
optionally the PER-LINE table for the lineage breakdown of a specific pair (the SMARCA2/4 lesson:
a pan-line mean hides genotype-conditional SL, so lineage stratification is a first-class read).

DISTINCT from depmap_paralog_aggregator (paralog-buffering): that reader emits a per-GENE
asymmetric buffering annotation feeding the dependency veto-suppressor. THIS reader emits the
SYMMETRIC per-pair GI + its lineage conditionality, for the combinatorial-dependency verdict.

Measured-vs-null discipline: a gene absent from the paralog library returns
`combinatorial_dependency_class: no_paralog_screened` (a coverage gap — the ParalogV2 library
only screens curated paralog pairs), NEVER an interaction-negative claim.

License: DepMap Consortium Member Data Use Agreement — Takeda institutional access.
Companion: data-catalog:manifests/derived/depmap-paralog-genetic-interaction-per-pair-v1.yaml
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

PRODUCT_MANIFEST_ID = "depmap-paralog-genetic-interaction-per-pair-v1"
SUMMARY_FILENAME = "paralog_gi_per_pair_summary.parquet"
METHOD_VERSION = "0.1.0"

# Verdict thresholds mirror the product's interaction_class (carried raw so the card can re-threshold).
STRONG_GI = -0.5

# Caches ONLY successful summary reads (a hit or a definitive empty tuple()), keyed by UPPER(target).
# A transient read failure returns None WITHOUT caching, so a later call retries — an @lru_cache over
# the raw read would memoize that None permanently, poisoning the target to data_unavailable for the
# whole process after one S3 blip. Mirrors structure_features_static: never latch a negative cache on
# a transient error.
_SUMMARY_CACHE: dict = {}


def _bucket_keys():
    """(bucket, per_line_key, summary_key) resolved from the manifest (single source of truth)."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from methods.catalog_query.read import bucket_key_for
    bucket, per_line_key = bucket_key_for(PRODUCT_MANIFEST_ID)
    # summary companion lives at the same prefix (documented in the manifest parameters).
    summary_key = per_line_key.rsplit("/", 1)[0] + "/" + SUMMARY_FILENAME
    return bucket, per_line_key, summary_key


def _read_summary_rows(target: str) -> Optional[tuple]:
    """Pushdown-read summary rows for one target_gene. None on read failure (NOT cached — so a
    later call retries); empty tuple if the gene is absent from the library (cached). Successful
    reads are cached in _SUMMARY_CACHE. Returns a tuple of dicts."""
    sym = (target or "").strip().upper()
    if sym in _SUMMARY_CACHE:
        return _SUMMARY_CACHE[sym]
    try:
        import pyarrow.parquet as pq
        import pyarrow.fs as fs
        bucket, _per_line_key, summary_key = _bucket_keys()
        tbl = pq.read_table(
            f"{bucket}/{summary_key}", filesystem=fs.S3FileSystem(),
            filters=[("target_gene", "=", sym)],
        )
    except Exception:  # noqa: BLE001
        return None
    result = tuple() if tbl.num_rows == 0 else tuple(tbl.to_pylist())
    _SUMMARY_CACHE[sym] = result
    return result


def _read_pair_lines(target: str, partner: str) -> Optional[list]:
    """Per-line GI rows for a specific (target, partner) pair — for the lineage breakdown.
    None on read failure; [] if the pair is absent."""
    try:
        import pyarrow.parquet as pq
        import pyarrow.fs as fs
        bucket, per_line_key, _summary_key = _bucket_keys()
        tbl = pq.read_table(
            f"{bucket}/{per_line_key}", filesystem=fs.S3FileSystem(),
            filters=[("target_gene", "=", (target or "").strip().upper()),
                     ("partner_gene", "=", (partner or "").strip().upper())],
        )
    except Exception:  # noqa: BLE001
        return None
    return tbl.to_pylist()


def _classify(summary_rows: Optional[tuple]) -> str:
    """Map a target's summary rows -> combinatorial_dependency_class (strongest partner wins).

      strong_synthetic_lethal   >=1 partner with interaction_class 'constitutive_buffering'
      context_synthetic_lethal  else, >=1 partner 'context_buffering'
      suppressive_interaction   else, >=1 partner 'suppressive'
      no_interaction            partners screened, none interacting
      no_paralog_screened       gene absent from the paralog library (coverage gap — measured-vs-null)
    """
    if summary_rows is None:
        return "data_unavailable"
    if len(summary_rows) == 0:
        return "no_paralog_screened"
    classes = {r.get("interaction_class") for r in summary_rows}
    if "constitutive_buffering" in classes:
        return "strong_synthetic_lethal"
    if "context_buffering" in classes:
        return "context_synthetic_lethal"
    if "suppressive" in classes:
        return "suppressive_interaction"
    return "no_interaction"


def _rank_partners(summary_rows: tuple, top_n: int = 20) -> list:
    """Partner ranking by mean_gi ascending (most synthetic-lethal first)."""
    rows = sorted(summary_rows, key=lambda r: (r.get("mean_gi") if r.get("mean_gi") is not None else 0.0))
    out = []
    for r in rows[:top_n]:
        out.append({
            "partner_gene": r.get("partner_gene"),
            "pair_id": r.get("pair_id"),
            "n_lines": int(r.get("n_lines") or 0),
            "mean_gi": r.get("mean_gi"),
            "median_gi": r.get("median_gi"),
            "gi_ttest_pvalue": r.get("gi_ttest_pvalue"),
            "frac_lines_strong_gi": r.get("frac_lines_strong_gi"),
            "min_gi": r.get("min_gi"),
            "min_gi_lineage": r.get("min_gi_lineage"),
            "n_lineages_strong": int(r.get("n_lineages_strong") or 0),
            "interaction_class": r.get("interaction_class"),
        })
    return out


def combinatorial_dependency_for_gene(target: str, summary_rows: Optional[tuple] = None) -> dict:
    """Per-target combinatorial-KO genetic-interaction summary. summary_rows injectable for tests."""
    sym = (target or "").strip().upper()
    rows = summary_rows if summary_rows is not None else _read_summary_rows(sym)
    klass = _classify(rows)
    partners = _rank_partners(rows, top_n=20) if rows else []
    strongest = partners[0] if partners else None
    n_interacting = sum(
        1 for p in partners
        if p["interaction_class"] in ("constitutive_buffering", "context_buffering", "suppressive")
    )
    out = {
        "combinatorial_dependency_class": klass,
        "n_paralog_partners_screened": len(rows) if rows else 0,
        "n_interacting_partners": n_interacting,
        "strongest_partner": (strongest or {}).get("partner_gene"),
        "strongest_partner_mean_gi": (strongest or {}).get("mean_gi"),
        "strongest_partner_class": (strongest or {}).get("interaction_class"),
        "top_partners": partners,
        "combinatorial_context": _context(sym, klass, strongest, len(rows) if rows else 0),
        "method_version": METHOD_VERSION,
        "_data_source": PRODUCT_MANIFEST_ID,
    }
    # A read failure (klass=data_unavailable, from _read_summary_rows returning None) is an infra
    # failure — surface a breadcrumb so it is never mistaken for a benign coverage gap (mirrors
    # exon_window / cd_antigen_backbone). NOT cached upstream, so a later call retries.
    if klass == "data_unavailable":
        out["_live_read_error"] = "paralog_genetic_interaction_read_failed"
    return out


def lineage_breakdown_for_pair(target: str, partner: str) -> dict:
    """Per-lineage GI breakdown for a specific pair — surfaces genotype/lineage-conditional SL
    that a pan-line summary hides (the SMARCA2/4 lesson)."""
    lines = _read_pair_lines(target, partner)
    if lines is None:
        return {"status": "data_unavailable", "pair": f"{target}/{partner}"}
    if not lines:
        return {"status": "pair_not_screened", "pair": f"{target}/{partner}"}
    by_lin: dict = {}
    for r in lines:
        lin = r.get("OncotreeLineage") or "Unknown"
        by_lin.setdefault(lin, []).append(r.get("gi_score"))
    per_lineage = []
    for lin, vals in by_lin.items():
        vals = [v for v in vals if v is not None]
        if not vals:
            continue
        med = sorted(vals)[len(vals) // 2]
        per_lineage.append({
            "lineage": lin, "n_lines": len(vals),
            "median_gi": med,
            "n_strong": sum(1 for v in vals if v < STRONG_GI),
            "strong_in_lineage": med < STRONG_GI,
        })
    per_lineage.sort(key=lambda d: d["median_gi"])
    return {
        "status": "ok", "pair": f"{target}/{partner}",
        "n_lines_total": len(lines),
        "per_lineage": per_lineage,
        "strong_lineages": [d["lineage"] for d in per_lineage if d["strong_in_lineage"]],
    }


def _context(sym: str, klass: str, strongest: Optional[dict], n_screened: int) -> Optional[str]:
    if klass == "no_paralog_screened":
        return (f"{sym}: not present in the DepMap ParalogV2 dual-KO library (a coverage gap — the "
                f"library screens curated paralog pairs only, NOT evidence of no interaction).")
    if klass == "data_unavailable":
        return f"{sym}: paralog GI product unavailable (read error)."
    if klass == "no_interaction":
        return (f"{sym}: {n_screened} paralog partner(s) screened; none show a genetic interaction "
                f"beyond the additive single-KO expectation.")
    s = strongest or {}
    pg, mg, ic = s.get("partner_gene"), s.get("mean_gi"), s.get("interaction_class")
    frac = s.get("frac_lines_strong_gi")
    minlin = s.get("min_gi_lineage")
    if klass == "strong_synthetic_lethal":
        return (f"{sym}: constitutive synthetic-lethal / buffering interaction with {pg} "
                f"(mean GI {mg:.3f} across cell lines) — the pair is required together broadly.")
    if klass == "context_synthetic_lethal":
        return (f"{sym}: CONTEXT-dependent synthetic-lethal interaction with {pg} (mean GI {mg:.3f}; "
                f"~{(frac or 0)*100:.0f}% of lines show strong buffering, strongest in {minlin}) — "
                f"the dependency is conditional (lineage / genotype), not broad. Check the lineage breakdown.")
    if klass == "suppressive_interaction":
        return (f"{sym}: suppressive (positive-GI) interaction with {pg} (mean GI {mg:.3f}) — "
                f"co-loss is LESS lethal than additive (masking/epistasis).")
    return None
