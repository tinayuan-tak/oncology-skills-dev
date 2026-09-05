"""OFFLINE replay of the frozen EPCAM/COADREAD dossier — the drift guard tumor-presence lacked.

Every other tumor-presence test feeds `_verdict`/`_per_modality_verdicts`/`_headline` SYNTHETIC
inputs (hand-built `fired` rule-id lists + fabricated card summaries carrying the run.py field
names), so none can catch the reader-real-field-names drift bug class. For a VERDICT-BEARING skill
that class has two failure modes, neither covered before this test:
  (a) headline: a card renames an output field → the `get_card_field(...)` read resolves to None
      SILENTLY (get_card_field only raises on a bad card_id, not a bad field);
  (b) VERDICT: a card renames a field that a target-contracts RULE keys on → the rule stops firing →
      `presence_verdict` collapses to a false-negative insufficient/data_unavailable. No existing
      test runs `fired_rules` over a real summary, so (b) was entirely unguarded.

This replays the REAL reader summaries frozen by freeze_fixture.py (run once against live S3) THROUGH
THE REAL run.py — only the live dispatcher is monkeypatched, so production CARDS + the
intracellular_intrinsic rule-firing + the collapse ladder + `_headline` all execute exactly as in a
real run. It therefore fails deterministically, credential-less, on the SAME drift a live run would,
covering both (a) and (b). The frozen fixture is refreshed by the nightly-live re-freeze
(card-behavior-matrix-nightly), which guards the snapshot itself.

Fixture: EPCAM / COADREAD — a canonical, maximally-characterized epithelial surface antigen, broadly
present in colorectal tumor (a stable measured-positive), in the single indication with the fullest
bucket coverage (paired tumor-adjacent RNA, CPTAC COAD protein, single-cell, subtype shard). All 14
cards resolve and 5 of 7 buckets are measured, giving the strongest possible drift floor.
"""
from __future__ import annotations

import copy
import json
import os
import runpy
import sys
from pathlib import Path

import pytest
import yaml

from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"
FIXTURE = SKILL_DIR / "tests" / "fixtures" / "epcam_coadread.yaml"

# run.py resolves _skills_common by inserting SKILLS_ROOT on sys.path; do it here too so the test
# can import + monkeypatch the SAME module object run.py will use (sys.modules cache).
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))


def _load_fixture() -> dict:
    if not FIXTURE.exists():
        pytest.skip(f"no frozen fixture at {FIXTURE} — run freeze_fixture.py against live S3")
    return yaml.safe_load(FIXTURE.read_text()) or {}


def _real_summary(s) -> bool:
    """A frozen entry is a REAL reader summary (not a freeze/dispatcher error, not empty)."""
    return (isinstance(s, dict) and bool(s)
            and not s.get("_freeze_error") and not s.get("_dispatcher_returned_none"))


def _rna_presence_positive() -> frozenset:
    """The measured-positive RNA presence verdict set — imported from run.py (single source of truth),
    NOT re-listed here, so a change to the skill's positive vocabulary is reflected automatically."""
    return load_run_py(SKILL_DIR, "_tp_run_const")._RNA_PRESENCE_POSITIVE


@pytest.fixture(scope="module")
def epcam_decision(tmp_path_factory):
    """Run the ACTUAL run.py end-to-end on EPCAM/COADREAD with the live dispatcher replaced by the
    frozen fixture; return the parsed decision.json."""
    frozen = _load_fixture()

    import _skills_common as skc

    def _fake_dispatcher_factory():
        def _read_live(card_id, target, indication, *args, **kwargs):
            s = frozen.get(card_id)
            if not _real_summary(s):
                return None                       # → resolve_cards marks the card _missing (honest)
            return copy.deepcopy(s)               # deepcopy: run.py must not mutate the shared fixture
        return _read_live

    out_dir = tmp_path_factory.mktemp("tp-epcam-replay")
    mp = pytest.MonkeyPatch()
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)   # else resolve_cards short-circuits to stubs
    mp.setattr(skc, "_import_dispatcher", _fake_dispatcher_factory)
    mp.setattr(sys, "argv", ["run.py", "--target", "EPCAM", "--indication", "COADREAD",
                             "--out", str(out_dir)])
    try:
        runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit as e:                        # run.py ends in sys.exit(run_wired_skill(...))
        assert e.code in (0, None), f"run.py exited non-zero ({e.code}) on the frozen EPCAM replay"
    finally:
        mp.undo()

    decision_path = out_dir / "decision.json"
    assert decision_path.exists(), "run.py wrote no decision.json on the frozen EPCAM replay"
    return json.loads(decision_path.read_text())


def test_fixture_is_nonvacuous():
    """Guard against a stale/broken freeze reading green: EPCAM/COADREAD resolves all 14 cards, so
    require the bulk (>=12) to carry a real summary. A freeze that silently produced errors/empties
    must fail here, not pass by vacuity."""
    frozen = _load_fixture()
    real = [cid for cid, s in frozen.items() if _real_summary(s)]
    assert len(real) >= 12, (
        f"only {len(real)}/{len(frozen)} frozen cards carry a real summary — refreeze against live "
        f"S3 (freeze_fixture.py). Real cards: {sorted(real)}")


def test_replay_conforms_to_data_product_schema(epcam_decision):
    """LOAD-BEARING output-drift guard: the FRESH emit from the real run.py must validate against the
    finalized data-product schema. Unlike the static golden, this runs run.py end-to-end, so a code
    change that drops a required key, flips role/polarity, or emits an undeclared presence_verdict token
    fails here. Uses the shared _skills_common helper (SKILLS_ROOT is already on sys.path above).
    CI-liveness: absence of the schema FAILS in CI, SKIPS locally."""
    from _skills_common.data_product_contract import conformance_errors, load_schema, schema_path

    schema = load_schema("tumor-presence")
    if schema is None:
        reason = f"data-product schema not found at {schema_path('tumor-presence')}"
        pytest.fail(reason + " [CI]") if os.environ.get("CI") else pytest.skip(reason)
    errors = conformance_errors(schema, epcam_decision)
    assert not errors, "FRESH replay emit violates the data-product schema:\n  " + "\n  ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:15])


def test_replay_verdict_resolves_positive(epcam_decision):
    """THE VERDICT-PATH DRIFT GUARD (the half no synthetic test covers): rules fire over the REAL
    frozen summaries, so a reader renaming a field a rule keys on collapses the verdict — caught here.
    EPCAM is broadly present in colorectal tumor, so the collapsed presence_verdict must be a
    measured-positive RNA call with a real driving rule, NEVER insufficient/data_unavailable."""
    assert epcam_decision["skill"] == "tumor-presence"
    headline = epcam_decision.get("headline") or {}
    verdict = headline.get("presence_verdict")
    assert verdict in _rna_presence_positive(), (
        f"presence_verdict={verdict!r} is not a measured-positive RNA call for EPCAM/COADREAD — "
        f"suspect a rule that stopped firing because a reader renamed a field it keys on "
        f"(the false-negative collapse this replay exists to catch). driving_rule_id="
        f"{headline.get('driving_rule_id')!r}.")
    assert headline.get("driving_rule_id"), (
        "presence_verdict resolved positive but driving_rule_id is empty — inconsistent verdict spine.")


def test_replay_per_modality_buckets_measured(epcam_decision):
    """Per-bucket floor: rule-firing drift can break a bucket even if the collapsed spine survives.
    EPCAM/COADREAD measures 5 of 7 buckets; require the RNA cell-line backbone (which drives the
    verdict) to be measured, plus a conservative >=4 measured buckets (headroom for a data refresh
    nudging one bucket without masking a wholesale rule-firing collapse)."""
    pm = (epcam_decision.get("headline") or {}).get("presence_verdict_by_modality") or {}
    backbone = pm.get("bulk_rna/cell_line") or {}
    assert backbone.get("evidence_state") == "measured", (
        f"bulk_rna/cell_line bucket is {backbone.get('evidence_state')!r}, not 'measured' — the RNA "
        f"backbone that drives EPCAM's presence verdict stopped firing (reader/rule drift).")
    measured = [k for k, b in pm.items() if isinstance(b, dict) and b.get("evidence_state") == "measured"]
    assert len(measured) >= 4, (
        f"only {len(measured)} measured buckets ({sorted(measured)}) for EPCAM/COADREAD (expected 5) "
        f"— a block of rules stopped firing over the real summaries.")


def test_replay_sc_heterogeneity_fields_wired(epcam_decision):
    """The two-axis TCE antigen-escape readout must be surfaced into
    the presence headline. Wiring guard: the keys must exist (value may be None on a fixture frozen
    before the fields existed — the nightly live re-freeze populates real values). When the fixture DOES
    carry a value, the escape class must be a member of the declared vocabulary."""
    h = epcam_decision.get("headline") or {}
    for k in ("sc_within_tumor_coverage_class", "sc_inter_donor_consistency_class",
              "sc_tce_antigen_escape_class", "sc_malignant_detection_donor_iqr",
              "sc_fraction_donors_broadly_detecting"):
        assert k in h, f"{k} not surfaced into the presence headline (sc-heterogeneity wiring drift)"
    esc = h.get("sc_tce_antigen_escape_class")
    if esc is not None:
        assert esc in {"escape_risk_low", "escape_risk_moderate", "escape_risk_patient_variable",
                       "escape_risk_high", "coverage_high_donor_underpowered", "data_unavailable"}


def test_replay_cptac_standardized_effect_wired(epcam_decision):
    """The variance-standardized CPTAC effect must reach the
    headline. EPCAM/COADREAD CPTAC is `ns` with a tiny raw effect (0.065) — the standardized class is
    `negligible` (Cohen's d ~0.16), recovered via the p-value approximation on the current product."""
    h = epcam_decision.get("headline") or {}
    for k in ("protein_effect_standardized_class", "protein_effect_cohens_d",
              "protein_effect_standardized_t", "protein_effect_standardized_method"):
        assert k in h, f"{k} not surfaced into the presence headline (cptac-standardized wiring drift)"
    assert h.get("protein_effect_standardized_class") == "negligible"
    assert h.get("protein_effect_standardized_method") == "pvalue_zscore_approx"


def test_replay_robustness_guards_wired(epcam_decision):
    """End-to-end wiring of the verdict-inert robustness guards over the REAL EPCAM/COADREAD summaries
    (the helpers are unit-tested; this proves _headline emits them from a real run):
      * abundance_floor_flag = adequate_abundance — EPCAM cell-line Gygi PROTEIN is bottom-decile (allgene
        pct 8.6), but EPCAM is a curated SURFACE/SECRETED antigen (#980) and the Gygi TMT panel
        systematically under-reads that class; ProCan (`mid`) recovers it. So the surface-class anchor
        RE-ANCHORS to ProCan → adequate_abundance (no floor flag at all), superseding the general SOFT
        single-lens flag. (For a NON-surface target the same shape stays the SOFT flag — unit-tested in
        test_presence_robustness_guards.py.) The re-anchor is threaded via the dispatcher passing
        target='EPCAM' into _headline (signature-introspected).
      * presence_headline_conflict = False — CPTAC is `ns` (present-not-elevated), a measured NEUTRAL,
        not a killer, so the conflict flag must stay silent (no false alarm).
      * presence_abundance_is_relative = True — the standing capability-ceiling flag."""
    h = epcam_decision.get("headline") or {}
    assert h.get("abundance_floor_flag") == "adequate_abundance", (
        f"expected adequate_abundance (#980 surface-class re-anchor: lone Gygi bottom-decile recovered by "
        f"ProCan for the EPCAM surface antigen); got {h.get('abundance_floor_flag')!r}")
    assert not (h.get("abundance_floor_low_lenses") or []), (
        "a surface-class re-anchor to adequate leaves NO low lenses (Gygi-low is a class under-read, "
        "not a floor)")
    assert h.get("presence_headline_conflict") is False
    assert h.get("presence_headline_conflict_note") is None
    assert h.get("presence_abundance_is_relative") is True


def test_replay_headline_resolves_broadly(epcam_decision):
    """Headline drift floor: a reader field-name drift that silently nulled a block of `get_card_field`
    reads would collapse many headline values to None. EPCAM/COADREAD resolves ~42 non-null headline
    fields; a conservative floor of >=30 fails hard on a block-nulling drift while leaving refresh
    headroom."""
    headline = epcam_decision.get("headline") or {}
    non_null = [k for k, v in headline.items() if v not in (None, "", [], "data_unavailable")]
    assert len(non_null) >= 30, (
        f"only {len(non_null)}/{len(headline)} headline fields resolved for the frozen EPCAM replay — "
        f"suspect a reader field-name drift (get_card_field -> None). Non-null keys: {sorted(non_null)}")


def test_replay_headline_block_populated_and_verdict_inert(epcam_decision):
    """The canonical HEADLINE block must BUILD (not silently degrade) on the real EPCAM/COADREAD run,
    and stay verdict-inert. EPCAM is broadly present with the fullest bucket coverage, so:
      * no _enrichment_errors['headline_block'] (a build fault degrades, never crashes — but must NOT
        happen on the canonical fixture);
      * verdict.call == the collapsed presence_verdict, verdict.driving_rule_id == the spine's (inert);
      * confidence is a real level, not 'insufficient' (full coverage);
      * the hero carries all four claim axes;
      * the sharpest tension is the HONEST one — after the quorum guard demotes EPCAM's lone Gygi
        bottom-decile (an MS artifact, orthogonally contradicted by ProCan/IHC), the top tension is no
        longer a spurious abundance floor but the tumor-vs-normal-elevation caveat (present, not selective;
        the window verdict is owned by tumor-selectivity)."""
    h = epcam_decision.get("headline") or {}
    assert "headline_block" not in (h.get("_enrichment_errors") or {}), (
        f"headline_block degraded on the canonical EPCAM replay: "
        f"{(h.get('_enrichment_errors') or {}).get('headline_block')}")
    blk = h.get("headline_block")
    assert isinstance(blk, dict), "no headline_block on the EPCAM replay"
    assert blk["verdict"]["call"] == h.get("presence_verdict")
    assert blk["verdict"]["gate"] == "presence" and blk["verdict"]["phrase"]
    assert blk["verdict"]["driving_rule_id"] == h.get("driving_rule_id")  # verdict-inert echo, not override
    assert blk["confidence"]["level"] in ("strong", "moderate", "weak")   # measured — never insufficient here
    assert [a["key"] for a in blk["hero"]["axes"]] == ["A", "B", "C", "D"]
    assert blk["headline_text"].endswith(".")
    # the demoted single-lens floor must NOT be the headline tension; the honest tension is the
    # tumor-vs-normal-elevation caveat (or another real axis conflict), never the spurious abundance floor.
    _tt = (blk.get("top_tension") or {}).get("text", "").lower()
    assert blk["top_tension"], "a top tension should still surface"
    assert "bottom-decile" not in _tt, f"the demoted single-lens abundance floor must not lead the headline; got {_tt!r}"
