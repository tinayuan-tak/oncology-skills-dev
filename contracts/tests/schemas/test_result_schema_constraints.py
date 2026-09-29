"""Schema-design constraint tests (defect register findings A, B, D).

Finding A — dependency-depmap-chronos: `is_pan_cancer_essential` (a >80%-of-
  lineages gene-level rollup) and `is_lineage_selective_dependency` (selective in
  THIS lineage) are logically mutually exclusive but were unconstrained, so a
  payload could assert both. Added a top-level `not` that rejects both-true.

Finding B — perturbation-prism-viability: `median_log_viability_across_compounds`
  was a required `number` with no valid value when `n_compounds_for_target=0`
  (no compound×cell-line pairs to aggregate). Now nullable, enforced null at n=0
  and numeric at n>0 via if/then/else.

Finding D — dependency-depmap-chronos top_codependencies: `partner_hgnc_id` was
  `pattern:^HGNC:[0-9]+$` and required, rejecting DepMap pseudogenes/readthroughs
  that lack a registered HGNC ID. Now nullable (pattern still enforced when set).
"""

import json
from pathlib import Path

import jsonschema

REPO = Path(__file__).resolve().parents[2]
CHRONOS = json.loads((REPO / "schemas" / "products" / "dependency-depmap-chronos.result.schema.json").read_text())
PRISM = json.loads((REPO / "schemas" / "products" / "perturbation-prism-viability.result.schema.json").read_text())

V = jsonschema.Draft202012Validator


def _valid(schema, instance):
    return not list(V(schema).iter_errors(instance))


# ---------------------------------------------------------------------------
# Finding A — pan-essential ⊕ lineage-selective mutual exclusion
# ---------------------------------------------------------------------------


def _chronos_base(**over):
    inst = {
        "chronos_score_median": -1.2,
        "chronos_score_n_lines": 30,
        "lineage_selectivity_zscore": -2.0,
        "is_lineage_selective_dependency": True,
    }
    inst.update(over)
    return inst


def test_A_both_true_rejected():
    """A gene cannot be both pan-cancer-essential AND lineage-selective."""
    inst = _chronos_base(is_lineage_selective_dependency=True, is_pan_cancer_essential=True)
    assert not _valid(CHRONOS, inst), "both-true must be rejected (Finding A)"


def test_A_lineage_selective_only_ok():
    """The common case — is_pan_cancer_essential absent — stays valid."""
    inst = _chronos_base(is_lineage_selective_dependency=True)
    assert "is_pan_cancer_essential" not in inst
    assert _valid(CHRONOS, inst)


def test_A_one_true_ok():
    """Both keys present but only one true is a legitimate combination."""
    assert _valid(CHRONOS, _chronos_base(is_lineage_selective_dependency=True, is_pan_cancer_essential=False))
    assert _valid(CHRONOS, _chronos_base(is_lineage_selective_dependency=False, is_pan_cancer_essential=True))


def test_A_both_false_ok():
    """Both present and both false is valid (neither call fires)."""
    assert _valid(CHRONOS, _chronos_base(is_lineage_selective_dependency=False, is_pan_cancer_essential=False))


# ---------------------------------------------------------------------------
# Finding D — nullable partner_hgnc_id for pseudogenes/readthroughs
# ---------------------------------------------------------------------------


def test_D_null_partner_hgnc_id_ok():
    """A co-dependency partner lacking a registered HGNC ID sets it to null."""
    inst = _chronos_base(
        top_codependencies=[
            {"partner_gene_symbol": "SOME-READTHROUGH", "partner_hgnc_id": None, "pearson_r": 0.42},
        ]
    )
    assert _valid(CHRONOS, inst), "null partner_hgnc_id must validate (Finding D)"


def test_D_valid_hgnc_id_ok():
    """A registered HGNC ID still validates."""
    inst = _chronos_base(
        top_codependencies=[
            {"partner_gene_symbol": "EGFR", "partner_hgnc_id": "HGNC:3236", "pearson_r": 0.6},
        ]
    )
    assert _valid(CHRONOS, inst)


def test_D_malformed_hgnc_id_still_rejected():
    """A non-null, non-matching string is still rejected (pattern enforced)."""
    inst = _chronos_base(
        top_codependencies=[
            {"partner_gene_symbol": "X", "partner_hgnc_id": "notanid", "pearson_r": 0.4},
        ]
    )
    assert not _valid(CHRONOS, inst)


# ---------------------------------------------------------------------------
# Finding B — median nullable iff n_compounds_for_target == 0
# ---------------------------------------------------------------------------


def test_B_zero_compounds_requires_null_median():
    """n=0 → median must be null (no pairs to aggregate)."""
    assert _valid(PRISM, {"n_compounds_for_target": 0, "median_log_viability_across_compounds": None})


def test_B_zero_compounds_numeric_median_rejected():
    """n=0 with a numeric median is a contradiction — rejected."""
    assert not _valid(PRISM, {"n_compounds_for_target": 0, "median_log_viability_across_compounds": -0.3})


def test_B_nonzero_compounds_requires_numeric_median():
    """n>0 → median must be a real number."""
    assert _valid(PRISM, {"n_compounds_for_target": 2, "median_log_viability_across_compounds": -0.3})


def test_B_nonzero_compounds_null_median_rejected():
    """n>0 with a null median is missing data — rejected."""
    assert not _valid(PRISM, {"n_compounds_for_target": 2, "median_log_viability_across_compounds": None})


# ---------------------------------------------------------------------------
# Finding E — requires_subgroup declared on every product (vocab-level)
# ---------------------------------------------------------------------------


def test_E_every_product_declares_requires_subgroup():
    """RP/Finding E: requires_subgroup is a standard field on every product."""
    import yaml

    products = yaml.safe_load((REPO / "vocabularies" / "products.yaml").read_text())["products"]
    missing = [p["id"] for p in products if "requires_subgroup" not in p]
    assert not missing, f"products missing requires_subgroup: {missing}"
