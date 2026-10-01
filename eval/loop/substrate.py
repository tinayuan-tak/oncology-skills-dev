#!/usr/bin/env python3
"""eval/loop/substrate.py — the triangulation-judge SUBSTRATE ASSEMBLER (SK#2303 WI-B).

Productionises the throwaway extractor in ``~/subskill-loop-pilot/judge.py`` into the stable,
testable interface the loop's triangulation judge (WI-C, #2355) and its containment guard (WI-D)
read. It turns ONE emitted bounded evidence package (``run.py --emit-envelope`` →
``evidence_package.json`` + ``decision.json``) into a per-family bundle of **RAW L2b islands** plus a
``field_contracts`` block — and does **NO hand-normalisation**.

Why RAW. The pilot's every false finding traced to a normaliser that did not anticipate a shape, never
to the framework (plan §5A.9/§5A.10). ``integrated_properties`` (L2b) is heterogeneous across families
along ≥4 axes, all of which this assembler reads NATIVELY rather than flattening:

  1. **token key** — 5 of 6 families carry ``concordance_class``; exactly one
     (``cellline_heterogeneity_lineage_qualifier``) carries ``qualifier_class``. A hard-coded
     ``concordance_class`` read fabricates a phantom ``(family, None)`` pair *and* silently drops the
     real token (plan §5A.7). We resolve the token key PER FAMILY and emit a loud ``MISSING_TOKEN``
     sentinel — never a ``None`` that flows into an index — when neither key is present.
  2. **``source_support`` container** — a **dict** (keyed by arm) for some families
     (``bulk_vs_singlecell_coverage_concordance``), a **list** for others. The ERBB2 "empty arms"
     false findings came from iterating a dict as a list. :func:`iter_source_support` is the one
     shape-aware primitive; it NEVER iterates a dict as a list.
  3. **per-arm schema** — tumor_presence / protein_presence arms carry ``source`` / ``present`` /
     ``value`` / a ``*_class`` / ``retained_quantitative``; coverage / abundance arms leave those null
     and carry ``stance`` / ``fields`` instead. We pass both through; the ``raw_island`` is authoritative.
  4. **concordance-vs-qualifier object** — a qualifier family folds no arms; it carries
     ``bound_fields`` / ``guards_misread`` / ``caveat`` instead. Its contract says it is NOT a
     concordance class, so the judge does not read it as one.

The ``field_contracts`` block is the SECOND guardrail the pilot validated: without each field's
contract (enum disposition + the load-bearing ``corroboration`` semantics) the judge confidently
flagged a correct-by-contract field (CD274 ``corroboration:high``); with it the false finding
disappeared. ``corroboration`` is INDEPENDENCE-AGREEMENT, not strength/abundance — see
:data:`CORROBORATION_CONTRACT`.

READ ``run_health`` + per-card ``read_error`` FIRST. A dead package (``n_cards_resolved == 0``, NOT
``status != "ok"`` — ``degraded`` is the normal per-triple state, plan §5A.6) is NULL-everything, never
data: :func:`assemble` returns ``null_everything=True`` with empty L2a/L2b and a reason, so no consumer
mistakes a package that resolved zero cards for a measured absence.

This module READS the governed vocabularies and the emitted packages; it writes nothing and resolves no
verdict. PURE: :func:`assemble_from_objects` takes parsed dicts and returns a dict (hermetic, testable).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

# The L2b token lives under exactly one of these keys, resolved PER FAMILY (never hard-coded).
TOKEN_KEYS = ("concordance_class", "qualifier_class")

# A loud, distinctive sentinel for a family that carries NEITHER token key. NEVER None: a None token
# flows silently into a (family, token) index and fabricates a phantom pair (plan §5A.7 finding 1).
MISSING_TOKEN = "<NO_TOKEN_KEY>"

# The load-bearing field semantics the judge MUST be fed (owner directive 2026-09-30, plan §5A.10). The
# pilot judge misread `corroboration:high` as "strong presence" when it MEANS "the family's independent
# arms agree on DETECTABILITY". Feeding this contract eliminated a live false positive (CD274).
CORROBORATION_CONTRACT = (
    "`corroboration` is the INDEPENDENCE-AGREEMENT of a family's INDEPENDENT arms ONLY: "
    "high = >=2 independent arms agree; low = they disagree; single_arm = one resolved. It is NOT a "
    "strength / abundance / breadth measure. For protein_presence the mass-spec sources "
    "{cptac, gygi, procan} are ONE independent arm (only cptac is corroboration_eligible); the "
    "antibody-IHC arm is the other. A detected class (even ihc_detected_low, if >=2 patients) makes the "
    "IHC arm 'present'. So high corroboration on a weak-but-detected IHC arm is CORRECT BY CONTRACT — "
    "the within-arm strength lives in the arm's datum / class, not in `corroboration`."
)

# #2331 — the typed `reliability` facet (#2306) now riding on each L2a entry (`l2a.<family>.reliability`).
# Fed alongside the anchors it is derived FROM so the judge is not hand-fed raw counts without the
# pipeline's own quality/power read of them: n_effective/powered are a per-property-kind calibration
# (powered='unmeasured' is HONEST ABSENCE of a floor, not evidence of good power); confound_flags /
# artifact_flags / detection_strength are governed vocab (contracts/vocabularies/reliability.enum.yaml).
# A property with NO reliability key (safety/dependency/genomic today mostly skeleton) is not a defect —
# it means the facet has nothing beyond the honest skeleton to report, not that the judge should flag
# its absence as a gap.
RELIABILITY_CONTRACT = (
    "`reliability` (when present on an l2a entry) is the pipeline's OWN typed quality/power read of that "
    "property's anchors — n_effective (effective N behind it), powered (true/false/'unmeasured' — "
    "'unmeasured' means no calibrated floor exists yet for that property kind, NOT that it is well- or "
    "under-powered), confound_flags / artifact_flags (governed vocab, e.g. microenvironment_weighted / "
    "floor_tie_percentile), and detection_strength (weak/moderate/strong, detection-kind properties only). "
    "Use it as GROUNDING CONTEXT for judging the property's class/token against its datum — a weak "
    "detection_strength or a confound_flag already EXPLAINS a borderline class and is not itself a new "
    "defect to report; but a confound/artifact flag present on an entry whose class/story does NOT "
    "surface it IS a legitimate `surface_unused_signal` finding. Absence of the key is the honest "
    "skeleton (no flags, no calibrated floor) on a signal-poor domain, not a gap."
)


def _repo_root() -> Path:
    """Repo root resolved from this file's location (eval/loop/substrate.py → repo root)."""
    return Path(__file__).resolve().parents[2]


def _default_contracts_root() -> Path:
    return _repo_root() / "contracts"


# ── field_contracts: enum dispositions + per-token semantics ─────────────────────────────────────────
def load_token_contracts(contracts_root: "Path | str | None" = None) -> dict:
    """Load the governed ``concordance_class`` vocabulary into two lookup tables:

      - ``tokens``  : ``{token_value: {"disposition", "means"}}`` (``means`` = the token's own one-line
        definition);
      - ``dispositions`` : ``{disposition: semantics}`` (the one-line disposition definition, e.g.
        ``concordant`` = "two or more arms resolved and agree").

    Best-effort: an unreadable / absent enum yields empty tables (the ``corroboration`` contract is
    static and still emits). The qualifier token has no governed enum of its own — its contract is
    carried from the raw island (see :func:`_family_contract`)."""
    root = Path(contracts_root) if contracts_root is not None else _default_contracts_root()
    enum_path = root / "vocabularies" / "concordance_class.enum.yaml"
    try:
        doc = yaml.safe_load(enum_path.read_text())
    except Exception:  # noqa: BLE001 — a missing/unreadable enum degrades to the static contract only
        return {"tokens": {}, "dispositions": {}}

    def _first_line(text: Any) -> "str | None":
        if not isinstance(text, str):
            return None
        stripped = text.strip()
        return stripped.split("\n")[0] if stripped else None

    dispositions = {
        d.get("disposition"): _first_line(d.get("definition"))
        for d in (doc.get("dispositions") or [])
        if isinstance(d, dict) and d.get("disposition")
    }
    tokens = {
        v.get("value"): {"disposition": v.get("disposition"), "means": _first_line(v.get("definition"))}
        for v in (doc.get("values") or [])
        if isinstance(v, dict) and v.get("value")
    }
    return {"tokens": tokens, "dispositions": dispositions}


# ── shape-aware island reading (the one normalisation primitive) ─────────────────────────────────────
def iter_source_support(island: dict) -> list[tuple]:
    """Shape-aware iteration of an island's ``source_support``, returning ``[(arm_key, arm_dict), ...]``.

    ``source_support`` is a **dict** keyed by arm for some families and a **list** for others (plan
    §5A.10 axis 2). This NEVER iterates a dict as a list — doing so yields the dict's KEYS (strings),
    which an ``isinstance(v, dict)`` filter then drops, producing the ERBB2 "empty arms" artifact. A
    family with no / malformed ``source_support`` (e.g. a qualifier) returns ``[]``.

    THIS is the load-bearing primitive the loop's mutation tooth targets: a normaliser that assumes
    list-shape reads zero arms off a dict-``source_support`` family."""
    ss = island.get("source_support")
    if isinstance(ss, dict):
        return [(k, v) for k, v in ss.items() if isinstance(v, dict)]
    if isinstance(ss, list):
        return [(None, v) for v in ss if isinstance(v, dict)]
    return []


def resolve_token(island: dict) -> tuple:
    """Resolve ``(token_key, token)`` for one L2b island, per family.

    Returns the first present key in :data:`TOKEN_KEYS` and its value; ``(None, MISSING_TOKEN)`` when
    neither is present. NEVER returns a ``None`` token (that would fabricate a phantom ``(family, None)``
    pair — plan §5A.7)."""
    for key in TOKEN_KEYS:
        if key in island:
            return key, island.get(key)
    return None, MISSING_TOKEN


def _arm_view(arm_key: "str | None", arm: dict) -> dict:
    """A thin per-arm VIEW carrying the L1 datum the judge audits — NOT a flattening of the island.

    ``class`` resolves the arm's own class token across the per-arm schema variants (axis 3);
    ``source`` falls back to the dict ``arm_key`` for a keyed container (list arms carry ``source``
    inline). ``datum`` is the raw ``retained_quantitative`` block; ``stance`` / ``fields`` pass through
    for the coverage/abundance arm schema. The authoritative, loss-free structure stays in
    ``raw_island`` — this view never replaces it."""
    cls = arm.get("presence_class") or arm.get("protein_presence_class") or arm.get("stratification_class")
    return {
        "source": arm.get("source") or arm_key,
        "value": arm.get("value"),
        "present": arm.get("present"),
        "class": cls,
        "datum": arm.get("retained_quantitative"),
        "stance": arm.get("stance"),
        "fields": arm.get("fields"),
    }


def _family_contract(family: str, token_key: "str | None", token: Any, island: dict, token_contracts: dict) -> dict:
    """The per-family contract bundle fed alongside the datum.

    For a governed ``concordance_class`` token: its disposition + one-line meaning + the disposition's
    semantics. For a ``qualifier_class`` family (no governed enum of its own): mark it a ``qualifier``
    and carry its ``guards_misread`` + ``caveat`` from the raw island, so the judge reads it as a
    MISREAD GUARD, never as a concordance class. For a missing token: a loud marker."""
    if token_key == "qualifier_class":
        return {
            "token": token,
            "token_key": token_key,
            "disposition": "qualifier",
            "means": "a verdict-INERT per-source qualifier, NOT a cross-source concordance class.",
            "guards_misread": island.get("guards_misread"),
            "caveat": island.get("caveat"),
        }
    if token == MISSING_TOKEN or token_key is None:
        return {"token": MISSING_TOKEN, "token_key": None, "disposition": None, "means": "no token key on this island"}
    entry = (token_contracts.get("tokens") or {}).get(token)
    if not entry:
        # A token not in the governed enum: surface it loudly rather than fabricating a meaning.
        return {"token": token, "token_key": token_key, "disposition": None, "means": None, "ungoverned_token": True}
    disposition = entry.get("disposition")
    return {
        "token": token,
        "token_key": token_key,
        "disposition": disposition,
        "means": entry.get("means"),
        "disposition_semantics": (token_contracts.get("dispositions") or {}).get(disposition),
    }


def _l2a_anchors(source_properties: dict) -> dict:
    """L2a per-source bundle: ``{family: {card_id, property, anchors: {field: value}, reliability}}`` —
    the anchor NUMBERS the labels abstract over (plan §0: the labels are abstractions to be audited
    AGAINST the datum), PLUS (#2306/#2331) the pipeline's own typed `reliability` read of those same
    anchors — passed through VERBATIM, never re-derived here (this module does no hand-normalisation).
    L2a is uniform across families (plan §5A.7 finding 2), so no shape branching is needed."""
    out: dict = {}
    for family, prop in (source_properties or {}).items():
        if not isinstance(prop, dict):
            continue
        anchors = {a.get("field"): a.get("value") for a in (prop.get("anchors") or []) if isinstance(a, dict)}
        out[family] = {
            "card_id": prop.get("card_id"),
            "property": prop.get("property"),
            "anchors": anchors,
            "comparability": prop.get("comparability"),
            # #2306/#2331: the typed quality/power facet — see RELIABILITY_CONTRACT. VERBATIM passthrough;
            # None when the property carries none (an un-rolled-out domain, or a resolve.py read older
            # than #2306).
            "reliability": prop.get("reliability"),
        }
    return out


def _l3_compact(l3d: "dict | None") -> "dict | None":
    """A compact L3d view: coherence + headline + per-chapter (aspect, claim_id) + caveats. The
    chapters' ``claim_id`` is the DOWNWARD handle the containment guard re-verifies against."""
    if not isinstance(l3d, dict):
        return None
    chapters = [
        {"aspect": c.get("aspect"), "claim_id": c.get("claim_id")}
        for c in (l3d.get("chapters") or [])
        if isinstance(c, dict)
    ]
    caveats = [c.get("caveat") if isinstance(c, dict) else c for c in (l3d.get("caveats") or [])]
    return {
        "coherence": l3d.get("coherence"),
        "headline": l3d.get("headline"),
        "chapters": chapters,
        "caveats": caveats,
    }


def _card_read_errors(evidence_package: dict) -> list[dict]:
    """Per-card ``read_error`` surfaced on the emitted cards (``availability_state == 'read_error'``) —
    a framework-coverage gap: the reader could not LOOK (timeout / deadlock / exception), distinct from a
    measured absence. Read FIRST so a dead card is never consumed as data."""
    out = []
    for c in evidence_package.get("cards") or []:
        if isinstance(c, dict) and c.get("availability_state") == "read_error":
            out.append(
                {
                    "card_id": c.get("card_id"),
                    "availability_state": c.get("availability_state"),
                    "availability_reason": c.get("availability_reason"),
                }
            )
    return out


def _n_cards_resolved(run_health: "dict | None") -> "int | None":
    if not isinstance(run_health, dict):
        return None
    val = run_health.get("n_cards_resolved")
    return val if isinstance(val, int) else None


def assemble_from_objects(
    evidence_package: dict,
    decision: "dict | None" = None,
    *,
    contracts_root: "Path | str | None" = None,
    run_health: "dict | None" = None,
) -> dict:
    """Assemble the judge substrate from already-parsed objects (PURE — no I/O).

    ``evidence_package`` is the ``--emit-envelope`` ``evidence_package.json`` (carries L2a
    ``source_properties``, L2b ``integrated_properties``, ``l3d``). ``run_health`` is read from
    ``decision`` (``decision['run_health']``) unless passed explicitly. The result is the stable bundle
    the triangulation judge + containment guard consume — see the module docstring for the per-family
    shape. Dead package (``n_cards_resolved == 0`` or no ``run_health``) ⇒ ``null_everything`` with empty
    L2a/L2b."""
    if run_health is None and isinstance(decision, dict):
        run_health = decision.get("run_health")

    read_errors = _card_read_errors(evidence_package)
    n_resolved = _n_cards_resolved(run_health)

    # Dead-package gate FIRST (plan §5A.6): n_cards_resolved is the dead/alive instrument (0 = dead), NOT
    # run_health.status (`degraded` is a normal usable per-triple state). No run_health at all = we cannot
    # vouch the package is live ⇒ also NULL-everything.
    if run_health is None or n_resolved == 0:
        reason = "no run_health section" if run_health is None else "n_cards_resolved == 0 (dead package)"
        return {
            "run_health": run_health,
            "null_everything": True,
            "null_reason": reason,
            "card_read_errors": read_errors,
            "l2a": {},
            "l2b": {},
            "l3": None,
            "field_contracts": {"_corroboration": CORROBORATION_CONTRACT, "_reliability": RELIABILITY_CONTRACT},
            "families_missing_token": [],
        }

    token_contracts = load_token_contracts(contracts_root)
    integrated = evidence_package.get("integrated_properties") or {}

    l2b: dict = {}
    field_contracts: dict = {"_corroboration": CORROBORATION_CONTRACT, "_reliability": RELIABILITY_CONTRACT}
    missing_token: list[str] = []
    for family, island in integrated.items():
        if not isinstance(island, dict):
            continue
        token_key, token = resolve_token(island)
        if token == MISSING_TOKEN:
            missing_token.append(family)
        arms = [_arm_view(key, arm) for key, arm in iter_source_support(island)]
        l2b[family] = {
            "token_key": token_key,
            "token": token,
            "corroboration": island.get("corroboration"),
            "arms": arms,
            "raw_island": island,  # VERBATIM — no shape loss, no flattening
        }
        field_contracts[family] = _family_contract(family, token_key, token, island, token_contracts)

    return {
        "run_health": run_health,
        "null_everything": False,
        "null_reason": None,
        "card_read_errors": read_errors,
        "l2a": _l2a_anchors(evidence_package.get("source_properties") or {}),
        "l2b": l2b,
        "l3": _l3_compact(evidence_package.get("l3d")),
        "field_contracts": field_contracts,
        "families_missing_token": missing_token,
    }


def assemble(run_dir: "Path | str", *, contracts_root: "Path | str | None" = None) -> dict:
    """Assemble the judge substrate from an emitted run directory.

    Reads ``<run_dir>/evidence_package.json`` (required — the bounded sections live here) and
    ``<run_dir>/decision.json`` (optional — the ``run_health`` sentinel; absent ⇒ NULL-everything).
    Delegates to :func:`assemble_from_objects`."""
    run_path = Path(run_dir)
    evidence_package = json.loads((run_path / "evidence_package.json").read_text())
    decision: "dict | None" = None
    decision_path = run_path / "decision.json"
    if decision_path.exists():
        decision = json.loads(decision_path.read_text())
    return assemble_from_objects(evidence_package, decision, contracts_root=contracts_root)
