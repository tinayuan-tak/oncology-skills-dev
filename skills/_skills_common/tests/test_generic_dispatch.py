"""T11 (2026-08-11 engineering review): the generic (data-driven) dispatcher.

_live_readers.py was a 1842-line god-file with ~92 hand-written _dispatch_* functions, ~30 of them
pure passthroughs (mod = _import_method(X); return mod.read_Y(target=, indication=)) that duplicate
the card→method mapping already declared in the card_spec. The generic dispatcher lets a card
declare `module` + `entrypoint` in its card_spec and be routed WITHOUT a bespoke function, collapsing
those passthroughs into data. This pins: (a) a generic-wired card resolves via _generic_dispatch,
(b) it returns the SAME result as a direct method call, (c) an unwired card still returns None.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # skills/ — _live_readers in _skills_common

from _skills_common import _live_readers as lr  # noqa: E402
from conftest import skip_if_no_data  # noqa: E402  (T10: live-S3 skip guard)

_CONTRACTS = Path(
    os.environ.get(
        "TARGET_CONTRACTS_ROOT",
        "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts",
    )
)

# ppi-interactome is the reference generic-wired card (module+entrypoint in its card_spec, and its
# bespoke dispatcher was removed). Skip if this contracts checkout predates that wiring.
_PPI_CARD = _CONTRACTS / "cards" / "ppi-interactome.card.yaml"


def _ppi_generic_wired() -> bool:
    if not _PPI_CARD.exists():
        return False
    import yaml

    spec = yaml.safe_load(_PPI_CARD.read_text()) or {}
    has_entrypoint = any(m.get("entrypoint") for m in (spec.get("methods") or []) if isinstance(m, dict))
    return has_entrypoint and "ppi-interactome" not in lr.CARD_DISPATCHERS


pytestmark = pytest.mark.skipif(
    not _ppi_generic_wired(),
    reason="ppi-interactome not generic-wired in this contracts checkout (T11 not landed here)",
)


def test_generic_dispatch_resolves_wired_card():
    # LIVE read (reads the ppi-interactome S3 product). skip_if_no_data skips — never fails —
    # when creds/data are unavailable (e.g. skills CI has no AWS creds); the reader now re-raises
    # NoCredentialsError instead of masking it, so an unguarded read would hard-fail. (2026-08-15)
    r = skip_if_no_data(lambda: lr.read_live_summary("ppi-interactome", "KRAS", "COADREAD"))
    assert r is not None, "generic dispatch returned None for a module+entrypoint card"


def test_generic_matches_direct_method_call():
    """The generic path must produce byte-identical output to calling the method directly (the old
    bespoke dispatcher's behavior) — proving the collapse is behavior-preserving.

    Genuinely-LIVE: compares two real reads of the ppi-interactome product. Cannot be mocked
    hermetic (that would make the equivalence tautological), so it self-skips creds/data-less
    via skip_if_no_data (2026-08-15) — the reader re-raises NoCredentialsError, which would
    otherwise hard-fail in a creds-less CI."""
    direct = skip_if_no_data(
        lambda: lr._import_method("ppi_interactome").read_target_summary(target="KRAS", indication="COADREAD")
    )
    generic = skip_if_no_data(lambda: lr.read_live_summary("ppi-interactome", "KRAS", "COADREAD"))
    assert generic == direct


def test_unwired_card_still_returns_none():
    """A card_id with neither a bespoke dispatcher nor generic wiring must still resolve to None
    (so the caller stubs/marks-failed) — the generic path must not mask genuine unwiring."""
    assert lr.read_live_summary("no-such-card-xyz-123", "KRAS", "COADREAD") is None


def test_generic_dispatch_direct_helper():
    """_generic_dispatch resolves module+entrypoint from the card_spec directly."""
    r = skip_if_no_data(lambda: lr._generic_dispatch("ppi-interactome", "KRAS", "COADREAD"))
    assert r is not None and isinstance(r, dict)
