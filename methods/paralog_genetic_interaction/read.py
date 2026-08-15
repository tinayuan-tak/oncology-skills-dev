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
METHOD_VERSION = "0.2.0"

# Reader-authoritative GI thresholds. The product carries the raw effect fields (mean_gi,
# frac_lines_strong_gi, min_gi) precisely so the card can re-threshold — this reader now does so
# rather than trusting the product's baked `interaction_class` convenience column (see _partner_class
# for the over-call bug that column had). Chronos scale; NEGATIVE GI = synthetic-lethal / buffering.
STRONG_GI = -0.5                    # a "strong" synthetic-lethal / buffering LINE (per-line bar)
CONSTITUTIVE_MEAN = -0.25          # mean-GI floor for a broad additive-negative interaction
FRAC_STRONG_CONSTITUTIVE = 0.4     # ...AND a MAJORITY-ish of lines strongly buffered — the specificity gate
SUPPRESSIVE_MEAN = 0.25            # positive GI / masking
CONTEXT_FRAC = 0.10                # minority-of-lines fraction hinting conditional SL
CONTEXT_MIN = -1.0                 # a single very-strong line hints conditional SL

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
    """Pushdown-read summary rows for one target_gene. Returns None on a GENUINE no-object
    (NoSuchKey/404) and RAISES on transient/creds/broken-env (neither cached, so a later call
    retries); empty tuple if the gene is absent from the library (cached). Successful reads are
    cached in _SUMMARY_CACHE. The public `combinatorial_dependency_for_gene` catches the transient
    raise at its boundary and degrades to data_unavailable + a cause-accurate breadcrumb. Returns a
    tuple of dicts."""
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
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent
        # Genuine NoSuchKey/404 (or pyarrow FileNotFoundError) on the summary object -> None (NOT
        # cached) -> caller emits data_unavailable (unchanged). A transient/creds/broken-env failure is
        # NOT absence -> re-raise so the live-read seam tags _live_read_error; not cached, later retries.
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return None
        raise
    result = tuple() if tbl.num_rows == 0 else tuple(tbl.to_pylist())
    _SUMMARY_CACHE[sym] = result
    return result


def _read_pair_lines(target: str, partner: str) -> Optional[list]:
    """Per-line GI rows for a specific (target, partner) pair — for the lineage breakdown.
    Returns None on a GENUINE no-object (NoSuchKey/404) and RAISES on transient/creds/broken-env;
    [] if the pair is absent. The public `lineage_breakdown_for_pair` catches the transient raise at
    its boundary and degrades to a data_unavailable status + breadcrumb (never propagates)."""
    try:
        import pyarrow.parquet as pq
        import pyarrow.fs as fs
        bucket, per_line_key, _summary_key = _bucket_keys()
        tbl = pq.read_table(
            f"{bucket}/{per_line_key}", filesystem=fs.S3FileSystem(),
            filters=[("target_gene", "=", (target or "").strip().upper()),
                     ("partner_gene", "=", (partner or "").strip().upper())],
        )
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent
        # Genuine NoSuchKey/404 (or pyarrow FileNotFoundError) on the per-line object -> None ->
        # caller treats as absent (unchanged). A transient/creds/broken-env failure is NOT absence ->
        # re-raise so the live-read seam surfaces an honest _live_read_error instead of a dead axis.
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return None
        raise
    return tbl.to_pylist()


def _partner_class(r: dict) -> Optional[str]:
    """Reader-authoritative re-classification of ONE partner row from its RAW GI effect fields.

    Supersedes the product's baked `interaction_class` convenience column. That column keyed
    `constitutive_buffering` on `mean_gi <= -0.25 AND one-sample-t p < 0.05` — but at the screen's n
    (~278 lines) the t-test vs 0 is significant (p < 1e-40) for ANY tiny consistent offset, so the
    p-gate was INERT and classification collapsed to the single -0.25 mean cutoff. That over-called
    `constitutive` on weak, family-wide additive GI against non-paralog partners: ZAP70 (a SYK-family
    T/NK kinase) scored as the top "constitutive" partner for BOTH EGFR and ERBB2, and FLT3's call
    rested on a flat RTK-family plateau (FGFR1/PDGFRA/RET, all frac_strong ~0.2) while its true
    class-III paralog KIT read weakest — the signature of a generic two-kinase-KO additive effect, not
    paralog buffering.

    We re-gate on EFFECT: a CONSTITUTIVE (broad) buffering interaction must show a strong per-line SL
    effect in a MAJORITY-ish of lines (frac_lines_strong_gi >= FRAC_STRONG_CONSTITUTIVE), not merely a
    small mean shift. On the validated positive control MARK2/MARK3 frac_strong = 0.58 (survives as
    constitutive); the over-called artifacts sit at 0.19-0.29 and demote to context_buffering — a
    minority-of-lines, conditional signal, which is the honest description. The inert p-gate is dropped
    (effect size, not significance-at-large-n, is the right discriminator here).

    Falls back to the baked `interaction_class` only when the raw effect fields are absent (an older
    product build), so the reader degrades gracefully rather than mis-classifying to no_interaction.
    """
    mean_gi = r.get("mean_gi")
    if mean_gi is None:  # pre-raw-field product build — trust the baked convenience label
        return r.get("interaction_class")
    frac_strong = r.get("frac_lines_strong_gi") or 0.0
    min_gi = r.get("min_gi")
    if mean_gi <= CONSTITUTIVE_MEAN and frac_strong >= FRAC_STRONG_CONSTITUTIVE:
        return "constitutive_buffering"
    if mean_gi >= SUPPRESSIVE_MEAN:
        return "suppressive"
    if frac_strong >= CONTEXT_FRAC or (min_gi is not None and min_gi < CONTEXT_MIN):
        return "context_buffering"
    return "no_interaction"


def _classify(summary_rows: Optional[tuple]) -> str:
    """Map a target's summary rows -> combinatorial_dependency_class (strongest partner wins).

      strong_synthetic_lethal   >=1 partner re-classifying to 'constitutive_buffering'
      context_synthetic_lethal  else, >=1 partner 'context_buffering'
      suppressive_interaction   else, >=1 partner 'suppressive'
      no_interaction            partners screened, none interacting
      no_paralog_screened       gene absent from the paralog library (coverage gap — measured-vs-null)

    Per-partner class is re-derived from raw effect fields by _partner_class (reader-authoritative),
    NOT read from the product's baked `interaction_class` column.
    """
    if summary_rows is None:
        return "data_unavailable"
    if len(summary_rows) == 0:
        return "no_paralog_screened"
    classes = {_partner_class(r) for r in summary_rows}
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
            # reader-authoritative re-classification (frac_strong-gated); the product's baked label is
            # preserved as interaction_class_product so a reclassification is auditable, not silent.
            "interaction_class": _partner_class(r),
            "interaction_class_product": r.get("interaction_class"),
        })
    return out


def combinatorial_dependency_for_gene(target: str, summary_rows: Optional[tuple] = None) -> dict:
    """Per-target combinatorial-KO genetic-interaction summary. summary_rows injectable for tests."""
    sym = (target or "").strip().upper()
    read_error = None
    if summary_rows is not None:
        rows = summary_rows
    else:
        try:
            rows = _read_summary_rows(sym)   # None = genuine no-object; raises on transient
        except Exception as e:  # noqa: BLE001 — graceful boundary: never propagate a read blip
            # This reader ALREADY owns the honest "read failure -> data_unavailable + breadcrumb"
            # contract; propagating a transient S3/creds/broken-env exception past the public boundary
            # would crash the whole skill run on a blip. The refinement is that the breadcrumb now
            # names the true cause; _read_summary_rows does not cache a failed load, so a later call
            # retries.
            rows = None
            read_error = f"paralog_genetic_interaction transient/creds/broken-env read failure: {e}"
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
        out["_live_read_error"] = read_error or (
            "paralog_genetic_interaction genuine no-object (NoSuchKey/404): paralog GI product absent")
    return out


def lineage_breakdown_for_pair(target: str, partner: str) -> dict:
    """Per-lineage GI breakdown for a specific pair — surfaces genotype/lineage-conditional SL
    that a pan-line summary hides (the SMARCA2/4 lesson)."""
    try:
        lines = _read_pair_lines(target, partner)   # None = genuine no-object; raises on transient
    except Exception as e:  # noqa: BLE001 — graceful boundary: never propagate a read blip
        return {"status": "data_unavailable", "pair": f"{target}/{partner}",
                "_live_read_error": f"paralog_genetic_interaction transient/creds/broken-env read failure: {e}"}
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
    mg_str = f"{mg:.3f}" if mg is not None else "n/a"  # null-safe: a degenerate row must not crash the read
    if klass == "strong_synthetic_lethal":
        return (f"{sym}: constitutive synthetic-lethal / buffering interaction with {pg} "
                f"(mean GI {mg_str} across cell lines) — the pair is required together broadly.")
    if klass == "context_synthetic_lethal":
        return (f"{sym}: CONTEXT-dependent synthetic-lethal interaction with {pg} (mean GI {mg_str}; "
                f"~{(frac or 0)*100:.0f}% of lines show strong buffering, strongest in {minlin}) — "
                f"the dependency is conditional (lineage / genotype), not broad. Check the lineage breakdown.")
    if klass == "suppressive_interaction":
        return (f"{sym}: suppressive (positive-GI) interaction with {pg} (mean GI {mg_str}) — "
                f"co-loss is LESS lethal than additive (masking/epistasis).")
    return None
