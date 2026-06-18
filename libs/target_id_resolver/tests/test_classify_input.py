"""Unit tests for input classification — purely deterministic, no network."""

import pytest

from target_id_resolver.core import _classify_input


@pytest.mark.parametrize(
    "value,expected",
    [
        ("TP53", "hgnc_symbol"),
        ("KRAS", "hgnc_symbol"),
        ("HGNC:11998", "hgnc_id"),
        ("HGNC:6407", "hgnc_id"),
        ("ENSG00000141510", "ensembl_gene_id"),
        ("ENSG00000141510.18", "ensembl_gene_id"),
        ("P04637", "uniprot_accession"),  # canonical TP53 UniProt
        ("Q9Y6K9", "uniprot_accession"),
        ("7157", "entrez_id"),
        # Edge: BAF250A is symbol-shaped despite containing digits.
        ("BAF250A", "hgnc_symbol"),
        # Edge: lowercase symbol still classified as symbol (we case-fold downstream).
        ("tp53", "hgnc_symbol"),
    ],
)
def test_classify_input(value, expected):
    assert _classify_input(value) == expected
