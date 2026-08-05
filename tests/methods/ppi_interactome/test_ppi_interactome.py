"""PPI interactome method: STRING high-confidence degree + CORUM complex membership.

S3-free unit test (fixture STRING info/links + CORUM + sidecar) + a live smoke (skips without S3)."""
from __future__ import annotations

import gzip
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.ppi_interactome import read as _ppi  # noqa: E402


def _fixtures(tmp_path):
    import pandas as pd
    info = tmp_path / "info.txt.gz"
    with gzip.open(info, "wt") as fh:
        fh.write("#string_protein_id\tpreferred_name\n")
        fh.write("9606.ENSP_TGT\tTGT\n9606.ENSP_A\tPARTNERA\n9606.ENSP_B\tPARTNERB\n")
    links = tmp_path / "links.txt.gz"
    with gzip.open(links, "wt") as fh:
        fh.write("protein1 protein2 combined_score\n")
        fh.write("9606.ENSP_TGT 9606.ENSP_A 900\n")   # high-confidence
        fh.write("9606.ENSP_TGT 9606.ENSP_B 300\n")   # below threshold -> excluded
    corum_u = tmp_path / "corum_uniprot.txt"
    corum_u.write_text("UniProtKB_accession_number\tcorum_id\nP99999\t42\n")
    corum_c = tmp_path / "corum_complete.txt"
    corum_c.write_text("complex_id\tcomplex_name\n42\tTest Complex\n")
    sc = tmp_path / "sidecar.parquet"
    pd.DataFrame([{"hgnc_primary_symbol_at_resolution": "TGT", "uniprot_canonical": "P99999"}]).to_parquet(sc)
    for fn in (_ppi._load_string_info, _ppi._load_corum, _ppi._load_uniprot_sidecar):
        fn.cache_clear()
    return dict(info_path=str(info), links_path=str(links), corum_uniprot_path=str(corum_u),
                corum_complete_path=str(corum_c), sidecar_path=str(sc))


def test_string_threshold_and_corum_membership(tmp_path):
    s = _ppi.read_target_summary("TGT", **_fixtures(tmp_path))
    # only the score>=700 edge counts
    assert s["n_high_confidence_interactors"] == 1
    assert s["top_interactors"][0]["partner"] == "PARTNERA"
    # CORUM complex resolved via the sidecar (symbol->AC->complex->name)
    assert s["n_corum_complexes"] == 1
    assert s["in_protein_complex"] is True
    assert s["corum_complexes"][0]["complex_name"] == "Test Complex"


def test_unknown_target_data_unavailable(tmp_path):
    s = _ppi.read_target_summary("NOTAPROTEIN", **_fixtures(tmp_path))
    assert s["interactome_class"] == "data_unavailable"


def test_live_egfr_is_hub():
    for fn in (_ppi._load_string_info, _ppi._load_corum, _ppi._load_uniprot_sidecar):
        fn.cache_clear()
    try:
        s = _ppi.read_target_summary("EGFR")
    except Exception:  # noqa: BLE001
        pytest.skip("no S3")
    if s.get("_data_note"):
        pytest.skip("PPI source unreachable (no S3)")
    assert s["n_high_confidence_interactors"] > 50
    assert s["in_protein_complex"] is True


def test_string_edges_from_product_pushdown(tmp_path):
    """The FAST path: _string_edges_from_product reads the gene-sorted product with a gene_symbol
    pushdown filter, returning symbol-resolved HC edges (no info-map, no stream). S3-free fixture."""
    import pandas as pd
    from methods.ppi_interactome import read as _ppi
    prod = tmp_path / "string_hc.parquet"
    pd.DataFrame([
        {"gene_symbol": "TGT", "partner_symbol": "PARTNERA", "combined_score": 900},
        {"gene_symbol": "TGT", "partner_symbol": "PARTNERB", "combined_score": 800},
        {"gene_symbol": "OTHER", "partner_symbol": "ZZZ", "combined_score": 950},
    ]).to_parquet(prod)
    edges = _ppi._string_edges_from_product("TGT", product_path=str(prod))
    assert edges is not None
    partners = {e["partner"] for e in edges}
    assert partners == {"PARTNERA", "PARTNERB"}   # only TGT's edges, not OTHER's
    assert all(e["combined_score"] >= 700 for e in edges)


def test_string_product_missing_returns_none(tmp_path):
    """Product unreadable → None (signals the reader to fall back to the legacy stream)."""
    from methods.ppi_interactome import read as _ppi
    assert _ppi._string_edges_from_product("TGT", product_path=str(tmp_path / "nope.parquet")) is None
