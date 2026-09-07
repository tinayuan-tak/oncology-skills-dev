"""gdc_dr45_pancohort aggregator — manifest-driven per-aliquot MAF streaming.

Verifies (no S3, no real manifest): the tumor-only file filter, per-gene case-frequency with
case-level dedup, the hotspot rows, and the multi-disease-program guard (CPTAC-3 must raise).
Mocks _load_manifest_files + _stream_maf_genes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from methods.gdc_dr45_pancohort import aggregate as agg  # noqa: E402


def _fake_files():
    # 3 tumor aliquots across 2 CASES (c1 has two aliquots → must dedup to 1 case) + 1 normal (dropped).
    return [
        {
            "project_id": "ALCHEMIST-ALCH",
            "case_id": "c1",
            "path": "p/c1a.maf.gz",
            "description": "primary tumor sample",
        },
        {"project_id": "ALCHEMIST-ALCH", "case_id": "c1", "path": "p/c1b.maf.gz", "description": "ffpe tumor sample"},
        {"project_id": "ALCHEMIST-ALCH", "case_id": "c2", "path": "p/c2.maf.gz", "description": "primary tumor sample"},
    ]


# gene rows per file path: (gene, hgvs, variant_class)
_FILE_ROWS = {
    "p/c1a.maf.gz": [("KRAS", "p.G12C", "Missense_Mutation"), ("TP53", "p.R175H", "Missense_Mutation")],
    "p/c1b.maf.gz": [("KRAS", "p.G12C", "Missense_Mutation")],  # same case c1, same call → dedups
    "p/c2.maf.gz": [("KRAS", "p.G12V", "Missense_Mutation")],
}


def _patch(monkeypatch, files=None):
    monkeypatch.setattr(
        agg, "_load_manifest_files", lambda program, repo=None: files if files is not None else _fake_files()
    )
    monkeypatch.setattr(agg, "_boto3_client", lambda: object())
    monkeypatch.setattr(agg, "ensure_aws_profile", lambda: None)

    def _fake_stream(s3, key):
        # key is DR45_S3_PREFIX/path → recover the path suffix
        for p, rows in _FILE_ROWS.items():
            if key.endswith(p):
                return rows
        return []

    monkeypatch.setattr(agg, "_stream_maf_genes", _fake_stream)


def test_aggregate_case_dedup_and_frequency(monkeypatch):
    _patch(monkeypatch)
    tbl = agg.aggregate_program("ALCHEMIST-ALCH").to_pylist()
    summary = {r["gene_symbol"]: r for r in tbl if r["hotspot_protein_change"] is None}
    # 2 distinct cases (c1 deduped from its 2 aliquots)
    assert summary["KRAS"]["n_samples_in_indication"] == 2
    # KRAS mutated in BOTH cases (c1 + c2) → freq 1.0; TP53 in only c1 → 0.5
    assert summary["KRAS"]["n_samples_mutated"] == 2 and summary["KRAS"]["overall_mutation_frequency"] == 1.0
    assert summary["TP53"]["n_samples_mutated"] == 1 and summary["TP53"]["overall_mutation_frequency"] == 0.5
    assert summary["KRAS"]["indication"] == "NSCLC"


def test_hotspot_rows_dedup_by_case(monkeypatch):
    _patch(monkeypatch)
    tbl = agg.aggregate_program("ALCHEMIST-ALCH").to_pylist()
    kras_hs = {
        r["hotspot_protein_change"]: r["hotspot_n_samples"]
        for r in tbl
        if r["gene_symbol"] == "KRAS" and r["hotspot_protein_change"]
    }
    # G12C in c1 (two aliquots → 1 case), G12V in c2
    assert kras_hs == {"p.G12C": 1, "p.G12V": 1}


def test_load_manifest_files_filters_tumor_and_program(tmp_path):
    """The tumor-only + program filter lives in _load_manifest_files (description-driven).
    Point it at a synthetic manifest via data_catalog_repo and verify a normal file + an
    off-program file are both dropped."""
    import yaml

    mdir = tmp_path / "manifests" / "sources"
    mdir.mkdir(parents=True)
    (mdir / "gdc-pancohort-somatic-dr45-0.yaml").write_text(
        yaml.safe_dump(
            {
                "files": [
                    {
                        "project_id": "ALCHEMIST-ALCH",
                        "case_id": "c1",
                        "path": "p/c1.maf.gz",
                        "description": "primary tumor sample",
                    },
                    {
                        "project_id": "ALCHEMIST-ALCH",
                        "case_id": "c9",
                        "path": "p/c9n.maf.gz",
                        "description": "blood derived normal",
                    },
                    {
                        "project_id": "OTHER-PROG",
                        "case_id": "x",
                        "path": "p/x.maf.gz",
                        "description": "primary tumor sample",
                    },
                ]
            }
        )
    )
    files = agg._load_manifest_files("ALCHEMIST-ALCH", data_catalog_repo=tmp_path)
    assert [f["case_id"] for f in files] == ["c1"]  # normal + off-program dropped


def test_multi_disease_program_raises():
    # CPTAC-3 is not in PROGRAM_TO_INDICATION (needs per-case disease join) → must raise, not guess.
    with pytest.raises(ValueError, match="per-case disease join"):
        agg._resolve_indication("CPTAC-3")
