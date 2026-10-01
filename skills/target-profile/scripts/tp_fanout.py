"""target-profile — sub-skill fan-out orchestration: the SUB_SKILLS / SUB_SKILL_CARDS
composition maps, per-sub-skill verdict loading, the concurrent fan-out, and the opt-in subtype tier."""

from __future__ import annotations

import concurrent.futures
import importlib.util
import inspect
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Optional

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from _skills_common import fired_rules, resolve_cards
from _skills_common import narrator_lenses as _narrator_lenses
from _skills_common.card_preprocessors import preprocess_cards_for_gate
from _skills_common.compose_core import subskill_composition
from _skills_common.evidence_graph import attach_evidence_graph
from _skills_common.literature_retrieval import default_retrieve, verify_citations
from _skills_common.literature_synthesis import make_literature_fn
from _skills_common.narrator_engine import LensConfig as _LensConfig
from _skills_common.narrator_engine import make_synthesize_fn
from _skills_common.skill_report import ROLE_GATING, build_skill_report
from _skills_common.subgroup_derivation import subgroup_signals_for
from _skills_common.subtype_axis import is_differential_axis  # SK#1624 powered-axis gate for the differential mint
from tp_common import SKILLS_DIR

# Central per-skill narrator/literature lens registry, auto-collected by `LensConfig.name` (== the skill
# dir id). Lets the fan-out run a sub-skill's OWN --literature lane (make_literature_fn) centrally, WITHOUT
# importing each skill's run.py or adding a per-skill hook. Future-proof: a new lens declared in
# narrator_lenses is picked up automatically. Skills with no lens simply get no per-subskill literature.
_SKILL_LENS = {v.name: v for v in vars(_narrator_lenses).values() if isinstance(v, _LensConfig)}


# PERF: fan-out thread-pool worker cap. min(#sub-skills, cores-2) — headroom-aware; env
# override for tuning/CI. Threads (not processes) so the process-global method caches are shared.
_FANOUT_MAX_WORKERS = int(os.environ.get("TARGET_PROFILE_FANOUT_WORKERS", max(2, (os.cpu_count() or 4) - 2)))


# --- Sub-skill orchestration ------------------------------------------------

_SUBSKILL_FN_CACHE: dict = {}
# Module cache populated by _load_sub_skill_verdict_fn (prewarm runs it first, single-threaded), so
# the OPTIONAL _synthesis_facet loader below reads the SAME already-exec'd module — no second
# importlib.exec_module / sys.path race in the concurrent pool.
_SUBSKILL_MODULE_CACHE: dict = {}


def _load_sub_skill_verdict_fn(skill_dir_name: str) -> Any:
    """Load a sub-skill's run.py module and return its `_verdict()` or
    `_snapshot()` function (whichever exists). Sub-skills follow the
    convention of exposing one such function; we grab it via importlib
    so target-profile doesn't hard-code each sub-skill's Python path.

    MEMOIZED (perf): each sub-skill module is exec'd ONCE. This both avoids
    re-executing modules per call AND makes the concurrent fan-out safe — the pool
    workers hit the cache (populated by _prewarm_sub_skill_imports before the pool),
    so no two threads run importlib.exec_module / sys.path.insert concurrently.
    """
    fn = _SUBSKILL_FN_CACHE.get(skill_dir_name, "__miss__")
    if fn != "__miss__":
        return fn
    run_py = SKILLS_DIR / skill_dir_name / "scripts" / "run.py"
    spec = importlib.util.spec_from_file_location(
        f"_subskill_{skill_dir_name.replace('-', '_')}",
        run_py,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _SUBSKILL_MODULE_CACHE[skill_dir_name] = module
    fn = getattr(module, "_verdict", None) or getattr(module, "_snapshot", None)
    _SUBSKILL_FN_CACHE[skill_dir_name] = fn
    return fn


def _load_sub_skill_facet_fn(skill_dir_name: str) -> Any:
    """Return a sub-skill's OPTIONAL `_synthesis_facet(cards, fired, verdict_pair) -> dict`, or None.

    This is the uniform opt-in a sub-skill uses to hand the composed synthesis its own DETERMINISTIC
    cross-modal reconciliation (e.g. tumor-presence's per-modality presence matrix + proxy-quality +
    normal comparators) — so the LLM reasons over the skill's computed reconciliation instead of
    re-deriving it from raw card numbers. Reads the module cached by _load_sub_skill_verdict_fn
    (prewarmed single-threaded), so no sub-skill without the hook pays any cost and the concurrent
    pool never re-execs a module. VERDICT-INERT: the facet never enters `fired` or the resolver."""
    module = _SUBSKILL_MODULE_CACHE.get(skill_dir_name)
    if module is None:
        _load_sub_skill_verdict_fn(skill_dir_name)  # populate the module cache
        module = _SUBSKILL_MODULE_CACHE.get(skill_dir_name)
    return getattr(module, "_synthesis_facet", None) if module is not None else None


def _load_sub_skill_headline_fn(skill_dir_name: str) -> Any:
    """Return a sub-skill's OPTIONAL `_headline(cards, fired, verdict_pair[, target, indication]) -> dict`,
    or None. Same uniform module hook as `_load_sub_skill_facet_fn`. Used ONLY to reconstruct a headline
    (with `evidence_capsules` + `subgroup_signals`) so `build_evidence_graph` can be called in composition
    exactly as the standalone dispatcher calls it — the composed fan-out otherwise never builds a headline.
    VERDICT-INERT + DISPLAY-ONLY: the headline is recomputed purely to project the evidence_graph and never
    re-enters `fired`/`verdict`/`cards` or the resolver."""
    module = _SUBSKILL_MODULE_CACHE.get(skill_dir_name)
    if module is None:
        _load_sub_skill_verdict_fn(skill_dir_name)  # populate the module cache
        module = _SUBSKILL_MODULE_CACHE.get(skill_dir_name)
    # Accept the alt hook name _headline_fn too: genomic-alteration-profile names its headline hook
    # _headline_fn (passed explicitly to the standalone dispatcher via headline_fn=), so a bare
    # getattr("_headline") missed it — the composed reconstruction got an EMPTY headline → no claim_vector
    # → the literature synthesis mis-tagged every genomic axis omics_unavailable → overall insufficient
    # (genomic literature discordance was UNMEASURABLE composed, though it works standalone). Fall back to
    # _headline_fn so the composed evidence-graph + per-subskill lit lane get genomic's claim_vector.
    if module is None:
        return None
    return getattr(module, "_headline", None) or getattr(module, "_headline_fn", None)


def _reconstruct_decision(skill_dir_name, cards, fired, verdict_pair, target, indication) -> dict:
    """Reconstruct a DISPLAY-ONLY decision dict (`{skill, target, indication, headline, cards,
    fired_rules}`) for a sub-skill inside the fan-out — the shape both the evidence_graph projection and
    the optional per-subskill literature lane consume, exactly as the standalone dispatcher would.
    VERDICT-INERT + best-effort: the reconstructed headline is never stored or re-fed to the resolver;
    a missing `_headline` hook / any failure → an empty headline (a partial decision still projects)."""
    headline: dict = {}
    hl_fn = _load_sub_skill_headline_fn(skill_dir_name)
    if hl_fn is not None:
        kwargs = {}
        try:
            hp = inspect.signature(hl_fn).parameters
            if "target" in hp:
                kwargs["target"] = target
            if "indication" in hp:
                kwargs["indication"] = indication
        except (ValueError, TypeError):
            kwargs = {}
        try:
            headline = hl_fn(cards, fired, verdict_pair, **kwargs) or {}
        except Exception:  # noqa: BLE001 — headline recompute failed (e.g. missing cards on a gateless skill)
            headline = {}
    # Attach evidence_capsules exactly as the standalone dispatcher does (dispatcher.py: after the
    # headline hook, CENTRALLY — not inside the hook). The fan-out only calls the `_headline` hook, so
    # without this the reconstructed headline has NO capsules → build_evidence_graph reads caps={} →
    # every card's key_evidence (effect / n / significance / top_strata / raw data rows) AND its typed
    # reference-frame interpretation rulers come back empty, because _build_key_evidence keys all of
    # them off the capsule (measurement_type + values live on the capsule, not the card). This restores
    # the composed drill-downs to standalone parity. VERDICT-INERT / display-only / best-effort.
    if isinstance(headline, dict):
        try:
            from _skills_common.evidence_capsule import emit_capsules

            headline.setdefault("evidence_capsules", emit_capsules(cards, indication))
        except Exception:  # noqa: BLE001 — verdict-inert projection; never break the fan-out
            pass
    return {
        "skill": skill_dir_name,
        "target": target,
        "indication": indication,
        "headline": headline,
        "cards": cards,
        "fired_rules": fired,
    }


def _load_sub_skill_certainty_fn(skill_dir_name: str) -> Any:
    """Return a sub-skill's OPTIONAL `_strength_certainty(cards, fired, verdict_pair) -> dict`, or None.

    The uniform opt-in a sub-skill uses to hand the composed layer its per-axis (strength, certainty)
    SIDECAR (CERTAINTY_MODEL) — a verdict-inert reliability object keyed by sub-skill short. Mirrors
    `_load_sub_skill_facet_fn`: reads the prewarmed module cache, so a sub-skill without the hook pays
    no cost. Only functional-requirement (the reference axis) supplies it today. VERDICT-INERT: the
    certainty object never enters `fired`, the resolver, or the nomination sub_verdicts."""
    module = _SUBSKILL_MODULE_CACHE.get(skill_dir_name)
    if module is None:
        _load_sub_skill_verdict_fn(skill_dir_name)  # populate the module cache
        module = _SUBSKILL_MODULE_CACHE.get(skill_dir_name)
    return getattr(module, "_strength_certainty", None) if module is not None else None


def _load_sub_skill_claim_record_fn(skill_dir_name: str) -> Any:
    """Return a sub-skill's OPTIONAL `_claim_record(cards, fired, verdict_pair) -> dict`, or None.

    M1 of the factored-record migration (target-contracts VERDICT_REPRESENTATION_MIGRATION.md): the
    uniform opt-in a sub-skill uses to hand the composed layer its factored claim record SHADOW
    (schemas/claim_record.schema.json) — a verdict-inert typed record keyed by sub-skill short.
    Mirrors `_load_sub_skill_certainty_fn` exactly; a sub-skill without the hook pays no cost.
    CONSUMED BY NOTHING at M1 — the record never enters `fired`, the resolver, or the nomination
    sub_verdicts; it is surfaced beside the verdict spine for the M2 render-equivalence proof."""
    module = _SUBSKILL_MODULE_CACHE.get(skill_dir_name)
    if module is None:
        _load_sub_skill_verdict_fn(skill_dir_name)  # populate the module cache
        module = _SUBSKILL_MODULE_CACHE.get(skill_dir_name)
    return getattr(module, "_claim_record", None) if module is not None else None


# Module-level literal NAMES a sub-skill declares to tune its own sub-group panel, discovered by
# CONVENTION (suffix) rather than a per-skill registry. Every one of the 12 panel-tuning skills follows
# it exactly — `_<SHORT>_VALUE_TIERS` (the value→tier map) and, where the first-`*_class` heuristic is
# ambiguous, `_<SHORT>_SUBGROUP_READER` (the explicit per-measurement_type field spec).
_SUBGROUP_TIERS_SUFFIX = "_VALUE_TIERS"
_SUBGROUP_READER_SUFFIX = "_SUBGROUP_READER"


def _load_sub_skill_subgroup_reader(skill_dir_name: str) -> tuple[Optional[dict], Optional[Any]]:
    """Return the `(reader_spec, classify)` pair a sub-skill's STANDALONE run uses for its sub-group panel.

    WHY (2026-09-12): the composed panel was built by a bare `subgroup_signals_for(skill_dir, cards)` —
    NO reader_spec, NO classify — so it fell back to `_heuristic_reader` (binds the FIRST `*_class` key in
    summary DICT ORDER) and the lens-blind `default_classify` (substring heuristic; anything without a
    strong/moderate/weak keyword reads `absent`). Meanwhile 12 sub-skills DO tune their standalone panel
    (11 pass `subgroup_classify=` to run_wired_skill, genomic-alteration-profile calls
    `subgroup_signals_for` itself), and target-intrinsic + functional-requirement also pass an explicit
    `subgroup_reader_spec=`. ALL of it was dropped in composition, so the embedded lens view in the
    composed dashboard showed DIFFERENT sub-group tiers than the standalone skill report from the SAME
    evidence — e.g. target-intrinsic's `potent_measured_ligand` (its strongest tractability precedent)
    read `absent` composed and `strong` standalone.

    Discovery is by the module-literal naming CONVENTION above, not a hand-maintained map, so a new
    panel-tuning skill is picked up automatically. `test_subgroup_reader_parity.py` AST-verifies, per
    skill, that what this returns is exactly what that skill's own standalone call passes — the guard
    that keeps a convention from silently drifting into a divergence.

    Reads the prewarmed module cache like the sibling `_load_sub_skill_*` hooks; a skill that tunes
    nothing pays no cost and gets `(None, None)` (the framework default). VERDICT-INERT: the panel is a
    display projection — it never enters `fired`, the resolver, or the nomination sub_verdicts."""
    module = _SUBSKILL_MODULE_CACHE.get(skill_dir_name)
    if module is None:
        _load_sub_skill_verdict_fn(skill_dir_name)  # populate the module cache
        module = _SUBSKILL_MODULE_CACHE.get(skill_dir_name)
    if module is None:
        return None, None
    reader_spec = classify = None
    for name, val in vars(module).items():
        if not name.startswith("_") or not isinstance(val, dict):
            continue
        if name.endswith(_SUBGROUP_READER_SUFFIX):
            reader_spec = val
        elif name.endswith(_SUBGROUP_TIERS_SUFFIX):
            from _skills_common.subgroup_derivation import make_value_classifier

            classify = make_value_classifier(val)
    return reader_spec, classify


import random  # noqa: E402 — used only by the best-effort synthesis retry below
import threading  # noqa: E402

# The deterministic fan-out is concurrent (one thread per sub-skill). The OPTIONAL per-sub-skill
# Bedrock narration, however, throttles hard (503) when all narrators fire at once, so serialize
# JUST the synthesis Bedrock calls behind this lock — the card reads / verdict spine stay concurrent.
# Combined with the jittered retry below, this clears the concurrent-throttle failure mode.
_SYNTH_LOCK = threading.Lock()

# Transient Bedrock conditions worth a backoff retry (throttling / capacity), vs a hard error
# (auth, bad request) that will never clear. Matched on the message since the shared llm layer
# surfaces provider errors as strings/typed exceptions with these tokens.
_TRANSIENT_SYNTHESIS_TOKENS = (
    "503",
    "ServiceUnavailable",
    "Throttl",
    "Too many",
    "TooManyRequests",
    "capacity",
    "timeout",
    "Timeout",
    "429",
)


def _is_transient_synth(err: str) -> bool:
    return any(tok in (err or "") for tok in _TRANSIENT_SYNTHESIS_TOKENS)


def _synthesize_with_retry(
    synth_fn,
    cards,
    fired,
    verdict_pair,
    target,
    indication,
    synthesis_model,
    *,
    max_attempts: int = 4,
    literature_synthesis=None,
) -> dict:
    """Call a sub-skill's _llm_synthesis with backoff on TRANSIENT Bedrock errors (503/throttle),
    which are common when the concurrent fan-out fires all narrators at once. Best-effort +
    VERDICT-INERT: a persistent failure returns a {_synthesis_error} note; never raises.

    `literature_synthesis` (optional) is the per-sub-skill literature lane computed BEFORE narration;
    it is threaded into the decision the narrator reads (each hook sets
    decision['literature_synthesis']) so the exec_bullets weave + cite the literature. None → the hook
    narrates over an empty literature lane, byte-identical to the pre-reorder behaviour.

    Jittered exponential backoff spreads the retries so simultaneously-throttled narrators do not
    re-collide. A non-transient error (auth / bad request) fails fast — no point retrying."""
    last_err = None
    for attempt in range(max_attempts):
        try:
            with _SYNTH_LOCK:  # serialize the Bedrock call across the concurrent fan-out (anti-throttle)
                result = synth_fn(
                    cards,
                    fired,
                    verdict_pair,
                    target,
                    indication,
                    synthesis_model,
                    None,
                    literature_synthesis=literature_synthesis,
                )
        except Exception as e:  # noqa: BLE001 — narration must never break the fan-out
            last_err = f"{type(e).__name__}: {e}"
            result = None
        # A narrator may swallow the provider error and RETURN a {_synthesis_error} dict instead of raising.
        if isinstance(result, dict) and "_synthesis_error" in result:
            last_err = str(result.get("_synthesis_error"))
            if not _is_transient_synth(last_err):
                return result  # hard error — surface as-is, no retry
        elif result is not None:
            return result  # success
        if attempt < max_attempts - 1 and _is_transient_synth(last_err or ""):
            time.sleep(min(30.0, 2.0 * (2**attempt)) + random.uniform(0.0, 1.5))  # jittered backoff
            continue
        break
    return {
        "_synthesis_error": last_err or "unknown",
        "_note": "per-sub-skill LLM synthesis unavailable after retries; the deterministic verdict is unaffected.",
    }


def _load_sub_skill_synthesis_fn(skill_dir_name: str) -> Any:
    """Return a sub-skill's OPTIONAL `_llm_synthesis(cards, fired, verdict_pair, target, indication,
    model_id=None, subtype=None) -> dict`, or None.

    The uniform opt-in a sub-skill uses to hand the COMPOSED target-profile fan-out its OWN single-lens
    LLM narration — the same provenance-tagged block its standalone `--synthesize` run attaches at
    decision['llm_synthesis'], reasoned over the SAME evidence through the SAME lens synthesizer.
    Mirrors `_load_sub_skill_facet_fn` exactly (reads the prewarmed module cache, so a sub-skill
    without the hook pays no cost). Only the six narrator-bearing sub-skills (tumor-presence,
    functional-requirement, tumor-selectivity, genomic-alteration-profile, tractability-small-molecule,
    surface-modality-fit) supply it. VERDICT-INERT + best-effort: the narration is a Bedrock call
    attached AFTER the deterministic verdict, structurally unable to touch fired / the resolver /
    the nomination spine; it runs ONLY when the composed run is invoked with --synthesize-subskills."""
    module = _SUBSKILL_MODULE_CACHE.get(skill_dir_name)
    if module is None:
        _load_sub_skill_verdict_fn(skill_dir_name)  # populate the module cache
        module = _SUBSKILL_MODULE_CACHE.get(skill_dir_name)
    return getattr(module, "_llm_synthesis", None) if module is not None else None


def _prewarm_sub_skill_imports() -> None:
    """Perf byte-stability guard: single-threaded, BEFORE the thread pool, trigger every
    import the concurrent workers would otherwise race on — the compose-dashboard dispatcher (via
    resolve_cards' _import_dispatcher) and each sub-skill's verdict module (which does sys.path.insert
    + importlib.exec_module). After this, the workers hit warm module caches; no concurrent
    sys.path mutation / module exec. Idempotent + best-effort (a load failure surfaces later on the
    real call, exactly as serial)."""
    try:
        from _skills_common import resolve_cards as _rc  # noqa: F401 — triggers _import_dispatcher
    except Exception:  # noqa: BLE001
        pass
    for skill_dir, _short in SUB_SKILLS:
        try:
            _load_sub_skill_verdict_fn(skill_dir)  # populates _SUBSKILL_FN_CACHE
        except Exception:  # noqa: BLE001
            pass


# The wired question-answering skills to compose. Order matches phase A→K.
# RESTRUCTURED 2026-07-14 (scope deep-dive):
#   - tractability-and-modality SPLIT → tractability-small-molecule (SM
#     chemical-genetic verdict) + surface-modality-fit (biologics-modality call
#     the old skill only displayed).
#   - mutation-profile REFRAMED → genomic-alteration-profile (SNV + copy-number
#     + fusion [LIVE, additive signal-only]).
#   - patient-population-and-access DELETED (thin re-projection of the
#     mutation-hotspot-frequency card; its prevalence fields folded into
#     genomic-alteration-profile).
#   - surfaceome-cohort-ranking DROPPED from the fan-out (per-indication scan,
#     not a per-target question-skill; its cohort_rank_class is now covered
#     inside surface-modality-fit). The scan skill still exists as a utility.
SUB_SKILLS = [
    ("tumor-presence", "expression"),
    ("tumor-selectivity", "selectivity"),
    ("functional-requirement", "dependency"),
    ("mechanism-and-pharmacology", "mechanism"),
    ("genomic-alteration-profile", "genomic_alteration"),  # reframed from mutation-profile
    ("differentiation-landscape", "differentiation"),
    ("tractability-small-molecule", "tractability_sm"),  # split (SM half)
    ("surface-modality-fit", "surface_modality"),  # split (biologics half)
    ("immune-context", "immune_context"),  # TCE EFFECTOR axis (new fan-out member 2026-08-20):
    # "is the indication immune-hot — CD8 effectors to redirect?",
    # the orthogonal companion to surface-modality-fit's antigen side.
    # Verdict-bearing but GATELESS/ADDITIVE like combinatorial-
    # dependency (inline _verdict, NO shared resolver → absent from
    # _SHORT_TO_GATE): contributes sub_verdict + claim_vector (CD8-
    # fraction atom) to the LLM synthesis, NEVER the nomination spine
    # (recommendation byte-stable). Indication-level / target-independent
    # v1 — kept off the gate pending calibration.
    ("on-target-safety-liability", "safety"),
    ("target-intrinsic", "target_intrinsic"),  # GATELESS descriptive PEER (2026-08-17): the
    # indication-INDEPENDENT target biology dossier composed as a
    # first-class fan-out input (not a side-channel), so the
    # cross-evidence integrator (LLM synthesis) + sub_verdicts render
    # see it. DESCRIPTIVE: target-intrinsic/run.py has synthesis:none
    # → NO _verdict/_snapshot → verdict_fn is None → verdict=None; and
    # it is DELIBERATELY absent from _SHORT_TO_GATE → gate=None. So its
    # CompositionResult primary is None → it contributes ONLY to
    # sub_verdicts + the LLM synthesis context, NEVER the recommendation
    # gate/positive-tier/deciding-axis. This is the framework's FIRST
    # verdict=None gateless short (`expression`/`combinatorial_dependency`
    # are gateless but DO emit a verdict); the must-not-gate requirement
    # is satisfied STRUCTURALLY (verdict=None + gate=None), so
    # overall_recommendation + confidence stay byte-identical.
    ("cis-feature-coherence", "cis_coherence"),  # GATELESS coherence facet (2026-08-20): the
    # locus->expression->dependency coherence owner. ADDITIVE like
    # combinatorial-dependency — DEDICATED axis cis_coherence, self-
    # contained resolver verdict, DELIBERATELY absent from _SHORT_TO_GATE
    # → surfaced in sub_verdicts + the LLM synthesis but NEVER drives the
    # nomination spine (recommendation byte-stable). It DISTINGUISHES an
    # amplification-driven cis-driver from a passenger / an expressed-but-
    # inert target / a trans-driven dependency — a cross-axis integrator
    # over its own new leg + reused expression-dependency + amp-expr cards.
    # GRADUATED (gate v1.6.0, 2026-08-20): cis_coherence is now a
    # CONFIDENCE-tier axis in nomination_verdict_gate.yaml — positive_signal
    # (coherent_cis_driver, supportive), positive_contradiction
    # (expressed_cis_coupled_inert, blocks `strong`), correlated_dimension
    # group [genomic_alteration, cis_coherence]. It is VERDICT-INERT for
    # overall_recommendation ONLY (no `gates` action → can NEVER cross the
    # kill boundary) — it moves CONFIDENCE, not Go/No-Go. It is DELIBERATELY
    # kept OUT of _SHORT_TO_GATE (that map == the kill/hold gating axes,
    # ROLE_GATING + polarity scored) so it stays role=inert / not_scored; its
    # flip-stability is scanned via _CONFIDENCE_AXIS_TO_GATE (feeds
    # target_index only, never recommendation_fragility_index/contested).
    ("combination-and-vulnerability", "combination_vulnerability"),  # CONSOLIDATED relational (gene×gene) annex
    # (skill wired 2026-08-20). Canonical axis
    # combination_vulnerability (target_profiling_axes.yaml). GATELESS
    # verdict=None like target-intrinsic — its payload is a RANKED
    # PARTNER TABLE + a relational claim_vector (SL/CODEP/COMBO/RESISTANCE
    # with target_pair partner atoms), NOT a scalar. DELIBERATELY absent
    # from _SHORT_TO_GATE → contributes ONLY to sub_verdicts + the LLM
    # synthesis, NEVER the nomination spine (recommendation byte-stable;
    # verdict=None + gate=None satisfies must-not-gate STRUCTURALLY). The
    # three standalone source skills stay wired in this stage (their cards
    # are composed under both entries — like copy-number-distribution);
    # retiring them is the spine-gated follow-on.
    ("translational-readiness", "translational_readiness"),  # GATELESS descriptive PEER (wired 2026-08-31),
    # EXACT target-intrinsic precedent. translational-readiness/run.py
    # passes verdict_fn=None (DESCRIPTIVE — model availability / PDX /
    # organoid context informs confidence, not a nomination gate), so
    # verdict_fn is None → verdict=None; and it is DELIBERATELY absent
    # from _SHORT_TO_GATE → gate=None. So verdict=None + gate=None
    # satisfies the must-not-gate requirement STRUCTURALLY, exactly like
    # target-intrinsic → overall_recommendation + confidence stay
    # byte-identical (only a new descriptive sub_verdict=None row appears).
    # 3 of its 4 cards (target-model-availability, target-genotype-
    # matched-model, target-pdx-drug-response) reach the composed profile
    # via NO other path; organoid-crispr-dependency already reaches it via
    # functional-requirement, so it is NOT re-listed here (would double-
    # read — same discipline as target-intrinsic's 12 elsewhere-HOME'd
    # cards). Needs AWS_PROFILE=cbg for HCMI/PDXE S3 reads (already
    # required for the DEFAULT-ON --ground substrate chain).
    ("literature-context", "literature_context"),  # GATELESS descriptive PEER (wired 2026-09-02),
    # EXACT target-intrinsic / translational-readiness precedent.
    # literature-context/run.py passes verdict_fn=None (DESCRIPTIVE —
    # cited-literature co-occurrence + relation direction is CONTEXT/
    # CONFIDENCE, never a nomination gate; RISK_ASSESSMENT_INTEGRATION.md
    # §4), so verdict=None; and it is DELIBERATELY absent from
    # _SHORT_TO_GATE → gate=None. verdict=None + gate=None satisfies the
    # must-not-gate requirement STRUCTURALLY → overall_recommendation +
    # confidence stay byte-identical (only a new descriptive
    # sub_verdict=None row appears). Composes ONE card
    # (cited-literature-evidence) reached via NO other path — it PROMOTES
    # the former cited_literature_evidence.json tp_grounding side-channel
    # (auto_cited_evidence, now REMOVED) to a first-class fan-out input.
    # Needs AWS_PROFILE=cbg for the OT europepmc / PubTator3 S3 reads
    # (already required for the DEFAULT-ON --ground substrate chain).
]

# Composed sub-skill SHORT name → resolver GATE name (resolvers/<gate>.resolver.yaml). Used by the
# verdict-inert FRAGILITY facet to run the flip scan on each axis's own resolver. Most shorts equal
# their gate; the two exceptions are explicit here: `tractability_sm`'s resolver is
# `tractability_small_molecule`, and `expression` (tumor-presence) has NO resolver gate — presence is
# verdict-inert for the nomination spine (no rung reads it), so it is intentionally absent and the
# fragility facet treats it as flip-inapplicable, not robust. A guard test pins that every mapped gate
# has a non-empty resolver_referenced_rule_ids and that the mapping matches each sub-skill's own
# resolve_verdict_for_gate call.
_SHORT_TO_GATE = {
    "selectivity": "selectivity",
    "dependency": "dependency",
    "mechanism": "mechanism",
    "genomic_alteration": "genomic_alteration",
    "differentiation": "differentiation",
    "tractability_sm": "tractability_small_molecule",
    "surface_modality": "surface_modality",
    "safety": "safety",
}

# CONFIDENCE-tier axes that are resolver-backed and DECISION-RELEVANT (read by the positive_signal /
# positive_contradiction vocab) but are NOT gating axes — deliberately absent from _SHORT_TO_GATE, so
# they keep role=inert / polarity=not_scored and can NEVER cross the kill boundary (no `gates` action →
# they move CONFIDENCE, not overall_recommendation). The fragility facet uses this map ONLY to resolve a
# gate name for the flip scan, so their flip-stability folds into `target_index` (call-fragility) while
# it can never touch `recommendation_fragility_index` / `contested`. Keeping it separate from
# _SHORT_TO_GATE is what preserves the "8 gating shorts" invariant (skill_report ROLE_GATING mirror,
# report_render vocab, the "six gateless" count) — membership here is NOT gating membership.
_CONFIDENCE_AXIS_TO_GATE = {
    "cis_coherence": "cis_coherence",  # graduated to a confidence positive+contradiction axis at gate v1.6.0
}


def _gateless_absent_resolver(short: str, exc: RuntimeError) -> bool:
    """Should the fan-out SWALLOW `exc` (→ verdict=None) instead of aborting the composed run?

    True IFF `short` is a GATELESS axis (absent from _SHORT_TO_GATE, so it can NEVER move the
    nomination spine) AND `exc` is resolve_or_raise's specific absent-contract RuntimeError.

    Motivation: a GATELESS resolver-backed axis (cis_coherence, added 2026-08-20) crashed the WHOLE
    target-profile run with exit 1 when the target-contracts checkout predated its resolver merge —
    resolve_or_raise fired "resolver spec missing" and the fan-out re-raised it at fut.result(). Since
    the axis is verdict-inert to the spine, an ABSENT contract must degrade to verdict=None (like
    target-intrinsic / combination-vulnerability, which carry no resolver at all), not abort.

    Guarded narrowly so it never masks a real defect: verdict-BEARING gates keep fail-loud, and only
    the specific absent-contract message is swallowed — a genuine sub-skill fault carries a different
    message and still propagates. Standalone skill runs (their own run.py) are unaffected."""
    return short not in _SHORT_TO_GATE and "resolver spec missing" in str(exc)


# Card set for each sub-skill (must match SKILL.md composition.cards_used).
# RESTRUCTURED 2026-07-14 — keys track the SUB_SKILLS renames above.
SUB_SKILL_CARDS = {
    "tumor-presence": [
        # 2026-08-20 facet-parity (generalized guard): tumor-presence's _headline/_synthesis_facet reads
        # these via get_card_field, but they were DROPPED from the composer entry → _headline raised →
        # swallowed → the presence claim_vector facet was silently None in the COMPOSED profile.
        # Presence is NOT in _SHORT_TO_GATE (verdict-inert to the nomination spine), so composing them is
        # byte-stable on the verdict; it restores the presence claim_vector to the composed panel.
        "cellline-rna-distribution-by-subtype",
        "normal-tissue-liability",
        "rna-protein-concordance-tumor",
        "sc-normal-celltype-expression",
        "cellline-rna-distribution",
        "tumor-rna-vs-adjacent",
        "tumor-protein-abundance-cptac",
        "cellline-protein-abundance",  # Gygi cell-line MS — cell_line_protein_abundance axis.
        # Added to tumor-presence/run.py CARDS in an earlier PR but never
        # to this composer map → dropped from the composed profile.
        # Restored so the dual RNA+protein presence reaches the LLM.
        "cellline-protein-abundance-procan",  # ProCan-DepMapSanger DIA/SWATH — 2nd, orthogonal cell-line
        # MS platform of the SAME cell_line_protein_abundance claim.
        # DISPLAY-ONLY / verdict-inert (fires no rule); composed here so
        # the ProCan corroboration reaches the composed profile alongside
        # the Gygi sibling (composer-consistency guard: CARDS + this map
        # in lockstep).
        "tumor-elevation-breadth",  # pan-cancer K-of-N breadth — same drift class:
        # added to tumor-presence CARDS but not this map, so it was
        # silently dropped from the composed profile. Restored.
        "tumor-rna-distribution",  # Q1 (expression-extraction plan) — per-sample tumor RNA
        # distribution; added to tumor-presence CARDS + this composer
        # map together (composer-consistency guard).
        "tumor-rna-distribution-by-subtype",  # target_subtype-grain sibling — per-molecular-subtype
        # panorama (per_subgroup_metrics). Same pairing rule: wired into
        # tumor-presence CARDS + this composer map together.
        "tumor-protein-distribution-by-subtype",  # CPTAC-protein analogue of the RNA-by-subtype sibling
        # (per_subgroup_metrics, MSI_H/MSS). DISPLAY-ONLY / verdict-inert;
        # composed here (also feeds tp_evidence_package _SUBTYPE_STRAT_CARDS)
        # so the protein subtype panorama reaches the composed profile —
        # added to tumor-presence CARDS + this composer map together.
        "expression-purity-confound",  # Q9 (2026-07-23) — purity-confound caveat; render facet.
        # phospho-pathway-activity RE-HOMED 2026-08-05 → the mechanism-and-pharmacology entry below
        # (activity/signaling-state, not presence). Kept in lockstep with its sub-skill CARDS.
        "cellline-rna-protein-concordance",  # Q5 (2026-07-23) — rna_as_biomarker; biomarker preferred_assay input.
        "tumor-scrna-celltype-expression",  # composer-registry sweep (2026-08-07): single-cell
        # per-compartment tumor presence. In tumor-presence
        # CARDS (and surface-modality-fit CARDS) but composed under NO
        # entry → silently dropped. Composed here under its presence home
        # (also satisfies the surface-modality-fit CARDS listing).
        "hpa-pathology-cancer-ihc",  # MS-INDEPENDENT antibody IHC protein-in-tumor (protein_ihc/tumor
        # bucket). Added to tumor-presence CARDS + this composer map together
        # (composer-consistency guard); DISPLAY-ONLY / verdict-inert.
    ],
    "tumor-selectivity": [
        "tumor-vs-normal-selectivity",
        "tumor-vs-normal-percentile-crossing",  # Q2 — paired with tumor-selectivity CARDS (composer-consistency)
        "modality-therapeutic-window",  # (2026-08-08): the normal-breadth veto rule
        # (tvn-no-therapeutic-window-veto) keys on THIS card. It was
        # composed only under the surface-modality-fit lens, so in the
        # composed target-profile the veto NEVER fired in the selectivity
        # lens's `fired` set (card_id_filter=SUB_SKILL_CARDS) → a
        # broadly-normal housekeeping gene nominated as strong_tumor_selective
        # (the FP the redesign exists to kill, resurrected in Go/No-Go).
        # Adding it here makes the veto fire identically standalone vs
        # composed. (A card may be composed under >1 lens.)
        "sc-normal-celltype-expression",  # composer-consistency: the sc-normal critical-organ
        # veto (tvn-sc-normal-critical-organ-veto) must fire in the
        # COMPOSED selectivity lens too, else the axis-D downgrade is
        # lost in Go/No-Go (same class as the earlier deferred gap).
        "expression-purity-confound",  # composer-consistency with the standalone CARDS
        # (verdict-inert facet; feeds no selectivity resolver rung).
        "surface-abundance-density",  # composer-consistency: the absolute-density facet
        # (verdict-inert; feeds no resolver rung). Surfaces Tier-1
        # copies/cell + modality-floor standing in the composed profile.
        "normal-tissue-protein-abundance-tphp",  # composer-consistency: the QUANTITATIVE normal-tissue PROTEIN
        # comparator (TPHP DIA-MS; verdict-inert, feeds no resolver rung).
        # Surfaces the normal-PROTEIN breadth/abundance facet in the
        # composed selectivity lens too. Multi-parity list #2 (SUB_SKILL_
        # CARDS) — mirrored in DIMENSION_CARDS[selectivity] (#3).
        "tumor-vs-normal-protein-abundance-tphp",  # composer-consistency: the TPHP DIA-MS RNA→PROTEIN tumor-vs-
        # normal corroboration facet (verdict-inert, feeds no resolver
        # rung), PARALLEL to tumor-protein-abundance-cptac. Multi-parity
        # list #2 (SUB_SKILL_CARDS) — mirrored in DIMENSION_CARDS[selectivity]
        # (#3). (NB: the CPTAC sibling is NOT here — it is the certainty
        # corroboration card, consumed via the certainty model, not composed.)
        # v1.9.0 (2026-08-17) SINGLE-CELL + SPATIAL — composer-consistency with the standalone CARDS.
        # All verdict-inert (feed no resolver rung); composed here so the malignant-vs-stroma + in-situ
        # spatial evidence also surfaces in the COMPOSED target-profile selectivity lens (not only
        # standalone). tumor-scrna-celltype-expression is multi-homed (also under tumor-presence, which
        # keys the sc_rna/tumor presence bucket) — a card may compose under >1 lens (cf. modality-
        # therapeutic-window above). spatial-* are composed NOWHERE else, so this is their only home.
        "tumor-scrna-celltype-expression",  # malignant-cell-intrinsic vs stroma/CAF (purity confound, measured)
        "spatial-region-rna-expression",  # in-situ tumour-vs-TME RNA enrichment
        "spatial-tumor-normal-colocalization",  # in-situ normal-epithelium bystander adjacency
        "spatial-surface-protein-abundance",  # in-situ protein enrichment (abstains where GeoMx sparse)
    ],
    "functional-requirement": [
        "pan-cancer-crispr-dependency-distribution",
        "pan-cancer-rnai-dependency-distribution",
        "crispr-rnai-dependency-concordance",
        "prism-crispr-concordance",  # 2026-07-24 BUGFIX (found by the resolver-dependency
        # guard) — the dependency resolver's
        # `chemical_genetic_confirmed_dependent` rung fires on
        # e7-triangulated-target-engaged-supportive, which keys
        # on prism-crispr-concordance. It was composed ONLY under
        # tractability-small-molecule, so the Gate-C chemical-
        # genetic dependency CONFIRMATION could never fire in the
        # composed profile. Cross-gate card (C confirm + E1
        # compound-found), like prism-crispr-concordance's dual
        # role in the resolver comment. (Also in tractability-sm.)
        "dependency-lineage-selectivity",
        "paralog-buffering",
        "expression-dependency-correlation",  # Gate-C biomarker facet (2026-07-22). Was ORPHANED:
        # in the render maps (CARD_TITLE/CARD_ROLE/reports_into)
        # + a live dispatcher, but composed by NO sub-skill, so
        # correlation_class never computed → rendered empty.
        # Render-only facet (verdict-inert: its rules feed no
        # resolver). Also in functional-requirement/run.py CARDS.
        "recommended-models",  # Q4 patient↔model correspondence (2026-07-22) — model-
        # backed-dependency corroboration; paired with
        # functional-requirement CARDS (composer-consistency).
        "organoid-crispr-dependency",  # Organoid-native Chronos facet (2026-08-18) — corroborating
        # dependency read in patient-derived 3D organoids. Paired
        # with functional-requirement CARDS (composer-consistency).
        # ADDITIVE render-only facet (verdict-inert: its supportive/
        # neutral rules feed NO resolver ladder).
        "abundance-dependency",  # Q7 (2026-07-23) — protein abundance→dependency (protein
        # arm of expression-as-biomarker-of-dependency); render facet.
        "partner-conditional-dependency",  # 2026-08-10: verdict-bearing card.
        # In functional-requirement/run.py CARDS but DROPPED here, so
        # the dependency resolver's partner_conditional_dependent rung
        # (partner-conditional-{strongly,moderately}-dependent-supportive)
        # was DEAD in the composed profile — a partner-conditional SL
        # target (WRN×MSI) was force-vetoed non_dependent. The composer
        # guard (test_resolver_dependency_cards_are_in_the_composer_entry)
        # was sitting RED on exactly this. Restored.
        "cross-consortium-dependency",  # 2026-08-11 Project Score
        # cross-consortium dependency corroboration. In
        # functional-requirement CARDS but composed under no
        # entry → dropped from the composed profile. VERDICT-INERT
        # (no interpretation rules → feeds no resolver rung), so
        # composing it is byte-stable on the verdict spine; it only
        # restores the render facet to the composed target-profile.
        "coessential-module",  # 2026-08-19 (enrichment review): co-essential-module
        # CONFIDENCE facet (is the dependency embedded in a coherent
        # module?). In functional-requirement CARDS; composed here so
        # it is not dropped from the profile. VERDICT-INERT (no
        # resolver rung; folds into dependency_confidence_note) →
        # byte-stable on the verdict spine.
        "dependency-predictability",  # 2026-08-20 (facet-parity): in functional-requirement
        # CARDS + read by _headline (predictability_class →
        # DEP corroboration bump) but DROPPED here, so
        # _synthesis_facet's _headline raised KeyError →
        # swallowed → the dependency claim_vector facet
        # AND synthesis.claim_vectors were silently None in the
        # COMPOSED profile. VERDICT-INERT (CONFIDENCE annotation;
        # no resolver rung) → byte-stable on the verdict spine.
        "genomic-event-model-match",  # 2026-08-20 (facet-parity): same class — read by
        # _headline (event_correspondence_class biomarker render
        # facet), in functional-requirement CARDS, dropped here.
        # VERDICT-INERT (render facet; no resolver rung).
    ],
    "immune-context": [
        "immune-context",  # CIBERSORT LM22 CD8 effector context (gdc-pancanatlas-immune-2018)
        # VERDICT-INERT TME/immune display cards (wired 2026-08-25): composed for facet-parity so the
        # TME composition + ICI-response context reach the composed profile. immune-context is gateless
        # (absent from _SHORT_TO_GATE) — byte-stable on the nomination spine. Kept in lockstep with the
        # immune-context run.py CARDS + DIMENSION_CARDS[immune_context] (test_dimension_cards_matches_spine).
        "myeloid-compartment-expression-cheng",
        "caf-compartment-expression-luo",
        "ici-response-association",
        "tcga-til-fraction-saltz",  # absolute H&E-DL TIL corroborator (Saltz 2018); verdict-inert
        "ici-response-imvigor210",  # urothelial ICI-response + phenotype (IMvigor210); verdict-inert
        "spatial-tumor-normal-colocalization",  # T0-4: spatial inflamed/excluded resolution of the CD8 call; verdict-inert
    ],
    "combination-and-vulnerability": [  # CONSOLIDATED relational annex (wired 2026-08-20).
        "synthetic-lethal-partners",  # curated SynLethDB SL (summary → synthetic_lethal_summary atom)
        "combinatorial-dependency",  # measured paralog dual-KO GI (CODEP axis; target_pair atoms)
        "cross-consortium-paralog-gi",  # T0-1: Dede/in4mer orthogonal corroboration of the CODEP call (verdict-inert)
        "combo-crispr-screen",  # combination co-targets under inhibition (COMBO axis)
        "combo-chemical-synergy",  # chemical drug×drug synergy (SYNERGY axis; Sanger 2022 Bliss)
        "resistance-emergence-signature",  # resistance mediators that rescue (RESISTANCE liability axis)
        # These FIVE source cards are composed ONLY here (each appears exactly
        # once in the composer — NOT multi-homed; unlike copy-number-distribution
        # which genuinely composes under >1 lens). The standalone SL /
        # combinatorial-dependency / combo-crispr source SKILLS are separate skill
        # dirs, NOT fan-out members — there are no "standalone entries above".
        # Matches the skill's SKILL.md cards_used. GATELESS → the relational
        # claim_vector axes read these; byte-stable on the spine.
    ],
    "cis-feature-coherence": [
        "cis-feature-expression-coherence",  # GoF leg-1: CN -> own-expression cis-dosage (amplification, mRNA)
        "cis-feature-protein-coherence",  # GoF leg-1 (PROTEIN): CN -> own-protein cis-dosage; slope RATIO vs
        # mRNA leg = dosage-buffering fingerprint. VERDICT-INERT (fires no rule).
        "cellline-methylation-expression-coherence",  # LoF leg-1: promoter methylation -> own LOW expression (silencing)
        "expression-dependency-correlation",  # leg-2 (reused; also composed under functional-requirement)
        "abundance-dependency",  # leg-2 (PROTEIN, reused from the dependency axis); VERDICT-INERT here
        "amp-expr-stratified-dependency",  # leg-2 (reused; also composed under genomic-alteration-profile)
        "patient-cis-coherence",  # VERDICT-INERT patient (TCGA) corroboration facet (fires no rule)
        # Matches cis-feature-coherence SKILL.md cards_used. The two leg-2
        # cards are HOME cards of other sub-skills; composing them here too
        # is byte-stable (same cards, different lens) — the cis_coherence
        # axis rules fire on their fields via card_id_filter.
        "cellline-isoform-expression",  # molecular-form facet (verdict-inert display)
    ],
    "mechanism-and-pharmacology": [
        "signaling-network-mechanism",
        "phospho-pathway-activity",  # RE-HOMED 2026-08-05 from tumor-presence — phospho ACTIVITY /
        # signaling-state facet (CPTAC phosphoproteomics). Render facet.
        "pathway-activity-context",  # 2026-08-11 PROGENy pathway-activity
        # context. In mechanism-and-pharmacology CARDS, composed under no
        # entry → dropped. VERDICT-INERT render facet (no rules).
        "tahoe-drug-perturbation",  # 2026-08-11 Tahoe MoA/PD-marker
        # perturbation facet. In mechanism-and-pharmacology CARDS,
        # composed under no entry → dropped. VERDICT-INERT render facet.
        "dependency-predictability",  # 2026-08-20 facet-parity: mechanism's _headline reads this via
        # _predictability_mechanism_facet (SIGNOR cross-ref), but it was
        # DROPPED from the composer entry → once mechanism exposes a
        # _synthesis_facet (claim-vector rollout) the facet would raise →
        # swallowed → mechanism claim_vector silently None in the COMPOSED
        # profile. Feeds NO mechanism resolver rung (verdict byte-stable);
        # composing it restores the PREDICTABILITY axis + the SIGNOR x-ref.
        # (ALSO composed under genomic-alteration-profile — dual home.)
        "driver-pathway-position",  # (SK#2314 P1, 2026-10-01) target+indication-conditioned POSITIONAL
        # read vs the indication's frequently-altered driver pathway. SOFT / VERDICT-INERT (no mechanism
        # resolver rung — verdict byte-stable). HOMED here; ALSO composed under genomic-alteration-profile (dual home).
    ],
    "genomic-alteration-profile": [  # reframed from mutation-profile
        # 2026-08-20 facet-parity (generalized guard): genomic's _build_headline lifts these two
        # (dependency CONFIDENCE cards) via _lift_field (declarative _HEADLINE_FIELDS), but they were
        # DROPPED from the composer entry → _synthesis_facet raised KeyError → swallowed → the genomic
        # claim_vector was silently None in the COMPOSED profile. Dependency-confidence cards feed NO
        # genomic resolver rung → verdict byte-stable; composing them restores the genomic claim_vector.
        "cross-consortium-dependency",
        "dependency-predictability",
        "tumor-splice-dysregulation",  # splice-form facet (verdict-inert display; tumor-splice-expression dedup'd 2026-09-06)
        "mutation-type-counts",
        "mutation-stratified-dependency",
        "mutation-hotspot-frequency",
        "copy-number-distribution",  # CN axis wired 2026-07-14
        "copy-number-stratified-dependency",  # (2026-08-06): amp×dependency rescue (fires
        # biomarker_stratified_dependency); composer-consistency
        "fusion-stratified-dependency",  # (2026-08-06): fusion×dependency rescue (fires
        # biomarker_stratified_dependency; EWSR1-FLI1/BCR-ABL1);
        # composer-consistency with genomic-alteration-profile CARDS
        "amp-expr-stratified-dependency",  # amp-expr (2026-08-06): conjoint amp+overexpr×dependency
        # rescue (fires biomarker_stratified_dependency; ERBB2/MYC/
        # KRAS-amp); composer-consistency with genomic CARDS
        "mutation-drug-response",  # (2026-08-09): genotype×PRISM drug-response;
        # its mutation-drug-response-strongly-sensitive-supportive rung
        # fires the DISTINCT drug_response_biomarker verdict. Composed
        # here so that rung can fire in the target-profile (else the
        # verdict was dead-in-composition — the composer guard caught it).
        "fusion-rearrangement-landscape",  # LIVE (tcga-fusion-consensus-v1); additive signal-only
        "splice-exon-skip-landscape",  # CASE-002: curated exon-skip DRIVER (METex14) → splice_exon_skip_driver
        # rung; composer-consistency with genomic-alteration-profile CARDS
        "alteration-role",  # typed driver-role (OncoKB×IntOGen), 2026-07-22 —
        # paired with genomic-alteration-profile CARDS (composer-consistency)
        "functional-gene-state",  # allele-count / biallelic two-hit state (2026-07-22) —
        # composer-consistency with genomic-alteration-profile CARDS.
        "genomic-event-model-match",  # canonical patient↔model genomic-event join
        # (2026-07-22) — composer-consistency.
        "genomic-instability-state",  # composer-registry sweep (2026-08-07): aneuploidy/WGD/MSI/
        # signature genome-state axis. In genomic-alteration-profile
        # CARDS but composed under no entry → dropped. Restored.
        "variant-level-interpretation",  # composer-registry sweep (2026-08-07): per-variant
        # oncogenicity (CIViC + hotspot). Same drift — in CARDS,
        # not composed → dropped. Restored.
        "variant-effect-mave-mavedb",  # MAVEdb MEASURED multiplexed variant-effect (DMS/SGE)
        # facet — in genomic-alteration-profile CARDS; composed here for
        # composer-consistency. VERDICT-INERT (no rules; verdict byte-stable).
        "ddr-deficiency-context",  # 2026-08-11 DDR/HRD inert context
        # facet. In genomic-alteration-profile CARDS, composed under
        # no entry → dropped. VERDICT-INERT render facet (no rules).
        "mutational-signature-context",  # 2026-08-12: per-indication mutagenic-process cohort facet
        # (TCGA MC3 SBS). In genomic-alteration-profile CARDS →
        # composer-consistency requires it here. VERDICT-INERT (no rules).
        "oncogenic-pathway-alteration",  # 2026-08-11 oncogenic-pathway
        # alteration context. In genomic-alteration-profile CARDS,
        # composed under no entry → dropped. VERDICT-INERT render facet.
        "driver-pathway-position",  # (SK#2314 P1, 2026-10-01) target+indication-conditioned POSITIONAL read
        # vs the frequently-altered driver pathway, surfaced alongside oncogenic-pathway-alteration. SOFT /
        # VERDICT-INERT (no genomic rung → verdict byte-stable). HOMED in mechanism-and-pharmacology (dual home).
        "target-clonality",  # scientific-gap (2026-08-14): mutation clonality/truncality
        # (ccf). In genomic-alteration-profile CARDS →
        # composer-consistency requires it here. VERDICT-INERT (no rules).
    ],
    "differentiation-landscape": [
        "co-mutation-and-mutual-exclusivity",
        "clinical-precedent",  # (2026-08-21) AACT trial precedent — in differentiation-landscape
        # CARDS; composed here so the fanout does not silently drop it.
        # VERDICT-INERT render facet (no resolver rung; nomination byte-stable).
        "competitor-landscape",  # (2026-08-24) Open Targets competitor field — in differentiation-
        # landscape CARDS; composed here so the fanout does not silently drop
        # it. VERDICT-INERT render facet (no resolver rung; nomination
        # byte-stable). Its modality_landscape feeds the deterministic
        # competitor cross-ref (competitor_crossref) injected into synthesis.
        "expression-clinical-association",  # Q11 (2026-07-23) — expression→survival prognostic context;
        # render facet, paired with differentiation-landscape CARDS.
        "stemness-context",  # 2026-08-11 Malta 2018 mRNAsi
        # stemness context. In differentiation-landscape CARDS,
        # composed under no entry → dropped. VERDICT-INERT render facet.
        "precog-prognostic-association",  # 2026-08-11 PRECOG prognostic
        # meta-Z corroboration. In differentiation-landscape CARDS,
        # composed under no entry → dropped. VERDICT-INERT render facet.
        "pathway-node-leverage",  # (2026-08-17): COMPARATIVE node-leverage. In
        # differentiation-landscape CARDS; composed here so the fanout
        # does not silently drop it. VERDICT-INERT (soft axis_fit signals
        # + fired_rule_ids for the hypothesis agent; feeds NO resolver →
        # nomination byte-stable, axis_fit is not gate-consumed).
        "alteration-clinical-association",  # Q11-alteration (2026-08-20): OS by {target} mutation status.
        # In differentiation-landscape CARDS; composed here so the fanout
        # does not drop it. VERDICT-INERT (alteration-* rules feed NO resolver).
        "subtype-survival-association",  # Q2-subtype (2026-08-20): OS across molecular subtypes (target-
        # independent context). VERDICT-INERT (subtype-* rules feed NO resolver).
        "mutational-signature-context",  # (#1815 / #954): patient-selection render facet of the co-mutation
        # landscape (TCGA MC3 mutational processes). In differentiation-landscape/run.py CARDS; composed
        # here so the fanout does not silently drop it. VERDICT-INERT render facet (no resolver rung).
        "oncogenic-pathway-alteration",  # (#1816 / #954): orthogonal genomic pathway-alteration-frequency
        # lens complementing the dependency-only node-leverage read. In differentiation-landscape/run.py
        # CARDS; composed here so the fanout does not silently drop it. VERDICT-INERT render facet.
    ],
    "tractability-small-molecule": [  # split: SM chemical-genetic half
        "prism-compound-activity",
        "prism-crispr-concordance",
        "measured-potency-tractability",  # 2026-08-10: measured-potency card.
        # In tractability-small-molecule/run.py CARDS but DROPPED here,
        # so the tractability_small_molecule resolver's measured_potent_ligand
        # AND structurally_ligandable rungs (measured-potent-ligand-sm-supportive
        # + measured-weak-ligand-sm-supportive) were unreachable in the
        # composed profile. Was invisible to the composer guard until the
        # 2026-08-10 _GATE_BY_SUBSKILL fix added this gate. Restored.
        "dependency-predictability",
        "structure-features-static",  # 2026-07-24 — forward-ligandability (pocket/druggability).
        # In tractability-small-molecule/run.py CARDS but was dropped
        # from this composer entry (composed only under surface-
        # modality-fit, a DIFFERENT sub-skill), so the SM ligandability
        # signal never reached the composed tractability sub-verdict.
        # Cross-gate card (SM pocket + surface epitope), needed in BOTH.
        "degradation-feasibility",  # composer-registry sweep (2026-08-07): the degrader-lens E3
        # slice (E3-substrate + PROTAC precedent + location gate). In
        # tractability-small-molecule CARDS (feeds the degrader lens)
        # but composed under no entry → dropped. Restored so the
        # degradability signal reaches the composed profile.
        "known-drug-tractability",  # composer-registry sweep (2026-08-08): DGIdb pharmacology leg
        # (E-known-drug) wired into tractability-small-molecule CARDS
        # but composed under no entry → dropped. The card already
        # feeds the skill's own verdict (run.py:198); this restores it to
        # the composed target-profile so the known-drug signal reaches it.
        "gdsc-drug-activity",  # 2026-08-25: Sanger GDSC1/2 2nd drug-response platform, ORTHOGONAL
        # corroboration of PRISM. In tractability-small-molecule/run.py CARDS;
        # composed here for composer-consistency + DIMENSION_CARDS parity.
        # VERDICT-INERT (fires no rule, no resolver rung) — the composed
        # tractability sub-verdict is byte-stable with or without it.
        "mutation-hotspot-frequency",  # #993 pt1: the indication's mutant-allele spectrum, read ONLY by
        # the verdict-INERT minority_allele_coverage_caveat. In tractability-small-molecule/run.py CARDS;
        # composed here for composer-consistency (facet claim_vector). Fires no rule, no resolver rung.
    ],
    "surface-modality-fit": [  # split: biologics-modality half
        "surface-topology-and-ptm",
        "surfaceome-family-classification",
        "structure-features-static",
        "surface-abundance-density",
        "adc-tce-modality-fit",
        "normal-tissue-liability",  # HPA IHC off-tumor safety — in surface-modality-fit CARDS
        # (composer-consistency; was run.py-present but here-absent)
        "copy-number-distribution",  # (2026-07-23): genomic amplification → surface antigen-
        # density (adc/bite_tce/antibody). Cross-cutting — ALSO in
        # genomic-alteration-profile (SM/degrader): one
        # card, two modality gates, divergent modality reads.
        "rna-protein-concordance-tumor",  # orphan-fix (2026-08-05): tier:indication RNA↔protein
        # concordance; its important-weighted ADC/TCE surface rules
        # were unreachable until surface-modality-fit composed it.
        # composer-registry sweep (2026-08-07): four surface/biologics cards in surface-modality-fit
        # CARDS but composed under no entry → silently dropped from the composed profile. Restored.
        "protein-surface-evidence",  # measured surface-localization evidence (CSPA/HPA).
        "shed-ectodomain-liability",  # shed-antigen serum-decoy liability (ADC/TCE drug-sink).
        "modality-therapeutic-window",  # composed therapeutic-window dispatcher call.
        "pmhc-presentation",  # peptide-centric pMHC presentation (TCE/TCR-mimetic reach).
        # composer-registry sweep (2026-08-08): five more surface/biologics cards added to
        # surface-modality-fit CARDS but composed under no entry →
        # silently dropped from the composed profile. Restored (all fire additive supportive-only
        # rules; the composed surface_modality verdict stays byte-stable — narrative completeness only).
        "cd-antigen-backbone",  # CD/IO-antigen backbone clinical-precedent.
        "modality-exon-window",  # per-exon tumor-vs-normal ADC/TCE window.
        "mutation-stratified-surface",  # mutant-up surface-antigen signal.
        "pathway-stratified-surface",  # pathway-stratified surface signal.
        "sc-normal-celltype-expression",  # single-cell normal-tissue safety comparator.
        "sc-surface-normal-safety",  # REVIVE 2026-08-19: sc CITE-seq surface footprint on normal immune (additive; no resolver rung → composed verdict byte-stable).
        "sc-surface-rna-protein-concordance",  # REVIVE 2026-08-19: sc RNA↔surface-protein proxy quality (additive; no resolver rung → byte-stable).
        "surfaceome-cohort-ranking",  # REVIVE 2026-08-20: per-target cohort-percentile context (product landed 2026-08-18; additive verdict-inert facet).
        "surface-bulk-pair-selectivity",  # 2026-08-20: bulk AND/OR/NOT pair-selectivity best-partner facet (bispecific; additive verdict-inert; companion to same-cell avidity).
        "tumor-scrna-celltype-expression",  # within-tumor antigen HOMOGENEITY (tce_homogeneity_class —
        # the ADC-vs-TCE discriminator). READ in _headline, so once
        # surface-modality-fit exposes a _synthesis_facet (claim-vector
        # rollout 2026-08-20) it is REQUIRED in THIS entry: the fan-out
        # scopes each sub-skill to its OWN entry, so "composed under
        # tumor-presence" no longer suffices for the surface FACET (the
        # facet-parity guard pins this). Additive; composed surface
        # verdict byte-stable (fit_class resolves off adc-tce-modality-fit).
        "surface-colocalization-avidity",  # wired 2026-08-20: same-cell avidity + tumor-vs-NORMAL selectivity
        # window for AND-gate bispecifics. READ in _headline (samecell_* keys),
        # so REQUIRED in THIS entry (facet-parity guard: the fan-out scopes each
        # sub-skill to its own entry). Its rules are in no resolver → additive;
        # composed surface verdict byte-stable.
        "pmhc-epitope-evidence-iedb",  # 2026-08-25: IEDB experimentally-validated pMHC epitope / MHC ground truth
        # (experimental complement to pmhc-presentation's benign-atlas breadth).
        # VERDICT-INERT display card — no rule maps it, no resolver rung consumes it
        # → composed surface verdict byte-stable. In surface-modality-fit CARDS.
        "cellline-surfaceome-abundance",  # #2025: cell-line surfaceome MS abundance (additive; no rule
        # maps it, no resolver rung consumes it → composed surface verdict byte-stable). Composer-
        # consistency with surface-modality-fit's own run.py CARDS entry.
        "surface-localization-concordance",  # #2067, surfaceome 26Q3 arc #2024; target-contracts#966
        # MERGED: BRIDGE derived card cross-tabbing cellline-surfaceome-abundance's cell-line
        # surface_localization_class against protein-surface-evidence's orthogonal surface_confirmation_
        # class. interpretation: rules_pending — additive; no rule/resolver rung consumes it → composed
        # surface verdict byte-stable. Composer-consistency with surface-modality-fit's own run.py CARDS.
    ],
    "on-target-safety-liability": [
        "gnomad-lof-constraint",
        "shet-lof-intolerance",  # 2026-08-28 — continuous GeneBayes s_het (VERDICT-INERT complement
        # to gnomAD constraint); added to CARDS + this map together.
        "alteration-role",  # 2026-07-24 BUGFIX — REQUIRED for the mutant-selective safety
        # downgrade to fire IN COMPOSITION. The fan-out scopes each
        # sub-skill to ITS OWN SUB_SKILL_CARDS entry (card_id_filter),
        # so alteration-role being composed under genomic-alteration-
        # profile did NOT make it available to the safety sub-skill.
        # safety.resolver 1.3.0's downgrade rungs are when_all_fired:
        # [<constraint/burden warning>, activating-driver-role-safety-
        # context]; that context rule keys on alteration-role. Without
        # this line, wt_constraint_mechanism_mismatch / wt_human_
        # genetics_mechanism_mismatch could NEVER fire in the composed
        # profile — a KRAS/COADREAD run wrongly HELD on WT-constraint.
        # (Also in on-target-safety-liability/run.py CARDS.)
        "normal-tissue-liability-gtex",  # Q3 — paired with on-target-safety-liability CARDS (composer-consistency)
        "target-safety-prioritisation",  # OT engineered-score safety CONTEXT (verdict-inert)
        "drug-warning-safety",  # (2026-08-21) OT pharmacovigilance CONTEXT (verdict-inert)
        "onsides-adverse-event-safety",  # (2026-08-25) OnSIDES drug-label ADE CONTEXT (verdict-inert display; per-MedDRA-term, fuzzy drug->gene join). (Also in on-target-safety-liability/run.py CARDS.)
        "gene-burden-safety",  # OT rare-variant burden LoF-tolerance (verdict-moving; safety.resolver 1.3.0)
        "clingen-dosage",  # ClinGen haploinsufficiency dosage-sensitivity (verdict-moving; safety.resolver 1.3.0)
        "mouse-ko-phenotype",  # mouse-KO normal-physiology (developmental-guardrailed; verdict-moving; safety.resolver 1.3.0)
        "clinvar-pathogenicity-safety",  # ClinVar germline-pathogenic (4th corroborating leg; verdict-moving)
        "copy-number-distribution",  # (2026-08-17) — REQUIRED for the amplification GUARD to fire IN
        # COMPOSITION (same pattern as alteration-role above). safety.resolver
        # GROUP-0's copy-number-amplified-oncogene-safety-context rung keys on
        # copy-number-distribution.patient_focal_cn_class; without this line the
        # guard could never fire in the composed profile and an amplification-
        # driven oncogene (ERBB2/MDM2) would still be wrongly DOWNGRADED off its
        # on-target-safety HOLD. (Also in on-target-safety-liability/run.py CARDS.)
        "functional-gene-state",  # (PR-4c 2026-08-24) — REQUIRED for the RARELY-ALTERED guard to fire IN
        # COMPOSITION. safety.resolver GROUP-0b keys on functional-gene-state-
        # rarely-altered-neutral; without this line an amplification/role-only
        # oncogene (MCL1) would still be wrongly downgraded off its cardiotox
        # HOLD. (Also in on-target-safety-liability/run.py CARDS.)
        "pan-cancer-crispr-dependency-distribution",  # (data-util expansion 2026-08-21) — REQUIRED for the
        # pan-essential broad-tox HOLD (pan-essential-broad-tox-safety-warning →
        # pan_essential_broad_tox_concern) to fire IN COMPOSITION. Also composed
        # under functional-requirement (dependency lens); a card may be read by
        # multiple lenses. (Also in on-target-safety-liability/run.py CARDS.)
        "normal-tissue-liability",  # (data-util expansion 2026-08-21) — REQUIRED for the HPA-IHC essential-
        # tissue protein HOLD (normal-tissue-protein-liability-safety-warning →
        # normal_tissue_protein_safety_concern) to fire IN COMPOSITION. Also
        # composed under surface-modality-fit (surface lens). (Also in run.py CARDS.)
        "normal-tissue-protein-abundance-tphp",  # (T0-3 2026-09-10) — TPHP DIA-MS quantitative vital-organ
        # PROTEIN, VERDICT-INERT safety display CONTEXT (fills nerve/muscle/blood/adrenal/thyroid HPA-IHC
        # is blind to). Also composed under tumor-selectivity (its home lens). (Also in run.py CARDS.)
    ],
    "target-intrinsic": [  # GATELESS descriptive dossier (2026-08-17). Compose ONLY the
        # target-intrinsic-EXCLUSIVE cards — the ones NOT already composed under
        # another sub-skill's lens. target-intrinsic's OTHER 12 cards
        # (gnomad-lof-constraint + the P5 safety legs → on-target-safety-liability;
        # surfaceome-family-classification + structure-features-static +
        # shed-ectodomain-liability + normal-tissue-liability → surface-modality-fit;
        # signaling-network-mechanism → mechanism-and-pharmacology; paralog-buffering →
        # functional-requirement) are DELIBERATELY not re-listed here — re-adding them
        # would double-read those cards, and the composer drop-guard/reverse-guard are
        # already satisfied because they are HOME cards of target-intrinsic composed
        # SOMEWHERE. No gate is scoped to this entry (target_intrinsic ∉ _SHORT_TO_GATE),
        # so the resolver-dependency guard does not apply — these cards fire only their
        # own descriptive/verdict-inert rules (if any) and never a nomination rung.
        "target-identity-summary",  # canonical id / family / aliases (also read standalone by the emitter for hgnc_id)
        "target-development-level",  # Pharos/IDG TDL druggability/novelty tier (Tclin/Tchem/Tbio/Tdark)
        "measured-potency-tractability",  # borrowed: ChEMBL/BindingDB measured chemical matter (tier:target); verdict-inert
        "protein-domains-class",  # UniProt FT DOMAIN architecture + keyword protein class
        "domain-modality-relevance",  # interpretive domain→modality facet (inhibitor_sufficient vs removal_required)
        "ppi-interactome",  # STRING functional network + CORUM complex membership
        "gene-ontology-annotation",  # GO BP/MF/CC term membership
        "reactome-pathway-membership",  # Reactome pathway/geneset membership + top-level rollup
    ],
    "translational-readiness": [  # GATELESS descriptive peer (wired 2026-08-31), target-intrinsic
        # precedent. Compose ONLY the translational-readiness-EXCLUSIVE cards
        # — those NOT already composed under another sub-skill's lens.
        # organoid-crispr-dependency (its 4th card) is DELIBERATELY not listed
        # here: it is a HOME card of functional-requirement and already composed
        # under that entry, so re-listing would double-read (same discipline as
        # target-intrinsic's elsewhere-HOME'd cards). The drop-guard is satisfied
        # (organoid-crispr-dependency IS composed somewhere). No gate is scoped to
        # this entry (translational_readiness ∉ _SHORT_TO_GATE), so the resolver-
        # dependency guard does not apply — these cards fire only their own
        # verdict-inert rules (if any) and never a nomination rung.
        "target-model-availability",  # per-indication HCMI patient-derived model coverage (indication-grain)
        "target-genotype-matched-model",  # does an available HCMI model carry THIS target's alteration?
        "target-pdx-drug-response",  # Novartis PDXE in-vivo drug-response (target-grain)
    ],
    "literature-context": [  # GATELESS descriptive peer (wired 2026-09-02), target-intrinsic /
        # translational-readiness precedent. Its SINGLE card is reached via NO
        # other path — it PROMOTES the former cited_literature_evidence.json
        # tp_grounding side-channel (auto_cited_evidence, now REMOVED) to a
        # first-class fan-out input. No gate is scoped to this entry
        # (literature_context ∉ _SHORT_TO_GATE), so the resolver-dependency guard
        # does not apply; the card is verdict-inert (fires no nomination rung).
        "cited-literature-evidence",  # OT europepmc co-occurrence + PubTator3 relation direction (gene×indication)
    ],
}


# --- Subtype tier (verdict-affecting, opt-in via --subtypes) ----------------
# The subtype sub-result is CONDITIONAL: it only enters sub_results when a
# subtype scope is requested. This preserves exact backward-compat — no
# --subtypes → sub_results is byte-identical to before → gate unchanged. It
# implements the design's "subtype channel terminal WHEN Scope.subtypes
# populated" as opt-in-by-scope.
SUBTYPE_SHORT = "subtype_fit"
SUBTYPE_CARDS = [
    "subgroup-stratified-dependency",  # VERDICT-BEARING in this tier: its subtype-non-dependence-
    # opposing rule is what _subtype_verdict reads → one-directional
    # negative HOLD (subtype_specific_non_dependence).
    "subgroup-stratified-mutation-frequency",  # CONTEXT-SIGNAL within this tier (2026-09-11): the rule
    # subtype-mutation-frequency-recurrent-context fires on a measured,
    # floor-cleared, recurrently_mutated stratum → subtype_fit_mutation:
    # neutral. GATE-INERT (like the expression-context rules): mutation
    # FREQUENCY is prevalence, not efficacy/requirement, so _subtype_verdict
    # (which reads only subtype_fit_genomic / subtype_fit_selectivity) never
    # maps it to a verdict. No longer "fires nothing" — it now reaches the
    # fired-signal spine (provenance / convergence measured-axis set) as
    # patient-selection context, NOT the verdict. The genomic-alteration axis
    # owns any biomarker-stratified DEPENDENCY claim.
    "tumor-vs-normal-selectivity",  # VERDICT-BEARING in this tier (2026-09-11, STAD subtype-shard wiring).
    # DUAL-GRAIN card: under subgroup_context it resolves via _dispatch_selectivity_by_subgroup
    # (read_stratified_tumor_vs_normal_selectivity) → per_subgroup_metrics. Its
    # subtype-restricted-selectivity-supportive rule fires on a MEASURED, floor-cleared (n>=30),
    # strong_tumor_selective stratum → subtype_fit_selectivity: supportive → _subtype_verdict maps it
    # to subtype_restricted_selectivity (a SUPPORTIVE positive). This is the TUMOR-TISSUE analogue of
    # the dependency rung, reaching indications whose DepMap subtype channel is data-blocked (STAD/ESCA:
    # 0 subtype-labeled DepMap lines). The card's WHOLE-COHORT selectivity_class rules key on a scalar
    # field absent from the by-subgroup envelope, so they do NOT fire here (no double-count). Its pooled
    # read stays in the `selectivity` sub-skill; this entry only adds the subtype-grain projection.
]

# Per-card SERVING COHORTS: which cohort(s) back each subtype card's panorama read. Used to filter
# each card's stratum scope to the strata the subtype_crosswalk marks as CARRIED by that cohort
# (2026-09-11, CDH3 subtype-dispatch review). WHY: the crosswalk already records, per stratum, the
# `cohorts:` that actually have members (CMS/CIMP/sidedness are cohorts:[tcga] — PATIENT-ONLY), but the
# dispatcher sent the WHOLE resolved stratum set to EVERY card. So a patient-only stratum was routed
# into the DepMap CELL-LINE dependency card, which structurally cannot serve it → an evidence_state:
# absent, subgroup_n:0 row per stratum (the n>=30 floor suppresses them, so verdict-inert, but each run
# still fanned 15 dead strata into a card that can never carry them). Filtering by the registry cohort
# keeps each stratum on the card(s) that CAN serve it — CMS drops from dependency, stays for the
# TCGA-backed selectivity card. A stratum with NO cohorts recorded is left unfiltered (graceful).
_SUBTYPE_CARD_COHORTS: dict[str, set[str]] = {
    "subgroup-stratified-dependency": {"depmap"},  # DepMap cell-line CRISPR/RNAi
    # patient mutation frequency: TCGA-MC3 + GENIE molecular shards AND the GENIE-BPC line-of-therapy shard
    "subgroup-stratified-mutation-frequency": {"tcga", "depmap", "genie", "genie_bpc"},
    "tumor-vs-normal-selectivity": {"tcga"},  # TCGA/GTEx tumor-vs-normal DESeq2 by subgroup
}


def _strata_for_card(card_id: str, subtypes: list[str], cohorts_of: dict[str, list[str]]) -> list[str]:
    """The subset of `subtypes` this card's backing cohort can serve, per the subtype_crosswalk
    `cohorts:` field (see _SUBTYPE_CARD_COHORTS). A stratum is kept when its registry cohorts intersect
    the card's serving cohorts; a stratum the registry does not enumerate (no cohorts recorded) is kept
    unfiltered so an unregistered stratum is never silently dropped. A card with no declared serving
    cohorts (defensive) keeps every stratum. Order-preserving."""
    serving = _SUBTYPE_CARD_COHORTS.get(card_id)
    if serving is None:
        return list(subtypes)
    return [s for s in subtypes if not cohorts_of.get(s) or (set(cohorts_of[s]) & serving)]


def _subtype_expression_differential(expr_result: dict | None) -> str | None:
    """SK#1624 — the LOWEST-priority subtype-tier positive: a POWERED cross-subtype expression
    DIFFERENTIAL. Returns the fired rule_id (for provenance) iff, in the `expression` sub-result,
    (1) a subtype-expression-enriched/restricted-context rule fired emitting `subtype_fit_expression:
    supportive` (target-contracts promoted these from neutral, #1624), AND (2) the tumor-rna-
    distribution-by-subtype card's rolled-up `subtype_axis_quality` is `powered`
    (is_differential_axis — >=2 strata clear the n>=30 floor). The powered gate is applied HERE, not in
    the rule's in_record, so a single-stratum `exploratory` enrichment (a hypothesis, not a real
    differential) fires the context rule but never mints the verdict. Returns None otherwise.

    Reads the `expression` sub-result (threaded in from the completed main fan-out) rather than the
    subtype tier's own SUBTYPE_CARDS: tumor-rna-distribution-by-subtype lives in the `expression`
    short, so its fired records carry `subtype_fit_expression` in their in-memory signals dict."""
    if not expr_result:
        return None
    quality = None
    for c in expr_result.get("cards") or []:
        if c.get("card_id") == "tumor-rna-distribution-by-subtype":
            quality = (c.get("summary") or {}).get("subtype_axis_quality")
            break
    if not is_differential_axis(quality):
        return None
    for f in expr_result.get("fired") or []:
        if "supportive" in ((f.get("signals") or {}).get("subtype_fit_expression") or ""):
            return f.get("rule_id")
    return None


def _subtype_verdict(fired: list[dict], expr_result: dict | None = None) -> tuple[str, str | None] | None:
    """Verdict producer for the subtype tier. BI-DIRECTIONAL, negative-precedence (2026-08-19,
    subtype-verdict-shifting review).

    NEGATIVE (unchanged, takes precedence): subtype-non-dependence-opposing matches a MEASURED,
    floor-cleared, NOT-dependent stratum -> subtype_fit_genomic: opposing ->
    `subtype_specific_non_dependence` (the nomination gate maps it to a HOLD).

    POSITIVE — DEPENDENCY (2026-08-19): subtype-restricted-dependency-supportive matches a MEASURED,
    floor-cleared, STRONG-dependent stratum -> subtype_fit_genomic: supportive ->
    `subtype_restricted_dependency` (the gate treats it as a SUPPORTIVE positive + a non_dependent
    veto-suppressor — the precision-oncology channel: POU2F3/SCLC-P, CMS4/CRC).

    POSITIVE — TUMOR-TISSUE SELECTIVITY (2026-09-11, STAD subtype-shard wiring):
    subtype-restricted-selectivity-supportive matches a MEASURED, floor-cleared, strong_tumor_selective
    per-subgroup row on tumor-vs-normal-selectivity -> subtype_fit_selectivity: supportive ->
    `subtype_restricted_selectivity` (a SUPPORTIVE positive; NOT a veto-suppressor). This is the
    tumor-tissue analogue that reaches indications whose DepMap subtype dependency channel is
    data-blocked (STAD/ESCA carry 0 subtype-labeled DepMap lines).

    POSITIVE — POWERED EXPRESSION DIFFERENTIAL (2026-09-26, SK#1624), LOWEST priority: on a `powered`
    subtype axis a subtype-expression-enriched/restricted-context rule (subtype_fit_expression:
    supportive) -> `subtype_powered_differential`. A DOMINANT patient-selection nomination signal in
    nomination_verdict_gate.yaml, but ADDITIVE here — it is minted ONLY when no opposing / dependency /
    selectivity subtype verdict was found, so it never displaces them (see _subtype_expression_differential
    for the powered gate).

    Precedence is CONSERVATIVE and RANKED: (1) any opposing subtype -> HOLD wins. Else (2) a dependency
    supportive -> subtype_restricted_dependency (the STRONGER positive: KO-proven efficacy + veto-
    suppressor). Else (3) a selectivity supportive -> subtype_restricted_selectivity. Else (4) a powered
    expression differential -> subtype_powered_differential (SK#1624, lowest — additive, never displaces).
    So a subtype with BOTH strong dependency and strong selectivity reports the dependency verdict;
    selectivity-only subtypes (the data-blocked-dependency case) get the selectivity verdict; a
    powered-expression-only subtype gets the differential verdict. Admissibility (n>=30 floor, measured)
    is enforced upstream at rule-fire time (the powered-axis gate additionally skills-side). Byte-stable:
    no --subtypes -> no subtype tier -> None; and the expression differential fires only where the
    tumor-rna subtype axis is `powered` (the ~34-package powered-differential set), so a run whose
    expression axis is not powered is byte-identical to before.
    """

    def _sig(f: dict) -> str:
        # `or ''` guards subtype_fit_genomic: null (present key, None value) -> else `'x' in None` raises.
        return (f.get("signals") or {}).get("subtype_fit_genomic") or ""

    def _sig_sel(f: dict) -> str:
        # the tumor-tissue selectivity channel (distinct from the verdict-inert subtype_fit_expression).
        return (f.get("signals") or {}).get("subtype_fit_selectivity") or ""

    subtype = [f for f in fired if f.get("tier") == "subtype"]
    opposing = [f for f in subtype if "opposing" in _sig(f)]
    if opposing:
        return ("subtype_specific_non_dependence", opposing[0].get("rule_id"))  # HOLD — precedence
    supportive = [f for f in subtype if "supportive" in _sig(f)]
    if supportive:
        return ("subtype_restricted_dependency", supportive[0].get("rule_id"))  # SUPPORTIVE positive (dependency)
    sel_supportive = [f for f in subtype if "supportive" in _sig_sel(f)]
    if sel_supportive:
        # SUPPORTIVE positive (tumor-tissue selectivity) — the data-blocked-dependency channel.
        return ("subtype_restricted_selectivity", sel_supportive[0].get("rule_id"))
    # LOWEST priority (SK#1624): a POWERED cross-subtype expression differential. ADDITIVE — reached
    # only when none of the above subtype verdicts fired, so it never displaces them.
    expr_rule = _subtype_expression_differential(expr_result)
    if expr_rule:
        return ("subtype_powered_differential", expr_rule)
    return None


# --- Subtype tier skill_report SPINE (2026-09-17) -----------------------------------------------
#
# The inline subtype tier was the ONE axis in the fan-out with NO `synthesis_facet`, so
# `tp_facets._skill_reports_by_short` (which requires `r['synthesis_facet']['skill_report']`) skipped it
# and `synthesis.skill_reports` carried NO `subtype_fit` entry on ANY run. With no report there is no
# `provenance`, so the axis was invisible to every provenance reader — `risk_projection.
# _axis_card_provenance`, `evidence_coverage_by_axis`, `report_render.ir._dim_members`. That absence, not
# any mapping, is why `subtype_fit` could not be decided in the #1418/#1420 axis→dim settlement: an axis
# with no measurable provenance cannot be argued about. This emits the report; it does NOT map the axis
# into a risk dim (still `open_pending_review` in `risk_projection.AXIS_DIM_EXCLUSIONS`).
#
# ★ WHAT THIS DELIBERATELY DOES NOT DO — the scope-foreclosure invariant is PRESERVED BY PLACEMENT.
# The report is built INSIDE the `if subtypes:` block, so a default (no `--subtypes`) run still has NO
# `subtype_fit` key in `sub_results` at all. `tp_gates._SCOPE_OPTIN_GATING_AXES` depends on exactly that
# distinction: absent → `excluded` (scope-foreclosed), present-but-dormant → `latent`, and NEITHER is
# `blind` (a blind gated axis would make the cross-evidence fail-closed ceiling DECLINE every target on
# the default path). So the target is NOT "0/504 → 504/504 reports"; it is "0/N → N/N on the subtype-
# scoped runs", and manufacturing a report on the no-subtypes path would be the exact failure
# `_SCOPE_OPTIN_GATING_AXES` exists to prevent.
#
# ★ ROLE = GATING, AND WHY THAT CONTRADICTS A COMMENT ABOVE. `_SHORT_TO_GATE`'s comment calls itself
# "the kill/hold gating axes, ROLE_GATING + polarity scored", and `subtype_fit` is ABSENT from it — yet
# `subtype_fit` IS in `tp_gates._GATING_AXES` and `tp_gates` maps
# ("subtype_fit", "subtype_specific_non_dependence") → "hold". FOUR rosters answer "is this axis
# gating?" and they do NOT agree (measured 2026-09-17):
#   * `_SHORT_TO_GATE` (skills, resolver map)                    → ABSENT
#   * `tp_gates._GATING_AXES` (skills, recommendation-forcing)   → PRESENT
#   * contracts `gate_coverage.yaml` biomarker_facets            → PRESENT (grain: sub_skill ⇒ scorecard row)
#   * contracts `coverage/rule_role_partition.yaml`              → all 12 subtype rules are `display`
# The last is not drift but STRUCTURAL BLINDNESS: that partition defines gating as "reachable from a
# verdict-moving RESOLVER keypath", and `subtype_fit` has no resolver — its verdict comes from
# `_subtype_verdict` over panorama rows, and the hold is applied by a hardcoded skills-side action map
# the partition cannot see. `role` describes how the COMPOSER treats the axis (the contract's own words),
# and the composer treats it as hold-capable ⇒ ROLE_GATING. This is therefore the ONE axis where
# role=gating does NOT imply membership in `_SHORT_TO_GATE`.
#
# ★ POLARITY IS ALWAYS EXPLICIT — NEVER THE FALL-THROUGH. `canonical_polarity` for a gating role reads
# `headline_block.verdict.polarity`, and the fan-out NEVER builds a headline, so the default path is
# `_HEADLINE_TO_CANONICAL.get(None) → "neutral"`: a NEUTRAL polarity for an axis whose verdict can force
# a hold. That is the wrong direction on a fall-through (a favorable label reachable by the LEAST
# evidence), and it is not merely cosmetic — `build_skill_report_rollup` computes
# `peak_gating_rank = max(rank)` over the gating polarities, so a DORMANT axis emitting `neutral` (rank 0)
# would RAISE the peak gating signal of a target whose every other gating axis reads `opposing` (rank -1).
# A target must not read better because an axis said nothing. So every case is mapped explicitly and the
# dormant case is `not_scored`, which `_SKILL_REPORT_POLARITY_RANK` does not contain ⇒ it is visible in
# `gating_polarities` but contributes NO rank (label, do not drop).
_SUBTYPE_VERDICT_POLARITY = {
    # the HOLD (negative, precedence-winning). `opposing` and NOT `killer`: a hold is not a veto, and
    # `killer` is the token `build_skill_report_rollup` collects into `killer_axes` / the INV-6
    # `recommendation_exceeds_signals` flag and that `report_render.ir` de-escalates. Claiming a veto
    # here would overstate a hold on a display surface with real readers.
    "subtype_specific_non_dependence": "opposing",
    "subtype_restricted_dependency": "supportive",  # KO-proven efficacy + non_dependent veto-suppressor
    "subtype_restricted_selectivity": "supportive",  # tumor-tissue analogue; NOT a veto-suppressor
    "subtype_powered_differential": "supportive",  # SK#1624 powered cross-subtype expression differential;
    # DOMINANT positive in the nomination gate but `supportive` POLARITY on this display surface (a
    # patient-selection nomination input, NOT a veto/hold): same polarity family as the two rungs above.
    # MUST be listed — an unrecognized token fail-closes to `opposing` (_SUBTYPE_UNRECOGNIZED_POLARITY).
    # recognized by tp_gates but NON-gating ("falls through as a permissive pass, never forces hold") and
    # it asserts nothing was measurable ⇒ unranked, exactly like the dormant case. Listed EXPLICITLY, not
    # left to a default, so that adding a verdict to the vocab forces a decision here (a guard test pins
    # this map against tp_gates._RECOGNIZED_GATING_VERDICTS['subtype_fit']).
    "insufficient": "not_scored",
}

# ★ TWO fall-throughs, pointing OPPOSITE ways — do not collapse them into one default.
#   verdict is None  → the tier RAN and no stratum fired: `latent`/dormant, the designed OK state
#                      (_SCOPE_OPTIN_GATING_AXES). Nothing was measured ⇒ `not_scored` (UNRANKED).
#   verdict is a non-empty token NOT in the map → UNRECOGNIZED/RENAMED. `tp_gates` fail-closes exactly
#                      this case to its least-permissive action (_GATING_AXIS_FAILCLOSED_ACTION
#                      ['subtype_fit'] == 'hold'), so the spine must fail the SAME direction: `opposing`.
#                      Defaulting it to `not_scored` would let a renamed hold verdict read as "nothing
#                      measured" on the display spine while the gate was holding on it.
_SUBTYPE_UNRECOGNIZED_POLARITY = "opposing"  # mirrors _GATING_AXIS_FAILCLOSED_ACTION['subtype_fit']


def _subtype_spine_skill_report(
    verdict_pair: "tuple[str, str | None] | None",
    sub_cards: list,
    sub_fired: list,
) -> dict:
    """The subtype tier's `skill_report`, for `synthesis_facet.skill_report`. Pure projection over the
    already-decided `verdict_pair` + the tier's own cards/fired — it NEVER recomputes a verdict.

    `fired_rule_ids` is derived as the rule_ids of THIS run's `sub_fired`, which is what
    `archetype_core.fired_rule_ids_from_sub_results` would otherwise reach via its legacy `fired`
    fallback — the two must stay the same SET, or supplying a report would silently change the atlas
    rule-fingerprint (a report is not automatically atlas-inert; that reader takes the spine leg the
    moment `provenance.fired_rule_ids` is non-empty).

    `modality_scope=None` is DELIBERATE, for the same reason: `_modality_scope_by_axis` reads the spine
    first and falls back to `claim_record_shadow`, and the subtype tier emits NEITHER today, so that
    reader has no `subtype_fit` entry at all. Emitting a scope here would invent a per-channel
    FOR-WHAT claim the tier never computed. `claim_vector` is likewise omitted from the facet, so
    `archetype_core.vector_from_sub_results` (chips → legacy claim_vector fallback) and
    `feature_vectoriser.numeric_values_from_sub_results` (claim_vector guard) are unchanged.
    """
    verdict = verdict_pair[0] if verdict_pair else None
    driving_rule_id = verdict_pair[1] if verdict_pair and len(verdict_pair) > 1 else None
    if not verdict:  # dormant/`latent`: the tier ran, no stratum fired → unranked, never favorable
        polarity = "not_scored"
    else:  # a token we do not recognize fails CONSERVATIVE, the same direction tp_gates fails
        polarity = _SUBTYPE_VERDICT_POLARITY.get(verdict, _SUBTYPE_UNRECOGNIZED_POLARITY)

    # cards_used / cards_missing follow the SAME convention every wired skill uses (the resolver's
    # `_missing` flag, e.g. tumor-selectivity/run.py, dispatcher.py:993) — `used` is the NOT-missing set,
    # not every requested card, or a fully data-blocked tier would report itself as covered. Order is the
    # tier's resolve order (deterministic: SUBTYPE_CARDS × servable strata), deduped defensively.
    def _ids(missing: bool) -> list:
        out: list = []
        for c in sub_cards or []:
            if not isinstance(c, dict) or not c.get("card_id"):
                continue
            if bool(c.get("_missing")) is missing and c["card_id"] not in out:
                out.append(c["card_id"])
        return out

    used, missing = _ids(missing=False), _ids(missing=True)
    return build_skill_report(
        role=ROLE_GATING,
        verdict=verdict,
        driving_rule_id=driving_rule_id,
        fired_rule_ids=[f.get("rule_id") for f in (sub_fired or []) if isinstance(f, dict) and f.get("rule_id")],
        cards_used=used,
        cards_missing=missing,
        modality_scope=None,  # see docstring — keeps _modality_scope_by_axis byte-stable
        canonical_polarity_override=polarity,
    )


def _subtype_spine_facet(
    verdict_pair: "tuple[str, str | None] | None",
    sub_cards: list,
    sub_fired: list,
) -> Optional[dict]:
    """`synthesis_facet` for the subtype tier: the skill_report and NOTHING else.

    ★ THE NAME IS `_subtype_spine_facet`, NOT `_subtype_facet`, AND THAT IS LOAD-BEARING.
    `tp_facets_subtype._subtype_facet` already exists (the cross-axis subtype CONVERGENCE blob, a
    different thing), `tp_facets` re-exports it, and `run.py` imports it BY NAME at line ~70 and THEN does
    `from tp_fanout import *` at line ~94. Because this module's `__all__` lists its underscore names
    (16 of 20 — `__all__` OVERRIDES the "star-import skips `_names`" rule), a same-named helper here
    silently REBINDS `run._subtype_facet` to this function: later star-import wins. Measured, not
    theorised — it red-lined 18 previously-green tests with `TypeError: missing 2 required positional
    arguments`. A guard test pins the two `__all__` sets disjoint.

    BEST-EFFORT by the same discipline every other spine projection in this repo follows (see
    tumor-selectivity/run.py's `_enrichment_errors` guard): a DISPLAY/provenance projection must never be
    able to break the fan-out, whose `verdict` is already decided above. On failure this returns None,
    which is byte-identical to the pre-2026-09-17 behaviour (no facet ⇒ `_skill_reports_by_short` skips
    the tier) — the degrade path is the OLD path, not a new one.
    """
    try:
        return {"skill_report": _subtype_spine_skill_report(verdict_pair, sub_cards, sub_fired)}
    except Exception:  # noqa: BLE001 — provenance projection; degrades to the pre-existing no-facet state
        return None


def _skipped_synthesis_output() -> dict:
    """Stub llm_output for --verdict-only/--no-synthesis (no Bedrock call).

    The deterministic recommendation gate + positive-tier logic clamp into
    overall_recommendation / confidence exactly as for a real (or degraded _synthesis_error)
    narration, so the verdict spine is byte-identical. Renderers read
    llm_output.get(section, {}).get("value", default) — absent narrative sections degrade to
    empty; executive_summary carries a note so the report is self-explanatory, not blank.
    """
    return {
        "_synthesis_skipped": True,
        "executive_summary": {
            "value": (
                "_LLM synthesis skipped (--verdict-only). The deterministic verdict spine below — "
                "gate scorecard, sub-verdicts, recommendation gate, positive tier, deciding axis — "
                "is authoritative and byte-identical to a full run. Re-run without --verdict-only "
                "for the narrative synthesis._"
            ),
            "_source": "synthesis_skipped",
        },
        "overall_recommendation": {"value": None, "_source": "synthesis_skipped"},
        "confidence": {"value": None, "_source": "synthesis_skipped"},
    }


def _select_active_sub_skills(skills: "Optional[Iterable[str]]") -> list:
    """The (skill_dir, short) pairs to run: all of SUB_SKILLS when `skills` is None (byte-stable full
    fan-out), else only those whose DIR id OR short name is named. Raises if the subset matches nothing
    (a typo must fail loud, not silently run everything). Module-level so it is unit-testable."""
    if skills is None:
        return list(SUB_SKILLS)
    want = {s.strip() for s in skills if s and s.strip()}
    active = [(sd, sh) for sd, sh in SUB_SKILLS if sd in want or sh in want]
    if not active:
        raise ValueError(f"skills={sorted(want)} matched no sub-skill (dir or short) in SUB_SKILLS")
    return active


def _run_sub_skills(
    target: str,
    indication: str,
    subtypes: Optional[list[str]] = None,
    profile_timers: bool = False,
    plot_data_root: Optional[Path] = None,
    synthesize_subskills: bool = False,
    subskill_literature: bool = False,
    subskill_literature_scope: str = "all",
    synthesis_model: Optional[str] = None,
    skills: "Optional[Iterable[str]]" = None,
    trace: "Optional[Any]" = None,
) -> dict:
    """Invoke each sub-skill's verdict logic in-process. Returns dict keyed
    by short name (`expression`, `selectivity`, ...) with:
      - `skill_dir`
      - `cards`: card_outputs from resolve_cards
      - `fired`: fired-rules list
      - `verdict`: (verdict_str, driving_rule_id) tuple or None if the
        sub-skill doesn't expose a verdict function (e.g. patient-
        population-and-access has no rules; verdict is None)
    """
    # Fire BOTH rule axes and merge. load_interpretation_rules loads exactly
    # one axis file, so a sub-skill whose cards span axes (surface-modality-fit
    # fires surface_intrinsic; most others fire intracellular_intrinsic) would
    # otherwise silently fire nothing on the un-loaded axis. filter_by_card_ids
    # scopes each axis's rules to the sub-skill's cards, so firing both is safe
    # (no cross-contamination) and card-correct regardless of which file a
    # card's rules live in. (Fixed 2026-07-14 when the tractability split first
    # made a surface-only sub-skill a peer in the composer.)
    # Rule AXES fired per sub-skill (card_id_filter scopes each to its own cards). combinatorial_dependency
    # (2026-08-14) is a DEDICATED axis — the combinatorial-dependency skill's rules live in
    # combinatorial-dependency.rules.yaml on their own axis, isolated from the shared ladder. Without it
    # here the fan-out fired NO combinatorial rules → the axis always resolved `insufficient` in the
    # composed profile (a hollow composition) while the standalone skill read constitutive/context. Other
    # sub-skills lack the combinatorial-dependency card, so this axis is a no-op for them (card_id_filter).
    axes = (
        "intracellular_intrinsic",
        "surface_intrinsic",
        "combinatorial_dependency",
        "cis_coherence",
        "combination_opportunity",
        "resistance_emergence",
    )

    def _one_sub_skill(skill_dir: str, short: str) -> tuple[str, dict]:
        """Compute one sub-skill's (cards, fired, verdict). Pure over (target, indication) +
        that sub-skill's own cards — no cross-sub-skill state (verified collect-then-synthesize),
        so this is safe to run concurrently. Returns (short, result-dict)."""
        _t0 = time.perf_counter() if profile_timers else 0.0
        # Figure Stage 3 (offline seam): when plot_data_root is set (a figures-emitting run), each
        # method persists its plot_data under <plot_data_root>/cards/<card_id>/ DURING resolution, so the
        # figure emitters render OFFLINE from it instead of re-executing a second live read. VERDICT-INERT
        # — persistence is a side artifact; the returned card summaries (hence the verdict spine) are
        # byte-identical to a plot_data_root=None run. None (verdict-only / --no-figures) => no persistence.
        cards = resolve_cards(
            SUB_SKILL_CARDS[skill_dir], target, indication, plot_data_root=plot_data_root, trace=trace
        )
        if profile_timers:
            print(
                f"[perf] read  {short:26s} {time.perf_counter() - _t0:6.1f}s ({len(SUB_SKILL_CARDS[skill_dir])} cards)",
                file=sys.stderr,
            )
        # (2026-08-13): apply the sub-skill gate's registered CARD PREPROCESSOR (e.g. the
        # genomic-alteration family-wise FDR) BEFORE firing, so the composed fan-out corrects the card
        # summaries identically to the standalone skill's main(). Previously the FDR was standalone-only
        # → this fan-out fired on un-corrected p-values and over-credited biomarker_stratified_dependency
        # (the nomination veto-suppressor). No-op for gates with no registered preprocessor.
        preprocess_cards_for_gate(cards, _SHORT_TO_GATE.get(short))
        fired: list[dict] = []
        for axis in axes:
            fired.extend(fired_rules(cards, axis=axis, card_id_filter=SUB_SKILL_CARDS[skill_dir]))
        verdict_fn = _load_sub_skill_verdict_fn(skill_dir)
        try:
            verdict_pair = verdict_fn(fired) if verdict_fn else None
        except RuntimeError as exc:
            if not _gateless_absent_resolver(short, exc):
                raise
            verdict_pair = None
        # OPTIONAL deterministic cross-modal reconciliation facet (2026-08-17). Best-effort +
        # VERDICT-INERT: a sub-skill that exposes _synthesis_facet hands the composed synthesis its
        # own reconciliation (e.g. tumor-presence's per-modality matrix); absence / failure → None,
        # never touching verdict/fired/cards. Only tumor-presence supplies it today.
        _facet_fn = _load_sub_skill_facet_fn(skill_dir)
        synthesis_facet = None
        if _facet_fn is not None:
            try:
                # A _synthesis_facet may OPTIONALLY declare target/indication (signature-introspected,
                # mirrors the dispatcher's headline_fn call) — e.g. tumor-presence keys a curated surface-
                # antigen vocab for its #980 abundance anchor. Pass them only when declared, so standalone
                # (dispatcher) and composed (fan-out) compute the SAME facet (no drift); a 3-arg facet is
                # called byte-identically.
                _facet_kwargs = {}
                try:
                    _fp = inspect.signature(_facet_fn).parameters
                    if "target" in _fp:
                        _facet_kwargs["target"] = target
                    if "indication" in _fp:
                        _facet_kwargs["indication"] = indication
                except (ValueError, TypeError):
                    _facet_kwargs = {}
                synthesis_facet = _facet_fn(cards, fired, verdict_pair, **_facet_kwargs)
            except Exception:  # noqa: BLE001 — a facet must never break the fan-out
                synthesis_facet = None
        # OPTIONAL per-axis (strength, certainty) SIDECAR (CERTAINTY_MODEL). Best-effort +
        # VERDICT-INERT, same discipline as synthesis_facet: a sub-skill that exposes _strength_certainty
        # hands the composed layer its reliability object; absence / failure → None. Only
        # functional-requirement supplies it today.
        # PREFER the strength_certainty a sub-skill already emitted into its synthesis_facet (tumor-presence
        # emits a RE-BASED composite there — strength from the integrated claim_vector, not the collapsed
        # verdict — so the composed composite matches the standalone one). Fall back to the _strength_certainty
        # hook for skills that expose the hook but not the facet key.
        strength_certainty = (
            (synthesis_facet or {}).get("strength_certainty") if isinstance(synthesis_facet, dict) else None
        )
        if strength_certainty is None:
            _cert_fn = _load_sub_skill_certainty_fn(skill_dir)
            if _cert_fn is not None:
                try:
                    strength_certainty = _cert_fn(cards, fired, verdict_pair)
                except Exception:  # noqa: BLE001 — a sidecar must never break the fan-out
                    strength_certainty = None
        # OPTIONAL factored claim-record SHADOW (M1). Same best-effort + VERDICT-INERT discipline as
        # strength_certainty: a sub-skill exposing _claim_record hands the composed layer its factored
        # record; absence / failure → None. Consumed by nothing (surfaced for M2 render-equivalence).
        _cr_fn = _load_sub_skill_claim_record_fn(skill_dir)
        claim_record_shadow = None
        if _cr_fn is not None:
            try:
                claim_record_shadow = _cr_fn(cards, fired, verdict_pair)
            except Exception:  # noqa: BLE001 — a shadow must never break the fan-out
                claim_record_shadow = None
        # OPTIONAL per-sub-skill LITERATURE lane (--subskill-literature / --rich-embedded). Runs the SAME
        # make_literature_fn(<lens>) the standalone --literature run uses (EuropePMC/PubTator grounding +
        # verify_citations), attaching decision['literature_synthesis'] so the carried evidence_graph gets
        # its literature axes + citations (embedded lens view == standalone). Best-effort + VERDICT-INERT;
        # serialized behind _SYNTH_LOCK (shared with narration) to avoid the concurrent-Bedrock throttle.
        # Scope-gated: 'all' sub-skills, or 'gating' (the _SHORT_TO_GATE axes only). A skill with no lens
        # is skipped (honest). Lands on synthesis_facet['literature_synthesis'], read by the carry below.
        # RUNS BEFORE NARRATION (the reorder): the literature it computes (`_lit`) is threaded into the
        # decision the narrator reads (narrator_engine._render_literature reads decision['literature_
        # synthesis']) so the per-sub-skill exec_bullets WEAVE + CITE the literature lane (citation_ids /
        # PMIDs), matching the standalone --literature+--synthesize product. `_lit` stays None → the
        # narrator prompt is byte-identical to a no-literature run.
        _lit = None
        if (
            subskill_literature
            and isinstance(synthesis_facet, dict)
            and (subskill_literature_scope != "gating" or _SHORT_TO_GATE.get(short))
        ):
            _lens = _SKILL_LENS.get(skill_dir)
            if _lens is not None:
                try:
                    _lit_decision = _reconstruct_decision(skill_dir, cards, fired, verdict_pair, target, indication)
                    _litfn = make_literature_fn(_lens, retrieve_fn=default_retrieve, verify_fn=verify_citations)
                    with _SYNTH_LOCK:
                        _lit = _litfn(_lit_decision, synthesis_model)
                    if isinstance(_lit, dict) and _lit:
                        synthesis_facet["literature_synthesis"] = _lit
                except Exception:  # noqa: BLE001 — a display lane must never break the fan-out
                    _lit = None
        # OPTIONAL per-sub-skill single-lens LLM narration (--synthesize-subskills). Best-effort +
        # VERDICT-INERT, same discipline as synthesis_facet: a narrator-bearing sub-skill exposes
        # _llm_synthesis and hands the composed layer the SAME provenance-tagged block its standalone
        # --synthesize run attaches; absence (7 non-narrator shorts) / failure (Bedrock auth) → None.
        # This is the ONLY hook here that issues a network (Bedrock) call, gated on synthesize_subskills.
        # The literature lane above ran FIRST; its result (`_lit`) is threaded into the decision the
        # narrator reads so the exec_bullets weave + cite the literature. None → today's behaviour.
        llm_synthesis = None
        if synthesize_subskills:
            _synth_fn = _load_sub_skill_synthesis_fn(skill_dir)
            if _synth_fn is not None:
                llm_synthesis = _synthesize_with_retry(
                    _synth_fn,
                    cards,
                    fired,
                    verdict_pair,
                    target,
                    indication,
                    synthesis_model,
                    literature_synthesis=_lit,
                )
            else:
                # central-lens narration fallback: a sub-skill WITHOUT a bespoke `_llm_synthesis` hook
                # (only 6 declare one) still narrates through its OWN lens via make_synthesize_fn(<lens>) —
                # the same narrator the standalone --synthesize run uses — so rich-embedded narrative is
                # fleet-wide, not just the 6 hook-bearing skills. Best-effort + locked (Bedrock throttle).
                _lens = _SKILL_LENS.get(skill_dir)
                if _lens is not None:
                    try:
                        _n_decision = _reconstruct_decision(skill_dir, cards, fired, verdict_pair, target, indication)
                        # Feed the pre-computed literature lane onto the decision the narrator reads so its
                        # exec_bullets weave + cite the literature (verdict-inert; None → byte-identical).
                        _n_decision["literature_synthesis"] = _lit
                        with _SYNTH_LOCK:
                            llm_synthesis = make_synthesize_fn(_lens)(_n_decision, synthesis_model)
                    except Exception:  # noqa: BLE001 — a display lane must never break the fan-out
                        llm_synthesis = None
        # PHASE 3 (tumor-presence): the EMITTED presence word is reconciled with the signal package in
        # _headline (stromal-only / protein↔RNA conflict / not-present demote to caveated tokens). The
        # facet carries that reconciled word; reflect it in the STORED sub-result verdict so the composed
        # dashboard + risk-rollup can't display a word that disagrees with presence_state. The internal
        # hooks above stay on the raw verdict_pair. Verdict-INERT (presence ∉ _SHORT_TO_GATE); no-op for
        # every other sub-skill (only presence's facet carries presence_verdict).
        # EMBEDDED SUB-SKILL VIEW (subgroup_signals propagation): compute the hierarchy sub-group signals
        # centrally and attach them to the skill_report on the spine, so the composed report can render
        # each skill's embedded view (sub-group bands + signal×confidence scatter) — the same detail the
        # standalone sub-skill report shows. Best-effort + VERDICT-INERT: any fault (or target-contracts
        # absent) → {} → skipped; never touches verdict/fired/cards. Mirrors the dispatcher, which
        # attaches subgroup_signals to the standalone headline.
        # (2026-09-12) Now passes the sub-skill's OWN reader spec + value→tier classifier — the pair its
        # standalone run uses — instead of the framework default. This was the "per-skill tuned reader
        # specs are a follow-up" note: 12 skills tune their panel and composition dropped ALL of it, so
        # the embedded view showed different tiers than the standalone report from the same evidence
        # (see _load_sub_skill_subgroup_reader). A facet-supplied claim_vector still sharpens the overlay.
        if isinstance(synthesis_facet, dict):
            _sr = synthesis_facet.get("skill_report")
            if isinstance(_sr, dict) and not _sr.get("subgroup_signals"):
                try:
                    _cv = synthesis_facet.get("claim_vector")
                    _spec, _classify = _load_sub_skill_subgroup_reader(skill_dir)
                    _sg_kwargs = {"claim_vector": _cv if isinstance(_cv, dict) else None}
                    if _spec is not None:
                        _sg_kwargs["reader_spec"] = _spec
                    if _classify is not None:
                        _sg_kwargs["classify"] = _classify
                    _sg = subgroup_signals_for(SKILLS_DIR / skill_dir, cards, **_sg_kwargs)
                    if _sg:
                        _sr["subgroup_signals"] = _sg
                except Exception:  # noqa: BLE001 — verdict-inert; never break the fan-out
                    pass

        stored_verdict = verdict_pair
        if isinstance(synthesis_facet, dict) and synthesis_facet.get("presence_verdict") and verdict_pair:
            stored_verdict = (synthesis_facet["presence_verdict"], verdict_pair[1] if len(verdict_pair) > 1 else None)
        # OPTIONAL evidence_graph CARRY (P2, composed-evidence-graph rollup; docs/COMPOSED_EVIDENCE_GRAPH_ROLLUP.md §1).
        # Best-effort + VERDICT-INERT + DISPLAY-ONLY. The fan-out never builds a headline, so reconstruct the
        # sub-skill's headline (evidence_capsules + subgroup_signals) via its _headline hook and call
        # build_evidence_graph EXACTLY as the standalone dispatcher does (dispatcher.py:669/908), then stash the
        # graph on the skill_report so tp_facets._skill_reports_by_short carries it to
        # target_report.skill_reports[<short>].evidence_graph. The embedded lens view then renders from the SAME
        # graph as the standalone dashboard. Absence of a _headline hook / any failure → no graph attached;
        # sub_verdicts / target_call / cards / fired are untouched (byte-stable). The reconstructed headline is
        # NEVER stored or re-fed to the resolver — it exists only to project the display graph.
        if isinstance(synthesis_facet, dict) and isinstance(synthesis_facet.get("skill_report"), dict):
            try:
                _eg_decision = _reconstruct_decision(skill_dir, cards, fired, verdict_pair, target, indication)
                # literature_synthesis is populated by the --subskill-literature lane above (else None);
                # llm_synthesis by --synthesize-subskills (else None → narrative={}).
                _eg_decision["literature_synthesis"] = synthesis_facet.get("literature_synthesis")
                _eg_decision["llm_synthesis"] = llm_synthesis
                # Call the SHARED seam (identical to the dispatcher + genomic main): builds the graph incl.
                # per-card key_evidence + self-checks referential integrity onto the reconstructed headline,
                # then stash it on the skill_report for the embedded lens view.
                attach_evidence_graph(_eg_decision, SKILLS_DIR / skill_dir)
                _eg_graph = (_eg_decision.get("headline") or {}).get("evidence_graph")
                if _eg_graph is not None:
                    synthesis_facet["skill_report"]["evidence_graph"] = _eg_graph
            except Exception:  # noqa: BLE001 — a display projection must never break the fan-out
                pass
        return short, {
            "skill_dir": skill_dir,
            "cards": cards,
            "fired": fired,
            "verdict": stored_verdict,  # (str, driving_rule_id) or None; presence word = reconciled
            # Deterministic cross-modal reconciliation for the synthesis prompt (None for every
            # sub-skill except tumor-presence). ADDITIVE / verdict-inert — see _load_sub_skill_facet_fn.
            "synthesis_facet": synthesis_facet,
            # Per-axis (strength, certainty) sidecar (None except functional-requirement). ADDITIVE /
            # verdict-inert — see _load_sub_skill_certainty_fn. Assembled by tp_facets._certainty_by_axis.
            "strength_certainty": strength_certainty,
            # Factored claim-record SHADOW (M1). ADDITIVE / verdict-inert / consumed-by-nothing — see
            # _load_sub_skill_claim_record_fn. Assembled by tp_facets._claim_record_shadow_by_axis.
            "claim_record_shadow": claim_record_shadow,
            # Per-sub-skill single-lens LLM narration (None unless --synthesize-subskills AND the
            # sub-skill declares a narrator). ADDITIVE / verdict-inert — see
            # _load_sub_skill_synthesis_fn; persisted into subskills/<short>/package.json by tp_manifest.
            "llm_synthesis": llm_synthesis,
            # the SAME sub-verdict, carried in the shared CompositionResult type (the
            # foundation the later --emit evidence-package stage consumes). ADDITIVE — wraps the
            # already-decided verdict_pair (post-resolver logic preserved); verdict/fired/cards and
            # the nomination emission are untouched, so output stays byte-identical. Gateless shorts
            # (tumor-presence `expression`) → empty primary; the presence verdict stays in `verdict`.
            "composition": subskill_composition(
                card_outputs=cards,
                fired=fired,
                gate=_SHORT_TO_GATE.get(short),
                verdict_pair=verdict_pair,
            ),
        }

    # PERF (2026-07-23): the sub-skills are GENUINELY INDEPENDENT (collect-then-synthesize;
    # no sub-skill reads another's result), so fan them out CONCURRENTLY. THREADS not processes: the
    # method-layer caches (depmap_common.parquet lru + disk cache; framework-tpm-long/hpa disk latches)
    # are process-global, so threads SHARE a target's reads across sub-skills (processes would
    # duplicate + re-download). pandas/pyarrow release the GIL during parquet/CSV I/O, so the IO-bound
    # reads overlap. Wall is bounded by the longest single sub-skill (measured: `expression` ~106s).
    #
    # BYTE-STABILITY: concurrency must NOT change the deterministic verdict spine. Two guards:
    #   1. Pre-warm all imports ONCE before the pool (below) — neutralizes the sys.path.insert(0,...)
    #      global-list race in the dispatcher/method imports.
    #   2. Re-assemble `results` in SUB_SKILLS order (NOT completion order) — every downstream
    #      reduction (_ordinal_matrix / _gate_recommendation / _deciding_axis / scorecard) + the
    #      nomination.json sub_verdicts iterate this dict; insertion order must match the serial run.
    # OPTIONAL skill SUBSET (skill-scoped discordance harvest): run only the named sub-skills' lanes
    # instead of the whole fan-out. None → the full fan-out (byte-stable default; the composed-profile /
    # nomination path never passes this). A COMPUTE subset for the eval loop, NOT a composition change —
    # a subset run is not a valid nomination package (the gate needs the full axis set).
    _active = _select_active_sub_skills(skills)
    _prewarm_sub_skill_imports()
    completed: dict = {}
    # DEV TOOLING (--trace, chain audit): a ReadTrace attributes each captured read to the card being
    # resolved via a thread-local sink, so concurrent sub-skills would interleave reads ambiguously.
    # Force the sequential fan-out (1 worker) under trace — the documented "--trace forces the sequential
    # read path" contract — so per-card IO attribution is unambiguous. None ⇒ full concurrency, unchanged.
    _workers = 1 if trace is not None else min(len(_active), _FANOUT_MAX_WORKERS)
    with concurrent.futures.ThreadPoolExecutor(max_workers=_workers) as ex:
        futures = {ex.submit(_one_sub_skill, sd, sh): sh for sd, sh in _active}
        for fut in concurrent.futures.as_completed(futures):
            short, res = fut.result()  # a sub-skill exception propagates here (fail-loud, as serial did)
            completed[short] = res
    # deterministic re-order: rebuild in SUB_SKILLS order (byte-stability guard #2)
    results: dict = {short: completed[short] for _, short in _active}

    # Subtype tier — ONLY when a subtype scope was requested. Panorama cards need
    # the resolved strata + assignments shard threaded via subgroup_context; the
    # subtype rule fires in_record on measured, floor-cleared, not-dependent rows.
    if subtypes:
        # Per-card cohort filtering (2026-09-11, CDH3 subtype-dispatch review): resolve each card with
        # ONLY the strata its backing cohort can serve (see _SUBTYPE_CARD_COHORTS / _strata_for_card),
        # rather than fanning the whole stratum set into every card. A patient-only stratum
        # (CMS/CIMP/sidedness) no longer reaches the DepMap cell-line dependency card as a dead
        # subgroup_n:0 row; it still reaches the TCGA-backed selectivity card that can carry it.
        # VERDICT-INERT: the dropped rows were floor-suppressed absences that fired no subtype rule.
        # A card left with NO servable stratum is skipped (no empty-scope panorama read).
        from tp_facets_subtype import _load_subtype_crosswalk

        cohorts_of = _load_subtype_crosswalk(indication).get("cohorts_of", {})
        sub_cards = []
        for _card_id in SUBTYPE_CARDS:
            _card_strata = _strata_for_card(_card_id, subtypes, cohorts_of)
            if not _card_strata:
                continue
            _ctx = {"resolved_strata_ids": _card_strata, "catalog_status": "resolved_active"}
            sub_cards.extend(
                resolve_cards(
                    [_card_id],
                    target,
                    indication,
                    subgroup_context=_ctx,
                    plot_data_root=plot_data_root,
                    trace=trace,
                )
            )
        sub_fired: list[dict] = []
        for axis in axes:
            sub_fired.extend(fired_rules(sub_cards, axis=axis, card_id_filter=SUBTYPE_CARDS))
        # SK#1624: thread the completed `expression` sub-result so the lowest-priority powered-
        # differential branch can read its fired subtype-expression signals + axis-quality grade.
        subtype_verdict_pair = _subtype_verdict(sub_fired, results.get("expression"))
        results[SUBTYPE_SHORT] = {
            "skill_dir": None,  # not a directory sub-skill; composed inline
            "cards": sub_cards,
            "fired": sub_fired,
            "verdict": subtype_verdict_pair,
            "scope_subtypes": list(subtypes),
            # skill_report SPINE for the inline tier (see _subtype_spine_skill_report). Carries ONLY
            # `skill_report` — no `claim_vector` — so the claim-vector readers (archetype_core.
            # vector_from_sub_results, feature_vectoriser.numeric_values_from_sub_results) keep taking
            # exactly the leg they take today. Best-effort + verdict-INERT: the tier's `verdict` above is
            # already decided and a projection must never be able to break the fan-out.
            "synthesis_facet": _subtype_spine_facet(subtype_verdict_pair, sub_cards, sub_fired),
            # typed sub-verdict carrier (see _one_sub_skill). ADDITIVE.
            "composition": subskill_composition(
                card_outputs=sub_cards,
                fired=sub_fired,
                gate=_SHORT_TO_GATE.get(SUBTYPE_SHORT),
                verdict_pair=subtype_verdict_pair,
            ),
        }
    return results


__all__ = [
    "SUBTYPE_CARDS",
    "SUBTYPE_SHORT",
    "SUB_SKILLS",
    "SUB_SKILL_CARDS",
    "_FANOUT_MAX_WORKERS",
    "_SHORT_TO_GATE",
    "_SUBSKILL_FN_CACHE",
    "_SUBTYPE_UNRECOGNIZED_POLARITY",
    "_SUBTYPE_VERDICT_POLARITY",
    "_gateless_absent_resolver",
    "_load_sub_skill_verdict_fn",
    "_load_sub_skill_facet_fn",
    "_load_sub_skill_certainty_fn",
    "_load_sub_skill_synthesis_fn",
    "_prewarm_sub_skill_imports",
    "_run_sub_skills",
    "_skipped_synthesis_output",
    "_subtype_spine_facet",
    "_subtype_spine_skill_report",
    "_subtype_verdict",
]
