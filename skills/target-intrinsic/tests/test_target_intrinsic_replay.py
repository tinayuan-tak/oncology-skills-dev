"""OFFLINE replay of the frozen EGFR dossier — the field-name-drift guard that runs in PR CI.

The sibling test_target_intrinsic_golden.py asserts the same drift floor on a LIVE end-to-end run,
but it SKIPS on a credential-less runner — so in PR CI (no S3) it never fires, and the
reader-real-field-names bug class (a card method renames an output field → the `_HEADLINE_SPEC`
read in run.py resolves to None SILENTLY) ships uncaught.

This test closes that gap: it replays the REAL reader summaries frozen by freeze_fixture.py (run once
against live S3) THROUGH THE REAL run.py — only the live dispatcher is monkeypatched, so the
production CARDS / axis / _headline all execute exactly as in a real run. It therefore fails
deterministically, credential-less, on the SAME drift the live golden catches, plus catches
_HEADLINE_SPEC → reader field-name divergence introduced by any PR.

Faithfulness: we runpy the actual scripts/run.py (run_name="__main__"); nothing about CARDS, the
headline field-map, or the axis is duplicated here — a change to the skill is reflected in the
replay. The frozen fixture is refreshed by a nightly-live re-freeze (freeze_fixture.py), which is what
guards the snapshot itself against reader drift.
"""
from __future__ import annotations

import copy
import json
import runpy
import sys
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"
FIXTURE = SKILL_DIR / "tests" / "fixtures" / "egfr.yaml"

# run.py resolves _skills_common by inserting SKILLS_ROOT on sys.path; do it here too so the test
# can import + monkeypatch the SAME module object run.py will use (sys.modules cache).
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))


def _load_fixture() -> dict:
    if not FIXTURE.exists():
        pytest.skip(f"no frozen EGFR fixture at {FIXTURE} — run freeze_fixture.py against live S3")
    return yaml.safe_load(FIXTURE.read_text()) or {}


def _real_summary(s) -> bool:
    """A frozen entry is a REAL reader summary (not a freeze/dispatcher error, not empty)."""
    return (isinstance(s, dict) and bool(s)
            and not s.get("_freeze_error") and not s.get("_dispatcher_returned_none"))


@pytest.fixture(scope="module")
def egfr_decision(tmp_path_factory):
    """Run the ACTUAL run.py end-to-end on EGFR with the live dispatcher replaced by the frozen
    fixture; return the parsed decision.json."""
    frozen = _load_fixture()

    import _skills_common as skc

    def _fake_dispatcher_factory():
        def _read_live(card_id, target, indication, *args, **kwargs):
            s = frozen.get(card_id)
            if not _real_summary(s):
                return None                       # → resolve_cards marks the card _missing (honest)
            return copy.deepcopy(s)               # deepcopy: run.py must not mutate the shared fixture
        return _read_live

    out_dir = tmp_path_factory.mktemp("ti-egfr-replay")
    mp = pytest.MonkeyPatch()
    # FRAMEWORK_HEALTH_SMOKE would short-circuit resolve_cards to synthetic empties — force it off so
    # we exercise the real resolve→headline path over the frozen summaries.
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    mp.setattr(skc, "_import_dispatcher", _fake_dispatcher_factory)
    mp.setattr(sys, "argv", ["run.py", "--target", "EGFR", "--out", str(out_dir)])
    try:
        runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit as e:                        # run.py ends in sys.exit(run_wired_skill(...))
        assert e.code in (0, None), f"run.py exited non-zero ({e.code}) on the frozen EGFR replay"
    finally:
        mp.undo()

    decision_path = out_dir / "decision.json"
    assert decision_path.exists(), "run.py wrote no decision.json on the frozen EGFR replay"
    return json.loads(decision_path.read_text())


def test_fixture_is_nonvacuous():
    """Guard against a stale/broken freeze reading green: the committed fixture must carry a real
    summary for the BULK of the roster (>=12), matching the live golden's drift-floor gate. A freeze
    that silently produced mostly errors/empties must fail here, not pass by vacuity."""
    frozen = _load_fixture()
    real = [cid for cid, s in frozen.items() if _real_summary(s)]
    assert len(real) >= 12, (
        f"only {len(real)}/{len(frozen)} frozen cards carry a real summary — refreeze against live "
        f"S3 (freeze_fixture.py). Real cards: {sorted(real)}")


def test_replay_identity_and_verdict_free(egfr_decision):
    """Identity resolves and the descriptive (verdict-free) contract holds on the replayed run."""
    assert egfr_decision["skill"] == "target-intrinsic"
    assert (egfr_decision.get("headline") or {}).get("target_symbol") == "EGFR"
    # descriptive skill: no top-level verdict spine
    assert egfr_decision.get("verdict") in (None, "descriptive", "none"), (
        f"target-intrinsic is verdict-free; got verdict={egfr_decision.get('verdict')!r}")


def test_replay_domain_modality_not_removal_favored(egfr_decision):
    """P2.1 regression (end-to-end, offline): EGFR is a multi-domain RTK + canonical INHIBITOR target;
    the class-driven heuristic must NOT call it removal_favored."""
    klass = (egfr_decision.get("headline") or {}).get("modality_implication_class")
    assert klass != "removal_favored", (
        f"EGFR modality_implication_class={klass!r}: the multi-domain-enzyme heuristic mislabelled a "
        f"well-drugged inhibitor target as degrader-favored.")


def test_replay_headline_resolves_broadly(egfr_decision):
    """THE DRIFT FLOOR (offline mirror of the live golden): with the bulk of cards replaying real
    summaries, the dossier headline must resolve broadly. A reader field-name drift (an
    `_HEADLINE_SPEC` field renamed at the source → get_card_field returns None) would collapse many
    headline values to None — this is exactly the silent bug the live golden can't catch in PR CI."""
    headline = egfr_decision.get("headline") or {}
    non_null = [k for k, v in headline.items() if v not in (None, "", [], "data_unavailable")]
    assert len(non_null) >= 12, (
        f"only {len(non_null)}/{len(headline)} headline fields resolved for the frozen EGFR replay — "
        f"suspect a reader field-name drift vs _HEADLINE_SPEC (g('card','field') -> None). "
        f"Non-null keys: {sorted(non_null)}")


def test_replay_headline_block_descriptive_and_verdict_inert(egfr_decision):
    """The canonical HEADLINE block must BUILD (not silently degrade) on the real EGFR replay in
    DESCRIPTIVE MODE (target-intrinsic is gateless, verdict_fn=None):
      * no _enrichment_errors['headline_block'] (a build fault degrades, never crashes — but must NOT
        happen on the canonical fixture);
      * verdict.call is None (no gate verdict) yet verdict.phrase is a non-empty string (the
        deterministic dominant-signal summary) and polarity == 'neutral';
      * confidence.level is a valid tier;
      * the hero lists exactly the two claim axes (MODALITY_ROUTING, TRACTABILITY_PRECEDENT)."""
    h = egfr_decision.get("headline") or {}
    assert "headline_block" not in (h.get("_enrichment_errors") or {}), (
        f"headline_block degraded on the EGFR replay: "
        f"{(h.get('_enrichment_errors') or {}).get('headline_block')}")
    blk = h.get("headline_block")
    assert isinstance(blk, dict), "no headline_block on the EGFR replay"
    assert blk["verdict"]["call"] is None                    # gateless — descriptive, no verdict token
    assert isinstance(blk["verdict"]["phrase"], str) and blk["verdict"]["phrase"]
    assert blk["verdict"]["gate"] == "target_intrinsic"
    assert blk["verdict"]["polarity"] == "neutral"           # a descriptive lens has no positive/negative call
    assert blk["confidence"]["level"] in ("strong", "moderate", "weak", "insufficient")
    assert [a["key"] for a in blk["hero"]["axes"]] == ["MODALITY_ROUTING", "TRACTABILITY_PRECEDENT"]
    assert blk["headline_text"].endswith(".")


def test_replay_intrinsic_confirmation_caveat_guards_egfr(egfr_decision):
    """v1.6.0 verdict-INERT surface (offline CI guard): EGFR is a co-crystal-confirmed, approved-drug kinase
    → the intrinsic_confirmation_caveat must resolve the MILDER experimentally_confirmed_intrinsic_property
    GUARD (never demoted), and intrinsic_provenance must confirm the property + flag the OT double-count."""
    h = egfr_decision.get("headline") or {}
    cav = h.get("intrinsic_confirmation_caveat")
    assert isinstance(cav, dict), "no intrinsic_confirmation_caveat on the EGFR replay"
    assert cav["reason"] == "experimentally_confirmed_intrinsic_property", (
        f"EGFR (approved-drug, co-crystal) must be GUARDED, not flagged inflated; got {cav['reason']!r}")
    prov = h.get("intrinsic_provenance") or {}
    assert prov.get("experimentally_confirmed_actionable_property") is True
    assert prov.get("ot_composite_double_counts_dedicated_cards") is True
