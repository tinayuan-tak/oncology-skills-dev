"""Hierarchy-driven sub-group derivation (signals-first spec v0.1).

DERIVES per-sub-group {signal, confidence, sources} for a skill from its question_hierarchy.yaml + the
resolved cards — replacing hand-wired card-ids. Sources bind by `measurement_type` (× entity_grain: a
`tier: subtype` card is a CONDITIONER, not a whole-cohort source). Confidence = agreement × sample-size
over the sources, capped by conflict — NOT weakest-link. Generic + reusable fleet-wide: a skill supplies
a per-measurement_type reader spec; this module does the binding + aggregation.

Verdict-INERT: a one-way projection over resolved cards; never feeds a verdict/resolver. Best-effort —
if target-contracts is unavailable (no measurement_type lookup), returns {} (spine unaffected).
"""

from __future__ import annotations

import functools
import re
from typing import Callable

from _skills_common.paths import target_contracts_root

_CT = target_contracts_root()
# The PRESENCE ordinal. Every member is a MEASURED read of how much signal there is.
_TIERV = {"strong": 3, "moderate": 2, "weak": 1, "absent": 0}

# ── THE ABSTENTION TOKEN ──────────────────────────────────────────────────────────────────────────
# `unmeasured` is deliberately NOT a fifth rung of _TIERV, because it is not a quantity of signal —
# it is the absence of a MEASUREMENT, which is off the presence axis entirely. Before this existed the
# only home for it was `absent` (explicitly in target-intrinsic's map, implicitly via default_classify
# everywhere else), which states "we looked and there is no signal" when the truth is "we could not
# look". That is the same error class as reading a withheld immune denominator as effector absence.
#
# Giving it a NUMBER instead would have been worse than leaving it as `absent`, because the ordinal is
# consumed as a distance as well as a rank: evidence_capsule._cross_card_conflicts flags
# `max(tier) - min(tier) >= 2` as a DISAGREEMENT between cards, so `unmeasured = -1` would have made a
# card that never measured "conflict" with any card reading `moderate` — fabricating contradictions out
# of coverage gaps. So the token is off-axis and every ordinal site below decides explicitly what to do
# with it: it never votes, it never ranks, and it never disagrees.
UNMEASURED = "unmeasured"
_TIERS = (*_TIERV, UNMEASURED)  # the full valid tier vocabulary: presence ordinal + the abstention

# Non-measurement tokens a card may carry. Matched by default_classify so an abstention degrades to
# UNMEASURED instead of to `absent`. Deliberately NARROW: only tokens that assert nothing was measured.
# `indeterminate` / `insufficient` are NOT here — those are measured-but-inconclusive reads, a different
# claim (the measurement happened and did not resolve), and collapsing them here would overstate coverage.
_UNMEASURED_TOKENS = (
    "data_unavailable",
    "not_measured",
    "unmeasured",
    "no_data",
    "not_assessed",
    "not_covered",
    "uninterpretable",
    "_unreliable",
)
_POW = ["low", "moderate", "high", "very high"]


def is_measured(tier: str) -> bool:
    """True when `tier` is a point on the PRESENCE ordinal (i.e. something was actually measured)."""
    return tier in _TIERV


@functools.lru_cache(maxsize=1024)
def _card_meta(card_id: str) -> tuple:
    """(measurement_type, tier) from the card contract; ('', '') if unresolvable. Cached."""
    p = _CT / "cards" / f"{card_id}.card.yaml"
    if not p.exists():
        return (None, None)
    try:
        import yaml

        y = yaml.safe_load(p.read_text()) or {}
    except Exception:  # noqa: BLE001 — verdict-inert projection; never break the spine
        return (None, None)
    return (y.get("measurement_type"), y.get("tier"))


@functools.lru_cache(maxsize=1024)
def _card_capsule_contract(card_id: str) -> tuple:
    """(primary_class, categorical_fields) from the card contract's optional `capsule:` block; (None, ())
    when the card declares none. This is the contracts-first source the evidence-capsule emitter consumes
    to (a) pick the verdict-driving *_class instead of the alphabetical-first heuristic and (b) surface the
    card's salient non-numeric fields — replacing the emitter's central config / hint guessing for any card
    that has declared. Cached; verdict-inert; never raises."""
    p = _CT / "cards" / f"{card_id}.card.yaml"
    if not p.exists():
        return (None, ())
    try:
        import yaml

        y = yaml.safe_load(p.read_text()) or {}
    except Exception:  # noqa: BLE001 — verdict-inert projection; never break the spine
        return (None, ())
    cap = y.get("capsule") or {}
    fields = cap.get("categorical_fields") or []
    return (cap.get("primary_class"), tuple(f for f in fields if isinstance(f, str)))


def default_classify(v) -> str:
    """Ordinal presence tier from a categorical card value (token heuristic; a skill may pass its own).

    Returns UNMEASURED for a non-measurement token, which is checked FIRST: a missing value used to fall
    through every presence test to `absent`, so "we could not measure" and "we measured no signal" were the
    same output. They are different claims and only one of them is evidence."""
    s = str(v or "").lower()
    if not s or any(t in s for t in _UNMEASURED_TOKENS):
        return UNMEASURED
    if any(t in s for t in ("broadly_high", "strong", "malignant_broadly", "top_1pct", "adequate", "__present__")):
        return "strong" if "__present__" not in s else "moderate"
    if any(t in s for t in ("broadly_moderate", "moderate", "multi", "partial", "lineage_restricted", "mid")):
        return "moderate"
    if any(t in s for t in ("broadly_low", "sparse", "single", "poor", "bottom_decile")):
        return "weak"
    return "absent"


def make_value_classifier(value_tiers: dict, default: Callable = default_classify) -> Callable:
    """Build an auditable per-skill classify(v) from an explicit {card_value: tier} map. The default
    token heuristic (default_classify) is lens-blind — it tags oncology signals it doesn't recognise
    (`concordant_dependent`, `broad_organoid_dependency`, `lineage_selective`, `triangulated_target_engaged`)
    as `absent`, i.e. flips a POSITIVE signal to a negative one. This lets a skill state the tier for its
    OWN card vocabulary explicitly (data, not code), with default_classify as the fallback for any value
    the map omits — so an unseen value degrades to the heuristic rather than silently to `absent`.
    `tier` must be one of strong/moderate/weak/absent/unmeasured (unknown tiers fall through to the
    default). A skill maps its own non-measurement tokens to `unmeasured` (see UNMEASURED above) so the
    abstention is stated in the skill's data rather than inferred from a token spelling."""
    norm = {str(k).lower(): v for k, v in (value_tiers or {}).items()}

    def classify(v) -> str:
        t = norm.get(str("" if v is None else v).lower())
        return t if t in _TIERS else default(v)

    return classify


def _nbucket(n) -> str:
    if not isinstance(n, (int, float)):
        return "low"
    return "very high" if n >= 1e5 else "high" if n >= 100 else "moderate" if n >= 20 else "low"


# DEFAULT heuristic reader — so fleet wiring needs no per-skill reader spec. Picks the primary signal
# field (a `*_class`, else a signal-keyword string field) + the sample-size field(s) from a card summary.
_SIGNAL_KEY = re.compile(
    r"(expression|dependency|abundance|selectivity|breadth|role|state|fit|density|"
    r"score|concordance|biomarker|activity|druggability|homogeneity|coverage)"
)
_N_KEY = re.compile(
    r"(^n_|_n$|_samples$|_cells$|_cells_total$|_donors$|_lines$|_evaluated$|subgroup_n|"
    r"_paired|cells_ran|n_cohorts|_ligands$|_patients$|_models$|_compounds$)"
)
# FEATURE / QUALITY counts that superficially match _N_KEY but are NOT a sample size — binding them as
# `n` mis-reads power (n_domains_low_plddt=6 as PDB coverage; n_admissible_strata=14 as patient count).
_N_DENY = re.compile(
    r"(_low_plddt$|_axes$|_strata$|_domains$|_classes$|_flags$|_bins$|_categories$|"
    r"_features$|_complexes$|_paralogs.*$|_partners$|_interactors$)"
)
# Prefer a genuine SAMPLE-SIZE field over any other n-match (the reader takes the FIRST present n, so
# ordering decides): patients/samples/lines/cells/donors/models/ligands rank ahead of generic counts.
_N_PRIORITY = (
    "patient",
    "sample",
    "cell_line",
    "_lines",
    "cell",
    "donor",
    "model",
    "screen",
    "ligand",
    "tumor",
    "compound",
    "pair",
    "cohort",
)


def _n_rank(k: str) -> int:
    kl = k.lower()
    return next((i for i, t in enumerate(_N_PRIORITY) if t in kl), len(_N_PRIORITY))


def _heuristic_reader(summary: dict) -> "dict | None":
    if not isinstance(summary, dict):
        return None
    cls = next((k for k in summary if k.endswith("_class") and isinstance(summary[k], str)), None) or next(
        (k for k in summary if _SIGNAL_KEY.search(k) and isinstance(summary[k], str)), None
    )
    if not cls:
        return None
    ns = [k for k in summary if _N_KEY.search(k) and isinstance(summary[k], (int, float)) and not _N_DENY.search(k)]
    ns = sorted(ns, key=lambda k: (_n_rank(k), k))  # true sample-size fields first; deterministic tie-break
    return {"class": cls, "n": ns, "label": cls.replace("_class", "").replace("_", " ")}


def derive_subgroups(
    hierarchy: dict, cards: list, reader_spec: "dict | None" = None, classify: Callable = default_classify
) -> dict:
    """{sub_group -> {signal, confidence, n_sources, n_agree, power, conflict, sources[]}}.

    reader_spec: {measurement_type: {"class": field, "n": [fields], "label": str,
                                     "present_synonyms": (...)}}  — how to read each source card.
    """
    type_sg = {}
    for sg in hierarchy.get("sub_groups", []):
        for q in sg.get("questions", []):
            for mt in q.get("measurement_types", []):
                type_sg.setdefault(mt, sg["id"])

    per: dict = {}
    _seen: set = set()  # (sub_group, _data_source, value) — dedup byte-identical sources
    for c in cards or []:
        cid = c.get("card_id")
        summ = c.get("summary") or {}
        mt, tier = _card_meta(cid)
        sg = type_sg.get(mt)
        if not sg or tier == "subtype":
            continue  # not a source for a whole-cohort sub-group signal
        if reader_spec and mt in reader_spec:
            spec = reader_spec[mt]  # explicit per-skill spec; a FALSY value = confidence-only card,
            if not spec:  # not a signal source (e.g. FR's paralog-buffering caveat) → skip
                continue
        else:
            spec = _heuristic_reader(summ)  # no per-skill spec for this measurement_type → default heuristic
        if not spec:
            continue
        raw = summ.get(spec["class"])
        if raw in spec.get("present_synonyms", ()):  # e.g. protein ns = quantified/present, not low
            raw = "__present__"
        t = classify(raw)
        # Dedup byte-identical sources: two cards from the SAME provenance with the SAME measured value are
        # ONE measurement, not independent corroboration (e.g. genomic FUS's two tcga-spliceseq splice cards).
        _ds = summ.get("_data_source")
        if _ds is not None:
            _key = (sg, _ds, summ.get(spec["class"]))
            if _key in _seen:
                continue
            _seen.add(_key)
        n = next((summ.get(f) for f in spec.get("n", []) if isinstance(summ.get(f), (int, float))), None)
        conflict = summ.get("allgene_percentile_class") == "bottom_decile"  # level != breadth
        per.setdefault(sg, []).append(
            {
                "card": cid,
                "tier": t,
                "n": n,
                "power": _nbucket(n),
                "label": spec.get("label", mt),
                "conflict": conflict,
                "value": summ.get(spec["class"]),
            }
        )

    out: dict = {}
    for sg, srcs in per.items():
        # An ABSTAINING source is held out of the vote entirely — out of the numerator AND the
        # denominator. Leaving it in the denominator would read as DISAGREEMENT ("1 of 2 sources agrees")
        # when the second source never spoke, silently converting a coverage gap into weak evidence.
        measured = [s for s in srcs if is_measured(s["tier"])]
        abstained = [s for s in srcs if not is_measured(s["tier"])]
        present = [s for s in measured if _TIERV[s["tier"]] >= 2]
        # ...and it never ranks: the signal is the strongest MEASURED read, and only reports UNMEASURED
        # when nothing was measured at all (in which case there is no confidence to report either).
        signal = max(measured, key=lambda s: _TIERV[s["tier"]])["tier"] if measured else UNMEASURED
        best_power = max((s["power"] for s in (measured or srcs)), key=lambda p: _POW.index(p))
        conflicts = [s for s in measured if s["conflict"]]
        # confidence = agreement × sample-size, capped by conflict (NOT weakest-link)
        conf = (
            "low"
            if not measured
            else "high"
            if len(present) == len(measured) and best_power in ("high", "very high")
            else "moderate"
            if len(present) >= max(1, len(measured) // 2)
            else "low"
        )
        if conflicts and conf == "high":
            conf = "moderate"
        # A held-out source must stay VISIBLE, or the hold-out silently inflates apparent agreement
        # (n_sources == n_agree with an unread card in the list reads as unanimity). n_sources counts
        # only the sources that voted; n_unmeasured says how many did not, and why is on each source.
        if abstained and conf == "high":
            conf = "moderate"  # unanimity among 1 of 3 cards is not high confidence
        out[sg] = {
            "signal": signal,
            "confidence": conf,
            "n_sources": len(measured),
            "n_agree": len(present),
            "n_unmeasured": len(abstained),
            "power": best_power,
            "conflict": bool(conflicts),
            "sources": [
                {
                    "card": s["card"],
                    "tier": s["tier"],
                    "n": s["n"],
                    "label": s["label"],
                    "conflict": s["conflict"],
                    "value": s["value"],
                }
                for s in srcs
            ],
        }
    return out


# ── FIRST-CLASS SUBTYPE: generic per-stratum projection of each sub-group ──────────────────────────
# Fleet version of tumor-presence's _attach_subtype_firstclass. Reads the `tier: subtype` cards'
# per_subgroup_metrics for each sub-group and produces by_stratum {stratum: {signal, certainty, n,
# powered}}. Certainty = sample-size, 1-tier multiplicity haircut (k strata >= 5), POWER-GATED
# (evidence_state!=measured OR n<floor -> low/underpowered, never over-read). Subtype stays an
# orthogonal CONDITIONER: this REFINES a sub-group per stratum, it never mints a new sub-group.
_CERT = {"low": 0, "moderate": 1, "high": 2}
_CERT_INV = {0: "low", 1: "moderate", 2: "high"}
_STRATUM_ID_FIELDS = ("stratum_id", "stratum")
_STRATUM_N_FIELDS = ("n_tumor_samples", "subgroup_n", "n_cell_lines", "n")
_STRATUM_CLASS_FIELDS = ("tumor_expression_class", "protein_expression_class", "class", "expression_class")
_SUBGROUP_N_FLOOR = 30


def _multiplicity_haircut(cert: str, k: int) -> str:
    if cert not in _CERT or not isinstance(k, int) or k < 5:
        return cert
    return _CERT_INV[max(0, _CERT[cert] - 1)]


def _stratum_tier(row: dict, classify) -> str:
    for f in _STRATUM_CLASS_FIELDS:
        if row.get(f) is not None:
            return classify(row.get(f))
    med = row.get("median_log2tpm")
    if isinstance(med, (int, float)):
        return "strong" if med >= 5 else "moderate" if med >= 3.46 else "weak" if med >= 1 else "absent"
    # No class field and no median = nothing to read off this row. `absent` here claimed the stratum was
    # measured and empty; it was not measured at all.
    return UNMEASURED


def derive_stratified(hierarchy: dict, cards: list, classify=default_classify) -> dict:
    """{sub_group -> {stratum -> {signal, certainty, n, powered, multiplicity_strata_tested}}} from the
    sub-group's `tier: subtype` cards. Empty when no subtype cards / no per_subgroup_metrics."""
    type_sg = {}
    for sg in hierarchy.get("sub_groups", []):
        for q in sg.get("questions", []):
            for mt in q.get("measurement_types", []):
                type_sg.setdefault(mt, sg["id"])
    sg_rows: dict = {}
    for c in cards or []:
        summ = c.get("summary") or {}
        mt, tier = _card_meta(c.get("card_id"))
        sg = type_sg.get(mt)
        if not sg or tier != "subtype":
            continue
        rows = summ.get("per_subgroup_metrics")
        if isinstance(rows, list):
            sg_rows.setdefault(sg, []).extend(r for r in rows if isinstance(r, dict))

    out: dict = {}
    for sg, rows in sg_rows.items():
        by: dict = {}
        for r in rows:
            sid = next((r.get(f) for f in _STRATUM_ID_FIELDS if r.get(f)), None)
            if not sid:
                continue
            n = next((r.get(f) for f in _STRATUM_N_FIELDS if isinstance(r.get(f), (int, float))), None)
            powered = r.get("evidence_state") == "measured" and isinstance(n, (int, float)) and n >= _SUBGROUP_N_FLOOR
            by.setdefault(sid, []).append({"tier": _stratum_tier(r, classify), "n": n, "powered": powered})
        k = len(by)
        strata = {}
        for sid, reads in by.items():
            # Rank over MEASURED reads only; a stratum whose every read abstained reports UNMEASURED
            # rather than the bottom of the presence ordinal. `_TIERV.get(..., -1)` would have sorted the
            # abstention below a genuine `absent`, i.e. picked a non-measurement as the stratum's signal
            # whenever it was the only read.
            m_reads = [x for x in reads if is_measured(x["tier"])]
            if m_reads:
                best = max(m_reads, key=lambda x: _TIERV[x["tier"]])
            else:
                # Keep the stratum's own n: the cohort size is known even when nothing was read off it,
                # and dropping it would make an unread stratum indistinguishable from an empty one.
                n_any = next((x["n"] for x in reads if isinstance(x["n"], (int, float))), None)
                best = {"tier": UNMEASURED, "n": n_any}
            n = best["n"]
            base = (
                "high"
                if isinstance(n, (int, float)) and n >= 100
                else "moderate"
                if isinstance(n, (int, float)) and n >= _SUBGROUP_N_FLOOR
                else "low"
            )
            powered = any(x["powered"] for x in reads)
            cert = _multiplicity_haircut(base, k) if powered else "low"  # underpowered stratum never over-read
            strata[sid] = {
                "signal": best["tier"],
                "certainty": cert,
                "n": n,
                "powered": powered,
                "multiplicity_strata_tested": k,
            }
        if strata:
            out[sg] = strata
    return out


# ── UNIFICATION: sub-group SIGNAL from the claim_vector (not the coarse heuristic re-read) ──────────
# claim_vector_core is the mature, verdict-inert (signal × corroboration) contract: per-skill TUNED
# signal_fn, gap≠absent discipline, and citable evidence ATOMS (the rules→data trace). Its axes ARE the
# hierarchy sub-groups (ClaimSpec axis_key == sub_group id; presence maps A/C/D via a sub-group's
# `claim_axes`). So the AUTHORITATIVE sub-group signal is the claim's — the heuristic reader only
# supplies the corroborating CARD sources + sample-size confidence. This overlay makes the two views ONE
# hierarchy: sub-group signal + evidence atoms from the claim, cross-card corroboration + subtype from
# the cards. Ordinal, gap-honest (all-unmeasured claims -> `unmeasured`, which the heuristic cannot say).
_SIGNAL_ORD = {"strong": 3, "moderate": 2, "weak": 1, "absent": 0, "negative": 0, "unmeasured": None}
_ORD_SIGNAL = {3: "strong", 2: "moderate", 1: "weak", 0: "absent"}


def _claim_axes_for(sg: dict) -> list:
    """Which claim_vector axis_keys roll into this sub-group. Declared per sub-group via `claim_axes`
    (presence: A/C/D); defaults to the sub-group id (the ClaimSpec fleet, where axis_key == sub_group)."""
    ax = sg.get("claim_axes")
    return list(ax) if isinstance(ax, list) and ax else [sg["id"]]


def overlay_claim_signals(subgroup_signals: dict, claim_vector: dict, hierarchy: dict) -> dict:
    """Set each sub-group's SIGNAL from its mapped claim_vector axis/axes (the tuned, discipline-respecting
    tier), carrying the claim's evidence_atom trace, and merge the claim's conflict. Keeps the card-derived
    `sources`, `confidence`, and `by_stratum` untouched (corroboration + sample-size + subtype stay). A
    sub-group with a mapped claim but no card source is CREATED (signal-only). Verdict-inert, in-place +
    returned; no-op when claim_vector/hierarchy missing. Mutates `subgroup_signals`."""
    if not (isinstance(subgroup_signals, dict) and isinstance(claim_vector, dict) and isinstance(hierarchy, dict)):
        return subgroup_signals
    for sg in hierarchy.get("sub_groups", []):
        sgid = sg.get("id")
        mapped = [(ax, claim_vector[ax]) for ax in _claim_axes_for(sg) if isinstance(claim_vector.get(ax), dict)]
        if not mapped:
            continue  # no claim for this axis — leave heuristic signal
        measured = [(ax, cl) for ax, cl in mapped if _SIGNAL_ORD.get(cl.get("signal")) is not None]
        if measured:
            best = max(_SIGNAL_ORD[cl["signal"]] for _, cl in measured)
            claim_signal = _ORD_SIGNAL[best]
        else:
            claim_signal = "unmeasured"  # gap≠absent — the heuristic could not express this
        entry = subgroup_signals.setdefault(
            sgid, {"confidence": "low", "n_sources": 0, "n_agree": 0, "power": "low", "conflict": False, "sources": []}
        )
        entry["signal"] = claim_signal
        entry["signal_source"] = "claim_vector"
        entry["claims"] = [
            {
                k: v
                for k, v in {
                    "axis": ax,
                    "signal": cl.get("signal"),
                    "corroboration": cl.get("corroboration"),
                    "conflict": cl.get("conflict"),
                    "evidence": cl.get("evidence"),
                    "evidence_atom": cl.get("evidence_atom"),
                }.items()
                if v is not None
            }
            for ax, cl in mapped
        ]
        entry["conflict"] = bool(entry.get("conflict")) or any(cl.get("conflict") for _, cl in mapped)
    return subgroup_signals


def subgroup_signals_for(skill_dir, cards, reader_spec=None, classify=default_classify, claim_vector=None) -> dict:
    """One-call wiring for a skill's run.py: load <skill_dir>/question_hierarchy.yaml, derive the pooled
    sub-group signals, fold in the first-class per-stratum by_stratum, and (when a `claim_vector` is
    given) OVERLAY the authoritative claim signal + evidence atoms over each sub-group. Uses the default
    heuristic reader unless a per-skill reader_spec is given. Best-effort — returns {} on any fault
    (verdict-inert; never breaks the spine)."""
    try:
        from pathlib import Path as _P

        import yaml

        hier = yaml.safe_load((_P(skill_dir) / "question_hierarchy.yaml").read_text()) or {}
        sg = derive_subgroups(hier, cards, reader_spec, classify)
        for name, by in derive_stratified(hier, cards, classify).items():
            if name in sg:
                sg[name]["by_stratum"] = by
        if isinstance(claim_vector, dict):
            overlay_claim_signals(sg, claim_vector, hier)
        return sg
    except Exception:  # noqa: BLE001 — verdict-inert projection; never break the spine
        return {}
