"""OFFLINE verdict-replay of frozen tractability-small-molecule dossiers — the drift guard this skill lacked.

tractability-small-molecule is VERDICT-BEARING (druggability_snapshot via the shared resolver) and has a
DOCUMENTED reader-drift history: a 2026-08-09 fix caught that the headline read the WRONG field
names (activity_class / concordance_class instead of prism_activity_class / crispr_prism_concordance_class),
so two chemical facts were ALWAYS None and the LLM synthesis prompt was starved — a silent reader drift no
synthetic test caught. Its existing tests feed the resolver SYNTHETIC fired-sets (test_snapshot_ladder /
test_resolver_oracle_equivalence), so a card method RENAMING a field a rule keys on passes green while in
production the rule stops firing and the verdict silently changes class. No existing test runs `fired_rules`
over a real summary.

This replays the REAL reader summaries frozen by freeze_fixture.py (run once against live S3) THROUGH THE
REAL run.py — only the live dispatcher is monkeypatched, so production CARDS + the intracellular_intrinsic
rule-firing + the shared tractability_small_molecule resolver + the degrader-lens projection execute exactly
as in a real run. It fails deterministically, credential-less, on the SAME reader drift a live run would.

Three curated fixtures pin distinct rungs of the druggability ladder, each exercising a DIFFERENT card reader:
  - EGFR / COADREAD  — well_covered (e7-triangulated-target-engaged-supportive): chemical + genetic +
    structural evidence all agree. The top, most-composite rung — if ANY of the three legs' readers drift,
    EGFR drops out of well_covered → red.
  - BRAF / COADREAD  — chemically_active (known-drug-approved-antineoplastic-sm-supportive): the known-drug
    (DGIdb) pharmacology leg.
  - FOXA1 / COADREAD — structurally_ligandable (ligandability-predicted-sm-supportive): the structure-
    features-static forward-ligandability leg (predicted pocket, no chemical).

Plus a direct guard on the field-drift bug: the chemical-fact headline fields must resolve non-null.
The frozen fixtures are refreshed by the nightly-live re-freeze (card-behavior-matrix-nightly). Mirror of
tumor-selectivity's replay.
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

if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

# A resolved druggability_snapshot must never collapse to these for a target with real chemical/genetic data.
_COLLAPSED = {None, "", "insufficient"}
# The positive tractability outcomes the resolver can emit (grep of tractability_small_molecule.resolver.yaml).
_TRACTABLE = {
    "well_covered",
    "chemically_confirmed_genetic",
    "chemically_active",
    "measured_potent_ligand",
    "structurally_ligandable",
    "tool_compound_only",
    "clinical_precedent_only",
    "weakly_active",
}


def _real_summary(s) -> bool:
    return isinstance(s, dict) and bool(s) and not s.get("_freeze_error") and not s.get("_dispatcher_returned_none")


def _load_fixture(pair_id: str) -> dict:
    fx = FIXTURES / f"{pair_id}.yaml"
    if not fx.exists():
        pytest.skip(f"no frozen fixture at {fx} — run freeze_fixture.py against live S3")
    return yaml.safe_load(fx.read_text()) or {}


_DECISION_CACHE: dict = {}


def _decision(pair_id: str, target: str, indication: str) -> dict:
    if pair_id in _DECISION_CACHE:
        return _DECISION_CACHE[pair_id]
    frozen = _load_fixture(pair_id)

    import _skills_common as skc

    def _fake_dispatcher_factory():
        def _read_live(card_id, target_, indication_, *args, **kwargs):
            s = frozen.get(card_id)
            if not _real_summary(s):
                return None
            return copy.deepcopy(s)

        return _read_live

    import tempfile

    out_dir = Path(tempfile.mkdtemp(prefix=f"tsm-{pair_id}-"))
    mp = pytest.MonkeyPatch()
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    mp.setattr(skc, "_import_dispatcher", _fake_dispatcher_factory)
    mp.setattr(sys, "argv", ["run.py", "--target", target, "--indication", indication, "--out", str(out_dir)])
    try:
        runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit as e:
        assert e.code in (0, None), f"run.py exited non-zero ({e.code}) on the {pair_id} replay"
    finally:
        mp.undo()

    decision_path = out_dir / "decision.json"
    assert decision_path.exists(), f"run.py wrote no decision.json on the {pair_id} replay"
    d = json.loads(decision_path.read_text())
    _DECISION_CACHE[pair_id] = d
    return d


# ── the three curated fixtures (pair_id, target, indication, expected_verdict) ────────────────────
EGFR = ("egfr_coadread", "EGFR", "COADREAD", "well_covered")
BRAF = ("braf_coadread", "BRAF", "COADREAD", "chemically_active")
FOXA1 = ("foxa1_coadread", "FOXA1", "COADREAD", "structurally_ligandable")
ALL = [EGFR, BRAF, FOXA1]


@pytest.mark.parametrize("pair_id,target,indication,_exp", ALL, ids=[p[1].lower() for p in ALL])
def test_replay_conforms_to_data_product_schema(pair_id, target, indication, _exp):
    """LOAD-BEARING output-drift guard: the FRESH run.py emit must validate against the finalized
    data-product schema (static golden trimmed → this is the conformance target). CI-fail-not-skip."""
    import os
    from _skills_common.data_product_contract import conformance_errors, load_schema, schema_path

    schema = load_schema("tractability-small-molecule")
    if schema is None:
        reason = f"data-product schema not found at {schema_path('tractability-small-molecule')}"
        pytest.fail(reason + " [CI]") if os.environ.get("CI") else pytest.skip(reason)
    errors = conformance_errors(schema, _decision(pair_id, target, indication))
    assert not errors, f"FRESH {pair_id} emit violates the data-product schema:\n  " + "\n  ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:15]
    )


@pytest.mark.parametrize("pair_id,target,indication,_exp", ALL, ids=[p[1].lower() for p in ALL])
def test_fixture_is_nonvacuous(pair_id, target, indication, _exp):
    """Guard against a stale/broken freeze reading green: each curated target resolves most of the 7-card
    roster. Require >=5 to carry a real summary."""
    frozen = _load_fixture(pair_id)
    real = [cid for cid, s in frozen.items() if _real_summary(s)]
    assert len(real) >= 5, (
        f"only {len(real)}/{len(frozen)} frozen cards carry a real summary for {pair_id} — refreeze "
        f"against live S3 (freeze_fixture.py). Real cards: {sorted(real)}"
    )


@pytest.mark.parametrize("pair_id,target,indication,expected", ALL, ids=[p[1].lower() for p in ALL])
def test_verdict_matches_expected(pair_id, target, indication, expected):
    """THE VERDICT-PATH DRIFT GUARD: rules fire over the REAL frozen summaries and the shared
    tractability_small_molecule resolver runs. Each curated target's resolved druggability_snapshot must
    equal its pinned rung — a reader field rename that stops a rule firing changes it and fails here."""
    d = _decision(pair_id, target, indication)
    assert d["skill"] == "tractability-small-molecule"
    h = d.get("headline") or {}
    v = h.get("druggability_snapshot")
    assert v not in _COLLAPSED, (
        f"druggability_snapshot={v!r} collapsed for {target}/{indication} — a rule stopped firing "
        f"(reader field rename?)."
    )
    assert v == expected, f"druggability_snapshot={v!r} for {target}/{indication}, expected {expected!r}."
    assert h.get("driving_rule_id"), "resolved a verdict but driving_rule_id is empty — inconsistent spine."


def test_egfr_triangulated_top_rung():
    """CROWN-JEWEL GUARD: EGFR resolves well_covered — the triangulated top rung requiring chemical +
    genetic + structural evidence to agree. If ANY of the three legs' readers drift so its rule stops
    firing, EGFR drops out of well_covered and this test goes red."""
    d = _decision(*EGFR[:3])
    h = d.get("headline") or {}
    assert h.get("druggability_snapshot") == "well_covered", (
        f"EGFR resolved {h.get('druggability_snapshot')!r}, not well_covered — a chemical/genetic/"
        f"structural leg's reader drifted so the triangulation rung stopped firing."
    )
    assert h.get("druggability_snapshot") in _TRACTABLE


@pytest.mark.parametrize("pair_id,target,indication,expected", ALL, ids=[p[1].lower() for p in ALL])
def test_headline_block_present_and_consistent(pair_id, target, indication, expected):
    """CANONICAL HEADLINE guard: every replay emits a non-degraded headline_block whose canonical verdict
    matches the druggability spine, a valid confidence level, and a 5-axis hero (POTENCY/ACTIVITY/STRUCT/
    DRUG/DEGRADER). The block is a verdict-INERT projection — this asserts it rode the spine intact
    (no _enrichment_errors) and did not perturb druggability_snapshot."""
    d = _decision(pair_id, target, indication)
    h = d.get("headline") or {}
    # the block built (best-effort emitter must have succeeded on real data)
    assert not (h.get("_enrichment_errors") or {}).get("headline_block"), (
        f"headline_block degraded for {target}: {(h.get('_enrichment_errors') or {}).get('headline_block')}"
    )
    block = h.get("headline_block")
    assert isinstance(block, dict) and block, f"no headline_block emitted for {target}"
    # canonical verdict.call tracks the druggability spine (single source of truth)
    verdict = block.get("verdict") or {}
    assert verdict.get("call") == h.get("druggability_snapshot") == expected
    assert verdict.get("gate") == "tractability_sm"
    assert verdict.get("polarity") == "positive"  # all three curated fixtures are tractable rungs
    assert verdict.get("phrase")  # a human phrase was produced
    # confidence is one of the canonical tiers
    assert (block.get("confidence") or {}).get("level") in {"strong", "moderate", "weak", "insufficient"}
    # deterministic headline_text present
    assert isinstance(block.get("headline_text"), str) and block["headline_text"].endswith(".")
    # hero surfaces exactly the 5 declared claim axes, in order
    hero = block.get("hero") or {}
    assert [a.get("key") for a in (hero.get("axes") or [])] == ["POTENCY", "ACTIVITY", "STRUCT", "DRUG", "DEGRADER"]


@pytest.mark.parametrize("pair_id,target,indication,_exp", [EGFR, BRAF], ids=["egfr", "braf"])
def test_chemical_fact_headline_fields_resolve(pair_id, target, indication, _exp):
    """DIRECT REGRESSION GUARD: a 2026-08-09 bug had the headline read the WRONG field
    names so prism_activity_class / prism_crispr_concord were ALWAYS None — silent, no test caught it.
    For a chemically-characterised target these two headline fields MUST resolve non-null; a reader
    rename that reintroduces the wrong-field-name drift fails here."""
    h = _decision(pair_id, target, indication).get("headline") or {}
    assert h.get("prism_activity_class") not in (None, "", "data_unavailable"), (
        f"{target} prism_activity_class is empty — the T5.1 wrong-field-name drift has reappeared "
        f"(headline reads a key the prism-compound-activity method no longer emits)."
    )
    assert h.get("prism_crispr_concord") not in (None, "", "data_unavailable"), (
        f"{target} prism_crispr_concord is empty — the T5.1 wrong-field-name drift has reappeared "
        f"(headline reads a key the prism-crispr-concordance method no longer emits)."
    )
