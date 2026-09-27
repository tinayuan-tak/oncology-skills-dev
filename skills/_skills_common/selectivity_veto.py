"""Shared selectivity VETO clamp for the tumor-selectivity gate (5 arms, 3 outcomes).

The selectivity axis-A verdict (from target-contracts/resolvers/selectivity.resolver.yaml) is
NECESSARY but NOT SUFFICIENT: a gene over-expressed vs its tissue of origin but with NO therapeutic
window vs the worst critical normal (a housekeeping archetype — GAPDH/ACTB, or the TROP2/TACSTD2
broadly-normal surface archetype) is not a real target regardless of its axis-A fold-change. This
POST-RESOLVER clamp downgrades a selective axis-A verdict when ANY selectivity veto rule fired
(worst-case conjunction, first arm in precedence wins the label). One-directional: it can only
DOWNGRADE a selective call, never upgrade.

The five arms produce THREE distinct outcomes (the 2026-08-19 sc-normal-liability SPLIT + the
2026-08-31 INT-axis stromal arm) — see `_VETO_RULE_VERDICT` below:
  - two KILLs        — `selective_but_broadly_normal` (bulk window arms) and
                       `selective_but_stromal_confound` (the signal is in the WRONG cells);
  - one PRESERVING   — `selective_with_normal_liability` (sc-normal critical-organ + TPHP
                       normal-protein): the target IS tumor-selective and ALSO carries a named
                       normal liability that safety/modality-fit own, not a loss of selectivity.
Precedence: stromal-confound > window > full-normal > sc-normal > tphp-normal-protein.

MODALITY-CONDITIONAL (2026-09-12): the veto rules in target-contracts declare PER-MODALITY signals,
and three of the five arms declare `adc: neutral` on purpose — `tvn-no-full-normal-window-veto` names
sacituzumab/Dato-DXd (broad-LOW normal is ADC-tolerable; the payload/bystander buffer arbitrates),
and the sc-normal + TPHP arms carry the same precedent. The clamp used to ignore that lens entirely
and map every fired arm straight to its verdict, so the framework KILLED validated ADC antigens in
their approved indication on evidence its own contract calls neutral for that modality. When a
modality lens is supplied AND the essential-organ axis is affirmatively clean, a KILL arm whose own
`signals[modality]` is `neutral`/`supportive` is SKIPPED and precedence falls through to the next arm
— so an arm that is `opposing` for that modality (e.g. the essential-organ window veto, where the
tumor sits below a VITAL organ) still KILLs. Three deliberate asymmetries: (a) the PRESERVING outcome
is never modality-suppressed — a named normal liability is informative for every modality and blocks
nothing; (b) with NO modality lens the clamp is worst-case exactly as before, so default runs are
byte-identical; (c) the waiver requires `therapeutic_window_class == clean_window` — the "CLEAN VS THE
ESSENTIAL SET" clause of the contract's own ADC-neutrality comment. Without (c) the 36-target panel
measured designed true negatives ESCAPING (RPL13A/COADREAD, MUC1/BRCA — both `narrow_window`, a class
that fires no rung in this lens, so the full-normal KILL was the only thing holding them down).

WHY SHARED: the clamp is single-sourced here and applied in ALL consumers — tumor-selectivity's
run.py::_verdict, the composed engine (_skills_common.compose_core.resolve_gate_spine) and
_skills_common.flip_analysis — so they apply it identically. (The engine resolves selectivity via the
raw resolver, which has no veto rungs; without this shared clamp it would report
`strong_tumor_selective` for a broadly-normal gene that the standalone skill downgrades.) The clamp is
a NO-OP unless a veto rule actually fired AND the verdict is a selective axis-A class, so non-veto
targets are byte-unchanged in every engine.
"""

from __future__ import annotations

SELECTIVITY_GATE = "selectivity"

# The axis-A "selective" verdicts the normal-breadth veto can downgrade.
_AXIS_A_SELECTIVE = frozenset(
    {
        "strong_tumor_selective",
        "modest_tumor_selective",
        "field_effect_tumor_selective",
    }
)

# All normal-breadth veto rule_ids — ANY firing downgrades a selective axis-A call. Ordered by the
# precedence used for the driving_rule LABEL when several fire: essential-organ window > pan-normal
# window > sc-normal cell-type > tphp normal-protein (the bulk window vetoes are the longer-standing
# instruments). NOTE the arms do NOT all yield the same verdict — the two window arms KILL, the
# sc-normal + tphp arms are selectivity-PRESERVING (see `_VETO_RULE_VERDICT`). Mirrors
# modality-therapeutic-window (2 arms) + sc-normal-celltype-expression (1) + tphp normal-protein (1).
_WINDOW_VETO_RULE = "tvn-no-therapeutic-window-veto"
_FULL_NORMAL_VETO_RULE = "tvn-no-full-normal-window-veto"
_SC_NORMAL_VETO_RULE = "tvn-sc-normal-critical-organ-veto"
# 4th arm (2026-08-25): quantitative normal-PROTEIN abundance liability (TPHP DIA-MS). Fires on the
# normal-tissue-protein-abundance-tphp card's tphp_normal_protein_liability_class == broad_and_abundant
# (abundance-gated Floor-C, NOT DIA detection). Like the sc-normal arm it is SELECTIVITY-PRESERVING ->
# selective_with_normal_liability (a named normal-protein liability, not the housekeeping KILL).
_TPHP_NORMAL_PROTEIN_VETO_RULE = "tvn-tphp-broad-abundant-normal-protein-veto"
_NORMAL_BREADTH_VETO_RULES = (
    _WINDOW_VETO_RULE,
    _FULL_NORMAL_VETO_RULE,
    _SC_NORMAL_VETO_RULE,
    _TPHP_NORMAL_PROTEIN_VETO_RULE,
)

# The INT-axis (tumor-cell-INTRINSIC) veto — the stromal-confound arm (2026-08-31). Distinct from the
# four SAFE-axis normal-breadth arms above: it fires when the bulk axis-A selective signal is driven by
# CAF/stroma rather than the malignant cells (tumor-scrna-celltype-expression stromal_confound_class ==
# stromal_confounded), a FALSE window for tumor-cell-targeted modalities. Symmetric instrument, orthogonal
# axis. Provenance-gated in the reader (only a trustworthy cube emits stromal_confounded), so the clamp
# never fires on a weak-annotation cube.
_STROMAL_CONFOUND_VETO_RULE = "tvn-stromal-confound-veto"

# The clamp produces two DISTINCT downgrade outcomes (the sc-normal-liability SPLIT, 2026-08-19):
#   - the therapeutic-window arms (tumor BELOW the worst critical/full normal — housekeeping GAPDH,
#     the TROP2 broadly-normal surface archetype) → the KILL: no real tumor-vs-normal window at all.
#   - the sc-normal critical-organ arm → a SELECTIVITY-PRESERVING named-organ flag: the target IS
#     tumor-selective (a real window vs origin) but is also expressed in an essential cell type of a
#     NON-origin critical organ that bulk medians dilute. Approved antigens (DLL3 forebrain neuron,
#     ERBB2 cardiomyocyte/nephron, FOLR1 renal) land here — their normal expression is REAL but they
#     are drugs via modality/accessibility/clinical precedent, so this is a SAFETY/therapeutic-index
#     concern (owned by on-target-safety-liability + modality-fit), NOT loss of selectivity. Measured
#     on the #416 backtest panel: the old single-verdict clamp collapsed these into the housekeeping
#     KILL — a false-negative for approved drugs (the CD19 "over-eager clamp kills good targets" lesson).
_VETO_VERDICT = "selective_but_broadly_normal"  # housekeeping / no-window KILL (SAFE axis)
_LIABILITY_VERDICT = "selective_with_normal_liability"  # sc-normal critical-organ: selectivity-preserving
_STROMAL_CONFOUND_VERDICT = "selective_but_stromal_confound"  # INT-axis KILL: axis-A signal is in the WRONG cells
# rule_id → the verdict its firing produces. Precedence is the _SELECTIVITY_VETO_PRECEDENCE order below:
# when BOTH a window veto AND the sc-normal arm fire (e.g. TACSTD2/TROP2), the window KILL wins — a gene
# with no window at all is not rescued by also having a named-organ liability.
_VETO_RULE_VERDICT = {
    _STROMAL_CONFOUND_VETO_RULE: _STROMAL_CONFOUND_VERDICT,  # INT-axis KILL (wrong cells)
    _WINDOW_VETO_RULE: _VETO_VERDICT,
    _FULL_NORMAL_VETO_RULE: _VETO_VERDICT,
    _SC_NORMAL_VETO_RULE: _LIABILITY_VERDICT,
    _TPHP_NORMAL_PROTEIN_VETO_RULE: _LIABILITY_VERDICT,  # normal-PROTEIN abundance liability (selectivity-preserving)
}

# FULL precedence order across ALL selectivity veto arms — first firing wins the verdict + driving label.
# OPTION B (2026-08-31): the INT-axis stromal-confound KILL OUTRANKS the SAFE-axis normal-breadth window
# KILL. When a gene is BOTH stroma-driven AND broadly-normal (FAP/POSTN/collagen), "the antigen is not on
# the tumor cells" is the more fundamental disqualifier for a tumor-cell-targeted modality — and the more
# actionable nomination signal — than "broadly expressed in normal tissue". Then the two SAFE-axis KILLs,
# then the two selectivity-preserving SAFE-axis liabilities. All arms only DOWNGRADE a selective axis-A call.
_SELECTIVITY_VETO_PRECEDENCE = (
    _STROMAL_CONFOUND_VETO_RULE,
    _WINDOW_VETO_RULE,
    _FULL_NORMAL_VETO_RULE,
    _SC_NORMAL_VETO_RULE,
    _TPHP_NORMAL_PROTEIN_VETO_RULE,
)
# All clamp outcomes still had axis-A over-expression hold; consumers asking "did any selectivity veto
# fire?" should test membership here (now incl. the INT-axis stromal-confound outcome).
_VETO_OUTCOMES = frozenset(_VETO_RULE_VERDICT.values())


# ── #796: MARROW-COVERAGE TRANSIENT ABSTAIN ──────────────────────────────────────────────────────────
# A SECOND, orthogonal post-resolver clamp stage, applied AFTER apply_normal_breadth_veto (see
# run.py::_verdict). NOT a veto arm: it is not driven by any fired rule_id and its output is NOT a
# _VETO_OUTCOME. It is an ABSTAIN, not a KILL.
#
# THE BUG (#796): the primary-marrow reader (analysis-methods tcga_gtex_tpm_quantiles/marrow.py) caches
# a read failure for the whole process. A TRANSIENT outage (network / creds / throttle / 5xx / parse)
# used to be indistinguishable from a definitive config miss — both surfaced marrow_substrate ==
# "unavailable". When marrow drops out of the essential-organ denominator, window_ratio_essential
# INFLATES, therapeutic_window_class moves OFF no_therapeutic_window, tvn-no-therapeutic-window-veto
# never fires, and the essential-window KILL SILENTLY VANISHES for myeloid-argmax targets
# (CD33 / CLEC12A / IL3RA / FLT3). analysis-methods now mints a DISTINCT marrow_substrate ==
# "unavailable_transient" token for transient causes (definitive misses keep "unavailable").
#
# THE ABSTAIN: when the marrow substrate is transiently unavailable AND the target is marrow-PLAUSIBLE
# (could plausibly have marrow as its essential-window argmax), a still-selective axis-A call is
# WITHHELD as `selective_pending_marrow_coverage` — "the safety denominator is transiently incomplete;
# re-run to resolve". It does NOT fabricate a KILL and does NOT clear a KILL that fired on other
# grounds: it runs AFTER the veto walk, so if any veto fired the verdict is already a KILL/liability
# ∉ _AXIS_A_SELECTIVE and this stage is a no-op (that is how "never clears a KILL" is enforced by
# construction). withhold_only: the ONLY transition it makes is selective-axis-A → the abstain.
#
# MARROW-PLAUSIBILITY is derived WITHOUT the missing marrow value — the transient is process-wide and
# hits every target, so the signal MUST come from an INDEPENDENT substrate. It reads the
# sc-normal-celltype-expression card's sc_normal_essential_max_tissue (CELLxGENE single-cell atlas,
# unaffected by the HPA bulk-marrow outage): a target whose single-cell normal essential-organ argmax
# is bone marrow is exactly one whose bulk-marrow denominator, had it loaded, could have been the
# essential-window argmax. Absent that signal the abstain does NOT fire (fail-open on the withhold —
# a transient with no independent marrow evidence leaves the call unchanged, never scope-creeps to all
# targets).
SUBSTRATE_UNAVAILABLE_TRANSIENT = "unavailable_transient"
_MARROW_SUBSTRATE_CARD = "modality-therapeutic-window"
_MARROW_SUBSTRATE_FIELD = "marrow_substrate"
_MARROW_PLAUSIBLE_CARD = "sc-normal-celltype-expression"
_MARROW_PLAUSIBLE_FIELD = "sc_normal_essential_max_tissue"
_MARROW_PLAUSIBLE_VALUES = frozenset({"bone marrow"})  # note the SPACE (CELLxGENE tissue label), not an underscore
_MARROW_COVERAGE_ABSTAIN_VERDICT = "selective_pending_marrow_coverage"
_MARROW_COVERAGE_ABSTAIN_DRIVER = "tvn-marrow-coverage-transient-abstain"  # provenance label (NOT a fired rule_id)

# The FULL post-resolver clamp verdict set = the rule-fired veto OUTCOMES ∪ the substrate-conditioned
# abstain. Kept in lockstep with target-contracts resolvers/selectivity.resolver.yaml `clamp_verdicts`
# by a skills-side guard test (tumor-selectivity/tests/test_verdict.py). The abstain is deliberately
# NOT a _VETO_OUTCOME (not driven by a fired rule_id, absent from precedence / never-suppressed math),
# so all veto-precedence logic stays on _VETO_OUTCOMES unchanged.
_CLAMP_VERDICTS = _VETO_OUTCOMES | {_MARROW_COVERAGE_ABSTAIN_VERDICT}


# ── MODALITY-CONDITIONAL KILL SUPPRESSION (2026-09-12) ───────────────────────────────────────────────
# The veto rules in target-contracts already carry a per-modality lens in their `signals:` block, and
# the KILL arms are NOT uniformly opposing: `tvn-no-full-normal-window-veto` declares `adc: neutral`
# with the comment "the TROP2/TACSTD2 salivary-gland archetype: broad-LOW normal (clean vs the
# essential set) is ADC-tolerable — sacituzumab/Dato-DXd are validated ADCs here; the bystander/payload
# buffer + internalization arbitrate (density-led)". The clamp ignored that lens, so a validated ADC
# antigen was downgraded to the housekeeping KILL on evidence the contract itself calls neutral for
# ADCs. Honour the rule's OWN declaration rather than a Python-side modality table (the contract is the
# single source of truth, and a new arm's lens is picked up with no code change here).
#
# Scope is deliberately narrow:
#   - only the KILL outcomes can be suppressed. The selectivity-PRESERVING outcome is a named normal
#     liability that blocks nothing and is informative for every modality, so it always stands (its
#     arms also declare `adc: neutral`, and suppressing it would DELETE safety signal rather than
#     unblock a nomination).
#   - suppression FALLS THROUGH to the next arm in precedence. An arm that is `opposing` for the chosen
#     modality still KILLs — e.g. the essential-organ `tvn-no-therapeutic-window-veto` is `opposing`
#     for all four modalities (tumor below a VITAL organ is not payload-buffered), so an ADC lens
#     never rescues a target that fails THAT arm.
#   - `None` modality (the default, and every composed/flip-analysis path today) is worst-case exactly
#     as before, so runs without an explicit lens are byte-identical.
# PRECONDITION (2026-09-12, found by the 36-target panel): the waiver is only sound when the
# ESSENTIAL-ORGAN axis is affirmatively CLEAN — which is exactly what the contract comment states
# ("broad-LOW normal (CLEAN VS THE ESSENTIAL SET) is ADC-tolerable"). Waiving on the `adc: neutral`
# declaration ALONE ignored that clause and let designed true negatives escape: measured on the panel,
# RPL13A/COADREAD (a ribosomal housekeeping decoy, tumor 641 TPM vs BONE_MARROW 617 — essential ratio
# 1.04) and MUC1/BRCA (182 vs LUNG 134, ratio 1.36) both rose from the housekeeping KILL to the
# selectivity-PRESERVING `selective_with_normal_liability`. Their essential axis is `narrow_window`, and
# `narrow_window` fires NO rung in this lens (the intracellular lens rules only `no_therapeutic_window`),
# so the full-normal KILL was the ONLY thing standing between a 600-TPM-everywhere gene and a preserving
# verdict — and the lens removed it. A narrow window against a VITAL organ is not payload-buffered, so
# the waiver now requires the measured essential class to be `clean_window`; anything else (narrow /
# no-window / not-expressed / data_unavailable / missing) FAILS CLOSED and the KILL stands.
_ESSENTIAL_WINDOW_CARD = "modality-therapeutic-window"
_ESSENTIAL_WINDOW_FIELD = "therapeutic_window_class"
_CLEAN_ESSENTIAL_WINDOW_CLASSES = frozenset({"clean_window"})

_KILL_VERDICTS = frozenset({_VETO_VERDICT, _STROMAL_CONFOUND_VERDICT})
# Only an EXPLICIT non-opposing declaration suppresses. `insufficient` means "coverage gap, not used as
# opposing evidence" elsewhere in the grammar, but a veto arm only fires when the measurement EXISTS,
# so treating it as a suppressor would be reading a data-availability token as a safety judgement.
# A missing / unknown / `opposing` signal keeps the KILL.
_NON_OPPOSING_MODALITY_SIGNALS = frozenset({"neutral", "supportive"})


def essential_window_class(cards) -> str | None:
    """The measured essential-organ window class from the ``modality-therapeutic-window`` card, or None
    when the card is absent. Helper so all three clamp consumers read the waiver PRECONDITION from the
    same field rather than each re-deriving it. ``cards`` is the resolved card list
    (``[{card_id, summary}, …]``)."""
    for card in cards or []:
        if card.get("card_id") == _ESSENTIAL_WINDOW_CARD:
            return (card.get("summary") or {}).get(_ESSENTIAL_WINDOW_FIELD)
    return None


def _essential_axis_is_clean(window_class) -> bool:
    """Fail-closed: only an affirmative ``clean_window`` satisfies the waiver's precondition."""
    return window_class in _CLEAN_ESSENTIAL_WINDOW_CLASSES


def _kill_suppressed_by_modality(rule: dict, modality, window_class=None) -> bool:
    """True when ``rule`` is a KILL arm that its OWN contract declares non-opposing for ``modality``
    AND the essential-organ axis is affirmatively clean (``window_class == clean_window``)."""
    if not modality:
        return False
    if not _essential_axis_is_clean(window_class):
        return False
    if _VETO_RULE_VERDICT.get(rule.get("rule_id")) not in _KILL_VERDICTS:
        return False
    return (rule.get("signals") or {}).get(modality) in _NON_OPPOSING_MODALITY_SIGNALS


def modality_suppressed_kill_arms(fired: list[dict], modality, window_class=None) -> list[str]:
    """Provenance for the headline/report: the rule_ids of KILL arms that DID fire but were suppressed
    by ``modality``'s declared lens. Empty for every modality-less run, and empty whenever the waiver's
    essential-window precondition is unmet — this MUST stay in lockstep with apply_normal_breadth_veto
    or the headline would claim a waiver the verdict never granted. Exposed so a suppressed KILL is
    VISIBLE rather than silently absent — a consumer must be able to see that the target failed a
    normal-breadth arm and that the arm was waived for this modality, not that it never fired."""
    if not modality:
        return []
    return [
        r.get("rule_id")
        for r in fired
        if r.get("rule_id") in _SELECTIVITY_VETO_PRECEDENCE and _kill_suppressed_by_modality(r, modality, window_class)
    ]


# ── #978: protein + population-normal RESCUE of a flat/discordant matched-adjacent-RNA arm ───────────
# For a CEA/EpCAM-class antigen whose ADJACENT normal tissue ALSO expresses the target, the tumor-vs-
# matched-adjacent RNA-DGE arm is flat/mixed even when the tumor is genuinely elevated — collapsing the
# aggregate RNA classifier to `not_informative` / `discordant_across_comparators`. That flat adjacent arm
# must NOT sink a selectivity call that the INDEPENDENT protein + population-normal arms support. This is a
# one-directional UPGRADE clamp (the sign-mirror of apply_normal_breadth_veto): a rescue-eligible RNA
# verdict is lifted to `field_effect_tumor_selective` ONLY when BOTH (a) CPTAC tumor-vs-normal protein is up
# (sig + non-negligible effect — the strongly/modestly-up rules) AND (b) the population-normal percentile-
# crossing is up (the strong-crossing rule). Rests the rescue on TWO orthogonal arms, not the single
# batch-confounded GTEx comparator the classifier's own field-effect FIXes use, and extends the rescue to
# modest-GTEx / mixed-adjacent antigens the classifier cannot reach.
#
# APPLIED BEFORE apply_normal_breadth_veto (see run.py::_verdict / compose_core): the upgraded
# field_effect_tumor_selective is still a selective axis-A class, so the stromal-confound / no-window /
# sc-normal vetoes can STILL downgrade it — the FAP (stromal), TACSTD2 (no-window), GAPDH (housekeeping)
# safety nets are preserved. One-directional: only lifts a rescue-eligible RNA verdict, never touches a
# positive/negative call.
#
# BACKTEST NOTE (2026-09-04): inert on the current surface-antigen panel — CEACAM5 is already
# field_effect via the classifier's GTEx-based FIX2 (not rescue-eligible), and EPCAM's CPTAC protein is
# NOT tumor-elevated (its downgrade is a distinct mixed-adjacent RNA-classifier problem, tracked
# separately). Shipped as a byte-stable DEFENSIVE guard (unit-tested on synthetic fired-sets) that fires
# for a future modest-GTEx antigen with independent CPTAC + population support.
_RESCUE_ELIGIBLE = frozenset({"not_informative", "discordant_across_comparators"})
_CPTAC_UP_RULES = frozenset({"protein-strongly-up-supportive", "protein-modestly-up-neutral"})
_POP_NORMAL_UP_RULES = frozenset({"tumor-vs-normal-crossing-strong-supportive"})
_PROTEIN_POPULATION_RESCUE_DRIVER = (
    "tvn-protein-population-field-effect-rescue"  # provenance label (not a resolver rung)
)


def apply_protein_population_rescue(verdict, driving_rule_id, fired):
    """Post-resolver one-directional UPGRADE clamp (#978): lift a rescue-eligible RNA verdict
    (``not_informative`` / ``discordant_across_comparators`` — a flat/mixed matched-adjacent arm) to
    ``field_effect_tumor_selective`` when BOTH a CPTAC-protein-up rule AND the population-normal-crossing-up
    rule are in ``fired``. Returns the input pair unchanged otherwise. MUST be applied BEFORE
    apply_normal_breadth_veto so the normal-breadth / stromal-confound vetoes still downgrade the upgraded
    call. ``fired`` is the flat list of fired-rule dicts."""
    if verdict not in _RESCUE_ELIGIBLE:
        return verdict, driving_rule_id
    fired_ids = {r.get("rule_id") for r in fired}
    if (_CPTAC_UP_RULES & fired_ids) and (_POP_NORMAL_UP_RULES & fired_ids):
        return "field_effect_tumor_selective", _PROTEIN_POPULATION_RESCUE_DRIVER
    return verdict, driving_rule_id


def apply_normal_breadth_veto(verdict, driving_rule_id, fired, modality=None, window_class=None):
    """Post-resolver clamp: downgrade a SELECTIVE axis-A ``(verdict, driving_rule_id)`` when ANY
    selectivity veto rule is in ``fired``. The INT-axis stromal-confound arm → ``selective_but_stromal_
    confound`` (the axis-A signal is in the WRONG cells — CAF/stroma, not malignant); the SAFE-axis window
    arms → ``selective_but_broadly_normal`` (the housekeeping/no-window KILL); the sc-normal critical-organ
    AND tphp normal-protein arms → ``selective_with_normal_liability`` (selectivity-PRESERVING named
    liabilities). Precedence (Option B): stromal-confound > window > full-normal > sc-normal >
    tphp-normal-protein — the stromal-confound KILL (not on the tumor cells) outranks the normal-breadth
    KILL when both fire, and both KILLs outrank the named liabilities. Returns the input pair unchanged
    when the verdict is not a selective axis-A class or no veto fired. One-directional.

    ``modality`` is the OPTIONAL modality lens (``adc`` / ``bite_tce`` / ``small_molecule`` /
    ``degrader``). When given AND ``window_class`` (the measured essential-organ
    ``therapeutic_window_class``) is affirmatively ``clean_window``, a KILL arm that its own contract
    declares ``neutral``/``supportive`` for that modality is SKIPPED and precedence falls through to the
    next arm — see the MODALITY-CONDITIONAL block above. Selectivity-PRESERVING arms are never
    suppressed; a non-clean/absent ``window_class`` fails CLOSED (the KILL stands); and ``None`` modality
    (the default) reproduces the pre-2026-09-12 worst-case behavior exactly.

    ``fired`` is the flat list of fired-rule dicts (each with ``rule_id``, and — for the modality lens —
    the contract's ``signals`` block)."""
    if verdict not in _AXIS_A_SELECTIVE:
        return verdict, driving_rule_id
    fired_by_id = {r.get("rule_id"): r for r in fired}
    for veto_rule in _SELECTIVITY_VETO_PRECEDENCE:
        rule = fired_by_id.get(veto_rule)
        if rule is None:
            continue
        if _kill_suppressed_by_modality(rule, modality, window_class):
            continue
        return _VETO_RULE_VERDICT[veto_rule], veto_rule
    return verdict, driving_rule_id


def marrow_substrate_class(cards) -> str | None:
    """The marrow_substrate token from the ``modality-therapeutic-window`` card (``None`` when the card
    is absent). #796: analysis-methods mints ``"unavailable_transient"`` for a transient marrow-HPA read
    failure vs ``"unavailable"`` for a definitive config miss. ``cards`` is the resolved card list
    (``[{card_id, summary}, …]``)."""
    for card in cards or []:
        if card.get("card_id") == _MARROW_SUBSTRATE_CARD:
            return (card.get("summary") or {}).get(_MARROW_SUBSTRATE_FIELD)
    return None


def marrow_plausible_from_cards(cards) -> bool:
    """True when the target is marrow-PLAUSIBLE per an INDEPENDENT substrate: the
    ``sc-normal-celltype-expression`` card's ``sc_normal_essential_max_tissue`` is bone marrow (the
    CELLxGENE single-cell atlas, unaffected by the HPA bulk-marrow transient). Derived WITHOUT the
    missing marrow value so the abstain cannot scope-creep to all targets during a process-wide
    transient. Fail-open (returns False) when the card or field is absent."""
    for card in cards or []:
        if card.get("card_id") == _MARROW_PLAUSIBLE_CARD:
            return (card.get("summary") or {}).get(_MARROW_PLAUSIBLE_FIELD) in _MARROW_PLAUSIBLE_VALUES
    return False


def apply_marrow_coverage_abstain(verdict, driving_rule_id, marrow_substrate, marrow_plausible):
    """Post-resolver ABSTAIN clamp (#796), applied AFTER apply_normal_breadth_veto. WITHHOLDS a
    still-selective axis-A ``(verdict, driving_rule_id)`` as ``selective_pending_marrow_coverage`` when
    the marrow substrate is TRANSIENTLY unavailable (``marrow_substrate == "unavailable_transient"``)
    AND the target is marrow-PLAUSIBLE. Returns the input pair unchanged otherwise.

    withhold_only: it never fabricates a KILL and never clears a KILL that fired on other grounds — it
    only acts on a verdict that is STILL a selective axis-A class, so if apply_normal_breadth_veto
    already downgraded to a KILL/liability (∉ _AXIS_A_SELECTIVE) this is a no-op. The DEFINITIVE
    ``"unavailable"`` token does NOT trigger it, and a non-plausible target is left unchanged (no
    scope-creep to all targets during a process-wide transient)."""
    if verdict not in _AXIS_A_SELECTIVE:
        return verdict, driving_rule_id
    if marrow_substrate != SUBSTRATE_UNAVAILABLE_TRANSIENT:
        return verdict, driving_rule_id
    if not marrow_plausible:
        return verdict, driving_rule_id
    return _MARROW_COVERAGE_ABSTAIN_VERDICT, _MARROW_COVERAGE_ABSTAIN_DRIVER
