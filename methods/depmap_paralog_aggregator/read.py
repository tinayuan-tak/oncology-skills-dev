"""depmap_paralog_aggregator.read — DepMap paralog CRISPR gene-effect reader.

Consumer: paralog-buffering evidence card (Phase C-adjacent) via
functional-requirement skill. Emits per-target paralog-buffering summary
from DepMap 26Q1 dual-paralog CRISPR knockout screens.

Data: dmc-26q1-paralogs/ParalogGeneEffect.csv (Chronos-style gene-effect
scores per (paralog-pair, cell-line) dual knockout, ~69MB CSV).

Runtime discipline:
  - @lru_cache(maxsize=1) on parse-and-index
  - Module-level negative cache on S3-absent
  - Per-target reads O(k) where k = paralog-pairs-involving-target

License: DepMap Consortium Member Data Use Agreement — Takeda institutional
access. Not redistributable outside Takeda.

Companion: data-catalog:manifests/sources/depmap-consortium-26q1-paralogs.yaml
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from methods.catalog_query.read import bucket_prefix_for


DEFAULT_AWS_PROFILE = "cbg"
PARALOG_SOURCE_MANIFEST_ID = "depmap-consortium-26q1-paralogs"
# bucket + key resolved from the data-catalog manifest (single source of truth).
S3_BUCKET, _PARALOG_PREFIX = bucket_prefix_for(PARALOG_SOURCE_MANIFEST_ID)
PARALOG_GENE_EFFECT_S3_KEY = f"{_PARALOG_PREFIX}ParalogGeneEffect.csv"

CACHE_DIR = Path.home() / ".cache" / "framework-depmap-paralog"
CACHE_CSV = CACHE_DIR / "ParalogGeneEffect.csv"

# Module-level negative cache
_PARALOG_STATUS: Optional[bool] = None


from methods.target_id_sidecar import s3_client as _boto3_client


def _ensure_paralog_cached() -> Optional[Path]:
    """Fetch ParalogGeneEffect.csv to local cache. Returns None if unreachable; negative-cached.

    Definitive-vs-transient discipline (mirrors opentargets_common.ensure_entity_cached): a
    404/NoSuchKey LATCHES the axis unavailable (product genuinely absent), a transient failure
    (throttle/creds/network) does NOT latch — it stays None so a later call retries — and a broken
    env (missing boto3) RE-RAISES rather than masking the axis as a fake data gap. Previously ANY
    exception latched _PARALOG_STATUS=False, so a single transient blip killed the paralog axis for
    the rest of the process (the dead-axis-masking bug)."""
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
        except ImportError:
            raise  # broken env (boto3 missing) — never mask the whole axis as a data gap
        except Exception as e:  # noqa: BLE001
            from methods.target_id_sidecar import is_definitively_absent

            if is_definitively_absent(e):
                _PARALOG_STATUS = False  # product genuinely absent -> honest, latched data_unavailable
            # transient (throttle/creds/network): do NOT latch -> stays None so a later call retries
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

    Buffering metric (aligns reader to the card + rules contract):
    the buffering signal is NOT the dual-KO effect alone — it is how much MORE
    lethal the dual KO is than the best single KO:
        dep_delta_paired_vs_max_single(A,B) = median_dual(A,B) - max(single(A), single(B))
    A strongly-negative delta means each paralog rescues the other (true buffering),
    distinct from a pair that is essential simply because one member is a
    baseline-essential gene. Single-KO baselines are the bare-gene-symbol columns in
    the SAME ParalogGeneEffect.csv (4547 present), previously skipped.

    Returns:
      (pair_delta_index, per_gene_pair_index)
      - pair_delta_index: dict[(gene_a_upper, gene_b_upper) -> {
            median_dual, single_a, single_b, delta_vs_max_single}]
      - per_gene_pair_index: dict[gene_upper -> list[(other_gene, pair_record)]]
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
        # Classify each column as a DUAL-KO pair, a SINGLE-KO baseline, or skip.
        pair_labels: list[tuple[Optional[tuple[str, str]], int]] = []
        single_labels: list[tuple[Optional[str], int]] = []
        CONTROL_MARKERS = {"AAVS1", "CHR2", "NONTARGET", "SAFE"}
        for idx, col_name in enumerate(header):
            pair_labels.append((None, idx))  # default: not a pair
            single_labels.append((None, idx))  # default: not a single
            if idx == 0:
                continue
            raw = col_name.strip()
            tokens = [t.strip().upper() for t in raw.split("_")]
            if len(tokens) == 1:
                # SINGLE-KO baseline: bare gene symbol (e.g. "A3GALT2").
                g = tokens[0]
                if g and g not in CONTROL_MARKERS:
                    single_labels[idx] = (g, idx)
                continue
            if len(tokens) != 2:
                continue  # 3+ token controls
            gene_a, gene_b = tokens
            if not gene_a or not gene_b:
                continue
            if gene_a in CONTROL_MARKERS or gene_b in CONTROL_MARKERS:
                continue
            if gene_a == gene_b:
                continue
            pair_labels[idx] = (tuple(sorted([gene_a, gene_b])), idx)

        single_effects: dict[str, list[float]] = {}
        # Stream rows once: collect dual-KO effects per pair + single-KO per gene.
        for row in reader:
            for key, idx in pair_labels:
                if key is None or idx >= len(row):
                    continue
                v = row[idx].strip()
                if v:
                    try:
                        pair_effects.setdefault(key, []).append(float(v))
                    except ValueError:
                        pass
            for gene, idx in single_labels:
                if gene is None or idx >= len(row):
                    continue
                v = row[idx].strip()
                if v:
                    try:
                        single_effects.setdefault(gene, []).append(float(v))
                    except ValueError:
                        pass

    # Aggregate to median per pair + per single gene.
    dual_median = {k: statistics.median(v) for k, v in pair_effects.items() if v}
    single_median = {g: statistics.median(v) for g, v in single_effects.items() if v}

    # Compute the buffering delta per pair: median_dual - max(single_a, single_b).
    # Single-KO baseline missing for a member → that member's single effect is
    # treated as unavailable (None); delta falls back to None (NOT to 0, which would
    # fabricate a baseline — measured-vs-null discipline).
    # SIGN CONVENTION (matches the card contract): dep_delta_paired_vs_max_single is
    # the POSITIVE additional lethality of the dual KO over the best single KO =
    #   max(single_a, single_b) - median_dual.
    # On the Chronos scale (more-negative = more lethal), a dual KO that is more
    # lethal than either single → max_single (less negative) minus median_dual (more
    # negative) → POSITIVE delta. strong → delta > 0.5; partial → 0.2-0.5; none → <0.2.
    pair_delta_index: dict[tuple, dict] = {}
    for (a, b), med_dual in dual_median.items():
        sa = single_median.get(a)
        sb = single_median.get(b)
        singles = [s for s in (sa, sb) if s is not None]
        max_single = max(singles) if singles else None
        delta = (max_single - med_dual) if max_single is not None else None
        pair_delta_index[(a, b)] = {
            "median_dual": med_dual,
            "single_a": sa,
            "single_b": sb,
            "delta_vs_max_single": delta,
        }

    per_gene_pair_index: dict[str, list[tuple[str, dict]]] = {}
    for (a, b), rec in pair_delta_index.items():
        per_gene_pair_index.setdefault(a, []).append((b, rec))
        per_gene_pair_index.setdefault(b, []).append((a, rec))

    return pair_delta_index, per_gene_pair_index


# Card-contract thresholds (paralog-buffering.card.yaml:60-61) on the POSITIVE
# dep_delta_paired_vs_max_single (dual-KO additional lethality over the best single).
_STRONG_DELTA = 0.5
_PARTIAL_DELTA = 0.2


def _classify_buffering(delta: Optional[float]) -> str:
    """Buffering class from dep_delta_paired_vs_max_single (card contract).

    delta = max(single_a, single_b) - median_dual (positive = dual KO is more lethal
    than either single = the paralogs buffer each other). Card vocab: strong/partial/
    none. A missing delta (no single-KO baseline for either member) is NOT classified
    as `none` — it is genuinely unmeasured; callers treat a None delta as excluded
    from the buffering call (measured-vs-null discipline), never as a confirmed no-buffer.
    """
    if delta is None:
        return "unmeasured"
    if delta > _STRONG_DELTA:
        return "strong"
    if delta >= _PARTIAL_DELTA:
        return "partial"
    return "none"


# ---- Derived-product read path (preferred) -----------------------------------
# The gene-sorted derived product depmap-paralog-buffering-per-gene-v1 carries everything the
# live raw-CSV recompute produces PLUS the Ensembl-Compara ohnolog_flag the card declares
# (strongest_paralog_ohnolog). It is now materialized on S3, so this is the PRIMARY read:
# a cheap per-gene pyarrow predicate-pushdown lookup (vs parsing the 69 MB CSV live). The
# raw-CSV recompute (_read_from_raw_csv) is retained as a graceful FALLBACK when the product
# is unreachable (network/auth/absent) — same buffering math, minus the ohnolog annotation.
DERIVED_PRODUCT_MANIFEST_ID = "depmap-paralog-buffering-per-gene-v1"


def _derived_parquet_uri() -> Optional[str]:
    """Resolve the derived product's S3 URI from the data-catalog manifest (single source of
    truth). Returns None if the manifest is unreadable (then the reader falls back to raw CSV)."""
    try:
        from methods.catalog_query.read import s3_uri_for

        return s3_uri_for(DERIVED_PRODUCT_MANIFEST_ID)
    except Exception:  # absence-discipline: exempt -- manifest unresolvable → reader falls back to raw-CSV recompute (benign fallback, not a dead axis)
        return None


def _fetch_derived_row(parquet_uri: str, gene: str) -> Optional[dict]:
    """Pyarrow predicate-pushdown read of ONE gene row from the derived product. Returns the
    row dict or None (target absent). Mirrors depmap_predictability.cli.fetch_predictability_row."""
    import pyarrow.parquet as pq

    if parquet_uri.startswith("s3://"):
        import pyarrow.fs as pafs

        without = parquet_uri[len("s3://") :]
        bucket, _, key = without.partition("/")
        fs = pafs.S3FileSystem()
        path = f"{bucket}/{key}"
    else:
        fs = None
        path = parquet_uri
    table = pq.read_table(path, filesystem=fs, filters=[("target_gene_symbol", "=", gene.upper().strip())])
    if table.num_rows == 0:
        return None
    return {col: table[col][0].as_py() for col in table.column_names}


def _read_from_derived_product(target: str) -> Optional[dict]:
    """Preferred read: map a derived-product row → the card's summary_fields, INCLUDING the real
    strongest_paralog_ohnolog (from the strongest partner's ohnolog_flag). Returns:
      - a full summary dict on success,
      - an _empty_result('target_not_in_paralog_screens') when the gene is absent from the product,
      - None to signal "product unreachable — caller should fall back to the raw-CSV recompute".
    """
    import json as _json

    uri = _derived_parquet_uri()
    if not uri:
        return None
    try:
        row = _fetch_derived_row(uri, target)
    except Exception:  # noqa: BLE001 — unreachable product → signal fallback (None)
        return None
    if row is None:
        return _empty_result("target_not_in_paralog_screens")

    try:
        top = _json.loads(row.get("top_partners") or "[]")
    except (ValueError, TypeError):
        top = []
    # Card-shaped functional_paralogs (rename product keys → card keys).
    functional_paralogs = [
        {
            "partner_gene_symbol": p.get("partner_symbol"),
            "median_dual_ko_effect": p.get("median_dual_ko_effect"),
            "single_ko_effect": p.get("single_ko_target"),
            "dep_delta_paired_vs_max_single": p.get("dep_delta_paired_vs_max_single"),
            "buffering_class": p.get("buffering_class"),
            "ohnolog": p.get("ohnolog_flag"),
        }
        for p in top
    ]
    # The strongest partner is the first entry (product sorts top_partners by delta desc).
    strongest = top[0] if top else None
    return {
        "paralog_buffering_class": row.get("paralog_buffering_class", "data_unavailable"),
        "n_paralogs_annotated": row.get("n_paralogs_annotated", 0),
        "n_paralogs_functionally_buffering": row.get("n_paralogs_buffering", 0),
        "functional_paralogs": functional_paralogs[:20],
        # strongest_paralog_symbol = the MAX-buffering-delta partner (dep_delta_paired_vs_max_single),
        # NOT necessarily the biologically-canonical redundant paralog. Ties/near-ties among strong
        # partners are common + meaningful (e.g. CDK4: CDK1 δ=1.57 edges CDK4/6 δ=1.48) — consumers
        # wanting the full picture should read the ranked `functional_paralogs` list, not just this scalar.
        "strongest_paralog_symbol": row.get("strongest_partner") or "",
        # The card-declared field, POPULATED from the product's Ensembl-Compara ohnolog_flag.
        "strongest_paralog_ohnolog": (strongest.get("ohnolog_flag") if strongest else None),
        # Tri-state provenance for the ohnolog flag: on this PRIMARY path the flag is a
        # real annotation → `annotated`. The fallback path emits `unknown_fallback` so a None ohnolog
        # there is never confused with a genuine False by the strong_ohnolog_paralog predicate.
        "strongest_paralog_ohnolog_status": "annotated",
        "strongest_paralog_delta": row.get("strongest_delta"),
        "method_version": "0.3.1",  # 0.3.1: + ohnolog_status tri-state + strongest-paralog semantics doc
        "_data_source": DERIVED_PRODUCT_MANIFEST_ID,
        "_data_source_upstream": PARALOG_SOURCE_MANIFEST_ID,
    }


def read_target_summary(target: str, indication: str = None) -> dict:
    """Per-target paralog-buffering summary (aligned to the card + rule contract).

    Args:
        target: HGNC gene symbol (paralog data keys on symbol directly).
        indication: unused (paralog buffering is indication-agnostic).

    PREFERRED path: read the gene-sorted derived product depmap-paralog-buffering-per-gene-v1
    (cheap predicate-pushdown), which carries the Ensembl-Compara ohnolog annotation. If that
    product is unreachable, FALL BACK to recomputing from the raw ParalogGeneEffect.csv (same
    buffering math; strongest_paralog_ohnolog is then None — the annotation lives only in the
    product's offline Ensembl join).

    Returns dict with:
      - paralog_buffering_class ∈ {strong, partial, none, data_unavailable}
      - n_paralogs_annotated, n_paralogs_functionally_buffering (strong or partial)
      - functional_paralogs: list<{partner_gene_symbol, median_dual_ko_effect,
        single_ko_effect, dep_delta_paired_vs_max_single, buffering_class[, ohnolog]}>
      - strongest_paralog_symbol / strongest_paralog_delta / strongest_paralog_ohnolog
    """
    # 1) PREFERRED: the derived product (real ohnolog). None → product unreachable → fall back.
    product_result = _read_from_derived_product(target)
    if product_result is not None:
        return product_result

    # 2) FALLBACK: recompute live from the raw CSV (no ohnolog annotation available).
    return _read_from_raw_csv(target)


def _read_from_raw_csv(target: str) -> dict:
    """FALLBACK read: recompute buffering live from the raw ParalogGeneEffect.csv when the
    derived product is unreachable. strongest_paralog_ohnolog is None here (the Ensembl-Compara
    ohnolog join exists only in the offline product build)."""
    try:
        pair_delta_index, per_gene_pair_index = _load_paralog_indexed()
    except Exception as e:
        return _empty_result(f"paralog_load_failed: {type(e).__name__}: {e}")

    if not pair_delta_index:
        return _empty_result("paralog_data_unavailable")

    target_upper = target.upper().strip()
    pairs = per_gene_pair_index.get(target_upper, [])

    if not pairs:
        return _empty_result("target_not_in_paralog_screens")

    functional_paralogs = []
    for partner, rec in pairs:
        delta = rec["delta_vs_max_single"]
        # max single-KO effect of the pair (the baseline the delta is measured against)
        singles = [s for s in (rec["single_a"], rec["single_b"]) if s is not None]
        max_single = max(singles) if singles else None
        functional_paralogs.append(
            {
                "partner_gene_symbol": partner,
                "median_dual_ko_effect": rec["median_dual"],
                "single_ko_effect": max_single,
                "dep_delta_paired_vs_max_single": delta,
                "buffering_class": _classify_buffering(delta),
            }
        )

    # Rank by delta descending (strongest buffering first); unmeasured (None) last.
    functional_paralogs.sort(
        key=lambda x: (x["dep_delta_paired_vs_max_single"] is not None, x["dep_delta_paired_vs_max_single"] or 0.0),
        reverse=True,
    )

    n_annotated = len(functional_paralogs)
    n_buffering = sum(1 for p in functional_paralogs if p["buffering_class"] in ("strong", "partial"))

    # Skill-level class from the strongest MEASURED partner. If every partner is
    # unmeasured (no single-KO baseline anywhere), the buffering call is unavailable,
    # not `none` — absence of the baseline is not evidence of no buffering.
    measured = [p for p in functional_paralogs if p["dep_delta_paired_vs_max_single"] is not None]
    if not measured:
        return _empty_result("paralog_single_ko_baseline_unavailable", n_annotated=n_annotated)
    strongest = measured[0]
    return {
        "paralog_buffering_class": strongest["buffering_class"],
        "n_paralogs_annotated": n_annotated,
        "n_paralogs_functionally_buffering": n_buffering,
        "functional_paralogs": functional_paralogs[:20],
        # strongest_paralog_symbol = MAX-delta partner (see primary path note); read functional_paralogs
        # for the full ranked list rather than treating this scalar as the canonical redundant paralog.
        "strongest_paralog_symbol": strongest["partner_gene_symbol"],
        # strongest_paralog_ohnolog is UNKNOWN (not False) on this FALLBACK path. The ohnolog annotation
        # (Ensembl-Compara LCA) is produced solely by the offline product build; this raw-CSV recompute
        # cannot derive it. Emit None + an explicit `unknown_fallback` STATUS so the value is never
        # confused with a genuine "not an ohnolog" (False) — the strong_ohnolog_paralog predicate would
        # otherwise silently read None==True as False and suppress the escape-risk warning (a latent
        # false-negative). The status field lets the card emit an honest `ohnolog_unknown` caveat instead.
        "strongest_paralog_ohnolog": None,
        "strongest_paralog_ohnolog_status": "unknown_fallback",
        "strongest_paralog_delta": strongest["dep_delta_paired_vs_max_single"],
        "method_version": "0.3.1-fallback-raw-csv",  # fallback recompute (product unreachable)
        # PROVENANCE: this FALLBACK recomputes buffering LIVE from the RAW source CSV
        # (ParalogGeneEffect.csv) — report exactly that, and name the derived product as the
        # preferred source the primary path reads instead.
        "_data_source": "depmap-consortium-26q1-paralogs/ParalogGeneEffect.csv (raw, live recompute — FALLBACK)",
        "_data_source_upstream": PARALOG_SOURCE_MANIFEST_ID,
        "_intended_derived_product": "depmap-paralog-buffering-per-gene-v1",
        "_paralog_ohnolog_note": (
            "ohnolog annotation unavailable on the raw-CSV fallback path; it is populated by the "
            "PRIMARY read from the derived product depmap-paralog-buffering-per-gene-v1. This "
            "fallback fired because that product was unreachable at read time."
        ),
    }


def _empty_result(note: str, n_annotated: int = 0) -> dict:
    return {
        "paralog_buffering_class": "data_unavailable",
        "n_paralogs_annotated": n_annotated,
        "n_paralogs_functionally_buffering": 0,
        "functional_paralogs": [],
        "strongest_paralog_symbol": "",
        "strongest_paralog_ohnolog": None,  # card-declared field; always present (None when unmeasured)
        "strongest_paralog_ohnolog_status": "data_unavailable",  # no paralog data at all → not annotatable
        "strongest_paralog_delta": None,
        "method_version": "0.2.1",
        "_data_note": note,
    }
