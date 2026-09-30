"""product: resolve a symbol-keyed dge_deseq2 product onto the authority gene_id.

This is the capability the S3c cross-substrate concordance QC (#732) consumes so
it can join recount3 and Xena/Toil products on the STABLE Ensembl id instead of
the drifting/reused symbol string, WITHOUT rewiring the R loaders.

Mutation teeth: an empty / all-unresolved product must RAISE, not return a
silently unmapped frame. Fixtures store the RAW SOURCE text and RE-DERIVE the
authority via build_authority (a pre-computed authority blob could never fail).
"""

from __future__ import annotations

import pandas as pd
import pytest

from onc_methods.gene_id_authority.build import build_authority
from onc_methods.gene_id_authority.product import (
    annotate_product_with_gene_id,
    resolve_symbols_to_gene_ids,
)

from ._fixtures import write_sources


@pytest.fixture
def authority(tmp_path):
    ens, v23 = write_sources(tmp_path)
    return build_authority(ens, v23)


# --- recount3 keys on symbol_hgnc; Xena/Toil keys on symbol_gencode_v23 ------


def test_recount3_clean_symbol_resolves_1to1(authority):
    res = resolve_symbols_to_gene_ids(["KRAS"], "recount3", authority).iloc[0]
    assert res["gene_id"] == "ENSG00000133703"
    assert res["mapped"] and not res["ensg_ambiguous"]
    assert res["n_authority_genes"] == 1
    assert not res["symbol_drift"] and not res["symbol_reuse_conflict"]


def test_drift_symbol_resolves_by_substrate_namespace(authority):
    """ENSG00000000460 is FIRRM in v116 (recount3) but C1orf112 in v23 (Toil).
    Each substrate's own symbol resolves to the SAME stable gene_id, and the row
    is flagged drift — the signal that a symbol-string join would have dropped
    it but the gene_id join recovers it."""
    r3 = resolve_symbols_to_gene_ids(["FIRRM"], "recount3", authority).iloc[0]
    toil = resolve_symbols_to_gene_ids(["C1orf112"], "xena_toil", authority).iloc[0]
    assert r3["gene_id"] == toil["gene_id"] == "ENSG00000000460"
    assert r3["symbol_drift"] and toil["symbol_drift"]
    # The other substrate's symbol is NOT in this substrate's namespace:
    assert not resolve_symbols_to_gene_ids(["C1orf112"], "recount3", authority).iloc[0]["mapped"]


def test_reuse_symbol_maps_to_DIFFERENT_genes_per_substrate(authority):
    """'MEG8' is a reused string: v116 gene ENSG...225746, v23 gene ENSG...258399.
    Resolving per substrate keeps them distinct (a symbol join would fuse them),
    and both carry the reuse flag."""
    r3 = resolve_symbols_to_gene_ids(["MEG8"], "recount3", authority).iloc[0]
    toil = resolve_symbols_to_gene_ids(["MEG8"], "xena_toil", authority).iloc[0]
    assert r3["gene_id"] == "ENSG00000225746"
    assert toil["gene_id"] == "ENSG00000258399"
    assert r3["gene_id"] != toil["gene_id"]
    assert r3["symbol_reuse_conflict"] and toil["symbol_reuse_conflict"]


def test_unmapped_symbol_flagged_not_dropped(authority):
    res = resolve_symbols_to_gene_ids(["NOT_A_GENE"], "recount3", authority).iloc[0]
    assert not res["mapped"]
    assert pd.isna(res["gene_id"])
    assert res["n_authority_genes"] == 0
    assert pd.isna(res["symbol_drift"])


# --- within-substrate collapse: a symbol backing >1 gene has NO single id ----


def _write_par_sources(tmp_path):
    """A raw source pair where one HGNC symbol backs TWO distinct gene ids in the
    v116 namespace (a PAR-style shared symbol). Stored raw + re-derived so the
    ambiguous branch is exercised on real build output, and the shared fixtures'
    hardcoded sibling-test counts stay untouched."""
    ens = tmp_path / "ens_par.tsv"
    v23 = tmp_path / "v23_par.probemap"
    ens.write_text(
        "Gene stable ID\tGene stable ID version\tHGNC ID\tHGNC symbol\tGene name\n"
        "ENSG00000182162\tENSG00000182162.11\tHGNC:1\tP2RY8\tP2RY8\n"
        "ENSG00000185960\tENSG00000185960.14\tHGNC:1\tP2RY8\tP2RY8\n"  # same symbol, distinct gene
        "ENSG00000133703\tENSG00000133703.13\tHGNC:6407\tKRAS\tKRAS\n"  # clean control
    )
    v23.write_text(
        "id\tgene\tchrom\tchromStart\tchromEnd\tstrand\nENSG00000133703.11\tKRAS\tchr12\t25205246\t25250929\t-\n"
    )
    return ens, v23


def test_collapsed_symbol_is_ambiguous_not_fabricated(tmp_path):
    ens, v23 = _write_par_sources(tmp_path)
    auth = build_authority(ens, v23)
    res = resolve_symbols_to_gene_ids(["P2RY8", "KRAS"], "recount3", auth).set_index("gene_symbol")
    assert res.loc["P2RY8", "n_authority_genes"] == 2
    assert res.loc["P2RY8", "ensg_ambiguous"]
    assert res.loc["P2RY8", "mapped"]  # present, just not uniquely
    assert pd.isna(res.loc["P2RY8", "gene_id"])  # NEVER a first-seen fabricated id
    assert res.loc["KRAS", "gene_id"] == "ENSG00000133703"
    assert not res.loc["KRAS", "ensg_ambiguous"]


# --- annotate_product_with_gene_id: additive columns + order + fail-loud -----


def test_annotate_preserves_product_and_adds_columns(authority):
    product = pd.DataFrame(
        {"gene_symbol": ["KRAS", "FIRRM", "NOT_A_GENE"], "log2fc_A": [1.0, -2.0, 0.3], "padj_A": [1e-5, 1e-3, 0.9]}
    )
    out = annotate_product_with_gene_id(product, "recount3", authority)
    # original columns + rows untouched, order preserved
    assert list(out["gene_symbol"]) == ["KRAS", "FIRRM", "NOT_A_GENE"]
    assert list(out["log2fc_A"]) == [1.0, -2.0, 0.3]
    assert list(out["gene_id"])[:2] == ["ENSG00000133703", "ENSG00000000460"]
    assert pd.isna(out["gene_id"].iloc[2])
    for col in ("gene_id", "n_authority_genes", "mapped", "ensg_ambiguous", "symbol_drift", "symbol_reuse_conflict"):
        assert col in out.columns


def test_annotate_empty_product_raises(authority):
    empty = pd.DataFrame({"gene_symbol": []})
    with pytest.raises(ValueError, match="degenerate"):
        annotate_product_with_gene_id(empty, "recount3", authority)


def test_annotate_all_unresolved_raises(authority):
    """An id-keyed frame passed as symbol-keyed resolves NOTHING → must raise
    rather than return a silently unmapped product (the green-on-empty tooth)."""
    id_keyed = pd.DataFrame({"gene_symbol": ["ENSG00000133703", "ENSG00000000460"]})
    with pytest.raises(ValueError, match="degenerate"):
        annotate_product_with_gene_id(id_keyed, "recount3", authority)


def test_annotate_missing_symbol_col_raises(authority):
    with pytest.raises(ValueError, match="symbol_col"):
        annotate_product_with_gene_id(pd.DataFrame({"gene": ["KRAS"]}), "recount3", authority)


def test_unknown_substrate_raises(authority):
    with pytest.raises(ValueError, match="unknown substrate"):
        resolve_symbols_to_gene_ids(["KRAS"], "not_a_substrate", authority)
