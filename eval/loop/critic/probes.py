#!/usr/bin/env python3
"""eval/loop/critic/probes.py — C1 (pair-identity) + CALIB (direction) REGRESSION probes
(SK#2303 Phase-0 WI-G, issue #2357).

Productionises ``~/subskill-loop-pilot/probe.py``. Per the epic (#2303) and this issue's own
problem statement: these two deterministic probes yield ~0 findings on a MATURE skill (tumor-presence
L2b was clean in the pilot — 67 (family, token) instances all valid), so they are DEMOTED from
discovery probes to a REGRESSION FLOOR: on a clean batch they must stay silent, and they exist to
catch a FUTURE defect (a builder emitting an off-enum token, a normaliser fabricating a phantom pair,
a calibration read flipping direction) the day one lands. ``eval/loop/tests/test_probes.py`` carries
the 5 planted-defect teeth that keep that floor trustworthy.

★★ INDEX ON THE PROPERTY LAYERS, NEVER THE VERDICT (SK#2091; epic #2303 §"hard boundaries"). Both
probes read ONLY ``source_properties`` (L2a) and ``integrated_properties`` (L2b) — neither probe
reads, diffs, or gates on ``synthesis.verdict`` / ``driving_rule_id`` / any other verdict field.

Each probe returns a list of 4-tuples ``(probe_id, severity, verdict, message)`` where ``verdict`` is
one of ``"fail"`` (a real finding) or ``"not_evaluable"`` (framework-coverage gap, e.g. a dead
package or an absent section — NEVER silently treated as a pass; NULL-not-pass semantics carry
through to the loop's convergence gate, epic WI-H). A clean, fully-populated, well-formed package
emits an EMPTY list from each probe — that silence is the regression floor's "true zero," not an
absence of effort.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
import _predicates as P  # noqa: E402


# ── Probe C1: L2b (family, token) pair-identity vs the authoritative enum ─────────────────────────
def probe_c1(evidence_package: dict, *, contracts_root: "Path | str | None" = None) -> list[tuple]:
    """For every ``integrated_properties`` island, resolve its token key PER FAMILY (never a
    hard-coded ``concordance_class`` read — that fabricates a phantom ``(family, None)`` pair for the
    one family that carries ``qualifier_class`` instead) and check the ``(island_key, token)`` pair
    against the authoritative enum (``concordance_class.enum.yaml`` for a concordance family,
    :data:`_predicates.QUALIFIER_ENUM` for the one ungoverned qualifier family).

    A missing ``integrated_properties`` section is ``not_evaluable`` (framework-coverage gap, never a
    silent pass). A token valid for some OTHER family is reported as a ROGUE PAIR (the bare-token-bug
    signature a normaliser regression would produce) rather than merely "unknown token."
    """
    ip = evidence_package.get("integrated_properties")
    if ip is None:
        return [("C1", "S2", "not_evaluable", "integrated_properties section ABSENT")]
    if not isinstance(ip, dict):
        return [("C1", "S1", "fail", "integrated_properties is not an object")]

    l2b_enum = P.load_l2b_enum(contracts_root)
    out: list[tuple] = []
    for family, island in ip.items():
        if not isinstance(island, dict):
            out.append(("C1", "S1", "fail", f"{family}: island is not an object"))
            continue
        token_key, token = P.resolve_token(island)
        if token == P.MISSING_TOKEN:
            out.append(
                (
                    "C1",
                    "S1",
                    "fail",
                    f"{family}: NO token key ({'/'.join(P.TOKEN_KEYS)}) present — would index as "
                    f"(family, None) if not caught",
                )
            )
            continue
        allowed = l2b_enum.get(family) or P.QUALIFIER_ENUM.get(family)
        if allowed is None:
            out.append(("C1", "S1", "fail", f"{family}: UNKNOWN L2b family (not in the governed enum)"))
            continue
        if token not in allowed:
            all_tables = {**l2b_enum, **P.QUALIFIER_ENUM}
            other = [f for f, toks in all_tables.items() if f != family and token in toks]
            why = f"valid for {other} not {family} — ROGUE PAIR" if other else "not in any known family's enum"
            out.append(("C1", "S1", "fail", f"{family}: token '{token}' {why}"))
    return out


# ── Probe CALIB: calibration-direction on the curated control roster (property layer) ─────────────
def probe_calib(
    evidence_package: dict,
    gene: str,
    indication: str,
    *,
    contracts_root: "Path | str | None" = None,
) -> list[tuple]:
    """For a CONTROL gene (curated in ``tumor_presence_controls.yaml``), check that its L2a
    ``patient_tumor_abundance`` property reads in the direction its curated role predicts:
    positives read HIGH, housekeeping reads at the CEILING, silent/lineage-marker (out of lineage)
    reads at the FLOOR. Silent for a non-control gene — CALIB only calibrates against the curated
    roster, it does not grade arbitrary targets.

    Honours the ``negative_except_lineage`` scope guard: a lineage marker INSIDE its own tissue is
    not a negative here (a scope-blind probe would false-positive on, e.g., SFTPC in NSCLC) —
    resolved via ``indication_crosswalk.yaml``'s ``gtex_normal_tissue``, never a second hard-coded map.
    """
    roles = P.load_controls(contracts_root)
    role, except_lineage = roles.get(gene, (None, None))
    if role is None:
        return []  # not a curated control -> CALIB is silent by design

    source_properties = evidence_package.get("source_properties")
    if not isinstance(source_properties, dict):
        return [("CALIB", "S2", "not_evaluable", f"{gene}/{indication} [{role}]: source_properties section ABSENT")]
    pta = source_properties.get("patient_tumor_abundance")
    if pta is None:
        return [("CALIB", "S2", "not_evaluable", f"{gene}/{indication} [{role}]: patient_tumor_abundance ABSENT")]
    if not isinstance(pta, dict):
        return [("CALIB", "S1", "fail", f"{gene}/{indication} [{role}]: patient_tumor_abundance is not an object")]

    prop = pta.get("property")
    pct = P.pct_of(pta)

    if role == "lineage_marker" and except_lineage:
        tissue_map = P.load_indication_tissue(contracts_root)
        if tissue_map.get(indication) == except_lineage:
            return [
                (
                    "CALIB",
                    "S3",
                    "not_evaluable",
                    f"{gene}/{indication}: lineage_marker IN its own lineage ({except_lineage}) — "
                    f"not a negative here, scope-skipped",
                )
            ]

    if role in ("tumor_antigen", "positive"):
        if prop in P.LOW_PROPS or (pct is not None and pct < 50):
            return [("CALIB", "S1", "fail", f"{gene}/{indication} POSITIVE reads low: property={prop} pct={pct}")]
    elif role == "housekeeping":  # CEILING reference
        if pct is not None and pct < 90:
            return [("CALIB", "S1", "fail", f"{gene}/{indication} HOUSEKEEPING not at ceiling: pct={pct} (<90)")]
        if prop in P.LOW_PROPS:
            return [("CALIB", "S1", "fail", f"{gene}/{indication} HOUSEKEEPING reads low: property={prop}")]
    elif role in ("silent", "lineage_marker"):  # FLOOR reference (out-of-lineage)
        if prop in P.HIGH_PROPS or (pct is not None and pct > 50):
            return [("CALIB", "S1", "fail", f"{gene}/{indication} {role} FLOOR reads high: property={prop} pct={pct}")]
    return []


__all__ = ["probe_c1", "probe_calib"]
