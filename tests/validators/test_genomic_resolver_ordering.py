"""Behavioral golden for genomic_alteration.resolver.yaml precedence (Sweep-2 item B, 2026-08-15).

Item B fix: the passenger fallback (`mut-no-mutations-neutral` → passenger_pattern) is a
SUBSTANTIVE "not a driver" statement. When the copy-number axis is ALSO not measured
(`cn-data-unavailable-insufficient` co-fires), collapsing to passenger_pattern asserts
"not a driver" from a DOUBLE data-gap — the mutation-only failure the 2026-07-14
amplification reframe was built to kill. The fix adds a measured-vs-null guard rung ABOVE
the passenger rung: no-mutations × CN-unavailable → `insufficient` (honest coverage gap),
NOT passenger_pattern.

These pins assert the fix AND that the narrow scope leaves every neighbouring behaviour
byte-stable (mut-no-mutations ALONE, measured-neutral CN, and CN-driver-wins-over-passenger
are all UNCHANGED). Evaluated with a self-contained first-match interpreter that mirrors
claude-oncology-skills/_skills_common/resolver.py::resolve_verdict — the ONE engine the
skills call — so this test is the target-contracts-side golden for the shipped spec.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((REPO / "resolvers" / "genomic_alteration.resolver.yaml").read_text())


def resolve(*fired_ids: str) -> tuple[str, str | None]:
    """First-match interpreter — byte-identical semantics to _skills_common/resolver.py."""
    fired = set(fired_ids)
    for rung in SPEC.get("resolve", []):
        verdict = rung["verdict"]
        if "when_fired" in rung:
            rid = rung["when_fired"]
            if rid in fired:
                return verdict, (rung.get("driving_rule") or rid)
        elif "when_any_fired" in rung:
            for rid in rung["when_any_fired"]:
                if rid in fired:
                    return verdict, (rung.get("driving_rule") or rid)
        elif "when_all_fired" in rung:
            rids = rung["when_all_fired"]
            if all(r in fired for r in rids):
                return verdict, (rung.get("driving_rule") or rids[-1])
    return SPEC["default"], None


# --- item B: the fix ------------------------------------------------------


def test_no_mutations_with_cn_unavailable_is_insufficient_not_passenger():
    # DOUBLE data-gap: mutation says "rarely mutated / no signal" AND CN is not measured.
    # Must be an HONEST coverage gap, not a substantive passenger call.
    verdict, drv = resolve("mut-no-mutations-neutral", "cn-data-unavailable-insufficient")
    assert verdict == "insufficient", (
        "no-mutations x CN-unavailable is a double data-gap → insufficient, NOT passenger_pattern"
    )
    assert drv == "cn-data-unavailable-insufficient", (
        "the CN coverage gap is the provenance anchor for the insufficient call"
    )


# --- narrow-scope guards: neighbouring behaviour is UNCHANGED -------------


def test_no_mutations_alone_still_passenger():
    # Mutation measured-neutral, CN NOT unavailable → passenger_pattern stands (existing pin).
    assert resolve("mut-no-mutations-neutral") == ("passenger_pattern", "mut-no-mutations-neutral")


def test_no_mutations_with_measured_neutral_cn_still_passenger():
    # A MEASURED-neutral CN (broadly_neutral fires cn-broadly-neutral-neutral, which the resolver
    # does not consume) is NOT a data gap → passenger_pattern stands. Only CN-*unavailable* is guarded.
    assert resolve("mut-no-mutations-neutral", "cn-broadly-neutral-neutral")[0] == "passenger_pattern"


def test_cn_driver_still_beats_passenger():
    # A real CN driver + no mutations still names the CN driver (no regression to the guard).
    assert resolve("cn-recurrently-amplified-supportive", "mut-no-mutations-neutral") == (
        "recurrent_amplification_driver",
        "cn-recurrently-amplified-supportive",
    )


def test_fusion_driver_still_beats_passenger_even_with_cn_unavailable():
    # A recurrently-rearranged oncogene with no mutations AND unmeasured CN is still a fusion driver,
    # not swallowed by the new guard (fusion rung precedes both the guard and passenger).
    assert resolve(
        "fusion-landscape-recurrent-driver-supportive", "mut-no-mutations-neutral", "cn-data-unavailable-insufficient"
    )[0] == ("recurrent_fusion_driver")


def test_mixed_pattern_unaffected_by_guard():
    # The guard is scoped to the no-mutations neutral; a mixed mutation profile with unmeasured CN
    # still reads mixed_pattern (a genuine mutation-axis characterization, not a "not a driver" claim).
    assert resolve("mut-mixed-neutral", "cn-data-unavailable-insufficient")[0] == "mixed_pattern"


def test_nothing_fired_is_default_insufficient():
    assert resolve() == ("insufficient", None)


# --- scope-coherence Phase 1: dependency-rung indication-scope gate (the old→new flip golden) ------
# All four stratified biomarker rungs now require their <class>-indication-scoped-context gate. These
# pins encode the reviewed flip list: within_indication drivers RETAIN biomarker_stratified_dependency;
# pan-lineage-only dependencies fall through to the next driver rung (confirmed_driver / recurrent_*),
# and an ISOLATED pan-lineage dependency (no recurrence/role/landscape support in-indication) drops to
# insufficient (honest — no indication-level evidence). Realistic co-signals accompany each class.


def test_within_indication_dependency_retains_biomarker_all_classes():
    """The gate FIRES (evidence_scope within_indication) → the biomarker rung stands. KRAS/BRAF COADREAD
    (both mutation-strong @ within_indication) live here — they retain their verdict under the gate."""
    assert resolve(
        "mutant-strongly-dependent-supportive",
        "mutant-indication-scoped-context",
        "mut-missense-dominant-supportive",
        "alteration-role-gof-driver-supportive",
    ) == ("biomarker_stratified_dependency", "mutant-strongly-dependent-supportive")
    assert (
        resolve(
            "cn-amplified-strongly-dependent-supportive",
            "cn-amplified-indication-scoped-context",
            "cn-recurrently-amplified-supportive",
        )[0]
        == "biomarker_stratified_dependency"
    )
    assert (
        resolve(
            "fusion-positive-strongly-dependent-supportive",
            "fusion-positive-indication-scoped-context",
            "fusion-landscape-recurrent-driver-supportive",
        )[0]
        == "biomarker_stratified_dependency"
    )


def test_pan_lineage_dependency_with_cosignals_downgrades_to_driver_not_biomarker():
    """The gate is ABSENT (pan_lineage_evidence_only) → the biomarker rung fails when_all_fired and the
    call falls to the next positive-driver rung. Still a driver, no longer an indication biomarker."""
    # mutation: → confirmed_driver (mut shape + role)
    assert resolve(
        "mutant-strongly-dependent-supportive",
        "mut-missense-dominant-supportive",
        "alteration-role-gof-driver-supportive",
    ) == ("confirmed_driver", "mut-missense-dominant-supportive")
    # copy-number: → confirmed_driver (CN recurrence + role)
    assert resolve(
        "cn-amplified-strongly-dependent-supportive",
        "cn-recurrently-amplified-supportive",
        "alteration-role-gof-driver-supportive",
    ) == ("confirmed_driver", "cn-recurrently-amplified-supportive")
    # fusion: → recurrent_fusion_driver (landscape recurrence)
    assert (
        resolve("fusion-positive-strongly-dependent-supportive", "fusion-landscape-recurrent-driver-supportive")[0]
        == "recurrent_fusion_driver"
    )


def test_isolated_pan_lineage_dependency_is_insufficient():
    """A pan-lineage dependency with NO indication-native corroboration (no recurrence/role/landscape)
    now honestly reads insufficient rather than an unearned indication biomarker."""
    assert resolve("mutant-strongly-dependent-supportive")[0] == "insufficient"
    assert resolve("cn-amplified-strongly-dependent-supportive")[0] == "insufficient"
    assert resolve("fusion-positive-strongly-dependent-supportive")[0] == "insufficient"


# --- scope-coherence Phase 2: recurrent_snv_driver (pooled patient recurrence → verdict) ----------


def test_snv_recurrence_alone_is_recurrent_snv_driver():
    # A top-1% pooled-recurrent SNV with no dependency / variant-class / CN / fusion signal → the SNV
    # landscape-recurrence driver (the honest floor for recurrence-only SNV drivers).
    assert resolve("snv-recurrence-top-driver-supportive") == (
        "recurrent_snv_driver",
        "snv-recurrence-top-driver-supportive",
    )


def test_variant_class_pattern_outranks_snv_recurrence():
    # A lof/missense-dominant spectrum (tier 5) is a stronger call than bare recurrence (tier 6).
    assert resolve("mut-lof-dominant-supportive", "snv-recurrence-top-driver-supportive")[0] == "lof_dominant_pattern"


def test_cn_and_fusion_landscape_outrank_snv_recurrence():
    # recurrent_snv_driver is LAST in tier 6 — a dually-altered gene keeps its CN/fusion verdict.
    assert resolve("cn-recurrently-amplified-supportive", "snv-recurrence-top-driver-supportive")[0] == (
        "recurrent_amplification_driver"
    )
    assert resolve("fusion-landscape-recurrent-driver-supportive", "snv-recurrence-top-driver-supportive")[0] == (
        "recurrent_fusion_driver"
    )


def test_dependency_outranks_snv_recurrence():
    # A within-indication KO-dependency (tier 1) wins over recurrence.
    assert (
        resolve(
            "mutant-strongly-dependent-supportive",
            "mutant-indication-scoped-context",
            "snv-recurrence-top-driver-supportive",
        )[0]
        == "biomarker_stratified_dependency"
    )
