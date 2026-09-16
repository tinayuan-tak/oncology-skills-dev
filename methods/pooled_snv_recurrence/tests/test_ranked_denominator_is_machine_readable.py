"""The pooled percentile's reference-set size must be a field, not a phrase in an English sentence.

Consumer report, 2026-09-16 (the second half of the same report that surfaced the PIK3CA zero): the
pooled cross-indication denominator is not comparable across indications, and nothing in the emitted
data says so. MEASURED in framework-run 2026-09-11-verdict-only-tables:

  PIK3CA / BRCA      pooled_driver_recurrence_class=top_1pct  percentile=99.680
                     context: "pooled MSK-CHORD — PIK3CA ranks among 469 panel-covered genes in BRCA"
  KRAS   / COADREAD  pooled_driver_recurrence_class=top_1pct  percentile=99.970
                     context: "pooled GENIE+MSK-CHORD+TCGA-MC3 — KRAS ranks among 18495 ..."

Both render as top_1pct, but the reference sets differ by 39x AND in kind: BRCA's 469 genes are a
targeted panel, COADREAD's 18495 include whole-exome TCGA-MC3. Panels are deliberately enriched for
recurrently-mutated drivers, so a top-1% rank among 469 panel genes clears a much higher bar than the
same rank among 18495 exome-wide genes — the reference set is pre-selected for the property being
ranked. A consumer comparing the two needs that count, and until this change the only way to get it
was to regex the prose.

The count was always computed (`n_ranked` from the product, `len(null_vec)` live). It simply never
left the function except inside a formatted string. These tests pin it as a field on every return
path, including the paths where no ranking happened and the honest value is None.
"""

from __future__ import annotations

import re

import methods.pooled_snv_recurrence.read as pr


def _install(monkeypatch, mc3=None, genie=None, msk=None):
    """Same offline harness as test_pooled_recurrence: force the LIVE path over in-memory cohorts."""
    monkeypatch.setattr(pr, "_pooled_from_product", lambda *a, **k: None)
    monkeypatch.setattr(pr, "_mc3_gene_counts", lambda ind: mc3 or {})
    monkeypatch.setattr(pr, "_genie_gene_counts", lambda ind: genie or {})
    monkeypatch.setattr(pr, "_msk_gene_counts", lambda ind: msk or {})
    pr._pooled_for_indication.cache_clear()


def test_a_ranked_gene_reports_the_size_of_the_set_it_was_ranked_against(monkeypatch):
    """The headline. 201 genes clear _MIN_COVERED here, so that is the reference set."""
    mc3 = {"KRAS": (250, 500)}
    mc3.update({f"G{i}": (1, 500) for i in range(200)})
    _install(monkeypatch, mc3=mc3)

    r = pr.pooled_recurrence_for_gene("KRAS", "COADREAD")

    assert r["pooled_driver_recurrence_percentile"] is not None, "fixture must actually rank (else vacuous)"
    assert r["n_ranked_genes"] == 201, (
        f"the percentile was ranked against 201 genes but the field reports {r['n_ranked_genes']!r}; "
        f"without it, two indications' percentiles cannot be compared"
    )


def test_the_field_agrees_with_the_number_in_the_prose_it_replaces(monkeypatch):
    """The field and the sentence must not be able to drift apart — they are the same quantity, and
    the prose is what consumers have been reading until now."""
    mc3 = {"KRAS": (250, 500)}
    mc3.update({f"G{i}": (1, 500) for i in range(120)})
    _install(monkeypatch, mc3=mc3)

    r = pr.pooled_recurrence_for_gene("KRAS", "COADREAD")

    in_prose = re.search(r"ranks among (\d+) panel-covered genes", r["pooled_recurrence_context"])
    assert in_prose, f"context string changed shape: {r['pooled_recurrence_context']!r}"
    assert int(in_prose.group(1)) == r["n_ranked_genes"]


def test_two_indications_with_different_reference_sets_are_now_distinguishable(monkeypatch):
    """The consumer's actual comparison, in miniature: two cohorts, both yielding a top rank for the
    target, with reference sets an order of magnitude apart. Before this change the two rows were
    indistinguishable on any field a machine reads."""
    # Both sets must be >= 100 genes or top_1pct is arithmetically unreachable (the max of an
    # N-gene null sits at the (1 - 1/N)th percentile), which would make the "same class" premise of
    # this test impossible to satisfy rather than merely false.
    small = {"PIK3CA": (200, 500)}
    small.update({f"P{i}": (1, 500) for i in range(99)})  # 100-gene panel-like reference set
    _install(monkeypatch, msk=small)
    brca = pr.pooled_recurrence_for_gene("PIK3CA", "BRCA")

    big = {"KRAS": (250, 500)}
    big.update({f"G{i}": (1, 500) for i in range(999)})  # 1000-gene exome-like reference set
    _install(monkeypatch, mc3=big)
    coadread = pr.pooled_recurrence_for_gene("KRAS", "COADREAD")

    assert brca["pooled_driver_recurrence_class"] == coadread["pooled_driver_recurrence_class"], (
        "fixture must reproduce the consumer's situation — the same CLASS from very different frames"
    )
    assert brca["n_ranked_genes"] == 100
    assert coadread["n_ranked_genes"] == 1000
    assert brca["n_ranked_genes"] != coadread["n_ranked_genes"], "the frames must now be tellable apart"


def test_no_cohort_for_the_indication_reports_none_not_zero(monkeypatch):
    """None means "no reference set was built". 0 would mean "a set was built and it was empty" —
    a different fact, and the sort of conflation this whole change is about."""
    _install(monkeypatch)
    r = pr.pooled_recurrence_for_gene("KRAS", "MPN")
    assert r["pooled_driver_recurrence_class"] == "data_unavailable"
    assert r["n_ranked_genes"] is None


def test_a_gene_covered_by_no_cohort_reports_none(monkeypatch):
    _install(monkeypatch, mc3={"KRAS": (10, 500)})
    r = pr.pooled_recurrence_for_gene("BRAF", "COADREAD")
    assert r["pooled_driver_recurrence_class"] == "data_unavailable"
    assert r["n_ranked_genes"] is None


def test_a_gene_too_thin_to_rank_still_reports_the_frame_size(monkeypatch):
    """Deliberate asymmetry with the two None cases above: here the null WAS built and the gene just
    could not be placed in it, so the frame size is a real, useful number even though the percentile
    is None."""
    mc3 = {"THIN": (1, 5)}  # below _MIN_COVERED
    mc3.update({f"G{i}": (1, 500) for i in range(50)})
    _install(monkeypatch, mc3=mc3)

    r = pr.pooled_recurrence_for_gene("THIN", "COADREAD")

    assert r["pooled_driver_recurrence_percentile"] is None, "fixture must be too thin to rank"
    assert r["n_ranked_genes"] == 50, "the reference set existed; report its size"


def test_every_return_path_carries_the_key(monkeypatch):
    """A whitelist-shaped consumer (see _pooled_recurrence_fields in gdc_somatic_hotspot) silently
    drops a key that is missing rather than raising, so an absent key is invisible. Pin presence on
    all four live paths at once."""
    cases = []
    _install(monkeypatch)
    cases.append(pr.pooled_recurrence_for_gene("KRAS", "MPN"))
    _install(monkeypatch, mc3={"KRAS": (10, 500)})
    cases.append(pr.pooled_recurrence_for_gene("BRAF", "COADREAD"))
    thin = {"THIN": (1, 5)}
    thin.update({f"G{i}": (1, 500) for i in range(50)})
    _install(monkeypatch, mc3=thin)
    cases.append(pr.pooled_recurrence_for_gene("THIN", "COADREAD"))
    ranked = {"KRAS": (250, 500)}
    ranked.update({f"G{i}": (1, 500) for i in range(120)})
    _install(monkeypatch, mc3=ranked)
    cases.append(pr.pooled_recurrence_for_gene("KRAS", "COADREAD"))

    for i, r in enumerate(cases):
        assert "n_ranked_genes" in r, f"return path {i} omits n_ranked_genes; a whitelisting reader would see nothing"


def test_the_hotspot_cards_field_whitelist_forwards_the_key(monkeypatch):
    """_pooled_recurrence_fields copies a fixed tuple of keys, so adding a field upstream is INERT
    until that tuple names it. That whitelist is exactly why the count stayed prose-only, so pin the
    forwarding rather than assuming it."""
    from methods.gdc_somatic_hotspot import read as hs

    monkeypatch.setattr(
        "methods.pooled_snv_recurrence.read.pooled_recurrence_for_gene",
        lambda t, i: {
            "pooled_driver_recurrence_class": "top_1pct",
            "pooled_driver_recurrence_percentile": 99.68,
            "pooled_mutation_frequency": 0.354,
            "n_covered_pooled": 6807,
            "n_mutated_pooled": 2412,
            "cohorts_contributing": ["MSK-CHORD"],
            "n_ranked_genes": 469,
            "pooled_recurrence_context": "pooled MSK-CHORD — PIK3CA ranks among 469 panel-covered genes in BRCA",
        },
    )

    out = hs._pooled_recurrence_fields("PIK3CA", "BRCA")

    assert out["n_ranked_genes"] == 469, "the card's whitelist drops the denominator before it reaches a consumer"


def test_the_graceful_failure_path_also_declares_the_key(monkeypatch):
    """Absence-discipline: the except branch must return the SAME key set as the success branch, or a
    consumer sees the key appear and vanish depending on whether a network read happened to work."""
    from methods.gdc_somatic_hotspot import read as hs

    def _boom(t, i):
        raise RuntimeError("pooled product unreachable")

    monkeypatch.setattr("methods.pooled_snv_recurrence.read.pooled_recurrence_for_gene", _boom)

    out = hs._pooled_recurrence_fields("PIK3CA", "BRCA")

    assert out["pooled_driver_recurrence_class"] == "data_unavailable"
    assert "n_ranked_genes" in out and out["n_ranked_genes"] is None
