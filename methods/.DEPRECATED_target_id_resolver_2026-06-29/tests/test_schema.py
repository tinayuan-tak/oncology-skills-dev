"""Pydantic Target schema unit tests — no network required."""

import pytest
from datetime import datetime, timezone

from target_id_resolver.schema import (
    Ensembl,
    HGNC,
    NCBI,
    DeprecationWarning_,
    InputDescriptor,
    ReleasePins,
    Target,
    UniProt,
)


def _make_minimal_target(**overrides):
    """Helper: build a minimum-valid Target for round-trip / validation tests."""
    base = dict(
        hgnc=HGNC(id="HGNC:11998", primary_symbol="TP53"),
        ensembl=Ensembl(gene_id="ENSG00000141510", version="18", full="ENSG00000141510.18"),
        release_pins=ReleasePins(resolver_release="resolver_v0.1.0-alpha"),
        resolver_version="0.1.0a1",
        resolved_at=datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return Target(**base)


def test_minimal_valid_target():
    t = _make_minimal_target()
    assert t.hgnc.id == "HGNC:11998"
    assert t.ensembl.full == "ENSG00000141510.18"


def test_hgnc_id_pattern_enforced():
    with pytest.raises(Exception):  # pydantic ValidationError
        HGNC(id="11998", primary_symbol="TP53")  # missing HGNC: prefix


def test_ensembl_full_consistency_check():
    """ensembl.full MUST equal '{gene_id}.{version}' if provided."""
    with pytest.raises(Exception):
        Ensembl(gene_id="ENSG00000141510", version="18", full="ENSG00000141510.17")


def test_ensembl_from_versioned_helper():
    e = Ensembl.from_versioned("ENSG00000141510.18")
    assert e.gene_id == "ENSG00000141510"
    assert e.version == "18"
    assert e.full == "ENSG00000141510.18"


def test_ensembl_from_versioned_rejects_unversioned():
    with pytest.raises(ValueError):
        Ensembl.from_versioned("ENSG00000141510")  # no version suffix


def test_uniprot_accession_pattern_canonical_six_char():
    """Standard 6-char UniProt accession (TP53)."""
    u = UniProt(canonical_accession="P04637", reviewed=True)
    assert u.canonical_accession == "P04637"


def test_uniprot_accession_rejects_isoform_suffix():
    """v2.0 stores canonical only — isoform suffixes (P04637-1) must reject."""
    with pytest.raises(Exception):
        UniProt(canonical_accession="P04637-1")


def test_release_pins_resolver_release_pattern():
    with pytest.raises(Exception):
        ReleasePins(resolver_release="not-a-valid-format")


def test_target_with_deprecation_warning():
    t = _make_minimal_target(
        hgnc=HGNC(id="HGNC:11110", primary_symbol="ARID1A"),
        ensembl=Ensembl(gene_id="ENSG00000117713", version="0", full="ENSG00000117713.0"),
        deprecation_warning=DeprecationWarning_(
            input_alias="BAF250A",
            resolved_to_primary="ARID1A",
            note="Previous symbol mapping",
        ),
    )
    assert t.deprecation_warning.input_alias == "BAF250A"


def test_target_fingerprint_excludes_resolved_at():
    t1 = _make_minimal_target()
    t2 = _make_minimal_target(resolved_at=datetime(2030, 1, 1, tzinfo=timezone.utc))
    assert t1.fingerprint() == t2.fingerprint()


def test_target_round_trip_json():
    """JSON dump -> JSON load preserves all fields."""
    import json
    t1 = _make_minimal_target(ncbi=NCBI(entrez_id=7157))
    body = t1.model_dump(mode="json", exclude_none=True)
    serialized = json.dumps(body)
    loaded = Target(**json.loads(serialized))
    assert loaded.fingerprint() == t1.fingerprint()


def test_input_descriptor_kind_validated():
    InputDescriptor(value="TP53", interpreted_as="hgnc_symbol")
    with pytest.raises(ValueError):
        InputDescriptor(value="TP53", interpreted_as="not_a_valid_kind")
