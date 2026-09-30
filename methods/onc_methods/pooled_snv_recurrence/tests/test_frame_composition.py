"""The percentile's reference-set FRAME: how it is described in prose, and that the product path
describes it identically to the live path.

Two defects motivate these tests, both found while rebuilding the product as v2:

1. The context string hardcoded "ranks among N panel-covered genes" at both the live and the product
   site, while the pool has always included whole-exome TCGA-MC3 — so the phrase was already false
   for COADREAD's 18495 genes, not merely after the rebuild. A top-1% rank among panel genes is a
   much weaker claim than among exome-wide genes (panels are pre-enriched for recurrently-mutated
   drivers), which is precisely the comparability problem n_ranked_genes was added to expose; prose
   contradicting that field defeats the point.

2. The frame's composition is an INDICATION-level property, but a product row is pushed down one at a
   time and carries only its OWN gene's cohorts. Deriving the wording from cohorts_contributing would
   therefore mislabel every panel-only gene sitting in an exome-wide frame — hence the separate
   ranked_frame_cohorts column, and hence test_panel_only_gene_in_exome_frame below, which is the
   case that distinguishes the two implementations.

No S3: the per-cohort readers are monkeypatched, and the product read is served from an in-memory
pyarrow table by stubbing pyarrow.parquet.read_table.
"""

from __future__ import annotations

import pyarrow.fs
import pyarrow.parquet

import onc_methods.pooled_snv_recurrence.read as pr

# Captured BEFORE any test stubs it out: _install replaces _pooled_from_product with a lambda to force
# the live path, so the product-path tests need a handle on the real one to put back.
_REAL_FROM_PRODUCT = pr._pooled_from_product


# ── the noun phrase itself ────────────────────────────────────────────────────────────────────────
def test_panel_only_frame_says_panel_covered():
    assert pr._frame_noun_phrase(["GENIE", "MSK-CHORD"]) == "panel-covered genes"


def test_frame_with_whole_exome_arm_is_not_called_panel_covered():
    phrase = pr._frame_noun_phrase(["GENIE", "MSK-CHORD", "TCGA-MC3"])
    assert "panel-covered genes" != phrase
    assert "exome-wide" in phrase and "not panel-preselected" in phrase


def test_unknown_cohort_falls_through_to_neither_claim():
    # An arm whose assay breadth we cannot classify must not inherit either label: "exome-wide" would
    # overstate the evidence, "panel-covered" would understate it. The fall-through claims neither.
    phrase = pr._frame_noun_phrase(["GENIE", "SOME-NEW-COHORT-2027"])
    assert phrase == "pooled-covered genes"
    assert "panel-covered" not in phrase and "exome-wide" not in phrase


def test_empty_frame_claims_no_breadth():
    assert pr._frame_noun_phrase([]) == "pooled-covered genes"
    assert pr._frame_noun_phrase(None) == "pooled-covered genes"


def test_ranked_frame_cohorts_unions_over_the_whole_frame():
    entries = [{"cohorts": ["GENIE"]}, {"cohorts": ["MSK-CHORD", "TCGA-MC3"]}, {"cohorts": ["GENIE"]}]
    assert pr.ranked_frame_cohorts(entries) == ["GENIE", "MSK-CHORD", "TCGA-MC3"]


# ── fixtures: a frame built by all three arms, reporting a gene only the panels cover ─────────────
def _install(monkeypatch, mc3=None, genie=None, msk=None):
    monkeypatch.setattr(pr, "_pooled_from_product", lambda *a, **k: None)  # force the LIVE path
    monkeypatch.setattr(pr, "_mc3_gene_counts", lambda ind: mc3 or {})
    monkeypatch.setattr(pr, "_genie_gene_counts", lambda ind: genie or {})
    monkeypatch.setattr(pr, "_msk_gene_counts", lambda ind: msk or {})
    pr._pooled_for_indication.cache_clear()


# TCGA-MC3 supplies the exome-wide background; PANELONLY is covered by the two panels ALONE, so its
# cohorts_contributing excludes MC3 while the frame it is ranked against includes it.
_MC3 = {f"G{i}": (1, 500) for i in range(150)}
_GENIE = {"PANELONLY": (30, 100), "KRAS": (300, 700)}
_MSK = {"PANELONLY": (20, 100), "KRAS": (120, 300)}


def test_panel_only_gene_in_exome_frame_is_described_by_the_frame(monkeypatch):
    _install(monkeypatch, mc3=_MC3, genie=_GENIE, msk=_MSK)
    r = pr.pooled_recurrence_for_gene("PANELONLY", "COADREAD")
    assert r["cohorts_contributing"] == ["GENIE", "MSK-CHORD"]  # the GENE is panel-only ...
    # ... but the frame is exome-wide, and the frame is what the percentile is measured against.
    assert "exome-wide" in r["pooled_recurrence_context"]
    assert "panel-covered genes" not in r["pooled_recurrence_context"]


def test_panel_only_pool_still_says_panel_covered(monkeypatch):
    # The v1 BRCA/PRAD situation: MSK-CHORD alone. The phrase is correct here and must not regress to
    # the exome wording just because the fix went in.
    msk = {"KRAS": (250, 500)}
    msk.update({f"G{i}": (1, 500) for i in range(150)})
    _install(monkeypatch, msk=msk)
    r = pr.pooled_recurrence_for_gene("KRAS", "BRCA")
    assert r["cohorts_contributing"] == ["MSK-CHORD"]
    assert "ranks among" in r["pooled_recurrence_context"]
    assert "panel-covered genes" in r["pooled_recurrence_context"]
    assert "exome-wide" not in r["pooled_recurrence_context"]


# ── the product path must reproduce the live path exactly ─────────────────────────────────────────
def _serve_product_from(monkeypatch, table):
    """Make _pooled_from_product read `table` instead of S3.

    _pooled_from_product imports pyarrow.parquet INSIDE the function, but resolves `.read_table` on
    the shared module object at call time — so patching the module attribute reaches it. S3FileSystem
    is stubbed too: constructing a real one would attempt region resolution.
    """
    monkeypatch.setattr(pr, "_pooled_from_product", _REAL_FROM_PRODUCT)  # undo _install's stub
    monkeypatch.setattr(pr, "s3_uri_for", lambda _id: "s3://bucket/key/recurrence.parquet")
    monkeypatch.setattr(pyarrow.fs, "S3FileSystem", lambda *a, **k: None)

    def fake_read_table(path, filesystem=None, filters=None, **kw):
        want = dict((col, val) for col, op, val in (filters or []) if op == "=")
        keep = [
            i
            for i in range(table.num_rows)
            if all(table.column(c)[i].as_py() == v for c, v in want.items() if c in table.column_names)
        ]
        return table.take(keep)

    monkeypatch.setattr(pyarrow.parquet, "read_table", fake_read_table)


def test_product_row_carries_the_frame_not_the_gene(monkeypatch):
    _install(monkeypatch, mc3=_MC3, genie=_GENIE, msk=_MSK)
    table = pr.build_pooled_recurrence_table("COADREAD")
    rows = {r["gene_symbol"]: r for r in table.to_pylist()}
    # Every row records the SAME frame -- it is a property of the indication ...
    assert {r["ranked_frame_cohorts"] for r in rows.values()} == {"GENIE,MSK-CHORD,TCGA-MC3"}
    # ... while cohorts_contributing still varies per gene.
    assert rows["PANELONLY"]["cohorts_contributing"] == "GENIE,MSK-CHORD"
    assert rows["G0"]["cohorts_contributing"] == "TCGA-MC3"
    assert rows["PANELONLY"]["n_ranked_genes"] == table.num_rows


def test_pre_v2_vintage_without_the_column_does_not_crash(monkeypatch):
    """A v1 parquet has no ranked_frame_cohorts. Its frame breadth is then genuinely unknown, so the
    reader must fall through to the breadth-neutral phrase rather than guess or raise."""
    _install(monkeypatch, mc3=_MC3, genie=_GENIE, msk=_MSK)
    table = pr.build_pooled_recurrence_table("COADREAD")
    v1 = table.drop_columns(["ranked_frame_cohorts"])
    _serve_product_from(monkeypatch, v1)

    out = pr._pooled_from_product("PANELONLY", "COADREAD", None)
    assert out is not None, "a v1-shaped row must still be readable"
    assert "pooled-covered genes" in out["pooled_recurrence_context"]
    assert "panel-covered genes" not in out["pooled_recurrence_context"]
    assert "exome-wide" not in out["pooled_recurrence_context"]
    assert out["n_ranked_genes"] == table.num_rows  # the rest of the row is unaffected


def test_product_path_matches_live_on_every_field(monkeypatch):
    _install(monkeypatch, mc3=_MC3, genie=_GENIE, msk=_MSK)
    live = {g: pr.pooled_recurrence_for_gene(g, "COADREAD") for g in ("PANELONLY", "KRAS", "G0")}
    table = pr.build_pooled_recurrence_table("COADREAD")
    _serve_product_from(monkeypatch, table)
    for gene, expect in live.items():
        got = pr._pooled_from_product(gene, "COADREAD", None)
        assert got is not None, f"{gene} should be a rankable product row"
        assert got["pooled_recurrence_context"] == expect["pooled_recurrence_context"], gene
        for k in ("n_ranked_genes", "n_covered_pooled", "n_mutated_pooled", "cohorts_contributing"):
            assert got[k] == expect[k], f"{gene}.{k}"


# ── producer/reader vintage agreement ────────────────────────────────────────────────────────────
def test_upload_key_is_derived_from_the_reader_product_id():
    """Two independent literals is how a v2 build gets published under the v1 prefix."""
    from onc_methods.pooled_snv_recurrence import cli

    assert pr._POOLED_PRODUCT_ID == "pooled-snv-recurrence-v2"
    assert cli.S3_KEY == f"data-catalog/derived/{pr._POOLED_PRODUCT_ID}/recurrence.parquet"
