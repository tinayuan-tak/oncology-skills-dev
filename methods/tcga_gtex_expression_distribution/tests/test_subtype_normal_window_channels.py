"""Guard: the per-subtype normal-window ENRICHMENT keeps matched and proxy channels distinct.

A proxy normal (histological analogue, e.g. HNSC→esophagus) is WEAKER evidence than a true matched
normal and must NEVER be reported in the matched channel. These are S3-free structural checks on the
config maps + the mutual-exclusivity invariant."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.tcga_gtex_expression_distribution import read as R  # noqa: E402


def test_proxy_map_only_covers_indications_without_a_true_normal():
    """A proxy set is a FALLBACK — never defined for an indication that has a true GTEx normal
    (else it would shadow the matched channel)."""
    for ind in R.INDICATION_TO_PROXY_NORMAL_TISSUES:
        assert ind not in R.INDICATION_TO_GTEX_TISSUE, (
            f"{ind} has both a true normal AND a proxy set — the proxy would shadow the matched "
            f"channel. Proxies are only for no-true-normal indications.")


def test_hnsc_proxy_set_is_squamous_justified_and_ordered():
    """HNSC proxies are the documented squamous analogues, esophagus first (closest match)."""
    specs = R.INDICATION_TO_PROXY_NORMAL_TISSUES["HNSC"]
    tissues = [t for t, _rationale in specs]
    assert tissues[0] == "ESOPHAGUS"                      # closest histological match, ranked first
    assert set(tissues) == {"ESOPHAGUS", "SKIN", "SALIVARY_GLAND"}
    assert all(rationale for _t, rationale in specs)       # every proxy carries a rationale string


def test_hnsc_and_paad_are_subtype_enabled_but_differ_in_comparator():
    """Both are subtype-enabled (in the assignment map), but HNSC has NO true normal (→ proxy) while
    PAAD has one (→ matched) — the config that drives normal_comparator_type."""
    assert "HNSC" in R.INDICATION_TO_TUMOR_ASSIGNMENT_MANIFEST
    assert "PAAD" in R.INDICATION_TO_TUMOR_ASSIGNMENT_MANIFEST
    assert "HNSC" not in R.INDICATION_TO_GTEX_TISSUE and "HNSC" in R.INDICATION_TO_PROXY_NORMAL_TISSUES
    assert "PAAD" in R.INDICATION_TO_GTEX_TISSUE and "PAAD" not in R.INDICATION_TO_PROXY_NORMAL_TISSUES
