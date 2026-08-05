"""per_sample_maf producer (2026-08-05): the ALT-2 subtype-panorama substrate.

The subgroup-stratified-mutation-frequency panorama recomputes frequency WITHIN each
stratum member-set from a per-sample MAF at ~/.cache/framework-gdc-pancohort-somatic/
{ind}-mc3.parquet. No first-class producer existed (only test fixtures wrote it), so the
panorama read subgroup_n=0 everywhere. per_sample_maf() builds it from the MC3 stream.

CRITICAL join-key contract (the subgroup-stratification sample-id trap): the assignments
shards key on the 3-segment PATIENT barcode (TCGA-A6-2670), so `sample_id` here MUST be the
patient barcode — NOT the 4-segment sample id the aggregate's internal dedup uses. These
tests mock the S3 MC3 stream with a synthetic gzipped MAF and pin: patient-barcode join key,
non-synonymous filter, dedup across aliquots, and off-indication rejection.
"""
from __future__ import annotations

import gzip
import io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from methods.gdc_somatic_hotspot import cli  # noqa: E402


_MAF_HEADER = "Hugo_Symbol\tVariant_Classification\tHGVSp_Short\tTumor_Sample_Barcode"


def _maf_line(gene, vc, hgvs, barcode):
    return f"{gene}\t{vc}\t{hgvs}\t{barcode}"


def _mock_mc3(monkeypatch, lines):
    """Patch boto3.client so per_sample_maf reads a synthetic gzipped MAF."""
    payload = ("\n".join([_MAF_HEADER] + lines) + "\n").encode("utf-8")
    gz_bytes = io.BytesIO()
    with gzip.GzipFile(fileobj=gz_bytes, mode="wb") as f:
        f.write(payload)
    gz_bytes.seek(0)

    class _FakeBody:
        def __init__(self, b): self._b = b
        def read(self, *a): return self._b.read(*a)

    class _FakeS3:
        def get_object(self, Bucket, Key):
            return {"Body": _FakeBody(io.BytesIO(gz_bytes.getvalue()))}

    # boto3 is imported function-locally inside per_sample_maf, so patch the boto3 module.
    import boto3
    monkeypatch.setattr(boto3, "client", lambda *a, **k: _FakeS3())


def test_sample_id_is_patient_barcode(monkeypatch):
    """sample_id MUST be the 3-segment patient barcode (joins the assignments shard),
    not the 4-segment sample id."""
    # TCGA-A6 is a COAD TSS code. Aliquot barcode → patient TCGA-A6-2670.
    lines = [_maf_line("KRAS", "Missense_Mutation", "p.G12D", "TCGA-A6-2670-01A-01D-1234-10")]
    _mock_mc3(monkeypatch, lines)
    tbl = cli.per_sample_maf("COADREAD").to_pylist()
    assert len(tbl) == 1
    assert tbl[0]["sample_id"] == "TCGA-A6-2670"          # 3-segment patient barcode
    assert tbl[0]["sample_id"].count("-") == 2
    assert tbl[0]["gene_symbol"] == "KRAS"
    assert tbl[0]["protein_change"] == "p.G12D"


def test_synonymous_variants_dropped(monkeypatch):
    lines = [
        _maf_line("KRAS", "Missense_Mutation", "p.G12D", "TCGA-A6-2670-01A-01D-1-10"),
        _maf_line("TTN", "Silent", "p.=", "TCGA-A6-2670-01A-01D-1-10"),          # synonymous → dropped
        _maf_line("XYZ", "3'UTR", "", "TCGA-A6-2670-01A-01D-1-10"),               # non-coding → dropped
    ]
    _mock_mc3(monkeypatch, lines)
    genes = {r["gene_symbol"] for r in cli.per_sample_maf("COADREAD").to_pylist()}
    assert genes == {"KRAS"}


def test_dedup_across_aliquots_of_same_patient(monkeypatch):
    """Two aliquots of the same patient + same call collapse to ONE row (so a per-stratum
    nunique(sample_id) counts patients, not aliquots)."""
    lines = [
        _maf_line("KRAS", "Missense_Mutation", "p.G12D", "TCGA-A6-2670-01A-01D-1111-10"),
        _maf_line("KRAS", "Missense_Mutation", "p.G12D", "TCGA-A6-2670-01A-11D-2222-10"),  # 2nd aliquot
    ]
    _mock_mc3(monkeypatch, lines)
    rows = cli.per_sample_maf("COADREAD").to_pylist()
    assert len(rows) == 1
    assert rows[0]["sample_id"] == "TCGA-A6-2670"


def test_off_indication_rows_rejected(monkeypatch):
    """A LUAD-TSS barcode must not appear in a COADREAD per-sample MAF."""
    lines = [
        _maf_line("KRAS", "Missense_Mutation", "p.G12D", "TCGA-A6-2670-01A-01D-1-10"),   # COAD
        _maf_line("EGFR", "Missense_Mutation", "p.L858R", "TCGA-05-4384-01A-01D-1-10"),  # LUAD TSS 05
    ]
    _mock_mc3(monkeypatch, lines)
    rows = cli.per_sample_maf("COADREAD").to_pylist()
    assert {r["gene_symbol"] for r in rows} == {"KRAS"}


def test_empty_indication_returns_empty_table(monkeypatch):
    # SCLC maps to no TCGA projects → empty, no stream needed.
    tbl = cli.per_sample_maf("SCLC")
    assert tbl.num_rows == 0
    assert [f.name for f in tbl.schema] == ["sample_id", "gene_symbol", "protein_change", "project"]
