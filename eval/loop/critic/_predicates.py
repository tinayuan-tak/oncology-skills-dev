#!/usr/bin/env python3
"""eval/loop/critic/_predicates.py — shared predicate primitives for the subskill-loop critic
(SK#2303 Phase-0 WI-G, issue #2357).

This module OWNS the predicate interface #2224 later imports (per the WI-G issue note). It carries
NOTHING that resolves a verdict (SK#2091: index on L2a/L2b, never `presence_verdict` /
`driving_rule_id`) and does NO I/O beyond reading the three governed YAML vocabularies named in the
issue's context scope — it writes nothing.

Productionises ``~/subskill-loop-pilot/probe.py``'s per-family token resolution and control-roster
reads, with ONE pilot bug fixed: the pilot hard-coded ``concordance_class`` as the sole token key for
the authoritative L2b family enum. The real vocabulary (``concordance_class.enum.yaml``) carries
``families.<family>.island_key`` (the key an emitted package actually uses in
``integrated_properties``) and ``families.<family>.tokens`` (the governed token roster) — ALL
governed families currently carry ``concordance_class``. Exactly one emitted L2b island
(``cellline_heterogeneity_lineage_qualifier``) carries ``qualifier_class`` instead and is explicitly
OUT OF SCOPE for ``concordance_class.enum.yaml`` (not a concordance fold — see
``presence_claims.py`` and the enum file's own ``related_ungoverned_vocabularies`` note). This module
resolves the token key PER ISLAND (never hard-coded) and treats the qualifier family's tiny, static,
UNGOVERNED token set as its own enum — never silently merged into the main one, and never dropped as
a phantom ``(family, None)`` pair.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# The L2b token lives under exactly one of these keys, resolved PER ISLAND (never hard-coded — a
# hard-coded `concordance_class` read fabricates a phantom (family, None) pair for the one family
# that carries `qualifier_class` instead; this was a pilot bug misread as a data defect).
TOKEN_KEYS = ("concordance_class", "qualifier_class")

# A loud, distinctive sentinel for an island that carries NEITHER token key. NEVER None: a None
# token flows silently into a (family, token) index and fabricates a phantom pair.
MISSING_TOKEN = "<NO_TOKEN_KEY>"

# `cellline_heterogeneity_lineage_qualifier` is a verdict-INERT per-source qualifier, not a
# concordance fold (presence_claims.py; concordance_class.enum.yaml's own
# `related_ungoverned_vocabularies` section records the boundary). It carries NO governed enum of
# its own. One value has ever been observed live; treated here as its own tiny static enum so C1 can
# still bound it rather than skip it entirely. Extending this is a deliberate, reviewed edit, same as
# any other governed-vocabulary bump — NOT a place to silently widen on a probe false-positive.
QUALIFIER_ENUM: dict[str, set] = {
    "cellline_heterogeneity_lineage_qualifier": {"cellline_heterogeneity_is_cross_lineage"},
}

# L2a `property` class tokens that read as HIGH / LOW on the tumor-abundance axis (presence_claims.py
# `_BULK_BROAD_PRESENCE` / `_BULK_RNA_PRESENT_CLASSES` frozensets + the `broadly_low -> absent`
# collapse). Used by the CALIB probe's direction check; NOT a verdict token.
HIGH_PROPS = frozenset({"broadly_high", "subset_high", "broadly_moderate", "broadly_detected"})
LOW_PROPS = frozenset({"broadly_low", "absent", "not_detected"})


def _repo_root() -> Path:
    """Repo root resolved from this file's location (eval/loop/critic/_predicates.py -> repo root)."""
    return Path(__file__).resolve().parents[3]


def _default_contracts_root() -> Path:
    return _repo_root() / "contracts"


def resolve_token(island: dict) -> tuple:
    """Resolve ``(token_key, token)`` for one L2b island, per family (never hard-coded).

    Returns the first present key in :data:`TOKEN_KEYS` and its value; ``(None, MISSING_TOKEN)`` when
    NEITHER key is present on the island. NEVER returns a ``None`` token — that would fabricate a
    phantom ``(family, None)`` pair that silently indexes as "no token" instead of surfacing loudly."""
    if not isinstance(island, dict):
        return None, MISSING_TOKEN
    for key in TOKEN_KEYS:
        if key in island:
            return key, island.get(key)
    return None, MISSING_TOKEN


def load_l2b_enum(contracts_root: "Path | str | None" = None) -> dict:
    """Load the authoritative L2b ``(family, token)`` pair-identity enum, keyed by the island's
    EMITTED key (``families.<family>.island_key`` — the string an evidence package actually carries
    under ``integrated_properties``, NOT the human-readable family name the vocabulary groups them
    under). Returns ``{island_key: set(tokens)}``.

    Best-effort: an unreadable/absent enum yields an empty dict (callers must treat an empty enum as
    "cannot evaluate," never as "nothing is governed")."""
    root = Path(contracts_root) if contracts_root is not None else _default_contracts_root()
    enum_path = root / "vocabularies" / "concordance_class.enum.yaml"
    try:
        doc = yaml.safe_load(enum_path.read_text())
    except Exception:  # noqa: BLE001 — degrade to empty, caller decides how to treat that
        return {}
    out: dict = {}
    for fam in (doc.get("families") or {}).values():
        if not isinstance(fam, dict):
            continue
        island_key = fam.get("island_key")
        tokens = fam.get("tokens")
        if island_key and isinstance(tokens, list):
            out[island_key] = set(tokens)
    return out


def load_controls(contracts_root: "Path | str | None" = None) -> dict:
    """Load the curated tumor-presence control roster (``tumor_presence_controls.yaml``) into
    ``{gene: (role, negative_except_lineage|None)}``. Positive controls carry role
    ``"tumor_antigen"``; negative controls carry their own declared ``role``
    (``housekeeping`` / ``lineage_marker`` / ``silent``) plus an optional
    ``negative_except_lineage`` scope guard."""
    root = Path(contracts_root) if contracts_root is not None else _default_contracts_root()
    ctrl_path = root / "vocabularies" / "tumor_presence_controls.yaml"
    try:
        doc = yaml.safe_load(ctrl_path.read_text())
    except Exception:  # noqa: BLE001
        return {}
    roles: dict = {}
    for gene, entry in (doc.get("positive_controls") or {}).items():
        if isinstance(entry, dict):
            roles[gene] = (entry.get("role") or "positive", None)
    for gene, entry in (doc.get("negative_controls") or {}).items():
        if isinstance(entry, dict):
            roles[gene] = (entry.get("role"), entry.get("negative_except_lineage"))
    return roles


def load_indication_tissue(contracts_root: "Path | str | None" = None) -> dict:
    """Load ``indication_crosswalk.yaml`` into ``{canonical_code: gtex_normal_tissue}`` — the scope
    map CALIB uses to honour a ``negative_except_lineage`` guard (a lineage marker read INSIDE its
    own lineage is not a negative)."""
    root = Path(contracts_root) if contracts_root is not None else _default_contracts_root()
    xw_path = root / "vocabularies" / "indication_crosswalk.yaml"
    try:
        doc = yaml.safe_load(xw_path.read_text())
    except Exception:  # noqa: BLE001
        return {}
    out: dict = {}
    for ind in doc.get("indications") or []:
        if isinstance(ind, dict) and ind.get("canonical_code"):
            out[ind["canonical_code"]] = ind.get("gtex_normal_tissue")
    return out


def pct_of(source_property: "dict | None", field: str = "allgene_percentile") -> "float | None":
    """Pull a named numeric anchor (default ``allgene_percentile``) out of an L2a
    ``source_properties.<family>`` object's ``anchors`` list. Returns ``None`` when the family, its
    anchors, or the named field is absent — the CALIB probe falls back to the ``property`` class
    token in that case, never treating a missing anchor as a measured value."""
    if not isinstance(source_property, dict):
        return None
    for a in source_property.get("anchors") or []:
        if isinstance(a, dict) and a.get("field") == field:
            val = a.get("value")
            return val if isinstance(val, (int, float)) else None
    return None
