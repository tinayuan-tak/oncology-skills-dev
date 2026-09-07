"""functional_gene_state pure two-hit classifier — the biology truth table. No S3 (dict fixtures)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.functional_gene_state.classify import (  # noqa: E402
    SampleEvidence,
    classify_functional_state,
    summarize_states,
    FUNCTIONAL_STATES,
)


def _c(**kw) -> str:
    return classify_functional_state(SampleEvidence(**kw))


# ── biallelic-genetic: completed two-hit events ──────────────────────────────
def test_homdel_is_biallelic_regardless_of_mutation():
    assert _c(has_mutation=False, cn_class="homdel") == "biallelic-genetic"
    assert _c(has_mutation=True, cn_class="homdel") == "biallelic-genetic"


def test_mutation_plus_single_copy_loss_is_biallelic():
    # a hit + loss of the other allele = both alleles inactivated
    assert _c(has_mutation=True, cn_class="loss") == "biallelic-genetic"


def test_mutation_plus_loh_at_locus_is_biallelic():
    # copy-neutral LOH: the mutant allele duplicated, wild-type lost → both alleles mutant
    assert _c(has_mutation=True, cn_class="neutral", loh_at_locus=True) == "biallelic-genetic"


# ── monoallelic: exactly one hit ─────────────────────────────────────────────
def test_het_mutation_copy_neutral_no_loh_is_monoallelic():
    assert _c(has_mutation=True, cn_class="neutral", loh_at_locus=False) == "monoallelic"
    assert _c(has_mutation=True, cn_class="gain", loh_at_locus=False) == "monoallelic"


def test_single_copy_loss_no_mutation_is_monoallelic():
    assert _c(has_mutation=False, cn_class="loss") == "monoallelic"


# ── wt: no hits ──────────────────────────────────────────────────────────────
def test_no_mutation_no_loss_is_wt():
    assert _c(has_mutation=False, cn_class="neutral") == "wt"
    assert _c(has_mutation=False, cn_class="gain") == "wt"
    assert _c(has_mutation=False, cn_class=None) == "wt"


# ── uncertain: signals present but second hit undeterminable ─────────────────
def test_mutation_unknown_background_is_uncertain():
    # mutation but CN not measured and LOH not determinable (model-side copy-neutral case)
    assert _c(has_mutation=True, cn_class=None, loh_at_locus=None) == "uncertain"
    # mutation, copy-neutral, LOH could-not-be-determined → cannot exclude a hidden 2nd hit
    assert _c(has_mutation=True, cn_class="neutral", loh_at_locus=None) == "uncertain"


def test_all_states_are_in_vocabulary():
    # exhaustive-ish sweep: every combination lands in the declared vocabulary
    for has_mut in (True, False):
        for cn in ("homdel", "loss", "neutral", "gain", None):
            for loh in (True, False, None):
                s = _c(has_mutation=has_mut, cn_class=cn, loh_at_locus=loh)
                assert s in FUNCTIONAL_STATES, (has_mut, cn, loh, s)


# ── summary rollup ───────────────────────────────────────────────────────────
def test_summarize_biallelic_fraction_excludes_uncertain_from_denominator():
    states = ["biallelic-genetic"] * 2 + ["monoallelic"] * 3 + ["wt"] * 4 + ["uncertain"] * 1
    summ = summarize_states(states)
    assert summ["n_samples"] == 10
    assert summ["n_determinable"] == 9  # 10 − 1 uncertain
    assert summ["state_counts"]["biallelic-genetic"] == 2
    assert summ["fraction_biallelic"] == pytest.approx(2 / 9)
    # any-alteration = NOT-wt over ALL samples: 10 − 4 wt = 6 (the lone `uncertain` carries a hit)
    assert summ["fraction_any_alteration"] == pytest.approx(6 / 10)


def test_summarize_empty():
    summ = summarize_states([])
    assert summ["n_samples"] == 0
    assert summ["fraction_biallelic"] is None
    assert summ["fraction_any_alteration"] is None


# ── Phase-2 epigenetic states ────────────────────────────────────────────────
def test_summarize_biallelic_epigenetic_counts_toward_biallelic_fraction():
    # biallelic+epigenetic and biallelic-genetic both count as completed two-hit events
    states = ["biallelic-genetic", "biallelic+epigenetic", "epigenetic", "wt"]
    summ = summarize_states(states)
    assert summ["state_counts"]["biallelic-genetic"] == 1
    assert summ["state_counts"]["biallelic+epigenetic"] == 1
    assert summ["state_counts"]["epigenetic"] == 1
    assert summ["n_determinable"] == 4  # no uncertain
    assert summ["fraction_biallelic"] == pytest.approx(2 / 4)


def test_summarize_epigenetic_only_not_biallelic():
    # pure epigenetic silencing (no genetic hit) is a hit but not biallelic inactivation
    states = ["epigenetic", "wt", "wt"]
    summ = summarize_states(states)
    assert summ["fraction_biallelic"] == pytest.approx(0.0)
    assert summ["fraction_any_alteration"] == pytest.approx(1 / 3)


def test_methylation_state_upgrade_logic():
    """Verify the Phase-2 upgrade rules directly (no S3) via read_model_states_per_model
    monkey-patched to return fixture data."""
    from methods.functional_gene_state import read as fgs_read

    # Patch all four data-fetching functions with fixtures
    def _damaging(_fn, _t):
        return {"ACH-A": True, "ACH-B": False, "ACH-C": False}

    def _cn(_t):
        # ACH-A: has mutation + CN loss → biallelic-genetic (methylation is redundant)
        # ACH-B: wt genetic, but methylated → epigenetic
        # ACH-C: monoallelic (loss, no mutation) + methylated → biallelic+epigenetic
        return {
            "ACH-A": 0.5,  # cn loss (between HOMDEL_MAX and LOSS_MAX)
            "ACH-B": 0.9,  # neutral
            "ACH-C": 0.5,
        }  # cn loss

    def _meth(_t):
        return {"ACH-A": True, "ACH-B": True, "ACH-C": True}

    orig_dam = fgs_read._read_depmap_mut_matrix
    orig_hot = fgs_read._read_depmap_mut_matrix
    orig_cn = fgs_read._read_depmap_cn
    orig_meth = fgs_read._read_model_methylation

    try:
        fgs_read._read_depmap_mut_matrix = _damaging
        fgs_read._read_depmap_cn = _cn
        fgs_read._read_model_methylation = _meth

        result = fgs_read.read_model_states_per_model("TESTGENE")
    finally:
        fgs_read._read_depmap_mut_matrix = orig_dam
        fgs_read._read_depmap_cn = orig_cn
        fgs_read._read_model_methylation = orig_meth

    assert result["ACH-A"]["state"] == "biallelic-genetic"  # genetic already biallelic; meth redundant
    assert result["ACH-B"]["state"] == "epigenetic"  # wt genetic + methylated → epigenetic
    assert result["ACH-C"]["state"] == "biallelic+epigenetic"  # monoallelic + methylated → biallelic
    assert result["ACH-B"]["is_methylated"] is True
    assert result["ACH-A"]["is_methylated"] is True


def test_patient_methylation_upgrade_logic():
    """Phase-2b: patient-arm methylation upgrade via _read_patient_arm — no S3, fixture patches."""
    import pandas as pd
    from methods.functional_gene_state import read as fgs_read

    # Fixture patients: P-A, P-B, P-C, P-D (one per upgrade scenario)
    # P-A: wt genetic + methylated → epigenetic
    # P-B: monoallelic (GISTIC loss, no mutation) + methylated → biallelic+epigenetic
    # P-C: biallelic-genetic (homdel) + methylated → biallelic-genetic (genetic wins)
    # P-D: wt genetic + NOT methylated → wt (no regression)

    def _mc3(_t):
        # No mutations — all patients classified by CN only
        return pd.DataFrame(
            columns=["Hugo_Symbol", "Variant_Classification", "Tumor_Sample_Barcode", "Chromosome", "Start_Position"]
        )

    def _gistic(_t):
        # P-A: neutral (GISTIC 0), P-B: loss (GISTIC -1), P-C: homdel (GISTIC -2), P-D: neutral
        # Keys are aliquot barcodes (truncated to patient in the arm)
        return {
            "TCGA-01-AAAA-01": 0,  # P-A: neutral
            "TCGA-02-BBBB-01": -1,  # P-B: single-copy loss
            "TCGA-03-CCCC-01": -2,  # P-C: homozygous deletion
            "TCGA-04-DDDD-01": 0,  # P-D: neutral
        }

    def _sample_ct():
        # map patient barcodes → cancer type matching the indication
        return {
            "TCGA-01-AAAA": "KIRC",
            "TCGA-02-BBBB": "KIRC",
            "TCGA-03-CCCC": "KIRC",
            "TCGA-04-DDDD": "KIRC",
        }

    def _segs_cached():
        return None  # no ABSOLUTE segments; LOH will be None for all patients

    def _meth(_t, _ind):
        return {
            "TCGA-01-AAAA": True,  # P-A: methylated
            "TCGA-02-BBBB": True,  # P-B: methylated
            "TCGA-03-CCCC": True,  # P-C: methylated (but genetic already biallelic)
            # P-D deliberately absent → is_methylated = None → no upgrade
        }

    orig_mc3 = fgs_read._read_mc3_gene
    orig_gistic = fgs_read._read_gistic_gene
    orig_sct = fgs_read._load_sample_cancer_types
    orig_segs = fgs_read._absolute_segments_cached
    orig_meth = fgs_read._read_patient_methylation
    # clear lru_cache on the functions we're replacing
    fgs_read._load_sample_cancer_types.cache_clear()
    fgs_read._absolute_segments_cached.cache_clear()

    try:
        fgs_read._read_mc3_gene = _mc3
        fgs_read._read_gistic_gene = _gistic
        fgs_read._load_sample_cancer_types = _sample_ct
        fgs_read._absolute_segments_cached = _segs_cached
        fgs_read._read_patient_methylation = _meth
        # force the LIVE full-object path (this test patches live-path internals; the
        # product path would shadow them). Mirrors test_two_hit_product_readpath's fallback.
        orig_two_hit = fgs_read._read_two_hit_evidence
        fgs_read._read_two_hit_evidence = lambda _t: None

        result = fgs_read._read_patient_arm("TESTGENE", "KIRC")
    finally:
        fgs_read._read_mc3_gene = orig_mc3
        fgs_read._read_gistic_gene = orig_gistic
        fgs_read._load_sample_cancer_types = orig_sct
        fgs_read._absolute_segments_cached = orig_segs
        fgs_read._read_patient_methylation = orig_meth
        fgs_read._read_two_hit_evidence = orig_two_hit
        fgs_read._load_sample_cancer_types.cache_clear()
        fgs_read._absolute_segments_cached.cache_clear()

    counts = result["state_counts"]
    assert counts["epigenetic"] == 1, "P-A: wt + meth → epigenetic"
    assert counts["biallelic+epigenetic"] == 1, "P-B: monoallelic + meth → biallelic+epigenetic"
    assert counts["biallelic-genetic"] == 1, "P-C: homdel + meth → biallelic-genetic (genetic wins)"
    assert counts["wt"] == 1, "P-D: neutral + no meth → wt"
    assert result["methylation_source"] == "pancanatlas_hm450_promoter_v1"


def test_patient_methylation_graceful_degradation():
    """When HM450 parquet is unavailable (_read_patient_methylation returns {}), states are unchanged."""
    import pandas as pd
    from methods.functional_gene_state import read as fgs_read

    def _mc3(_t):
        return pd.DataFrame(
            columns=["Hugo_Symbol", "Variant_Classification", "Tumor_Sample_Barcode", "Chromosome", "Start_Position"]
        )

    def _gistic(_t):
        return {"TCGA-01-AAAA-01": 0, "TCGA-02-BBBB-01": -1}

    def _sample_ct():
        return {"TCGA-01-AAAA": "KIRC", "TCGA-02-BBBB": "KIRC"}

    def _segs_cached():
        return None

    def _no_meth(_t, _ind):
        return {}  # parquet not available

    orig_mc3 = fgs_read._read_mc3_gene
    orig_gistic = fgs_read._read_gistic_gene
    orig_sct = fgs_read._load_sample_cancer_types
    orig_segs = fgs_read._absolute_segments_cached
    orig_meth = fgs_read._read_patient_methylation
    fgs_read._load_sample_cancer_types.cache_clear()
    fgs_read._absolute_segments_cached.cache_clear()

    try:
        fgs_read._read_mc3_gene = _mc3
        fgs_read._read_gistic_gene = _gistic
        fgs_read._load_sample_cancer_types = _sample_ct
        fgs_read._absolute_segments_cached = _segs_cached
        fgs_read._read_patient_methylation = _no_meth
        orig_two_hit = fgs_read._read_two_hit_evidence
        fgs_read._read_two_hit_evidence = lambda _t: None

        result = fgs_read._read_patient_arm("TESTGENE", "KIRC")
    finally:
        fgs_read._read_mc3_gene = orig_mc3
        fgs_read._read_gistic_gene = orig_gistic
        fgs_read._load_sample_cancer_types = orig_sct
        fgs_read._absolute_segments_cached = orig_segs
        fgs_read._read_patient_methylation = orig_meth
        fgs_read._read_two_hit_evidence = orig_two_hit
        fgs_read._load_sample_cancer_types.cache_clear()
        fgs_read._absolute_segments_cached.cache_clear()

    counts = result["state_counts"]
    # No methylation data → pure genetic states, no epigenetic upgrades
    assert counts.get("epigenetic", 0) == 0
    assert counts.get("biallelic+epigenetic", 0) == 0
    assert counts["wt"] == 1  # P-A: neutral, no mutation → wt
    assert counts["monoallelic"] == 1  # P-B: single-copy loss, no mutation → monoallelic
    assert result["methylation_source"] is None


# ── M1: CCLE RRBS column → ModelID join (punctuated display names must resolve) ─────────────────
import gzip  # noqa: E402
import io  # noqa: E402
import methods.functional_gene_state.read as _fgs_read  # noqa: E402

# A Model.csv whose display CellLineName is PUNCTUATED ("NCI-H2126", "DMS 53"); the RRBS columns are
# the CCLE-style CELLLINE_TISSUE form ("NCIH2126_LUNG"). The prior code keyed the bridge on the
# punctuated CellLineName and looked it up with col.split("_")[0] ("NCIH2126") → never matched.
_MODEL_CSV = (
    "ModelID,CellLineName,StrippedCellLineName,CCLEName,OncotreeLineage\n"
    "ACH-000001,NCI-H2126,NCIH2126,NCIH2126_LUNG,Lung\n"
    "ACH-000002,DMS 53,DMS53,DMS53_LUNG,Lung\n"
)
_RRBS_TSV = (
    "locus_id\tCpG_sites_hg19\tavg_coverage\tNCIH2126_LUNG\tDMS53_LUNG\nTP53_17_7571720_7572720\t12\t30\t0.85\t0.05\n"
)


def _fake_s3_read_bytes(key: str) -> bytes:
    if key == _fgs_read.DEPMAP_MODEL_KEY:
        return _MODEL_CSV.encode()
    if key == _fgs_read.CCLE_RRBS_KEY:
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
            gz.write(_RRBS_TSV.encode())
        return buf.getvalue()
    raise AssertionError(f"unexpected key {key}")


def test_ccle_colname_bridge_resolves_punctuated_names(monkeypatch):
    monkeypatch.setattr(_fgs_read, "_s3_read_bytes", _fake_s3_read_bytes)
    _fgs_read._load_ccle_colname_to_model_id.cache_clear()
    m = _fgs_read._load_ccle_colname_to_model_id()
    # PRIMARY: full CCLE-style column resolves.
    assert m["NCIH2126_LUNG"] == "ACH-000001"
    assert m["DMS53_LUNG"] == "ACH-000002"
    # FALLBACK: the stripped alnum fragment (col.split("_")[0]) also resolves.
    assert m["NCIH2126"] == "ACH-000001"
    assert m["DMS53"] == "ACH-000002"
    _fgs_read._load_ccle_colname_to_model_id.cache_clear()


def test_read_model_methylation_maps_column_to_model_id(monkeypatch):
    """End-to-end: a punctuated-name cell line's RRBS column maps to its ModelID and thresholds
    correctly. Directly exercises the M1 fix (other tests monkeypatch _read_model_methylation whole)."""
    # Force the LIVE gzip path: the precomputed-product fast path is tried first, so stub it absent
    # (else this offline test would attempt a real S3 parquet read of the ccle-rrbs product).
    monkeypatch.setattr(_fgs_read, "_read_model_methylation_product", lambda *a, **k: None)
    monkeypatch.setattr(_fgs_read, "_s3_read_bytes", _fake_s3_read_bytes)
    _fgs_read._load_ccle_colname_to_model_id.cache_clear()
    out = _fgs_read._read_model_methylation("TP53")
    assert out == {"ACH-000001": True, "ACH-000002": False}  # 0.85 > 0.30 methylated; 0.05 not
    _fgs_read._load_ccle_colname_to_model_id.cache_clear()
