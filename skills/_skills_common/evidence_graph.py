"""evidence_graph — the additive, byte-stable "claim graph" at decision.headline.evidence_graph.

A one-way, DISPLAY-ONLY projection over data already present in a subskill's `decision` dict, so a
downstream renderer can draw the whole dashboard (verdict header, signal×confidence heatmap, question
table with per-question omics + literature, and each card's dataset→data→rule→verdict chain) with
ZERO heuristic joins, zero `.card.yaml` reads, and zero free-text parsing. It introduces NO new
science, feeds NO rule/resolver/gate, and changes NO existing field — `evidence_graph` is the only
key added (attached by reference into `decision["headline"]` at the dispatcher seam).

Nodes carry stable ids and edges are explicit. Datasets and citations are deduplicated into id-keyed
arrays; every other node references them by id. Both directions of the hot edges are materialized
(`questions[].card_ids` and `cards[].question_ids`). Referential integrity is a hard invariant: every
id referenced by an edge resolves to a node in the same package.

Canonical vocabulary comes from the per-skill `questions.yaml` registry (see load_questions): a stable
semantic `question_id` slug + a unified `axis_id` set shared by the question hierarchy AND the
literature lane. The literature axis→question crosswalk is derived from that registry, giving the
otherwise-missing link (e.g. presence axis B → elevated_vs_normal).

Fail-soft throughout: absent `literature_synthesis`/`llm_synthesis` (or their error stubs) yield empty
`literature`/`narrative` sub-objects; a skill without a `questions.yaml` still emits a
referentially-intact graph with best-effort (null) question anchoring.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Optional

import yaml

SCHEMA_VERSION = "1.0"


# ── canonical question registry loader ─────────────────────────────────────────────────────────────
def load_questions(skill_dir) -> list:
    """Load the per-skill canonical question registry (`<skill_dir>/questions.yaml` → questions[]).
    Fail-soft: returns [] when the file is absent or unreadable (a skill not yet migrated)."""
    try:
        p = Path(skill_dir) / "questions.yaml"
        if not p.exists():
            return []
        doc = yaml.safe_load(p.read_text()) or {}
        qs = doc.get("questions") or []
        return [q for q in qs if isinstance(q, dict) and q.get("id")]
    except Exception:  # noqa: BLE001 — display-only projection; never break the spine
        return []


# ── small provenance-unwrap helper (a --literature-only decision.json can re-wrap axes) ─────────────
def _unwrap(v):
    """Unwrap an llm-provenance-stamped value ({value,_source:'llm_synthesized',...}) → its value."""
    if isinstance(v, dict) and "value" in v and v.get("_source") == "llm_synthesized":
        return v["value"]
    return v


# ── signal / confidence projection (ONE canonical polarity vocabulary; no new scoring) ──────────────
# The single display polarity scale is the ordinal_view vocabulary {supportive, neutral, opposing,
# killer} (+ off-scale not_applicable). `_canon_polarity` normalizes the legacy per-lane tokens that
# reached the graph — card fired/liability strings, the question_table's supports/opposes, and the
# headline verdict's positive/negative — onto it, so every consumer (report_render — the sole
# renderer — and the composed embedded view) reads one vocabulary. Unknown tokens pass through
# UNCHANGED so a new vocabulary value can never silently acquire a wrong rank.
_CANON_POLARITY = {
    "supports": "supportive",
    "supportive": "supportive",
    "positive": "supportive",
    "opposes": "opposing",
    "opposing": "opposing",
    "negative": "opposing",
    "neutral": "neutral",
    "killer": "killer",
    "none": "not_applicable",
    "not_applicable": "not_applicable",
    "na": "not_applicable",
}


def _canon_polarity(p):
    """Map a legacy polarity token to the canonical ordinal_view vocabulary; None→None, unknown→as-is."""
    if p is None:
        return None
    return _CANON_POLARITY.get(str(p).lower(), p)


def _verdict_polarity(headline: dict, hb_verdict: dict):
    """The graph verdict node's direction, with the ONE severity the headline channel cannot carry.

    Base value is the canonicalized headline verdict polarity — a READ DIRECTION, deliberately NOT
    role-gated, so a `descriptive`/`inert` axis still renders which way its evidence points even
    though the spine scores it `not_scored`. That asymmetry is intended and pinned (see
    docs/UNIFIED_OUTPUT_CONTRACT.md § "Type 2"); do not "fix" it by copying the spine wholesale.

    The correction here is a different fact. `killer` is a member of the ordinal_view scale above,
    but it was UNREACHABLE from this input: `headline_block.verdict.polarity` is the 3-band
    positive/neutral/negative field, and `skill_report._HEADLINE_TO_CANONICAL` floors every negative
    at `opposing` precisely because severity needs the driving rule, which this layer cannot see. A
    skill that KNOWS its call is a veto therefore declares it via
    `build_skill_report(canonical_polarity_override="killer")` — which lands on the SIBLING
    `headline.skill_report.polarity`, one key over in this same emitted object. The graph never read
    it, so a surface-axis KILL rendered as merely `opposing` on the only surface any renderer reads
    (`report_render` reads (5) for `_skill_graph_header`; nothing renders (4)).

    ESCALATE-ONLY, and that is the whole safety argument: `killer` is the least favourable token on
    the scale, so honouring a declared one can only ever make the surface read WORSE, never better,
    and it can never blank a badge. Nothing here may lower or blank a direction. Monotone by
    construction, so there is no state in which this join softens a call.
    """
    base = _canon_polarity(hb_verdict.get("polarity"))
    sr = (headline or {}).get("skill_report")
    if isinstance(sr, dict) and sr.get("polarity") == "killer":
        return "killer"
    return base


def _verdict_call(headline: dict, hb_verdict: dict):
    """The graph verdict node's `id` — the skill's OWN call token, read from the authoritative spine.

    Sibling of `_verdict_polarity` above, and the same shape of join for the same reason: the value
    this layer wants already exists one key over, on `headline.skill_report`, and reading it makes an
    invariant STRUCTURAL that was previously only true by habit.

    WHAT THIS FIELD IS, because the contract got it wrong for the life of the file. `verdict.id` was
    declared to be the *resolver* token and "must be identical" to `sub_verdicts.<axis>.verdict`.
    It is not: it is the skill's own **call**, which for ten of eleven skills HAPPENS to be their
    resolver verdict (they pass it straight through to `build_skill_report(verdict=…)`) and for
    `surface-modality-fit` deliberately is not — `run.py` passes the composed `adc-tce-modality-fit`
    `fit_class`, keeping the resolver's safety/density downgrade in the top tension on purpose. So the
    measured "619 / 683 agree with the resolver" was a **confound**: it is a property of those ten
    skills, not of this field. The invariant that actually holds is `id == skill_report.call`, at
    683/683 composed rows and 218/218 per-skill rows. See docs/UNIFIED_OUTPUT_CONTRACT.md § "Type 1".

    VALUE-NEUTRAL, replayed rather than argued: over all 297 live `decision.json`
    (292 with a dict headline) the pre-join chain and this one return the identical value on
    **292 / 292**. It could not be otherwise — `skill_report.call` and the fall-through chain are
    **co-present or co-absent** on every row (218 both set, 74 both falsy, and NO one-sided cell), so
    this join can neither fill a blank nor blank a value. The 74 are real and stay on the fallback:
    60 carry a `skill_report` with no `call` (combination-and-vulnerability, literature-context,
    translational-readiness, target-intrinsic, surface-modality-fit) and 14 carry no `skill_report`
    at all.

    The point of reading the spine anyway is that a future skill which passes a different token to
    `build_skill_report(verdict=…)` than it puts on `headline_block.verdict.call` now cannot silently
    fork these two surfaces — before this join, nothing joined them and nothing would have noticed.
    """
    sr = (headline or {}).get("skill_report")
    if isinstance(sr, dict) and sr.get("call"):
        return sr["call"]
    return headline.get("presence_verdict") or hb_verdict.get("call") or headline.get("verdict")


def _question_signal(row: dict) -> dict:
    s = row.get("signal") or {}
    return {"tier": s.get("tier"), "polarity": _canon_polarity(s.get("polarity")), "label": s.get("label")}


def _question_confidence(row: dict) -> dict:
    cf = row.get("confidence") or {}
    return {"level": cf.get("tier"), "dots": cf.get("dots"), "label": cf.get("label")}


def _card_signal(cap: dict, sg_tier: Optional[str], fired: bool, is_liability: bool) -> dict:
    """A coarse per-card signal for the heatmap, on the canonical polarity vocabulary. `tier`
    (strength) reuses the card's subgroup-source tier when the framework bound it to a sub-group
    (else None — honest gap); `polarity` is the coarse read (liability class → killer / fired →
    supportive / else neutral) and `liability` carries the orthogonal boolean so a renderer can label
    a liability distinctly from a generic killer without re-deriving it from the class string;
    `label` = the card's class."""
    if is_liability:
        polarity = "killer"
    elif fired:
        polarity = "supportive"
    else:
        polarity = "neutral"
    return {"tier": sg_tier, "polarity": polarity, "label": cap.get("class"), "liability": bool(is_liability)}


_CONF_DOTS = {"high": 3, "moderate": 2, "low": 1, "standard": 2, "unknown": 0, "unmeasured": 0}
# Optional Evidence & Conclusion Ontology annotation for evidence_state (advisory; no ontology import,
# no RDF — see the schema's PROV/ECO/SEPIO $comment). Nullable; unknown states → None.
_ECO_BY_STATE = {"measured": "ECO:0000006", "comparator": "ECO:0000006", "inferred": "ECO:0000363"}


def _card_confidence(cap: dict, n: Optional[float]) -> dict:
    es = cap.get("evidence_state")
    level = "high" if es == "measured" else ("low" if es in ("comparator", "inferred") else "moderate")
    return {
        "level": level,
        "dots": _CONF_DOTS.get(level, 0),
        "evidence_state": es,
        "eco_id": _ECO_BY_STATE.get(es),
        "n": n,
    }


# ── card ↔ question join (measurement_type membership, with subtype-tier disambiguation) ────────────
def _ambiguous_measurement_types(caps: dict) -> set:
    """measurement_types carried by BOTH a subtype-tier and a non-subtype card in this package — for
    these the subtype flag disambiguates which question a card joins (whole-cohort vs by-subtype)."""
    by_mt_subtype, by_mt_whole = set(), set()
    for cap in caps.values():
        mt = cap.get("measurement_type")
        if not mt:
            continue
        (by_mt_subtype if cap.get("tier") == "subtype" else by_mt_whole).add(mt)
    return by_mt_subtype & by_mt_whole


def _card_question_ids(cap: dict, questions: list, ambiguous: set) -> list:
    """Question slugs this card belongs to: its measurement_type ∈ the question's measurement_types,
    with subtype-tier disambiguation for measurement_types shared by a whole-cohort + by-subtype pair."""
    mt = cap.get("measurement_type")
    is_subtype = cap.get("tier") == "subtype"
    out = []
    for q in questions:
        mts = q.get("measurement_types") or []
        if mt not in mts:
            continue
        if mt in ambiguous and bool(q.get("subtype", False)) != is_subtype:
            continue
        out.append(q["id"])
    return out


# ── citation id minting (stable, deterministic) ─────────────────────────────────────────────────────
_AUTHOR_YEAR = re.compile(r"^\s*([A-Za-z][A-Za-z'\-]+).*?((?:19|20)\d{2})")


def _citation_id(cite: dict, taken: set) -> str:
    label = str(cite.get("label") or "")
    m = _AUTHOR_YEAR.match(label)
    if m:
        base = (m.group(1) + m.group(2)).lower()
    elif cite.get("pmid"):
        base = f"pmid{cite['pmid']}"
    else:
        base = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "citation"
    cid = base
    i = 2
    while cid in taken:
        cid = f"{base}-{i}"
        i += 1
    taken.add(cid)
    return cid


# ── narrative anchor extraction (single-lens rationale cites card_id/rule_id in plain prose) ─────────
_ID_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+){2,}")


def _narrative_cites(text: str, card_ids: set, rule_ids: set) -> tuple:
    """Anchor a narrative to the package by exact card_id/rule_id substrings appearing in its prose
    (order-preserving dedup). Display-only: never invents an id not present in the package."""
    found_cards, found_rules = [], []
    for tok in _ID_TOKEN.findall(text or ""):
        if tok in card_ids and tok not in found_cards:
            found_cards.append(tok)
        if tok in rule_ids and tok not in found_rules:
            found_rules.append(tok)
    return found_cards, found_rules


# ── key_evidence promotion (the decisive-data-point substrate) ──────────────────────────────────────
from _skills_common.display_gloss import fill_placeholders  # noqa: E402
from _skills_common.evidence_salience import (  # noqa: E402
    SUBTYPE_SPECS,
    build_interpretation,
    round_keep_tiny,
    sig_round,
    spec_for,
)
from _skills_common.subtype_axis import (  # noqa: E402  SK#1518 shared axis-quality gate (#1623)
    SUBTYPE_DIFFERENTIAL_CLASSES,
    is_differential_axis,
)

_KE_R = 4
_KE_ROLE = {"INDICATION": "indication", "extreme_strongest": "strongest", "extreme_weakest": "weakest"}


def _kenum(v):
    # Same shared helper as the capsule's `_num`. This site destroys nothing TODAY — measured on 944 real
    # decisions, all 564 annihilated `key_evidence.effect` values reached it through the numeric_anchors
    # fallback (both implicated axes declare `effect_field: None`), so repairing the capsule repairs them.
    # It is hardened anyway because it is the identical one-line bug on the SAME numbers, and it goes live
    # the moment any axis pins an `effect_field` whose value can be tiny — a q-value used as the effect.
    return round_keep_tiny(v, _KE_R) if isinstance(v, float) else v


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _graded_restriction_class(summary: dict, restriction_class):
    """Gate the surfaced `restriction_class` on the axis-quality GRADE (#1623). `restriction_class`
    (the `subtype_stratification_class` family) is derived from the MEASURED strata alone, so a single
    measured-enriched stratum in an `exploratory` (or weaker) family yields a differential class while
    `subtype_axis_quality` says the axis is not powered — a combination the downstream narrator/synthesis
    consumers (`subtype:{restriction_class}`) would present as a real cross-subtype differential. When the
    class asserts a differential but the axis is not `powered` (is_differential_axis False), drop it to
    None so it is omitted rather than read as a differential — matching the two reader consumers that
    already honor the grade (presence_cardboard_figure, presence_question_table). Any non-differential
    class (e.g. pan_subtype_uniform) or a powered axis is passed through unchanged. Verdict-inert;
    key_evidence feeds no gate."""
    if restriction_class in SUBTYPE_DIFFERENTIAL_CLASSES and not is_differential_axis(
        (summary or {}).get("subtype_axis_quality")
    ):
        return None
    return restriction_class


def _build_subtype_axis(summary: dict) -> Optional[dict]:
    """Project the subtype-stratified evidence (§3.16, F8) into key_evidence.subtype_axis. Null when the
    card carries no subtype axis (--subtypes off) so standard-run graphs stay byte-stable. Fail-soft.
    The surfaced `restriction_class` is grade-gated (#1623): a differential class on a not-`powered` axis
    is dropped so the narrative never presents a hypothesis-grade axis as a real cross-subtype differential."""
    s = summary or {}
    # (a) multi-axis omnibus (presence): subtype_omnibus_by_axis, one row per molecular axis
    axes = s.get("subtype_omnibus_by_axis")
    if isinstance(axes, list) and axes and all(isinstance(a, dict) for a in axes):
        sp = SUBTYPE_SPECS["subtype_omnibus_by_axis"]
        driving = s.get(sp["driving_axis_field"])
        drow = next((a for a in axes if a.get(sp["axis_field"]) == driving), None) or axes[0]
        out = {
            "driving_axis": driving or drow.get(sp["axis_field"]),
            "restriction_class": _graded_restriction_class(s, s.get(sp["restriction_class_field"])),
        }
        if _is_num(drow.get(sp["omnibus_field"])):
            out["omnibus"] = {"stat": sp["omnibus_field"], "value": sig_round(drow[sp["omnibus_field"]])}
        which = drow.get(sp["which_separate_field"])
        if isinstance(which, dict):
            out["which_separate"] = {"highest": which.get("highest"), "lowest": which.get("lowest")}
        subs = s.get(sp["subgroup_array"])
        if isinstance(subs, list):
            top = [
                {
                    "label": r.get(sp["subgroup_label_field"]),
                    "value": _kenum(r.get(sp["subgroup_effect_field"])),
                    "n": r.get(sp["subgroup_n_field"]),
                }
                for r in subs
                if isinstance(r, dict) and _is_num(r.get(sp["subgroup_effect_field"]))
            ][:3]
            if top:
                out["top_subtypes"] = top
        return out
    # (b) per_subgroup_metrics dependency split (median_chronos per subtype)
    subs = s.get("per_subgroup_metrics")
    if isinstance(subs, list) and subs and any(isinstance(r, dict) and _is_num(r.get("median_chronos")) for r in subs):
        sp = SUBTYPE_SPECS["per_subgroup_metrics"]
        rows = sorted(
            (r for r in subs if isinstance(r, dict) and _is_num(r.get("median_chronos"))),
            key=lambda r: r.get("median_chronos"),
        )
        top = [
            {"label": r.get("stratum"), "value": _kenum(r.get("median_chronos")), "n": r.get("subgroup_n")}
            for r in rows
        ][:3]
        return (
            {
                "driving_axis": None,
                "restriction_class": _graded_restriction_class(s, s.get(sp["restriction_class_field"])),
                "top_subtypes": top,
            }
            if top
            else None
        )
    # (c) per_axis_association survival
    paa = s.get("per_axis_association")
    if isinstance(paa, list) and paa and all(isinstance(a, dict) for a in paa):
        driving = next(
            (a for a in paa if str(a.get("subtype_survival_association_class") or "").startswith("subtype_stratifies")),
            None,
        )
        row = driving or paa[0]
        out = {"driving_axis": row.get("axis"), "restriction_class": s.get("subtype_survival_association_class")}
        if _is_num(row.get("logrank_p")):
            out["omnibus"] = {"stat": "logrank_p", "value": sig_round(row["logrank_p"])}
        return out
    return None


def _build_key_evidence(cap: dict, summary: dict, indication: Optional[str] = None) -> Optional[dict]:
    """Promote the DECISIVE data points behind a card into a bounded, typed object, from the capsule's
    already-computed shapes (top_k_strata w/ q, n_basis, categorical_anchors, conflict_pairs) + the
    per-measurement_type salience spec's pinned significance/omnibus scalars read from the card summary.
    ADDITIVE + DISPLAY-ONLY: feeds no rule/gate. None when nothing salient is available."""
    cap = cap or {}
    summary = summary or {}
    spec = spec_for(cap.get("measurement_type")) or {}
    direction = spec.get("direction")
    tks = cap.get("top_k_strata") or []
    ind_row = next((r for r in tks if r.get("role") == "INDICATION"), None)
    strong_row = next((r for r in tks if r.get("role") == "extreme_strongest"), None)
    eff_row = ind_row or strong_row

    # effect: indication/strongest stratum > scalar effect_field > first numeric anchor
    effect = None
    n = None
    if eff_row is not None:
        effect = {"metric": eff_row.get("metric"), "value": eff_row.get("value"), "direction": direction}
        n = eff_row.get("n")
    elif spec.get("effect_field") and _is_num(summary.get(spec["effect_field"])):
        effect = {
            "metric": spec["effect_field"],
            "value": _kenum(summary[spec["effect_field"]]),
            "direction": direction,
        }
    else:
        na = cap.get("numeric_anchors") or []
        if na:
            effect = {"metric": na[0].get("metric"), "value": na[0].get("value"), "direction": direction}

    # significance: the effect stratum's q > a scalar significance_field
    significance = None
    if eff_row is not None and eff_row.get("q") is not None:
        significance = {"stat": spec.get("significance_field") or "q_value", "value": eff_row.get("q")}
    elif spec.get("significance_field") and _is_num(summary.get(spec["significance_field"])):
        significance = {"stat": spec["significance_field"], "value": sig_round(summary[spec["significance_field"]])}

    # omnibus: an explicitly-pinned cross-stratum test (fails the anchor-hint heuristic)
    omnibus = None
    of = spec.get("omnibus_field")
    if of and _is_num(summary.get(of)):
        omnibus = {"stat": of, "value": sig_round(summary[of])}

    # n fallback: pinned n_field > first NUMERIC n_basis value (skip booleans like
    # depmap_curated_common_essential / is_tce_viable that also live in n_basis)
    if not _is_num(n):
        n = None
        nf = spec.get("n_field")
        if nf and _is_num(summary.get(nf)):
            n = summary[nf]
        elif isinstance(cap.get("n_basis"), dict):
            # only a COUNT-like n_basis entry (n_* / *_n / *count*) — n_basis also holds decisive
            # medians/z-scores/effects, and grabbing the first numeric mis-read those as the sample
            # size (e.g. syn_z_score 0.39, median_chronos -1.18 surfacing as "n").
            n = next(
                (
                    v
                    for k, v in cap["n_basis"].items()
                    if _is_num(v) and (str(k).startswith("n_") or str(k).endswith("_n") or "count" in str(k).lower())
                ),
                None,
            )

    # top_strata: reshape the capsule rows to the schema shape (label/role/value/n/q)
    top_strata = []
    for r in tks:
        row = {
            "label": r.get("stratum"),
            "role": _KE_ROLE.get(r.get("role"), r.get("role")),
            "value": r.get("value"),
            "n": r.get("n"),
        }
        if r.get("q") is not None:
            row["q"] = r.get("q")
        top_strata.append(row)

    # categorical: the spec's decisive labels present in summary, else the capsule's categorical_anchors
    categorical = [
        {"field": f, "value": summary[f]}
        for f in (spec.get("categorical") or [])
        if f in summary and summary.get(f) is not None
    ]
    if not categorical:
        categorical = [
            {"field": a.get("field"), "value": a.get("value")} for a in (cap.get("categorical_anchors") or [])
        ]

    # conflict: the first sibling-disagreement pair
    conflict = None
    cps = cap.get("conflict_pairs") or []
    if cps and isinstance(cps[0], dict):
        cp = cps[0]
        conflict = {
            "this_class": cp.get("this_class"),
            "other": [
                {"card": o.get("card"), "class": o.get("class"), "tier": o.get("tier")}
                for o in (cp.get("other_sources") or [])
            ],
        }

    subtype_axis = _build_subtype_axis(summary)

    # typed reference-frame ruler(s) — the per-type SALIENCE_SPEC reference_frame projected onto the summary
    # + capsule (cut single-sourced from the card thresholds:, resolved inside the salience layer so THIS
    # builder does no card.yaml read). [] when the type has no reference_frame or the value is absent.
    interpretation = build_interpretation(cap, summary, spec, cap.get("card_id"), indication=indication)

    ke = {}
    if interpretation:
        ke["interpretation"] = interpretation
    if effect:
        ke["effect"] = effect
    if _is_num(n):
        ke["n"] = n
    if significance:
        ke["significance"] = significance
    if omnibus:
        ke["omnibus"] = omnibus
    if top_strata:
        ke["top_strata"] = top_strata
    if categorical:
        ke["categorical"] = categorical
    if isinstance(cap.get("n_basis"), dict) and cap.get("n_basis"):
        ke["n_basis"] = cap["n_basis"]
    if conflict:
        ke["conflict"] = conflict
    if subtype_axis:
        ke["subtype_axis"] = subtype_axis
    return ke or None


# Measurement layers that fire rules but are NEVER selected by a presence-verdict ladder
# (tumor-presence run.py `_MEASUREMENT_RANK` / `_rank_verdict`): their fired rules are
# corroboration / proxy-reliability signals (e.g. `rna_as_biomarker` — is RNA an adequate proxy for
# protein), off the presence axis, so a card in one of these layers moves no verdict and is
# `display_only` even though it fired ≥1 rule. Keyed by capsule `measurement_type`; unique to the two
# RNA↔protein-concordance cards (cellline-/rna-protein-concordance-tumor). See #1526 F1.
_DISPLAY_ONLY_MEASUREMENT_TYPES = frozenset({"rna_protein_concordance"})


# ── the builder ──────────────────────────────────────────────────────────────────────────────────
def build_evidence_graph(decision: dict, questions: Optional[list] = None) -> dict:
    """Assemble decision.headline.evidence_graph as a pure projection/JOIN over `decision`.

    `questions` is the canonical registry (load_questions); when None or empty the graph still emits
    with best-effort (null) question anchoring. Deterministic ordering throughout (questions by seq;
    cards in decision.cards order; sorted dedup for datasets/citations) so the emitted JSON is
    byte-stable.
    """
    decision = decision or {}
    h = decision.get("headline") or {}
    questions = questions or []
    # Bound once, up here, because they are needed BOTH by the emitted request echo at the bottom and by
    # the question-text interpolation in the middle. They were only ever read at the bottom, which is how
    # the templates below went un-substituted while the values sat in the same return dict.
    g_target, g_indication = decision.get("target"), decision.get("indication")
    caps = ((h.get("evidence_capsules") or {}).get("capsules")) or {}
    cards_list = decision.get("cards") or []
    fired_rules = decision.get("fired_rules") or []

    # verdict spine (read-only)
    hb = h.get("headline_block") or {}
    hb_verdict = hb.get("verdict") or {}
    driving_rule_id = h.get("driving_rule_id") or hb_verdict.get("driving_rule_id")
    verdict_call = _verdict_call(h, hb_verdict)

    fired_by_card: dict = {}
    driving_card_id = None
    for r in fired_rules:
        cid, rid = r.get("card_id"), r.get("rule_id")
        if cid:
            fired_by_card.setdefault(cid, []).append(r)
        if rid and rid == driving_rule_id:
            driving_card_id = cid
    # `verdict_bearing` means "moved the verdict" (was selected by a ladder), NOT merely "fired ≥1
    # rule": a card whose measurement layer has no presence-verdict ladder fires only display /
    # proxy-reliability rules and stays display_only. See _DISPLAY_ONLY_MEASUREMENT_TYPES / #1526 F1.
    verdict_bearing_cards = {
        cid
        for cid in fired_by_card
        if (caps.get(cid) or {}).get("measurement_type") not in _DISPLAY_ONLY_MEASUREMENT_TYPES
    }

    # per-card (strength tier, sample-size n) from the framework's own subgroup-source binding — the
    # authoritative per-card corroboration read (only for cards bound to a sub-group; else None).
    sg_by_card: dict = {}
    for _blk in (h.get("subgroup_signals") or {}).values():
        if not isinstance(_blk, dict):
            continue
        for _s in _blk.get("sources") or []:
            if isinstance(_s, dict) and _s.get("card") and _s.get("card") not in sg_by_card:
                sg_by_card[_s["card"]] = (_s.get("tier"), _s.get("n"))

    # ordered questions (by seq); keep the registry rows as-is for anchoring
    questions = sorted(questions, key=lambda q: q.get("seq", 1_000_000))
    ambiguous = _ambiguous_measurement_types(caps)

    # question_table rows keyed by legacy_id (Q1..Q7), for signal/confidence/prose (never mutated)
    qt_rows = {r.get("id"): r for r in (h.get("question_table") or []) if isinstance(r, dict)}

    # ── cards[] (all cards, both edge directions) ──
    card_nodes, dataset_ids_seen = [], []
    card_qids: dict = {}
    for c in cards_list:
        cid = c.get("card_id")
        cap = caps.get(cid, {}) or {}
        rules_for = fired_by_card.get(cid, [])
        rule_ids = [r.get("rule_id") for r in rules_for if r.get("rule_id")]
        is_vb = cid in verdict_bearing_cards
        is_liability = (
            str(cap.get("class") or "").upper().endswith("LIABILITY")
            or "liability" in str(cap.get("class") or "").lower()
        )
        qids = _card_question_ids(cap, questions, ambiguous) if cap else []
        card_qids[cid] = qids
        # class field/value — from the fired rule (verdict-bearing) else the first categorical anchor.
        if rules_for:
            class_field, class_value = rules_for[0].get("field"), rules_for[0].get("value")
        else:
            anchors = cap.get("categorical_anchors") or []
            first = anchors[0] if anchors else {}
            class_field, class_value = (
                first.get("field"),
                (cap.get("class") if cap.get("class") is not None else first.get("value")),
            )
        dataset_ids = list(c.get("input_manifest_ids") or [])
        for d in dataset_ids:
            if d not in dataset_ids_seen:
                dataset_ids_seen.append(d)
        numeric = cap.get("numeric_anchors") or []
        sg_tier, sg_n = sg_by_card.get(cid, (None, None))
        chain = {
            "dataset_ids": dataset_ids,
            "data": [{"field": a.get("metric"), "value": a.get("value")} for a in numeric[:4]],
            "rule_id": (rule_ids[0] if rule_ids else None),
            "contributes_to_verdict": is_vb,
            "is_driving": cid == driving_card_id,
        }
        key_fields = {a.get("metric"): a.get("value") for a in numeric if a.get("metric")}
        key_evidence = _build_key_evidence(cap, c.get("summary") or {}, g_indication)
        card_nodes.append(
            {
                "id": cid,
                "measurement_type": cap.get("measurement_type"),
                "tier": cap.get("tier"),
                "role": "verdict_bearing" if is_vb else "display_only",
                "question_ids": qids,
                "axis_id": next((q.get("axis_id") for q in questions if q["id"] in qids and q.get("axis_id")), None),
                "signal": _card_signal(cap, sg_tier, is_vb, is_liability),
                "confidence": _card_confidence(cap, sg_n),
                "class": {"field": class_field, "value": class_value},
                "dataset_ids": dataset_ids,
                "rule_ids": rule_ids,
                "chain": chain,
                "key_fields": key_fields,
                "key_evidence": key_evidence,
            }
        )

    # ── questions[] (both edge directions; literature axis crosswalk fed later) ──
    q_nodes = []
    for q in questions:
        qid = q["id"]
        # cards whose question_ids include this question (inverse of the card→question join)
        q_card_ids = [c["id"] for c in card_nodes if qid in c["question_ids"]]
        q_rule_ids = []
        for cnode in card_nodes:
            if cnode["id"] in q_card_ids:
                for rid in cnode["rule_ids"]:
                    if rid not in q_rule_ids:
                        q_rule_ids.append(rid)
        row = qt_rows.get(q.get("legacy_id"), {})
        evidence_refs = []
        for cnode in card_nodes:
            if cnode["id"] in q_card_ids and cnode["class"].get("value") is not None:
                evidence_refs.append(
                    {
                        "card_id": cnode["id"],
                        "field": cnode["class"].get("field"),
                        "value": cnode["class"].get("value"),
                        "label": f"{cnode['id']} {cnode['class'].get('value')}",
                    }
                )
        q_nodes.append(
            {
                "id": qid,
                "seq": q.get("seq"),
                # Interpolate the request into the authored template. The registry text is a TEMPLATE
                # (`{target.symbol}` / `{indication.label}`); passing it through raw shipped the literal
                # placeholder to every consumer of the graph. `target`/`indication` are the same values
                # this function already emits at the top of its own return dict.
                "text": fill_placeholders(q.get("text"), g_target, g_indication) or row.get("question"),
                "axis_id": q.get("axis_id"),
                "role": q.get("role"),
                "signal": _question_signal(row),
                "confidence": _question_confidence(row),
                "card_ids": q_card_ids,
                "rule_ids": q_rule_ids,
                "literature_axis_ids": [],  # filled by the literature crosswalk below
                "evidence_refs": evidence_refs,
                "prose": {"primary": row.get("primary"), "support": row.get("support")},
            }
        )
    q_by_id = {q["id"]: q for q in q_nodes}

    # ── rules[] ──
    rule_nodes = []
    for r in fired_rules:
        rid = r.get("rule_id")
        rule_nodes.append(
            {
                "id": rid,
                "card_id": r.get("card_id"),
                "field": r.get("field"),
                "value": r.get("value"),
                "dominant": bool(r.get("dominant")),
                "is_driving": rid == driving_rule_id,
                "rationale": r.get("rationale_summary"),
            }
        )

    # ── datasets[] (dedup, sorted for byte-stability) ──
    dataset_nodes = [{"id": d, "s3_uri": None, "license": None} for d in sorted(set(dataset_ids_seen))]

    # ── literature + citations (Phase 3) ──
    literature, citation_nodes = _build_literature(decision, questions, q_by_id)

    # ── narrative (Phase 4) ── pass the citation NODES (id + pmid, for PMID:-ref normalization) + the
    # registry legacy_id→slug map (so a bullet's positional `Q3` ref resolves to its semantic question id).
    narrative = _build_narrative(
        decision,
        card_nodes,
        rule_nodes,
        q_nodes,
        citation_nodes=citation_nodes,
        legacy_to_qid={q.get("legacy_id"): q["id"] for q in questions if q.get("legacy_id") and q.get("id")},
    )

    # ── verdict node ──
    conf = hb.get("confidence") or {}
    tension = hb.get("top_tension") or {}
    tension_cards = [
        c
        for c in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+){2,}", str(tension.get("text") or ""))
        if c in {cn["id"] for cn in card_nodes}
    ]
    verdict_node = {
        "id": verdict_call,
        "call": hb_verdict.get("phrase") or hb.get("headline_text") or verdict_call,
        "polarity": _verdict_polarity(h, hb_verdict),
        "driving_rule_id": driving_rule_id,
        "confidence": {"level": conf.get("level"), "coverage": conf.get("coverage")},
        "top_tension": (
            {"text": tension.get("text"), "severity": tension.get("severity"), "source_card_ids": tension_cards}
            if tension
            else None
        ),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "skill": decision.get("skill"),
        "target": g_target,
        "indication": g_indication,
        "verdict": verdict_node,
        "questions": q_nodes,
        "cards": card_nodes,
        "rules": rule_nodes,
        "datasets": dataset_nodes,
        "literature": literature,
        "citations": citation_nodes,
        "narrative": narrative,
    }


def _build_literature(decision: dict, questions: list, q_by_id: dict) -> tuple:
    """Project decision.literature_synthesis into {axes[], blind_spots[], overall_consistency,
    key_divergence} with the axis→question crosswalk + hoisted top-level citations[]. Fail-soft:
    absent/errored/skipped → ({}, [])."""
    lit = decision.get("literature_synthesis")
    if not isinstance(lit, dict) or any(k in lit for k in ("_literature_error", "_literature_skipped")):
        return {}, []

    # crosswalk: axis_id → question_ids (verdict/display questions on that axis, NOT corroboration ones)
    axis_to_questions: dict = {}
    for q in questions:
        ax = q.get("axis_id")
        if ax and q.get("role") != "corroboration":
            axis_to_questions.setdefault(ax, []).append(q["id"])

    axes_raw = _unwrap(lit.get("axes")) or []
    blind_raw = _unwrap(lit.get("blind_spots")) or []
    taken: set = set()

    def _cite_ids(cite_list) -> list:
        ids = []
        for c in cite_list or []:
            if not isinstance(c, dict):
                continue
            ids.append((c, _citation_id(c, taken)))
        return ids

    citation_nodes, _seen_pairs = [], {}
    axes_out = []
    for ax in axes_raw:
        if not isinstance(ax, dict):
            continue
        axis_id = ax.get("axis_key")
        cite_ids = []
        for cite, cid in _cite_ids(ax.get("citations")):
            citation_nodes.append(
                {
                    "id": cid,
                    "label": cite.get("label"),
                    "pmid": cite.get("pmid"),
                    "doi": cite.get("doi"),
                    "verified": bool(cite.get("verified")),
                }
            )
            cite_ids.append(cid)
        qids = list(axis_to_questions.get(axis_id, []))
        for qid in qids:
            if qid in q_by_id and axis_id not in q_by_id[qid]["literature_axis_ids"]:
                q_by_id[qid]["literature_axis_ids"].append(axis_id)
        axes_out.append(
            {
                "axis_id": axis_id,
                "question_ids": qids,
                "read": ax.get("literature_read"),
                "agreement_vs_omics": ax.get("agreement_vs_omics"),
                "confidence": ax.get("confidence"),
                "assertion": ax.get("assertion"),
                "citation_ids": cite_ids,
            }
        )

    blind_out = []
    for bs in blind_raw:
        if not isinstance(bs, dict):
            continue
        cite_ids = []
        for cite, cid in _cite_ids(bs.get("citations")):
            citation_nodes.append(
                {
                    "id": cid,
                    "label": cite.get("label"),
                    "pmid": cite.get("pmid"),
                    "doi": cite.get("doi"),
                    "verified": bool(cite.get("verified")),
                }
            )
            cite_ids.append(cid)
        blind_out.append(
            {"text": bs.get("signal"), "why_omics_blind": bs.get("why_omics_blind"), "citation_ids": cite_ids}
        )

    literature = {
        "axes": axes_out,
        "blind_spots": blind_out,
        "overall_consistency": _unwrap(lit.get("overall_consistency")),
        "key_divergence": _unwrap(lit.get("key_divergence")),
    }
    return literature, citation_nodes


def _build_narrative(
    decision: dict,
    card_nodes: list,
    rule_nodes: list,
    q_nodes: list,
    citation_nodes: Optional[list] = None,
    legacy_to_qid: Optional[dict] = None,
) -> dict:
    """Project decision.llm_synthesis into an anchored narrative. Fail-soft: absent/error stub → {}.
    Stage 2: leads with `exec_bullets`, each anchored to real card/question/citation ids. The narrator
    cites in the VOCABULARY the prompt showed it — a citation as `PMID:40855221`, a question by its
    positional `Q3` — so we NORMALIZE those to the graph node ids (a citation node's `pmid`; the
    registry `legacy_id`→slug map) before filtering. Refs that still don't resolve are dropped, so
    referential integrity always holds; `rationale` carries the demoted verbose prose."""
    syn = decision.get("llm_synthesis")
    if not isinstance(syn, dict) or any(k in syn for k in ("_synthesis_error", "_synthesis_skipped")):
        return {}
    card_ids = {c["id"] for c in card_nodes}
    rule_ids = {r["id"] for r in rule_nodes if r["id"]}
    q_ids = {q["id"] for q in q_nodes}
    legacy_to_qid = legacy_to_qid or {}
    cite_ids = {c["id"] for c in (citation_nodes or []) if c.get("id")}
    # pmid → citation node id (the narrator emits `PMID:40855221`; the node id is minted from author-year
    # or `pmid<n>`), so map by the node's pmid field, normalizing the `PMID:`/`pmid:` prefix + any colon.
    pmid_to_cid = {str(c.get("pmid")): c["id"] for c in (citation_nodes or []) if c.get("pmid") and c.get("id")}

    def _norm_pmid(ref):
        return re.sub(r"(?i)^pmid[:\s]*", "", str(ref)).strip()

    def _resolve_qid(ref):
        return ref if ref in q_ids else legacy_to_qid.get(ref)

    def _resolve_cid(ref):
        if ref in cite_ids:
            return ref
        return pmid_to_cid.get(_norm_pmid(ref))

    # focused llm_synthesis stamps each field as {value,_source:"llm_synthesized",...}; unwrap so the
    # graph carries plain scalars (mirrors _build_literature, which already unwraps its axes).
    text = " ".join(
        str(_unwrap(syn.get(k)) or "") for k in ("rationale", "key_caveat", "context_read", "key_signals_summary")
    )
    cited_cards, cited_rules = _narrative_cites(text, card_ids, rule_ids)
    cited_qids = [q["id"] for q in q_nodes if set(q["card_ids"]) & set(cited_cards)]

    def _dedup(seq):
        out = []
        for x in seq:
            if x and x not in out:
                out.append(x)
        return out

    # exec_bullets (PRIMARY): unwrap + anchor each bullet's cites to REAL ids (normalize pmid/legacy refs,
    # then drop any still-unresolved id so the referential invariant holds); canonicalize polarity.
    exec_bullets = []
    for b in _unwrap(syn.get("exec_bullets")) or []:
        if not isinstance(b, dict):
            continue
        bc = b.get("cites") or {}
        exec_bullets.append(
            {
                "text": _unwrap(b.get("text")),
                "polarity": _canon_polarity(_unwrap(b.get("polarity"))),
                "cites": {
                    "card_ids": _dedup(i for i in (bc.get("card_ids") or []) if i in card_ids),
                    "question_ids": _dedup(_resolve_qid(i) for i in (bc.get("question_ids") or [])),
                    "citation_ids": _dedup(_resolve_cid(i) for i in (bc.get("citation_ids") or [])),
                },
            }
        )
    out = {
        "relevance": _unwrap(syn.get("relevance")) or _unwrap(syn.get("context_read")),
        "rationale": _unwrap(syn.get("rationale")) or _unwrap(syn.get("key_signals_summary")),
        "confidence_qualifier": _unwrap(syn.get("confidence_qualifier")),
        "key_caveat": _unwrap(syn.get("key_caveat")),
        "cites": {"question_ids": cited_qids, "card_ids": cited_cards, "rule_ids": cited_rules},
    }
    if exec_bullets:
        out["exec_bullets"] = exec_bullets
    return out


# ── governance: referential integrity + schema validation + fail-soft attach seam ──────────────────
def _referential_integrity_errors(graph: dict) -> list:
    """Every id referenced by an EDGE must resolve to a node in the SAME package (the invariant JSON
    Schema cannot express). MIRRORS target-contracts validators/validate_evidence_graph.py
    referential_integrity_errors — keep the two in lockstep. Pure; no I/O."""
    errs: list = []
    g = graph or {}
    card_ids = {c.get("id") for c in (g.get("cards") or []) if isinstance(c, dict)}
    rule_ids = {r.get("id") for r in (g.get("rules") or []) if isinstance(r, dict)}
    q_ids = {q.get("id") for q in (g.get("questions") or []) if isinstance(q, dict)}
    ds_ids = {d.get("id") for d in (g.get("datasets") or []) if isinstance(d, dict)}
    cite_ids = {c.get("id") for c in (g.get("citations") or []) if isinstance(c, dict)}
    axis_ids = {a.get("axis_id") for a in ((g.get("literature") or {}).get("axes") or []) if isinstance(a, dict)}

    def _chk(ids, universe, where):
        for i in ids or []:
            if i is not None and i not in universe:
                errs.append(f"REFERENTIAL [{where}]: id '{i}' does not resolve to a node")

    for q in g.get("questions") or []:
        if not isinstance(q, dict):
            continue
        _chk(q.get("card_ids"), card_ids, f"question[{q.get('id')}].card_ids")
        _chk(q.get("rule_ids"), rule_ids, f"question[{q.get('id')}].rule_ids")
        _chk(q.get("literature_axis_ids"), axis_ids, f"question[{q.get('id')}].literature_axis_ids")
        for ref in q.get("evidence_refs") or []:
            if isinstance(ref, dict):
                _chk([ref.get("card_id")], card_ids, f"question[{q.get('id')}].evidence_refs.card_id")
    for c in g.get("cards") or []:
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        _chk(c.get("question_ids"), q_ids, f"card[{cid}].question_ids")
        _chk(c.get("dataset_ids"), ds_ids, f"card[{cid}].dataset_ids")
        _chk(c.get("rule_ids"), rule_ids, f"card[{cid}].rule_ids")
        chain = c.get("chain") or {}
        _chk(chain.get("dataset_ids"), ds_ids, f"card[{cid}].chain.dataset_ids")
        if chain.get("rule_id") is not None:
            _chk([chain.get("rule_id")], rule_ids, f"card[{cid}].chain.rule_id")
        conflict = (c.get("key_evidence") or {}).get("conflict") or {}
        for o in conflict.get("other") or []:
            if isinstance(o, dict) and o.get("card") is not None:
                _chk([o.get("card")], card_ids, f"card[{cid}].key_evidence.conflict.other.card")
    for r in g.get("rules") or []:
        if isinstance(r, dict) and r.get("card_id") is not None:
            _chk([r.get("card_id")], card_ids, f"rule[{r.get('id')}].card_id")
    lit = g.get("literature") or {}
    for ax in lit.get("axes") or []:
        if isinstance(ax, dict):
            _chk(ax.get("question_ids"), q_ids, f"literature.axes[{ax.get('axis_id')}].question_ids")
            _chk(ax.get("citation_ids"), cite_ids, f"literature.axes[{ax.get('axis_id')}].citation_ids")
    for bs in lit.get("blind_spots") or []:
        if isinstance(bs, dict):
            _chk(bs.get("citation_ids"), cite_ids, "literature.blind_spots.citation_ids")
    verdict = g.get("verdict") or {}
    if verdict.get("driving_rule_id") is not None:
        _chk([verdict.get("driving_rule_id")], rule_ids, "verdict.driving_rule_id")
    tension = verdict.get("top_tension") or {}
    if isinstance(tension, dict):
        _chk(tension.get("source_card_ids"), card_ids, "verdict.top_tension.source_card_ids")
    narrative = g.get("narrative") or {}
    cite_node_ids = {c.get("id") for c in (g.get("citations") or []) if isinstance(c, dict)}
    cites = narrative.get("cites") or {}
    _chk(cites.get("question_ids"), q_ids, "narrative.cites.question_ids")
    _chk(cites.get("card_ids"), card_ids, "narrative.cites.card_ids")
    _chk(cites.get("rule_ids"), rule_ids, "narrative.cites.rule_ids")
    for i, b in enumerate(narrative.get("exec_bullets") or []):
        bc = (b or {}).get("cites") or {} if isinstance(b, dict) else {}
        _chk(bc.get("question_ids"), q_ids, f"narrative.exec_bullets[{i}].cites.question_ids")
        _chk(bc.get("card_ids"), card_ids, f"narrative.exec_bullets[{i}].cites.card_ids")
        _chk(bc.get("citation_ids"), cite_node_ids, f"narrative.exec_bullets[{i}].cites.citation_ids")
    return errs


@functools.lru_cache(maxsize=None)
def _load_schema(contracts_repo: Optional[str] = None):
    """Load evidence_graph.schema.json from target-contracts (best-effort; None if unavailable)."""
    try:
        import json

        if contracts_repo:
            base = Path(contracts_repo)
        else:
            from _skills_common.paths import DEFAULT_CONTRACTS_REPO

            base = Path(DEFAULT_CONTRACTS_REPO)
        p = base / "schemas" / "evidence_graph.schema.json"
        return json.loads(p.read_text()) if p.exists() else None
    except Exception:  # noqa: BLE001
        return None


def assert_evidence_graph_valid(
    graph: dict, schema: Optional[dict] = None, contracts_repo: Optional[str] = None
) -> bool:
    """Raise AssertionError unless `graph` is schema-valid AND referentially intact. The single shared
    check the per-skill evidence_graph tests call (replacing 14 copy-pasted referential-integrity bodies).
    Schema validation is best-effort — skipped (referential-only) when jsonschema or the contracts schema
    is unavailable (isolated CI), so the referential invariant is always enforced."""
    errs = _referential_integrity_errors(graph)
    try:
        from jsonschema import Draft202012Validator

        sch = schema if schema is not None else _load_schema(contracts_repo)
        # Lockstep guard: only schema-validate against a schema that DECLARES key_evidence (the Stage-1
        # contracts schema). Against the pre-Stage-1 trunk schema (additionalProperties:false, no
        # key_evidence) we'd otherwise false-reject the additive field during the cross-repo landing
        # window — so fall back to referential-only until the schema catches up.
        if sch is not None and "key_evidence" in ((sch.get("$defs", {}).get("card", {}).get("properties", {})) or {}):
            for e in Draft202012Validator(sch).iter_errors(graph):
                path = ".".join(str(p) for p in e.absolute_path) or "<root>"
                errs.append(f"STRUCTURAL [{path}]: {e.message}")
    except Exception:  # noqa: BLE001 — jsonschema/schema absent → referential-only
        pass
    assert not errs, "evidence_graph invalid:\n  " + "\n  ".join(errs)
    return True


def attach_evidence_graph(decision: dict, skill_dir) -> dict:
    """Build decision.headline.evidence_graph and attach it by reference. The SINGLE seam called from the
    shared dispatcher (run_wired_skill — every wired skill, incl. genomic-alteration-profile since it
    migrated off its hand-rolled main) and target-profile's tp_fanout decision-reconstruction — so both
    paths get an identical, governed graph. Fail-soft: on any fault
    (or a referential-integrity error) it logs to headline['_enrichment_errors'] and NEVER raises, leaving
    the verdict spine untouched. Byte-stable in the happy path (no error key added)."""
    try:
        h = decision.get("headline")
        if not isinstance(h, dict):
            return decision
        graph = build_evidence_graph(decision, questions=load_questions(skill_dir))
        errs = _referential_integrity_errors(graph)
        if errs:
            # _enrichment_errors is the codebase's stage-keyed DICT convention (headline_block, etc.)
            h.setdefault("_enrichment_errors", {})["evidence_graph"] = errs[:10]
        h["evidence_graph"] = graph
    except Exception as e:  # noqa: BLE001 — verdict-inert projection; never break the spine
        try:
            decision["headline"].setdefault("_enrichment_errors", {})["evidence_graph"] = f"{type(e).__name__}: {e}"
        except Exception:
            pass
    return decision


__all__ = [
    "build_evidence_graph",
    "attach_evidence_graph",
    "assert_evidence_graph_valid",
    "load_questions",
    "SCHEMA_VERSION",
]
