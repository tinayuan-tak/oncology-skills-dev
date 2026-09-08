"""uniprot_protein_features: FT DOMAIN architecture + KW→protein-class mapping.

S3-free fixture test (synthetic DAT: a kinase w/ domain, a keyword-only TF) + live smoke."""

from __future__ import annotations

import gzip
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.uniprot_protein_features import derive as _d  # noqa: E402
from methods.uniprot_protein_features import read as _r

_DAT = (
    "AC   P00001;\nGN   Name=KIN1;\n"
    'FT   DOMAIN          10..250\nFT                   /note="Protein kinase"\n'
    "KW   Kinase; Transferase; ATP-binding; 3D-structure.\n//\n"
    "AC   P00002;\nGN   Name=TF1;\n"
    "KW   Activator; DNA-binding; Disease variant.\n//\n"
    "AC   P00003;\nGN   Name=BORING1;\n"  # no domain, no class keyword -> excluded
    "KW   3D-structure; Phosphoprotein.\n//\n"
)


def test_domain_and_keyword_class_extraction(tmp_path):
    dat = tmp_path / "sp.dat.gz"
    with gzip.open(dat, "wt") as fh:
        fh.write(_DAT)
    df = _d.build_payload(local_dat=str(dat))
    acs = set(df["uniprot_ac"])
    assert acs == {"P00001", "P00002"}  # P00003 excluded (no domain + no class keyword)
    kin = df[df["uniprot_ac"] == "P00001"].iloc[0]
    assert kin["domain_architecture"] == "Protein kinase"
    assert "kinase" in list(kin["protein_class"]) and "transferase" in list(kin["protein_class"])
    tf = df[df["uniprot_ac"] == "P00002"].iloc[0]
    assert tf["n_domains"] == 0  # keyword-only, no FT DOMAIN
    assert "transcription_factor" in list(tf["protein_class"])  # Activator + DNA-binding -> TF


def test_live_egfr_kinase():
    _r._load_indexed.cache_clear()
    try:
        s = _r.read_target_summary("EGFR")
    except Exception:  # noqa: BLE001
        pytest.skip("no S3")
    if s.get("_data_note"):
        pytest.skip("protein-features product unreachable (no S3)")
    assert s["n_domains"] >= 1
    assert "kinase" in s["protein_class"]


# --- InterPro additive layer (1.1.0) ---------------------------------------
def _fixtures(tmp_path):
    """Build local curated + InterPro + interpro-sidecar parquets. Curated has a kinase (K1, AC A1)
    with 1 domain + a keyword-only TF (T1, AC A2, 0 domains). InterPro adds domains for A1 (2), A2
    (1), and a THIRD AC A3 that is NOT in the curated product at all (interpro_only gap-fill)."""
    import pandas as pd

    cur = pd.DataFrame(
        [
            {
                "uniprot_ac": "A1",
                "n_domains": 1,
                "domain_names": ["Protein kinase"],
                "domain_architecture": "Protein kinase",
                "protein_class": ["kinase"],
                "protein_class_primary": "kinase",
            },
            {
                "uniprot_ac": "A2",
                "n_domains": 0,
                "domain_names": [],
                "domain_architecture": None,
                "protein_class": ["transcription_factor"],
                "protein_class_primary": "transcription_factor",
            },
        ]
    )
    cur_p = tmp_path / "cur.parquet"
    cur.to_parquet(cur_p)
    cur_sc = pd.DataFrame(
        [
            {"native_row_key": "A1", "hgnc_primary_symbol_at_resolution": "K1"},
            {"native_row_key": "A2", "hgnc_primary_symbol_at_resolution": "T1"},
        ]
    )
    cur_sc_p = tmp_path / "cur_sc.parquet"
    cur_sc.to_parquet(cur_sc_p)
    ip = pd.DataFrame(
        [
            {
                "uniprot_accession": "A1",
                "interpro_id": "IPR1",
                "interpro_name": "L-domain",
                "interpro_type": "domain",
                "start": 10,
                "end": 90,
            },
            {
                "uniprot_accession": "A1",
                "interpro_id": "IPR2",
                "interpro_name": "Kinase domain",
                "interpro_type": "domain",
                "start": 100,
                "end": 300,
            },
            {
                "uniprot_accession": "A2",
                "interpro_id": "IPR3",
                "interpro_name": "p53-like DBD",
                "interpro_type": "domain",
                "start": 5,
                "end": 200,
            },
            {
                "uniprot_accession": "A1",
                "interpro_id": "IPRF",
                "interpro_name": "Some family",
                "interpro_type": "family",
                "start": None,
                "end": None,
            },  # non-domain type: must be ignored
            {
                "uniprot_accession": "A3",
                "interpro_id": "IPR9",
                "interpro_name": "Orphan domain",
                "interpro_type": "domain",
                "start": 1,
                "end": 50,
            },
        ]
    )
    ip_p = tmp_path / "ip.parquet"
    ip.to_parquet(ip_p)
    ip_sc = pd.DataFrame(
        [  # InterPro sidecar is a SUPERSET: includes A3 (not in curated)
            {"native_row_key": "A1", "hgnc_primary_symbol_at_resolution": "K1"},
            {"native_row_key": "A2", "hgnc_primary_symbol_at_resolution": "T1"},
            {"native_row_key": "A3", "hgnc_primary_symbol_at_resolution": "ORPHAN1"},
        ]
    )
    ip_sc_p = tmp_path / "ip_sc.parquet"
    ip_sc.to_parquet(ip_sc_p)
    return str(cur_p), str(cur_sc_p), str(ip_p), str(ip_sc_p)


def _read(tmp_path, target):
    cur_p, cur_sc_p, ip_p, ip_sc_p = _fixtures(tmp_path)
    _r._load_indexed.cache_clear()
    _r._load_interpro_symbol_map.cache_clear()
    return _r.read_target_summary(
        target, payload_path=cur_p, sidecar_path=cur_sc_p, interpro_path=ip_p, interpro_sidecar_path=ip_sc_p
    )


def test_curated_plus_interpro_is_both(tmp_path):
    s = _read(tmp_path, "K1")
    assert s["domain_evidence"] == "both"
    assert s["n_domains"] == 1  # curated UNCHANGED
    assert s["protein_features_class"] == "single_domain"  # curated PRIMARY unchanged
    assert s["interpro_n_domains"] == 2  # family type ignored
    assert s["interpro_domain_names"] == ["L-domain", "Kinase domain"]  # start-ordered


def test_keyword_only_gains_interpro_is_interpro_only(tmp_path):
    s = _read(tmp_path, "T1")
    assert s["protein_features_class"] == "no_curated_domain"  # curated PRIMARY unchanged
    assert s["domain_evidence"] == "interpro_only"
    assert s["interpro_n_domains"] == 1
    assert s["interpro_domain_names"] == ["p53-like DBD"]


def test_absent_from_curated_but_in_interpro_gapfill(tmp_path):
    # ORPHAN1 (A3) is NOT in the curated product; resolves only via the InterPro sidecar fallback.
    s = _read(tmp_path, "ORPHAN1")
    assert s["protein_features_class"] == "data_unavailable"  # no curated record
    assert s["domain_evidence"] == "interpro_only"
    assert s["uniprot_ac"] == "A3"
    assert s["interpro_n_domains"] == 1


def test_interpro_fields_present_in_empty(tmp_path):
    e = _r._empty("x")
    for f in ("domain_evidence", "interpro_n_domains", "interpro_domain_names", "interpro_domain_architecture"):
        assert f in e
