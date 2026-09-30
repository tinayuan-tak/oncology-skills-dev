"""audit: drift/reuse counts, symbol-join-loss population, coverage denominators.

Every count is derived by hand from the raw fixture (tests/.../_fixtures.py) and
asserted exactly, so a change in the flag logic that shifts a denominator fails
here rather than sliding into the published report.

Fixture population (6 rows survive the symbol_canonical restriction):
  ENSG00000133703 KRAS/KRAS        both, clean
  ENSG00000000460 FIRRM/C1orf112   both, DRIFT
  ENSG00000225746 MEG8/SNHG23      both, DRIFT + reuse (v116 MEG8 vs v23 258399)
  ENSG00000258399 (—)/MEG8         both, reuse (v23 MEG8 vs v116 225746), no HGNC
  ENSG00000222222 BARONLY/(—)      ens116-only
  ENSG00000111111 (—)/FOOONLY      v23-only, no HGNC
  ENSG00000333333                  dropped (no symbol in either source)
"""

from __future__ import annotations

from onc_methods.gene_id_authority.audit import (
    audit_authority,
    coverage_report,
    full_report,
    symbol_join_loss,
)
from onc_methods.gene_id_authority.build import build_authority

from ._fixtures import write_sources


def _authority(tmp_path):
    ens, v23 = write_sources(tmp_path)
    return build_authority(ens, v23)


def test_audit_counts(tmp_path):
    a = audit_authority(_authority(tmp_path))
    assert a["n_genes"] == 6
    assert a["n_in_both_sources"] == 4
    assert a["n_ensembl116_only"] == 1
    assert a["n_gencode_v23_only"] == 1
    assert a["n_symbol_drift"] == 2  # 460, 225746
    assert a["n_symbol_reuse_conflict"] == 2  # 225746, 258399 (MEG8 fusion)
    assert a["n_symbol_reassigned_disjoint"] == 1  # MEG8 only (KRAS shares a gene)
    assert a["n_no_hgnc_symbol"] == 2  # 111111, 258399


def test_symbol_join_loss_population(tmp_path):
    loss = symbol_join_loss(_authority(tmp_path))
    assert loss["n_comparable_both_substrates"] == 4
    assert loss["n_dropped_by_symbol_drift"] == 2
    assert loss["n_at_risk_symbol_reuse"] == 2
    # Exactly one clean reassignment illustration: MEG8 → different gene per release.
    assert len(loss["reassignment_examples"]) == 1
    ex = loss["reassignment_examples"][0]
    assert ex["symbol"] == "MEG8"
    assert ex["gencode_v23_gene_id"] == ["ENSG00000258399"]
    assert ex["ensembl116_gene_id"] == ["ENSG00000225746"]


def test_coverage_report_denominators(tmp_path):
    cov = coverage_report(_authority(tmp_path))
    assert cov["ensembl116"]["n_native_genes"] == 5
    assert cov["ensembl116"]["n_with_hgnc_symbol"] == 4
    assert cov["ensembl116"]["n_shared_with_gencode_v23"] == 4
    assert cov["gencode_v23"]["n_native_genes"] == 5
    assert cov["gencode_v23"]["n_shared_with_ensembl116"] == 4
    assert cov["gencode_v23"]["n_absent_from_ensembl116"] == 1


def test_full_report_is_json_serialisable(tmp_path):
    import json

    rep = full_report(_authority(tmp_path))
    # All values must be plain python ints/lists/dicts (no numpy) → round-trips.
    round_tripped = json.loads(json.dumps(rep))
    assert set(round_tripped) == {"authority_audit", "symbol_join_loss", "coverage"}
