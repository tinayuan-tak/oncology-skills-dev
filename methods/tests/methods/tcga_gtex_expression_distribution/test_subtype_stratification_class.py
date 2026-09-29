"""subtype_stratification_class — the graded patient-selection signal fed to the biomarker facet.

Pure-logic tests of the grading (no S3): build a synthetic landscape and assert the class. The strong
class (subtype_restricted_with_window) can't be reached by the broadly-expressed live test targets, so
it's pinned here. Imports the REAL classifier (no mirror) so there is zero drift risk."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.tcga_gtex_expression_distribution.read import (  # noqa: E402
    classify_subtype_stratification as _classify,
)


def _rec(signal, state="measured", frac_norm=None, proxy_frac=None):
    r = {"evidence_state": state, "subtype_signal": signal}
    if frac_norm is not None:
        r["fraction_tumor_above_normal_p95"] = frac_norm
    if proxy_frac is not None:
        r["proxy_normal_windows"] = [{"proxy_tissue": "ESOPHAGUS", "fraction_tumor_above_proxy_p95": proxy_frac}]
    return r


def test_restricted_with_matched_window_is_strongest():
    ls = [_rec("subtype_restricted", frac_norm=0.8), _rec("subtype_uniform", frac_norm=0.1)]
    assert _classify(ls) == "subtype_restricted_with_window"


def test_restricted_with_proxy_window_also_qualifies():
    ls = [_rec("subtype_restricted", proxy_frac=0.7)]
    assert _classify(ls) == "subtype_restricted_with_window"


def test_restricted_without_window_is_plain_restricted():
    ls = [_rec("subtype_restricted", frac_norm=0.2)]  # restricted but doesn't clear window
    assert _classify(ls) == "subtype_restricted"


def test_enriched_only_is_weak_selection():
    ls = [_rec("subtype_enriched", frac_norm=0.9), _rec("subtype_uniform")]
    assert _classify(ls) == "subtype_enriched"


def test_all_uniform_is_pan_subtype():
    assert _classify([_rec("subtype_uniform"), _rec("subtype_uniform")]) == "pan_subtype_uniform"


def test_depleted_does_not_create_a_selection_signal():
    # CDX2/COADREAD case: a depleted subtype is NOT a positive patient-selection opportunity
    assert _classify([_rec("subtype_depleted"), _rec("subtype_uniform")]) == "pan_subtype_uniform"


def test_no_measured_strata_is_axis_unavailable():
    assert _classify([_rec("subtype_uniform", state="underpowered")]) == "subtype_axis_unavailable"
