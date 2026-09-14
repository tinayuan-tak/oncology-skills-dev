"""Synthetic-data tests for the shed_ectodomain_liability reader (no S3).

Validates: (1) the two-tier classifier (curated clinical > HPA secretome proxy >
membrane-retained > indeterminate) at each band; (2) the curated tier RESCUES shed
receptors that the HPA proxy misses (ERBB2/CEACAM5 have no HPA secretome value yet
are clinically_shed) — the false-negative the design exists to prevent; (3) the
indeterminate (read, no evidence either way) vs data_unavailable (couldn't read)
distinction; (4) the card-contract field set; (5) opposing-not-killer discipline
(the reader is agnostic to the signal, but the class it emits must be one the
opposing rules key on). Classifier + curated lookup are pure — most assertions need
no file. The HPA tier uses a tiny synthetic TSV.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Portable repo root: was hardcoded to the author's /home/sagemaker-user checkout, so every
# path guard below read as "data missing" on a CI runner or in a worktree.
METHODS_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(METHODS_REPO))
from methods.shed_ectodomain_liability import cli as sc  # noqa: E402
from methods.shed_ectodomain_liability import read as sc_read  # noqa: E402

# --- classifier (pure) ----------------------------------------------------


def test_classify_clinical_beats_everything():
    # a curated entry present → clinically_shed regardless of HPA
    entry = {"serum_marker": "CA125", "shed_product": "soluble CA125"}
    assert sc.classify_shed(entry, {"found": True, "secretome_location": None}) == "clinically_shed"
    assert sc.classify_shed(entry, {"found": False}) == "clinically_shed"


def test_classify_secretome_proxy_when_no_curated_but_hpa_secreted():
    hpa_blood = {"found": True, "secretome_location": "Secreted to blood", "secreted_systemic": True}
    hpa_local = {"found": True, "secretome_location": "Secreted to digestive system", "secreted_local": True}
    assert sc.classify_shed(None, hpa_blood) == "secretome_proxy_shed"
    assert sc.classify_shed(None, hpa_local) == "secretome_proxy_shed"


def test_classify_membrane_retained_when_hpa_has_gene_no_secretion():
    hpa = {"found": True, "secretome_location": None, "secreted_systemic": False, "secreted_local": False}
    assert sc.classify_shed(None, hpa) == "not_shed_membrane_retained"


def test_classify_indeterminate_when_no_evidence_either_way():
    # gene not in curated vocab AND not in HPA at all → cannot tell (NOT not_shed)
    hpa = {"found": False, "secretome_location": None}
    assert sc.classify_shed(None, hpa) == "indeterminate"


# --- curated tier lookup (pure; against the real vocab) --------------------


def test_curated_tier_covers_canonical_shed_antigens():
    """MUC16/MUC1/MSLN/ERBB2/CEACAM5 must all be in the curated clinical tier."""
    v = sc.load_shed_vocab()  # reads target-contracts/vocabularies/shed_antigen_targets.yaml
    for g in ("MUC16", "MUC1", "MSLN", "ERBB2", "MET", "CEACAM5", "FOLR1"):
        entry = sc.lookup_clinical_shed(g, vocab=v)
        assert entry is not None, f"{g} must be a curated clinically_shed antigen"
        assert entry.get("serum_marker"), f"{g} curated entry must name a serum marker"
        assert entry.get("primary_source_citation"), f"{g} curated entry must cite a source"


def test_curated_lookup_is_case_insensitive_and_misses_gracefully():
    v = sc.load_shed_vocab()
    assert sc.lookup_clinical_shed("muc16", vocab=v) is not None
    assert sc.lookup_clinical_shed("KRAS", vocab=v) is None


# --- the FALSE-NEGATIVE-PREVENTION test (the reason two tiers exist) -------


def test_curated_tier_rescues_shed_receptors_hpa_misses(tmp_path):
    """ERBB2 + CEACAM5 have NO HPA secretome annotation (verified live 2026-07-19),
    yet are clinically shed. A single-source (HPA-only) reader would call them
    not_shed. The curated tier must rescue them to clinically_shed."""
    hpa_tsv = _write_hpa_tsv(tmp_path)  # ERBB2/CEACAM5 rows have empty Secretome location
    for g in ("ERBB2", "CEACAM5"):
        out = sc.load_and_classify(g, hpa_path=hpa_tsv)
        assert out["shed_liability_class"] == "clinically_shed", (
            f"{g} is clinically shed but HPA has no secretome value — curated tier must rescue it"
        )
        assert out["shed_evidence_tier"] == "clinical"


# --- HPA proxy tier (synthetic TSV) ---------------------------------------


def _write_hpa_tsv(tmp_path):
    p = tmp_path / "proteinatlas_mini.tsv"
    cols = [sc.HPA_GENE_COL, sc.HPA_UNIPROT_COL, sc.HPA_SECRETOME_COL]
    rows = [
        ["MUC13", "Q9H3R2", "Secreted to digestive system"],  # uncurated, HPA-secreted → proxy
        ["ERBB2", "P04626", ""],  # curated shed RTK, HPA blank
        ["CEACAM5", "P06731", ""],  # curated shed, HPA blank
        ["KRAS", "P01116", ""],  # non-shed, HPA has it blank
        ["SFTPB", "P07988", "Secreted to blood"],  # uncurated blood-secreted → proxy
    ]
    with open(p, "w") as fh:
        fh.write("\t".join(cols) + "\n")
        for r in rows:
            fh.write("\t".join(r) + "\n")
    return str(p)


def test_uncurated_hpa_secreted_gene_is_secretome_proxy(tmp_path):
    hpa = _write_hpa_tsv(tmp_path)
    out = sc.load_and_classify("MUC13", hpa_path=hpa)
    assert out["shed_liability_class"] == "secretome_proxy_shed"
    assert out["shed_evidence_tier"] == "secretome_proxy"
    assert out["serum_marker"] is None  # not curated → no clinical marker
    assert out["hpa_secretome_location"] == "Secreted to digestive system"


def test_uncurated_blank_hpa_gene_is_membrane_retained(tmp_path):
    hpa = _write_hpa_tsv(tmp_path)
    out = sc.load_and_classify("KRAS", hpa_path=hpa)
    assert out["shed_liability_class"] == "not_shed_membrane_retained"


def test_gene_absent_from_hpa_and_vocab_is_indeterminate(tmp_path):
    hpa = _write_hpa_tsv(tmp_path)
    out = sc.load_and_classify("ZZZ_NOT_A_GENE", hpa_path=hpa)
    assert out["shed_liability_class"] == "indeterminate", (
        "absent from both tiers = coverage gap, NOT a determination of not-shed"
    )


# --- card-contract fields --------------------------------------------------


def test_card_contract_fields_present(tmp_path):
    hpa = _write_hpa_tsv(tmp_path)
    out = sc.load_and_classify("MUC13", hpa_path=hpa)
    for f in (
        "shed_liability_class",
        "shed_evidence_tier",
        "serum_marker",
        "shed_product",
        "shedding_protease",
        "hpa_secretome_location",
        "source_citation",
        "method_version",
    ):
        assert f in out, f"card-contract field missing: {f}"


def test_emitted_class_is_in_card_vocabulary(tmp_path):
    hpa = _write_hpa_tsv(tmp_path)
    valid = {"clinically_shed", "secretome_proxy_shed", "not_shed_membrane_retained", "indeterminate"}
    for g in ("ERBB2", "MUC13", "KRAS", "ZZZ_NOT_A_GENE"):
        out = sc.load_and_classify(g, hpa_path=hpa)
        assert out["shed_liability_class"] in valid


# --- graceful degradation (the dispatcher entry) --------------------------


def test_read_target_summary_graceful_on_unreadable_source(monkeypatch):
    """If the sources can't be loaded, read_target_summary must return
    data_unavailable + _live_read_error — NOT raise. Distinct from indeterminate
    (a successful read of an absent gene)."""

    def _boom(*a, **k):
        raise RuntimeError("s3 unreachable")

    monkeypatch.setattr(sc, "load_and_classify", _boom)
    out = sc_read.read_target_summary(target="MUC16", indication="OV")
    assert out["shed_liability_class"] == "data_unavailable"
    assert out["_live_read_error"] == "shed_ectodomain_read_failed"
