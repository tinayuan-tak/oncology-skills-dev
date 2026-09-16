"""The lineage/name fallbacks in this card were written correctly and could never fire. Prove they now do.

Six consumer sites in cli.py guard a missing cell-line lineage or name, and before the frame-boundary fix
every one of them was inert — for two DIFFERENT reasons, which is why fixing only one shape is not enough:

  1. `meta.get("OncotreeLineage") or meta.get("lineage") or ... or "unknown"`  (:369, :582, :795, :900)
     inert because **float('nan') is truthy** — the first term wins and `lineage` becomes nan.
  2. `meta.get("CellLineName", mid)`                                          (:809, :891 pre-fix)
     inert because a `.get` default fires on an absent KEY, and the key is PRESENT holding NaN.

Converting the boundary to None fixes (1) outright — None is falsy, so the authors' own chain runs. It does
NOT fix (2): None is still a present value, so those two sites were rewritten to `or`. This file pins both,
because a fallback that cannot fire is indistinguishable from one that does until you feed it a gap.
"""

from __future__ import annotations

import math
from io import StringIO

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

from methods.depmap_chronos_distribution.cli import emit_plot_data  # noqa: E402
from methods.depmap_common import model_metadata_by_id  # noqa: E402

# 8 models so pd.qcut(q=4) has distinct edges. ACH-000007/8 are the gaps: no lineage, no name.
MODEL_CSV = """ModelID,CellLineName,CCLEName,OncotreeLineage,OncotreeSubtype,PrimaryDisease
ACH-000001,NIHOVCAR3,NIHOVCAR3_OVARY,Ovary/Fallopian Tube,High-Grade Serous,Ovarian Cancer
ACH-000002,HL-60,HL60_HAEMATOPOIETIC,Myeloid,AML,Leukemia
ACH-000003,A549,A549_LUNG,Lung,LUAD,Lung Cancer
ACH-000004,MCF7,MCF7_BREAST,Breast,IDC,Breast Cancer
ACH-000005,HCT116,HCT116_LARGE_INTESTINE,Bowel,COAD,Colorectal Cancer
ACH-000006,PANC1,PANC1_PANCREAS,Pancreas,PDAC,Pancreatic Cancer
ACH-000007,,,,,
ACH-000008,,,,,
"""

CHRONOS = {
    "ACH-000001": -1.8,
    "ACH-000002": -1.4,
    "ACH-000003": -1.0,
    "ACH-000004": -0.7,
    "ACH-000005": -0.4,
    "ACH-000006": -0.1,
    "ACH-000007": 0.2,
    "ACH-000008": 0.5,
}


def _frame():
    return pd.read_csv(StringIO(MODEL_CSV))


def _plot_data(metadata, tmp_path):
    emit_plot_data(CHRONOS, metadata, -1.0, tmp_path)
    return pd.read_parquet(tmp_path / "plot_data.parquet").set_index("cell_line_id")


def test_pre_fix_both_fallbacks_are_inert(tmp_path):
    """Pin the pre-state for BOTH shapes at once — this is what made the guards look like they worked."""
    row = _frame().iloc[6].to_dict()  # ACH-000007, straight off the frame, unconverted
    or_chain = row.get("OncotreeLineage") or row.get("lineage") or row.get("PrimaryDisease") or "unknown"
    assert isinstance(or_chain, float) and math.isnan(or_chain), (
        f"the `or`-chain must be inert against truthy NaN pre-fix, got {or_chain!r}"
    )
    get_default = row.get("CellLineName", "ACH-000007")
    assert isinstance(get_default, float) and math.isnan(get_default), (
        f"a .get default cannot fire on a present-but-NaN key, got {get_default!r}"
    )


def test_lineage_falls_back_to_unknown(tmp_path):
    df = _plot_data(model_metadata_by_id(_frame()), tmp_path)
    assert df.loc["ACH-000007", "lineage"] == "unknown"
    assert df.loc["ACH-000008", "lineage"] == "unknown"
    assert df.loc["ACH-000001", "lineage"] == "Ovary/Fallopian Tube", "present values untouched"


def test_cell_line_name_falls_back_to_the_model_id(tmp_path):
    """The `.get(k, default)` → `or` rewrite. A name is the one field where borrowing the ID IS right:
    the row is keyed by cell_line_id anyway, so an empty label would render as a blank axis tick."""
    df = _plot_data(model_metadata_by_id(_frame()), tmp_path)
    assert df.loc["ACH-000007", "cell_line_name"] == "ACH-000007"
    assert df.loc["ACH-000001", "cell_line_name"] == "NIHOVCAR3"


def test_no_non_finite_reaches_any_plot_data_column(tmp_path):
    """Quantified over every cell, not just the two fields we happen to have named."""
    df = _plot_data(model_metadata_by_id(_frame()), tmp_path)
    bad = [
        (idx, col, v)
        for col in df.columns
        for idx, v in df[col].items()
        if isinstance(v, float) and not math.isfinite(v)
    ]
    assert bad == [], f"non-finite values reached plot_data: {bad}"
    assert df["sub_lineage"].loc["ACH-000007"] == "", "the '' fallback is the card's choice, and it fires"
    assert df["primary_disease"].loc["ACH-000007"] == ""
