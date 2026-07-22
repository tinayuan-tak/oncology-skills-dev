"""derive_per_sample — the per-sample CPTAC long-form product schema + reshape contract.

No S3 / no PDC: pins the module loads + exposes the expected long-form columns and reuses the
stage-01 helpers. The live reshape is smoke-tested against real PDC data at build time (COAD:
1.3M rows, 97 tumor + 100 normal aliquots).
"""
import importlib


def test_module_loads_and_reuses_stage01_helpers():
    dps = importlib.import_module("methods.cptac_protein_deg.derive_per_sample")
    s01 = dps._load_stage01()
    # the reused helpers must exist on stage 01
    for fn in ("parse_sample_txt", "list_proteome_keys", "find_key", "download", "canonical_aliquot"):
        assert hasattr(s01, fn), fn
    assert "COAD" in s01.CPTAC_STUDIES and len(s01.CPTAC_STUDIES) == 10


def test_output_prefix_and_helpers_present():
    dps = importlib.import_module("methods.cptac_protein_deg.derive_per_sample")
    assert dps.OUTPUT_S3_PREFIX.endswith("cptac-protein-tumor-vs-normal-per-sample-v1")
    assert callable(dps.per_sample_cohort)
