"""Subskill provenance/reproducibility block (2026-08-13).

Guards the fix that routes real per-card provenance onto the subskill DEFAULT path (decision.json /
provenance.yaml), not just the opt-in evidence envelope:
  - resolve_cards stamps each card with its DECLARED input_manifest_ids (card_spec.required_inputs);
  - make_decision_json surfaces a top-level `provenance` block + per-card input_manifest_ids;
  - build_subskill_provenance single-sources that block (skills sha, data_mode/release_pin,
    resolved_release_digest + resolved_content_digest);
  - REGRESSION GUARD: resolved_content_digest is computed OUTSIDE resolved_release_governance, so the
    shared compose/target-profile envelope governance (byte-golden + engine-equivalence pinned) is
    untouched.

Hermetic — no live S3. resolved_release_governance/resolved_content_digest are best-effort (fail-open
when the catalog helper is absent), so these assert the ALWAYS-computed digests, not catalog heads.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import _skills_common as skc  # noqa: E402
import _skills_common.dispatcher as D  # noqa: E402
from _skills_common.envelope import (  # noqa: E402
    build_subskill_provenance,
    resolved_content_digest,
    resolved_release_governance,
)


def _card(cid, mids, missing=False):
    return {"card_id": cid, "summary": {}, "_missing": missing,
            "provenance": {"input_manifest_ids": list(mids)}}


# ── resolve_cards stamps declared manifest ids ──────────────────────────────

def test_resolve_cards_stamps_input_manifest_ids(monkeypatch):
    """resolve_cards must attach provenance.input_manifest_ids from the card_spec, for available AND
    missing cards, WITHOUT relying on the reader stamping _data_source."""
    monkeypatch.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    monkeypatch.setattr(skc, "_import_dispatcher",
                        lambda: (lambda cid, t, i, **k: {"foo_class": "bar"} if cid == "c-ok" else None))
    monkeypatch.setattr(skc, "card_input_manifest_ids",
                        lambda cid: ("m-1", "m-2") if cid == "c-ok" else ("m-3",))
    out = skc.resolve_cards(["c-ok", "c-missing"], "EGFR", "PANCANCER")
    by_id = {c["card_id"]: c for c in out}
    assert by_id["c-ok"]["provenance"]["input_manifest_ids"] == ["m-1", "m-2"]
    # the missing card (dispatcher returned None) still carries its DECLARED inputs
    assert by_id["c-missing"]["_missing"] is True
    assert by_id["c-missing"]["provenance"]["input_manifest_ids"] == ["m-3"]


def test_card_input_manifest_ids_reads_real_card_spec():
    """Against a checked-out target-contracts, a known card resolves its declared product_id."""
    from _skills_common.rules_loader import TARGET_CONTRACTS
    if not (TARGET_CONTRACTS / "cards" / "gnomad-lof-constraint.card.yaml").is_file():
        pytest.skip("target-contracts not checked out adjacent")
    mids = skc.card_input_manifest_ids("gnomad-lof-constraint")
    assert "gnomad-constraint-per-gene-v1" in mids


def test_card_input_manifest_ids_failopen_on_unknown():
    """Unknown/malformed card_id → empty tuple (provenance never blocks a run)."""
    assert skc.card_input_manifest_ids("no-such-card-xyz") == ()


# ── make_decision_json surfaces the block + per-card ids ────────────────────

def test_make_decision_json_carries_provenance_and_percard_ids():
    cards = [_card("c1", ["m-a"]), _card("c2", ["m-b", "m-c"])]
    prov = {"skills_repo_sha": "abc1234", "data_mode": "live", "release_pin": "unpinned"}
    d = skc.make_decision_json("s", "EGFR", "PANCANCER", "q", cards, [], {"k": 1}, provenance=prov)
    assert d["provenance"] == prov
    per_card = {c["card_id"]: c["input_manifest_ids"] for c in d["cards"]}
    assert per_card == {"c1": ["m-a"], "c2": ["m-b", "m-c"]}


def test_make_decision_json_omits_provenance_when_none():
    """Backward-compat: no provenance arg → no top-level key (older callers unaffected)."""
    d = skc.make_decision_json("s", "EGFR", "PANCANCER", "q", [_card("c1", [])], [], {})
    assert "provenance" not in d


# ── build_subskill_provenance shape + digests ───────────────────────────────

def test_build_subskill_provenance_shape():
    cards = [_card("c1", ["fam-x-v1"]), _card("c2", ["fam-y-v2"])]
    p = build_subskill_provenance(cards, "live", None, "deadbee", resolver_release_pin="resolver_v1.0.0")
    assert p["skills_repo_sha"] == "deadbee"
    assert p["data_mode"] == "live"
    assert p["release_pin"] == "unpinned"            # None normalised
    assert p["resolver_release_pin"] == "resolver_v1.0.0"
    assert len(p["resolved_release_digest"]) == 16   # always computed from declared manifest ids


def test_content_digest_deterministic_and_order_independent():
    a = resolved_content_digest([_card("c1", ["m-a"]), _card("c2", ["m-b"])])
    b = resolved_content_digest([_card("c2", ["m-b"]), _card("c1", ["m-a"])])
    assert a is not None and a == b                  # sorted → order-independent + stable


def test_content_digest_none_when_no_manifests():
    assert resolved_content_digest([_card("c1", [])]) is None


# ── (B) honest is_stale for product-id-declared families (SUBSKILL-only) ─────
# A card declares its inputs as products.yaml product_ids, so a family whose `used` ids are all
# product_ids (not concrete manifest ids) had is_stale = (head not in used) = trivially True even when
# the run read the current head. build_subskill_provenance now marks such staleness INDETERMINATE
# rather than falsely True. Subskill-only: compose-dashboard does not route through this function, so
# the byte-golden resolved_release_governance output for the composed envelope is unchanged.

def _catalog_available() -> bool:
    from _skills_common.envelope import _known_manifest_ids
    return _known_manifest_ids() is not None


def test_is_stale_indeterminate_for_product_id_declared_family():
    if not _catalog_available():
        pytest.skip("catalog resolver unavailable")
    from _skills_common.envelope import _known_manifest_ids
    pid = "expression-rna-tumor-vs-adjacent"       # a product_id, not a manifest id
    if pid in _known_manifest_ids():
        pytest.skip(f"{pid} is itself a manifest id here — not the product-id case")
    p = build_subskill_provenance([_card("tumor-rna-vs-adjacent", [pid])],
                                  "latest_approved", None, "deadbee")
    entry = (p.get("resolved_releases") or {}).get(pid)
    if entry is None or entry.get("head") is None:
        pytest.skip(f"{pid} did not resolve in this catalog checkout")
    assert entry["is_stale"] is None, f"product-id family must be indeterminate, got {entry}"
    assert entry.get("stale_indeterminate") == "product_id_declared_not_concrete_manifest"
    # the resolution itself still names the correct OUTPUT manifest head (not an error)
    assert entry["head"]


def test_is_stale_stays_boolean_for_concrete_manifest_family():
    """The refinement touches ONLY product-id families — a concrete manifest id keeps a real bool
    is_stale and carries no stale_indeterminate marker."""
    if not _catalog_available():
        pytest.skip("catalog resolver unavailable")
    from _skills_common.envelope import _known_manifest_ids
    known = _known_manifest_ids()
    concrete = "tcga-tumor-tpm-recount3-long-v1"
    if concrete not in known:
        concrete = sorted(known)[0]                # any real concrete manifest id
    p = build_subskill_provenance([_card("c", [concrete])], "latest_approved", None, "deadbee")
    entry = next(iter((p.get("resolved_releases") or {}).values()), {})
    assert isinstance(entry.get("is_stale"), bool), f"concrete family must keep a bool, got {entry}"
    assert "stale_indeterminate" not in entry


# ── REGRESSION GUARD: shared envelope governance must not gain the content digest ──

def test_resolved_release_governance_has_no_content_digest():
    """resolved_content_digest lives OUTSIDE resolved_release_governance on purpose — the shared
    function feeds the compose/target-profile envelope (byte-golden + engine-equivalence pinned).
    Re-introducing the content digest there is what broke test_end_to_end + test_engine_equivalence."""
    g = resolved_release_governance([_card("c1", ["fam-x-v1"])], "latest_approved", None)
    assert "resolved_content_digest" not in g
    assert "resolved_release_digest" in g


# ── end-to-end through the dispatcher ───────────────────────────────────────

def test_dispatcher_emits_provenance_block(monkeypatch, tmp_path):
    """run_wired_skill must attach decision['provenance'] built from the resolved cards' declared
    manifest ids — the subskill default output is reproducible without --emit-envelope."""
    cards_out = [_card("target-identity-summary", ["target-id-resolver-release"]),
                 _card("gnomad-lof-constraint", ["gnomad-constraint-per-gene-v1"])]
    cards_out[0]["summary"] = {"resolver_release_pin": "resolver_v1.0.0"}
    monkeypatch.setattr(D, "resolve_cards", lambda cards, target, indication, **k: cards_out)
    monkeypatch.setattr(D, "fired_rules", lambda card_outputs, axis, card_id_filter=None: [])
    captured = {}
    monkeypatch.setattr(D, "write_package",
                        lambda **kw: (captured.__setitem__("d", kw["decision"]), {"tables": [], "figures": []})[1])
    D.run_wired_skill(
        skill_name="target-intrinsic", skill_version="test",
        cards=["target-identity-summary", "gnomad-lof-constraint"],
        axis="intracellular_intrinsic", question="Q {target} {indication}",
        verdict_fn=None, headline_fn=lambda cards, fired, vp: {"h": 1},
        argv=["--target", "EGFR", "--out", str(tmp_path)],
    )
    prov = captured["d"]["provenance"]
    assert prov["skills_repo_sha"]                      # a real sha or the 0000000 sentinel
    assert prov["data_mode"] == "live"                  # dispatcher default
    assert prov["resolver_release_pin"] == "resolver_v1.0.0"   # lifted from the identity card
    assert len(prov["resolved_release_digest"]) == 16
