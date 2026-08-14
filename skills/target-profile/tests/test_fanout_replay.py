"""OFFLINE FAN-OUT replay of frozen target-profile dossiers — the engine-level drift guard this composed
engine lacked.

target-profile fans out to 10 sub-skills in-process (_run_sub_skills → _one_sub_skill). For EACH sub-skill
the fan-out (a) resolves that sub-skill's SUB_SKILL_CARDS entry, (b) applies the gate's card preprocessor
(preprocess_cards_for_gate — the genomic family-wise FDR, G1), (c) fires rules on both axes scoped by
card_id_filter, and (d) calls the sub-skill's OWN _verdict (which carries any post-resolver clamp — e.g.
tumor-selectivity's normal-breadth veto, F1). This is the exact path where the F1 (selectivity veto),
G1 (genomic FDR), and safety (alteration-role mutant-selective downgrade) seam bugs manifested.

Unlike compose-dashboard (which has an offline byte-golden), target-profile has NO full-run offline
golden — its resolve_cards needs live S3 — so the fan-out MACHINERY was never exercised offline over REAL
card summaries with REAL verdict logic. test_subskill_composition.py monkeypatches away BOTH the data
boundary AND the verdict functions, so it tests composition plumbing only. THIS test closes that gap: it
monkeypatches only the live dispatcher (like the per-skill replays), serving frozen REAL summaries, and
runs the REAL _run_sub_skills — so preprocess + card_id_filter + each sub-skill's real _verdict all
execute exactly as in a live fan-out.

The fixtures are scoped (via freeze_fixture.py --sub-skills) to the SEAM-CRITICAL sub-skills; the fan-out
reads any un-frozen card as _missing, so the other sub-skills resolve `insufficient` (asserted, to prove
graceful degradation + that no stray rule fires). Two fixtures pin all three seam paths END-TO-END through
the fan-out:
  - TACSTD2 / COADREAD (tumor-selectivity frozen) — selectivity resolves selective_but_broadly_normal:
    the F1 normal-breadth VETO fires INSIDE THE FAN-OUT (via the sub-skill's own _verdict clamp). If a
    veto-card reader drifts, TACSTD2 reads tumor_selective in the composed profile → this test goes red.
  - KRAS / COADREAD (genomic + safety frozen) — genomic resolves biomarker_stratified_dependency (the G1
    FDR-preprocessed path) AND safety resolves wt_constraint_mechanism_mismatch (the mutant-selective
    downgrade — guards that alteration-role feeds the safety gate in the fan-out, the 2026-07-24 bugfix).

Mirror of the per-skill replays (SK#411), lifted to the composed fan-out engine.
"""
from __future__ import annotations

import copy
import importlib.util
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
if str(SKILLS_ROOT / "compose-dashboard" / "scripts") not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT / "compose-dashboard" / "scripts"))


def _load_tp():
    """Import target-profile run.py once (top-level only; no __main__ side effects)."""
    spec = importlib.util.spec_from_file_location("_tp_run_fanout", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_tp_run_fanout"] = mod
    spec.loader.exec_module(mod)
    return mod


_TP = _load_tp()


def _real_summary(s) -> bool:
    return (isinstance(s, dict) and bool(s)
            and not s.get("_freeze_error") and not s.get("_dispatcher_returned_none"))


def _load_fixture(pair_id: str) -> dict:
    fx = FIXTURES / f"{pair_id}.yaml"
    if not fx.exists():
        pytest.skip(f"no frozen fixture at {fx} — run freeze_fixture.py against live S3")
    return yaml.safe_load(fx.read_text()) or {}


_RESULT_CACHE: dict = {}


def _fan_out(pair_id: str, target: str, indication: str) -> dict:
    """Run the REAL target-profile fan-out (_run_sub_skills) with the live dispatcher replaced by the
    frozen fixture; cache + return the {short: verdict_str_or_None} map."""
    if pair_id in _RESULT_CACHE:
        return _RESULT_CACHE[pair_id]
    frozen = _load_fixture(pair_id)

    import _skills_common as skc

    def _fake_dispatcher_factory():
        def _read_live(card_id, target_, indication_, *args, **kwargs):
            s = frozen.get(card_id)
            if not _real_summary(s):
                return None                       # un-frozen card → resolve_cards marks it _missing
            return copy.deepcopy(s)
        return _read_live

    mp = pytest.MonkeyPatch()
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    mp.setattr(skc, "_import_dispatcher", _fake_dispatcher_factory)
    try:
        sub_results = _TP._run_sub_skills(target, indication)
    finally:
        mp.undo()

    verdicts = {short: (r.get("verdict")[0] if r.get("verdict") else None)
                for short, r in sub_results.items()}
    _RESULT_CACHE[pair_id] = verdicts
    return verdicts


TACSTD2 = ("tacstd2_coadread", "TACSTD2", "COADREAD")
KRAS = ("kras_coadread", "KRAS", "COADREAD")


def test_fanout_covers_all_sub_skills():
    """Sanity: the fan-out drives every SUB_SKILLS axis (a regression that dropped one would shrink
    this). 2026-08-14: 10 -> 11 with combinatorial_dependency (measured dual-KO SL complement, added
    to SUB_SKILLS as an ADDITIVE non-gate axis). Pinned to len(SUB_SKILLS) so it tracks future adds."""
    v = _fan_out(*TACSTD2)
    assert len(v) == len(_TP.SUB_SKILLS), (
        f"fan-out produced {len(v)} sub-results, expected {len(_TP.SUB_SKILLS)}: {sorted(v)}")
    for short in ("expression", "selectivity", "dependency", "genomic_alteration", "safety",
                  "surface_modality", "tractability_sm", "mechanism", "differentiation",
                  "synthetic_lethal_partners", "combinatorial_dependency"):
        assert short in v, f"sub-skill {short!r} missing from the fan-out results"


def test_selectivity_veto_fires_in_the_fanout():
    """CROWN-JEWEL (F1 in the composed path): TACSTD2 is broadly-normal epithelial — its tumor-selectivity
    sub-verdict must resolve to selective_but_broadly_normal, i.e. the normal-breadth VETO fires INSIDE the
    fan-out (via the sub-skill's own _verdict clamp). If a veto-card reader drifts so the veto stops firing,
    TACSTD2 would read tumor_selective in the composed profile — this test goes red. This is the fan-out
    analog of the tumor-selectivity standalone replay (F1 was DEAD in compose-dashboard; here we prove it is
    LIVE in target-profile's fan-out)."""
    v = _fan_out(*TACSTD2)
    assert v["selectivity"] == "selective_but_broadly_normal", (
        f"fan-out selectivity={v['selectivity']!r} for TACSTD2, expected selective_but_broadly_normal — "
        f"the normal-breadth veto stopped firing in the fan-out (silent F1-in-fan-out regression).")


def test_genomic_fdr_path_and_safety_downgrade_fire_in_the_fanout():
    """CROWN-JEWEL (G1 + safety in the composed path): for KRAS the fan-out must
      - resolve genomic_alteration to biomarker_stratified_dependency (the G1 family-wise-FDR
        preprocess path — preprocess_cards_for_gate runs in _one_sub_skill before firing), and
      - resolve safety to wt_constraint_mechanism_mismatch (the mutant-selective downgrade — proving
        alteration-role reaches the safety gate in the fan-out; the 2026-07-24 SUB_SKILL_CARDS bugfix).
    A reader/scoping drift on either path changes these in the composed profile with no other offline guard."""
    v = _fan_out(*KRAS)
    assert v["genomic_alteration"] == "biomarker_stratified_dependency", (
        f"fan-out genomic_alteration={v['genomic_alteration']!r} for KRAS, expected "
        f"biomarker_stratified_dependency (the G1 FDR-preprocessed fan-out path).")
    assert v["safety"] == "wt_constraint_mechanism_mismatch", (
        f"fan-out safety={v['safety']!r} for KRAS, expected wt_constraint_mechanism_mismatch — the "
        f"mutant-selective downgrade stopped firing in the fan-out (alteration-role not reaching the "
        f"safety gate — the 2026-07-24 fan-out bugfix regressed).")


def test_unfrozen_sub_skills_degrade_to_insufficient():
    """The fixtures are scoped to the seam-critical sub-skills; every OTHER sub-skill reads _missing cards
    and must degrade to insufficient (never spuriously resolve a verdict from a stray/misrouted card —
    which would signal a card_id_filter scoping bug in the fan-out)."""
    v = _fan_out(*TACSTD2)
    for short in ("dependency", "genomic_alteration", "safety", "mechanism", "differentiation",
                  "tractability_sm", "synthetic_lethal_partners"):
        assert v[short] in (None, "insufficient", "combination_insufficient"), (
            f"un-frozen sub-skill {short!r} resolved {v[short]!r} (not insufficient) for the "
            f"selectivity-scoped TACSTD2 fixture — suspect a card_id_filter scoping leak in the fan-out.")
