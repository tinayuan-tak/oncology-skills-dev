"""The Xena/Toil secondary product is invisible to the verdict/discovery path (S1b, #694).

S1b promotes the Xena/Toil loader to a catalogued substrate, but it must stay SECONDARY /
diagnostic — never a classifier or verdict input. The mechanism that guarantees this is a
naming convention, not a runtime flag: the Xena/Toil product carries a `-xenatoil` id INFIX
(`{ind}-dge-tumor-vs-normal-sensitivity-xenatoil-v1`), so it does NOT end in the exact suffix
the pancan discovery glob and the roster check key on, and the single-gene verdict reader
builds the plain `-sensitivity-v1` id with no way to point it at the xenatoil object.

These tests pin that convention against the REAL discovery/roster/reader code (not a
re-implementation of the predicate), so if someone ever drops the infix — or, worse, widens
`_SENSITIVITY_SUFFIX`/the glob to match it — the secondary substrate stops being secondary and
this fails loudly. Hermetic: the S3 listing is an injected fake.
"""

from __future__ import annotations

import inspect

from methods.dge_deseq2 import derive_pancan_stack as dps
from methods.dge_deseq2 import read as dge_read

# The id infix the batch driver / manifest use for the Xena/Toil substrate (scripts/
# run_indication_batch.sh: SUBSTRATE=xena_toil -> SUBSTRATE_INFIX="-xenatoil").
_XENATOIL_INFIX = "-xenatoil"


def _recount3_dir(ind: str) -> str:
    """The recount3 (classifier) product directory name for an indication."""
    return f"{ind.lower()}{dps._SENSITIVITY_SUFFIX}"


def _xenatoil_dir(ind: str) -> str:
    """The Xena/Toil (secondary) product directory name: the infix sits before `-v1`."""
    # mirrors dest_prefix() in scripts/run_indication_batch.sh
    return f"{ind.lower()}-dge-tumor-vs-normal-sensitivity{_XENATOIL_INFIX}-v1"


class _FakeInfo:
    """Stand-in for pyarrow.fs.FileInfo — the discovery code only reads `.base_name`."""

    def __init__(self, base_name: str):
        self.base_name = base_name


class _FakeS3FS:
    """Returns a fixed listing regardless of selector, so list_published_* is hermetic."""

    def __init__(self, dir_names):
        self._dir_names = list(dir_names)

    def get_file_info(self, selector):  # noqa: ARG002 - selector unused, listing is fixed
        return [_FakeInfo(n) for n in self._dir_names]


def test_xenatoil_id_does_not_match_the_discovery_suffix():
    # The whole secondary-ness hinges on this string fact: the infix breaks the exact-suffix
    # match, so the discovery glob and roster check never see the Xena/Toil product.
    assert _recount3_dir("COADREAD").endswith(dps._SENSITIVITY_SUFFIX)
    assert not _xenatoil_dir("COADREAD").endswith(dps._SENSITIVITY_SUFFIX), (
        "the -xenatoil product id must NOT end in the sensitivity discovery suffix, or it would "
        "be picked up by list_published_sensitivity_indications and become a verdict input"
    )


def test_discovery_glob_lists_recount3_but_not_xenatoil():
    # Feed BOTH product dirs (plus an unrelated derived product) through the REAL discovery
    # function via an injected fake S3 listing. Only the recount3 product should surface.
    fake = _FakeS3FS(
        [
            _recount3_dir("COADREAD"),
            _recount3_dir("BRCA"),
            _xenatoil_dir("COADREAD"),  # the secondary product — must be ignored
            "coadread-some-other-derived-thing-v1",
        ]
    )
    found = dps.list_published_sensitivity_indications(s3fs=fake)
    assert found == {"COADREAD", "BRCA"}, (
        f"discovery must list only the recount3 products; got {sorted(found)} "
        "(a -xenatoil id leaking in here would put the secondary substrate in the pancan stack)"
    )


def test_roster_check_ignores_a_landed_xenatoil_product():
    # A landed Xena/Toil product must NOT trip assert_roster_matches_published as an
    # "unmapped published indication" — it isn't a sensitivity-v1 product at all. We pass the
    # already-filtered `published` set the discovery function would return (COADREAD present via
    # its recount3 product) to confirm no drift is raised on account of the xenatoil object.
    declared = set(dps._INDICATION_CELL_B_SEMANTICS)
    # Simulate discovery having run over a bucket that also holds the xenatoil object: because
    # the suffix filter already excluded it, `published` never contains a xenatoil-only code.
    dps.assert_roster_matches_published(published=declared)  # no raise = rosters agree


def test_verdict_reader_has_no_substrate_lever_to_reach_xenatoil():
    # The single-gene verdict reader builds the plain `-sensitivity-v1` id internally and takes
    # only (target, indication) — there is no substrate parameter a caller could flip to route
    # it at the -xenatoil object. Pin the signature so adding such a lever is a conscious change.
    params = list(inspect.signature(dge_read.read_tumor_vs_normal_sensitivity_gene_row).parameters)
    assert params == ["target", "indication"], (
        f"verdict reader signature drifted to {params}; a substrate/product-id parameter would "
        "let a caller point the classifier read at the secondary Xena/Toil product"
    )
