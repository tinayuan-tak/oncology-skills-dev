"""functional_gene_state Phase-2 accelerator: the two-hit product read-path.

Guards the reshape that replaced the ~1.6 GB per-query live read (MC3 + ABSOLUTE + GISTIC) with a
per-gene pushdown scan of pancan-genomic-two-hit-per-gene-v1. Three invariants, all S3-free
(the product read + sample-map + methylation are monkeypatched):

  1. RECONSTRUCTION is faithful: an absent product row → wt; a stored row's fields → the SAME
     SampleEvidence the live path builds → the SAME classify + summarize output.
  2. FALLBACK: an unreachable product (reader returns None) routes to the live path.
  3. The product path is marked (_read_path) so a consumer can assert the accelerator was used.
"""

from __future__ import annotations

import pytest

from onc_methods.functional_gene_state import read as fgs


@pytest.fixture
def patched(monkeypatch):
    """A tiny COADREAD cohort of 5 patients + no methylation; product rows injected per-test."""
    sample_ct = {f"TCGA-AA-000{i}": "COAD" for i in range(5)}
    monkeypatch.setattr(fgs, "_load_sample_cancer_types", lambda: sample_ct)
    monkeypatch.setattr(fgs, "_read_patient_methylation", lambda *a, **k: {})
    return sample_ct


def test_reconstruction_classifies_from_product_rows(patched):
    """Two altered rows (one biallelic homdel, one mutation+LOH → biallelic; one mutation copy-neutral
    no-LOH → monoallelic) + two absent patients (→ wt). Assert the rolled-up counts."""
    rows = (
        {
            "gene_symbol": "GX",
            "patient_barcode": "TCGA-AA-0000",
            "cancer_type": "COAD",
            "has_mutation": False,
            "mutation_is_lof": None,
            "cn_class": "homdel",
            "loh_at_locus": None,
        },
        {
            "gene_symbol": "GX",
            "patient_barcode": "TCGA-AA-0001",
            "cancer_type": "COAD",
            "has_mutation": True,
            "mutation_is_lof": True,
            "cn_class": "neutral",
            "loh_at_locus": True,
        },
        {
            "gene_symbol": "GX",
            "patient_barcode": "TCGA-AA-0002",
            "cancer_type": "COAD",
            "has_mutation": True,
            "mutation_is_lof": False,
            "cn_class": "neutral",
            "loh_at_locus": False,
        },
        # TCGA-AA-0003, TCGA-AA-0004 absent → wt
    )
    monkeypatch_rows(fgs, rows)
    out = fgs._read_patient_arm("GX", "COADREAD")
    assert out["_read_path"] == "two_hit_product_v1"
    c = out["state_counts"]
    assert c["biallelic-genetic"] == 2  # homdel + (mut+LOH)
    assert c["monoallelic"] == 1  # mut, copy-neutral, no LOH
    assert c["wt"] == 2  # the two absent patients
    assert out["n_mutated"] == 2
    assert out["fraction_biallelic"] == 2 / 5  # n_determinable = 5 (no uncertain)


def test_absent_patients_reconstruct_to_wt(patched):
    """An empty product row set (gene present, no altered patients) → every patient wt."""
    monkeypatch_rows(fgs, ())
    out = fgs._read_patient_arm("GY", "COADREAD")
    assert out["_read_path"] == "two_hit_product_v1"
    assert out["state_counts"]["wt"] == 5
    assert out["fraction_any_alteration"] == 0.0
    assert out["n_mutated"] == 0


def test_unreachable_product_falls_back_to_live(patched, monkeypatch):
    """Reader returns None (product unreachable) → the live path runs. We stub the live path to a
    sentinel so the test stays S3-free; the point is the ROUTING, not the live read itself."""
    monkeypatch.setattr(fgs, "_read_two_hit_evidence", lambda target: None)
    sentinel = {"_arm": "patient", "state_counts": {}, "_read_path": "live_full_object", "_stub": True}
    monkeypatch.setattr(fgs, "_read_patient_arm_live", lambda *a, **k: sentinel)
    out = fgs._read_patient_arm("GZ", "COADREAD")
    assert out["_read_path"] == "live_full_object"
    assert out.get("_stub") is True


def test_uncertain_when_mutation_and_loh_unknown(patched):
    """A mutation on a copy-neutral background with UNKNOWN LOH (None) → uncertain (rule 4), and it is
    excluded from the biallelic denominator. This is the field the reshape most easily gets wrong."""
    rows = (
        {
            "gene_symbol": "GW",
            "patient_barcode": "TCGA-AA-0000",
            "cancer_type": "COAD",
            "has_mutation": True,
            "mutation_is_lof": False,
            "cn_class": None,
            "loh_at_locus": None,
        },
    )
    monkeypatch_rows(fgs, rows)
    out = fgs._read_patient_arm("GW", "COADREAD")
    assert out["state_counts"]["uncertain"] == 1
    assert out["state_counts"]["wt"] == 4
    assert out["n_determinable"] == 4  # uncertain excluded
    assert out["fraction_biallelic"] == 0.0  # 0 biallelic / 4 determinable


def monkeypatch_rows(mod, rows):
    """Force _read_two_hit_evidence to return `rows` (bypasses S3). Uses the lru cache-free direct
    attribute set; each test calls it before invoking _read_patient_arm."""
    mod._read_two_hit_evidence = lambda target: rows
