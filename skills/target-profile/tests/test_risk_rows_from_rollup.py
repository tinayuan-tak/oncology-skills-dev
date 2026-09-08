"""md risk table renders the CANONICAL risk_rollup (target_report Wave 2, risk-collapse) — the md was
the outlier (its own _risk_by_category mapping); HTML + risk_rollup.json already use the rollup. The
adapter converts rollup dims → md (category, level, driver) rows; None/absent → renderer falls back to
the local mapping (e.g. --no-substrate). Pure over synthetic inputs.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SKILLS = SCRIPTS.parent.parent
for _p in (str(SKILLS), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _skills_common.risk_projection import _risk_rows_from_rollup  # noqa: E402


def _dims():
    return {
        "biological": {"pillar": "Right Target", "bin": "MED", "chain": [("dependency", "discordant", "MED")]},
        "druggability": {
            "pillar": "Right Molecule",
            "bin": "LOW",
            "chain": [("tractability-SM", "measured_potent_ligand", "LOW")],
        },
        "safety": {
            "pillar": "Right Safety",
            "bin": "HIGH",
            "chain": [("on-target-safety", "highly_constrained", "HIGH")],
        },
        "clinical": {"pillar": "Right Patient", "bin": "ENGINE-BLIND", "chain": []},
        "commercial": {
            "pillar": "Right Commercial",
            "bin": "LOW",
            "chain": [("competitor-landscape", "no_known_competitor", "LOW")],
        },
        "translational": {"pillar": "Right Patient", "bin": "ENGINE-BLIND", "chain": []},
    }


def test_adapter_maps_bins_and_order():
    rows = _risk_rows_from_rollup(_dims())
    assert [r[0] for r in rows] == ["biological", "druggability", "translational", "clinical", "safety", "commercial"]
    lvl = dict((c, l) for c, l, _ in rows)
    assert lvl["druggability"] == "LOW"  # strong tractability → LOW (not the old MED default)
    assert lvl["safety"] == "HIGH"
    assert lvl["biological"] == "MEDIUM"  # MED → MEDIUM
    assert lvl["clinical"] == "insufficient_evidence"  # ENGINE-BLIND → insufficient_evidence
    # driver comes from the top chain entry
    drv = dict((c, d) for c, _, d in rows)
    assert "tractability-SM" in drv["druggability"]


def test_adapter_accepts_wrapped_dims_and_rejects_junk():
    assert _risk_rows_from_rollup({"dims": _dims()})[0][0] == "biological"
    assert _risk_rows_from_rollup(None) is None
    assert _risk_rows_from_rollup({"not": "dims"}) is None
    assert _risk_rows_from_rollup("nope") is None
