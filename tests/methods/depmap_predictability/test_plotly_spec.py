"""emit_plotly_specs (Gate-C plotly debt, 2026-07-21) for depmap_predictability.

Interactive twin of emit_feature_importance_bar: horizontal bar of top-10 SHAP-ranked RF features
colored by feature_class. Built from the SAME summary the SVG + v2 parquet use — no drift. No S3
(synthetic summary). Plotly optional; no feature data → no-op.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CLI = REPO / "methods" / "depmap_predictability" / "cli.py"
# Portable sibling root: was hardcoded to the author's /home/sagemaker-user checkout, so the
# guard below reported "not available" on every CI runner -- even though the workflow checks
# this sibling out and exports its root. `or` rather than a .get() default, so an EMPTY value
# falls back too instead of yielding Path("") == the CWD, which reads as a plausible wrong root.
CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT") or REPO.parent / "rnd-computational-biology-oncology-target-contracts"
)

pytest.importorskip("plotly", reason="plotly not installed in this env")


def _load():
    spec = importlib.util.spec_from_file_location("e5_cli", CLI)
    m = importlib.util.module_from_spec(spec)
    sys.modules["e5_cli"] = m
    spec.loader.exec_module(m)
    return m


cli = _load()


def _decode(v):
    if isinstance(v, dict) and "bdata" in v:
        import numpy as np

        return np.frombuffer(base64.b64decode(v["bdata"]), dtype={"f8": "<f8", "f4": "<f4"}[v["dtype"]]).tolist()
    return list(v)


def _summary():
    feats = [
        {"feature": "KRAS_expr", "importance": 0.42, "feature_class": "own_expression"},
        {"feature": "lineage_Bowel", "importance": 0.21, "feature_class": "lineage"},
        {"feature": "TP53_mut", "importance": 0.12, "feature_class": "cross_gene_expression"},
    ]
    return {
        "predictability_class": "own_omics_driven",
        "pearson_r_squared_rf": 0.55,
        "pearson_r_squared_rf_ci_lo": 0.4,
        "pearson_r_squared_rf_ci_hi": 0.7,
        "model_agreement": "concordant",
        "pred_top_features_rf": feats,
    }


def test_emits_valid_feature_bar():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        written = cli.emit_plotly_specs(_summary(), "KRAS", out, CONTRACTS)
        assert {w["id"] for w in written} == {"feature_importance_bar"}
        obj = json.loads((out / "figure_feature_importance_bar.plotly.json").read_text())
        assert obj["data"] and obj["data"][0]["type"] == "bar"
        assert obj["data"][0]["orientation"] == "h"
        assert written[0]["type"] == "plotly"


def test_no_drift_importances_match_summary():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plotly_specs(_summary(), "KRAS", out, CONTRACTS)
        obj = json.loads((out / "figure_feature_importance_bar.plotly.json").read_text())
        assert sorted(_decode(obj["data"][0]["x"])) == sorted([0.42, 0.21, 0.12])


def test_top_feature_at_top_of_bar():
    """Reversed so the highest-SHAP feature sits at the top (mirrors the SVG invert_yaxis).
    In Plotly horizontal bars, the LAST y-tick renders at the top."""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        cli.emit_plotly_specs(_summary(), "KRAS", out, CONTRACTS)
        obj = json.loads((out / "figure_feature_importance_bar.plotly.json").read_text())
        ticktext = obj["layout"]["yaxis"]["ticktext"]
        assert ticktext[-1] == "KRAS_expr"  # highest importance at top


def test_no_features_no_op():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        assert cli.emit_plotly_specs({"pred_top_features_rf": []}, "KRAS", out, CONTRACTS) == []
