"""Live-API tests against MyGene.info /v3/query.

These tests hit the public MyGene.info endpoint and require network access.
Run with `pytest -m live`. They are the round-trip proof that the resolver
contract works end-to-end against real data.
"""

import pytest

from target_id_resolver import resolve
from target_id_resolver.errors import NotFoundError

pytestmark = pytest.mark.live


def test_resolve_kras_canonical():
    """KRAS — canonical primary symbol with known cross-references."""
    t = resolve("KRAS")
    assert t.hgnc.id == "HGNC:6407"
    assert t.hgnc.primary_symbol == "KRAS"
    assert t.ensembl.gene_id == "ENSG00000133703"
    assert t.uniprot is not None
    assert t.uniprot.canonical_accession == "P01116"
    assert t.ncbi is not None
    assert t.ncbi.entrez_id == 3845
    assert t.deprecation_warning is None
    # Aliases include known historical names like 'C-K-RAS'.
    assert any("K-RAS" in a or a == "KRAS2" for a in t.aliases_at_resolution)
    # Input descriptor preserves the original input.
    assert t.input is not None
    assert t.input.value == "KRAS"
    assert t.input.interpreted_as == "hgnc_symbol"


def test_resolve_tp53_canonical():
    """TP53 — most frequently cited cancer gene; sanity check."""
    t = resolve("TP53")
    assert t.hgnc.id == "HGNC:11998"
    assert t.hgnc.primary_symbol == "TP53"
    assert t.ensembl.gene_id == "ENSG00000141510"
    assert t.uniprot is not None
    assert t.uniprot.canonical_accession == "P04637"
    assert t.deprecation_warning is None


def test_resolve_baf250a_deprecated_alias():
    """BAF250A is a previous symbol for ARID1A. Resolver MUST forward-map and
    populate deprecation_warning, never raise."""
    t = resolve("BAF250A")
    assert t.hgnc.id == "HGNC:11110"
    assert t.hgnc.primary_symbol == "ARID1A"
    assert t.deprecation_warning is not None
    assert t.deprecation_warning.input_alias == "BAF250A"
    assert t.deprecation_warning.resolved_to_primary == "ARID1A"


def test_resolve_marc1_repurposed_alias():
    """MARC1 was re-mapped to MTARC1. Treat as deprecation, not ambiguity,
    because HGNC explicitly forward-maps it."""
    t = resolve("MARC1")
    assert t.hgnc.primary_symbol == "MTARC1"
    assert t.deprecation_warning is not None
    assert t.deprecation_warning.input_alias == "MARC1"


def test_resolve_by_hgnc_id():
    """HGNC ID input bypasses symbol search — resolves directly."""
    t = resolve("HGNC:11998")
    assert t.hgnc.primary_symbol == "TP53"
    assert t.input.interpreted_as == "hgnc_id"


def test_resolve_by_ensembl_gene_id_unversioned():
    t = resolve("ENSG00000141510")
    assert t.hgnc.primary_symbol == "TP53"
    assert t.input.interpreted_as == "ensembl_gene_id"


def test_resolve_by_ensembl_gene_id_versioned():
    """Versioned Ensembl input strips version for query, but the suffix is
    captured in the input descriptor."""
    t = resolve("ENSG00000141510.18")
    assert t.hgnc.primary_symbol == "TP53"
    assert t.input.value == "ENSG00000141510.18"


def test_resolve_by_uniprot_accession():
    t = resolve("P04637")
    assert t.hgnc.primary_symbol == "TP53"
    assert t.input.interpreted_as == "uniprot_accession"


def test_resolve_by_entrez_id():
    t = resolve("7157")
    assert t.hgnc.primary_symbol == "TP53"
    assert t.input.interpreted_as == "entrez_id"


def test_resolve_not_found():
    """Non-existent symbol raises NotFoundError, not silent miss."""
    with pytest.raises(NotFoundError):
        resolve("NOT_A_REAL_GENE_SYMBOL_XYZ123")


def test_resolve_release_pin_recorded():
    """Every Target carries the resolver_release in release_pins for audit."""
    t = resolve("KRAS")
    assert t.release_pins.resolver_release == "resolver_v0.1.0-alpha"
    # Alpha pin: hgnc + mygene_metadata are populated; ensembl/uniprot/ncbi pins
    # are intentionally not (they're populated from the federated MyGene response,
    # tagged via mygene_metadata).
    assert t.release_pins.hgnc == "hgnc-2026-q2"
    assert t.release_pins.mygene_metadata == "mygene-info-metadata-20260602"


def test_target_round_trips_to_json():
    """Target -> JSON dump validates against target.schema.json shape."""
    t = resolve("KRAS")
    body = t.model_dump(mode="json", exclude_none=True)
    # Spot-check a few schema invariants.
    assert body["hgnc"]["id"].startswith("HGNC:")
    assert body["ensembl"]["gene_id"].startswith("ENSG")
    assert "release_pins" in body
    assert body["release_pins"]["resolver_release"].startswith("resolver_v")


def test_target_fingerprint_is_deterministic():
    """Same input + same release -> identical fingerprint (modulo resolved_at)."""
    t1 = resolve("KRAS")
    t2 = resolve("KRAS")
    assert t1.fingerprint() == t2.fingerprint()
