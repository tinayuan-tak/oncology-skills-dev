"""cspa_surface_confirmation.read — surface-confirmation lookup via the resolver sidecar.

Hermetic: builds a synthetic payload parquet (keyed by UniProt AC) + a synthetic resolver sidecar
(native_row_key AC → hgnc_primary_symbol_at_resolution) in tmp — no S3, no CSPA xlsx. Pins:
  - a measured surface protein resolves by SYMBOL via the sidecar (the whole point — never trust a
    source's own symbol column);
  - lookup by UniProt AC works directly;
  - a target absent from the CSPA master is an honest measured-negative (not_surface, measured=False),
    NOT data_unavailable;
  - an unloadable derived product → data_unavailable.
The category→class mapping (build_payload) is checked on the raw Table_B category strings.
"""

from __future__ import annotations

import importlib
import sys
import tempfile
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

read_mod = importlib.import_module("methods.cspa_surface_confirmation.read")
derive_mod = importlib.import_module("methods.cspa_surface_confirmation.derive")


def _fixtures(tmp: Path):
    payload = pd.DataFrame(
        [
            {
                "uniprot_ac": "P00533",
                "surface_confirmation_class": "confirmed_high",
                "cspa_category": "1 - high confidence",
                "n_celllines_detected": 27,
            },
            {
                "uniprot_ac": "Q12864",
                "surface_confirmation_class": "confirmed_high",
                "cspa_category": "1 - high confidence",
                "n_celllines_detected": 1,
            },
            {
                "uniprot_ac": "O00000",
                "surface_confirmation_class": "not_surface",
                "cspa_category": "3 - unspecific",
                "n_celllines_detected": 2,
            },
        ]
    )
    ppath = tmp / "cspa.parquet"
    payload.to_parquet(ppath, index=False)
    sidecar = pd.DataFrame(
        [
            {"native_row_key": "P00533", "hgnc_primary_symbol_at_resolution": "EGFR"},
            {"native_row_key": "Q12864", "hgnc_primary_symbol_at_resolution": "CDH17"},
            {"native_row_key": "O00000", "hgnc_primary_symbol_at_resolution": "NOISE1"},
        ]
    )
    spath = tmp / "cspa.target_resolution.parquet"
    sidecar.to_parquet(spath, index=False)
    return str(ppath), str(spath)


def test_symbol_resolves_via_sidecar_to_measured_surface():
    with tempfile.TemporaryDirectory() as d:
        pp, sp = _fixtures(Path(d))
        read_mod._load_indexed.cache_clear()
        r = read_mod.read_surface_confirmation("EGFR", payload_path=pp, sidecar_path=sp)
        assert r["surface_confirmation_class"] == "confirmed_high"
        assert r["measured_in_cspa"] is True
        assert r["evidence_tier"] == "measured"
        assert r["uniprot_ac"] == "P00533"
        assert r["n_celllines_detected"] == 27


def test_lookup_by_uniprot_accession_directly():
    with tempfile.TemporaryDirectory() as d:
        pp, sp = _fixtures(Path(d))
        read_mod._load_indexed.cache_clear()
        r = read_mod.read_surface_confirmation("Q12864", payload_path=pp, sidecar_path=sp)
        assert r["surface_confirmation_class"] == "confirmed_high"
        assert r["uniprot_ac"] == "Q12864"


def test_absent_target_is_measured_negative_not_data_unavailable():
    with tempfile.TemporaryDirectory() as d:
        pp, sp = _fixtures(Path(d))
        read_mod._load_indexed.cache_clear()
        r = read_mod.read_surface_confirmation("KRAS", payload_path=pp, sidecar_path=sp)
        assert r["surface_confirmation_class"] == "not_surface"
        assert r["measured_in_cspa"] is False  # honest measured-absent, not a coverage gap
        assert r["evidence_tier"] == "measured"


def test_unspecific_category_maps_to_not_surface():
    with tempfile.TemporaryDirectory() as d:
        pp, sp = _fixtures(Path(d))
        read_mod._load_indexed.cache_clear()
        r = read_mod.read_surface_confirmation("NOISE1", payload_path=pp, sidecar_path=sp)
        assert r["surface_confirmation_class"] == "not_surface"  # cat 3 = detected-but-unspecific
        assert r["measured_in_cspa"] is True  # it IS in the master, just unspecific


def test_missing_derived_product_is_data_unavailable():
    read_mod._load_indexed.cache_clear()
    r = read_mod.read_surface_confirmation(
        "EGFR", payload_path="/nonexistent/x.parquet", sidecar_path="/nonexistent/x.sc.parquet"
    )
    assert r["surface_confirmation_class"] == "data_unavailable"


def test_build_payload_category_mapping():
    """build_payload maps the three CSPA categories to the card vocab."""
    with tempfile.TemporaryDirectory() as d:
        xl = Path(d) / "s2.xlsx"
        with pd.ExcelWriter(xl) as w:
            pd.DataFrame({"ID_link": ["P1"], "ENTREZ gene symbol": ["G1"]}).to_excel(
                w, sheet_name="Table_A", index=False
            )
            pd.DataFrame(
                {
                    "ID_link ": ["P00533", "Q12864", "O00000"],  # trailing space → stripped
                    "CSPA category": ["1 - high confidence", "2 - putative", "3 - unspecific"],
                    "Protein count": [27, 5, 2],
                }
            ).to_excel(w, sheet_name="Table_B", index=False)
        df = derive_mod.build_payload(str(xl))
        by_ac = df.set_index("uniprot_ac")["surface_confirmation_class"].to_dict()
        assert by_ac["P00533"] == "confirmed_high"
        assert by_ac["Q12864"] == "confirmed"
        assert by_ac["O00000"] == "not_surface"
