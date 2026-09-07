"""Finding #3/#9 regression: RNAi strongly_selective must require GENUINE bimodality (shape), not the
selective fraction band alone; the shape uses a real Sarle BC, not the median-proxy."""

from __future__ import annotations
import importlib.util, sys
from pathlib import Path
import numpy as np

REPO = Path(__file__).resolve().parents[3]
CLI = REPO / "methods" / "depmap_demeter_distribution" / "cli.py"


def _load():
    spec = importlib.util.spec_from_file_location("rnai_cli_b", CLI)
    m = importlib.util.module_from_spec(spec)
    sys.modules["rnai_cli_b"] = m
    spec.loader.exec_module(m)
    return m


cli = _load()


def test_bimodality_coefficient_separates_bimodal_from_unimodal():
    bimodal = np.concatenate([np.full(60, -2.0), np.full(60, 0.0)])
    unimodal = np.random.default_rng(0).normal(0.0, 0.3, 200)
    assert cli._bimodality_coefficient(bimodal) > cli.BIMODALITY_COEFFICIENT_THRESHOLD
    assert cli._bimodality_coefficient(unimodal) < cli.BIMODALITY_COEFFICIENT_THRESHOLD
    assert cli._bimodality_coefficient([1.0, 2.0]) is None  # n<4 → None (median-shift fallback)


def test_rnai_strongly_selective_requires_bimodal_shape():
    # #3: in-band frac but NON-bimodal shape → NOT strongly_selective.
    assert (
        cli._classify_rnai_dependency(0.30, -0.30, "shifted_dependent", n_cell_lines_evaluated=700)
        == "broadly_dependent"
    )
    assert cli._classify_rnai_dependency(0.30, 0.05, "non_essential", n_cell_lines_evaluated=700) == "non_dependent"
    # genuine bimodality → strongly_selective (unchanged positive control)
    assert (
        cli._classify_rnai_dependency(0.30, -0.10, "bimodal_selective", n_cell_lines_evaluated=700)
        == "strongly_selective"
    )
