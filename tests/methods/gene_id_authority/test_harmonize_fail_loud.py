"""harmonize: resolution + the load-bearing FAIL-LOUD join contract.

Mutation teeth (analysis-methods#699): an empty/degenerate join must RAISE, not
return 0 rows. Each test perturbs ONE axis (drop the version strip, disjoint id
sets, wrong column) and asserts the guard fires. The drift/reuse tests prove the
id-keyed join fixes exactly what the symbol join broke.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from methods.gene_id_authority.build import build_authority  # noqa: E402
from methods.gene_id_authority.harmonize import (  # noqa: E402
    coverage,
    join_on_authority,
    resolve_to_authority,
)

from ._fixtures import write_sources  # noqa: E402


@pytest.fixture
def authority(tmp_path):
    ens, v23 = write_sources(tmp_path)
    return build_authority(ens, v23)


def test_resolve_strips_version_and_flags_unmapped(authority):
    res = resolve_to_authority(["ENSG00000133703.13", "ENSG00000000460", "ENSG09999999999"], authority).set_index(
        "native_id"
    )
    assert res.loc["ENSG00000133703.13", "gene_id"] == "ENSG00000133703"  # versioned → stripped
    assert bool(res.loc["ENSG00000000460", "mapped"])
    assert not bool(res.loc["ENSG09999999999", "mapped"])  # unknown id


def test_coverage_denominators(authority):
    cov = coverage(["ENSG00000133703.13", "ENSG00000000460", "ENSG09999999999"], authority)
    assert cov["n_total"] == 3
    assert cov["n_mapped"] == 2
    assert cov["n_dropped"] == 1
    assert cov["dropped_sample"] == ["ENSG09999999999"]


def test_happy_path_join_on_id(authority):
    left = pd.DataFrame({"ensembl_id": ["ENSG00000133703.13", "ENSG00000000460.17"], "lfc": [1.0, -2.0]})
    right = pd.DataFrame({"gid": ["ENSG00000133703", "ENSG00000000460"], "lfc": [1.1, -1.9]})
    merged = join_on_authority(left, right, authority, left_on="ensembl_id", right_on="gid")
    assert set(merged["gene_id"]) == {"ENSG00000133703", "ENSG00000000460"}
    assert set(merged["symbol_canonical"]) == {"KRAS", "FIRRM"}


def test_empty_join_raises(authority):
    """Disjoint id sets → 0 shared → MUST raise, never a silent empty frame."""
    left = pd.DataFrame({"gid": ["ENSG00000133703"]})
    right = pd.DataFrame({"gid": ["ENSG00000000460"]})
    with pytest.raises(ValueError, match="degenerate"):
        join_on_authority(left, right, authority, left_on="gid", right_on="gid")


def test_min_shared_floor_raises(authority):
    left = pd.DataFrame({"gid": ["ENSG00000133703", "ENSG00000000460"]})
    right = pd.DataFrame({"gid": ["ENSG00000133703", "ENSG00000000460"]})
    # Two shared, but demand three → guard fires.
    with pytest.raises(ValueError, match="min_shared=3"):
        join_on_authority(left, right, authority, left_on="gid", right_on="gid", min_shared=3)


def test_wrong_id_column_raises(authority):
    left = pd.DataFrame({"gid": ["ENSG00000133703"]})
    right = pd.DataFrame({"gid": ["ENSG00000133703"]})
    with pytest.raises(ValueError, match="left_on"):
        join_on_authority(left, right, authority, left_on="not_a_col", right_on="gid")


def test_drift_gene_joins_on_id_not_symbol(authority):
    """ENSG00000000460 is C1orf112 in v23 but FIRRM in v116. A SYMBOL join would
    drop it; the id join keeps it. Simulate each substrate carrying its own
    native symbol and confirm the id join still pairs them."""
    recount3 = pd.DataFrame({"gene": ["FIRRM"], "gid": ["ENSG00000000460"]})  # v116 symbol
    toil = pd.DataFrame({"gene": ["C1orf112"], "gid": ["ENSG00000000460.17"]})  # v23 symbol
    # Symbol join would find nothing in common:
    assert set(recount3["gene"]).isdisjoint(set(toil["gene"]))
    # Id join recovers the gene:
    merged = join_on_authority(recount3, toil, authority, left_on="gid", right_on="gid")
    assert list(merged["gene_id"]) == ["ENSG00000000460"]


def test_reuse_not_fused_by_id_join(authority):
    """'MEG8' names DIFFERENT genes in v23 vs v116. A symbol join fuses them;
    the id join keeps ENSG...258399 and ENSG...225746 as separate rows."""
    toil = pd.DataFrame({"gid": ["ENSG00000258399", "ENSG00000225746"], "v": [1, 2]})
    recount3 = pd.DataFrame({"gid": ["ENSG00000258399", "ENSG00000225746"], "v": [3, 4]})
    merged = join_on_authority(toil, recount3, authority, left_on="gid", right_on="gid")
    assert len(merged) == 2
    assert set(merged["gene_id"]) == {"ENSG00000258399", "ENSG00000225746"}
