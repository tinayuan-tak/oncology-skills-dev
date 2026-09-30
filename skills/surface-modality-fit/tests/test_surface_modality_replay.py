"""OFFLINE verdict-replay of frozen surface-modality-fit dossiers — the drift guard this skill lacked.

surface-modality-fit's verdict is resolver-native but MULTI-CARD: the surface_modality resolver takes the
composed adc-tce-modality-fit `fit_class` as the base rung, then applies KILLER/downgrade combination
rungs (`when_all_fired: [<fit-supportive>, <killer-rule>]`) fed by the liability cards —
normal-tissue-liability + sc-normal-celltype-expression (bite_tce killers), surface-abundance-density
(TCE-floor downgrade), shed-ectodomain-liability (shed opposing), + the ihc-not-detected protein killer.
Its existing tests feed the resolver SYNTHETIC fired-sets, so a card method RENAMING a field a killer
rung keys on passes green while in production the killer silently stops firing → a TCE-UNSAFE antigen
reads as cleanly both_viable (a FALSE "TCE is safe" biologics-fit call). No existing test runs
`fired_rules` over a real summary for this skill.

This replays the REAL reader summaries frozen by freeze_fixture.py (run once against live S3) THROUGH THE
REAL run.py — only the live dispatcher is monkeypatched, so production CARDS + the surface_intrinsic
rule-firing + the shared surface_modality resolver (incl. all killer/downgrade combination rungs) execute
exactly as in a real run. It fails deterministically, credential-less, on the SAME reader drift a live run
would.

Three curated fixtures pin the base ladder AND both bite_tce KILLER rungs (via two distinct killer cards):
  - CEACAM5 / COADREAD — both_viable base, DOWNGRADED to adc_preferred_tce_unsafe by the SC-NORMAL bite
    killer (sc-normal-high-liability-bite-killer). Crown jewel: if the sc-normal reader drifts, CEACAM5
    flips back to both_viable (TCE falsely "safe") and this test goes red.
  - TACSTD2 / COADREAD — both_viable base, DOWNGRADED to adc_preferred_tce_unsafe by the HPA-IHC
    NORMAL-TISSUE-ESSENTIAL bite killer (a DIFFERENT killer card). Guards the second killer path.
  - ERBB2 / COADREAD — both_viable base (v1.3.0 dominance gate: p95HER2 is a MINORITY isoform so the
    gene-level HER2 fit is NO LONGER blanked to isoform_dependent_undefined — HER2 is the canonical ADC
    antigen, T-DXd approved), DOWNGRADED to adc_preferred_tce_unsafe by the normal-tissue bite killer.
    Guards the isoform dominance-gate fix AND the base→TCE-unsafe downgrade path.

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

# The bite_tce KILLER rules that DOWNGRADE a both_viable/tce_preferred base fit to a TCE-unsafe verdict.
_BITE_KILLER_RULES = {"sc-normal-high-liability-bite-killer", "normal-tissue-essential-bite-killer"}
# Legitimate TCE-unsafe safety-DOWNGRADE drivers (a `both_viable` base dropped to a TCE-unsafe verdict
# by an on-target-off-tumor normal liability). Superset of the bite killers: after the 2026-09-07
# sc-normal-killer repoint (blunt HIGH_LIABILITY → organ-aware critical_organ_liability), an ORIGIN-tissue
# antigen (CEACAM5: colonocyte = COADREAD origin) no longer fires the sc-normal bite killer — its TCE arm
# is instead correctly killed by the off-origin therapeutic-window liability (lung). Both are real
# safety-downgrade rules; the crown-jewel guard is that SOME such rule drove the downgrade (not a base call).
_TCE_UNSAFE_DOWNGRADE_RULES = _BITE_KILLER_RULES | {
    "modality-window-essential-liability-tce-opposing",
    "exon-window-essential-liability-tce-opposing",
}
# The TCE-unsafe downgrade verdicts those killers emit.
_TCE_UNSAFE = {"adc_preferred_tce_unsafe", "tce_unsafe_normal_liability"}
_COLLAPSED = {None, "", "insufficient", "modality_ambiguous"}


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

    out_dir = Path(tempfile.mkdtemp(prefix=f"smf-{pair_id}-"))
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
CEACAM5 = ("ceacam5_coadread", "CEACAM5", "COADREAD", "adc_preferred_tce_unsafe")
TACSTD2 = ("tacstd2_coadread", "TACSTD2", "COADREAD", "adc_preferred_tce_unsafe")
ERBB2 = ("erbb2_coadread", "ERBB2", "COADREAD", "adc_preferred_tce_unsafe")
# pMHC promotion (2026-08-25): WT1 is an INTRACELLULAR transcription factor — correctly surface-
# neither_viable — yet carries T-cell-validated IEDB epitopes, so it resolves to the pMHC-TCE route.
# #2113: WT1's frozen fixture has pmhc_presentation_class=intermediate_presentation (Q1–Q3, below the
# broad veto but NOT tumor-restricted Q1), so it fires NEITHER the restricted nor the broad presentation
# rule → the normal-presentation window is UNMEASURED-as-restricted, and the promotion correctly resolves
# to the NON-NOMINATING caveat pmhc_tce_supported_presentation_unconfirmed (not the clean positive). This
# now guards BOTH the pMHC verdict path AND the normal-presentation measuredness gate against reader drift.
WT1 = ("wt1_coadread", "WT1", "COADREAD", "pmhc_tce_supported_presentation_unconfirmed")
ALL = [CEACAM5, TACSTD2, ERBB2, WT1]


@pytest.mark.parametrize("pair_id,target,indication,_exp", ALL, ids=[p[1].lower() for p in ALL])
def test_replay_conforms_to_data_product_schema(pair_id, target, indication, _exp):
    """LOAD-BEARING output-drift guard: the FRESH run.py emit must validate against the finalized
    data-product schema. Confirms both fit_class (skill_report.call) and the resolved
    surface_modality_verdict conform (static golden trimmed → this is the conformance target). CI-fail-not-skip."""
    import os

    from _skills_common.data_product_contract import conformance_errors, load_schema, schema_path

    schema = load_schema("surface-modality-fit")
    if schema is None:
        reason = f"data-product schema not found at {schema_path('surface-modality-fit')}"
        pytest.fail(reason + " [CI]") if os.environ.get("CI") else pytest.skip(reason)
    errors = conformance_errors(schema, _decision(pair_id, target, indication))
    assert not errors, f"FRESH {pair_id} emit violates the data-product schema:\n  " + "\n  ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:15]
    )


KILLER = [CEACAM5, TACSTD2]


@pytest.mark.parametrize("pair_id,target,indication,_exp", ALL, ids=[p[1].lower() for p in ALL])
def test_fixture_is_nonvacuous(pair_id, target, indication, _exp):
    """Guard against a stale/broken freeze reading green: each curated target resolves a good fraction of
    the ~18-card roster (several biologics cards are legitimately data_unavailable per target). Require >=10."""
    frozen = _load_fixture(pair_id)
    real = [cid for cid, s in frozen.items() if _real_summary(s)]
    assert len(real) >= 10, (
        f"only {len(real)}/{len(frozen)} frozen cards carry a real summary for {pair_id} — refreeze "
        f"against live S3 (freeze_fixture.py). Real cards: {sorted(real)}"
    )


@pytest.mark.parametrize("pair_id,target,indication,expected", ALL, ids=[p[1].lower() for p in ALL])
def test_verdict_matches_expected(pair_id, target, indication, expected):
    """THE VERDICT-PATH DRIFT GUARD: rules fire over the REAL frozen summaries and the shared
    surface_modality resolver runs. Each curated target's resolved surface_modality_verdict must equal
    its pinned class — a reader field rename that stops a killer/fit rule firing changes it and fails here."""
    d = _decision(pair_id, target, indication)
    assert d["skill"] == "surface-modality-fit"
    h = d.get("headline") or {}
    v = h.get("surface_modality_verdict")
    assert v not in _COLLAPSED, (
        f"surface_modality_verdict={v!r} collapsed for {target}/{indication} — a rule stopped firing "
        f"(reader field rename?)."
    )
    assert v == expected, f"surface_modality_verdict={v!r} for {target}/{indication}, expected {expected!r}."
    assert h.get("driving_rule_id"), "resolved a verdict but driving_rule_id is empty — inconsistent spine."


@pytest.mark.parametrize("pair_id,target,indication,expected", KILLER, ids=[p[1].lower() for p in KILLER])
def test_bite_killer_downgrades_tce(pair_id, target, indication, expected):
    """CROWN-JEWEL GUARD (silent killer-death → false 'TCE safe'): a target whose base fit is both_viable
    but which carries a normal-tissue / sc-normal on-target-off-tumor liability must be DOWNGRADED to a
    TCE-unsafe verdict by a bite_tce killer rung. If the killer card's reader drifts, the killer stops
    firing and the target reads as both_viable (TCE falsely safe) — this test goes red."""
    d = _decision(pair_id, target, indication)
    h = d.get("headline") or {}
    v = h.get("surface_modality_verdict")
    assert v in _TCE_UNSAFE, (
        f"{target} resolved {v!r}, not a TCE-unsafe downgrade — a bite_tce killer stopped firing "
        f"(normal-tissue / sc-normal reader drift → a TCE-unsafe antigen would read as both_viable)."
    )
    assert v != "both_viable", f"{target} read both_viable — the bite killer is DEAD (false TCE-safe call)."
    assert h.get("driving_rule_id") in _TCE_UNSAFE_DOWNGRADE_RULES, (
        f"{target} driving_rule_id={h.get('driving_rule_id')!r} is not a TCE-unsafe safety-downgrade rule "
        f"(bite killer or essential-window opposing)."
    )
    # the killer only MOVES the verdict if the base fit was viable — confirms the downgrade, not a base call
    assert h.get("fit_class") == "both_viable", (
        f"{target} base fit_class={h.get('fit_class')!r}, expected both_viable — the fixture no longer "
        f"exercises the killer DOWNGRADE (base fit drifted); re-curate/refreeze."
    )


def test_replay_headline_block_populated_and_verdict_inert():
    """The canonical headline_block builds end-to-end over the REAL CEACAM5/COADREAD summaries and stays
    verdict-inert:
      * no _enrichment_errors['headline_block'] (a build fault degrades, never crashes — but must NOT
        degrade on this fully-populated crown-jewel fixture);
      * verdict.call == the composed fit_class (the canonical modality-substrate call), gate/phrase set;
      * verdict.driving_rule_id echoes the spine's driving_rule_id (an inert echo, not an override);
      * confidence is a real level, not None; the hero carries all FIVE surface claim axes;
      * the resolver's TCE-unsafe DOWNGRADE surfaces as the top tension (CEACAM5 = adc_preferred_tce_unsafe
        while base fit_class == both_viable — the killer must be legible in the headline)."""
    d = _decision(*CEACAM5[:3])
    h = d.get("headline") or {}
    assert "headline_block" not in (h.get("_enrichment_errors") or {}), (
        f"headline_block degraded on the CEACAM5 replay: {(h.get('_enrichment_errors') or {}).get('headline_block')}"
    )
    blk = h.get("headline_block")
    assert isinstance(blk, dict), "no headline_block on the CEACAM5 replay"
    assert blk["verdict"]["call"] == h.get("fit_class")
    assert blk["verdict"]["gate"] == "surface_modality" and blk["verdict"]["phrase"]
    assert blk["verdict"]["driving_rule_id"] == h.get("driving_rule_id")  # verdict-inert echo, not override
    assert blk["confidence"]["level"] in ("strong", "moderate", "weak", "insufficient")
    assert [a["key"] for a in blk["hero"]["axes"]] == ["FIT", "TOPOLOGY", "DENSITY", "SAFETY", "SHED"]
    # CEACAM5 base fit is both_viable but the resolved verdict is a TCE-unsafe downgrade — the killer must
    # be surfaced as the top tension so the fit_class call does not falsely read "TCE safe".
    assert h.get("fit_class") == "both_viable" and h.get("surface_modality_verdict") == "adc_preferred_tce_unsafe"
    tension = blk.get("top_tension")
    assert tension and tension.get("source") == "surface_modality_downgrade", (
        f"expected the TCE-unsafe downgrade as top tension, got {tension!r}"
    )


def test_pmhc_tce_route_surfaces_when_surface_is_neither_viable():
    """pMHC PROMOTION crown-jewel (2026-08-25): WT1 (intracellular oncoprotein) is correctly surface-
    neither_viable, but its T-cell-validated IEDB epitopes promote the verdict to the pMHC-TCE route —
    the peptide-MHC (TCR-mimetic TCE) route the folded-surface ladder cannot see. The fit_class stays
    neither_viable (read direct from the composed card) alongside the verdict, and the headline surfaces
    the pMHC route as the top note so the "neither viable" call is not read as "no biologics route".

    #2113 NORMAL-PRESENTATION MEASUREDNESS GATE: WT1's fixture has pmhc_presentation_class=
    intermediate_presentation (fires neither the restricted nor the broad rule), so the tumor-restricted
    normal-presentation window is UNMEASURED and the promotion resolves to the NON-NOMINATING caveat
    pmhc_tce_supported_presentation_unconfirmed (not the clean positive). The top note surfaces the caveat.
    If the IEDB reader's epitope_evidence_class drifts, the promotion stops and this goes red."""
    d = _decision(*WT1[:3])
    h = d.get("headline") or {}
    assert h.get("fit_class") == "neither_viable", (
        f"WT1 fit_class={h.get('fit_class')!r}, expected neither_viable (intracellular — no cell-surface antigen)."
    )
    assert h.get("surface_modality_verdict") == "pmhc_tce_supported_presentation_unconfirmed", (
        f"WT1 verdict={h.get('surface_modality_verdict')!r}, expected the #2113 caveat "
        f"pmhc_tce_supported_presentation_unconfirmed (IEDB pMHC route, normal-presentation UNMEASURED)."
    )
    assert h.get("driving_rule_id") == "pmhc-iedb-tcell-validated-tce-supportive"
    assert h.get("pmhc_epitope_evidence_class") == "tcell_validated"
    blk = h.get("headline_block") or {}
    # the fit_class call is the negative neither_viable; the pMHC route rides as the top note.
    assert blk.get("verdict", {}).get("call") == "neither_viable"
    tension = blk.get("top_tension") or {}
    assert tension.get("source") == "pmhc_tce_route_presentation_unconfirmed", (
        f"expected the caveated pMHC-TCE route as top note, got {tension!r}"
    )


def test_isoform_dominance_gate_keeps_base_fit():
    """ERBB2 v1.3.0 dominance-gate guard: p95HER2 is a MINORITY epitope-ablating isoform, so the gene-level
    HER2 base fit_class must STAY favorable (both_viable) — NOT blanked to isoform_dependent_undefined.
    HER2 is the canonical internalizing ADC antigen (T-DXd approved in HER2+ gastric); blanking it was the
    round-1 capture defect. The subsequent normal-tissue bite-killer downgrade (→ adc_preferred_tce_unsafe)
    is legitimate and guarded by test_bite_killer_downgrades_tce; here we pin only that the BASE rung is
    favorable and the isoform suppression no longer hijacks it."""
    d = _decision(*ERBB2[:3])
    h = d.get("headline") or {}
    assert h.get("fit_class") == "both_viable", (
        f"ERBB2 base fit_class={h.get('fit_class')!r}, expected both_viable (isoform dominance gate must "
        f"NOT blank a minority-isoform target to isoform_dependent_undefined)."
    )
    assert h.get("surface_modality_verdict") != "isoform_dependent_undefined", (
        "ERBB2 verdict is still isoform_dependent_undefined — the dominance gate did not take effect."
    )
