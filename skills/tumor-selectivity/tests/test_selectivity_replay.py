"""OFFLINE verdict-replay of frozen tumor-selectivity dossiers — the drift guard this skill lacked.

tumor-selectivity's only test (test_verdict.py) feeds `_verdict` / `_headline` SYNTHETIC inputs
(hand-built `fired` rule-id lists + fabricated card summaries carrying the run.py field names). That
makes it tautological w.r.t. reader drift: if a card method RENAMES an output field, the synthetic
test still uses the run.py key and passes green, while in production two things break, NEITHER covered
before this test:
  (a) headline: a card renames a field → the `_headline` `get`-read resolves to None SILENTLY;
  (b) VERDICT: a card renames a field a target-contracts RULE keys on → the rule stops firing, so
      either the resolver verdict COLLAPSES (a selective call → insufficient — a false negative) or a
      normal-breadth VETO rule stops firing (a broadly-normal gene reads as tumor_selective — a FALSE
      POSITIVE, the exact failure the veto exists to prevent). No existing test runs `fired_rules`
      over a real summary.

This replays the REAL reader summaries frozen by freeze_fixture.py (run once against live S3) THROUGH
THE REAL run.py — only the live dispatcher is monkeypatched, so production CARDS + the
intracellular_intrinsic rule-firing + the shared selectivity resolver + the post-resolver
normal-breadth veto clamp + `_headline` all execute exactly as in a real run. It therefore fails
deterministically, credential-less, on the SAME drift a live run would, covering (a) and (b).

Two curated fixtures pin BOTH sides of the veto conjunction end-to-end:
  - CEACAM5 / COADREAD — canonical clean-selective epithelial antigen: axis-A field_effect_tumor_
    selective with a CLEAN window (no veto arm fires). Guards the false-NEGATIVE collapse AND a
    FALSE veto (a clean target must NOT be downgraded).
  - TACSTD2 (TROP2) / COADREAD — broadly-epithelial: axis-A strong_tumor_selective but ALL THREE
    normal-breadth veto arms fire (no therapeutic window vs worst critical normal + pan-normal +
    sc critical-organ), so the resolved verdict is selective_but_broadly_normal. Guards the
    silent-veto-DEATH false-positive: if a veto-card reader drifts, TROP2 would wrongly read as
    tumor_selective, and this test goes red.

The frozen fixtures are refreshed by the nightly-live re-freeze (card-behavior-matrix-nightly), which
guards the snapshots themselves against reader drift. Mirror of tumor-presence's replay.
"""
from __future__ import annotations

import copy
import json
import runpy
import sys
from pathlib import Path

import pytest
import yaml

from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"
FIXTURES = SKILL_DIR / "tests" / "fixtures"

# run.py resolves _skills_common by inserting SKILLS_ROOT on sys.path; do it here too so the test
# can import + monkeypatch the SAME module object run.py will use (sys.modules cache).
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

# Non-answers a resolved selectivity_class must never be — the false-negative collapse set.
_COLLAPSED = {None, "", "insufficient", "data_unavailable"}


# run.py's single-source-of-truth constants (selective family + veto rules), loaded once.
_TS = load_run_py(SKILL_DIR, "_ts_run_const")
_AXIS_A_SELECTIVE = set(_TS._AXIS_A_SELECTIVE)
_VETO_RULES = set(_TS._NORMAL_BREADTH_VETO_RULES)
# Every selective outcome the headline may carry: the axis-A selective family + the veto downgrade.
_SELECTIVE_OUTCOMES = _AXIS_A_SELECTIVE | {"selective_but_broadly_normal", "selective_with_normal_liability"}


def _real_summary(s) -> bool:
    """A frozen entry is a REAL reader summary (not a freeze/dispatcher error, not empty)."""
    return (isinstance(s, dict) and bool(s)
            and not s.get("_freeze_error") and not s.get("_dispatcher_returned_none"))


def _load_fixture(pair_id: str) -> dict:
    fx = FIXTURES / f"{pair_id}.yaml"
    if not fx.exists():
        pytest.skip(f"no frozen fixture at {fx} — run freeze_fixture.py against live S3")
    return yaml.safe_load(fx.read_text()) or {}


_DECISION_CACHE: dict = {}


def _decision(pair_id: str, target: str, indication: str) -> dict:
    """Run the ACTUAL run.py end-to-end on (target, indication) with the live dispatcher replaced by
    the frozen fixture; cache + return the parsed decision.json."""
    if pair_id in _DECISION_CACHE:
        return _DECISION_CACHE[pair_id]
    frozen = _load_fixture(pair_id)

    import _skills_common as skc

    def _fake_dispatcher_factory():
        def _read_live(card_id, target_, indication_, *args, **kwargs):
            s = frozen.get(card_id)
            if not _real_summary(s):
                return None                       # → resolve_cards marks the card _missing (honest)
            return copy.deepcopy(s)               # deepcopy: run.py must not mutate the shared fixture
        return _read_live

    import tempfile
    out_dir = Path(tempfile.mkdtemp(prefix=f"ts-{pair_id}-"))
    mp = pytest.MonkeyPatch()
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)   # else resolve_cards short-circuits to stubs
    mp.setattr(skc, "_import_dispatcher", _fake_dispatcher_factory)
    mp.setattr(sys, "argv", ["run.py", "--target", target, "--indication", indication,
                             "--out", str(out_dir)])
    try:
        runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit as e:                        # run.py ends in sys.exit(run_wired_skill(...))
        assert e.code in (0, None), f"run.py exited non-zero ({e.code}) on the {pair_id} replay"
    finally:
        mp.undo()

    decision_path = out_dir / "decision.json"
    assert decision_path.exists(), f"run.py wrote no decision.json on the {pair_id} replay"
    d = json.loads(decision_path.read_text())
    _DECISION_CACHE[pair_id] = d
    return d


# ── the two curated fixtures ─────────────────────────────────────────────────────────────────────
CEACAM5 = ("ceacam5_coadread", "CEACAM5", "COADREAD")
TACSTD2 = ("tacstd2_coadread", "TACSTD2", "COADREAD")


@pytest.mark.parametrize("pair_id,target,indication", [CEACAM5, TACSTD2],
                         ids=["ceacam5", "tacstd2"])
def test_fixture_is_nonvacuous(pair_id, target, indication):
    """Guard against a stale/broken freeze reading green: both curated pairs resolve all 10 cards, so
    require >=5 to carry a real summary. A freeze that silently produced errors/empties fails here."""
    frozen = _load_fixture(pair_id)
    real = [cid for cid, s in frozen.items() if _real_summary(s)]
    assert len(real) >= 5, (
        f"only {len(real)}/{len(frozen)} frozen cards carry a real summary for {pair_id} — refreeze "
        f"against live S3 (freeze_fixture.py). Real cards: {sorted(real)}")


@pytest.mark.parametrize("pair_id,target,indication", [CEACAM5, TACSTD2],
                         ids=["ceacam5", "tacstd2"])
def test_verdict_does_not_collapse(pair_id, target, indication):
    """THE VERDICT-PATH DRIFT GUARD (the half no synthetic test covers): rules fire over the REAL
    frozen summaries. Both curated targets are strongly tumor-associated in COADREAD, so the resolved
    selectivity_class must be a real selective outcome with a driving rule — NEVER a collapsed
    insufficient/data_unavailable (which is what a reader renaming a rule-keyed field would cause)."""
    d = _decision(pair_id, target, indication)
    assert d["skill"] == "tumor-selectivity"
    h = d.get("headline") or {}
    cls = h.get("selectivity_class")
    assert cls not in _COLLAPSED, (
        f"selectivity_class={cls!r} collapsed for {target}/{indication} — suspect a rule that stopped "
        f"firing because a reader renamed a field it keys on (the false-negative collapse this replay "
        f"exists to catch).")
    assert cls in _SELECTIVE_OUTCOMES, (
        f"selectivity_class={cls!r} is not a selective outcome for {target}/{indication} "
        f"(expected one of {sorted(_SELECTIVE_OUTCOMES)}).")
    assert h.get("driving_rule_id"), "resolved a verdict but driving_rule_id is empty — inconsistent spine."


def test_clean_target_retains_selectivity_no_false_veto():
    """CEACAM5/COADREAD has a CLEAN window (no veto arm fires): the resolved verdict must EQUAL the raw
    axis-A class (no downgrade), be in the axis-A selective family, and NO normal-breadth veto rule may
    appear in the fired set. Guards a veto FALSELY firing (over-downgrading a real target)."""
    d = _decision(*CEACAM5)
    h = d.get("headline") or {}
    assert h.get("selectivity_class") in _AXIS_A_SELECTIVE, (
        f"CEACAM5 resolved {h.get('selectivity_class')!r}, not an axis-A selective class — a veto "
        f"wrongly downgraded a clean-window target (or the axis-A rule stopped firing).")
    assert h.get("selectivity_class") == h.get("axis_a_selectivity_class"), (
        f"CEACAM5 resolved {h.get('selectivity_class')!r} != raw axis-A {h.get('axis_a_selectivity_class')!r} "
        f"— a normal-breadth veto fired on a clean-window target (false downgrade).")
    fired = {r.get("rule_id") for r in d.get("fired_rules", [])}
    assert not (fired & _VETO_RULES), (
        f"a normal-breadth veto rule fired for clean-window CEACAM5: {sorted(fired & _VETO_RULES)}.")


def test_broadly_normal_target_is_downgraded_by_veto():
    """THE CROWN-JEWEL GUARD (silent veto-death = false positive): TACSTD2/TROP2 is broadly expressed
    across normal epithelia — axis-A reads strong_tumor_selective, but the normal-breadth veto must
    downgrade it to selective_but_broadly_normal end-to-end. If a veto-card reader drifts so the veto
    rule stops firing, TROP2 would wrongly read tumor_selective and this test goes red — the exact
    protection the synthetic tests cannot give (they inject the veto rule-id directly)."""
    d = _decision(*TACSTD2)
    h = d.get("headline") or {}
    assert h.get("axis_a_selectivity_class") in _AXIS_A_SELECTIVE, (
        f"TACSTD2 raw axis-A class is {h.get('axis_a_selectivity_class')!r}, not selective — the "
        f"fixture no longer exercises the veto (axis-A rule drift?); refreeze/re-curate.")
    assert h.get("selectivity_class") == "selective_but_broadly_normal", (
        f"TACSTD2 resolved {h.get('selectivity_class')!r}, expected selective_but_broadly_normal — the "
        f"normal-breadth veto stopped firing over the real summaries (SILENT VETO DEATH → a broadly-"
        f"normal gene would nominate as tumor_selective).")
    assert h.get("selectivity_class") != h.get("axis_a_selectivity_class"), (
        "the veto downgrade must change the class vs the raw axis-A call (else the clamp is a no-op).")
    assert h.get("driving_rule_id") in _VETO_RULES, (
        f"TACSTD2 driving_rule_id={h.get('driving_rule_id')!r} is not a normal-breadth veto rule.")


@pytest.mark.parametrize("pair_id,target,indication", [CEACAM5, TACSTD2],
                         ids=["ceacam5", "tacstd2"])
def test_headline_block_present_and_wellformed(pair_id, target, indication):
    """The canonical HEADLINE block (verdict + confidence + top tension) is emitted, non-degraded, and
    carries the RESOLVED selectivity_class + a confidence level + the four WIN/DIST/INT/SAFE claim axes
    in the hero. Verdict-INERT: verdict.call must equal the skill's resolved selectivity_class (the block
    never moves the veto spine)."""
    d = _decision(pair_id, target, indication)
    h = d.get("headline") or {}
    block = h.get("headline_block")
    assert isinstance(block, dict) and block, f"headline_block missing/empty on the {pair_id} replay"
    # non-degraded: the best-effort enrich must not have caught an exception building the block
    assert "headline_block" not in (h.get("_enrichment_errors") or {}), (
        f"headline_block degraded: {(h.get('_enrichment_errors') or {}).get('headline_block')!r}")
    # verdict-inert: the block's canonical verdict == the skill's own resolved selectivity_class
    assert block["verdict"]["call"] == h.get("selectivity_class")
    assert block["verdict"]["gate"] == "selectivity"
    assert block["verdict"]["phrase"]                      # a curated human phrase, never empty
    assert block["verdict"]["polarity"] in {"positive", "negative", "neutral"}
    # confidence in the canonical vocabulary
    assert block["confidence"]["level"] in {"strong", "moderate", "weak", "insufficient"}
    # the hero surfaces the four selectivity claim axes in order
    assert [a["key"] for a in block["hero"]["axes"]] == ["WIN", "DIST", "INT", "SAFE"]
    # deterministic one-sentence headline text is always available (not the LLM narration)
    assert isinstance(block["headline_text"], str) and block["headline_text"].endswith(".")


def test_headline_block_veto_surfaces_normal_breadth_tension():
    """TACSTD2/TROP2 is downgraded by the normal-breadth veto (selective_but_broadly_normal) — the
    headline block must colour the verdict NEGATIVE and surface the normal-breadth veto as the top
    tension (the skill-specific tension_extra the per-axis claim conflicts don't carry)."""
    d = _decision(*TACSTD2)
    block = ((d.get("headline") or {}).get("headline_block")) or {}
    assert block.get("verdict", {}).get("call") == "selective_but_broadly_normal"
    assert block["verdict"]["polarity"] == "negative"
    tension = block.get("top_tension") or {}
    assert tension.get("source") == "normal_breadth_veto", (
        f"expected the normal-breadth veto to win the tension slot for TROP2, got {tension!r}")


@pytest.mark.parametrize("pair_id,target,indication", [CEACAM5, TACSTD2],
                         ids=["ceacam5", "tacstd2"])
def test_headline_resolves_broadly(pair_id, target, indication):
    """Headline drift floor: a reader field-name drift that silently nulled a block of `_headline`
    reads would collapse many values to None. Both pairs resolve ~40/41 headline fields; a
    conservative floor of >=20 fails hard on a block-nulling drift while leaving refresh headroom."""
    h = _decision(pair_id, target, indication).get("headline") or {}
    non_null = [k for k, v in h.items() if v not in (None, "", [], "data_unavailable")]
    assert len(non_null) >= 20, (
        f"only {len(non_null)}/{len(h)} headline fields resolved for {target}/{indication} — suspect a "
        f"reader field-name drift (_headline get -> None). Non-null keys: {sorted(non_null)}")
