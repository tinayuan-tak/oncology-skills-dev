"""Governance release-fingerprint enrichment (envelope.resolved_release_governance, 2026-08-12).

Hermetic: injects fake resolve_release + family_of, so no real data-catalog is needed. Covers the
digest (data fingerprint from the manifests actually read), per-family head + is_stale drift flag,
exclusion of excluded/empty cards, and fail-open on a per-family resolver error.
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.envelope import resolved_release_governance  # noqa: E402


def _card(card_id, manifests, excluded=False):
    if excluded:
        return {"card_id": card_id, "excluded_by_applies_when": True}
    return {"card_id": card_id, "provenance": {"input_manifest_ids": list(manifests)}}


# fake family_of: strip a trailing -<rel> token (mimics catalog_query._family_of)
def _fam(mid):
    import re
    return re.sub(r"-\d{2}q\d$", "", re.sub(r"-v\d+$", "", mid))


def test_empty_when_no_manifests():
    assert resolved_release_governance([_card("c", [], excluded=True), _card("d", [])],
                                       "latest_approved", None,
                                       resolve_release=lambda *a, **k: "x", family_of=_fam) == {}


def test_digest_is_deterministic_over_used_set():
    cards = [_card("a", ["depmap-chronos-26q1", "tcga-mc3-v2"]), _card("b", ["tcga-mc3-v2"])]
    heads = {"depmap-chronos": "depmap-chronos-26q1", "tcga-mc3": "tcga-mc3-v2"}
    g1 = resolved_release_governance(cards, "latest_approved", None,
                                     resolve_release=lambda f, m, p: heads[f], family_of=_fam)
    # reordered cards / duplicate manifest → identical digest (keyed on the sorted used SET)
    g2 = resolved_release_governance(list(reversed(cards)), "latest_approved", None,
                                     resolve_release=lambda f, m, p: heads[f], family_of=_fam)
    assert g1["resolved_release_digest"] == g2["resolved_release_digest"]
    assert len(g1["resolved_release_digest"]) == 16


def test_head_and_not_stale_when_run_used_the_head():
    cards = [_card("a", ["depmap-chronos-26q1"])]
    g = resolved_release_governance(cards, "latest_approved", None,
                                    resolve_release=lambda f, m, p: "depmap-chronos-26q1", family_of=_fam)
    fam = g["resolved_releases"]["depmap-chronos"]
    assert fam["used"] == ["depmap-chronos-26q1"]
    assert fam["head"] == "depmap-chronos-26q1"
    assert fam["is_stale"] is False


def test_is_stale_when_run_used_a_superseded_release():
    cards = [_card("a", ["depmap-chronos-25q4"])]
    g = resolved_release_governance(cards, "latest_approved", None,
                                    resolve_release=lambda f, m, p: "depmap-chronos-26q1", family_of=_fam)
    fam = g["resolved_releases"]["depmap-chronos"]
    assert fam["head"] == "depmap-chronos-26q1"
    assert fam["is_stale"] is True   # the drift signal


def test_excluded_cards_contribute_nothing():
    cards = [_card("live", ["fam-a-v1"]), _card("skip", ["fam-b-v1"], excluded=True)]
    g = resolved_release_governance(cards, "latest_approved", None,
                                    resolve_release=lambda f, m, p: f + "-v1", family_of=_fam)
    assert set(g["resolved_releases"]) == {"fam-a"}   # excluded card's manifest absent


def test_fail_open_on_resolver_error():
    """A per-family resolution error records head=None + resolution_error; it must NOT raise (governance
    must never block package emission), and the digest is still present."""
    def _boom(f, m, p):
        raise RuntimeError("catalog exploded")
    g = resolved_release_governance([_card("a", ["fam-x-v1"])], "latest_approved", None,
                                    resolve_release=_boom, family_of=_fam)
    assert g["resolved_release_digest"]
    fam = g["resolved_releases"]["fam-x"]
    assert fam["head"] is None and "catalog exploded" in fam["resolution_error"]


# ── O4: honest is_stale for product-id-declared families on the ENVELOPE path ──────────────────────
# The card provenance declares products.yaml product_ids (not concrete manifest ids), so is_stale =
# (head not in used) is trivially True even when the run read the head. The refinement (opt-in via
# refine_product_id_staleness) makes staleness honest. On the schema-bound evidence_package envelope,
# governance.resolved_releases[*].is_stale is typed `boolean`, so the refinement OMITS is_stale (dropping
# the false True) + adds a stale_indeterminate marker — NOT is_stale=None (which would fail schema).

import _skills_common.envelope as _env  # noqa: E402


def test_refine_off_by_default_keeps_false_stale_for_product_id_family(monkeypatch):
    """DEFAULT (refine=False) — compose-dashboard's byte-golden path — is UNCHANGED: a product-id
    family still carries a boolean is_stale (the trivially-True value), no stale_indeterminate."""
    monkeypatch.setattr(_env, "_known_manifest_ids", lambda: {"coadread-dge-df06320"})
    g = resolved_release_governance(
        [_card("c", ["expression-rna-tumor-vs-adjacent"])], "latest_approved", None,
        resolve_release=lambda f, m, p: "coadread-dge-df06320", family_of=_fam)
    entry = next(iter(g["resolved_releases"].values()))
    assert entry["is_stale"] is True                     # unchanged (false-stale preserved for byte-golden)
    assert "stale_indeterminate" not in entry


def test_refine_marks_product_id_family_indeterminate_schema_safe(monkeypatch):
    """OPT-IN (refine=True) — target-profile's --emit path: the product-id family's is_stale is OMITTED
    (schema-safe; the schema types it boolean) and a stale_indeterminate marker is added."""
    monkeypatch.setattr(_env, "_known_manifest_ids", lambda: {"coadread-dge-df06320"})
    g = resolved_release_governance(
        [_card("c", ["expression-rna-tumor-vs-adjacent"])], "latest_approved", None,
        resolve_release=lambda f, m, p: "coadread-dge-df06320", family_of=_fam,
        refine_product_id_staleness=True)
    entry = next(iter(g["resolved_releases"].values()))
    assert "is_stale" not in entry, f"is_stale must be OMITTED (not None) on the schema-bound envelope: {entry}"
    assert entry["stale_indeterminate"] == "product_id_declared_not_concrete_manifest"
    assert entry["head"] == "coadread-dge-df06320"       # resolution itself still names the head


def test_refine_leaves_concrete_manifest_family_boolean(monkeypatch):
    """The refinement touches ONLY product-id families — a concrete manifest id keeps a real bool
    is_stale even under refine=True."""
    monkeypatch.setattr(_env, "_known_manifest_ids", lambda: {"depmap-chronos-26q1"})
    g = resolved_release_governance(
        [_card("c", ["depmap-chronos-26q1"])], "latest_approved", None,
        resolve_release=lambda f, m, p: "depmap-chronos-26q1", family_of=_fam,
        refine_product_id_staleness=True)
    entry = g["resolved_releases"]["depmap-chronos"]
    assert entry["is_stale"] is False
    assert "stale_indeterminate" not in entry


def test_refine_noop_when_catalog_unavailable(monkeypatch):
    """No catalog (_known_manifest_ids None) → cannot distinguish product_id from manifest id → refine
    is a no-op, is_stale stays boolean (fail-open)."""
    monkeypatch.setattr(_env, "_known_manifest_ids", lambda: None)
    g = resolved_release_governance(
        [_card("c", ["expression-rna-tumor-vs-adjacent"])], "latest_approved", None,
        resolve_release=lambda f, m, p: "coadread-dge-df06320", family_of=_fam,
        refine_product_id_staleness=True)
    entry = next(iter(g["resolved_releases"].values()))
    assert isinstance(entry["is_stale"], bool)


def test_digest_only_when_catalog_helper_unavailable():
    """If no resolver is injected AND the lazy import fails, the digest still emits (fingerprint is
    computable without the catalog) but resolved_releases is omitted. We simulate 'unavailable' by
    injecting family_of but a resolve_release that is None → both must be present to enrich, else
    digest-only."""
    g = resolved_release_governance([_card("a", ["fam-x-v1"])], "latest_approved", None,
                                    resolve_release=None, family_of=_fam)
    # resolve_release None triggers the lazy import; in CI the real catalog_query may or may not
    # resolve fam-x. Either way the digest MUST be present and the call must not raise.
    assert "resolved_release_digest" in g
