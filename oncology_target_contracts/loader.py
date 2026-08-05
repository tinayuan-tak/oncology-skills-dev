"""loader — resolve the contracts tree and load its artifacts.

`contracts_root()` is the single resolution point, in priority order:
  1. TARGET_CONTRACTS_ROOT env var (explicit override — dev, tests, relocation)
  2. The installed package's own location — when installed editable (`pip install -e .`)
     this IS the repo root, so the data dirs (cards/, resolvers/, …) sit right beside
     the package dir. This is the Tier-1 "installed, no sibling-path" path.
  3. The canonical sibling-repo default (the shared SageMaker layout).

The loaders mirror the exact read patterns existing consumers use
(`root / <subdir> / <file>` + `yaml.safe_load`), so results are identical whether a
caller uses this API or its own current reader. This package is ADDITIVE — it does not
change how any existing consumer reads today.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

_ENV = "TARGET_CONTRACTS_ROOT"
_CANONICAL_DEFAULT = Path(
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"
)

# The package lives at <contracts-repo-root>/oncology_target_contracts/, so the repo
# root — where cards/, resolvers/, schemas/, vocabularies/, dashboards/ live — is the
# package dir's parent. For an editable install this resolves to the real repo tree.
_PKG_DIR = Path(__file__).resolve().parent
_REPO_ROOT_FROM_PKG = _PKG_DIR.parent


def _has_contracts_layout(p: Path) -> bool:
    """A directory 'is' the contracts tree if it carries the cards/ subdir."""
    return (p / "cards").is_dir()


@lru_cache(maxsize=1)
def contracts_root() -> Path:
    """Resolve the contracts tree root. See module docstring for priority order."""
    override = os.environ.get(_ENV)
    if override:
        return Path(override)
    if _has_contracts_layout(_REPO_ROOT_FROM_PKG):
        return _REPO_ROOT_FROM_PKG
    return _CANONICAL_DEFAULT


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"contract artifact not found: {path}")
    return yaml.safe_load(path.read_text())


def load_card(card_id: str, root: Optional[Path] = None) -> dict:
    """Load one evidence card by id (without the .card.yaml suffix)."""
    root = root or contracts_root()
    return _load_yaml(root / "cards" / f"{card_id}.card.yaml")


def load_resolver(gate: str, root: Optional[Path] = None) -> Optional[dict]:
    """Load a per-gate resolver spec, or None if the gate has no resolver."""
    root = root or contracts_root()
    path = root / "resolvers" / f"{gate}.resolver.yaml"
    if not path.exists():
        return None
    return _load_yaml(path)


def load_interpretation_rules(name: str, root: Optional[Path] = None) -> dict:
    """Load an interpretation-rules set (e.g. 'intracellular-intrinsic')."""
    root = root or contracts_root()
    return _load_yaml(root / "interpretation-rules" / f"{name}.rules.yaml")


def load_schema(name: str, root: Optional[Path] = None) -> dict:
    """Load a JSON schema by name (with or without the .schema.json suffix).

    Also resolves product schemas under schemas/products/ when a bare name is given.
    """
    import json

    root = root or contracts_root()
    fname = name if name.endswith(".json") else f"{name}.schema.json"
    candidates = [root / "schemas" / fname, root / "schemas" / "products" / fname]
    for c in candidates:
        if c.exists():
            return json.loads(c.read_text())
    raise FileNotFoundError(f"schema not found: {name} (looked in {[str(c) for c in candidates]})")


def load_vocabulary(name: str, root: Optional[Path] = None) -> dict:
    """Load a controlled-vocabulary file (accepts bare name or full filename)."""
    root = root or contracts_root()
    vocab_dir = root / "vocabularies"
    if (vocab_dir / name).exists():
        return _load_yaml(vocab_dir / name)
    # try common suffixes for a bare name
    for suffix in (".yaml", ".enum.yaml", ".yml"):
        p = vocab_dir / f"{name}{suffix}"
        if p.exists():
            return _load_yaml(p)
    raise FileNotFoundError(f"vocabulary not found: {name} (in {vocab_dir})")


def load_dashboard_spec(name: str, root: Optional[Path] = None) -> dict:
    """Load a dashboard spec by id (without the .dashboard_spec.yaml suffix)."""
    root = root or contracts_root()
    return _load_yaml(root / "dashboards" / f"{name}.dashboard_spec.yaml")


def load_modality_module(modality: str, root: Optional[Path] = None) -> dict:
    """Load a per-modality module (e.g. 'adc', 'bite_tce', 'small_molecule')."""
    root = root or contracts_root()
    return _load_yaml(root / "dashboards" / "modality-modules" / f"{modality}.module.yaml")


def iter_card_ids(root: Optional[Path] = None) -> list[str]:
    """Return all card ids present in the contracts tree, sorted."""
    root = root or contracts_root()
    return sorted(p.name[: -len(".card.yaml")] for p in (root / "cards").glob("*.card.yaml"))
