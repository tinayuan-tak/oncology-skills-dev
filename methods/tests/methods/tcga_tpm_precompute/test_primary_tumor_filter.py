"""tcga_tpm_precompute — the one delta vs GTEx: the Primary-Tumor sample filter.

The TPM math is inherited byte-for-byte from gtex_tpm_precompute (tested there); the NEW logic is
_primary_tumor_ids (restrict to sample_type == 'Primary Tumor'). No S3 — synthetic metadata.
"""

import importlib

import pandas as pd

cli = importlib.import_module("onc_methods.tcga_tpm_precompute.cli")


def test_primary_tumor_ids_keeps_only_primary_tumor():
    meta = pd.DataFrame(
        {
            "gdc_file_id": ["a", "b", "c", "d", "e"],
            "sample_type": ["Primary Tumor", "Solid Tissue Normal", "Metastatic", "Primary Tumor", "Recurrent Tumor"],
            "submitter_id": ["s1", "s2", "s3", "s4", "s5"],
        }
    )
    ids = cli._primary_tumor_ids(meta)
    assert ids == {"a", "d"}  # normal / metastatic / recurrent excluded


def test_primary_tumor_ids_includes_blood_cancer_primary():
    """LAML/DLBC (blood cancers) have NO 'Primary Tumor' — their primary samples are typed
    'Primary Blood Derived Cancer - ...'. Must be included, else the run crashes on LAML."""
    meta = pd.DataFrame(
        {
            "gdc_file_id": ["a", "b", "c"],
            "sample_type": [
                "Primary Blood Derived Cancer - Peripheral Blood",
                "Primary Blood Derived Cancer - Bone Marrow",
                "Blood Derived Normal",
            ],
            "submitter_id": ["s1", "s2", "s3"],
        }
    )
    ids = cli._primary_tumor_ids(meta)
    assert ids == {"a", "b"}  # both blood-cancer primaries kept; blood-derived NORMAL excluded


def test_33_studies_exclude_NA_catchall():
    assert "NA" not in cli.TCGA_STUDIES
    assert len(cli.TCGA_STUDIES) == 33
    assert "COAD" in cli.TCGA_STUDIES and "READ" in cli.TCGA_STUDIES
