"""Track C fix (enrichment review): rnai_screens_contributing was DECLARED but ALWAYS [] because
load_rnai_files loaded sample_info.csv but never returned it, so both callers omitted it from
compute_summary_stats. This pins that (a) compute_summary_stats populates the screen membership from a
sample_info_df, and (b) load_rnai_files now returns it as a 4th element (arity contract)."""
from __future__ import annotations
import importlib.util, inspect, sys
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
CLI = REPO / "methods" / "depmap_demeter_distribution" / "cli.py"


def _load():
    spec = importlib.util.spec_from_file_location("rnai_cli_sc", CLI)
    m = importlib.util.module_from_spec(spec); sys.modules["rnai_cli_sc"] = m
    spec.loader.exec_module(m); return m


cli = _load()


def test_screens_contributing_populated_from_sample_info():
    demeter_by_model = {"ACH-1": -0.6, "ACH-2": -0.1, "ACH-3": -0.4}
    model_metadata = {
        "ACH-1": {"CCLEName": "CL1_TISSUE", "OncotreeLineage": "Lung"},
        "ACH-2": {"CCLEName": "CL2_TISSUE", "OncotreeLineage": "Bowel"},
        "ACH-3": {"CCLEName": "CL3_TISSUE", "OncotreeLineage": "Skin"},
    }
    sample_info_df = pd.DataFrame([
        {"CCLE_ID": "CL1_TISSUE", "in_Achilles": True,  "in_DRIVE": True,  "in_Marcotte": False},
        {"CCLE_ID": "CL2_TISSUE", "in_Achilles": True,  "in_DRIVE": False, "in_Marcotte": True},
        {"CCLE_ID": "CL3_TISSUE", "in_Achilles": False, "in_DRIVE": True,  "in_Marcotte": True},
    ])
    summary = cli.compute_summary_stats(demeter_by_model, model_metadata, sample_info_df=sample_info_df)
    screens = {s["screen"]: s["n_lines"] for s in summary["rnai_screens_contributing"]}
    assert screens == {"Achilles": 2, "DRIVE": 2, "Marcotte": 2}   # each flag true in 2 of the 3 lines


def test_screens_contributing_empty_without_sample_info():
    # the pre-fix behaviour is retained as the honest empty when no sample_info is available
    summary = cli.compute_summary_stats({"ACH-1": -0.6}, {"ACH-1": {"CCLEName": "CL1"}}, sample_info_df=None)
    assert summary["rnai_screens_contributing"] == []


def test_load_rnai_files_returns_four_tuple():
    # arity contract: the 4th element (sample_info_df) is what the callers now forward. Assert via the
    # source (no S3): the function's return statements all yield 4 values.
    src = inspect.getsource(cli.load_rnai_files)
    returns = [ln.strip() for ln in src.splitlines() if ln.strip().startswith("return ")]
    assert returns, "no return statements found"
    for r in returns:
        # each return has 3 commas → 4 values (either the {}, {}, load_errors, sample_info_df error path
        # or the success 4-tuple)
        assert r.count(",") == 3, f"non-4-tuple return: {r}"
