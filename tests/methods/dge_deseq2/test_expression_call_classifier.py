"""_classify_expression_call — symmetric up/down tumor-vs-adjacent labelling (2026-07-21).

Added the down-side (strong/modest_downregulation) so a significantly NEGATIVE log2_fc is no longer
mislabelled `not_informative` (which hid tumor-depletion — e.g. KRAS COADREAD log2_fc=-0.62,
q=4e-11). Pins the thresholds + the direction-vs-magnitude distinction (a positive lfc below the
strong cutoff is still UP, never down).
"""

import importlib.util
from pathlib import Path

READ = Path(__file__).resolve().parents[3] / "methods" / "dge_deseq2" / "read.py"


def _load():
    spec = importlib.util.spec_from_file_location("dge_read", READ)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


f = _load()._classify_expression_call


def test_upregulation_thresholds():
    assert f(2.0, 1e-6) == "strong_upregulation"  # >= 1.5
    assert f(1.5, 1e-6) == "strong_upregulation"  # boundary
    assert f(0.8, 3e-6) == "modest_upregulation"  # 0.5..1.5 — UP, just modest (not down!)
    assert f(0.5, 1e-6) == "modest_upregulation"  # boundary


def test_downregulation_thresholds_symmetric():
    assert f(-2.0, 1e-9) == "strong_downregulation"  # <= -1.5
    assert f(-1.5, 1e-9) == "strong_downregulation"  # boundary
    assert f(-0.62, 4e-11) == "modest_downregulation"  # the KRAS COADREAD case
    assert f(-0.5, 1e-6) == "modest_downregulation"  # boundary


def test_not_informative_is_only_flat_or_nonsignificant():
    assert f(0.2, 1e-6) == "not_informative"  # small effect, significant → flat
    assert f(-0.2, 1e-6) == "not_informative"
    assert f(2.0, 0.9) == "not_informative"  # big effect but q >= 0.05
    assert f(-2.0, 0.9) == "not_informative"  # down but non-significant → not a call


def test_direction_is_the_sign_not_the_magnitude():
    """A positive log2_fc below the strong cutoff is UPREGULATION, never downregulation — the
    magnitude threshold does not flip direction."""
    assert f(0.8, 1e-6).endswith("upregulation")
    assert f(-0.8, 1e-6).endswith("downregulation")


def test_data_unavailable():
    assert f(None, 1e-6) == "data_unavailable"
    assert f(1.0, None) == "data_unavailable"
    assert f(float("nan"), 1e-6) == "data_unavailable"


# --- selectivity 4-panel emitter: None log2_cpm must not crash the boxplot -----


def test_selectivity_4panel_tolerates_none_log2cpm(tmp_path):
    """Regression: emit_tumor_vs_normal_selectivity_4panel crashed (None+None in matplotlib's
    boxplot np.mean) when a per-sample group carried None log2_cpm values — real KRAS COADREAD data
    hit this. Panel A must filter None like the plotly twin does."""
    import importlib
    from pathlib import Path
    import pytest

    pytest.importorskip("matplotlib", reason="matplotlib not installed in this env")
    CONTRACTS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
    if not (CONTRACTS / "plot_styles" / "takeda_palette.py").exists():
        pytest.skip("target-contracts plot_styles not available in this env")
    E = importlib.import_module("methods.dge_deseq2.emit")  # package-context import (see test_plotly_spec)
    # per-sample data with SOME None log2_cpm mixed in (the failure shape)
    per_sample = {
        "tumor_samples": [{"log2_cpm": 5.6}, {"log2_cpm": None}, {"log2_cpm": 6.1}],
        "adjacent_samples": [{"log2_cpm": None}, {"log2_cpm": 6.3}],
        "gtex_samples": [{"log2_cpm": 5.9}, {"log2_cpm": None}],
        "gtex_tissue": "COLON",
    }
    summary = {
        "selectivity_class": "not_informative",
        "log2fc_cell_a": -0.6,
        "q_value_cell_a": 1e-8,
        "dominant_direction": "down",
        "cells_ran": 3,
    }
    # must not raise (previously: TypeError None+None in matplotlib boxplot np.mean)
    E.emit_tumor_vs_normal_selectivity_4panel(
        sensitivity_summary=summary,
        per_sample_data=per_sample,
        target="KRAS",
        indication="COADREAD",
        out_dir=tmp_path,
        target_contracts_dir=CONTRACTS,
    )
    assert (tmp_path / "figure_tumor_vs_normal_selectivity_4panel.svg").exists()


def test_selectivity_4panel_renders_gtex_from_tpm_only(tmp_path):
    """Regression (chain review #4): the GTEx arm comes from the long TPM product carrying ONLY
    log2_tpm (log2_cpm=None). The emitter previously keyed the box panel on log2_cpm, so EVERY GTEx
    sample was silently dropped and the 3-group figure showed only tumor+adjacent. With the unit-
    selection fix the panel prefers log2_tpm, so the GTEx group renders and the axis is TPM."""
    import importlib
    from pathlib import Path
    import pytest

    pytest.importorskip("matplotlib", reason="matplotlib not installed in this env")
    CONTRACTS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
    if not (CONTRACTS / "plot_styles" / "takeda_palette.py").exists():
        pytest.skip("target-contracts plot_styles not available in this env")
    E = importlib.import_module("methods.dge_deseq2.emit")
    # the REAL failure shape: tumor/adj carry both units; GTEx (long product) has ONLY log2_tpm
    per_sample = {
        "tumor_samples": [{"log2_cpm": 5.6, "log2_tpm": 4.9}, {"log2_cpm": 6.1, "log2_tpm": 5.4}],
        "adjacent_samples": [{"log2_cpm": 6.3, "log2_tpm": 5.6}],
        "gtex_samples": [{"log2_cpm": None, "log2_tpm": 3.2}, {"log2_cpm": None, "log2_tpm": 3.5}],
        "gtex_tissue": "COLON",
    }
    summary = {
        "selectivity_class": "strong_tumor_selective",
        "log2fc_cell_a": 1.4,
        "q_value_cell_a": 1e-8,
        "dominant_direction": "up",
        "cells_ran": 3,
    }
    out = tmp_path / "figure_tumor_vs_normal_selectivity_4panel.svg"
    E.emit_tumor_vs_normal_selectivity_4panel(
        sensitivity_summary=summary,
        per_sample_data=per_sample,
        target="EPCAM",
        indication="COADREAD",
        out_dir=tmp_path,
        target_contracts_dir=CONTRACTS,
    )
    svg = out.read_text()
    # the GTEx group label must appear (it was silently absent before the fix)
    assert "GTEx COLON" in svg, "GTEx group missing from the box panel (the #4 regression)"
    # and the axis is TPM (all three groups on one comparable unit), not the old hardcoded CPM
    assert "log2(TPM + 1)" in svg
