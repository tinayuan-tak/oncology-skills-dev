"""cooccurrence_fisher_pancohort.read — panel-intersect Fisher co-mutation reader.

Consumer: co-mutation-and-mutual-exclusivity evidence card (Phase E) via
differentiation-landscape skill.

Product scope (what the bound derived product ACTUALLY contains — 2026-08-31):
  The derived parquet holds per-(cohort, source) Fisher/DISCOVER/SELECT pair rows.
  `source` is only ever `tcga_mc3` or `genie_v19` — there is NO cross-source
  `pooled` row and NO cross-source pooling is performed (see the manifest's
  "No cross-source cohort alignment" note). `pooled_eligible` is a PER-ROW flag
  marking pairs where both genes fall in the 166-gene GENIE panel-intersect; it is
  DISPLAY/interpretation metadata, it does NOT gate a pooled statistic (none exists).

Indication-scoped verdict discipline (2026-08-31 — differentiation-landscape review
B8-01/B8-02 fix):
  The VERDICT-driving fields (`cooccurrence_class`, `has_cooccurring_driver`,
  `has_mutually_exclusive_driver`) are computed from the INDICATION-matched cohort
  rows only — NOT pooled across all ~53 cohorts. Pooling every cohort let the SAME
  partner appear co-occurring in one cancer and mutually-exclusive in another (e.g.
  KRAS×TP53: +2.86 in Pancreatic, -1.35 in NSCLC, both q≈0) and thereby manufacture a
  spurious `both_patterns_present`. Two guards close that:
    1. Verdict scope = the indication's cohort(s) (INDICATION_TO_COOCCURRENCE_COHORTS);
       no indication / unmapped → the single PANCAN cohort, labelled `pan_cohort`;
       a mapped indication with no matching cohort row → honest `data_unavailable`.
    2. Within the scope, each partner is collapsed to its single most-significant row,
       so one partner can drive AT MOST ONE of {co-occurring, mutually-exclusive}. A
       `both_patterns_present` now requires TWO DISTINCT partners (legitimate biology).
    3. Multiplicity: the scoped q is Bonferroni-scaled by the number of distinct
       (cohort, source) test families in the scope (stage-03 already BH-controls the
       partner axis WITHIN each family), controlling the cross-cohort min-q selection.
  The pan-cohort `top_cooccurring` / `top_mutually_exclusive` landscape + `n_*` counts
  are retained UNCHANGED as DISPLAY context.

Wiring approach (data-layer hardening 2026-08-22 — streamed pushdown):
  - STREAMS the target's rows out of the derived parquet at
    s3://onc-compbio/data-catalog/derived/pancohort-cooccurrence-fisher-v1/
    via a pyarrow S3FileSystem with predicate pushdown on the manifest
    primary_filter_column (`target_gene_symbol`, the product's sort key) — only
    the target's row-groups transit the wire; NO whole-file download.
  - Emits `data_unavailable` gracefully only when the product object is
    DEFINITIVELY absent (NoSuchKey/404); transient/creds/broken-env failures
    surface a cause-accurate breadcrumb (absence discipline).

Runtime discipline: process-wide S3FileSystem singleton + per-target read cache
(+ a definitive-absence latch), so repeated targets don't re-hit S3.
"""

from __future__ import annotations

import threading
from typing import Optional


DERIVED_MANIFEST_ID = "pancohort-cooccurrence-fisher-v1"

# Framework indication code → the cohort label(s) the product uses for the VERDICT scope.
# The product mixes TWO cohort vocabularies: TCGA MC3 study codes (e.g. COAD, LUAD, PAAD)
# and GENIE OncoTree main-cancer-type names (e.g. "Colorectal Cancer", "Pancreatic Cancer").
# Mirrors the sibling indication→cohort discipline in methods/driver_role_overlay +
# methods/functional_gene_state: map ONLY to labels VERIFIED present in the product, so a
# mapped indication either scopes to real rows or honestly abstains — never silently matches
# nothing while appearing mapped. An indication ABSENT from this map falls back to the single
# PANCAN cohort (labelled `pan_cohort` — display, not an indication claim). Do NOT add a guessed
# variant; if a new indication has no verified cohort label, leave it OUT (PANCAN fallback is safe).
INDICATION_TO_COOCCURRENCE_COHORTS: dict[str, tuple[str, ...]] = {
    "COADREAD": ("COAD", "READ", "Colorectal Cancer"),
    "COAD": ("COAD", "Colorectal Cancer"),
    "READ": ("READ", "Colorectal Cancer"),
    "CRC": ("COAD", "READ", "Colorectal Cancer"),
    "LUAD": ("LUAD", "Non-Small Cell Lung Cancer"),
    "LUSC": ("LUSC", "Non-Small Cell Lung Cancer"),
    "NSCLC": ("LUAD", "LUSC", "Non-Small Cell Lung Cancer"),
    "SCLC": ("Small Cell Lung Cancer",),
    "BRCA": ("BRCA", "Breast Cancer"),
    "PAAD": ("PAAD", "Pancreatic Cancer"),
    "PDAC": ("PAAD", "Pancreatic Cancer"),
    "SKCM": ("SKCM", "Melanoma"),
    "MEL": ("SKCM", "Melanoma"),
    "STAD": ("Esophagogastric Cancer",),
    "GC": ("Esophagogastric Cancer",),
    "GEJ": ("Esophagogastric Cancer",),
    "ESCA": ("Esophagogastric Cancer",),
    "PRAD": ("Prostate Cancer",),
    "OV": ("OV", "Ovarian Cancer", "Ovarian/Fallopian Tube Cancer"),
    "KIRC": ("KIRC", "Renal Cell Carcinoma"),
    "RCC": ("KIRC", "Renal Cell Carcinoma"),
    "GBM": ("GBM", "Glioma"),
    "LGG": ("LGG", "Glioma"),
    "GLIOMA": ("GBM", "LGG", "Glioma"),
    "HNSC": ("Head and Neck Cancer",),
    "HNSCC": ("Head and Neck Cancer",),
    "BLCA": ("Bladder Cancer",),
    "LIHC": ("Hepatobiliary Cancer",),
    "HCC": ("Hepatobiliary Cancer",),
    "UCEC": ("Endometrial Cancer",),
}

# The single pan-cancer cohort used for the verdict when no indication is supplied / mapped.
_PANCOHORT_LABEL = "PANCAN"

# Pushdown key: the derived manifest's query_optimization.primary_filter_column, which is also its
# sort column. The product is SORTED by target_gene_symbol, so a per-target equality filter lets
# pyarrow skip non-matching row-groups — only the target's row-groups stream over the wire.
_PRIMARY_FILTER_COLUMN = "target_gene_symbol"

# Process-wide latch: True = product present, False = product DEFINITIVELY absent (NoSuchKey/404 —
# short-circuits every later target in the process), None = undetermined / transient failure (retry).
_DERIVED_STATUS: Optional[bool] = None

# Per-target streamed-read cache, keyed UPPER(target). Only SUCCESSFUL reads (incl. an empty list)
# are cached; a transient/creds/broken-env failure RAISES without caching so a later call retries —
# an @lru_cache over the raw read would memoize that failure into a permanent data_unavailable
# (mirrors methods/combo_drug_anchor).
_ROWS_CACHE: dict = {}

_S3FS = None
_S3FS_LOCK = threading.Lock()


def _get_s3fs():
    """Process-wide pyarrow S3FileSystem singleton (region pinned to us-east-1, the onc-compbio
    bucket, to skip the region-probe round-trip). Constructing one costs ~0.4s and this reader can
    fire for several targets per run (differentiation-landscape / target-profile fan-out), so build
    it ONCE. Double-checked locking so concurrent first-callers build a single instance. Mirrors
    the sibling dge_deseq2._get_s3fs / depmap_common.parquet._get_s3fs."""
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                import pyarrow.fs as fs

                _S3FS = fs.S3FileSystem(region="us-east-1")
    return _S3FS


def _read_target_rows(sym: str) -> Optional[list]:
    """STREAMED pyarrow pushdown of ONE target's co-occurrence rows — replaces the former whole-file
    `download_file` + local `pd.read_parquet`. Pushes the manifest primary_filter_column
    (target_gene_symbol == sym) AND the original bh_q_value <= 0.5 predicate, so only the target's
    row-groups stream over the wire (no download). Returns a list-of-dict records — identical
    shape/dtypes to the former `df.iloc[...].to_dict(orient="records")` (same pyarrow->pandas path) —
    or None when the product object is DEFINITIVELY absent (NoSuchKey/404). RAISES on transient /
    creds / broken-env so the public boundary surfaces the real cause instead of a silent dead axis
    (absence discipline; mirrors methods/combo_drug_anchor + target_id_sidecar.is_definitively_absent).
    Successful reads (incl. an empty list) are cached per target."""
    global _DERIVED_STATUS
    if _DERIVED_STATUS is False:
        return None
    if sym in _ROWS_CACHE:
        return _ROWS_CACHE[sym]
    try:
        from methods.catalog_query.read import bucket_key_for
        import pyarrow.parquet as pq

        bucket, key = bucket_key_for(DERIVED_MANIFEST_ID)
        tbl = pq.read_table(
            f"{bucket}/{key}",
            filesystem=_get_s3fs(),
            filters=[(_PRIMARY_FILTER_COLUMN, "=", sym), ("bh_q_value", "<=", 0.5)],
        )
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        # Only a GENUINE no-object (NoSuchKey/404 or pyarrow FileNotFoundError) is absence -> latch
        # _DERIVED_STATUS False (short-circuits later targets) and return None. A transient/creds/
        # broken-env failure is NOT absence -> re-raise (neither cached nor latched, so a later call
        # retries) and let the public boundary record the real cause.
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            _DERIVED_STATUS = False
            return None
        raise
    _DERIVED_STATUS = True
    # to_pandas().to_dict(orient="records") reproduces the exact records the former
    # pd.read_parquet(...).iloc[...].to_dict(orient="records") emitted (same dtypes).
    rows = tbl.to_pandas().to_dict(orient="records")
    _ROWS_CACHE[sym] = rows
    return rows


def _scope_cohorts(indication: Optional[str]) -> tuple[Optional[frozenset], str]:
    """Resolve the framework indication → the cohort label set that scopes the VERDICT.

    Returns (cohort_set, scope_label):
      - (frozenset(labels), "indication") when the indication maps to product cohort labels,
      - (None, "pan_cohort") when no indication is supplied OR the indication is unmapped —
        the caller then scopes the verdict to the single PANCAN cohort (display, not an
        indication-specific claim).
    """
    if not indication or not str(indication).strip():
        return (None, "pan_cohort")
    cohorts = INDICATION_TO_COOCCURRENCE_COHORTS.get(str(indication).upper().strip())
    if cohorts:
        return (frozenset(cohorts), "indication")
    return (None, "pan_cohort")


def _rows_in_scope(rows: list[dict], scope_cohorts: Optional[frozenset]) -> list[dict]:
    """Filter the target's rows to the verdict scope. ``None`` scope → the PANCAN cohort."""
    if scope_cohorts is None:
        return [r for r in rows if str(r.get("cohort", "")) == _PANCOHORT_LABEL]
    return [r for r in rows if str(r.get("cohort", "")) in scope_cohorts]


def _classify_partners(best_items, n_families: int) -> tuple[str, bool, bool]:
    """Classify a set of per-partner (q, log2_or) bests into (cooccurrence_class, has_cooc_driver,
    has_mutex_driver), applying the strong/modest q + log2-OR cutpoints with the shared Bonferroni
    family scaling. Precedence: strong_cooc & strong_mutex → both_patterns_present; then strong_cooc;
    strong_mutex; modest_cooc; modest_mutex; else ns."""
    strong_cooc = modest_cooc = strong_mutex = modest_mutex = False
    has_cooc_driver = has_mutex_driver = False
    for q, log2_or in best_items:
        qc = min(1.0, q * n_families)  # Bonferroni across scoped (cohort, source) families
        if qc < 0.001:
            if log2_or > 1.0:
                strong_cooc = True
                has_cooc_driver = True
            elif log2_or < -1.0:
                strong_mutex = True
                has_mutex_driver = True
        if qc < 0.05:
            if log2_or > 0.5:
                modest_cooc = True
            elif log2_or < -0.5:
                modest_mutex = True
    if strong_cooc and strong_mutex:
        cls = "both_patterns_present"
    elif strong_cooc:
        cls = "strong_cooccurring"
    elif strong_mutex:
        cls = "strong_mutually_exclusive"
    elif modest_cooc:
        cls = "modest_cooccurring"
    elif modest_mutex:
        cls = "modest_mutually_exclusive"
    else:
        cls = "ns"
    return (cls, has_cooc_driver, has_mutex_driver)


def _scoped_signals(rows: list[dict]) -> tuple[str, bool, bool, str]:
    """Derive the co-occurrence class + driver flags from a SCOPED (indication- or PANCAN-)
    restricted row set. Returns (cooccurrence_class, has_cooccurring_driver, has_mutually_exclusive_driver,
    cooccurrence_class_prefloor).

    Two robustness guards (B8-01 / B8-02 fix):
      * PER-PARTNER collapse — each partner contributes only its single most-significant
        (min bh_q) row, so one partner can satisfy AT MOST ONE of {co-occurring, mutex}.
        A `both_patterns_present` therefore requires TWO DISTINCT partners; the same
        partner carrying opposite signs in different cohorts can no longer manufacture it.
      * Multiplicity — the per-partner q is Bonferroni-scaled by the number of distinct
        (cohort, source) test families in the scope. Stage 03 BH-controls the partner axis
        WITHIN each family; this controls the cross-cohort min-q selection ACROSS families.
        With a single family (typical after scoping / PANCAN) the factor is 1 → unscaled.

    TCGA-WES-ONLY (panel-absent passenger) FLOOR: without a guard the class keyed on q + log2-OR
    ALONE and never asked whether the co-mutation signal is a TARGETED-PANEL claim at all. A gene
    sequenced ONLY in TCGA whole-exome — never on a GENIE targeted panel (no panel-intersect-eligible
    pair AND no GENIE-source significant pair anywhere in scope) — is typically a large/passenger
    gene (PCLO, TTN, MUC16, CSMD3), and its per-source co-occurrence is a tumor-mutational-burden /
    gene-length artifact, not biology (live: PCLO/COADREAD read `strong_cooccurring` off 3961
    tcga_mc3-only pairs). Such a target is demoted to `ns` (no panel-comparable co-mutation claim).

    Deliberately NARROW — GENIE presence, not panel-INTERSECT membership, is the gate. A real driver
    off the restrictive 166-gene ∩-of-10-workhorse-panels (e.g. KEAP1/LUAD, sequenced on GENIE panels
    with a genuine STK11 co-mutation / EGFR mutual-exclusivity signal) has GENIE-source significant
    pairs and is NOT touched. So every target with ANY panel-eligible pair OR ANY GENIE-source
    significant pair — every panel-present driver and every off-intersect-but-on-GENIE driver — keeps
    its exact pre-floor class (byte-identical). Only pure-TCGA-WES passengers flip. The un-floored
    call is preserved verbatim as `cooccurrence_class_prefloor` for audit.
    """
    if not rows:
        return ("ns", False, False, "ns")
    n_families = max(1, len({(r.get("cohort"), r.get("source")) for r in rows}))
    # partner → (best_q, log2_or_at_best_q)  — identical to the pre-floor per-partner collapse
    best: dict[str, tuple[float, float]] = {}
    for r in rows:
        partner = str(r.get("partner_gene_symbol", "")).strip().upper()
        if not partner:
            continue
        q = float(r.get("bh_q_value") or 1.0)
        if partner not in best or q < best[partner][0]:
            best[partner] = (q, float(r.get("log2_odds_ratio") or 0.0))

    prefloor_cls, has_cooc_driver, has_mutex_driver = _classify_partners(best.values(), n_families)

    # TCGA-WES-only passenger gate: no panel-eligible pair AND no GENIE-source significant pair.
    any_eligible = any(bool(r.get("pooled_eligible", False)) for r in rows)
    any_genie_sig = any(
        "genie" in str(r.get("source", "")).lower() and float(r.get("bh_q_value") or 1.0) < 0.05 for r in rows
    )
    if not any_eligible and not any_genie_sig:
        return ("ns", False, False, prefloor_cls)  # demote; audit keeps the raw call
    return (prefloor_cls, has_cooc_driver, has_mutex_driver, prefloor_cls)


def read_target_summary(target: str, indication: str = None) -> dict:
    sym = target.upper().strip()
    try:
        # Streamed per-target pushdown. None = product definitively absent (NoSuchKey/404);
        # RAISES on transient/creds/broken-env, caught below with a cause-accurate breadcrumb.
        rows = _read_target_rows(sym)
    except Exception as e:
        return _empty(f"cooccurrence_load_failed: {type(e).__name__}: {e}")
    if rows is None:
        return _empty("cooccurrence_data_unavailable")
    if not rows:
        return _empty("target_not_in_cooccurrence_scan")

    # Top-cooccurring + top-mutually-exclusive lists (ranked by ranking_score
    # if available, else by -log10(q) * sign(log2_or))
    def _rank(r):
        rs = r.get("ranking_score")
        if rs is not None:
            try:
                return float(rs)
            except (ValueError, TypeError):
                pass
        q = float(r.get("bh_q_value") or 1.0)
        log2_or = float(r.get("log2_odds_ratio") or 0.0)
        import math

        return -math.log10(max(q, 1e-300)) * (1 if log2_or > 0 else -1 if log2_or < 0 else 0)

    def _stripped(r: dict) -> dict:
        return {
            "partner_gene_symbol": r.get("partner_gene_symbol"),
            "log2_odds_ratio": r.get("log2_odds_ratio"),
            "bh_q_value": r.get("bh_q_value"),
            "source": r.get("source"),
            "pooled_eligible": bool(r.get("pooled_eligible", False)),
        }

    # DISPLAY landscape (PAN-COHORT, verdict-inert): dedup to one row per partner, keeping the
    # first (= lowest bh_q_value, the product is sorted target→bh_q_value). No cross-source
    # `pooled` row exists (see module docstring), so this is a straight per-partner best-of.
    seen: dict[str, dict] = {}
    for r in rows:
        partner = str(r.get("partner_gene_symbol", "")).strip().upper()
        if partner and partner not in seen:
            seen[partner] = r

    top_cooc = sorted((v for v in seen.values() if float(v.get("log2_odds_ratio") or 0) > 0), key=lambda r: -_rank(r))
    top_mutex = sorted((v for v in seen.values() if float(v.get("log2_odds_ratio") or 0) < 0), key=lambda r: _rank(r))

    n_sig_cooc = sum(
        1 for r in top_cooc if float(r.get("bh_q_value") or 1) < 0.05 and float(r.get("log2_odds_ratio") or 0) > 0.5
    )
    n_sig_mutex = sum(
        1 for r in top_mutex if float(r.get("bh_q_value") or 1) < 0.05 and float(r.get("log2_odds_ratio") or 0) < -0.5
    )

    # ── VERDICT (indication-scoped) ──────────────────────────────────────────────
    # Scope the verdict-driving fields to the indication's cohort(s); pool NOTHING across
    # unrelated cohorts (that manufactured spurious both_patterns_present — B8-01/B8-02).
    scope_cohorts, scope_label = _scope_cohorts(indication)
    scoped_rows = _rows_in_scope(rows, scope_cohorts)
    if scope_label == "indication" and not scoped_rows:
        # Indication maps to real cohort labels but the target has no row there → honest
        # abstention on the VERDICT, while the pan-cohort landscape below stays as display.
        cooccurrence_class = "data_unavailable"
        cooccurrence_class_prefloor = "data_unavailable"
        cooccurrence_scope = "unavailable"
        has_cooc_driver = has_mutex_driver = False
        scoped_cohorts: list[str] = []
    else:
        (cooccurrence_class, has_cooc_driver, has_mutex_driver, cooccurrence_class_prefloor) = _scoped_signals(
            scoped_rows
        )
        cooccurrence_scope = scope_label
        scoped_cohorts = sorted({str(r.get("cohort", "")) for r in scoped_rows})

    return {
        "cooccurrence_class": cooccurrence_class,  # VERDICT-DRIVING (indication-scoped, panel-floored)
        # AUDIT: the raw pre-floor class (all partners incl. panel-absent per-source-only pairs). When it
        # DIFFERS from cooccurrence_class the target's pattern rested on panel-ineligible pairs (possible
        # TMB/gene-length artifact); verdict-inert (no rule keys on it).
        "cooccurrence_class_prefloor": cooccurrence_class_prefloor,
        "cooccurrence_scope": cooccurrence_scope,  # indication | pan_cohort | unavailable
        "scoped_cohorts": scoped_cohorts,  # cohort label(s) the verdict used
        "has_cooccurring_driver": has_cooc_driver,  # VERDICT-DRIVING (scoped)
        "has_mutually_exclusive_driver": has_mutex_driver,  # scoped
        # ── pan-cohort DISPLAY landscape (verdict-inert) ──
        "n_significant_cooccurring": n_sig_cooc,
        "n_significant_mutually_exclusive": n_sig_mutex,
        "n_pairs_panel_intersect_eligible": sum(1 for r in rows if bool(r.get("pooled_eligible", False))),
        "n_pairs_per_source_only": sum(1 for r in rows if not bool(r.get("pooled_eligible", False))),
        "top_cooccurring": [_stripped(r) for r in top_cooc[:10]],
        "top_mutually_exclusive": [_stripped(r) for r in top_mutex[:10]],
        "method_version": "0.1.0",
        "_data_source": DERIVED_MANIFEST_ID,
    }


def _empty(note: str) -> dict:
    return {
        "cooccurrence_class": "data_unavailable",
        "cooccurrence_class_prefloor": "data_unavailable",
        "cooccurrence_scope": "unavailable",
        "scoped_cohorts": [],
        "n_significant_cooccurring": 0,
        "n_significant_mutually_exclusive": 0,
        "n_pairs_panel_intersect_eligible": 0,
        "n_pairs_per_source_only": 0,
        "top_cooccurring": [],
        "top_mutually_exclusive": [],
        "has_cooccurring_driver": False,
        "has_mutually_exclusive_driver": False,
        "method_version": "0.1.0",
        "_data_note": note,
    }
