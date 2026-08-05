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

from methods.uniprot_protein_features import derive as _d, read as _r  # noqa: E402

_DAT = (
    "AC   P00001;\nGN   Name=KIN1;\n"
    "FT   DOMAIN          10..250\nFT                   /note=\"Protein kinase\"\n"
    "KW   Kinase; Transferase; ATP-binding; 3D-structure.\n//\n"
    "AC   P00002;\nGN   Name=TF1;\n"
    "KW   Activator; DNA-binding; Disease variant.\n//\n"
    "AC   P00003;\nGN   Name=BORING1;\n"   # no domain, no class keyword -> excluded
    "KW   3D-structure; Phosphoprotein.\n//\n"
)


def test_domain_and_keyword_class_extraction(tmp_path):
    dat = tmp_path / "sp.dat.gz"
    with gzip.open(dat, "wt") as fh:
        fh.write(_DAT)
    df = _d.build_payload(local_dat=str(dat))
    acs = set(df["uniprot_ac"])
    assert acs == {"P00001", "P00002"}   # P00003 excluded (no domain + no class keyword)
    kin = df[df["uniprot_ac"] == "P00001"].iloc[0]
    assert kin["domain_architecture"] == "Protein kinase"
    assert "kinase" in list(kin["protein_class"]) and "transferase" in list(kin["protein_class"])
    tf = df[df["uniprot_ac"] == "P00002"].iloc[0]
    assert tf["n_domains"] == 0                              # keyword-only, no FT DOMAIN
    assert "transcription_factor" in list(tf["protein_class"])   # Activator + DNA-binding -> TF


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
