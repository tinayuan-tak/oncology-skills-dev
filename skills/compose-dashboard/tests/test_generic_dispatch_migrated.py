"""T11 dispatcher collapse — every generic-routed card resolves to a real callable.

After migrating 37 pure-passthrough dispatchers (their bespoke `_dispatch_*` deleted; their
card_specs now declare methods[].module + entrypoint), a card is routed by `_generic_dispatch`. This
guards the collapse WITHOUT needing S3: for every card that is generic-routed (declares an entrypoint
AND has no bespoke CARD_DISPATCHERS entry), the (module, entrypoint) must resolve to a real callable.

Of the 41 pure-passthrough candidates, 4 were deliberately KEPT bespoke (see
test_intentionally_kept_dispatchers): 3 are called INTERNALLY by composed dispatchers, and 1's method
package does not re-export its entrypoint.

Byte-equivalence rationale: `_generic_dispatch` calls `fn(target=target, indication=indication)` — the
IDENTICAL call the deleted bespoke passthrough made (`mod = _import_method(M); return
mod.EP(target=, indication=)`). So "the card resolves to the same fn `M.EP`" + "the args are the same
two kwargs" IS the behavior-preserving proof, statically (no data read, CI-safe). The live
data-equivalence proof for one card lives in test_generic_dispatch.py (ppi-interactome).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import _live_readers as lr  # noqa: E402

_CONTRACTS = Path(os.environ.get(
    "TARGET_CONTRACTS_ROOT",
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts",
))
_CARDS = _CONTRACTS / "cards"


def _generic_routed_cards() -> list[str]:
    """Cards that declare a methods[].entrypoint AND have NO bespoke dispatcher → routed generically."""
    out = []
    if not _CARDS.is_dir():
        return out
    for p in sorted(_CARDS.glob("*.card.yaml")):
        try:
            spec = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError:
            continue
        has_ep = any(isinstance(m, dict) and m.get("entrypoint") for m in (spec.get("methods") or []))
        cid = p.stem.replace(".card", "")
        if has_ep and cid not in lr.CARD_DISPATCHERS:
            out.append(cid)
    return out


_ROUTED = _generic_routed_cards()

pytestmark = pytest.mark.skipif(
    len(_ROUTED) < 35,
    reason=f"expected >=37 generic-routed cards (T11 collapse); found {len(_ROUTED)} "
           "— target-contracts checkout likely predates the module/entrypoint wiring (#329)",
)


def test_collapse_removed_the_passthrough_dispatchers():
    """The 37 migrated cards must no longer have a bespoke dispatcher (they route generically)."""
    # a representative sample of the migrated set — all must be absent from CARD_DISPATCHERS.
    for cid in ("tumor-vs-normal-selectivity", "dependency-lineage-selectivity", "gnomad-lof-constraint",
                "mutation-stratified-dependency", "reactome-pathway-membership", "target-development-level"):
        assert cid not in lr.CARD_DISPATCHERS, f"{cid} still has a bespoke dispatcher (not collapsed)"


def test_intentionally_kept_dispatchers():
    """4 of the 41 pure-passthrough candidates were deliberately NOT collapsed and must remain bespoke:
      - signaling-network-mechanism, surfaceome-family-classification, structure-features-static are
        called INTERNALLY by composed dispatchers (e.g. _dispatch_adc_tce_modality_fit), so deleting
        them would NameError at runtime — the generic path only routes top-level card reads.
      - mutation-drug-response's method package does not re-export its entrypoint
        (methods/depmap_mutation_drug_response/__init__.py), so _import_method(pkg).<entrypoint> is not
        package-accessible; both paths would AttributeError identically. Fix (add the __init__
        re-export in analysis-methods, matching ppi_interactome) is a documented follow-on.
    """
    for cid in ("signaling-network-mechanism", "surfaceome-family-classification",
                "structure-features-static", "mutation-drug-response"):
        assert cid in lr.CARD_DISPATCHERS, f"{cid} must remain a bespoke dispatcher (kept-with-reason)"


@pytest.mark.parametrize("card_id", _ROUTED)
def test_generic_routed_card_resolves_to_real_callable(card_id):
    """Every generic-routed card's (module, entrypoint) must resolve to a real callable — so
    _generic_dispatch's fn(target=, indication=) hits the same function the bespoke path did."""
    spec = yaml.safe_load((_CARDS / f"{card_id}.card.yaml").read_text()) or {}
    method = next(m for m in spec["methods"] if isinstance(m, dict) and m.get("entrypoint"))
    module = method.get("module") or method.get("call", "").replace("-", "_")
    entrypoint = method["entrypoint"]
    assert module, f"{card_id}: no module/derivable-call for generic dispatch"
    mod = lr._import_method(module)
    fn = getattr(mod, entrypoint, None)
    assert callable(fn), f"{card_id}: {module}.{entrypoint} is not a callable (generic dispatch would fail)"
