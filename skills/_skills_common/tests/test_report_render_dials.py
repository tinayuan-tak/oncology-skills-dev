"""report_render — determinism (byte-stable) + the three dials behaving as declared."""
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render._fixtures import make_nomination
from _skills_common.report_render import (build_ir, render_all, render_report, resolve_spec,
                                           string_backend_names, vocab)


def test_render_is_byte_stable():
    # pptx (a pandoc .pptx zip) embeds nondeterministic ids/timestamps → byte-stability is asserted only
    # on the text-form backends; the deterministic snapshot surface is the json view.
    nom = make_nomination()
    for name in string_backend_names():
        assert render_report(nom, preset="full", backend=name) == \
               render_report(nom, preset="full", backend=name), f"non-deterministic: {name!r}"


def test_level_is_progressive_disclosure():
    nom = make_nomination()
    k = {lvl: build_ir(nom, resolve_spec(level=lvl, scope="all")).present_kinds()
         for lvl in ("L0", "L1", "L2", "L3")}
    assert k["L0"] <= k["L1"] <= k["L2"] <= k["L3"]
    assert vocab.CLAIM_CHIPS not in k["L0"]
    assert vocab.PROVENANCE not in k["L2"]
    assert vocab.PROVENANCE in k["L3"]


def test_scope_gating_excludes_descriptive():
    ir = build_ir(make_nomination(), resolve_spec(scope="gating", level="L1"))
    shorts = {s.short for s in ir.sections}
    assert "target_intrinsic" not in shorts
    assert {"safety", "dependency"} <= shorts


def test_scope_explicit_list():
    ir = build_ir(make_nomination(), resolve_spec(scope=("safety",), level="L1"))
    assert [s.short for s in ir.sections] == ["safety"]


def test_killers_lead_within_gating():
    ir = build_ir(make_nomination(), resolve_spec(scope="gating", level="L0"))
    order = [s.short for s in ir.sections]
    assert order.index("safety") < order.index("dependency")


def test_bump_deciding_deepens_only_the_deciding_axis():
    ir = build_ir(make_nomination(), resolve_spec("reviewer-dossier"))
    assert ir.deciding_short == "safety"

    def has_prov(short):
        sec = next(s for s in ir.sections if s.short == short)
        return any(b.kind == vocab.PROVENANCE for b in sec.blocks)

    assert has_prov("safety") and not has_prov("dependency")


def test_lead_deciding_axis_hoists_deciding_skill_first():
    ir = build_ir(make_nomination(), resolve_spec(scope="all", level="L0", lead="deciding_axis"))
    assert ir.sections[0].short == "safety"


def test_render_all_single_ir_multiple_backends():
    names = string_backend_names()
    out = render_all(make_nomination(), preset="exec-brief", backends=names)
    assert set(out) == set(names)
    assert all(isinstance(v, str) and v for v in out.values())
