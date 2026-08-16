"""measurement_types — the read-side PULL resolver over the governed measurement-type registry.

DATA_TO_SKILL_CONTRACT.md (2026-07-21) inverts data→skill wiring to PULL: a gate declares the
`measurement_type` CLAIMS it needs (`composition.measurement_types_pulled` in its SKILL.md); the
registry (target-contracts/vocabularies/measurement_types.yaml) declares which PROVIDERS supply each
type. This module is the resolver that MATCHES the two — the "resolver matches on type" of the doc's
migration step 5.

SCOPE (deliberate, migration-safe): this is a READ-SIDE resolver + consistency layer. It does NOT
replace the card_id/dispatcher wiring that actually runs methods (that stays the live path during
migration, per the doc — "resolver matches on type, falling back to product_id/card_id"). What it
adds is: (1) resolve a pulled type → its registered providers, (2) classify each pull's status
(live_provider | registered_no_live_provider | unregistered), so a gate's pull-intent is queryable
and machine-checkable against the registry. This is how `surface_confirmation` being "pulled but
data-blocked" becomes a first-class visible state rather than a silent gap.

Cross-repo: reads target-contracts. Graceful — raises a clear error only when explicitly asked to
resolve and the registry is unreachable; the consistency helpers return an empty/None sentinel so a
skills-only checkout never hard-fails.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

_REGISTRY_ENV_VAR = "MEASUREMENT_TYPES_YAML"
_REGISTRY_DEFAULT_RELATIVE = (
    "rnd-computational-biology-oncology-target-contracts/"
    "vocabularies/measurement_types.yaml"
)

# Pull-status vocabulary — the classification of a single (gate pulls type X) edge.
STATUS_LIVE = "live_provider"                       # >=1 registered provider (a dataset or derived) exists
STATUS_NO_LIVE = "registered_no_live_provider"      # type registered but every provider is a placeholder
STATUS_UNREGISTERED = "unregistered"                # the pulled type is not in the registry at all (a defect)


def _resolve_registry_path() -> Optional[Path]:
    """Find measurement_types.yaml. Priority: env var → cwd/$HOME/relative → walk up from here.
    Returns None (not raise) if unfound, so consistency helpers can graceful-skip."""
    env = os.environ.get(_REGISTRY_ENV_VAR)
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in [here] + list(here.parents):
        candidate = parent / _REGISTRY_DEFAULT_RELATIVE
        if candidate.exists():
            return candidate
        alt = parent / "vocabularies" / "measurement_types.yaml"
        if alt.exists():
            return alt
    for c in (Path.cwd() / _REGISTRY_DEFAULT_RELATIVE, Path.home() / _REGISTRY_DEFAULT_RELATIVE):
        if c.exists():
            return c
    return None


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


def registered_types() -> Optional[set[str]]:
    """The set of registered measurement_type keys, or None if the registry is unreachable."""
    doc = _load_registry()
    return set(doc["measurement_types"]) if doc else None


def _providers(type_key: str) -> list[dict]:
    doc = _load_registry()
    if not doc:
        return []
    return (doc["measurement_types"].get(type_key) or {}).get("providers") or []


def _has_live_provider(type_key: str) -> bool:
    """A type has a live provider if any provider isn't a placeholder source. `derived_from`
    providers are live iff their inputs are (checked transitively, one level — the registry validator
    guarantees acyclicity, and deep chains here are rare)."""
    for p in _providers(type_key):
        if p.get("kind") == "dataset":
            if str(p.get("source", "")).strip().lower() not in ("placeholder", ""):
                return True
        elif p.get("kind") == "derived_from":
            inputs = p.get("inputs") or []
            if inputs and all(_has_live_provider(i) for i in inputs):
                return True
    return False


@dataclass(frozen=True)
class PullResolution:
    """The resolution of one (gate → measurement_type) pull edge."""
    measurement_type: str
    status: str                       # STATUS_LIVE | STATUS_NO_LIVE | STATUS_UNREGISTERED
    provider_sources: tuple           # the source names (or derived input-lists) backing this type

    @property
    def is_registered(self) -> bool:
        return self.status != STATUS_UNREGISTERED


def resolve_pull(type_key: str) -> PullResolution:
    """Resolve one pulled measurement_type against the registry.

    Raises FileNotFoundError only if the registry is genuinely unreachable — callers that want a
    graceful path should gate on `registered_types() is not None` first."""
    reg = registered_types()
    if reg is None:
        raise FileNotFoundError(
            "measurement_types.yaml not reachable; set MEASUREMENT_TYPES_YAML or check out "
            "target-contracts alongside the skills repo.")
    if type_key not in reg:
        return PullResolution(type_key, STATUS_UNREGISTERED, ())
    sources = []
    for p in _providers(type_key):
        if p.get("kind") == "dataset":
            sources.append(p.get("source"))
        elif p.get("kind") == "derived_from":
            sources.append("derived:" + "+".join(p.get("inputs") or []))
    status = STATUS_LIVE if _has_live_provider(type_key) else STATUS_NO_LIVE
    return PullResolution(type_key, status, tuple(sources))


def resolve_pulled_types(pulled: list[str]) -> list[PullResolution]:
    """Resolve a gate's full `measurement_types_pulled` list. Order-preserving."""
    return [resolve_pull(t) for t in pulled]


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
        for cid in ((spec or {}).get("cards") or []):
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
