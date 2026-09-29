"""Guard for the card ↔ resolver verdict-role reconciliation (cards review 2026-08-17, S2 #4).

(1) The committed snapshot must match the live computation (drift guard — a card gaining/losing
    resolver consumption fails CI, forcing a conscious update).
(2) Spot-pins the specific verdict-role mislabels the review found, so the load-bearing cases can't
    silently flip: cards whose PROSE claimed the wrong role are asserted against the COMPUTED truth.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VALIDATOR = REPO / "validators" / "validate_card_resolver_consumption.py"


def _mod():
    spec = importlib.util.spec_from_file_location("_ccrc", VALIDATOR)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_snapshot_matches_live_computation():
    """CI drift guard: `python validate_card_resolver_consumption.py` must exit 0 against the
    committed snapshot."""
    import subprocess
    import sys

    r = subprocess.run([sys.executable, str(VALIDATOR)], capture_output=True, text=True)
    assert r.returncode == 0, f"card→resolver consumption drifted:\n{r.stdout}\n{r.stderr}"


def test_computed_consumption_pins_review_mislabels():
    """The COMPUTED resolver-consumption must match reality for the cards whose prose was wrong
    (2026-08-17 review). These are the load-bearing anti-regression pins."""
    consumed = set(_mod().compute()["resolver_consumed_cards"])

    # Cards whose PROSE claims/implies verdict-INERT but which DO drive a resolver verdict:
    assert "mutation-drug-response" in consumed, (
        "mutation-drug-response is resolver-consumed (genomic_alteration drug_response_biomarker rung) — "
        "its card prose claiming 'VERDICT-INERT / no resolver rung' is wrong and must not re-drift green."
    )
    # mutation-hotspot-frequency BECAME resolver-consumed in the patient-recurrence Phase 2 work (#578):
    # its pooled_driver_recurrence_class == top_1pct fires snv-recurrence-top-driver-supportive, a
    # genomic_alteration rung (verdict recurrent_snv_driver). The card prose was updated to match
    # (pooled_driver_recurrence_class marked VERDICT-DRIVING); this pin now guards the CONSUMED state so
    # it can't silently drift back to "inert". (Was previously — incorrectly — pinned as inert here.)
    assert "mutation-hotspot-frequency" in consumed, (
        "mutation-hotspot-frequency is resolver-consumed since #578 (snv-recurrence-top-driver-supportive "
        "→ recurrent_snv_driver rung); the stale inert pin failed on main."
    )

    # Cards whose PROSE claims/implies verdict-DRIVING but which are resolver-INERT:
    for inert in ("genomic-event-model-match", "phospho-pathway-activity"):
        assert inert not in consumed, (
            f"{inert} is NOT consumed by any resolver rung — its card prose implying it 'drives rules' / "
            f"'routes into gates' is misleading; if a rung is later added, update the snapshot consciously."
        )

    # S1-1 guard (2026-08-17): copy-number-distribution now drives the safety amplification guard +
    # the genomic CN-consensus rungs.
    assert "copy-number-distribution" in consumed
    # sanity: known verdict-bearing backbone cards are present
    for driving in (
        "alteration-role",
        "gnomad-lof-constraint",
        "tumor-vs-normal-selectivity",
        "pan-cancer-crispr-dependency-distribution",
    ):
        assert driving in consumed
