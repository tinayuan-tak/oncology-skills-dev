"""Synthetic tests for the topology read-side (classifier + loaders + read entry).

Focus: the topology_class derivation (the decisive surface-druggability no-go signal —
GRIN2D-multipass / HTR1D-GPCR-multipass have no viable epitope), sidecar UniProt
resolution (payload gene_symbol is empty — must join via sidecar), the honest
PTM-data_unavailable block, and graceful degradation. No S3.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

METHODS_REPO = Path(__file__).resolve().parents[3]   # repo root (co-located code, not a hard-coded path)
sys.path.insert(0, str(METHODS_REPO))
from methods.topology_predictions_tmbed import classify as tc  # noqa: E402
from methods.topology_predictions_tmbed import read as tr      # noqa: E402


# --- classifier (pure) — the decisive no-go signal ------------------------

def test_multipass_is_multi_pass():
    # GRIN2D (ion channel) / HTR1D (GPCR, 7TM) → multi_pass → no viable epitope
    assert tc.classify_topology(n_tm_alpha=7, n_tm_beta=0, signal_peptide=False, ecd_orientation="outside") == "multi_pass"
    assert tc.classify_topology(n_tm_alpha=4, n_tm_beta=0, signal_peptide=False, ecd_orientation="inside") == "multi_pass"


def test_single_pass_type_1_needs_signal_peptide_and_outside():
    assert tc.classify_topology(1, 0, signal_peptide=True, ecd_orientation="outside") == "single_pass_type_1"


def test_single_pass_type_2_no_signal_peptide_outside():
    assert tc.classify_topology(1, 0, signal_peptide=False, ecd_orientation="outside") == "single_pass_type_2"


def test_single_pass_other_when_orientation_not_outside():
    assert tc.classify_topology(1, 0, signal_peptide=True, ecd_orientation="inside") == "single_pass_type_other"
    assert tc.classify_topology(1, 0, signal_peptide=False, ecd_orientation="unknown") == "single_pass_type_other"


def test_no_transmembrane_and_beta_barrel():
    assert tc.classify_topology(0, 0, signal_peptide=False, ecd_orientation="unknown") == "no_transmembrane"
    assert tc.classify_topology(0, 2, signal_peptide=False, ecd_orientation="outside") == "beta_barrel"
    # beta takes precedence even if alpha present (rare, but defined order)
    assert tc.classify_topology(1, 1, signal_peptide=True, ecd_orientation="outside") == "beta_barrel"


def test_gpi_never_emitted_from_1d_topology():
    # GPI-anchored is not derivable from TMbed 1D — must NOT be guessed (honest under-call)
    for args in [(1,0,True,"outside"),(0,0,False,"unknown"),(2,0,False,"outside")]:
        assert tc.classify_topology(*args) != "gpi_anchored"


# --- summary: card contract + honest PTM-unavailable ----------------------

def test_compute_summary_contract_and_unavailable_ptm():
    row = {"accession": "P0", "n_tm_alpha_helices": 7, "n_tm_beta_strands": 0,
           "signal_peptide": False, "signal_peptide_end": None, "ecd_length": 35,
           "ecd_orientation": "outside", "topology_summary": "TM-alpha|ECD-outside",
           "tmbed_model_version": "1.0.2"}
    s = tc.compute_summary(row, ptm_fields=tr._UNAVAILABLE_PTM_FIELDS, method_version="read-test")
    assert s["topology_class"] == "multi_pass"
    assert s["tm_pass_count"] == 7 and s["extracellular_residue_count"] == 35
    # PTM/motif fields honestly data_unavailable (product carries topology only)
    assert s["_ptm_coverage"] == "data_unavailable"
    assert s["n_glycosylation_sites"] is None and s["endocytosis_motif_types"] == []
    # card-contract topology fields present
    for f in ("topology_class","tm_pass_count","has_tm_beta","extracellular_residue_count",
              "ecd_orientation","signal_peptide_present","tmbed_model_version"):
        assert f in s, f"missing card field {f}"


# --- loaders + read entry (synthetic parquets) ----------------------------

def _write_products(tmp_path):
    payload = tmp_path / "topo.parquet"
    pd.DataFrame([
        {"accession": "Q9H1D0", "gene_symbol": "", "n_tm_alpha_helices": 7,   # HTR1D-like GPCR
         "n_tm_beta_strands": 0, "signal_peptide": False, "signal_peptide_end": None,
         "ecd_length": 25, "ecd_orientation": "outside", "topology_summary": "7TM",
         "tmbed_model_version": "1.0.2"},
        {"accession": "P43220", "gene_symbol": "", "n_tm_alpha_helices": 1,   # single-pass type-1
         "n_tm_beta_strands": 0, "signal_peptide": True, "signal_peptide_end": 24,
         "ecd_length": 300, "ecd_orientation": "outside", "topology_summary": "SP|TM|ECD-out",
         "tmbed_model_version": "1.0.2"},
    ]).to_parquet(payload, index=False)
    sidecar = tmp_path / "sidecar.parquet"
    pd.DataFrame([
        {"hgnc_primary_symbol_at_resolution": "HTR1D", "uniprot_canonical": "Q9H1D0"},
        {"hgnc_primary_symbol_at_resolution": "GLP1R", "uniprot_canonical": "P43220"},
    ]).to_parquet(sidecar, index=False)
    return str(payload), str(sidecar)


def test_read_target_summary_end_to_end(tmp_path):
    payload, sidecar = _write_products(tmp_path)
    out = tr.read_target_summary("HTR1D", indication="COADREAD",
                                 parquet_path=payload, sidecar_path=sidecar)
    assert out["topology_class"] == "multi_pass", "HTR1D GPCR must read multi_pass (no viable epitope)"
    assert out.get("_live_read_error") is None
    assert out["_ptm_coverage"] == "data_unavailable"


def test_read_sidecar_resolution_join(tmp_path):
    payload, sidecar = _write_products(tmp_path)
    out = tr.read_target_summary("GLP1R", parquet_path=payload, sidecar_path=sidecar)
    assert out["topology_class"] == "single_pass_type_1"


def test_read_target_not_in_resolver_is_data_unavailable(tmp_path):
    payload, sidecar = _write_products(tmp_path)
    out = tr.read_target_summary("NOTAGENE", parquet_path=payload, sidecar_path=sidecar)
    assert out["topology_class"] == "data_unavailable"
    assert out["_live_read_error"] == "target_not_in_resolver"


def test_read_graceful_on_parquet_failure(tmp_path):
    _, sidecar = _write_products(tmp_path)
    # valid sidecar, but point the payload at a nonexistent path → graceful data_unavailable
    out = tr.read_target_summary("HTR1D", parquet_path=str(tmp_path / "nope.parquet"),
                                 sidecar_path=sidecar)
    assert out["topology_class"] == "data_unavailable"
    assert out["_live_read_error"] == "topology_parquet_read_failed"


def test_s3_read_is_cached_once_per_key(tmp_path, monkeypatch):
    """The S3 loader must read each object (payload, sidecar) at most ONCE per process and reuse it
    across targets — the fix's whole point (previously re-downloaded the whole object every call).
    Local parquet_path/sidecar_path overrides bypass the cache (so the other tests are unaffected)."""
    import boto3
    payload, sidecar = _write_products(tmp_path)
    blobs = {("BKT", "topo.parquet"): Path(payload).read_bytes(),
             ("BKT", "sidecar.parquet"): Path(sidecar).read_bytes()}
    calls: dict = {}

    class _Body:
        def __init__(self, b): self._b = b
        def read(self): return self._b

    class _Client:
        def get_object(self, Bucket, Key):
            calls[(Bucket, Key)] = calls.get((Bucket, Key), 0) + 1
            return {"Body": _Body(blobs[(Bucket, Key)])}

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _Client())
    tc._read_parquet_s3.cache_clear()
    try:
        for _ in range(3):                                    # many "targets" in one process
            tc._read_parquet(None, "BKT", "topo.parquet")
            tc._read_parquet(None, "BKT", "sidecar.parquet")
        assert calls[("BKT", "topo.parquet")] == 1            # downloaded once, then cache hits
        assert calls[("BKT", "sidecar.parquet")] == 1
    finally:
        tc._read_parquet_s3.cache_clear()                     # don't leak cached frames to other tests
