"""Phase 3 — subtype as a conditioning axis with MULTIPLICITY-AWARE certainty.

The per-stratum claim vector surfaces a subtype-conditional POSITIVE (e.g. CD274/MSI-H: present in the
MSI-H stratum while the pooled read is low) rather than suppressing it. To keep that honest, per-stratum
certainty takes a 1-tier haircut when several strata are scanned (k >= 5) — the burden moves from
'never mint a positive' to 'discount its certainty'. Verdict-INERT: the function is descriptive and
emits no presence_verdict; the pooled spine is byte-stable by construction.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[2]
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common.presence_claims import presence_claim_vector_by_subtype  # noqa: E402


def _cards(n_subtypes_measured, rows):
    return [
        {
            "card_id": "tumor-rna-distribution-by-subtype",
            "summary": {
                "subtype_axis_available": True,
                "subtype_variance_explained": 0.21,
                "n_subtypes_measured": n_subtypes_measured,
                "per_subgroup_metrics": rows,
            },
        }
    ]


# CD274-shaped: MSI-H present (strong), MSS low — across a 14-stratum panel (the flattening case).
_MSIH = {"stratum_id": "MSI_H", "median_log2tpm": 6.0, "n_tumor_samples": 100, "fraction_tumor_above_normal_p95": 0.6}
_MSS = {"stratum_id": "MSS", "median_log2tpm": 1.5, "n_tumor_samples": 100, "fraction_tumor_above_normal_p95": 0.05}


def test_stratum_positive_is_surfaced():
    v = presence_claim_vector_by_subtype(_cards(14, [_MSIH, _MSS]))
    assert v["strata"]["MSI_H"]["A"]["signal"] == "strong"  # positive surfaced, not suppressed
    assert v["strata"]["MSS"]["A"]["signal"] == "weak"


def test_certainty_is_multiplicity_discounted():
    v = presence_claim_vector_by_subtype(_cards(14, [_MSIH, _MSS]))
    # base corroboration high (n=100) → moderate under a 14-stratum multiple-testing surface
    a = v["strata"]["MSI_H"]["A"]
    assert a["corroboration"] == "moderate"
    assert "high→moderate" in a["evidence"] and "of 14 strata" in a["evidence"]
    assert v["multiplicity_strata_tested"] == 14


def test_no_haircut_when_few_strata():
    v = presence_claim_vector_by_subtype(_cards(3, [_MSIH, _MSS]))
    assert v["strata"]["MSI_H"]["A"]["corroboration"] == "high"  # k<5 → no discount


def test_k_falls_back_to_row_count():
    cards = _cards(None, [_MSIH, _MSS])
    cards[0]["summary"].pop("n_subtypes_measured", None)
    v = presence_claim_vector_by_subtype(cards)
    assert v["multiplicity_strata_tested"] == 2  # counted from rows
    assert v["strata"]["MSI_H"]["A"]["corroboration"] == "high"  # k=2 < 5 → no discount


def test_verdict_inert_no_spine_key():
    v = presence_claim_vector_by_subtype(_cards(14, [_MSIH, _MSS]))
    assert "presence_verdict" not in v and "driving_rule_id" not in v
