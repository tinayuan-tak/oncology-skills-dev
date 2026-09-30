"""report_render — backend-coverage + parity: every backend handles every block kind, every block the
IR produces has a handler, and no payload shadows the reserved 'kind' field."""

from _skills_common.report_render import backends as be
from _skills_common.report_render import build_ir, resolve_spec, vocab
from _skills_common.report_render._fixtures import make_nomination, make_null_heavy_nomination


def test_every_backend_handles_every_block_kind():
    cov = be.coverage()
    assert set(cov) == set(be.BACKENDS)
    for name, kinds in cov.items():
        missing = vocab.BLOCK_KINDS - kinds
        assert not missing, f"backend {name!r} is missing handlers for {sorted(missing)}"


def test_no_payload_shadows_kind():
    # a payload field named 'kind' would shadow the block kind under {kind, **payload} serialization.
    for nom in (make_nomination(), make_null_heavy_nomination()):
        ir = build_ir(nom, resolve_spec("full"))
        blocks = [ir.header] + ([ir.about] if ir.about else [])
        blocks += [b for s in ir.sections for b in s.blocks]
        for b in blocks:
            assert "kind" not in b.payload, f"{b.kind} payload has a reserved 'kind' key"


def test_every_tier_kind_is_a_known_block_kind():
    assert set(vocab.TIER) == set(vocab.BLOCK_KINDS)
    assert set(vocab.CHIP_LIMIT_BY_LEVEL) == {0, 1, 2, 3}


def test_present_kinds_are_all_renderable_at_L3():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    present = ir.present_kinds()
    # NB: CLAIM_CHIPS is intentionally suppressed at L2+ when a question_table is present (dedupe), so
    # it is NOT guaranteed at L3; QUESTION_TABLE stands in for it. (Handler coverage for CLAIM_CHIPS is
    # guaranteed separately by test_every_backend_handles_every_block_kind.)
    for k in (
        vocab.REPORT_HEADER,
        vocab.SKILL_HEADER,
        vocab.CONFIDENCE,
        vocab.QUESTION_TABLE,
        vocab.PHASE_METRICS,
        vocab.FIGURE,
        vocab.PROVENANCE,
        vocab.ABOUT,
    ):
        assert k in present, f"expected {k} present at L3"
    for name, kinds in be.coverage().items():
        assert present <= kinds, f"backend {name!r} cannot render {sorted(present - kinds)}"
