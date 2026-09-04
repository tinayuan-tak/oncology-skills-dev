"""report_render — decision-critical detail blocks surfaced from buried spine content:
flip_conditions ("what would change the call"), subtype stratification (MSI/MSS…), and the
patient-selection biomarker facet. Fixture shapes mirror the real nomination."""
import sys
import json
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render._fixtures import make_nomination
from _skills_common.report_render import build_ir, render_report, resolve_spec, vocab


def _ov(ir, kind):
    return next((b for b in ir.overview if b.kind == kind), None)


# -- flip conditions ("what would change the call") --------------------------------------------
def test_flip_conditions_only_recommendation_flips_no_dev_notes():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    fc = _ov(ir, vocab.FLIP_CONDITIONS)
    assert fc is not None
    verdicts = {r["to_verdict"] for r in fc.payload["rows"]}
    assert "pan_essential_killer" in verdicts               # a counterfactual (present=False)
    assert "moderately_constrained_safety" in verdicts      # a load-bearing signal (present=True)
    assert "concordant_dependent" not in verdicts           # recommendation_flip=False → filtered out
    # the dev-note sentence must never reach the payload.
    assert all("sentence" not in r for r in fc.payload["rows"])


def test_flip_conditions_curated_not_exhaustive():
    # dependency emits 5 recommendation-flips (rests-on + kill + 2 strengthen + 1 dup neutralize) — the
    # block must CURATE, not dump: dedupe by direction, present-first, cap per axis + overall.
    from collections import Counter
    ir = build_ir(make_nomination(), resolve_spec("full"))
    fc = _ov(ir, vocab.FLIP_CONDITIONS)
    rows = fc.payload["rows"]
    dep = [r for r in rows if r["axis"] == vocab.skill_title("dependency")]
    assert len(dep) <= 2                                     # capped per axis
    assert any(r["present"] for r in dep)                    # the load-bearing rest-on survives
    dv = {r["to_verdict"] for r in dep}
    assert "pan_essential_killer" in dv                      # adverse kill kept
    assert "lineage_selective" not in dv and "selective_dependent" not in dv  # vacuous upside capped out
    assert "insufficient_underpowered" not in dv             # same-direction dup collapsed into the rest-on
    assert len(rows) <= 6                                    # global cap
    assert max(Counter(r["axis"] for r in rows).values()) <= 2


def test_flip_conditions_present_first_and_rendered_clean():
    t = render_report(make_nomination(), preset="full", backend="text")
    assert "What would change the call" in t
    assert "H fix" not in t and "DEV NOTE" not in t         # dev-note text never rendered
    # load-bearing (present) framing vs counterfactual framing.
    assert "rests on" in t
    h = render_report(make_nomination(), preset="full", backend="html")
    assert "What would change the call" in h and "DEV NOTE" not in h


def test_flip_conditions_tier_gated_at_L1():
    l0 = build_ir(make_nomination(), resolve_spec(level="L0"))
    l1 = build_ir(make_nomination(), resolve_spec(level="L1"))
    assert _ov(l0, vocab.FLIP_CONDITIONS) is None
    assert _ov(l1, vocab.FLIP_CONDITIONS) is not None


# -- subtype stratification ---------------------------------------------------------------------
def test_subtype_block_surfaces_convergent_subtype():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    sub = _ov(ir, vocab.SUBTYPE)
    assert sub is not None
    assert sub.payload["convergent_subtypes"] == ["MSI_H"]
    assert "MSI_H" in sub.payload["subtypes"]
    t = render_report(make_nomination(), preset="full", backend="text")
    assert "Subtype stratification" in t and "MSI_H" in t


def test_subtype_block_absent_when_axis_unavailable():
    nom = make_nomination()
    nom["target_report"]["subtype_convergence"] = {"verdict": "subtype_axis_unavailable",
                                                   "n_subtypes_evaluated": 0, "per_subtype": {}}
    assert _ov(build_ir(nom, resolve_spec("full")), vocab.SUBTYPE) is None


# -- biomarker facet ----------------------------------------------------------------------------
def test_biomarker_block_surfaces_stratification_not_dev_note():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    bm = _ov(ir, vocab.BIOMARKER)
    assert bm is not None
    assert bm.payload["preferred_assay"] == "genomic"
    assert bm.payload["mutation_stratification"] == "mutant_strongly_dependent"
    assert bm.payload["hypotheses"][0]["intended_use"] == "predictive"
    # the dev-note + deep dependency_performance must be dropped.
    assert all("_note" not in h and "dependency_performance" not in h
               for h in bm.payload["hypotheses"])
    t = render_report(make_nomination(), preset="full", backend="text")
    assert "Patient-selection biomarker" in t and "DEV NOTE" not in t
    assert "mutant strongly dependent" in t                 # humanized


# -- coverage / determinism ---------------------------------------------------------------------
def test_new_kinds_handled_by_every_backend_and_schema_valid():
    from _skills_common.report_render import coverage
    for name, kinds in coverage().items():
        for k in (vocab.FLIP_CONDITIONS, vocab.SUBTYPE, vocab.BIOMARKER):
            assert k in kinds, f"{name} cannot render {k}"
    obj = json.loads(render_report(make_nomination(), preset="full", backend="json"))
    ov_kinds = {b["kind"] for b in obj["overview"]}
    assert {vocab.FLIP_CONDITIONS, vocab.SUBTYPE, vocab.BIOMARKER} <= ov_kinds
