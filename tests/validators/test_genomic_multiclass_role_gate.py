"""Regression guard: multi_class_driver rungs must be alteration-role-gated (genomic redesign Stage 1).

The framework-wide rule audit found the genomic verdict called a PASSENGER a multi_class_driver
(CEACAM5/COADREAD: missense-dominant SHAPE + a CN-shape signal, but alteration_role=data_unavailable).
Cause: the multi_class rungs fired on [mut-driver-shape AND cn-driver-shape] with NO role co-signal,
unlike the confirmed_driver rungs. Fix: every REACHABLE mut-class multi_class rung now also requires an
alteration-role DRIVER rule (gof-supportive or lof-neutral). This pins that gate so the passenger FP
can't return. (Recurrence is deliberately NOT gated — mutation-hotspot-frequency has a data_unavailable
bin that would demote genuine drivers, §2e.)
"""

from __future__ import annotations

from pathlib import Path

import yaml

RESOLVER = Path(__file__).resolve().parents[2] / "resolvers" / "genomic_alteration.resolver.yaml"
# variant-class SHAPE rules — reachable multi_class drivers key on these (the mutant-dependent
# multi_class rungs are shadowed-dead under the N1 precedence hoist, so they're exempt).
_SHAPE_DRIVER_RULES = {"mut-lof-dominant-supportive", "mut-missense-dominant-supportive"}
_ROLE_RULES = {"alteration-role-gof-driver-supportive", "alteration-role-lof-driver-neutral"}


def test_shape_driven_multiclass_rungs_require_alteration_role():
    resolver = yaml.safe_load(RESOLVER.read_text())
    mc = [r for r in resolver["resolve"] if r.get("verdict") == "multi_class_driver"]
    shape_rungs = [r for r in mc if _SHAPE_DRIVER_RULES & set(r.get("when_all_fired", []))]
    assert shape_rungs, "expected reachable shape-driven multi_class rungs"
    for r in shape_rungs:
        waf = set(r["when_all_fired"])
        assert waf & _ROLE_RULES, (
            f"multi_class rung {r.get('when_all_fired')} keys on a variant-SHAPE driver rule but has NO "
            f"alteration-role driver co-signal — a passenger (missense-dominant shape, no driver role) "
            f"could be called multi_class_driver. Add gof-driver-supportive / lof-driver-neutral."
        )


def test_multiclass_precedes_confirmed_driver():
    """Stage 2 precedence: in the first-match ladder, multi_class_driver must appear BEFORE
    confirmed_driver (so a dually-altered driver surfaces multi-class instead of collapsing to a
    single-class confirmed_driver), and both must sit BELOW the stratified biomarker verdict and
    ABOVE the drug_response pattern layer."""
    import yaml

    rungs = yaml.safe_load(RESOLVER.read_text())["resolve"]

    def first(v):
        return next((i for i, r in enumerate(rungs) if r.get("verdict") == v), None)

    bm, mc, cd, dr = (
        first("biomarker_stratified_dependency"),
        first("multi_class_driver"),
        first("confirmed_driver"),
        first("drug_response_biomarker"),
    )
    assert None not in (bm, mc, cd, dr), (bm, mc, cd, dr)
    assert bm < mc < cd < dr, (
        f"first-match order must be biomarker({bm}) < multi_class({mc}) < confirmed_driver({cd}) "
        f"< drug_response({dr}) — else EGFR-style dually-altered drivers collapse to confirmed_driver."
    )
