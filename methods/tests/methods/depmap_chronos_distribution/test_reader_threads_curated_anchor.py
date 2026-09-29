"""T3: the live-reader path (read_pan_cancer_distribution — what the skill/compose-dashboard uses) must
thread DepMap curated core-essential membership into compute_summary_stats, else the pan-essential-killer
re-anchor is inert in production (defaults to None → fraction-only fallback). Live (needs S3 creds)."""

from __future__ import annotations

import os

import pytest

from methods.depmap_chronos_distribution.read import read_pan_cancer_distribution


# requires_data is NOT redundant with the skipif below, and neither is redundant with the
# _live_read_error guard inside the test. They cover three different conditions:
#   - skipif        → creds are ABSENT. Says nothing when creds are present but the read degrades.
#   - _live_read_error → the reader REPORTED a failure. A partially-successful read (dict returned,
#                     fields missing) sets no error key, so the asserts below run and fail.
#   - requires_data → the caller EXPLICITLY opted out of live data via SKILLS_SKIP_LIVE_DATA.
# Without the marker that opt-out was silently ignored: this test hard-failed inside
# scripts/preland.sh, which exports SKILLS_SKIP_LIVE_DATA=1, while the three already-marked live
# tests (cptac_protein_deg x2, pmhc_presentation x1) skipped cleanly in the same run.
@pytest.mark.requires_data
@pytest.mark.skipif(
    not os.environ.get("AWS_PROFILE") and not os.environ.get("AWS_ACCESS_KEY_ID"),
    reason="needs S3 creds for the live DepMap read",
)
def test_reader_populates_curated_anchor_and_retains_plk1_killer():
    s = read_pan_cancer_distribution("PLK1")
    if s.get("_live_read_error"):
        pytest.skip(f"live read unavailable: {s.get('_live_read_error')}")
    # PLK1 is a curated core-essential → the anchor input is populated True (not None) AND the class holds
    assert s.get("depmap_curated_common_essential") is True
    assert s.get("dependency_class") == "common_essential"  # pan-essential killer RETAINED
    assert s.get("pan_essential_fraction_call") == "common_essential"
