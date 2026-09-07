"""OFFLINE verdict-replay of frozen genomic-alteration-profile dossiers — the drift guard this skill lacked.

genomic-alteration-profile's existing tests (test_genomic_alteration_verdict.py + test_family_wise_fdr.py)
feed `_verdict` / `_apply_family_wise_fdr` SYNTHETIC inputs (hand-built `fired` rule-id lists + fabricated
card summaries carrying the run.py field names). That is tautological w.r.t. reader drift: if a card method
RENAMES an output field, the synthetic test still uses the run.py key and passes green, while in production a
target-contracts RULE that keys the renamed field stops firing — so the resolved genomic verdict SILENTLY
changes class. The dangerous direction is a driver→non-driver collapse: a confirmed_driver /
biomarker_stratified_dependency / recurrent_*_driver drops to passenger_pattern / insufficient, i.e. the
skill stops flagging a real oncogenic alteration (a nomination-moving false negative). No existing test runs
`fired_rules` over a REAL summary for this skill.

This replays the REAL reader summaries frozen by freeze_fixture.py (run once against live S3) THROUGH THE
REAL run.py — only the live dispatcher is monkeypatched, so production CARDS + the family-wise FDR
preprocessor + the intracellular_intrinsic rule-firing + the shared genomic_alteration resolver all
execute exactly as in a real run. It therefore fails deterministically, credential-less, on the SAME reader
drift a live run would.

Two curated fixtures pin canonical CRC drivers on DISTINCT axes:
  - KRAS / COADREAD — recurrent activating missense driver + a KRAS-mutant stratified-dependency signal;
    exercises the mutation-type + hotspot-frequency + stratified-dependency + alteration-role (GoF) reads
    that feed the confirmed_driver / biomarker_stratified_dependency rungs.
  - BRAF / COADREAD — recurrent V600E driver + variant-level oncogenicity + drug-response biomarker;
    a second, independent driver so a mutation-axis reader drift can't hide behind one target's idiosyncrasy.

Both are unambiguous COADREAD drivers, so the resolved genomic_alteration_profile must be a POSITIVE driver
class — never a passenger_pattern / insufficient collapse. The frozen fixtures are refreshed by the
nightly-live re-freeze (card-behavior-matrix-nightly), which guards the snapshots themselves against reader
drift. Mirror of the tumor-selectivity and tumor-presence replay tests.
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
FIXTURES = SKILL_DIR / "tests" / "fixtures"

# run.py resolves _skills_common by inserting SKILLS_ROOT on sys.path; do it here too so the test
# can import + monkeypatch the SAME module object run.py will use (sys.modules cache).
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

# Non-answers a resolved genomic verdict must never be for a KNOWN driver — the collapse set.
# passenger_pattern is included: a canonical driver reading as passenger is the false-negative this
# replay exists to catch (a rule stopped firing because a reader renamed a field it keys on).
_COLLAPSED = {None, "", "insufficient", "data_unavailable", "passenger_pattern"}

# The positive driver classes the genomic_alteration resolver can emit (grep of
# resolvers/genomic_alteration.resolver.yaml). A known driver must resolve to one of these.
_DRIVER_OUTCOMES = {
    "confirmed_driver",
    "multi_class_driver",
    "biomarker_stratified_dependency",
    "moderate_biomarker_dependency",
    "recurrent_amplification_driver",
    "recurrent_deletion_driver",
    "recurrent_fusion_driver",
    "drug_response_biomarker",
    "missense_dominant_pattern",
    "lof_dominant_pattern",
    "mixed_pattern",
    "recurrent_snv_driver",
}


def _real_summary(s) -> bool:
    """A frozen entry is a REAL reader summary (not a freeze/dispatcher error, not empty)."""
    return isinstance(s, dict) and bool(s) and not s.get("_freeze_error") and not s.get("_dispatcher_returned_none")


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
                return None  # → resolve_cards marks the card _missing (honest)
            return copy.deepcopy(s)  # deepcopy: run.py must not mutate the shared fixture

        return _read_live

    import tempfile

    out_dir = Path(tempfile.mkdtemp(prefix=f"gap-{pair_id}-"))
    mp = pytest.MonkeyPatch()
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)  # else resolve_cards short-circuits to stubs
    mp.setattr(skc, "_import_dispatcher", _fake_dispatcher_factory)
    mp.setattr(sys, "argv", ["run.py", "--target", target, "--indication", indication, "--out", str(out_dir)])
    try:
        runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit as e:  # run.py ends in sys.exit(main())
        assert e.code in (0, None), f"run.py exited non-zero ({e.code}) on the {pair_id} replay"
    finally:
        mp.undo()

    decision_path = out_dir / "decision.json"
    assert decision_path.exists(), f"run.py wrote no decision.json on the {pair_id} replay"
    d = json.loads(decision_path.read_text())
    _DECISION_CACHE[pair_id] = d
    return d


# ── the two curated fixtures ─────────────────────────────────────────────────────────────────────
KRAS = ("kras_coadread", "KRAS", "COADREAD")
BRAF = ("braf_coadread", "BRAF", "COADREAD")


@pytest.mark.parametrize("pair_id,target,indication", [KRAS, BRAF], ids=["kras", "braf"])
def test_replay_conforms_to_data_product_schema(pair_id, target, indication):
    """LOAD-BEARING output-drift guard: the FRESH run.py emit must validate against the finalized
    data-product schema. This skill hand-rolls main(); the emitter now builds run_health + provenance,
    so the fresh emit is a full envelope. Catches a dropped required key / an undeclared
    genomic_alteration_profile token. Static golden is trimmed → this is the conformance target."""
    import os
    from _skills_common.data_product_contract import conformance_errors, load_schema, schema_path

    schema = load_schema("genomic-alteration-profile")
    if schema is None:
        reason = f"data-product schema not found at {schema_path('genomic-alteration-profile')}"
        pytest.fail(reason + " [CI]") if os.environ.get("CI") else pytest.skip(reason)
    errors = conformance_errors(schema, _decision(pair_id, target, indication))
    assert not errors, f"FRESH {pair_id} emit violates the data-product schema:\n  " + "\n  ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:15]
    )


@pytest.mark.parametrize("pair_id,target,indication", [KRAS, BRAF], ids=["kras", "braf"])
def test_fixture_is_nonvacuous(pair_id, target, indication):
    """Guard against a stale/broken freeze reading green: both curated drivers resolve the bulk of the
    18-card roster (a few cards — fusion landscape/stratified — legitimately return data_unavailable for
    a non-fusion gene). Require >=10 to carry a real summary; a freeze that silently produced
    errors/empties fails here rather than passing the verdict guards vacuously."""
    frozen = _load_fixture(pair_id)
    real = [cid for cid, s in frozen.items() if _real_summary(s)]
    assert len(real) >= 10, (
        f"only {len(real)}/{len(frozen)} frozen cards carry a real summary for {pair_id} — refreeze "
        f"against live S3 (freeze_fixture.py). Real cards: {sorted(real)}"
    )


@pytest.mark.parametrize("pair_id,target,indication", [KRAS, BRAF], ids=["kras", "braf"])
def test_verdict_does_not_collapse(pair_id, target, indication):
    """THE VERDICT-PATH DRIFT GUARD (the half no synthetic test covers): rules fire over the REAL frozen
    summaries and the shared genomic_alteration resolver runs. Both curated targets are canonical COADREAD
    drivers, so the resolved genomic_alteration_profile must be a POSITIVE driver class with a driving
    rule — NEVER a passenger_pattern / insufficient collapse (what a reader renaming a rule-keyed field
    would cause)."""
    d = _decision(pair_id, target, indication)
    assert d["skill"] == "genomic-alteration-profile"
    h = d.get("headline") or {}
    cls = h.get("genomic_alteration_profile")
    assert cls not in _COLLAPSED, (
        f"genomic_alteration_profile={cls!r} collapsed for {target}/{indication} — suspect a rule that "
        f"stopped firing because a reader renamed a field it keys on (the driver→passenger false-negative "
        f"this replay exists to catch)."
    )
    assert cls in _DRIVER_OUTCOMES, (
        f"genomic_alteration_profile={cls!r} is not a positive driver class for known driver "
        f"{target}/{indication} (expected one of {sorted(_DRIVER_OUTCOMES)})."
    )
    assert h.get("driving_rule_id"), "resolved a verdict but driving_rule_id is empty — inconsistent spine."


@pytest.mark.parametrize("pair_id,target,indication", [KRAS, BRAF], ids=["kras", "braf"])
def test_headline_resolves_broadly(pair_id, target, indication):
    """Headline drift floor: a reader field-name drift that silently nulled a block of headline reads
    would collapse many values to None. The genomic headline carries ~30 fields across the mutation / CN /
    fusion / role / recurrence axes; a conservative floor of >=15 fails hard on a block-nulling drift while
    leaving refresh headroom (some axes are legitimately data_unavailable per target)."""
    h = _decision(pair_id, target, indication).get("headline") or {}
    non_null = [k for k, v in h.items() if v not in (None, "", [], "data_unavailable")]
    assert len(non_null) >= 15, (
        f"only {len(non_null)}/{len(h)} headline fields resolved for {target}/{indication} — suspect a "
        f"reader field-name drift (headline get -> None). Non-null keys: {sorted(non_null)}"
    )


# ── canonical HEADLINE block (verdict + confidence + top tension) ─────────────────────────────────
_VALID_CONFIDENCE = {"strong", "moderate", "weak", "insufficient"}
_GENOMIC_AXES = ("SNV", "CN", "FUS", "DEP")


@pytest.mark.parametrize("pair_id,target,indication", [KRAS, BRAF], ids=["kras", "braf"])
def test_headline_block_present_and_non_degraded(pair_id, target, indication):
    """The canonical headline_block is present, non-degraded (no _enrichment_errors), and internally
    consistent with the spine: verdict.call is the skill's resolved genomic_alteration_profile, the
    confidence.level is a valid tier, and the hero lists this skill's SNV/CN/FUS/DEP axes. Verdict-inert:
    verifies the block PROJECTS the spine, never that it changed it."""
    d = _decision(pair_id, target, indication)
    h = d.get("headline") or {}
    # the projection must not have degraded to an enrichment error
    assert (h.get("_enrichment_errors") or {}).get("headline_block") is None, (
        f"headline_block degraded for {target}/{indication}: {h.get('_enrichment_errors')}"
    )
    block = h.get("headline_block")
    assert isinstance(block, dict), f"no headline_block dict for {target}/{indication}"

    # verdict.call mirrors the resolved spine (verdict-inert projection, never a re-derivation)
    verdict = block.get("verdict") or {}
    assert verdict.get("call") == h.get("genomic_alteration_profile")
    assert verdict.get("gate") == "genomic_alteration"
    assert verdict.get("phrase")  # a human phrase was assigned
    assert verdict.get("polarity") in {"positive", "negative", "neutral"}

    # confidence.level is a valid tier
    assert (block.get("confidence") or {}).get("level") in _VALID_CONFIDENCE

    # the hero lists this skill's alteration axes, in order
    hero = block.get("hero") or {}
    assert [ax.get("key") for ax in (hero.get("axes") or [])] == list(_GENOMIC_AXES)

    # a deterministic headline sentence is always available (no live read / LLM)
    assert isinstance(block.get("headline_text"), str) and block["headline_text"].strip()
