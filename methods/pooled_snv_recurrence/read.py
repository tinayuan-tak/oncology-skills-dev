"""pooled_snv_recurrence.read — pooled multi-cohort SNV driver-recurrence + percentile.

Pools per-gene mutated/covered counts across THREE patient cohorts to make patient recurrence a robust,
verdict-relevant signal for the SNV class (scope-coherence Phase 2):
  - TCGA-MC3  (whole-EXOME)  — n_cov = full indication cohort (every gene covered).
  - AACR GENIE (panel)       — n_cov = coverage-correct (samples whose panel covers the gene).
  - MSK-CHORD  (panel)       — n_cov = coverage-correct (MSK-IMPACT panels).

POOLING = summed-counts / summed-coverage: pooled_freq = Σn_mut / Σn_cov — a single coverage-weighted
proportion that treats WES (n_cov = n_total) and panel (n_cov = panel-covering) uniformly and degrades
gracefully when a gene is panel-absent in some cohorts. We do NOT average per-cohort percentiles (that
double-normalizes and destroys the higher-N benefit). The pooled frequency is ranked among the pooled
null (all genes' pooled freqs, n_cov >= _MIN_COVERED). Verdict-RELEVANT via the recurrent_snv_driver rung.

CAVEAT (encoded in the manifest + card): MSK cohorts are metastatic/hypermutator-enriched → passenger
burden can inflate raw frequency; the within-indication percentile reframe partially controls it (all
genes rise together), but cross-cohort batch effects remain — hence `cohorts_contributing` provenance.
"""

from __future__ import annotations

from functools import lru_cache

from methods.catalog_query.read import s3_uri_for
from methods.indication_aliases import to_cohort_canonical

DEFAULT_CUTOFFS = {"top_1pct": 99.0, "top_decile": 90.0, "bottom_decile": 10.0}
_MIN_COVERED = 20  # pooled n_cov floor to rank a gene (mirrors the GENIE per-cohort floor)

# Precomputed per-(indication, gene) pooled-recurrence product (build_pooled_recurrence_table
# materialized per indication). Lets pooled_recurrence_for_gene push down ONE (indication, gene) row
# instead of rebuilding the pooled null LIVE — which loads the MSK-CHORD + GENIE panel-coverage maps
# and scans every cohort's MAF (~8-10s, the dominant cost of the mutation-hotspot-frequency card's
# pooled arm). Resolved lazily so import never breaks before the manifest is registered.
#
# v2 (2026-09-16) rebuilds the same schema against today's upstreams. v1 was materialized 2026-08-19
# against a FOUR-indication tcga-mc3-hotspot-frequency-v1, so BRCA and PRAD pooled the MSK-CHORD arm
# ALONE — 469 and 464 genes. That upstream now carries 31 indications including both, and GENIE serves
# both independently, so the same code pools all three arms: BRCA 469→16785 genes, PRAD 464→10711.
# Nothing in the producer hardcodes an indication→cohort map; availability is discovered per reader.
_POOLED_PRODUCT_ID = "pooled-snv-recurrence-v2"

# Assay breadth per cohort, for the context string's noun phrase. A percentile among PANEL genes and
# a percentile among EXOME-WIDE genes are materially different claims — panels are deliberately
# enriched for recurrently-mutated drivers, so their reference set is pre-selected for the very
# property being ranked, making a top-1% rank there much weaker. Naming the breadth in the prose is
# the human-readable half of what n_ranked_genes exposes to machines; getting it wrong (as the
# hardcoded "panel-covered genes" did for every pool containing whole-exome TCGA-MC3) overstates or
# understates the evidence at exactly the point a reader is deciding how much to believe it.
_COHORT_ASSAY_BREADTH = {"TCGA-MC3": "exome", "GENIE": "panel", "MSK-CHORD": "panel"}


def _frame_noun_phrase(frame_cohorts) -> str:
    """Noun phrase for WHAT the percentile's reference set contains, derived from the cohorts that
    built that reference set.

    Single source of the wording: the live path and the product path both call it, so the two context
    strings cannot drift apart (they are asserted byte-identical). Note the argument is the cohorts of
    the FRAME — the union over every ranked gene in the indication — NOT the cohorts of the one gene
    being reported. A GENIE-only gene can sit in an exome-wide frame, and it is the frame that the
    percentile is measured against.

    An UNRECOGNIZED cohort falls through to the breadth-neutral phrase rather than to either claim: a
    new arm whose assay we cannot classify must not silently inherit "exome-wide" (which would
    overstate) or "panel-covered" (which would understate)."""
    cohorts = [c for c in (frame_cohorts or []) if c]
    breadths = {_COHORT_ASSAY_BREADTH.get(c) for c in cohorts}
    if not cohorts or None in breadths:
        return "pooled-covered genes"
    if breadths == {"panel"}:
        return "panel-covered genes"
    return "pooled-covered genes (exome-wide, not panel-preselected)"


def ranked_frame_cohorts(ranked_entries) -> list:
    """Sorted union of the cohorts behind the ranked reference set — the frame's composition, as
    opposed to one gene's. Shared by the live path and the product builder so the value stored in the
    product is the same one the live path would compute."""
    out: set[str] = set()
    for e in ranked_entries:
        out.update(e["cohorts"])
    return sorted(out)


# ── pure pooling core (unit-testable, no I/O) ─────────────────────────────────────────────────────
def pool_gene_counts(per_cohort: dict) -> dict:
    """Merge {cohort_name: {gene: (n_mut, n_cov)}} → {gene: {n_mut, n_cov, cohorts}} by SUMMING counts.
    `cohorts` is the sorted list of cohorts that covered the gene (n_cov > 0) — the anti-pooling-artifact
    provenance. Pure; the concrete cohort readers below feed it."""
    pooled: dict[str, dict] = {}
    for cohort, counts in per_cohort.items():
        for gene, (n_mut, n_cov) in (counts or {}).items():
            if n_cov <= 0:
                continue
            e = pooled.setdefault(gene, {"n_mut": 0, "n_cov": 0, "cohorts": set()})
            e["n_mut"] += int(n_mut)
            e["n_cov"] += int(n_cov)
            e["cohorts"].add(cohort)
    for e in pooled.values():
        e["cohorts"] = sorted(e["cohorts"])
    return pooled


# ── concrete per-cohort count readers (module-level so tests can monkeypatch) ─────────────────────
def _mc3_gene_counts(indication: str) -> dict:
    """{gene: (n_mut, n_cov)} from the TCGA-MC3 hotspot-frequency aggregate (gene-summary rows). WES →
    n_cov = n_samples_in_indication (every gene covered). Empty on any absence (MC3 not the whole pool)."""
    from methods.gdc_somatic_hotspot.read import (
        _HOTSPOT_FREQUENCY_MANIFEST,
        _read_product_table,
        _resolve_aggregate_path,
    )

    try:
        tbl = _read_product_table(
            _resolve_aggregate_path(indication),
            _HOTSPOT_FREQUENCY_MANIFEST,
            filters=[("indication", "=", indication)],
            columns=["gene_symbol", "hotspot_protein_change", "n_samples_mutated", "n_samples_in_indication"],
        )
        if tbl is None:
            return {}
        df = tbl.to_pandas()
    except Exception:  # noqa: BLE001 — one cohort absent must not sink the pool
        return {}
    summary = df[df["hotspot_protein_change"].isnull()]
    out = {}
    for _, r in summary.iterrows():
        nmut, ncov = r.get("n_samples_mutated"), r.get("n_samples_in_indication")
        if nmut is not None and ncov not in (None, 0):
            out[str(r["gene_symbol"])] = (int(nmut), int(ncov))
    return out


def _genie_gene_counts(indication: str) -> dict:
    """{gene: (n_mut, n_cov)} from the GENIE coverage-correct frequencies (gene, freq, n_cov, n_mut)."""
    try:
        from methods.genie_panel_recurrence.read import _covered_gene_frequencies

        return {g: (int(n_mut), int(n_cov)) for g, _f, n_cov, n_mut in _covered_gene_frequencies(indication)}
    except Exception:  # noqa: BLE001
        return {}


def _msk_gene_counts(indication: str) -> dict:
    """{gene: (n_mut, n_cov)} from the MSK-CHORD coverage-correct frequencies (gene, n_mut, n_cov)."""
    try:
        from methods.msk_panel_coverage.read import msk_covered_gene_frequencies

        return {g: (int(n_mut), int(n_cov)) for g, n_mut, n_cov in msk_covered_gene_frequencies(indication)}
    except Exception:  # noqa: BLE001
        return {}


@lru_cache(maxsize=8)
def _pooled_for_indication(indication: str) -> dict:
    """{gene: {n_mut, n_cov, cohorts}} pooled across all contributing cohorts for one indication.

    The reader dict is built INSIDE the function (not module-level) so the names resolve against the
    current module globals at call time — that keeps the three cohort readers monkeypatchable in tests.
    """
    readers = {"TCGA-MC3": _mc3_gene_counts, "GENIE": _genie_gene_counts, "MSK-CHORD": _msk_gene_counts}
    per_cohort = {name: reader(indication) for name, reader in readers.items()}
    return pool_gene_counts(per_cohort)


def _pooled_from_product(target: str, indication: str, cutoffs: dict = None):
    """Read ONE (indication, gene) pooled-recurrence row from the precomputed product (pushdown).

    Returns the SAME dict pooled_recurrence_for_gene builds for a RANKABLE gene (n_cov >= _MIN_COVERED)
    — the product stores exactly those genes, with the percentile ranked among the same pooled null, and
    n_ranked_genes to reconstruct the context string byte-identically. Returns None when the product is
    UNREACHABLE (manifest not registered → s3_uri_for raises; object absent → 404) OR the (indication,
    gene) is NOT a rankable row — the caller then falls back to the LIVE path, which is the ONLY place
    the two non-rankable sub-cases are distinguished (uncovered → n_cov 0 data_unavailable; covered-but-
    thin → freq emitted, pct None). A transient/creds error re-raises. Cutoffs other than the default
    change the class thresholds, so a non-default cutoffs also routes to live (the product baked DEFAULT)."""
    if cutoffs is not None:
        return None
    try:
        uri = s3_uri_for(_POOLED_PRODUCT_ID)
    except Exception:  # noqa: BLE001  # absence-discipline: exempt -- LOCAL catalog manifest lookup, not an S3 read; a raise means the derived manifest is not registered → fall back to the live pooled computation
        return None
    try:
        import pandas as pd
        import pyarrow.fs as fs
        import pyarrow.parquet as pq

        path = uri.replace("s3://", "", 1)
        df = pq.read_table(
            path, filesystem=fs.S3FileSystem(), filters=[("indication", "=", indication), ("gene_symbol", "=", target)]
        ).to_pandas()
        if df.empty:
            return None  # not a rankable row → live fallback (distinguishes uncovered vs too-thin)
        row = df.iloc[0]
        cohorts = str(row["cohorts_contributing"]).split(",") if row["cohorts_contributing"] else []
        n_ranked = int(row["n_ranked_genes"])
        # Frame composition is an INDICATION-level property, so it cannot be derived from this one
        # pushed-down row's own cohorts — v2 records it as a column. A pre-v2 vintage lacks the column
        # entirely (row.get → None) and its breadth is then genuinely unknown, so _frame_noun_phrase's
        # neutral fall-through is the honest answer rather than a re-guess.
        raw_frame = row.get("ranked_frame_cohorts")
        if raw_frame is None or (isinstance(raw_frame, float) and pd.isna(raw_frame)):
            raw_frame = ""
        frame_cohorts = str(raw_frame).split(",") if raw_frame else []
        return {
            "pooled_mutation_frequency": float(row["pooled_mutation_frequency"]),
            "n_covered_pooled": int(row["n_covered_pooled"]),
            "n_mutated_pooled": int(row["n_mutated_pooled"]),
            "pooled_driver_recurrence_percentile": (
                None
                if pd.isna(row["pooled_driver_recurrence_percentile"])
                else float(row["pooled_driver_recurrence_percentile"])
            ),
            "pooled_driver_recurrence_class": str(row["pooled_driver_recurrence_class"]),
            "cohorts_contributing": cohorts,
            "n_ranked_genes": n_ranked,
            "pooled_recurrence_context": (
                f"pooled {'+'.join(cohorts)} — {target} ranks among {n_ranked} "
                f"{_frame_noun_phrase(frame_cohorts)} in {indication} (summed-counts/summed-coverage)"
            ),
        }
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        if not (isinstance(e, FileNotFoundError) or is_definitively_absent(e)):
            raise
        return None  # product object genuinely absent → live fallback


def pooled_recurrence_for_gene(target: str, indication: str, cutoffs: dict = None) -> dict:
    """Pooled multi-cohort recurrence for one (target, indication). Returns pooled_mutation_frequency
    (Σn_mut/Σn_cov), n_covered_pooled, n_mutated_pooled, pooled_driver_recurrence_percentile + _class,
    cohorts_contributing, n_ranked_genes, and a context string. data_unavailable when no cohort covers
    the gene.

    n_ranked_genes is the SIZE OF THE REFERENCE SET the percentile is ranked against, and it is not a
    detail: it varies by more than an order of magnitude across indications because the contributing
    cohorts do. MEASURED in framework-run 2026-09-11-verdict-only-tables — PIK3CA/BRCA ranked at the
    99.68th percentile among 469 genes (MSK-CHORD panel only), KRAS/COADREAD at the 99.97th among
    18495 (GENIE + MSK-CHORD + whole-exome TCGA-MC3). Both render as "top_1pct", but a top-1% rank
    among 469 PANEL genes is a much weaker statement than among 18495 exome-wide genes, since panels
    are deliberately enriched for recurrently-mutated drivers — the reference set is pre-selected for
    the very property being ranked. Until now that count existed only inside the English
    pooled_recurrence_context string, so a consumer comparing two indications' percentiles had to
    regex prose to discover they were not comparable. Every return path now carries it as a field
    (None where no ranking was attempted).

    Prefers the precomputed per-(indication, gene) product (pushdown; avoids rebuilding the pooled null
    LIVE — the MSK-CHORD + GENIE panel-coverage loads). Falls back to the live computation when the
    product is unreachable or the gene is not a rankable product row. Byte-identical either way."""
    indication = to_cohort_canonical(indication)  # LUAD/LUSC -> NSCLC (patient-cohort canonical grain)
    prod = _pooled_from_product(target, indication, cutoffs)
    if prod is not None:
        return prod
    pooled = _pooled_for_indication(indication)
    if not pooled:
        return {
            "pooled_driver_recurrence_class": "data_unavailable",
            "pooled_driver_recurrence_percentile": None,
            "pooled_mutation_frequency": None,
            "n_covered_pooled": None,
            "n_mutated_pooled": None,
            "cohorts_contributing": [],
            "n_ranked_genes": None,  # no cohort ⇒ no reference set was built
            "pooled_recurrence_context": f"no pooled SNV recurrence cohort for {indication}",
        }
    entry = pooled.get(target)
    if entry is None or entry["n_cov"] == 0:
        return {
            "pooled_driver_recurrence_class": "data_unavailable",
            "pooled_driver_recurrence_percentile": None,
            "pooled_mutation_frequency": None,
            "n_covered_pooled": 0,
            "n_mutated_pooled": 0,
            "cohorts_contributing": [],
            "n_ranked_genes": None,  # gene uncovered ⇒ it was never placed against the reference set
            "pooled_recurrence_context": f"{target} covered by no pooled cohort in {indication}",
        }
    freq = entry["n_mut"] / entry["n_cov"]
    ranked = [e for e in pooled.values() if e["n_cov"] >= _MIN_COVERED]
    null_vec = tuple(e["n_mut"] / e["n_cov"] for e in ranked)
    if entry["n_cov"] < _MIN_COVERED or not null_vec:
        pct, cls = None, "data_unavailable"
        note = f"{target} pooled coverage {entry['n_cov']} < {_MIN_COVERED} (too thin to rank)"
    else:
        from methods.percentile_null import classify_percentile, percentile_rank

        pct = percentile_rank(freq, null_vec)
        cls = classify_percentile(pct, cutoffs or DEFAULT_CUTOFFS)
        note = (
            f"pooled {'+'.join(entry['cohorts'])} — {target} ranks among {len(null_vec)} "
            f"{_frame_noun_phrase(ranked_frame_cohorts(ranked))} in {indication} "
            f"(summed-counts/summed-coverage)"
        )
    return {
        "pooled_mutation_frequency": freq,
        "n_covered_pooled": entry["n_cov"],
        "n_mutated_pooled": entry["n_mut"],
        "pooled_driver_recurrence_percentile": pct,
        "pooled_driver_recurrence_class": cls,
        "cohorts_contributing": entry["cohorts"],
        # The reference-set size behind `pct`. Reported even on the too-thin branch (where pct is
        # None): the null WAS built there, the gene just could not be placed in it, and saying how
        # big the frame is remains informative. 0 when no rankable gene existed at all.
        "n_ranked_genes": len(null_vec),
        "pooled_recurrence_context": note,
    }


def build_pooled_recurrence_table(indication: str):
    """Materialize the per-gene pooled recurrence table for one indication. One row per pooled-covered
    gene (n_cov >= _MIN_COVERED); percentile ranked among that same set."""
    import pyarrow as pa

    pooled = _pooled_for_indication(indication)
    rankable = {g: e for g, e in pooled.items() if e["n_cov"] >= _MIN_COVERED}
    if not rankable:
        return pa.Table.from_pylist([], schema=_schema())
    from methods.percentile_null import classify_percentile, percentile_rank

    null_vec = tuple(e["n_mut"] / e["n_cov"] for e in rankable.values())
    n_ranked = len(null_vec)  # == len(null_vec) in pooled_recurrence_for_gene → lets the product-read
    # reader reconstruct the context string byte-identically (see _pooled_from_product).
    # Same reason, for the other half of that string: the frame's noun phrase depends on the cohorts
    # behind the WHOLE reference set, which a single pushed-down row cannot recover from its own
    # cohorts_contributing. Denormalized onto every row so the pushdown stays one-row.
    frame_cohorts = ",".join(ranked_frame_cohorts(rankable.values()))
    rows = []
    for gene, e in rankable.items():
        freq = e["n_mut"] / e["n_cov"]
        pct = percentile_rank(freq, null_vec)
        rows.append(
            {
                "indication": indication,
                "gene_symbol": gene,
                "n_covered_pooled": e["n_cov"],
                "n_mutated_pooled": e["n_mut"],
                "pooled_mutation_frequency": freq,
                "pooled_driver_recurrence_percentile": pct,
                "pooled_driver_recurrence_class": classify_percentile(pct, DEFAULT_CUTOFFS),
                "cohorts_contributing": ",".join(e["cohorts"]),
                "n_ranked_genes": n_ranked,
                "ranked_frame_cohorts": frame_cohorts,
            }
        )
    rows.sort(key=lambda r: r["gene_symbol"])
    return pa.Table.from_pylist(rows, schema=_schema())


def _schema():
    import pyarrow as pa

    return pa.schema(
        [
            pa.field("indication", pa.string()),
            pa.field("gene_symbol", pa.string()),
            pa.field("n_covered_pooled", pa.int64()),
            pa.field("n_mutated_pooled", pa.int64()),
            pa.field("pooled_mutation_frequency", pa.float64()),
            pa.field("pooled_driver_recurrence_percentile", pa.float64()),
            pa.field("pooled_driver_recurrence_class", pa.string()),
            pa.field("cohorts_contributing", pa.string()),
            pa.field("n_ranked_genes", pa.int64()),
            # Cohorts behind the INDICATION's whole ranked reference set (this row's own cohorts are
            # cohorts_contributing, and the two differ whenever the arms cover different genes). New
            # in v2; absent in v1, which the reader tolerates.
            pa.field("ranked_frame_cohorts", pa.string()),
        ]
    )
