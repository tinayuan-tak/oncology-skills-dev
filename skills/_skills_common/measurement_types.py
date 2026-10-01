"""measurement_types — read-side evidence-substrate resolution over the governed registry.

The registry (target-contracts/vocabularies/measurement_types.yaml) declares, per measurement_type,
which cards are a view of it (`cards:` back-refs) and an OPTIONAL `evidence_substrate: <slug>` naming
the underlying data product. This module is the read-side companion of that registry: it resolves a
card_id → its measurement_type → the type's evidence_substrate, so an emitting skill can stamp each
evidence_package card entry with (measurement_type, evidence_substrate). A cross-evidence integrator
then uses those stamps to detect which cards share an underlying data product and NOT double-count
correlated evidence toward certainty (the HTR1D expression<->selectivity trap; cross-evidence roadmap
invariant 8).

Cross-repo: reads target-contracts. Graceful — all helpers are best-effort and return None/empty when
the registry is unreachable (a skills-only checkout) or a card/type is untagged; they never raise, so a
skills-only checkout never hard-fails.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

_REGISTRY_ENV_VAR = "MEASUREMENT_TYPES_YAML"


def _resolve_registry_path() -> Optional[Path]:
    """Find measurement_types.yaml: MEASUREMENT_TYPES_YAML env override, else the target-contracts
    root (TARGET_CONTRACTS_ROOT env, else the in-tree contracts/). Returns None (never raises) if
    unfound, so the substrate helpers graceful-skip on a reachable-registry-absent checkout.

    N3-1 #2144 stage 4: was a repo-root walk onto the retired rnd-...-target-contracts geometry
    symlink + a Path.home() clone — which resolved on a dev box but NOT in a fresh CI checkout.
    """
    env = os.environ.get(_REGISTRY_ENV_VAR)
    if env:
        return Path(env)
    from _skills_common.paths import target_contracts_root

    p = target_contracts_root() / "vocabularies" / "measurement_types.yaml"
    return p if p.exists() else None


@lru_cache(maxsize=1)
def _load_registry() -> Optional[dict]:
    """Parse the registry once. None if unreachable (skills-only checkout)."""
    import yaml

    path = _resolve_registry_path()
    if path is None:
        return None
    try:
        with path.open() as f:
            doc = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError):
        return None
    if not isinstance(doc.get("measurement_types"), dict):
        return None
    return doc


# --- evidence-substrate resolution (cross-evidence roadmap invariant 8) -----------------------
# The read-side companion of the registry's OPTIONAL `evidence_substrate: <slug>` per type + the
# `evidence_substrates:` controlled vocab. Lets an emitting skill stamp each evidence_package card
# entry with (measurement_type, evidence_substrate) so a cross-evidence integrator can detect which
# cards share underlying data products and NOT double-count correlated evidence toward certainty (the
# HTR1D expression<->selectivity trap). All helpers are best-effort: None/empty when the registry is
# unreachable (a skills-only checkout) or the card/type is untagged — never raise.


@lru_cache(maxsize=1)
def _card_to_type_map() -> dict:
    """{card_id -> measurement_type} from the registry's per-type `cards:` back-refs.
    Empty dict if the registry is unreachable. (A card_id can appear under exactly one type — the
    registry validator enforces that concordance, so last-writer-wins here is a non-issue.)"""
    doc = _load_registry()
    if not doc:
        return {}
    out: dict = {}
    for mt, spec in (doc.get("measurement_types") or {}).items():
        for cid in (spec or {}).get("cards") or []:
            out[cid] = mt
    return out


def card_measurement_type(card_id: str) -> Optional[str]:
    """The measurement_type a card is a view of (via the registry `cards:` back-ref), or None."""
    return _card_to_type_map().get(card_id)


def evidence_substrate_of(type_key: str) -> Optional[str]:
    """The `evidence_substrate` slug declared on a measurement_type, or None (untagged/unreachable)."""
    doc = _load_registry()
    if not doc:
        return None
    return ((doc.get("measurement_types") or {}).get(type_key) or {}).get("evidence_substrate")


def substrate_for_card(card_id: str) -> "tuple[Optional[str], Optional[str]]":
    """(measurement_type, evidence_substrate) for a card_id — both best-effort, either may be None.

    measurement_type is None when the card is not back-referenced by any registered type (e.g. an
    un-migrated card); evidence_substrate is None when the resolved type carries no substrate tag
    (the genuinely-independent singleton case)."""
    mt = card_measurement_type(card_id)
    if mt is None:
        return None, None
    return mt, evidence_substrate_of(mt)
