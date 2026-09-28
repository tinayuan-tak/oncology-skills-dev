"""Phase 2: control-benchmark position (fixture vocab + mocked percentiles, no S3).

Writes a tiny controls vocab + a stub indication_crosswalk into a tmp contracts dir, and
monkeypatches the Phase-1 percentile lookups, so the classification + indication-matched
exclusion + assembly logic is tested deterministically offline.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.tumor_presence_controls import read as CP  # noqa: E402


@pytest.fixture
def contracts(tmp_path):
    """A minimal target-contracts dir with the two vocabs the method reads."""
    voc = tmp_path / "vocabularies"
    voc.mkdir()
    (voc / "tumor_presence_controls.yaml").write_text(
        textwrap.dedent("""
        version: 9.9.9
        percentile_source: {tumor: allgene-tumor-rank-v1, cell_line: allgene-depmap-rank-26q1-v1}
        positive_controls:
          POS_HI: {role: tumor_antigen, applies: universal}
          POS_MID: {role: tumor_antigen, applies: universal}
        negative_controls:
          HK: {role: housekeeping, applies: universal}
          LUNGMARK: {role: lineage_marker, negative_except_lineage: Lung}
          SILENT: {role: silent, applies: universal}
    """)
    )
    (voc / "indication_crosswalk.yaml").write_text(
        textwrap.dedent("""
        indications:
          - {canonical_code: COADREAD, gtex_normal_tissue: Colon}
          - {canonical_code: NSCLC, gtex_normal_tissue: Lung}
    """)
    )
    # bust the lru_caches between tests (keyed on contracts_dir string)
    CP._load_controls.cache_clear()
    CP._load_crosswalk.cache_clear()
    return str(tmp_path)


# ---- indication-matched applicability ----
def test_lineage_marker_excluded_in_its_own_lineage(contracts):
    ctrls = CP._load_controls(contracts)
    # COLON indication → LUNGMARK stays applicable
    app, exc = CP._applicable_negatives(ctrls, "Colon")
    assert "LUNGMARK" in app and not exc
    # LUNG indication → LUNGMARK excluded (it's the lineage marker there)
    app, exc = CP._applicable_negatives(ctrls, "Lung")
    assert "LUNGMARK" not in app and "LUNGMARK" in exc
    # housekeeping + silent always applicable
    assert {"HK", "SILENT"}.issubset(app)


def test_indication_alias_resolves_tissue(contracts):
    # LUAD is not in the crosswalk directly; aliases → NSCLC → Lung.
    assert CP._indication_normal_tissue("LUAD", contracts) == "Lung"
    assert CP._indication_normal_tissue("COADREAD", contracts) == "Colon"
    assert CP._indication_normal_tissue("UNKNOWN_IND", contracts) is None


# ---- classification ----
def test_classify_above_all_positives():
    pos = {"POS_HI": 99.0, "POS_MID": 90.0}
    neg = {"SILENT": {"pct": 10.0, "role": "silent"}, "HK": {"pct": 99.9, "role": "housekeeping"}}
    assert CP._classify_control_position(99.5, pos, neg) == "above_all_positives"


def test_classify_within_positives():
    pos = {"POS_HI": 99.0, "POS_MID": 90.0}
    neg = {"SILENT": {"pct": 10.0, "role": "silent"}}
    assert CP._classify_control_position(92.0, pos, neg) == "within_positives"


def test_classify_above_negatives_below_positives():
    pos = {"POS_HI": 99.0, "POS_MID": 90.0}
    neg = {"SILENT": {"pct": 10.0, "role": "silent"}}
    assert CP._classify_control_position(50.0, pos, neg) == "above_negatives_below_positives"


def test_classify_below_negatives_uses_nonhousekeeping_floor():
    # a target below the SILENT floor is below_negatives; housekeeping ceiling is NOT the floor
    pos = {"POS_HI": 99.0}
    neg = {"SILENT": {"pct": 20.0, "role": "silent"}, "HK": {"pct": 99.9, "role": "housekeeping"}}
    assert CP._classify_control_position(15.0, pos, neg) == "below_negatives"
    # a target ABOVE the silent floor but below housekeeping is NOT below_negatives
    assert CP._classify_control_position(50.0, pos, neg) == "above_negatives_below_positives"


def test_classify_data_unavailable_when_target_none():
    assert CP._classify_control_position(None, {"P": 99.0}, {}) == "data_unavailable"


# ---- end-to-end assembly (mocked percentiles) ----
def _wire_percentiles(monkeypatch, pct_map):
    """Patch the tumor lookup so each symbol returns a fixed percentile."""
    import methods.allgene_percentile_precompute.lookup as _lk

    def _fake(ensembl_ids, studies, cutoffs=None, source="tcga_tumor"):
        # the method calls _symbol_to_ensembl_ids first; we instead key on a sentinel the
        # test injects via _symbol_to_ensembl_ids → [SYMBOL]
        sym = ensembl_ids[0] if ensembl_ids else None
        pct = pct_map.get(sym)
        return {"allgene_percentile": pct, "allgene_percentile_class": "top_1pct" if (pct or 0) >= 99 else "mid"}

    monkeypatch.setattr(_lk, "tumor_allgene_percentile", _fake)
    # make _symbol_to_ensembl_ids return [SYMBOL] so the fake keys on the symbol
    from methods.tcga_gtex_expression_distribution import read as _R

    monkeypatch.setattr(_R, "_symbol_to_ensembl_ids", lambda s: [s])
    monkeypatch.setattr(_R, "INDICATION_TO_TCGA_STUDIES", {"COADREAD": ["COAD", "READ"]})


def test_assembly_target_above_all_positives(contracts, monkeypatch):
    _wire_percentiles(
        monkeypatch, {"TARGET": 99.9, "POS_HI": 99.0, "POS_MID": 90.0, "HK": 99.9, "LUNGMARK": 18.0, "SILENT": 12.0}
    )
    out = CP.control_position_tumor("TARGET", "COADREAD", contracts_dir=contracts)
    assert out["control_position_class"] == "above_all_positives"
    # Mutation teeth (#862): control_target_percentile/_class must NOT be echoed — there is no
    # distinct control-target measurement, only allgene_percentile/_class from the same lookup
    # (surfaced separately by control_position_tumor's caller, not by this summary block).
    assert "control_target_percentile" not in out
    assert "control_target_class" not in out
    assert set(out["control_positives"]) == {"POS_HI", "POS_MID"}
    assert "LUNGMARK" in out["control_negatives"]  # applicable in COLON
    assert out["control_negatives_excluded_lineage_conflict"] == []


def test_assembly_excludes_lineage_negative_in_lung(contracts, monkeypatch):
    _wire_percentiles(
        monkeypatch, {"TARGET": 95.0, "POS_HI": 99.0, "POS_MID": 90.0, "HK": 99.9, "LUNGMARK": 99.0, "SILENT": 12.0}
    )
    monkeypatch.setattr(CP, "_INDICATION_CANONICAL_ALIAS", {"LUAD": "NSCLC"})
    # add LUAD studies so the target ranks
    from methods.tcga_gtex_expression_distribution import read as _R

    monkeypatch.setattr(_R, "INDICATION_TO_TCGA_STUDIES", {"LUAD": ["LUAD"]})
    out = CP.control_position_tumor("TARGET", "LUAD", contracts_dir=contracts)
    assert "LUNGMARK" in out["control_negatives_excluded_lineage_conflict"]
    assert "LUNGMARK" not in out["control_negatives"]


def test_vocab_missing_is_data_unavailable(tmp_path, monkeypatch):
    CP._load_controls.cache_clear()
    out = CP.control_position_tumor("TARGET", "COADREAD", contracts_dir=str(tmp_path))
    assert out["control_position_class"] == "data_unavailable"
