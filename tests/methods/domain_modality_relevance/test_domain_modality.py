"""domain_modality_relevance — per-target domain→modality implication.

Tests the curated-override > class-driven-heuristic precedence with injected features/vocab
(hermetic; no S3 / UniProt read), pinning: RIPK1 scaffolding override (the roadmap #3 case), the
single-domain enzyme → inhibitor_sufficient rule, the multi-domain enzyme → INDETERMINATE rule
(v0.2.0: domain count is not a scaffolding-dependence proxy — EGFR/BTK/RTKs are inhibitor targets,
so the heuristic declines to guess rather than mislabel them removal_favored), non-catalytic class
→ removal_favored, and the data_unavailable coverage gap.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from methods.domain_modality_relevance import read as r  # noqa: E402


# --- curated override (highest precedence) --------------------------------

_VOCAB = {
    "RIPK1": {
        "protein_class": "kinase",
        "functional_domains": ["Protein kinase", "RHIM", "Death domain"],
        "preferred_mechanism": "removal_required_scaffolding",
        "mechanism_context": "RIPK1 kinase-independent scaffolding via RHIM + death domain.",
        "primary_source_doi": "10.1016/j.molcel.2017.05.003",
    },
}


def test_ripk1_curated_scaffolding_override():
    # RIPK1 is protein_class=kinase (heuristic would say inhibitor_sufficient), but the curated
    # scaffolding entry OVERRIDES → removal_required_scaffolding. This is the roadmap #3 case.
    feats = {"protein_class": ["kinase"], "n_domains": 1, "protein_features_class": "single_domain"}
    out = r.domain_modality_for_gene("RIPK1", features=feats, vocab=_VOCAB)
    assert out["modality_implication_class"] == "removal_required_scaffolding"
    assert out["modality_implication_basis"] == "curated"
    assert out["scaffolding_function"] is True
    assert "kinase-independent" in out["modality_context"]
    assert out["_primary_source_doi"] == "10.1016/j.molcel.2017.05.003"


def test_curated_precedence_over_heuristic():
    # even with a rich multi-domain enzyme record, curated wins verbatim
    feats = {"protein_class": ["kinase"], "n_domains": 3, "protein_features_class": "multi_domain"}
    out = r.domain_modality_for_gene("ripk1", features=feats, vocab=_VOCAB)  # case-insensitive
    assert out["modality_implication_class"] == "removal_required_scaffolding"


# --- class-driven heuristic (non-curated) ---------------------------------


def test_single_domain_enzyme_is_inhibitor_sufficient():
    # a clean single-domain enzyme with no curated caveat → inhibitor_sufficient
    feats = {"protein_class": ["protease"], "n_domains": 1, "protein_features_class": "single_domain"}
    out = r.domain_modality_for_gene("SENP1", features=feats, vocab={})
    assert out["modality_implication_class"] == "inhibitor_sufficient"
    assert out["modality_implication_basis"] == "heuristic"
    assert out["scaffolding_function"] is None  # heuristic never ASSERTS scaffolding


def test_multi_domain_enzyme_is_indeterminate():
    # REGRESSION (v0.2.0): a multi-domain enzyme was formerly labelled removal_favored, which
    # mislabels well-drugged inhibitor targets (EGFR, BTK, most RTKs) as degrader-favored. Domain
    # count is not a valid scaffolding-dependence proxy → the heuristic now returns an honest
    # non-call (indeterminate); a curated entry is required to assert removal.
    feats = {"protein_class": ["kinase"], "n_domains": 3, "protein_features_class": "multi_domain"}
    out = r.domain_modality_for_gene("SOMEKINASE", features=feats, vocab={})
    assert out["modality_implication_class"] == "indeterminate"
    assert out["modality_implication_basis"] == "heuristic"
    assert out["scaffolding_function"] is None  # heuristic never ASSERTS scaffolding


def test_egfr_multi_domain_kinase_not_mislabelled_removal():
    # the concrete case the v0.2.0 fix targets: EGFR is a multi-domain RTK and a canonical INHIBITOR
    # target — it must NOT be called removal_favored by the class-driven heuristic.
    feats = {"protein_class": ["kinase"], "n_domains": 4, "protein_features_class": "multi_domain"}
    out = r.domain_modality_for_gene("EGFR", features=feats, vocab={})
    assert out["modality_implication_class"] == "indeterminate"
    assert out["modality_implication_class"] != "removal_favored"


def test_noncatalytic_class_is_removal_favored():
    # a transcription factor (no catalytic pocket) → removal_favored
    feats = {"protein_class": ["transcription_factor"], "n_domains": 2, "protein_features_class": "multi_domain"}
    out = r.domain_modality_for_gene("MYB", features=feats, vocab={})
    assert out["modality_implication_class"] == "removal_favored"


def test_no_features_is_data_unavailable():
    feats = {"protein_class": [], "n_domains": 0, "protein_features_class": "data_unavailable", "interpro_n_domains": 0}
    out = r.domain_modality_for_gene("NOPE", features=feats, vocab={})
    assert out["modality_implication_class"] == "data_unavailable"
    assert out["modality_implication_basis"] == "none"
    assert out["modality_context"] is None


def test_interpro_only_domain_is_indeterminate():
    # no curated FT DOMAIN + no mapped enzyme/non-enzyme class, but InterPro has domains. v0.2.0:
    # domains-present-but-no-catalytic-pocket is too weak to assert a removal call → indeterminate
    # (was removal_favored, an over-call). functional_domains still surfaced from InterPro.
    feats = {
        "protein_class": [],
        "n_domains": 0,
        "protein_features_class": "no_curated_domain",
        "interpro_n_domains": 2,
        "interpro_domain_names": ["Dom A", "Dom B"],
    }
    out = r.domain_modality_for_gene("GENEX", features=feats, vocab={})
    assert out["modality_implication_class"] == "indeterminate"
    assert out["functional_domains"] == ["Dom A", "Dom B"]
