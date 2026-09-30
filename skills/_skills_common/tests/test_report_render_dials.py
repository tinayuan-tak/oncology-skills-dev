"""report_render — determinism (byte-stable) + the three dials behaving as declared."""

from _skills_common.report_render import build_ir, render_all, render_report, resolve_spec, string_backend_names, vocab
from _skills_common.report_render._fixtures import make_nomination


def test_render_is_byte_stable():
    # pptx (a pandoc .pptx zip) embeds nondeterministic ids/timestamps → byte-stability is asserted only
    # on the text-form backends; the deterministic snapshot surface is the json view.
    nom = make_nomination()
    for name in string_backend_names():
        assert render_report(nom, preset="full", backend=name) == render_report(nom, preset="full", backend=name), (
            f"non-deterministic: {name!r}"
        )


def test_question_table_cells_render_label_not_dict_repr():
    # question_table_core puts DICTS in the signal/confidence cells ({tier,fill/dots,polarity,label}).
    # The HUMAN-READABLE backends must surface the `label`, never str(dict) — a real defect the earlier
    # string-cell fixture masked. json is EXCLUDED: it legitimately serializes the structured row dicts.
    nom = make_nomination()
    for name in [b for b in string_backend_names() if b != "json"]:
        if name == "html":
            # question tables live in the per-subskill sections, which the composed v6 HTML no longer
            # inlines — render the sections directly (the standalone subskill page's _emit_standalone_section
            # path) so the human-readable cell formatting is still exercised for HTML.
            from _skills_common.report_render.backends.html import HtmlBackend

            ir = build_ir(nom, resolve_spec("reviewer-dossier"))
            be = HtmlBackend()
            out = "".join(be._emit_standalone_section(s) for s in ir.sections)
        else:
            out = render_report(nom, preset="reviewer-dossier", backend=name)
        assert "Questions" in out or "question" in out.lower(), f"{name}: no question table rendered"
        assert "'tier'" not in out and '"tier":' not in out, f"{name}: raw dict repr leaked into cells"
        assert "'polarity'" not in out, f"{name}: raw dict repr leaked into cells"
        assert "constrained" in out, f"{name}: signal label not surfaced"
        assert "gnomAD v4: high" in out, f"{name}: confidence label not surfaced"


def test_level_is_progressive_disclosure():
    nom = make_nomination()
    k = {lvl: build_ir(nom, resolve_spec(level=lvl, scope="all")).present_kinds() for lvl in ("L0", "L1", "L2", "L3")}
    assert k["L0"] <= k["L1"]
    assert vocab.CLAIM_CHIPS not in k["L0"]
    # L1 shows claim_chips (no question_table yet); L2+ SWAPS to the question_table (dedupe suppresses
    # the redundant chips) — a deliberate swap, not strict cumulative.
    assert vocab.CLAIM_CHIPS in k["L1"] and vocab.QUESTION_TABLE not in k["L1"]
    assert vocab.QUESTION_TABLE in k["L2"] and vocab.CLAIM_CHIPS not in k["L2"]
    assert vocab.PROVENANCE not in k["L2"] and vocab.PROVENANCE in k["L3"]


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
