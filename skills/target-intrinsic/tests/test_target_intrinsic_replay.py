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
# The committed FULL-decision golden that freeze_golden_decision.py writes from THIS SAME offline
# replay path (json.dumps(indent=2, sort_keys=True)). Byte-compared below.
GOLDEN = SKILL_DIR / "tests" / "fixtures" / "target_intrinsic_egfr_full_decision.json"

# run.py resolves _skills_common by inserting SKILLS_ROOT on sys.path; do it here too so the test
# can import + monkeypatch the SAME module object run.py will use (sys.modules cache).


def _load_fixture() -> dict:
    if not FIXTURE.exists():
        pytest.skip(f"no frozen EGFR fixture at {FIXTURE} — run freeze_fixture.py against live S3")
    return yaml.safe_load(FIXTURE.read_text()) or {}


def _real_summary(s) -> bool:
    """A frozen entry is a REAL reader summary (not a freeze/dispatcher error, not empty)."""
    return isinstance(s, dict) and bool(s) and not s.get("_freeze_error") and not s.get("_dispatcher_returned_none")


def replay_decision(out_dir: Path, target: str = "EGFR") -> dict:
    """Run the ACTUAL run.py end-to-end with the live dispatcher replaced by the frozen fixture; return
    the parsed decision.json. Importable so freeze_golden_decision.py regenerates the committed
    full-decision golden through the SAME offline path this test exercises (no second wiring to drift)."""
    frozen = _load_fixture()

    import _skills_common as skc

    def _fake_dispatcher_factory():
        def _read_live(card_id, target, indication, *args, **kwargs):
            s = frozen.get(card_id)
            if not _real_summary(s):
                return None  # → resolve_cards marks the card _missing (honest)
            return copy.deepcopy(s)  # deepcopy: run.py must not mutate the shared fixture

        return _read_live

    mp = pytest.MonkeyPatch()
    # FRAMEWORK_HEALTH_SMOKE would short-circuit resolve_cards to synthetic empties — force it off so
    # we exercise the real resolve→headline path over the frozen summaries.
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    mp.setattr(skc, "_import_dispatcher", _fake_dispatcher_factory)
    mp.setattr(sys, "argv", ["run.py", "--target", target, "--out", str(out_dir)])
    try:
        runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit as e:  # run.py ends in sys.exit(run_wired_skill(...))
        assert e.code in (0, None), f"run.py exited non-zero ({e.code}) on the frozen {target} replay"
    finally:
        mp.undo()

    decision_path = out_dir / "decision.json"
    assert decision_path.exists(), f"run.py wrote no decision.json on the frozen {target} replay"
    return json.loads(decision_path.read_text())


@pytest.fixture(scope="module")
def egfr_decision(tmp_path_factory):
    """The frozen-fixture replay emit (module-scoped: one run.py execution per test session)."""
    return replay_decision(tmp_path_factory.mktemp("ti-egfr-replay"))


def _cards_from_runpy() -> list[str]:
    """run.py's CARDS literal (AST-parsed — no import, no dispatcher)."""
    import ast

    tree = ast.parse(RUN_PY.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "CARDS" for t in node.targets):
            return [e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    raise AssertionError("CARDS literal not found in run.py")


def test_fixture_covers_the_whole_roster():
    """The fixture must carry a REAL summary for EVERY card in CARDS — no silent partial freeze.

    Replaces the old `>= 12 real` floor, which let a stale snapshot pass while missing whole cards: the
    fixture shipped 19/20 (no `measured-potency-tractability`) for ~3 weeks, so the offline replay never
    exercised that card's headline reads or its sub-group panel source at all. EGFR resolves 20/20 live,
    so anything less means a stale or broken freeze (re-run freeze_fixture.py with AWS_PROFILE=cbg).
    A card that becomes legitimately unresolvable for EGFR is a DATA regression to chase, not to tolerate
    here."""
    frozen = _load_fixture()
    cards = _cards_from_runpy()
    missing = [c for c in cards if c not in frozen]
    assert not missing, (
        f"frozen fixture is missing {len(missing)} of the {len(cards)} wired cards: {missing} — re-freeze "
        f"(AWS_PROFILE=cbg pixi run python skills/target-intrinsic/tests/freeze_fixture.py)."
    )
    not_real = [c for c in cards if not _real_summary(frozen.get(c))]
    assert not not_real, (
        f"{len(not_real)}/{len(cards)} frozen cards carry no real summary: {not_real} — re-freeze, or "
        f"chase the reader/data regression that made them unresolvable for EGFR."
    )


def test_replay_conforms_to_data_product_schema(egfr_decision):
    """LOAD-BEARING output-drift guard: the FRESH run.py emit must validate against the finalized
    data-product schema. Confirms the gateless-descriptive shape (skill_report.call null, role
    descriptive) + the PANCANCER/indication envelope. CI-fail-not-skip."""
    import os

    from _skills_common.data_product_contract import conformance_errors, load_schema, schema_path

    schema = load_schema("target-intrinsic")
    if schema is None:
        reason = f"data-product schema not found at {schema_path('target-intrinsic')}"
        pytest.fail(reason + " [CI]") if os.environ.get("CI") else pytest.skip(reason)
    errors = conformance_errors(schema, egfr_decision)
    assert not errors, "FRESH replay emit violates the data-product schema:\n  " + "\n  ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:15]
    )


def test_replay_identity_and_verdict_free(egfr_decision):
    """Identity resolves and the descriptive (verdict-free) contract holds on the replayed run."""
    assert egfr_decision["skill"] == "target-intrinsic"
    assert (egfr_decision.get("headline") or {}).get("target_symbol") == "EGFR"
    # descriptive skill: no top-level verdict spine
    assert egfr_decision.get("verdict") in (None, "descriptive", "none"), (
        f"target-intrinsic is verdict-free; got verdict={egfr_decision.get('verdict')!r}"
    )


def test_replay_domain_modality_not_removal_favored(egfr_decision):
    """P2.1 regression (end-to-end, offline): EGFR is a multi-domain RTK + canonical INHIBITOR target;
    the class-driven heuristic must NOT call it removal_favored."""
    klass = (egfr_decision.get("headline") or {}).get("modality_implication_class")
    assert klass != "removal_favored", (
        f"EGFR modality_implication_class={klass!r}: the multi-domain-enzyme heuristic mislabelled a "
        f"well-drugged inhibitor target as degrader-favored."
    )


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
        f"Non-null keys: {sorted(non_null)}"
    )


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
        f"headline_block degraded on the EGFR replay: {(h.get('_enrichment_errors') or {}).get('headline_block')}"
    )
    blk = h.get("headline_block")
    assert isinstance(blk, dict), "no headline_block on the EGFR replay"
    assert blk["verdict"]["call"] is None  # gateless — descriptive, no verdict token
    assert isinstance(blk["verdict"]["phrase"], str) and blk["verdict"]["phrase"]
    assert blk["verdict"]["gate"] == "target_intrinsic"
    assert blk["verdict"]["polarity"] == "neutral"  # a descriptive lens has no positive/negative call
    assert blk["confidence"]["level"] in ("strong", "moderate", "weak", "insufficient")
    assert [a["key"] for a in blk["hero"]["axes"]] == ["MODALITY_ROUTING", "TRACTABILITY_PRECEDENT"]
    assert blk["headline_text"].endswith(".")


def test_replay_subgroup_panel_reads_the_spec_declared_fields(egfr_decision):
    """DETERMINISM guard for the signals-first panel: every sub-group source must carry the value of the
    field run.py's `_TARGET_INTRINSIC_SUBGROUP_READER` declares — not whichever `*_class` key happened to
    come first in the summary dict.

    The regression this pins: with no explicit spec, derive_subgroups used `_heuristic_reader` (first
    `*_class` in DICT ORDER), so the live run bound `shed_liability_class` / `measured_bioactivity_class`
    while this replay — same evidence, fixture re-serialized sorted — bound `measured_shed_class` /
    `chembl_approved_engagement_class`. Two different panels from identical data, and the offline guard
    could not see the tokens the live panel actually shows."""
    import ast

    frozen = _load_fixture()
    tree = ast.parse(RUN_PY.read_text())
    spec_by_mt = next(
        ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(getattr(t, "id", None) == "_TARGET_INTRINSIC_SUBGROUP_READER" for t in n.targets)
    )
    from _skills_common.subgroup_derivation import _card_meta

    field_by_card = {}
    for cid in frozen:
        mt, _tier = _card_meta(cid)
        spec = spec_by_mt.get(mt)
        if spec:
            field_by_card[cid] = spec["class"]

    panel = (egfr_decision.get("headline") or {}).get("subgroup_signals") or {}
    checked = 0
    for sg, block in panel.items():
        if not isinstance(block, dict):
            continue
        for src in block.get("sources") or []:
            cid = src.get("card")
            field = field_by_card.get(cid)
            assert field, f"{sg} source {cid} has no reader-spec entry — it bound via the heuristic fallback."
            assert src.get("value") == (frozen.get(cid) or {}).get(field), (
                f"{sg}/{cid}: panel value {src.get('value')!r} != frozen {field}="
                f"{(frozen.get(cid) or {}).get(field)!r} — the panel is reading a different field than the "
                f"reader spec declares."
            )
            checked += 1
    assert checked == 11, f"expected 11 panel sources on the EGFR replay, checked {checked}"


def test_replay_intrinsic_confirmation_caveat_guards_egfr(egfr_decision):
    """v1.6.0 verdict-INERT surface (offline CI guard): EGFR is a co-crystal-confirmed, approved-drug kinase
    → the intrinsic_confirmation_caveat must resolve the MILDER experimentally_confirmed_intrinsic_property
    GUARD (never demoted), and intrinsic_provenance must confirm the property + flag the OT double-count."""
    h = egfr_decision.get("headline") or {}
    cav = h.get("intrinsic_confirmation_caveat")
    assert isinstance(cav, dict), "no intrinsic_confirmation_caveat on the EGFR replay"
    assert cav["reason"] == "experimentally_confirmed_intrinsic_property", (
        f"EGFR (approved-drug, co-crystal) must be GUARDED, not flagged inflated; got {cav['reason']!r}"
    )
    prov = h.get("intrinsic_provenance") or {}
    assert prov.get("experimentally_confirmed_actionable_property") is True
    assert prov.get("ot_composite_double_counts_dedicated_cards") is True


# ---------------------------------------------------------------------------
# Committed-golden byte-drift guard (credential-less → runs in PR CI, never skips)
# ---------------------------------------------------------------------------
# Fields that legitimately vary run-to-run (wall-clock stamp, timings, and the git-HEAD provenance
# stamp). These are the ONLY nondeterministic leaves in a fresh replay: generated_at + run_health
# timings are wall-clock; provenance.skills_repo_sha records the repo HEAD at freeze/replay time, so
# it necessarily differs between the freeze commit and CI's HEAD. Normalizing exactly these lets the
# guard fail on EMIT-SHAPE drift while staying stable across runs and commits.
_VOLATILE_TOP = ("generated_at",)
_VOLATILE_RUN_HEALTH = ("compute_secs", "read_secs", "total_secs")
_VOLATILE_PROVENANCE = ("skills_repo_sha",)


def _strip_volatile(decision: dict) -> dict:
    d = copy.deepcopy(decision)
    for k in _VOLATILE_TOP:
        d.pop(k, None)
    rh = d.get("run_health")
    if isinstance(rh, dict):
        for k in _VOLATILE_RUN_HEALTH:
            rh.pop(k, None)
    prov = d.get("provenance")
    if isinstance(prov, dict):
        for k in _VOLATILE_PROVENANCE:
            prov.pop(k, None)
    return d


def _leaves(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, f"{prefix}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _leaves(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj


def _drift(committed, rebuilt) -> list[str]:
    a, b = dict(_leaves(committed)), dict(_leaves(rebuilt))
    return sorted(
        f"{k}: committed={a.get(k, '<absent>')!r} rebuilt={b.get(k, '<absent>')!r}"
        for k in set(a) | set(b)
        if a.get(k, "<absent>") != b.get(k, "<absent>")
    )


def test_committed_full_golden_matches_a_fresh_replay(egfr_decision):
    """THE FIX for #1672's silent staleness: the committed FULL-decision golden must byte-equal a fresh
    offline replay (modulo wall-clock stamp + timings). This runs credential-less in PR CI, so — unlike
    the LIVE golden (test_target_intrinsic_golden.py, which SKIPs without S3) — it NEVER skips: any
    emit-shape drift that lands without a refreeze reds here loudly instead of accumulating unseen.
    To fix a RED: refreeze via `pixi run python skills/target-intrinsic/tests/freeze_golden_decision.py`
    and commit the diff (that diff IS the review artifact for an output-shape change)."""
    assert GOLDEN.exists(), (
        f"committed golden missing at {GOLDEN} — regenerate with "
        f"`pixi run python skills/target-intrinsic/tests/freeze_golden_decision.py`"
    )
    committed = _strip_volatile(json.loads(GOLDEN.read_text()))
    fresh = _strip_volatile(egfr_decision)
    # Canonicalize through the same serializer freeze_golden_decision.py uses, so the comparison is on
    # exactly the committed bytes (types coalesced: a tuple → list once dumped).
    committed = json.loads(json.dumps(committed, sort_keys=True))
    fresh = json.loads(json.dumps(fresh, sort_keys=True))
    drift = _drift(committed, fresh)
    assert not drift, (
        f"{GOLDEN.name} is STALE vs a fresh offline replay ({len(drift)} leaves drifted). "
        f"Refreeze: `pixi run python skills/target-intrinsic/tests/freeze_golden_decision.py`.\n"
        + "\n".join(drift[:20])
    )
