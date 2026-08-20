"""cms_classifier (Phase 2) — hermetic: _parse_entrez + _run_cms_classifier reshape with a MOCKED
Rscript (no R, no DepMap). Validates the tall (sample × CMS stratum, is_member) shape + the
unclassifiable (NA CMS) path. The real CMScaller NTP run is a compute-session integration (Phase 4)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

pd = pytest.importorskip("pandas")
from methods.subgroup_assigner_classifier import cli  # noqa: E402


def test_parse_entrez():
    assert cli._parse_entrez("POU2F3 (25833)") == "25833"
    assert cli._parse_entrez("TP53 (7157)") == "7157"
    assert cli._parse_entrez("ModelID") is None
    assert cli._parse_entrez("NoParen") is None


def _fake_rscript(canned_rows):
    """A subprocess.run stand-in that writes the canned NTP output to the --out parquet."""
    def _run(cmd, check=False, **kwargs):
        out = cmd[cmd.index("--out") + 1]
        pd.DataFrame(canned_rows).to_parquet(out, index=False)
        class _R:  # noqa: D401 - minimal CompletedProcess stand-in
            returncode = 0
        return _R()
    return _run


_STRATUM_MAP = {"CMS1": "CMS1_depmap", "CMS2": "CMS2_depmap",
                "CMS3": "CMS3_depmap", "CMS4": "CMS4_depmap"}


def test_cms_reshape_winner_and_unclassifiable(tmp_path, monkeypatch):
    # ACH-1 → CMS2 (classified); ACH-2 → NA (unclassifiable, below FDR floor)
    canned = [
        {"sample_id": "ACH-1", "CMS": "CMS2", "p_value": 0.01, "FDR": 0.02},
        {"sample_id": "ACH-2", "CMS": None, "p_value": 0.5, "FDR": 0.4},
    ]
    monkeypatch.setattr(subprocess, "run", _fake_rscript(canned))

    expr = pd.DataFrame(
        {"GENEA (1)": [1.0, 2.0], "GENEB (2)": [3.0, 4.0]},
        index=["ACH-1", "ACH-2"],
    )
    config = {"cms_stratum_map": _STRATUM_MAP, "fdr_threshold": 0.05, "rnaseq": True}
    out = cli._run_cms_classifier(expr, config, tmp_path / "_cms_work")

    # every sample × every CMS stratum → one row
    assert set(out["stratum_id"]) == set(_STRATUM_MAP.values())
    assert len(out) == 2 * 4

    # ACH-1: exactly the mapped winner (CMS2_depmap) is_member True
    a1 = out[out["sample_id"] == "ACH-1"]
    assert a1[a1["is_member"]]["stratum_id"].tolist() == ["CMS2_depmap"]
    assert a1[a1["stratum_id"] == "CMS2_depmap"]["derivation_value"].iloc[0].startswith("CMS2_FDR=")

    # ACH-2: unclassifiable → NO stratum is_member; tagged once
    a2 = out[out["sample_id"] == "ACH-2"]
    assert not a2["is_member"].any()
    assert (a2["derivation_value"] == "unclassifiable:below_fdr_floor").sum() == 1


def test_cms_config_requires_stratum_map(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_rscript([]))
    expr = pd.DataFrame({"GENEA (1)": [1.0]}, index=["ACH-1"])
    with pytest.raises(ValueError, match="cms_stratum_map"):
        cli._run_cms_classifier(expr, {"fdr_threshold": 0.05}, tmp_path / "_w")


def test_cms_classifier_is_supported_method():
    assert "cms_classifier" in cli.SUPPORTED_CLASSIFIER_METHODS
