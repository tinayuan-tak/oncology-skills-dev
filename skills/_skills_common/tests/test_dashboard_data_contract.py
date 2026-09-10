"""Guards for the Dashboard Rendering Contract (report_render/DATA_CONTRACT.md).

report_render is the SOLE dashboard renderer and reads the backend output structures directly, so a
parallel dashboard arc lands PRs off them. DATA_CONTRACT.md documents that field interface, derived
from the ir.py reader builders. These tests keep the contract HONEST + keep the renderer green:

  1. the contract file exists and is versioned;
  2. every reader builder the contract names still exists in ir.py (catches a rename that would
     silently break the reader mapping the contract promises);
  3. the load-bearing section classes named in the contract's renderer-green gate actually emit
     (composed + standalone-subskill), hermetically, from the shared fixtures.

Verdict-inert: renders only; touches no resolver/gate.
"""

import re
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render import (  # noqa: E402
    ir as _ir,
)
from _skills_common.report_render import (
    render_report,
    render_skill_report,
)
from _skills_common.report_render._fixtures import make_decision_json, make_nomination  # noqa: E402

CONTRACT = Path(_ir.__file__).resolve().parent / "DATA_CONTRACT.md"

# The reader builders DATA_CONTRACT.md maps fields to. If one is renamed/removed, the contract's
# field→reader mapping is stale — update BOTH the builder and the contract in the same change.
_DOCUMENTED_READER_BUILDERS = (
    "build_ir",
    "build_ir_for_skill",
    "_risk_6dim_block",
    "_synthesis_block",
    "_synthesis_banner_block",
    "_composed_fingerprint_block",
    "_modality_matrix_block",
    "_literature_risk_block",
    "_card_scope",
    "_subtype_block",
    "_subtype_rollup",
    "_deciding_axis_block",
    "_cross_evidence_summary",
    "_skill_graph_header",
    "_evidence_fingerprint_block",
    "_card_chain_block",
    "_literature_axes_block",
    "_skill_synthesis_block",
    "_format_key_evidence",
)


def test_data_contract_exists_and_is_versioned():
    assert CONTRACT.is_file(), f"missing {CONTRACT}"
    text = CONTRACT.read_text()
    assert re.search(r"schema_version:\s*\d+\.\d+\.\d+", text), "DATA_CONTRACT.md must declare a schema_version"


def test_documented_reader_builders_still_exist():
    missing = [fn for fn in _DOCUMENTED_READER_BUILDERS if not hasattr(_ir, fn)]
    assert not missing, (
        f"reader builders named in DATA_CONTRACT.md no longer exist in ir.py: {missing} — "
        "a rename here silently breaks the documented field→reader mapping; update both together."
    )


def test_composed_render_emits_load_bearing_sections():
    # the DATA_CONTRACT renderer-green gate signature (composed full HTML).
    h = render_report(make_nomination(), preset="full", backend="html")
    for cls in ('class="dim ', "hgrid", "qtab"):
        assert cls in h, f"load-bearing composed section missing from HTML: {cls!r}"


def test_standalone_subskill_render_does_not_raise_and_is_nonempty():
    # report_render is also the sole renderer for the standalone per-subskill dashboard.
    h = render_skill_report(make_decision_json(), backend="html")
    assert isinstance(h, str) and len(h) > 200, "standalone subskill render should produce real HTML"
