"""Accessor for the per-gate certainty-corroboration manifest (follow-on: manifest authoritative).

Reads target-contracts vocabularies/certainty_corroboration.yaml — the declarative, VERDICT-DISJOINT
corroboration-source cards per gate (CERTAINTY_MODEL). A sub-skill's certainty extractor computes its
`corroboration` from a per-axis expert call (the model forbids a generic extractor), so this manifest
can't DRIVE the extractor — but the extractor can DECLARE which card(s) it reads for corroboration and
cross-check them against this manifest, so the two can't silently drift (the check the disjointness
validator, which only compares the manifest to the resolvers, cannot make).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from _skills_common.scope import DEFAULT_CONTRACTS_REPO


def corroboration_cards(gate: str, contracts_root: Optional[Path] = None) -> frozenset:
    """The verdict-disjoint corroboration source card(s) declared for `gate` in
    certainty_corroboration.yaml, or an empty set (gate not registered / manifest unreadable)."""
    root = Path(contracts_root) if contracts_root is not None else DEFAULT_CONTRACTS_REPO
    try:
        data = yaml.safe_load((root / "vocabularies" / "certainty_corroboration.yaml").read_text())
        return frozenset((data or {}).get("corroboration_by_gate", {}).get(gate, []) or [])
    except Exception:  # noqa: BLE001 — manifest absent/unreadable → empty (caller treats as "none declared")
        return frozenset()
