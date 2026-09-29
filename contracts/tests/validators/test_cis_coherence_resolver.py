"""Behavioral golden for cis_coherence.resolver.yaml (cis-feature-coherence Stage 0, 2026-08-20).

cis_coherence is a deterministic cross-tab of two coherence legs:
  leg-1  feature -> own-expression   (cis_dosage_class + cis_dosage_direction; the cis-feature-
         expression-coherence card. DIRECTIONAL since resolver v1.3.0 / card v1.1.0: "coupled" splits
         into an AMPLIFICATION arm and a DELETION arm, so it is a 3x2 cross-tab, not 2x2)
  leg-2  expression/feature -> own-dependency  (correlation_class OR amp_expr_stratification_class)

These pins encode the full cross-tab + the OR-on-leg-2 + the honest-abstention default. Evaluated with
a self-contained match-all-then-reduce interpreter that mirrors claude-oncology-skills/_skills_common/
resolver.py::resolve_verdict — the ONE engine the skills call — so this is the target-contracts-side
golden.

VERDICT-INERT: cis_coherence is a dedicated self-contained axis (like combination_opportunity), NOT in
the skills gating axes. This golden pins the classification only; no nomination gate depends on it.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((REPO / "resolvers" / "cis_coherence.resolver.yaml").read_text())

# leg tokens (fired by interpretation-rules/cis-coherence.rules.yaml)
DOSAGE_COUPLED = "cis-dosage-coupled-supportive"  # leg-1 + (coupled; direction-agnostic)
AMP = "cis-dosage-amplification-coupled-supportive"  # leg-1 direction: gain drives expression UP
DEL = "cis-dosage-deletion-coupled-neutral"  # leg-1 direction: loss drives expression DOWN
DOSAGE_UNCOUPLED = "cis-dosage-uncoupled-neutral"  # leg-1 - (measured, CN-independent)
DEP_CORR = "cis-expr-dependency-coupled-supportive"  # leg-2 + (correlation leg)
DEP_ABSENT = "cis-expr-dependency-absent-neutral"  # leg-2 - (no expr->dep)
DEP_CONJOINT = "cis-conjoint-dependent-supportive"  # leg-2 + (amp-expr conjoint leg)
SILENCING = "cis-silencing-coupled-supportive"  # LoF arm: methylation → low expression
SILENCING_CONFOUNDED = "cis-silencing-lineage-confounded-neutral"  # collapses within lineage → no rung


def resolve(*fired_ids: str) -> tuple[str, str | None]:
    """match_all_reduce interpreter — same semantics as _skills_common/resolver.py.

    Evaluates EVERY rung and reduces to the match of MINIMUM `priority` (rung order is irrelevant, per
    the VERDICT_REPRESENTATION_FOLD R6 order-independence property). Reading `priority` rather than file
    order is what makes this a real golden for the folded spec: a rung reordered in the file without a
    priority change must NOT move a verdict, and a priority edit must.
    """
    fired = set(fired_ids)
    best: tuple[int, str, str | None] | None = None
    for i, rung in enumerate(SPEC.get("resolve", [])):
        verdict = rung["verdict"]
        prio = rung.get("priority", i)
        hit: str | None = None
        if "when_fired" in rung:
            rid = rung["when_fired"]
            if rid in fired:
                hit = rung.get("driving_rule") or rid
        elif "when_any_fired" in rung:
            for rid in rung["when_any_fired"]:
                if rid in fired:
                    hit = rung.get("driving_rule") or rid
                    break
        elif "when_all_fired" in rung:
            rids = rung["when_all_fired"]
            if all(r in fired for r in rids):
                hit = rung.get("driving_rule") or rids[-1]
        if hit is not None and (best is None or prio < best[0]):
            best = (prio, verdict, hit)
    if best is None:
        return SPEC["default"], None
    return best[1], best[2]


def test_rung_file_order_matches_priority_order():
    """The two interpreters (file-order first-match vs priority reduce) must agree, so a reader of the
    ladder top-to-bottom reads the real precedence. Priorities are also unique (validate_fold_migration
    enforces that repo-wide); this pins the ORDER agreement for this resolver specifically."""
    prios = [r.get("priority") for r in SPEC["resolve"]]
    assert all(p is not None for p in prios), "every rung carries an explicit priority"
    assert prios == sorted(prios), f"file order diverges from priority order: {prios}"


# --- the four cross-tab cells -------------------------------------------------


def test_coupled_and_dependent_is_coherent_cis_driver():
    """leg-1 AMPLIFICATION-coupled + leg-2 dependent (either leg) → coherent_cis_driver, cis-dosage as
    driver. The oncogene-addiction chain (ERBB2/MYC/KRAS-amp): gain drives expression drives dependency."""
    assert resolve(DOSAGE_COUPLED, AMP, DEP_CONJOINT) == ("coherent_cis_driver", DOSAGE_COUPLED)
    assert resolve(DOSAGE_COUPLED, AMP, DEP_CORR) == ("coherent_cis_driver", DOSAGE_COUPLED)


def test_coupled_but_dependency_absent_is_expressed_cis_coupled_inert():
    """leg-1 AMPLIFICATION-coupled + leg-2 absent → expressed_cis_coupled_inert (the abundance-laundering
    guard): gain drives expression, but more abundance does not mean more required."""
    assert resolve(DOSAGE_COUPLED, AMP, DEP_ABSENT) == ("expressed_cis_coupled_inert", DEP_ABSENT)


def test_uncoupled_but_dependent_is_dependency_without_cis_dosage():
    """leg-1 uncoupled + leg-2 dependent → dependency_without_cis_dosage: a real dependency, but the
    expression is copy-number-INDEPENDENT (trans/lineage-regulated), not amplification-driven."""
    assert resolve(DOSAGE_UNCOUPLED, DEP_CONJOINT) == ("dependency_without_cis_dosage", DOSAGE_UNCOUPLED)
    assert resolve(DOSAGE_UNCOUPLED, DEP_CORR) == ("dependency_without_cis_dosage", DOSAGE_UNCOUPLED)


def test_uncoupled_and_absent_is_cis_uncoupled_no_dependency():
    """leg-1 uncoupled + leg-2 absent → cis_uncoupled_no_dependency (no coherent cis chain)."""
    assert resolve(DOSAGE_UNCOUPLED, DEP_ABSENT) == ("cis_uncoupled_no_dependency", DOSAGE_UNCOUPLED)


# --- coherent wins first-match when BOTH leg-2 signals fire (no double-count) --


def test_coherent_wins_when_both_leg2_signals_fire():
    # Conjoint + correlation both present with a coupled leg-1 → still one coherent_cis_driver.
    assert resolve(DOSAGE_COUPLED, AMP, DEP_CONJOINT, DEP_CORR) == ("coherent_cis_driver", DOSAGE_COUPLED)


def test_coherent_wins_over_inert_when_dep_present_and_absent_both_fire():
    # Defensive: if a card mis-emits both a dep-coupled AND dep-absent token, the coherent rung
    # outranks the inert rung → coherent wins (present beats absent).
    assert resolve(DOSAGE_COUPLED, AMP, DEP_CORR, DEP_ABSENT)[0] == "coherent_cis_driver"


# --- leg-1 DIRECTION (resolver v1.3.0): amplification vs deletion coupling ----


def test_deletion_coupled_with_a_dependency_leg_is_not_a_cis_driver():
    """A deletion-coupled gene that carries a dependency leg is NOT amplification-driven, so it must not
    read coherent_cis_driver — that verdict is the amplification-addiction chain. It lands on
    dependency_without_cis_dosage (the dependency exists; a dosage-addiction chain does not), and the
    DIRECTION token is the driving_rule so the memo says which arm was measured."""
    assert resolve(DOSAGE_COUPLED, DEL, DEP_CONJOINT) == ("dependency_without_cis_dosage", DEL)
    assert resolve(DOSAGE_COUPLED, DEL, DEP_CORR) == ("dependency_without_cis_dosage", DEL)


def test_deletion_coupled_without_a_dependency_leg_is_coherent_cis_loss_of_function():
    """The NEW v1.3.0 cell: loss lowers the target's expression and it is not a self-dependency — a
    synthetic-lethal / re-expression hypothesis. APC / STK11 / NF1 live here. Before v1.3.0 this fired the
    expressed_cis_coupled_inert rung, which was the wrong story (the gene is DOWN, not abundant-but-inert)."""
    assert resolve(DOSAGE_COUPLED, DEL, DEP_ABSENT) == ("coherent_cis_loss_of_function", DEL)


def test_direction_alone_cannot_reach_a_verdict():
    """Direction SHARPENS leg-1, it does not establish it: without the class token (and without a leg-2
    token) no rung can match, so the honest abstention stands. This is what keeps the direction pair from
    becoming a second, independent claim about the same measurement."""
    assert resolve(AMP) == ("insufficient_cis_coherence", None)
    assert resolve(DEL) == ("insufficient_cis_coherence", None)
    assert resolve(AMP, DEP_CORR) == ("insufficient_cis_coherence", None)


def test_amplification_and_deletion_directions_are_mutually_exclusive_in_practice():
    """cis_dosage_direction is ONE card field, so the two direction tokens can never co-fire from a real
    read. Pinned defensively: if a future emitter ever fired both, the amplification reading (lower
    priority number) wins rather than the resolver silently picking by file order."""
    assert resolve(DOSAGE_COUPLED, AMP, DEL, DEP_ABSENT)[0] == "expressed_cis_coupled_inert"


# --- honest abstention: any leg untestable/unmeasured -> default --------------


def test_epigenetic_silencing_is_standalone_lof_arm():
    """The silencing leg fires coherent_epigenetic_silencing on its own (no dependency leg): a silenced
    gene is turned off, not a self-dependency. MLH1/MGMT/CDKN2A archetype."""
    assert resolve(SILENCING) == ("coherent_epigenetic_silencing", SILENCING)


def test_genuine_amplification_addiction_wins_over_silencing():
    """A gene that is BOTH cis-dosage-coupled+dependent AND (oddly) silencing-coupled names the GoF
    amplification-addiction first (coherent_cis_driver outranks the silencing rung)."""
    assert resolve(DOSAGE_COUPLED, AMP, DEP_CONJOINT, SILENCING)[0] == "coherent_cis_driver"


def test_trans_driven_dependency_wins_over_silencing():
    """PANEL CALIBRATION (2026-09-12, v1.2.0): a gene that is cis-dosage-UNCOUPLED but has a real
    dependency leg AND (via a minority-subset, lineage-confounded methylation signal) fires the silencing
    rung must name dependency_without_cis_dosage, NOT coherent_epigenetic_silencing — a self-dependency is
    by definition not a silenced-off gene. This is the FGFR1/LUSC + NKX2-1/LUAD discordance the 20-target
    panel surfaced (dosage-uncoupled + expr-dep-coupled + silencing was wrongly resolving to silencing)."""
    assert resolve(DOSAGE_UNCOUPLED, DEP_CORR, SILENCING) == ("dependency_without_cis_dosage", DOSAGE_UNCOUPLED)
    assert resolve(DOSAGE_UNCOUPLED, DEP_CONJOINT, SILENCING) == ("dependency_without_cis_dosage", DOSAGE_UNCOUPLED)


def test_silenced_tsg_without_dependency_leg_still_names_silencing():
    """Guard against over-correction: a validated silenced TSG (MLH1/MGMT/CDKN2A) carries NO coupled
    dependency leg, so with only the silencing leg it still names coherent_epigenetic_silencing. CDKN2A is
    the full live fired-set — DELETION-coupled, dependency-absent, silenced — and the silencing rung
    outranks the coherent_cis_loss_of_function rung, so a MEASURED epigenetic mechanism is named in
    preference to the bare "the deleted arm carries the expression" statement."""
    assert resolve(SILENCING) == ("coherent_epigenetic_silencing", SILENCING)
    assert resolve(DOSAGE_COUPLED, DEL, DEP_ABSENT, SILENCING) == ("coherent_epigenetic_silencing", SILENCING)


def test_amplification_coupled_inert_gene_is_not_labeled_silenced():
    """THE MET-CLASS RESIDUAL, CLOSED (v1.3.0). Under v1.2.0 a gene whose GAIN arm drives its expression
    but which has no dependency leg lost to the silencing rung as soon as a (typically minority, lineage-
    confounded) methylation subset fired — MET/LUAD read coherent_epigenetic_silencing. The
    expressed_cis_coupled_inert rung now outranks the silencing rung for the AMPLIFICATION direction only,
    so the amplicon reading wins here while CDKN2A (deletion-coupled, previous test) keeps silencing.
    Note the discrimination is DIRECTIONAL, not a blanket demotion of the silencing rung."""
    assert resolve(DOSAGE_COUPLED, AMP, DEP_ABSENT, SILENCING) == ("expressed_cis_coupled_inert", DEP_ABSENT)


def test_lineage_confounded_silencing_token_reaches_no_rung():
    """silencing_lineage_confounded is recorded, not interpreted: the contrast collapsed within lineage, so
    it is neither a silencing claim nor a refutation. The token must therefore leave the verdict exactly
    where the other legs put it — CDH1 (dosage-uncoupled after the lineage control, dependency-absent,
    methylation confounded) is cis_uncoupled_no_dependency, and on its own the token abstains."""
    assert resolve(SILENCING_CONFOUNDED) == ("insufficient_cis_coherence", None)
    assert resolve(DOSAGE_UNCOUPLED, DEP_ABSENT, SILENCING_CONFOUNDED) == (
        "cis_uncoupled_no_dependency",
        DOSAGE_UNCOUPLED,
    )
    assert resolve(DOSAGE_COUPLED, AMP, DEP_CORR, SILENCING_CONFOUNDED)[0] == "coherent_cis_driver"


def test_nothing_fired_is_default_insufficient():
    assert resolve() == ("insufficient_cis_coherence", None)


def test_dosage_only_no_leg2_is_insufficient():
    # leg-1 present but leg-2 entirely unmeasured (no correlation/conjoint token) → cannot assemble
    # the chain → honest abstention, NOT a coherent or inert claim.
    assert resolve(DOSAGE_COUPLED) == ("insufficient_cis_coherence", None)
    assert resolve(DOSAGE_COUPLED, AMP) == ("insufficient_cis_coherence", None)
    assert resolve(DOSAGE_COUPLED, DEL) == ("insufficient_cis_coherence", None)


def test_every_resolver_verdict_is_in_the_pinned_enum():
    """The resolver is the source of truth for cis_coherence_verdict; the skill-output pins and the
    decision schema must both admit every rung it can produce. A new rung whose verdict is missing from
    the enum is a run-time schema violation on a REAL target, not a test-only gap — coherent_cis_loss_of_
    function is exactly that kind of addition."""
    import json

    produced = {r["verdict"] for r in SPEC["resolve"]} | {SPEC["default"]}
    pins = json.loads((REPO / "schemas" / "_skill_output" / "pins" / "cis-feature-coherence.pins.json").read_text())
    pinned = set(pins["$defs"]["cis_coherence_verdict_enum"]["enum"])
    decision = json.loads((REPO / "schemas" / "skills" / "cis-feature-coherence.decision.schema.json").read_text())
    declared = set(decision["$defs"]["cis_coherence_verdict_enum"]["enum"])
    assert produced <= pinned, f"resolver verdicts missing from the pins enum: {sorted(produced - pinned)}"
    assert produced <= declared, f"resolver verdicts missing from the decision schema: {sorted(produced - declared)}"


def test_leg2_only_no_dosage_is_insufficient():
    # leg-2 present but leg-1 untestable (cn_invariant_panel / data_unavailable fire no leg-1 token)
    # → cannot establish whether the dependency is cis-driven → abstain.
    assert resolve(DEP_CORR) == ("insufficient_cis_coherence", None)
    assert resolve(DEP_CONJOINT) == ("insufficient_cis_coherence", None)
