#!/usr/bin/env python3
"""eval/loop/critic/containment.py — the subskill-iteration loop's CONTAINMENT GUARD (SK#2303 WI-D, #2356).

The fail-closed guard between the propose-only triangulation judge (``critic/judge.py``, #2355) and any
tier routing. The judge gives CONFIDENT findings whose refs RESOLVE but whose INTERPRETATION can be wrong
without the field's contract — the single most valuable, and most dangerous, pilot result (plan §5A.9).
Ref-resolution alone is **necessary-but-NOT-sufficient** (plan §5A.9, "the containment guard … catches
fabricated numbers, NOT semantic misreadings of correctly-resolved fields"). So every finding is
deterministically re-verified on TWO axes before it may be routed:

  1. **Grounding** — each cited ``datum_ref`` is re-resolved against the **RAW L2b island** from the WI-B
     substrate (``substrate.assemble*`` → ``l2b[family]["raw_island"]``), NEVER a re-normalised copy. The
     one shape-aware primitive is ``substrate.iter_source_support`` (dict-keyed vs list ``source_support``
     — plan §5A.10 axis 2); an arm ref is resolved THROUGH it so a dict-``source_support`` family's arms
     are never mis-read as empty. A finding whose refs ALL fail to resolve is a confabulation ⇒ DROPPED.
  2. **Contract** — the claim is checked against the cited field's CONTRACT (enum disposition + the
     load-bearing ``corroboration`` semantics carried in the substrate's ``field_contracts`` block), not
     just that the refs exist. A finding that reads a field as something its contract says it does NOT
     mean (e.g. ``corroboration:high`` as a STRENGTH/abundance claim, when by contract it is
     INDEPENDENCE-AGREEMENT) CONTRADICTS the contract ⇒ DROPPED.

A finding that fails containment is **never passed to tiers** (acceptance). Two dispositions:
  - **DROPPED** — a false-premise finding (contract contradiction, or no ref resolves). It does not route.
  - **DEMOTED** — a *substrate-shape* / *schema-coherence* note for the OUTER loop (#2224), not a tier
    finding: e.g. an "empty arms" claim that a shape-aware raw re-read refutes (dict-vs-list
    ``source_support`` artifact — plan §5A.11). The observation about the SUBSTRATE is real; the finding
    about the PIPELINE is not — so it is kept, re-tagged, and routed away from the tiers.

The two pilot catches this guard reproduces (acceptance):
  1. **CD274 ``corroboration:high`` "overstated"** (``judge_CD274_LUAD.json[1]`` / ``ERBB2_BRCA.json[1]``):
     the pre-contract judge proposed downgrading ``corroboration`` because the IHC arm is mostly
     not-detected. ``corroboration`` is independence-agreement, not within-arm strength (CORRECT BY
     CONTRACT), so the finding's premise contradicts the contract ⇒ DROPPED. This is the module's
     MUTATION TOOTH: delete the contract check and this false finding passes.
  2. **ERBB2 "empty arms"** (``ERBB2_BRCA.json[5]``): the throwaway normaliser iterated a dict
     ``source_support`` as a list and fed the judge ``arms=[]``; the judge faithfully reported empty arms.
     Re-resolving the RAW island shape-aware finds the arms ⇒ DEMOTED as a substrate-shape artifact.

PURE / propose-adjacent: this module READS the assembled substrate bundle + a judge result; it writes
nothing, resolves no verdict, moves no threshold, and routes nothing to Tier-1 on its own (STOP-A). It
reuses ``substrate.iter_source_support`` (shape-aware arm reads) and the ``field_contracts`` the WI-B
assembler already loaded from ``contracts/vocabularies/*.enum.yaml`` — it does not re-read the vocabularies.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

# The substrate assembler (WI-B) lives one directory up (eval/loop/substrate.py). The eval/ convention is
# a bare sys.path import, no package __init__ under critic/ (judge.py / _predicates.py / probes.py live
# here under the same convention — do NOT add an __init__.py).
_LOOP_DIR = Path(__file__).resolve().parents[1]
if str(_LOOP_DIR) not in sys.path:
    sys.path.insert(0, str(_LOOP_DIR))

import substrate as _substrate  # noqa: E402

SCHEMA_VERSION = "1.0"

# ── dispositions ────────────────────────────────────────────────────────────────────────────────────
CONTAINED = "contained"  # survives: grounded AND no contract contradiction → MAY route
DROPPED_UNRESOLVED = "dropped:unresolved_refs"  # confabulation — no cited ref resolves
DROPPED_CONTRACT = "dropped:contract_contradiction"  # the claim contradicts the cited field's contract
DEMOTED_SHAPE = "demoted:substrate_shape_artifact"  # an "empty arms" claim a shape-aware raw read refutes

_DROPPED = frozenset({DROPPED_UNRESOLVED, DROPPED_CONTRACT})
_DEMOTED = frozenset({DEMOTED_SHAPE})

# A distinct sentinel so a RESOLVED field whose value is falsy (``None`` / ``0`` / ``False`` / ``[]``) is
# never confused with an ABSENT key. Presence, not truthiness, decides whether a ref resolved.
_MISSING = object()

# ── claim-signal patterns (the deterministic read of an LLM-prose claim) ──────────────────────────────
# A finding's `finding` + `why` prose is the LLM's claim; the guard reads it deterministically. These are
# the two load-bearing semantic classes the pilot surfaced, each matched conservatively (narrow enough not
# to fire on a finding that merely MENTIONS the field — see the per-check structural pre-conditions).

# The claim treats `corroboration` (or the concordance token) as a STRENGTH measure and proposes to
# LOWER it because the within-arm detection is weak. By the corroboration contract that is a misread.
_CORROBORATION_MISREAD = re.compile(
    r"(downgrad\w*\s+(the\s+)?corroboration"
    r"|corroboration[^.]{0,60}?(downgrad|overstat|too\s+high|should\s+(read|be)|lower)"
    r"|not\s+high[-\s]?corroboration"
    r"|(the\s+)?token\s+should\s+read\s+discordant"
    r"|high[-'\s]*corroboration[^.]{0,40}?(flatten|overstat|hides|buries|absorb))",
    re.IGNORECASE,
)

# The claim asserts a family's arms are EMPTY / absent / unevidenced in structure.
_EMPTY_ARMS = re.compile(
    r"(empty[\s/-]*(and\s+)?(null\s+)?arms?"
    r"|arms?\s+(are\s+)?empty"
    r"|null\s+arms?"
    r"|no\s+arms?\b"
    r"|zero\s+arms?"
    r"|carries\s+empty"
    r"|unevidenced\s+in\s+structure)",
    re.IGNORECASE,
)


# ── datum_ref resolution against the RAW island ───────────────────────────────────────────────────────
def _split_ref(ref: str) -> list[str]:
    """Tokenise a dotted datum_ref into segments, keeping an ``arms[<source>]`` bracket as ONE segment.

    e.g. ``l2b.protein_presence_concordance.arms[antibody_ihc].datum.n_high`` →
    ``['l2b','protein_presence_concordance','arms[antibody_ihc]','datum','n_high']``."""
    out: list[str] = []
    for part in ref.split("."):
        out.append(part)
    # Re-join a split that happened INSIDE brackets (a source key never contains '.', but be defensive).
    merged: list[str] = []
    depth = 0
    for seg in out:
        if depth:
            merged[-1] += "." + seg
        else:
            merged.append(seg)
        depth += seg.count("[") - seg.count("]")
    return merged


_ARM_RE = re.compile(r"^arms\[(?P<src>.+)\]$")


def _arm_datum_value(arm: dict, field: str) -> Any:
    """Read a datum field off a RAW arm dict, tolerating the per-arm schema variants (plan §5A.10 axis 3):
    list arms carry it under ``retained_quantitative``; dict (coverage/abundance) arms carry it under
    ``fields``. Falls back to the arm dict itself. Returns :data:`_MISSING` when absent."""
    for container_key in ("retained_quantitative", "fields"):
        container = arm.get(container_key)
        if isinstance(container, dict) and field in container:
            return container[field]
    if field in arm:
        return arm[field]
    return _MISSING


def _arm_attr_value(arm: dict, attr: str) -> Any:
    """Read a non-datum arm attribute (``class`` / ``present`` / ``value`` / ``source`` / ``stance``),
    resolving ``class`` across the per-arm class-token schema variants."""
    if attr == "class":
        for k in ("presence_class", "protein_presence_class", "stratification_class"):
            if k in arm:
                return arm[k]
        return _MISSING
    return arm.get(attr, _MISSING)


def resolve_ref(ref: str, bundle: dict) -> Any:
    """Re-resolve ONE datum_ref against the substrate bundle, reading the RAW L2b island (never the
    normalised arm view). Returns the resolved value, or :data:`_MISSING` if the path does not resolve.

    Supported roots: ``l2b.<family>[.token|.corroboration|.<raw_island_key>|.arms[<source>](.datum.<field>
    |.<attr>)]`` · ``l2a.<family>[.anchors.<field>|.<key>]`` · ``l3.<key>``. Arm refs are resolved THROUGH
    :func:`substrate.iter_source_support` so a dict-``source_support`` family's arms are read shape-aware."""
    if not isinstance(ref, str) or not isinstance(bundle, dict):
        return _MISSING
    segs = _split_ref(ref.strip())
    if not segs:
        return _MISSING
    root = segs[0].lower()

    if root == "l3":
        l3 = bundle.get("l3")
        if not isinstance(l3, dict) or len(segs) < 2:
            return _MISSING
        return l3.get(segs[1], _MISSING)

    if root == "l2a":
        if len(segs) < 2:
            return _MISSING
        fam = bundle.get("l2a", {}).get(segs[1])
        if not isinstance(fam, dict):
            return _MISSING
        if len(segs) == 2:
            return fam
        if segs[2] == "anchors":
            anchors = fam.get("anchors")
            if not isinstance(anchors, dict) or len(segs) < 4:
                return _MISSING
            return anchors.get(segs[3], _MISSING)
        return fam.get(segs[2], _MISSING)

    if root == "l2b":
        if len(segs) < 2:
            return _MISSING
        family = bundle.get("l2b", {}).get(segs[1])
        if not isinstance(family, dict):
            return _MISSING
        raw = family.get("raw_island")
        raw = raw if isinstance(raw, dict) else family
        if len(segs) == 2:
            return raw
        seg2 = segs[2]
        arm_match = _ARM_RE.match(seg2)
        if arm_match:
            src = arm_match.group("src")
            arm = None
            for arm_key, arm_dict in _substrate.iter_source_support(raw):
                # Match by the dict key OR by the arm's own `source` field (list arms carry it inline).
                if arm_key == src or (isinstance(arm_dict, dict) and arm_dict.get("source") == src):
                    arm = arm_dict
                    break
            if arm is None:
                return _MISSING
            if len(segs) == 3:
                return arm
            if segs[3] == "datum":
                if len(segs) < 5:
                    return arm.get("retained_quantitative", _MISSING)
                return _arm_datum_value(arm, segs[4])
            return _arm_attr_value(arm, segs[3])
        # `token` / `token_key` are the SUBSTRATE's abstraction over the raw island's per-family token key
        # (`concordance_class` vs `qualifier_class`) — re-resolve them against the RAW island through the
        # same shape-aware primitive the assembler used, never against a normalised copy.
        if seg2 == "token":
            _, tok = _substrate.resolve_token(raw)
            return tok
        if seg2 == "token_key":
            tok_key, _ = _substrate.resolve_token(raw)
            return tok_key if tok_key is not None else _MISSING
        # A direct raw-island key (corroboration / concordance_class / source_support / ...).
        return raw.get(seg2, _MISSING)

    return _MISSING


def _ref_report(datum_refs: list, bundle: dict) -> tuple[list[str], list[str]]:
    """Partition a finding's datum_refs into (resolved, unresolved) against the RAW island."""
    resolved: list[str] = []
    unresolved: list[str] = []
    for ref in datum_refs or []:
        if not isinstance(ref, str) or not ref.strip():
            continue
        if resolve_ref(ref, bundle) is _MISSING:
            unresolved.append(ref)
        else:
            resolved.append(ref)
    return resolved, unresolved


# ── the two contract / shape checks ───────────────────────────────────────────────────────────────────
def _claim_text(finding: dict) -> str:
    return " ".join(str(finding.get(k, "")) for k in ("finding", "why", "target"))


def _cites_corroboration(finding: dict) -> bool:
    """A finding CITES corroboration iff a datum_ref's final segment is ``corroboration`` (structural, not
    a mere prose mention — so a finding that only AFFIRMS a corroboration field is correct-by-contract,
    citing arm datums instead, is not swept in)."""
    for ref in finding.get("datum_refs") or []:
        if isinstance(ref, str) and _split_ref(ref.strip())[-1:] == ["corroboration"]:
            return True
    return False


def _corroboration_contract_contradiction(finding: dict, bundle: dict) -> "str | None":
    """DROP reason if the finding reads ``corroboration`` as a STRENGTH measure (and proposes to lower it)
    — a misread of its contract. Consults the substrate's ``field_contracts`` so the check is contract-
    DRIVEN: it fires only where the contract declares corroboration is NOT a strength/abundance measure."""
    if not _cites_corroboration(finding):
        return None
    if not _CORROBORATION_MISREAD.search(_claim_text(finding)):
        return None
    contract = (bundle.get("field_contracts") or {}).get("_corroboration")
    if not (isinstance(contract, str) and "INDEPENDENCE-AGREEMENT" in contract):
        return None  # no contract to judge against → cannot assert a contradiction
    return (
        "corroboration is INDEPENDENCE-AGREEMENT of a family's independent arms, NOT a within-arm "
        "strength/abundance measure (field_contracts._corroboration); a finding that proposes to lower "
        "it because an arm is weakly-detected misreads the contract (correct-by-contract)."
    )


def _l2b_family_of(finding: dict) -> "str | None":
    """Resolve the L2b family a finding is about, from its ``l2b.<family>...`` datum_refs first (the
    load-bearing handle), falling back to a family name appearing in the ``target`` string."""
    for ref in finding.get("datum_refs") or []:
        if isinstance(ref, str):
            segs = _split_ref(ref.strip())
            if len(segs) >= 2 and segs[0].lower() == "l2b":
                return segs[1]
    return None


def _empty_arms_shape_artifact(finding: dict, bundle: dict) -> "str | None":
    """DEMOTE reason if the finding asserts a family's arms are EMPTY but a shape-aware raw re-read finds
    arms (the dict-vs-list ``source_support`` artifact — plan §5A.11). The arms-absence claim about the
    PIPELINE is false; the SUBSTRATE-shape observation is routed to the outer loop, never to a tier."""
    if not _EMPTY_ARMS.search(_claim_text(finding)):
        return None
    family = _l2b_family_of(finding)
    islands = bundle.get("l2b") or {}
    candidates = [family] if family in islands else list(islands)
    for fam in candidates:
        raw = islands.get(fam, {}).get("raw_island")
        raw = raw if isinstance(raw, dict) else islands.get(fam, {})
        arms = _substrate.iter_source_support(raw)
        if arms:
            return (
                f"finding claims empty arms for L2b.{fam}, but a shape-aware re-read of the RAW island's "
                f"source_support finds {len(arms)} arm(s) — a dict-vs-list substrate-shape artifact, not a "
                f"pipeline defect (demoted to the outer loop's schema-coherence lane)."
            )
    return None


# ── per-finding + whole-result containment ─────────────────────────────────────────────────────────────
def check_finding(finding: dict, bundle: dict) -> dict:
    """Re-verify ONE finding against the raw island + its contract. Returns the finding augmented with a
    ``_containment`` block (``status`` + ``reason`` + resolved/unresolved refs + contract notes). Order of
    precedence: contract contradiction (DROP) → substrate-shape artifact (DEMOTE) → no ref resolves (DROP)
    → CONTAINED."""
    refs = finding.get("datum_refs") if isinstance(finding, dict) else None
    resolved, unresolved = _ref_report(refs if isinstance(refs, list) else [], bundle)

    contract_reason = _corroboration_contract_contradiction(finding, bundle)
    shape_reason = _empty_arms_shape_artifact(finding, bundle)

    if contract_reason is not None:
        status, reason = DROPPED_CONTRACT, contract_reason
    elif shape_reason is not None:
        status, reason = DEMOTED_SHAPE, shape_reason
    elif not resolved:
        status, reason = DROPPED_UNRESOLVED, "no cited datum_ref resolves against the raw island (confabulation)"
    else:
        status, reason = CONTAINED, None

    out = dict(finding)
    out["_containment"] = {
        "status": status,
        "reason": reason,
        "resolved_refs": resolved,
        "unresolved_refs": unresolved,
    }
    return out


def contain(judge_result: dict, bundle: dict) -> dict:
    """Containment-guard a whole judge result against its assembled substrate bundle.

    Returns a report partitioning the judge's findings into ``contained`` (grounded + contract-consistent →
    MAY route), ``dropped`` (false premise — contract contradiction or no ref resolves), and ``demoted``
    (substrate-shape / schema-coherence notes for the OUTER loop, never a tier). ``report_only`` stays
    ``True`` (STOP-A). A SKIPPED judge result (dead / NULL substrate) passes its skip through unchanged —
    there is nothing to contain."""
    base = {
        "schema_version": SCHEMA_VERSION,
        "report_only": True,
        "skipped": judge_result.get("skipped") if isinstance(judge_result, dict) else None,
        "n_in": 0,
        "n_contained": 0,
        "n_dropped": 0,
        "n_demoted": 0,
        "contained": [],
        "dropped": [],
        "demoted": [],
        "all": [],
    }
    if not isinstance(judge_result, dict) or base["skipped"]:
        return base
    findings = judge_result.get("findings") or []
    if not isinstance(findings, list):
        return base
    if not isinstance(bundle, dict) or bundle.get("null_everything"):
        # No substrate to re-verify against: nothing can be contained — route NOTHING (fail closed).
        base["skipped"] = "null_substrate: nothing to contain against"
        base["n_in"] = len(findings)
        return base

    base["n_in"] = len(findings)
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        checked = check_finding(finding, bundle)
        status = checked["_containment"]["status"]
        base["all"].append(checked)
        if status in _DROPPED:
            base["dropped"].append(checked)
        elif status in _DEMOTED:
            base["demoted"].append(checked)
        else:
            base["contained"].append(checked)
    base["n_contained"] = len(base["contained"])
    base["n_dropped"] = len(base["dropped"])
    base["n_demoted"] = len(base["demoted"])
    return base
