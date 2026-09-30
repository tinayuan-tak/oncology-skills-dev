"""immune_context.read — indication→TCGA-study coverage map (no S3).

Pins that first-class TCGA studies the immune-context card advertises resolve to study code(s)
rather than silently returning data_unavailable. The CIBERSORT product covers all 33 TCGA studies,
so UCEC + SARC (absent from the dge_deseq2 map) are supplemented in the reader. (IM-1 fix)

Also pins the LYMPHOID keys (2026-09-12): they exist so the fail-closed denominator guard is
REACHABLE from a real query — the map and the guard are two halves of one behaviour and must be
tested as a round trip, not separately.
"""

from __future__ import annotations

from onc_methods.immune_context.classify import (
    LYMPHOID_DENOMINATOR_STUDIES,
    has_lymphoid_denominator,
    summarize_immune_context,
)
from onc_methods.immune_context.read import INDICATION_TO_TCGA_STUDIES


def test_ucec_sarc_resolve_to_studies():
    assert INDICATION_TO_TCGA_STUDIES.get("UCEC") == ["UCEC"]
    assert INDICATION_TO_TCGA_STUDIES.get("SARC") == ["SARC"]


def test_nsclc_umbrella_still_resolves():
    # regression guard: the pre-existing umbrella supplement is preserved.
    assert INDICATION_TO_TCGA_STUDIES.get("NSCLC") == ["LUAD", "LUSC"]


# ── the lymphoid keys exist so the FAIL-CLOSED GUARD IS REACHABLE ─────────────────────────────────
# The guard (classify.has_lymphoid_denominator) shipped before this map had any lymphoid key, so no
# real query could reach it: DLBCL resolved to nothing and the reader answered `data_unavailable`
# ("no cohort") for a TCE-VALIDATED indication whose cohort exists. These tests pin the ROUND TRIP
# — indication resolves → guard fires → the honest token — because either half alone is useless.
def test_every_guarded_study_is_reachable_from_the_indication_map():
    """The two halves must agree: every study the guard names must be resolvable from SOME indication
    key, or the guard is unreachable dead code."""
    reachable = {s for studies in INDICATION_TO_TCGA_STUDIES.values() for s in studies}
    assert LYMPHOID_DENOMINATOR_STUDIES <= reachable, (
        f"guarded studies unreachable from any indication: {sorted(LYMPHOID_DENOMINATOR_STUDIES - reachable)} "
        f"— the fail-closed guard cannot fire on a real query"
    )


def test_lymphoid_indications_and_their_aliases_resolve_to_the_guarded_study():
    assert INDICATION_TO_TCGA_STUDIES.get("DLBC") == ["DLBC"]
    assert INDICATION_TO_TCGA_STUDIES.get("DLBCL") == ["DLBC"]  # alias — guard is keyed on the STUDY
    assert INDICATION_TO_TCGA_STUDIES.get("LAML") == ["LAML"]
    assert INDICATION_TO_TCGA_STUDIES.get("AML") == ["LAML"]
    assert INDICATION_TO_TCGA_STUDIES.get("THYM") == ["THYM"]


def test_the_resolved_lymphoid_indication_fails_closed_rather_than_publishing_a_class():
    """End to end on the shape that matters: DLBCL's REAL median CD8 share (0.1142) is above the hot
    cut, so an unguarded read would publish `immune_hot` for a lymphoma. It must publish the reason."""
    studies = INDICATION_TO_TCGA_STUDIES["DLBCL"]
    assert has_lymphoid_denominator(studies) is True
    s = summarize_immune_context(
        [{"T.cells.CD8": 0.1142} for _ in range(48)],
        studies=studies,
    )
    assert s["immune_context_class"] == "lymphoid_denominator_unreliable"
    assert s.get("median_cd8_fraction") is None  # withheld, not published-with-a-caveat


def test_the_supplement_did_not_make_a_solid_indication_lymphoid():
    """Non-vacuity partner: the new keys must not widen the guard onto solid tumours."""
    for ind in ("COADREAD", "SKCM", "PAAD", "PDAC", "NSCLC", "UCEC", "SARC", "GBM"):
        assert has_lymphoid_denominator(INDICATION_TO_TCGA_STUDIES[ind]) is False, ind
