"""SUBSTRATE / METHOD provenance on the tumour-vs-normal selectivity readers (2026-09-15).

`selectivity_evidence_independence` (FIX 4, test_comparator_independence.py) answers "how many
comparator FAMILIES ran". It cannot answer "is the one substrate internally COMPARABLE", and the two
are orthogonal. The gap this file guards, measured over the shipped manifests:

  * ACC / LGG / OV / TGCT / UCS and SCLC all return `population_normal_only` — no adjacent normals
    exist for any of them, so cell C is the only arm.
  * But the first five are DESeq2 NB GLM + apeglm on RAW INTEGER COUNTS drawn from the SINGLE
    recount3-tcga-gtex-2023-01-04 release, where tumour and normal were uniformly reprocessed by one
    Monorail pipeline on one gene model (G026).
  * SCLC is a Welch t-test on log2(TPM+1) across TWO parents on DIFFERENT genome builds and gene
    models — George-2015 hg19 FPKM via cBioPortal for the tumours, GTEx hg38/recount3 GENCODE-v26 for
    the normals — because the George raw reads are EGA-controlled (EGAS00001000925) and were never
    mirrored to SRA, so no uniform reprocessor can reach them.

Same independence label, materially different rigor, and NOTHING downstream could tell them apart.
`selectivity_substrate_basis` + `selectivity_substrate_caveat` are that missing axis.

What this file pins:
  1. the field actually VARIES over the real shipped corpus — a provenance field that returns one
     constant is indistinguishable from a hard-coded string and audits nothing
     (feedback_provenance_field_that_never_varies);
  2. the basis SEPARATES SCLC from OV, the pair `selectivity_evidence_independence` collapses;
  3. the `-by-subgroup-v1` REGRESSION — see test_by_subgroup_products_are_within_pipeline_not_cross_cohort,
     the defect that shipped in the first cut of this change and what it would take to bring it back;
  4. vocabulary closed AND every rung reachable, the guard whose absence let a dead `"ns"` literal
     survive in surfaceome_cohort_ranking;
  5. caveat present EXACTLY when the basis is cross-cohort, with the manifest's OWN measured numbers
     in it rather than a hard-coded magnitude;
  6. fail-soft: an unresolvable manifest degrades to the conservative label and never breaks the data
     read it annotates.

These are display-only fields — no verdict, gate or atlas column reads them (SALIENCE_SPECS mints
`{short}::num::{field}` only for axes carrying a `reference_frame`, and these are categorical), so
this file is the only thing standing between them and silent rot.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.dge_deseq2 import read as dge  # noqa: E402

# The documented vocabulary of `selectivity_substrate_basis`. ONE place, so a value added to the
# reader without being added here fails test_substrate_basis_vocabulary_is_closed.
SUBSTRATE_VOCAB = {
    "within_pipeline_deseq2_counts",
    "cross_cohort_non_deseq2",
    "unknown_substrate",
}

CATALOG = Path("/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")
SENSITIVITY_GLOB = "manifests/derived/*dge-tumor-vs-normal-sensitivity*.yaml"

# MEASURED 2026-09-15 by sweeping every manifest matched by SENSITIVITY_GLOB.
N_SENSITIVITY_MANIFESTS = 32
CROSS_COHORT_MANIFESTS = {"sclc-dge-tumor-vs-normal-sensitivity-v1"}
BY_SUBGROUP_MANIFESTS = {
    "coadread-dge-tumor-vs-normal-sensitivity-by-subgroup-v1",
    "nsclc-dge-tumor-vs-normal-sensitivity-by-subgroup-v1",
    "stad-dge-tumor-vs-normal-sensitivity-by-subgroup-v1",
}

requires_catalog = pytest.mark.skipif(
    not (CATALOG / "manifests" / "derived").is_dir(),
    reason=f"data-catalog checkout not present at {CATALOG}",
)


def _manifest_ids():
    return sorted(p.stem for p in CATALOG.glob(SENSITIVITY_GLOB))


@pytest.fixture
def stub_manifest(monkeypatch):
    """Feed `_substrate_provenance` a synthetic manifest doc.

    Two traps this fixture exists to close:
      * `_substrate_provenance` is @lru_cache'd, so a stubbed call on a manifest_id some EARLIER test
        already resolved for real would return the cached real answer and the stub would be silently
        inert. Clear on the way in AND on the way out, so neither direction leaks.
      * `load_manifest` is imported INSIDE the function body, so the name resolves against
        `methods.catalog_query.read` at call time — patching `methods.dge_deseq2.read` would not
        intercept it (the resolving-namespace rule).
    """
    import methods.catalog_query.read as cq

    dge._substrate_provenance.cache_clear()
    counter = itertools.count()

    def _install(doc):
        def _fake_load_manifest(manifest_id, *a, **kw):
            if isinstance(doc, Exception):
                raise doc
            return doc

        monkeypatch.setattr(cq, "load_manifest", _fake_load_manifest)
        # MONOTONIC key, never id(doc): CPython reuses id() once an object is freed, so a loop that
        # builds a doc, passes it, and drops it can hand two DIFFERENT docs the same cache key and
        # get the first one's answer back from the lru_cache — the stub silently inert, the test
        # green for the wrong reason.
        return dge._substrate_provenance(f"stub-{next(counter)}")

    yield _install
    dge._substrate_provenance.cache_clear()


def _doc(test="DESeq2 NB GLM + Wald test", cross=False, parents=("recount3-tcga-gtex-2023-01-04",), offset=None):
    params = {"statistical_test": test}
    if cross:
        params["cross_cohort_batch_confound"] = True
    if offset is not None:
        params["measured_global_offset"] = offset
    return {"derived_from": list(parents), "parameters": params}


# ── 1. the field VARIES over the real corpus ─────────────────────────────────


@requires_catalog
def test_substrate_basis_is_not_a_constant_over_the_shipped_corpus():
    """A provenance field with one value is a hard-coded string wearing a function's clothes.

    MEASURED 2026-09-15: 32 sensitivity manifests → 31 within-pipeline, 1 cross-cohort. The counts
    are allowed to drift as products land; what may NOT drift is that both classes are populated.
    """
    ids = _manifest_ids()
    assert len(ids) >= 2, f"corpus too small to prove variation: {ids}"
    bases = {m: dge._substrate_provenance(m)[0] for m in ids}
    assert len(set(bases.values())) >= 2, f"basis never varies — all {len(ids)} products read {set(bases.values())}"
    assert set(bases.values()) <= SUBSTRATE_VOCAB, f"off-vocabulary: {set(bases.values()) - SUBSTRATE_VOCAB}"
    # No product may land in UNKNOWN unnoticed: that is the "I cannot verify this" label, and a
    # shipped product sitting in it means the manifest lost a field this reader depends on.
    unknown = [m for m, b in bases.items() if b == "unknown_substrate"]
    assert unknown == [], f"shipped products fell into unknown_substrate (manifest shape changed?): {unknown}"


@requires_catalog
def test_sclc_is_the_cross_cohort_product_and_carries_the_caveat():
    basis, caveat = dge._substrate_provenance("sclc-dge-tumor-vs-normal-sensitivity-v1")
    assert basis == "cross_cohort_non_deseq2"
    assert caveat and "Welch" in caveat, caveat
    # Both parents NAMED, so a reader never has to open the manifest to see what was joined.
    assert "sclc-george-tpm-long-v1" in caveat and "gtex-tpm-recount3-long-v1" in caveat
    # And the rank is offered as the usable alternative to the untrustworthy magnitude.
    assert "selectivity_allgene_percentile_cell_c" in caveat


@requires_catalog
def test_every_other_shipped_product_is_within_pipeline_with_no_caveat():
    for m in _manifest_ids():
        basis, caveat = dge._substrate_provenance(m)
        if m in CROSS_COHORT_MANIFESTS:
            continue
        assert basis == "within_pipeline_deseq2_counts", f"{m} → {basis}"
        assert caveat is None, f"{m} carries a caveat it should not: {caveat}"


# ── 2. the pair that independence CANNOT separate ────────────────────────────


@requires_catalog
def test_basis_separates_sclc_from_ov_where_independence_cannot():
    """THE payoff test. OV and SCLC both ship cell C only, so both read `population_normal_only`,
    and both can mint `modest_tumor_selective`. Only the substrate basis tells them apart.

    If this ever passes trivially — because the two bases became equal — the whole change has been
    reduced to decoration.
    """
    c_only = dict(
        cells_ran=3,
        cells_supporting=1,
        dominant_direction="up",
        discordant=False,
        sig_all_cells=False,
        log2fc_cell_a=None,
        q_value_cell_a=None,
        log2fc_cell_b=None,
        q_value_cell_b=None,
        log2fc_cell_c=2.0,
        q_value_cell_c=1e-9,
        max_abs_log2fc=2.0,
    )
    # The axis that collapses them: identical label from identical row shape.
    assert dge._selectivity_evidence_independence(c_only) == "population_normal_only"

    sclc = dge._substrate_provenance("sclc-dge-tumor-vs-normal-sensitivity-v1")[0]
    ov = dge._substrate_provenance("ov-dge-tumor-vs-normal-sensitivity-v1")[0]
    assert sclc != ov, "substrate basis no longer separates SCLC from OV — the change is now inert"
    assert (sclc, ov) == ("cross_cohort_non_deseq2", "within_pipeline_deseq2_counts")


# ── 3. the -by-subgroup regression ───────────────────────────────────────────


@requires_catalog
def test_by_subgroup_products_are_within_pipeline_not_cross_cohort():
    """REGRESSION GUARD for a defect that shipped in the first cut of this change.

    That cut required `len(derived_from) == 1` for the within-pipeline label and let every unmatched
    shape FALL THROUGH to cross-cohort. The three `-by-subgroup-v1` products list a subgroup-label
    sidecar (`tcga-subgroup-assignments-*`) alongside their expression parent, so they have 2-3
    parents while being ordinary DESeq2 NB GLM runs on the SINGLE recount3-tcga-gtex-2023-01-04
    substrate. They were labelled `cross_cohort_non_deseq2` and handed a caveat asserting "the
    contrast is DESeq2 NB GLM + Wald test, not DESeq2 on raw counts" — self-contradictory — plus a
    false claim that tumour and normal came from different pipelines. 3 of the 4 products the label
    fired on were wrong.

    `derived_from` is a HETEROGENEOUS list: expression parents mixed with annotation sidecars, with
    no manifest key separating them (`type:` is only source-release/derived). Its arity therefore
    cannot stand in for the number of expression substrates, and it must never decide the basis.
    """
    for m in sorted(BY_SUBGROUP_MANIFESTS):
        basis, caveat = dge._substrate_provenance(m)
        assert basis == "within_pipeline_deseq2_counts", f"{m} → {basis} (the derived_from proxy is back)"
        assert caveat is None, f"{m} handed a caveat contradicting its own DESeq2 kernel: {caveat}"


def test_multi_parent_alone_never_triggers_the_cross_cohort_label(stub_manifest):
    """The same defect at the unit level, independent of what the catalog currently holds: many
    parents + a DESeq2 kernel + no declared confound is WITHIN-pipeline, however many parents."""
    for n in (1, 2, 3, 7):
        basis, caveat = stub_manifest(_doc(parents=tuple(f"parent-{i}" for i in range(n))))
        assert (basis, caveat) == ("within_pipeline_deseq2_counts", None), f"{n} parents → {basis}"


# ── 4. vocabulary: closed, and every rung reachable ──────────────────────────


def test_substrate_basis_vocabulary_is_closed(stub_manifest):
    """No manifest shape may produce a value outside the documented vocabulary."""
    kernels = [
        "DESeq2 NB GLM + Wald test",
        "deseq2 nb glm",  # case-insensitive prefix match
        "Welch's t-test (scipy.stats.ttest_ind, equal_var=False) on log2(TPM+1)",
        "",
        None,
    ]
    emitted = set()
    for kernel, cross, nparents in itertools.product(kernels, (False, True), (0, 1, 2)):
        basis, _ = stub_manifest(_doc(test=kernel, cross=cross, parents=tuple(f"p{i}" for i in range(nparents))))
        emitted.add(basis)
    for degenerate in ({}, {"parameters": {}}, {"parameters": None}, {"derived_from": None}, None):
        emitted.add(stub_manifest(degenerate)[0])
    assert emitted <= SUBSTRATE_VOCAB, f"off-vocabulary value emitted: {emitted - SUBSTRATE_VOCAB}"


def test_every_substrate_basis_value_is_reachable(stub_manifest):
    """The other direction: a rung nothing can reach is a rung that does not exist."""
    reached = {
        # 31 of 32 shipped products, incl. the by-subgroup family
        "within_pipeline_deseq2_counts": _doc(),
        # SCLC: confound DECLARED and the kernel is not DESeq2
        "cross_cohort_non_deseq2": _doc(test="Welch's t-test on log2(TPM+1)", cross=True),
        # no kernel recorded at all — cannot be called clean, is not evidence of a join either
        "unknown_substrate": _doc(test=None),
    }
    assert set(reached) == SUBSTRATE_VOCAB, "vocabulary and coverage table have diverged"
    for expected, doc in reached.items():
        assert stub_manifest(doc)[0] == expected


def test_unknown_does_not_silently_inherit_the_reassuring_label(stub_manifest):
    """Both half-shapes must land in UNKNOWN, from OPPOSITE directions.

    A non-DESeq2 kernel with no declared confound is not clean; a DESeq2 kernel that DOES declare a
    confound satisfies only ONE of the two conjuncts `cross_cohort_non_deseq2` asserts, so naming it
    that would be a false statement in a consumer-facing field.
    """
    non_deseq2_undeclared = stub_manifest(_doc(test="Welch's t-test on log2(TPM+1)", cross=False))
    assert non_deseq2_undeclared == ("unknown_substrate", None)

    deseq2_but_confounded = stub_manifest(_doc(test="DESeq2 NB GLM + Wald test", cross=True))
    assert deseq2_but_confounded == ("unknown_substrate", None)


# ── 5. the caveat: present exactly when earned, measured not hard-coded ──────


@requires_catalog
def test_caveat_is_present_exactly_when_the_basis_is_cross_cohort():
    """A biconditional, over the real corpus: no silent caveat on a clean product, and no
    cross-cohort product without one."""
    for m in _manifest_ids():
        basis, caveat = dge._substrate_provenance(m)
        assert (caveat is not None) == (basis == "cross_cohort_non_deseq2"), f"{m}: {basis} / {caveat!r}"


@requires_catalog
def test_caveat_quotes_the_manifests_OWN_measured_offset():
    """The confound SIZE comes from parameters.measured_global_offset, so the sentence can neither
    overstate nor understate what the producer actually quantified.

    SCLC manifest (2026-08-08): median_log2fc_c 0.27, frac_genes_up 0.636.
    """
    caveat = dge._substrate_provenance("sclc-dge-tumor-vs-normal-sensitivity-v1")[1]
    assert "+0.27" in caveat, caveat
    assert "63.6% of genes read up" in caveat, caveat


def test_caveat_tracks_the_numbers_rather_than_hard_coding_them(stub_manifest):
    """Different manifest numbers → different sentence. This is what makes the previous test a
    measurement rather than a coincidence: a hard-coded "+0.27" would pass that one and fail here."""
    doc = _doc(
        test="Welch's t-test on log2(TPM+1)", cross=True, offset={"median_log2fc_c": -1.5, "frac_genes_up": 0.21}
    )
    caveat = stub_manifest(doc)[1]
    assert "-1.50" in caveat and "21.0% of genes read up" in caveat, caveat
    assert "+0.27" not in caveat


def test_caveat_says_so_when_the_offset_was_never_quantified(stub_manifest):
    """A cross-cohort product with no measured_global_offset must still be flagged — silence about
    the size is not silence about the confound."""
    caveat = stub_manifest(_doc(test="Welch's t-test", cross=True, offset=None))[1]
    assert caveat is not None
    assert "offset not quantified in manifest" in caveat, caveat


# ── 6. fail-soft ─────────────────────────────────────────────────────────────


def test_unresolvable_manifest_degrades_instead_of_breaking_the_read():
    """`load_manifest` RAISES FileNotFoundError on an unknown id (it is uncached and does no
    swallowing), so this path is genuinely reachable, not a vacuous guard. Provenance annotation may
    never take down the data read it describes."""
    assert dge._substrate_provenance("no-such-manifest-anywhere-xyz") == ("unknown_substrate", None)


def test_a_raising_loader_is_caught(stub_manifest):
    assert stub_manifest(RuntimeError("catalog offline")) == ("unknown_substrate", None)


# ── 7. the emitted fields ────────────────────────────────────────────────────


def test_substrate_fields_shape_and_absent_manifest_id():
    """A reader with no manifest_id (the v2 two-product fallback) must emit the keys anyway — an
    ABSENT key reads downstream as "not applicable", which is a different claim from "unverified"."""
    f = dge._substrate_fields(None)
    assert f == {"selectivity_substrate_basis": "unknown_substrate", "selectivity_substrate_caveat": None}
    assert dge._substrate_fields("") == f


@requires_catalog
def test_substrate_fields_agree_with_substrate_provenance():
    for m in ("sclc-dge-tumor-vs-normal-sensitivity-v1", "ov-dge-tumor-vs-normal-sensitivity-v1"):
        basis, caveat = dge._substrate_provenance(m)
        f = dge._substrate_fields(m)
        assert f["selectivity_substrate_basis"] == basis
        assert f["selectivity_substrate_caveat"] == caveat
        assert f["selectivity_substrate_basis"] in SUBSTRATE_VOCAB
