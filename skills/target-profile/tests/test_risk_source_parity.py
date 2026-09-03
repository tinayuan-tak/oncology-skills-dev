"""Anti-divergence guard (risk-6dim re-home 2026-09-03): the md risk table, the HTML risk chips, and
target_report.risk_6dim ALL render from ONE deterministic dims object. Before this migration the md
renderer computed its own parallel 6-category mapping (a fallback with md-only LOW-MEDIUM/MEDIUM-HIGH
labels) that could drift from the HTML + risk_rollup.json. Now build_risk_6dim computes the projection
once (offline-safe, from in-memory sub_results) and every surface consumes it. Pure/synthetic — no data.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SKILLS = SCRIPTS.parent.parent
for _p in (str(SKILLS), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _skills_common.risk_projection import deterministic_bins  # noqa: E402
from tp_render_md import _risk_rows_from_rollup  # noqa: E402
from tp_render_html import _render_risk_rollup_html  # noqa: E402
from tp_facets import build_target_report  # noqa: E402
import tp_grounding  # noqa: E402


def _sub_results():
    # A clear mix: safety HIGH (constrained), biological LOW (concordant dep + known mech), druggability
    # LOW (well_covered), clinical/commercial/translational engine-blind (no card).
    return {
        "safety": {"verdict": ("highly_constrained_safety_concern", "r"),
                   "cards": [{"card_id": "gnomad-lof-constraint", "summary": {"loeuf_score": 0.1},
                              "interpretation_call": "x"}]},
        "dependency": {"verdict": ("concordant_dependent", "r"), "cards": []},
        "mechanism": {"verdict": ("well_characterized", "r"), "cards": []},
        "tractability_sm": {"verdict": ("well_covered", "r"), "cards": []},
    }


def test_build_risk_6dim_offline_equals_pure_projection():
    """grounded_by_axis=None → build_risk_6dim is exactly the pure deterministic projection over the
    in-memory package (no sibling / no network). Proves the fallback is unnecessary."""
    sr = _sub_results()
    dims = tp_grounding.build_risk_6dim(sr, "small_molecule", None, None)
    assert isinstance(dims, dict)
    assert dims["safety"]["bin"] == "HIGH"
    assert dims["druggability"]["bin"] == "LOW"
    assert dims["biological"]["bin"] == "LOW"
    assert dims["clinical"]["bin"] == "ENGINE-BLIND"


def test_md_html_and_target_report_share_one_source():
    dims = tp_grounding.build_risk_6dim(_sub_results(), "small_molecule", None, None)

    # (1) target_report.risk_6dim is the SAME dims object (by reference — no recompute).
    tr = build_target_report(target_call={"schema": "target_call.v1", "recommendation": "hold"},
                             risk_rollup=dims)
    assert tr["risk_6dim"] is dims

    # (2) the md table renders from that same dims (LOW→LOW, HIGH→HIGH, ENGINE-BLIND→insufficient_evidence).
    rows = _risk_rows_from_rollup(dims)
    lvl = {c: l for c, l, _ in rows}
    assert lvl["safety"] == "HIGH"
    assert lvl["druggability"] == "LOW"
    assert lvl["clinical"] == "insufficient_evidence"
    assert {c for c, _, _ in rows} == {"biological", "druggability", "translational",
                                       "clinical", "safety", "commercial"}

    # (3) the HTML risk section renders from that same dims — the safety HIGH chip is present.
    html = "".join(_render_risk_rollup_html(dims))
    assert "HIGH" in html
    assert "not evidenced" in html  # ENGINE-BLIND chip wording (clinical/commercial/translational)
