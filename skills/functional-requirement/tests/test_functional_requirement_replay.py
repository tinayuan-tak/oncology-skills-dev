"""OFFLINE replay of the frozen KRAS/COADREAD dossier — the drift guard functional-requirement lacked.

All other FR tests feed `_verdict` SYNTHETIC fired-rule lists, so none can catch the reader-real-field
drift bug class (a card method renaming an output field → a get_card_field read resolves to None
SILENTLY; for a verdict-bearing skill a renamed field a RULE keys on collapses the verdict). This skill
has already shipped TWO such silent drift bugs (run.py v1.3.1). This replays the REAL reader summaries
frozen by freeze_fixture.py THROUGH THE REAL run.py (only the live dispatcher is monkeypatched), so
production CARDS + rule-firing + resolver + _headline all execute — failing deterministically,
credential-less, on the SAME drift a live run would.

Fixture: KRAS / COADREAD — the canonical dependency reference (bimodal → a positive dependency call;
also the compose-dashboard engine-equivalence anchor), stable across the 2026-08-13 classifier fixes.
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
RUN_PY = SKILL_DIR / "scripts" / "run.py"
FIXTURE = SKILL_DIR / "tests" / "fixtures" / "kras_coadread.yaml"
# NEGATIVE-DIRECTION fixture (issue #1833): a hand-constructed non-dependent target whose queried
# indication (COADREAD -> Bowel) is screened at adequate power but above the dependency cut, so the
# preprocessor writes indication_dependency_class == not_dependent_in_indication and the indication VETO
# rung (not-dependent-in-indication-killer, resolver rung 10) is exercised end-to-end.
NEG_FIXTURE = SKILL_DIR / "tests" / "fixtures" / "not_dependent_in_indication.yaml"


# POSITIVE dependency calls (a real "yes, a dependency" verdict) — _DEPENDENCY_CALL_VERDICTS minus the
# negative calls (non_dependent, pan_essential_killer). Imported from run.py = single source.
_NEGATIVE_CALLS = {"non_dependent", "pan_essential_killer"}


def _load_fixture() -> dict:
    if not FIXTURE.exists():
        pytest.skip(f"no frozen fixture at {FIXTURE} — run freeze_fixture.py against live S3")
    return yaml.safe_load(FIXTURE.read_text()) or {}


def _real(s) -> bool:
    return isinstance(s, dict) and bool(s) and not s.get("_freeze_error") and not s.get("_dispatcher_returned_none")


def _positive_calls() -> set:
    return set(load_run_py(SKILL_DIR, "_fr_run_const")._DEPENDENCY_CALL_VERDICTS) - _NEGATIVE_CALLS


@pytest.fixture(scope="module")
def kras_decision(tmp_path_factory):
    frozen = _load_fixture()
    import _skills_common as skc

    def _factory():
        def _read(card_id, target, indication, *a, **k):
            s = frozen.get(card_id)
            return copy.deepcopy(s) if _real(s) else None

        return _read

    out_dir = tmp_path_factory.mktemp("fr-kras-replay")
    mp = pytest.MonkeyPatch()
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    mp.setattr(skc, "_import_dispatcher", _factory)
    mp.setattr(sys, "argv", ["run.py", "--target", "KRAS", "--indication", "COADREAD", "--out", str(out_dir)])
    try:
        runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit as e:
        assert e.code in (0, None), f"run.py exited non-zero ({e.code}) on the frozen KRAS replay"
    finally:
        mp.undo()
    decision_path = out_dir / "decision.json"
    assert decision_path.exists(), "run.py wrote no decision.json on the frozen KRAS replay"
    return json.loads(decision_path.read_text())


def _replay_decision(frozen_path: Path, target: str, indication: str, tmp_path_factory) -> dict:
    """Replay an arbitrary frozen card-summary fixture THROUGH THE REAL run.py (dispatcher monkeypatched),
    identical mechanics to the KRAS fixture. Shared so the positive (KRAS) and negative
    (not_dependent_in_indication) replays exercise the same production preprocessor->rule->resolver chain."""
    if not frozen_path.exists():
        pytest.skip(f"no frozen fixture at {frozen_path}")
    frozen = yaml.safe_load(frozen_path.read_text()) or {}
    import _skills_common as skc

    def _factory_read(card_id, tgt, ind, *a, **k):
        s = frozen.get(card_id)
        return copy.deepcopy(s) if _real(s) else None

    out_dir = tmp_path_factory.mktemp(f"fr-replay-{target}-{indication}")
    mp = pytest.MonkeyPatch()
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    mp.setattr(skc, "_import_dispatcher", lambda: _factory_read)
    mp.setattr(sys, "argv", ["run.py", "--target", target, "--indication", indication, "--out", str(out_dir)])
    try:
        runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit as e:
        assert e.code in (0, None), f"run.py exited non-zero ({e.code}) on the {frozen_path.name} replay"
    finally:
        mp.undo()
    decision_path = out_dir / "decision.json"
    assert decision_path.exists(), f"run.py wrote no decision.json on the {frozen_path.name} replay"
    return json.loads(decision_path.read_text())


@pytest.fixture(scope="module")
def not_dependent_decision(tmp_path_factory):
    return _replay_decision(NEG_FIXTURE, "SYNTHNDEP", "COADREAD", tmp_path_factory)


def test_negative_fixture_vetoes_in_indication(not_dependent_decision):
    """THE VETO-PATH DRIFT GUARD (issue #1833): the indication VETO direction had ZERO end-to-end
    coverage. `not_dependent_in_indication` appeared only in synthetic/direct-read tests that never drive
    the preprocessor->rule-firing->resolver chain, so a silent revert of the Stage-5b preprocessor would
    let a target that SHOULD be vetoed-in-indication fall through to the pooled verdict, UNCAUGHT.

    This replays a NON-dependent target whose queried indication (COADREAD -> Bowel) is screened at
    adequate power above the dependency cut. WITH the preprocessor: indication_dependency_class ==
    not_dependent_in_indication -> `not-dependent-in-indication-killer` (resolver rung 10) WINS ->
    dependency_verdict == not_dependent_in_indication. WITHOUT it (a no-op revert): the field is never
    written, the killer cannot fire, and the run falls through to the pooled `non-dependent-killer` ->
    non_dependent — so pinning the veto token + driving rule reds on exactly that revert."""
    assert not_dependent_decision["skill"] == "functional-requirement"
    h = not_dependent_decision.get("headline") or {}
    verdict = h.get("dependency_verdict")
    assert verdict == "not_dependent_in_indication", (
        f"dependency_verdict={verdict!r} — expected the indication VETO token 'not_dependent_in_indication'. "
        "A fall-through to the pooled 'non_dependent' means the indication killer stopped firing (preprocessor "
        f"no longer writing indication_dependency_class). driving_rule_id={h.get('driving_rule_id')!r}"
    )
    assert h.get("driving_rule_id") == "not-dependent-in-indication-killer", (
        f"driving_rule_id={h.get('driving_rule_id')!r} — expected 'not-dependent-in-indication-killer' "
        "(resolver rung 10, the measured indication-grain veto)."
    )
    # the by-scope indication rung must independently classify the veto (the _indication_lineage_read path)
    by = h.get("dependency_verdict_by_scope") or {}
    assert (by.get("indication") or {}).get("class") == "not_dependent_in_indication", (
        f"by_scope.indication.class={(by.get('indication') or {}).get('class')!r} — the independent "
        "_indication_lineage_read path disagrees with the resolver veto; the two indication reads have diverged."
    )


def test_fixture_is_nonvacuous():
    frozen = _load_fixture()
    real = [c for c, s in frozen.items() if _real(s)]
    assert len(real) >= 10, (
        f"only {len(real)}/{len(frozen)} frozen cards carry a real summary — refreeze (freeze_fixture.py). "
        f"Real: {sorted(real)}"
    )


def test_replay_conforms_to_data_product_schema(kras_decision):
    """LOAD-BEARING output-drift guard: the FRESH run.py emit must validate against the finalized
    data-product schema (the static golden is trimmed, so this — not it — is the conformance target).
    Catches a dropped required key / flipped role / an undeclared dependency_verdict token. CI-fail-not-skip."""
    import os

    from _skills_common.data_product_contract import conformance_errors, load_schema, schema_path

    schema = load_schema("functional-requirement")
    if schema is None:
        reason = f"data-product schema not found at {schema_path('functional-requirement')}"
        pytest.fail(reason + " [CI]") if os.environ.get("CI") else pytest.skip(reason)
    errors = conformance_errors(schema, kras_decision)
    assert not errors, "FRESH replay emit violates the data-product schema:\n  " + "\n  ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:15]
    )


def test_replay_verdict_is_a_positive_dependency_call(kras_decision):
    """THE VERDICT-PATH DRIFT GUARD: rules fire over the REAL frozen summaries. KRAS is a bona fide
    COADREAD dependency, so dependency_verdict must be a POSITIVE dependency call with a real driving
    rule — a reader field-rename that a rule keys on would collapse it to insufficient/non_dependent.

    PINS THE EXACT PROMOTED TOKEN (issue #1833): since the Stage-5b preprocessor went live (skills #1480,
    25e170eb) `_dependency_preprocess` writes `indication_dependency_class == selective_in_indication` for
    KRAS/COADREAD (Bowel IS an enriched lineage), so the indication rung `dependency-in-indication-
    selective-supportive` (resolver rung 4) WINS and the emitted verdict is `lineage_selective_in_indication`
    — NOT the pre-Stage-5b pooled `lineage_selective`. Membership in the positive set is too weak to catch a
    silent revert (BOTH tokens are positive); pinning the exact token + driving rule reds if the preprocessor
    stops writing the field, a rule keys on a renamed field, or the indication rung otherwise stops firing."""
    assert kras_decision["skill"] == "functional-requirement"
    h = kras_decision.get("headline") or {}
    verdict = h.get("dependency_verdict")
    assert verdict in _positive_calls(), (
        f"dependency_verdict={verdict!r} is not a positive dependency call for KRAS/COADREAD — suspect "
        f"a rule that stopped firing on a renamed reader field. driving_rule_id={h.get('driving_rule_id')!r}"
    )
    assert verdict == "lineage_selective_in_indication", (
        f"dependency_verdict={verdict!r} — expected the LIVE indication-grain token "
        "'lineage_selective_in_indication'. A collapse to the pre-Stage-5b pooled 'lineage_selective' means "
        "the indication rung stopped firing (preprocessor no longer writing indication_dependency_class, or a "
        f"rule keyed on a renamed reader field). driving_rule_id={h.get('driving_rule_id')!r}"
    )
    assert h.get("driving_rule_id") == "dependency-in-indication-selective-supportive", (
        f"driving_rule_id={h.get('driving_rule_id')!r} — expected the indication rung "
        "'dependency-in-indication-selective-supportive' (resolver rung 4). A different rule id means a higher-"
        "or lower-priority rung won, i.e. the indication verdict spine drifted."
    )
    # the headline_block projection MUST agree with the spine (verdict-inert projection contract)
    block = h.get("headline_block") or {}
    assert (block.get("verdict") or {}).get("call") == verdict, (
        "headline_block.verdict.call diverged from dependency_verdict — the projection is no longer inert."
    )


def test_replay_headline_resolves_broadly(kras_decision):
    """Headline drift floor: a reader field-name drift nulling a block of get_card_field reads would
    collapse many headline values to None. KRAS/COADREAD resolves ~18/19 fields; floor >=15."""
    h = kras_decision.get("headline") or {}
    non_null = [k for k, v in h.items() if v not in (None, "", [], "data_unavailable")]
    assert len(non_null) >= 15, (
        f"only {len(non_null)}/{len(h)} headline fields resolved for the frozen KRAS replay — suspect a "
        f"reader field-name drift (get_card_field -> None). Non-null: {sorted(non_null)}"
    )


def test_replay_by_scope_indication_is_honest(kras_decision):
    """Phase 3: dependency_verdict_by_scope reduces the pan-cancer lineage card to the QUERIED
    indication's lineage. For KRAS/COADREAD, Bowel IS a frozen enrichment hit → the indication rung is
    selective_in_indication, while the pan-cancer rung passes the pooled verdict through unchanged."""
    h = kras_decision.get("headline") or {}
    by = h.get("dependency_verdict_by_scope") or {}
    assert set(by) >= {"pan_cancer", "indication", "subtype"}, "by-scope layer missing a rung"
    # pan-cancer rung == the pooled verdict (verdict-inert: the reduction never moves the spine)
    assert by["pan_cancer"]["verdict"] == h.get("dependency_verdict")
    ind = by["indication"]
    assert ind["depmap_lineage"] == "Bowel"  # COADREAD → Bowel crosswalk
    assert ind["class"] == "selective_in_indication", (
        f"Bowel is a frozen enriched lineage for KRAS → expected selective_in_indication, got {ind['class']!r}"
    )


def test_replay_headline_block_present_and_wellformed(kras_decision):
    """The canonical HEADLINE block (verdict + confidence + top tension) is emitted, non-degraded, and
    carries the dependency verdict + a confidence level + the four claim axes in the hero. Verdict-INERT:
    verdict.call must equal the skill's dependency_verdict (the block never moves the spine)."""
    h = kras_decision.get("headline") or {}
    block = h.get("headline_block")
    assert isinstance(block, dict) and block, "headline_block missing/empty on the frozen KRAS replay"
    # non-degraded: the best-effort enrich must not have caught an exception building the block
    assert "headline_block" not in (h.get("_enrichment_errors") or {}), (
        f"headline_block degraded: {(h.get('_enrichment_errors') or {}).get('headline_block')!r}"
    )
    # verdict-inert: the block's canonical verdict == the skill's own dependency_verdict
    assert block["verdict"]["call"] == h.get("dependency_verdict")
    assert block["verdict"]["gate"] == "dependency"
    assert block["verdict"]["phrase"]  # a curated human phrase, never empty
    # confidence in the canonical vocabulary
    assert block["confidence"]["level"] in {"strong", "moderate", "weak", "insufficient"}
    # the hero surfaces the four dependency claim axes in order
    assert [a["key"] for a in block["hero"]["axes"]] == ["DEP", "SEL", "COND", "CHEM"]
    # deterministic one-sentence headline text is always available (not the LLM narration)
    assert isinstance(block["headline_text"], str) and block["headline_text"].endswith(".")
