"""Tests for the required_inputs[].product_id referential-integrity check in validate_cards.py.

A product_id must resolve to EITHER a data-catalog manifest id OR a registered products.yaml
product id. The check is WARNING-only (never an error — an un-materialized/placeholder product is a
tracked roadmap gap, not a schema violation) and GRACEFUL-SKIPS when the sibling data-catalog is
absent (a checkout-only CI runner can't distinguish a valid manifest id from a typo). Hermetic: the
manifest-id / product-id sets are monkeypatched so the tests don't depend on the sibling's contents.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _load(mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, REPO / "validators" / f"{mod_name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


VC = _load("validate_cards")


def _base_card(**overrides) -> dict:
    card = {
        "card_id": "synthetic-test-card",
        "version": "1.0.0",
        "question": "Synthetic card question for {target.symbol} in {indication.label}?",
        "applies_when": ["target.depmap_screened == true"],
        "required_inputs": [{"product_id": "some-manifest-v1"}],
        "methods": [{"call": "depmap-chronos"}],
        "outputs": {"summary_fields": ["median_chronos_panel"]},
        "caveats": ["A caveat long enough to satisfy the minLength constraint."],
        "schema_version": 1,
    }
    card.update(overrides)
    return card


def _validate(tmp_path: Path, card: dict) -> "VC.ValidationReport":
    p = tmp_path / "synthetic.card.yaml"
    p.write_text(yaml.safe_dump(card))
    return VC.validate_card_file(p)


def _warns(r) -> str:
    return "\n".join(r.warnings)


def _errs(r) -> str:
    return "\n".join(r.errors)


def _catalog(monkeypatch, manifests, products=frozenset()):
    monkeypatch.setattr(VC, "_data_catalog_manifest_ids", lambda: set(manifests))
    monkeypatch.setattr(VC, "_registered_product_ids", lambda: set(products))


def test_product_id_resolving_to_manifest_is_clean(tmp_path, monkeypatch):
    _catalog(monkeypatch, {"some-manifest-v1"})
    r = _validate(tmp_path, _base_card())
    assert r.ok, _errs(r)
    assert "PRODUCT_ID_UNRESOLVED" not in _warns(r)


def test_product_id_resolving_to_registered_product_is_clean(tmp_path, monkeypatch):
    """The products.yaml registry is the second legitimate namespace (not just manifests)."""
    _catalog(monkeypatch, {"other-v1"}, {"expression-rna-tumor-vs-adjacent"})
    r = _validate(tmp_path, _base_card(
        required_inputs=[{"product_id": "expression-rna-tumor-vs-adjacent"}]))
    assert r.ok, _errs(r)
    assert "PRODUCT_ID_UNRESOLVED" not in _warns(r)


def test_unresolved_product_id_is_warning_not_error(tmp_path, monkeypatch):
    """A truncated/renamed manifest ref (real drift: `depmap-predictability` for the real
    `depmap-predictability-26q1-v2`) warns but never errors."""
    _catalog(monkeypatch, {"depmap-predictability-26q1-v2"})
    r = _validate(tmp_path, _base_card(required_inputs=[{"product_id": "depmap-predictability"}]))
    assert r.ok  # WARNING, never an error (would otherwise red --strict-warnings CI)
    assert "PRODUCT_ID_UNRESOLVED" in _warns(r)
    assert "depmap-predictability" in _warns(r)


def test_template_placeholder_product_id_is_skipped(tmp_path, monkeypatch):
    """A {…} template placeholder is resolved at compose time, not here — must not warn."""
    _catalog(monkeypatch, {"real-manifest-v1"})
    r = _validate(tmp_path, _base_card(required_inputs=[{"product_id": "{release_pin}-somatic"}]))
    assert r.ok, _errs(r)
    assert "PRODUCT_ID_UNRESOLVED" not in _warns(r)


def test_graceful_skip_when_data_catalog_absent(tmp_path, monkeypatch):
    """Sibling data-catalog absent (checkout-only CI) → skip; a valid manifest id can't be told
    from a typo without the manifest list, so the check must never false-fail in isolation."""
    monkeypatch.setattr(VC, "_data_catalog_manifest_ids", lambda: None)
    r = _validate(tmp_path, _base_card(required_inputs=[{"product_id": "definitely-not-real"}]))
    assert r.ok, _errs(r)
    assert "PRODUCT_ID_UNRESOLVED" not in _warns(r)


def test_real_catalog_loader_smoke():
    """If the sibling data-catalog is present, the loader yields a non-empty manifest-id set
    (guards against a path/glob regression silently disabling the check)."""
    ids = VC._data_catalog_manifest_ids()
    if ids is None:
        return  # sibling absent in this checkout — nothing to assert
    assert isinstance(ids, set) and ids, "data-catalog present but yielded no manifest ids"
