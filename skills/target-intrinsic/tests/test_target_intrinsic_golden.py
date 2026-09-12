"""LIVE golden drift-guard for the target-intrinsic dossier (EGFR).

The sibling test_target_intrinsic.py is S3-FREE (it parses SKILL.md/run.py as text). That cannot
catch the reader-real-field-names bug class: a card method renaming an output field makes the
`g("card-id", "field")` read in _headline resolve to None SILENTLY — the skill still runs, the
headline key still exists, but the signal is gone and no static test notices.

This test runs the skill end-to-end on EGFR (a maximally-characterized reference target) and pins a
few STABLE, high-value expectations. It SKIPS gracefully when live reads are unavailable (CI without
S3 creds), so it fails on drift/logic bugs but not on data availability.

Self-contained: does not depend on the compose-dashboard skip_if_no_data conftest helper (still in review).
When it lands, this can be refactored to reuse it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"

# Live reads DECLARED by the environment: the skill's contracted profile (SKILL.md
# metadata.environment: AWS_PROFILE=cbg — the one that reaches the onc-compbio bucket), or an explicit
# force. When declared, a PARTIAL roster is a REGRESSION to fail on, not a data-availability skip.
# Otherwise every floor below skips: the SageMaker image exports AWS_PROFILE=cmp-dev by default, under
# which EGFR resolves only 8/20 — so "AWS_PROFILE is set" is NOT a usable liveness signal here.
_LIVE_DECLARED = os.environ.get("AWS_PROFILE") == "cbg" or bool(os.environ.get("TI_GOLDEN_REQUIRE_LIVE"))


def _skip_or_fail(reason: str) -> None:
    if _LIVE_DECLARED:
        pytest.fail(reason + " [live reads declared: AWS_PROFILE=cbg / TI_GOLDEN_REQUIRE_LIVE]")
    pytest.skip(reason)


def _card_available(cards: list, card_id: str) -> bool:
    for c in cards:
        if c.get("card_id") == card_id or c.get("id") == card_id:
            return not c.get("_missing")
    return False


@pytest.fixture(scope="module")
def egfr_decision(tmp_path_factory):
    """Run the dossier on EGFR once; return the parsed decision.json (or skip on no-S3)."""
    out_dir = tmp_path_factory.mktemp("ti-egfr")
    argv = [sys.executable, str(RUN_PY), "--target", "EGFR", "--out", str(out_dir)]
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        pytest.skip("target-intrinsic EGFR run timed out (slow/unavailable live reads)")
    # A hard non-zero exit is a real failure (the dispatcher should degrade gracefully, not crash).
    assert result.returncode == 0, (
        f"run.py exited {result.returncode} on EGFR.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    decision_path = out_dir / "decision.json"
    assert decision_path.exists(), f"no decision.json written.\nstdout:\n{result.stdout}"
    return json.loads(decision_path.read_text())


def test_egfr_identity_and_shape(egfr_decision):
    """Identity resolution + the verdict-free contract hold on a live run."""
    cards = egfr_decision.get("cards") or []
    available = [c for c in cards if not c.get("_missing")]
    if cards and not available:
        pytest.skip("all cards _missing on EGFR — no S3 (data availability, not a drift bug)")
    assert egfr_decision["skill"] == "target-intrinsic"
    headline = egfr_decision.get("headline") or {}
    # identity resolves for EGFR whenever the identity card is available
    if _card_available(cards, "target-identity-summary"):
        assert headline.get("target_symbol") == "EGFR"
    # descriptive skill: NO top-level verdict spine
    assert egfr_decision.get("verdict") in (None, "descriptive", "none"), (
        f"target-intrinsic is verdict-free; got verdict={egfr_decision.get('verdict')!r}"
    )


def test_egfr_domain_modality_not_mislabelled(egfr_decision):
    """Regression (end-to-end): EGFR is a multi-domain RTK and a canonical INHIBITOR target;
    the class-driven heuristic must NOT call it removal_favored (it now returns indeterminate)."""
    cards = egfr_decision.get("cards") or []
    if not _card_available(cards, "domain-modality-relevance"):
        pytest.skip("domain-modality-relevance card unavailable for EGFR (no S3)")
    klass = (egfr_decision.get("headline") or {}).get("modality_implication_class")
    assert klass != "removal_favored", (
        f"EGFR modality_implication_class={klass!r}: the multi-domain-enzyme heuristic mislabelled a "
        f"well-drugged inhibitor target as degrader-favored (the v0.2.0 fix should yield indeterminate "
        f"unless a curated entry exists)."
    )


def test_egfr_headline_resolves_broadly(egfr_decision):
    """Field-name drift guard: on EGFR with the bulk of cards available, the dossier headline should
    resolve broadly. A field-name drift that silently broke readers would collapse many headline
    values to None. Gated on broad availability so partial-S3 states skip rather than flake."""
    cards = egfr_decision.get("cards") or []
    available = [c for c in cards if not c.get("_missing")]
    if len(available) < 12:
        _skip_or_fail(f"only {len(available)} cards available for EGFR — partial S3; skip the drift floor")
    headline = egfr_decision.get("headline") or {}
    non_null = [k for k, v in headline.items() if v not in (None, "", [], "data_unavailable")]
    assert len(non_null) >= 12, (
        f"only {len(non_null)}/{len(headline)} headline fields resolved for EGFR while "
        f"{len(available)} cards are available — suspect a reader field-name drift "
        f"(g('card','field') -> None). Non-null keys: {sorted(non_null)}"
    )


def test_egfr_resolves_the_whole_roster_when_live(egfr_decision):
    """With live reads declared, EGFR must resolve ALL 20 cards — the same floor the committed offline
    fixture is held to (test_target_intrinsic_replay::test_fixture_covers_the_whole_roster). A card that
    goes _missing for the fleet's most-characterized target is an upstream data/reader regression, and it
    is also what silently staled the fixture at 19/20."""
    if not _LIVE_DECLARED:
        pytest.skip("live reads not declared (AWS_PROFILE != cbg) — roster completeness is not testable")
    cards = egfr_decision.get("cards") or []
    missing = sorted(c.get("card_id") or c.get("id") for c in cards if c.get("_missing"))
    assert not missing, f"{len(missing)}/{len(cards)} cards _missing for EGFR on a live run: {missing}"
