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

import pytest
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


def test_snv_recurrence_outranks_variant_class_shape():
    """FLIPPED in resolver 1.9.0 (was test_variant_class_pattern_outranks_snv_recurrence, which
    asserted the opposite). Variant-class SHAPE is not driver evidence: `mut-missense-dominant`
    fires for 62% of the 26-target genomic review panel INCLUDING both negative controls (GAPDH,
    ACTB), because most genes' somatic spectra are missense-dominant by base-substitution
    statistics alone. Pooled patient RECURRENCE in the top 1% is a far more specific statement, so
    the shape rungs moved below it (p38/39 → p50/51). Falsifier: ROS1/LUAD, where the shape rung was
    outranking real landscape recurrence."""
    assert resolve("mut-lof-dominant-supportive", "snv-recurrence-top-driver-supportive")[0] == "recurrent_snv_driver"
    assert (
        resolve("mut-missense-dominant-supportive", "snv-recurrence-top-driver-supportive")[0] == "recurrent_snv_driver"
    )
    # shape alone is still a real characterization — it was demoted, not removed
    assert resolve("mut-lof-dominant-supportive") == ("lof_dominant_pattern", "mut-lof-dominant-supportive")


def test_cn_amplification_still_outranks_snv_recurrence():
    # UNCHANGED by 1.9.0. The amplification arm has no measured specificity defect
    # (cn_recurrent_amplification_score clears its cut for 2.9% of genes genome-wide), so its rungs
    # were deliberately left alone — only the DELETION arm (60.1% null rate) was re-keyed.
    assert resolve("cn-recurrently-amplified-supportive", "snv-recurrence-top-driver-supportive")[0] == (
        "recurrent_amplification_driver"
    )


def test_bare_fusion_recurrence_no_longer_outranks_snv_recurrence():
    """FLIPPED in 1.9.0. `fusion-landscape-recurrent-driver-supportive` alone fires on promiscuous,
    low-prevalence rearrangement — STK11/LUAD is 3/632 tumours (0.47%) with ZERO recurrent partners,
    yet it was outranking stronger SNV evidence. The top fusion rung now requires the new
    fusion-recurrence-high-partner-context conjunct; bare fusion recurrence is demoted to p49."""
    assert resolve("fusion-landscape-recurrent-driver-supportive", "snv-recurrence-top-driver-supportive")[0] == (
        "recurrent_snv_driver"
    )
    # WITH partner corroboration the fusion call is restored — the gate discriminates, it does not veto
    assert resolve(
        "fusion-landscape-recurrent-driver-supportive",
        "fusion-recurrence-high-partner-context",
        "snv-recurrence-top-driver-supportive",
    )[0] == ("recurrent_fusion_driver")


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


# --- #8 hybrid-scope fail-open demotion (resolver v1.11.0, backtest-gated) -------------------------
# The *-indication-scoped-context gates admit BOTH within_indication and the hybrid
# within_indication_mut_vs_pan_wt scope, so a STRONG dependency at the hybrid scope earned the FULL
# biomarker_stratified_dependency band off a pooled-pan-lineage WT comparator. The four demotion rungs
# (priority 0-3, ABOVE the strong biomarker rung @4-7) require BOTH the within gate AND the new
# *-indication-scoped-fallback-context gate (hybrid only), so at hybrid scope both fire and the demotion
# rung wins (min priority) → moderate_biomarker_dependency — while a fully within_indication dependency
# (no fallback gate) keeps the dominant band @4-7. These pins are the teeth: the golden snapshot is BLIND
# to these debt rule_ids, so absent these cases the flip is untested here.

# The four classes: (strong rule, within gate, fallback gate, realistic in-indication driver co-signals).
_HYBRID_FAMILIES = [
    (
        "mutation",
        "mutant-strongly-dependent-supportive",
        "mutant-indication-scoped-context",
        "mutant-indication-scoped-fallback-context",
        ["mut-missense-dominant-supportive", "alteration-role-gof-driver-supportive"],
    ),
    (
        "copy_number",
        "cn-amplified-strongly-dependent-supportive",
        "cn-amplified-indication-scoped-context",
        "cn-amplified-indication-scoped-fallback-context",
        ["cn-recurrently-amplified-supportive", "alteration-role-gof-driver-supportive"],
    ),
    (
        "fusion",
        "fusion-positive-strongly-dependent-supportive",
        "fusion-positive-indication-scoped-context",
        "fusion-positive-indication-scoped-fallback-context",
        ["fusion-landscape-recurrent-driver-supportive"],
    ),
    (
        "amp_expr",
        "amp-expr-strongly-dependent-supportive",
        "amp-expr-indication-scoped-context",
        "amp-expr-indication-scoped-fallback-context",
        [],
    ),
]


@pytest.mark.parametrize("cls,strong,within,fallback,cosignals", _HYBRID_FAMILIES, ids=[f[0] for f in _HYBRID_FAMILIES])
def test_hybrid_scope_strong_dependency_demotes_to_moderate(cls, strong, within, fallback, cosignals):
    """A STRONG dependency at the hybrid within_indication_mut_vs_pan_wt scope (both scope gates fire)
    reads moderate_biomarker_dependency, NOT the full biomarker_stratified_dependency band."""
    verdict, drv = resolve(strong, within, fallback, *cosignals)
    assert verdict == "moderate_biomarker_dependency", (
        f"{cls} hybrid-scope strong dependency must demote to moderate_biomarker_dependency, got {verdict!r}"
    )
    assert drv == strong, f"{cls} demotion rung must anchor provenance to the dependency rule, not a scope gate"


@pytest.mark.parametrize("cls,strong,within,fallback,cosignals", _HYBRID_FAMILIES, ids=[f[0] for f in _HYBRID_FAMILIES])
def test_full_within_indication_strong_retains_dominant_band(cls, strong, within, fallback, cosignals):
    """The demotion is scoped to the hybrid gate ONLY: a fully within_indication strong dependency (the
    fallback gate is ABSENT) keeps biomarker_stratified_dependency. This is the 'within stays dominant'
    half of the locked decision — a guard that the demotion did not widen to all within-indication."""
    verdict, drv = resolve(strong, within, *cosignals)
    assert verdict == "biomarker_stratified_dependency", (
        f"{cls} fully within_indication strong dependency must retain the dominant band, got {verdict!r}"
    )
    assert drv == strong


def test_hybrid_demotion_outranks_driver_rungs_no_failopen():
    """THE fail-open guard: the resolver has NO clamp layer, so a demoted hybrid target must not slip
    UP to confirmed_driver via its driver co-signals. The demotion rung (priority 0-3) must win over
    the driver rungs (@12+), i.e. moderate_biomarker_dependency, never confirmed_driver."""
    # mutation hybrid strong WITH a full driver signature (shape + GoF role) that alone → confirmed_driver.
    assert resolve("mut-missense-dominant-supportive", "alteration-role-gof-driver-supportive") == (
        "confirmed_driver",
        "mut-missense-dominant-supportive",
    ), "precondition: these co-signals alone are a driver"
    verdict, drv = resolve(
        "mutant-strongly-dependent-supportive",
        "mutant-indication-scoped-context",
        "mutant-indication-scoped-fallback-context",
        "mut-missense-dominant-supportive",
        "alteration-role-gof-driver-supportive",
    )
    assert verdict == "moderate_biomarker_dependency", (
        f"hybrid demotion must outrank the driver rungs (no fail-open promotion), got {verdict!r}"
    )
    assert drv == "mutant-strongly-dependent-supportive"


def test_moderate_hybrid_dependency_unchanged():
    """The demotion rungs key on the STRONG dependency rule only. A MODERATE dependency at hybrid scope
    still resolves via the untouched moderate band (the within gate fires on the hybrid scope), so it is
    byte-stable at moderate_biomarker_dependency — the change touches ONLY the strong→moderate flip."""
    assert resolve("mutant-moderately-dependent-supportive", "mutant-indication-scoped-context") == (
        "moderate_biomarker_dependency",
        "mutant-moderately-dependent-supportive",
    )
    # and the same at hybrid scope (fallback gate present but unused by the moderate band)
    assert resolve(
        "mutant-moderately-dependent-supportive",
        "mutant-indication-scoped-context",
        "mutant-indication-scoped-fallback-context",
    ) == ("moderate_biomarker_dependency", "mutant-moderately-dependent-supportive")


# --- #1763: `underpowered` VALUE→VERDICT teeth (emitters now live; no longer byte-inert) ----------
# The stale "no live target emits underpowered until PR-C3" premise is corrected in the resolver +
# genomic_claims.py comments. Because that premise was comment-only (no test asserted the token's
# ABSENCE), correcting it must not leave the routing claim vacuously green. These pins prove the FULL
# path an emitted `underpowered` value takes — value → rule matcher (intracellular-intrinsic.rules.yaml)
# → resolver guard rung → verdict — so removing `underpowered` from a matcher OR dropping a guard rung
# reds this test. Read-only over the rules file (not edited here — see #1763 scope / interpretation-rules
# freeze). Emitters: depmap_cn_distribution/cli.py + tcga_patient_cn/read.py (copy_number_class),
# tcga_fusion_consensus/read.py (fusion_class).

RULES = yaml.safe_load((REPO / "interpretation-rules" / "intracellular-intrinsic.rules.yaml").read_text())


def _rules_firing(card_id: str, field: str, value: str) -> list[str]:
    """rule_ids whose `when` matcher (card_id+field, equals|in) admits the given value — mirrors the
    engine's value→rule matching, so this test exercises the SAME predicate the live card output hits."""
    hits = []
    for r in RULES["rules"]:
        w = r.get("when") or {}
        if w.get("card_id") != card_id or w.get("field") != field:
            continue
        if "equals" in w and w["equals"] == value:
            hits.append(r["rule_id"])
        elif "in" in w and value in w["in"]:
            hits.append(r["rule_id"])
    return hits


def test_underpowered_cn_value_fires_only_the_coverage_gap_rule():
    """copy_number_class == 'underpowered' must fire cn-data-unavailable-insufficient and NOTHING that
    reads as a driver or a measured passenger — the matcher was widened to in:[data_unavailable,
    underpowered] for PR-C2, and the emitters now produce the value."""
    fired = _rules_firing("copy-number-distribution", "copy_number_class", "underpowered")
    assert fired == ["cn-data-unavailable-insufficient"], fired


def test_underpowered_fusion_value_fires_only_the_coverage_gap_rule():
    """fusion_class == 'underpowered' must fire fusion-underpowered-insufficient only."""
    fired = _rules_firing("fusion-rearrangement-landscape", "fusion_class", "underpowered")
    assert fired == ["fusion-underpowered-insufficient"], fired


def test_underpowered_cn_routes_to_insufficient_never_passenger_or_driver():
    """The emitted underpowered CN value, with a no-mutations gene, resolves to `insufficient` via the
    double-data-gap guard — NEVER passenger_pattern and never any driver verdict."""
    (rid,) = _rules_firing("copy-number-distribution", "copy_number_class", "underpowered")
    verdict, drv = resolve("mut-no-mutations-neutral", rid)
    assert verdict == "insufficient", verdict
    assert verdict != "passenger_pattern"
    assert drv == "cn-data-unavailable-insufficient"


def test_underpowered_fusion_routes_to_insufficient_never_passenger_or_driver():
    """The emitted underpowered fusion value, with a no-mutations gene, resolves to `insufficient` via the
    fusion double-data-gap guard — NEVER passenger_pattern and never a driver rung."""
    (rid,) = _rules_firing("fusion-rearrangement-landscape", "fusion_class", "underpowered")
    verdict, drv = resolve("mut-no-mutations-neutral", rid)
    assert verdict == "insufficient", verdict
    assert verdict != "passenger_pattern"
    assert drv == "fusion-underpowered-insufficient"


def test_underpowered_never_reads_as_a_driver_when_alone():
    """An underpowered axis ALONE (no other signal) is a coverage gap → the resolver default insufficient,
    not a driver. Guards against a future rung ever promoting the gap token to a positive call."""
    (cn_rid,) = _rules_firing("copy-number-distribution", "copy_number_class", "underpowered")
    (fus_rid,) = _rules_firing("fusion-rearrangement-landscape", "fusion_class", "underpowered")
    assert resolve(cn_rid)[0] == "insufficient"
    assert resolve(fus_rid)[0] == "insufficient"
