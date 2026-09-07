"""CASE-009 — verdict-INERT pharmacovigilance_scope_caveat.

The full-sweep discordance loop flagged BCL2/PSMB5/XPO1/PARP1 (approved-drug targets) whose
PHARMACOVIGILANCE axis reads drug_warning_class='no_warning' while the literature documents real
on-target dose-limiting toxicity (TLS, cytopenias, neuropathy). Triage: the axis is a coarse OT
drug-warning + OnSIDES-BOXED detector, and the overall safety verdict is already conservative
(highly_constrained via gnomAD) — so this is a SCOPE clarifier, not a verdict change. The caveat
fires ONLY on the measured-negative 'no_warning' state and never enters the resolver.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

sf = load_run_py(Path(__file__).resolve().parent.parent, "sf_pv_caveat")


def test_fires_on_no_warning():
    c = sf._pharmacovigilance_scope_caveat({"drug_warning_class": "no_warning"})
    assert c is not None
    assert "OT-registered FDA warning" in c
    assert "NOT establish absence of on-target toxicity" in c
    assert "ORIENTS, never HOLDs" in c


def test_none_on_coverage_gap_and_warned_and_absent():
    # no_targeted_drug is a COVERAGE gap, not a measured-negative → no scope caveat
    assert sf._pharmacovigilance_scope_caveat({"drug_warning_class": "no_targeted_drug"}) is None
    # any warned class already surfaces the warning → no scope caveat needed
    for cls in ("black_box_warned", "withdrawn_drug", "other_warning", "insufficient"):
        assert sf._pharmacovigilance_scope_caveat({"drug_warning_class": cls}) is None
    # field absent → byte-stable None
    assert sf._pharmacovigilance_scope_caveat({}) is None


def test_registered_as_verdict_inert_facet_key():
    assert "pharmacovigilance_scope_caveat" in sf._SYNTHESIS_FACET_KEYS
