"""Session-scoped card-corpus fixtures (gate-speedup arc, #910).

Several validator tests each run the *full* card validator over all ~148 shipped
cards and then filter the resulting reports for their own findings — e.g. the
capsule live-fleet check, the product-id supersession fire-set, the measurement
entity-grains ceiling, the threshold-role sweep. Before this conftest each of
those tests rebuilt the whole `{card: report}` set independently, so the identical
`validate_card_file(path, schema)` computation ran once per test *file* (≈13-14s
apiece, the bulk of each file's wall-clock).

`validate_card_file` is a pure function of (card bytes, schema), and every caller
resolves the same `_load_schema()` (itself `@lru_cache`d), so the reports are
byte-identical no matter who computes them. We therefore compute the corpus once
per session and hand the *same* reports to every consumer. Findings stay live —
the reports are re-derived from the real card files each run (not a frozen
golden), so a genuinely broken card still surfaces in whichever test asserts on
it. See [[feedback_green_for_the_wrong_reason]]: the win is "validate once," not
"assert against a fixture that can never fail."

xdist note (#910): a `scope="session"` fixture is instantiated once *per worker*,
not once globally. Under `pytest -n auto` the win is "validate once per worker";
we deliberately do NOT try to share across workers (that is a separate, fragile
mechanism). Correctness is unaffected — worst case a worker re-validates, which is
exactly today's behavior — so the suite is green under both `-n0` and `-n auto`.

The independent `oncology_target_contracts/loader.py` `@lru_cache` caches only
`contracts_root()` (one Path), not parsed cards, so routing through it would buy
nothing here; these fixtures stay self-contained.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import MappingProxyType

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
CARDS_DIR = REPO / "cards"


def _load_validator():
    """Import validators/validate_cards.py as a module (mirrors the per-test loaders)."""
    spec = importlib.util.spec_from_file_location("_vc_conftest", REPO / "validators" / "validate_cards.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_vc_conftest"] = mod
    spec.loader.exec_module(mod)
    return mod


def _card_paths() -> list[Path]:
    # Non-recursive glob over cards/ — the shipped corpus is flat, so this matches
    # both the per-test `glob("*.card.yaml")` loops and validate_directory's rglob.
    return sorted(CARDS_DIR.glob("*.card.yaml"))


@pytest.fixture(scope="session")
def card_paths() -> tuple[Path, ...]:
    """Immutable, sorted tuple of every shipped card path."""
    return tuple(_card_paths())


@pytest.fixture(scope="session")
def card_specs(card_paths):
    """Read-only `{path: parsed_spec}` — the corpus parsed once per session.

    Serves the parse-only corpus loops (they only read fields). Structural mutation
    of the mapping is blocked via MappingProxyType; the inner dicts are documented
    read-only (no test mutates them — verified in #910).
    """
    specs = {p: (yaml.safe_load(p.read_text()) or {}) for p in card_paths}
    return MappingProxyType(specs)


@pytest.fixture(scope="session")
def cards_by_id(card_specs):
    """Read-only `{card_id: spec}` view of the parsed corpus (mirrors the old `_cards()` helper)."""
    return MappingProxyType({spec.get("card_id"): spec for spec in card_specs.values()})


@pytest.fixture(scope="session")
def card_reports(card_paths):
    """Read-only `{path: ValidationReport}` — the full validator run once per session.

    Byte-identical to each consumer's own `validate_card_file(path, schema)` loop:
    the validator is pure and every caller shares the same `_load_schema()`.
    """
    vc = _load_validator()
    schema = vc._load_schema()
    reports = {p: vc.validate_card_file(p, schema=schema) for p in card_paths}

    # Teeth against the risk #910 flags: a test accidentally mutating a shared
    # report would silently corrupt every later consumer. Snapshot the finding
    # lists at build time and assert they are untouched at session teardown, so a
    # future mutating test fails loudly instead of masking/injecting a finding.
    snapshot = {p: (tuple(r.errors), tuple(r.warnings), r.ok) for p, r in reports.items()}
    proxy = MappingProxyType(reports)
    yield proxy
    drift = [str(p) for p, r in reports.items() if (tuple(r.errors), tuple(r.warnings), r.ok) != snapshot[p]]
    assert not drift, f"a test mutated shared card_reports for: {drift}"
