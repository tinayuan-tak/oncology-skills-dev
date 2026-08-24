"""genomic-alteration (strength, certainty) sidecar — CERTAINTY_MODEL 3rd axis. Verdict-inert."""
from __future__ import annotations

import sys
from pathlib import Path

GA_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(GA_SCRIPTS))
import run as ga  # noqa: E402


def _cards(civic=None, n_cell_lines=None, mut_n=None):
    c = []
    if civic is not None:
        c.append({"card_id": "variant-level-interpretation", "summary": {"civic_variant_class": civic}})
    if n_cell_lines is not None:
        c.append({"card_id": "mutation-stratified-dependency",
                  "summary": {"n_cell_lines_evaluated": n_cell_lines}})
    if mut_n is not None:
        c.append({"card_id": "mutation-type-counts", "summary": {"mut_n_cell_lines_total": mut_n}})
    return c


def test_driver_with_oncogenic_civic_corroboration():
    sc = ga._strength_certainty(_cards(civic="oncogenic", n_cell_lines=50),
                                verdict_pair=("biomarker_stratified_dependency", "mutant-strongly-dependent-supportive"))
    assert sc["strength"] == "strong_positive"
    assert sc["certainty"]["coverage"] == "high"          # 50 cell lines
    assert sc["certainty"]["corroboration"] == "high"     # CIViC oncogenic
    assert sc["certainty"]["level"] == "high"


def test_civic_uncurated_is_unmeasured_not_low():
    # gene absent from CIViC -> corroboration unmeasured (ignorance), drops from level = coverage.
    sc = ga._strength_certainty(_cards(civic=None, mut_n=8),
                                verdict_pair=("missense_dominant_pattern", "mut-missense-dominant-supportive"))
    assert sc["strength"] == "weak_positive"
    assert sc["certainty"]["corroboration"] == "unmeasured"
    assert sc["certainty"]["level"] == sc["certainty"]["coverage"] == "medium"   # mut_n=8 -> medium


def test_vus_civic_disagrees_low():
    sc = ga._strength_certainty(_cards(civic="vus", n_cell_lines=50),
                                verdict_pair=("confirmed_driver", "alteration-role-gof-driver-supportive"))
    assert sc["certainty"]["corroboration"] == "low"      # CIViC does not confirm oncogenicity
    assert sc["certainty"]["level"] == "low"               # weakest-link


def test_insufficient_forces_low():
    sc = ga._strength_certainty([], verdict_pair=("insufficient", None))
    assert sc["strength"] == "none"
    assert sc["certainty"]["level"] == "low"
