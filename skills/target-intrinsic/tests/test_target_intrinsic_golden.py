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
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"


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
        f"run.py exited {result.returncode} on EGFR.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
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
        f"target-intrinsic is verdict-free; got verdict={egfr_decision.get('verdict')!r}")


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
        f"unless a curated entry exists).")


def test_egfr_headline_resolves_broadly(egfr_decision):
    """Field-name drift guard: on EGFR with the bulk of cards available, the dossier headline should
    resolve broadly. A field-name drift that silently broke readers would collapse many headline
    values to None. Gated on broad availability so partial-S3 states skip rather than flake."""
    cards = egfr_decision.get("cards") or []
    available = [c for c in cards if not c.get("_missing")]
    if len(available) < 12:
        pytest.skip(f"only {len(available)} cards available for EGFR — partial S3; skip the drift floor")
    headline = egfr_decision.get("headline") or {}
    non_null = [k for k, v in headline.items() if v not in (None, "", [], "data_unavailable")]
    assert len(non_null) >= 12, (
        f"only {len(non_null)}/{len(headline)} headline fields resolved for EGFR while "
        f"{len(available)} cards are available — suspect a reader field-name drift "
        f"(g('card','field') -> None). Non-null keys: {sorted(non_null)}")
