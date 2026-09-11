"""Tests for the required_inputs[].product_id referential-integrity check in validate_cards.py.

A product_id must resolve to one of FIVE namespaces: a data-catalog manifest id, a manifest's own
declared Analysis-Product `product_id:`, a registered vocabularies/products.yaml product id, a
non-manifest catalog-class input (subgroup-catalog / target-id-resolver-release), or — only when the
entry supplies a `release_pin` — a release-stripped manifest-id stem. The check is WARNING-only
(never an error — an un-materialized/placeholder product is a tracked roadmap gap, not a schema
violation) and GRACEFUL-SKIPS when the sibling data-catalog is absent (a checkout-only CI runner
can't distinguish a valid manifest id from a typo). Hermetic: ALL FIVE sets are monkeypatched so the
tests don't depend on the sibling's contents — a test that patched only some of them would silently
start consulting the real catalog when a namespace was added.
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


def _catalog(
    monkeypatch,
    manifests,
    products=frozenset(),
    declared=frozenset(),
    catalog_class=frozenset(),
    stems=frozenset(),
):
    monkeypatch.setattr(VC, "_data_catalog_manifest_ids", lambda: set(manifests))
    monkeypatch.setattr(VC, "_registered_product_ids", lambda: set(products))
    monkeypatch.setattr(VC, "_manifest_declared_product_ids", lambda: set(declared))
    monkeypatch.setattr(VC, "_catalog_class_input_ids", lambda: set(catalog_class))
    monkeypatch.setattr(VC, "_manifest_id_release_stems", lambda: set(stems))


def test_product_id_resolving_to_manifest_is_clean(tmp_path, monkeypatch):
    _catalog(monkeypatch, {"some-manifest-v1"})
    r = _validate(tmp_path, _base_card())
    assert r.ok, _errs(r)
    assert "PRODUCT_ID_UNRESOLVED" not in _warns(r)


def test_product_id_resolving_to_registered_product_is_clean(tmp_path, monkeypatch):
    """The products.yaml registry is the second legitimate namespace (not just manifests)."""
    _catalog(monkeypatch, {"other-v1"}, {"expression-rna-tumor-vs-adjacent"})
    r = _validate(tmp_path, _base_card(required_inputs=[{"product_id": "expression-rna-tumor-vs-adjacent"}]))
    assert r.ok, _errs(r)
    assert "PRODUCT_ID_UNRESOLVED" not in _warns(r)


def test_product_id_resolving_to_manifest_declared_analysis_product_is_clean(tmp_path, monkeypatch):
    """A DERIVED manifest may declare which registered Analysis Product it is an instance of
    (`depmap-predictability-26q1-v3.yaml` → `product_id: depmap-predictability`). A card naming that
    id is correct. Before 2026-09-11 this namespace was unknown to the check and every such card was
    reported as an unresolvable typo."""
    _catalog(monkeypatch, {"depmap-predictability-26q1-v3"}, declared={"depmap-predictability"})
    r = _validate(
        tmp_path,
        _base_card(required_inputs=[{"product_id": "depmap-predictability", "release_pin": "{release_pin}"}]),
    )
    assert r.ok, _errs(r)
    assert "PRODUCT_ID_UNRESOLVED" not in _warns(r)


def test_release_pinned_ref_resolves_to_a_stripped_manifest_stem(tmp_path, monkeypatch):
    """The unversioned-logical-dataset case. `mutation-hotspot-frequency` names
    `gdc-pancohort-somatic` + `release_pin: {release_pin}`; the only manifest is the release-pinned
    `gdc-pancohort-somatic-dr45-0`. Naming the pinned id instead would freeze the card to dr45.0, and
    the catalog has no field to express the alias — `product_id:` there means "instance of a
    registered Analysis Product" and its schema permits it only on DERIVED manifests, so a source
    release cannot declare one. The stem is therefore derived from the manifest id here."""
    _catalog(monkeypatch, {"gdc-pancohort-somatic-dr45-0"}, stems={"gdc-pancohort-somatic"})
    r = _validate(
        tmp_path,
        _base_card(required_inputs=[{"product_id": "gdc-pancohort-somatic", "release_pin": "{release_pin}"}]),
    )
    assert r.ok, _errs(r)
    assert "PRODUCT_ID_UNRESOLVED" not in _warns(r)


def test_stem_does_not_resolve_without_a_release_pin(tmp_path, monkeypatch):
    """The release_pin gate is what stops namespace 5 from degenerating into prefix matching. Without
    one, nothing pins the ref to a real artifact and the stem must NOT be accepted — otherwise any
    truncation of a versioned id (`hpa-normal-tissue-expression` for a card that meant the v1
    manifest and supplies no release) would silently pass."""
    _catalog(monkeypatch, {"gdc-pancohort-somatic-dr45-0"}, stems={"gdc-pancohort-somatic"})
    r = _validate(tmp_path, _base_card(required_inputs=[{"product_id": "gdc-pancohort-somatic"}]))
    assert r.ok  # still a warning, never an error
    assert "PRODUCT_ID_UNRESOLVED" in _warns(r)


def test_catalog_class_input_is_clean(tmp_path, monkeypatch):
    """`subgroup-catalog` is not a dataset and has no manifest — it is the per-indication registry at
    data-catalog/subgroup-catalogs/<IND>/. Six subgroup-stratified cards require it and all six fire."""
    _catalog(monkeypatch, {"other-v1"}, catalog_class={"subgroup-catalog"})
    r = _validate(tmp_path, _base_card(required_inputs=[{"product_id": "subgroup-catalog"}]))
    assert r.ok, _errs(r)
    assert "PRODUCT_ID_UNRESOLVED" not in _warns(r)


def test_unresolved_product_id_is_warning_not_error(tmp_path, monkeypatch):
    """A product with no catalog record in ANY of the four namespaces (real case:
    `antibody-internalization-per-protein-v1`) warns but never errors."""
    _catalog(monkeypatch, {"some-other-manifest-v1"})
    r = _validate(tmp_path, _base_card(required_inputs=[{"product_id": "antibody-internalization-per-protein-v1"}]))
    assert r.ok  # WARNING, never an error (would otherwise red --strict-warnings CI)
    assert "PRODUCT_ID_UNRESOLVED" in _warns(r)
    assert "antibody-internalization-per-protein-v1" in _warns(r)


def test_warning_does_not_claim_the_read_will_fail(tmp_path, monkeypatch):
    """An unresolved product_id costs PROVENANCE, not the read: required_inputs[].product_id is
    copied verbatim into provenance.input_manifest_ids and never used to route a read (verified —
    mutation-hotspot-frequency named the then-unresolvable `gdc-pancohort-somatic` and still emitted
    validation_state=pass). The old message asserted the reader would return _live_read_error and
    degrade the verdict to insufficient, which sent readers hunting a data gap that did not exist."""
    _catalog(monkeypatch, {"some-other-manifest-v1"})
    r = _validate(tmp_path, _base_card(required_inputs=[{"product_id": "not-a-real-product"}]))
    w = _warns(r)
    assert "PRODUCT_ID_UNRESOLVED" in w
    assert "_live_read_error" not in w
    assert "degrade" not in w


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


def test_real_manifest_declared_loader_finds_the_convention():
    """The declared-product_id scan must actually find the manifests using the convention. A glob or
    prefix regression here silently re-flags every logical-product ref as a typo — the exact failure
    mode this namespace was added to fix, and one that looks like card drift rather than a tool bug."""
    if VC._data_catalog_manifest_ids() is None:
        return  # sibling absent
    declared = VC._manifest_declared_product_ids()
    assert isinstance(declared, set)
    assert "depmap-predictability" in declared, (
        "depmap-predictability-26q1-v{2,3}.yaml declare `product_id: depmap-predictability`; "
        "the scan found none, so the namespace is silently disabled"
    )


def test_real_stem_loader_strips_only_version_tokens():
    """The stem set must contain the two logical ids real cards depend on, and must NOT have eaten a
    meaningful trailing WORD: a token is stripped only when it looks like a version/release
    (`v1`, `26q1`, `dr45`, a bare integer). Over-matching is the dangerous direction — stems would
    start colliding with product names and the check would stop catching typos. Note single-token
    stems are legitimate and expected (`hpa-v25-1` → `hpa`, `chembl-37` → `chembl`); what must never
    happen is a descriptive tail being dropped."""
    if VC._data_catalog_manifest_ids() is None:
        return  # sibling absent
    stems = VC._manifest_id_release_stems()
    assert "gdc-pancohort-somatic" in stems  # from gdc-pancohort-somatic-dr45-0
    assert "hpa-normal-tissue-expression" in stems  # from hpa-normal-tissue-expression-v1
    for eaten in ("gdc-pancohort", "hpa-normal-tissue", "hpa-normal"):
        assert eaten not in stems, f"version-token regex over-matched — stripped a real word to {eaten!r}"


def test_real_catalog_class_inputs_resolve_against_the_directory():
    """catalog-class inputs are gated on the directory EXISTING, so this stays a referential check
    rather than a hardcoded allowlist that would keep passing after the catalogs were deleted."""
    if VC._data_catalog_manifest_ids() is None:
        return  # sibling absent
    assert "subgroup-catalog" in VC._catalog_class_input_ids()
