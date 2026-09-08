"""Hermetic test: subgroup_effect_admissible — the small-n-but-tight POSITIVE admissibility for the
subtype-restricted-dependency rung (2026-08-19, subtype-verdict-shifting review §5; POU2F3/SCLC-P).

A below-n>=30-floor stratum is admissible for the POSITIVE rung iff n>=MIN_N_EFFECT_ADMISSIBLE (3) AND
>=EFFECT_STRONG_FRAC (0.75) of its lines are individually strongly dependent (Chronos <= -1.0). The
NEGATIVE hold's subgroup_n_floor_met (n>=30) is UNCHANGED — asymmetric by design.
"""

import importlib.util
import sys
from pathlib import Path

import pandas as pd

_R = Path(__file__).resolve().parents[3] / "methods" / "depmap_chronos" / "read.py"
spec = importlib.util.spec_from_file_location("depmap_chronos.read", _R)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
# make the package importable so relative imports in read.py resolve
import types

pkg = types.ModuleType("depmap_chronos")
pkg.__path__ = [str(_R.parent)]
sys.modules["depmap_chronos"] = pkg
spec.loader.exec_module(mod)


def _fixture(tmp_path, model_to_effect):
    df = pd.DataFrame({"ModelID": list(model_to_effect), "POU2F3 (25833)": list(model_to_effect.values())})
    p = tmp_path / "CRISPRGeneEffect.parquet"
    df.to_parquet(p)
    return p


def test_small_tight_stratum_is_effect_admissible_but_below_floor(tmp_path):
    # SCLC-P-like: n=5, 4/5 strongly dependent (<=-1.0), 1 outlier
    sclc_p = {"ACH-1": -1.61, "ACH-2": -1.53, "ACH-3": -1.53, "ACH-4": -1.13, "ACH-5": -0.22}
    pq = _fixture(tmp_path, sclc_p)
    rec = mod.read_stratified_dependency("POU2F3", "SCLC", chronos_parquet=pq, _sample_id_filter=list(sclc_p))
    assert rec["subgroup_n"] == 5
    assert rec["dependency_class"] == "strong_dependency"  # median -1.53
    assert rec["subgroup_effect_admissible"] is True  # 4/5 = 80% strong
    assert rec["subgroup_n_floor_met"] is False  # asymmetry: negative hold still needs n>=30


def test_small_loose_stratum_not_admissible(tmp_path):
    # SCLC-A-like: none strongly dependent
    sclc_a = {"ACH-6": -0.29, "ACH-7": -0.07, "ACH-8": 0.23, "ACH-9": -0.10}
    pq = _fixture(tmp_path, sclc_a)
    rec = mod.read_stratified_dependency("POU2F3", "SCLC", chronos_parquet=pq, _sample_id_filter=list(sclc_a))
    assert rec["subgroup_effect_admissible"] is False


def test_too_few_lines_not_admissible(tmp_path):
    # n=2 (< MIN_N_EFFECT_ADMISSIBLE), even if both strong
    two = {"ACH-a": -1.5, "ACH-b": -1.4}
    pq = _fixture(tmp_path, two)
    rec = mod.read_stratified_dependency("POU2F3", "SCLC", chronos_parquet=pq, _sample_id_filter=list(two))
    assert rec["subgroup_effect_admissible"] is False
