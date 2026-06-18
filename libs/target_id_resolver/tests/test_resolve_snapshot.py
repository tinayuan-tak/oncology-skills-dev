"""Snapshot-backend tests against resolver_v1.0.0.

Requires the local cache at $TARGET_ID_RESOLVER_CACHE_DIR (default
~/.cache/target-id-resolver/) to contain symlinks or copies of the four
pinned reference files. CI / dev setup populates the cache by syncing
the matching S3 prefixes; tests here assume the cache exists and skip
gracefully if it doesn't.

These tests parallel test_resolve_live.py — same target gene round-trips,
but exercising the snapshot dispatch path instead of MyGene.info live API.
The pair gives us an apples-to-apples regression matrix between alpha
and v1.0.0.
"""

import os
from pathlib import Path

import pytest

from target_id_resolver import resolve
from target_id_resolver.errors import NotFoundError, ResolverPinError


pytestmark = pytest.mark.snapshot

V1_RELEASE = "resolver_v1.0.0"

# Skip the entire module if the local cache isn't populated. Avoids requiring
# every CI runner to mirror reference data; populate cache out-of-band.
_CACHE = Path(os.environ.get("TARGET_ID_RESOLVER_CACHE_DIR",
                              str(Path.home() / ".cache" / "target-id-resolver")))
_REQUIRED_FILES = [
    _CACHE / "hgnc-2026-q2" / "hgnc_complete_set_2026-04-01.txt",
    _CACHE / "ensembl-id-mapping-release-116-snapshot-2026-06-18" / "hsapiens_gene_id_map_release-116.tsv",
    _CACHE / "uniprot-sprot-human-2026-02-snapshot-2026-06-18" / "uniprot_sprot_human.xml.gz",
]
if not all(p.is_file() for p in _REQUIRED_FILES):
    pytest.skip(
        f"Snapshot cache missing required files under {_CACHE}. "
        f"Populate by syncing s3://onc-compbio/data-catalog/sources/... "
        f"to {_CACHE}/{{manifest_id}}/.",
        allow_module_level=True,
    )


def test_resolve_kras_canonical():
    t = resolve("KRAS", resolver_release=V1_RELEASE)
    assert t.hgnc.id == "HGNC:6407"
    assert t.hgnc.primary_symbol == "KRAS"
    assert t.ensembl.gene_id == "ENSG00000133703"
    # v1.0.0 has REAL Ensembl version, not the .0 alpha sentinel.
    assert t.ensembl.version != "0"
    assert t.ensembl.full == f"{t.ensembl.gene_id}.{t.ensembl.version}"
    assert t.uniprot is not None
    assert t.uniprot.canonical_accession == "P01116"
    assert t.uniprot.reviewed is True
    assert t.ncbi is not None
    assert t.ncbi.entrez_id == 3845
    assert t.deprecation_warning is None


def test_resolve_tp53_canonical():
    t = resolve("TP53", resolver_release=V1_RELEASE)
    assert t.hgnc.id == "HGNC:11998"
    assert t.hgnc.primary_symbol == "TP53"
    assert t.ensembl.gene_id == "ENSG00000141510"
    assert t.ensembl.version != "0"  # real Ensembl version
    assert t.uniprot is not None
    assert t.uniprot.canonical_accession == "P04637"


def test_resolve_baf250a_deprecated_alias():
    t = resolve("BAF250A", resolver_release=V1_RELEASE)
    assert t.hgnc.id == "HGNC:11110"
    assert t.hgnc.primary_symbol == "ARID1A"
    assert t.deprecation_warning is not None
    assert t.deprecation_warning.input_alias == "BAF250A"
    assert t.deprecation_warning.resolved_to_primary == "ARID1A"
    # Case-insensitive alias matching: input is uppercase BAF250A,
    # HGNC stores BAF250a (lowercase suffix). The case-fold index
    # in _index.py makes this work.
    assert t.uniprot is not None
    assert t.uniprot.canonical_accession == "O14497"


def test_resolve_marc1_repurposed_alias():
    t = resolve("MARC1", resolver_release=V1_RELEASE)
    assert t.hgnc.primary_symbol == "MTARC1"
    assert t.deprecation_warning is not None


def test_resolve_by_hgnc_id():
    t = resolve("HGNC:11998", resolver_release=V1_RELEASE)
    assert t.hgnc.primary_symbol == "TP53"
    assert t.input.interpreted_as == "hgnc_id"


def test_resolve_by_ensembl_unversioned():
    t = resolve("ENSG00000141510", resolver_release=V1_RELEASE)
    assert t.hgnc.primary_symbol == "TP53"
    assert t.input.interpreted_as == "ensembl_gene_id"


def test_resolve_by_ensembl_versioned():
    t = resolve("ENSG00000141510.18", resolver_release=V1_RELEASE)
    assert t.hgnc.primary_symbol == "TP53"
    # Returned version is whatever the mirror says, not the input version.
    assert t.input.value == "ENSG00000141510.18"


def test_resolve_by_uniprot():
    t = resolve("P04637", resolver_release=V1_RELEASE)
    assert t.hgnc.primary_symbol == "TP53"


def test_resolve_by_entrez():
    t = resolve("7157", resolver_release=V1_RELEASE)
    assert t.hgnc.primary_symbol == "TP53"


def test_resolve_not_found():
    with pytest.raises(NotFoundError):
        resolve("NOT_A_REAL_GENE_SYMBOL_XYZ123", resolver_release=V1_RELEASE)


def test_release_pin_recorded_with_all_data_pins():
    """v1.0.0 Targets cite ALL five data_pins (alpha cited only hgnc + mygene)."""
    t = resolve("KRAS", resolver_release=V1_RELEASE)
    assert t.release_pins.resolver_release == V1_RELEASE
    assert t.release_pins.hgnc == "hgnc-2026-q2"
    assert t.release_pins.ensembl == "ensembl-id-mapping-release-116-snapshot-2026-06-18"
    assert t.release_pins.uniprot == "uniprot-sprot-human-2026-02-snapshot-2026-06-18"
    assert t.release_pins.ncbi_gene == "ncbi-gene-snapshot-2026-06-18"


def test_target_fingerprint_deterministic():
    """Same input + same release -> identical fingerprint (modulo resolved_at)."""
    t1 = resolve("KRAS", resolver_release=V1_RELEASE)
    t2 = resolve("KRAS", resolver_release=V1_RELEASE)
    assert t1.fingerprint() == t2.fingerprint()


def test_v1_real_ensembl_version_replaces_alpha_sentinel():
    """The whole point of the v1.0.0 promotion: real Ensembl versions
    (.16, .21, etc.) instead of the alpha .0 sentinel."""
    t = resolve("KRAS", resolver_release=V1_RELEASE)
    assert t.ensembl.version not in ("0", "")
    assert t.ensembl.version.isdigit()
