"""Pins the subclonal-recurrence guard (distillation change-3, contracts genomic_alteration 1.7.0):
a MEASURED predominantly-subclonal top-1% recurrent SNV with NO other corroboration demotes to
recurrent_snv_subclonal_uncertain, while clonal / clonality-unavailable / role-corroborated recurrent
SNVs keep recurrent_snv_driver. Deterministic resolver test (no data / no Bedrock)."""
from __future__ import annotations
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.resolver import resolve_or_raise  # noqa: E402


def _v(*rule_ids):
    return resolve_or_raise([{"rule_id": r} for r in rule_ids], "genomic_alteration")[0]


def test_subclonal_recurrence_demotes():
    # the target scenario: recurrence-only + measured subclonal → uncertain (not a confident driver)
    assert _v("snv-recurrence-top-driver-supportive", "snv-clonality-subclonal-opposing") == "recurrent_snv_subclonal_uncertain"


def test_clonal_or_unavailable_keeps_driver():
    # clonal / clonality-unavailable (guard rule absent) → recurrent_snv_driver unchanged (no coverage regression)
    assert _v("snv-recurrence-top-driver-supportive") == "recurrent_snv_driver"


def test_driver_role_preempts_the_subclonal_demotion():
    # OncoKB/intOGen driver ROLE corroborates a real driver regardless of clonality → keep the driver call
    assert _v("snv-recurrence-top-driver-supportive", "alteration-role-gof-driver-supportive",
              "snv-clonality-subclonal-opposing") == "recurrent_snv_driver"
    assert _v("snv-recurrence-top-driver-supportive", "alteration-role-lof-driver-neutral",
              "snv-clonality-subclonal-opposing") == "recurrent_snv_driver"


def test_guard_rule_never_fires_alone():
    # subclonal signal WITHOUT recurrence must not itself produce the uncertain verdict (it has no bare rung)
    assert _v("snv-clonality-subclonal-opposing") != "recurrent_snv_subclonal_uncertain"
