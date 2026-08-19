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
from typing import Optional

DEFAULT_CUTOFFS = {"top_1pct": 99.0, "top_decile": 90.0, "bottom_decile": 10.0}
_MIN_COVERED = 20  # pooled n_cov floor to rank a gene (mirrors the GENIE per-cohort floor)


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
        _read_product_table, _resolve_aggregate_path, _HOTSPOT_FREQUENCY_MANIFEST)
    try:
        tbl = _read_product_table(
            _resolve_aggregate_path(indication), _HOTSPOT_FREQUENCY_MANIFEST,
            filters=[("indication", "=", indication)],
            columns=["gene_symbol", "hotspot_protein_change", "n_samples_mutated", "n_samples_in_indication"])
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


def pooled_recurrence_for_gene(target: str, indication: str, cutoffs: dict = None) -> dict:
    """Pooled multi-cohort recurrence for one (target, indication). Returns pooled_mutation_frequency
    (Σn_mut/Σn_cov), n_covered_pooled, n_mutated_pooled, pooled_driver_recurrence_percentile + _class,
    cohorts_contributing, and a context string. data_unavailable when no cohort covers the gene."""
    pooled = _pooled_for_indication(indication)
    if not pooled:
        return {"pooled_driver_recurrence_class": "data_unavailable",
                "pooled_driver_recurrence_percentile": None, "pooled_mutation_frequency": None,
                "n_covered_pooled": None, "n_mutated_pooled": None, "cohorts_contributing": [],
                "pooled_recurrence_context": f"no pooled SNV recurrence cohort for {indication}"}
    entry = pooled.get(target)
    if entry is None or entry["n_cov"] == 0:
        return {"pooled_driver_recurrence_class": "data_unavailable",
                "pooled_driver_recurrence_percentile": None, "pooled_mutation_frequency": None,
                "n_covered_pooled": 0, "n_mutated_pooled": 0, "cohorts_contributing": [],
                "pooled_recurrence_context": f"{target} covered by no pooled cohort in {indication}"}
    freq = entry["n_mut"] / entry["n_cov"]
    null_vec = tuple(e["n_mut"] / e["n_cov"] for e in pooled.values() if e["n_cov"] >= _MIN_COVERED)
    if entry["n_cov"] < _MIN_COVERED or not null_vec:
        pct, cls = None, "data_unavailable"
        note = f"{target} pooled coverage {entry['n_cov']} < {_MIN_COVERED} (too thin to rank)"
    else:
        from methods.percentile_null import percentile_rank, classify_percentile
        pct = percentile_rank(freq, null_vec)
        cls = classify_percentile(pct, cutoffs or DEFAULT_CUTOFFS)
        note = (f"pooled {'+'.join(entry['cohorts'])} — {target} ranks among {len(null_vec)} "
                f"panel-covered genes in {indication} (summed-counts/summed-coverage)")
    return {
        "pooled_mutation_frequency": freq,
        "n_covered_pooled": entry["n_cov"],
        "n_mutated_pooled": entry["n_mut"],
        "pooled_driver_recurrence_percentile": pct,
        "pooled_driver_recurrence_class": cls,
        "cohorts_contributing": entry["cohorts"],
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
    from methods.percentile_null import percentile_rank, classify_percentile
    null_vec = tuple(e["n_mut"] / e["n_cov"] for e in rankable.values())
    rows = []
    for gene, e in rankable.items():
        freq = e["n_mut"] / e["n_cov"]
        pct = percentile_rank(freq, null_vec)
        rows.append({"indication": indication, "gene_symbol": gene,
                     "n_covered_pooled": e["n_cov"], "n_mutated_pooled": e["n_mut"],
                     "pooled_mutation_frequency": freq,
                     "pooled_driver_recurrence_percentile": pct,
                     "pooled_driver_recurrence_class": classify_percentile(pct, DEFAULT_CUTOFFS),
                     "cohorts_contributing": ",".join(e["cohorts"])})
    rows.sort(key=lambda r: r["gene_symbol"])
    return pa.Table.from_pylist(rows, schema=_schema())


def _schema():
    import pyarrow as pa
    return pa.schema([
        pa.field("indication", pa.string()), pa.field("gene_symbol", pa.string()),
        pa.field("n_covered_pooled", pa.int64()), pa.field("n_mutated_pooled", pa.int64()),
        pa.field("pooled_mutation_frequency", pa.float64()),
        pa.field("pooled_driver_recurrence_percentile", pa.float64()),
        pa.field("pooled_driver_recurrence_class", pa.string()),
        pa.field("cohorts_contributing", pa.string()),
    ])
