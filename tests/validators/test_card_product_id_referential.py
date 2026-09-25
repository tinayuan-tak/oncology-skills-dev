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

A SIXTH set, orthogonal to the five: the supersession map (2026-09-17), which drives the separate
PRODUCT_ID_SUPERSEDED warning. It is not a namespace — it does not make an id resolve — it answers a
different question about an id that already resolves: *is this still the head of its family?* The
five-namespace check is blind to that by construction, since a superseded manifest is still on disk.
`_catalog()` patches it to EMPTY by default, which is what keeps every test written before it existed
asserting what it originally asserted.
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


def _codes(r) -> set[str]:
    """The set of warning CODES emitted — the leading token of each warning (`add_warning` appends the
    message verbatim, and every message starts with its code).

    Needed because an absence assertion against `_warns(r)` is a substring test over concatenated
    text, and one warning's message may legitimately NAME another warning's code: the
    PRODUCT_ID_SUPERSEDED message explains that the drift is invisible to PRODUCT_ID_UNRESOLVED, so
    `"PRODUCT_ID_UNRESOLVED" not in _warns(r)` fails on that explanation rather than on a real second
    warning. Same shape as a grep for a retracted string firing on the retraction itself. Assert
    codes, not substrings, whenever the claim is that a warning is ABSENT."""
    return {w.split(None, 1)[0] for w in r.warnings if w}


def _errs(r) -> str:
    return "\n".join(r.errors)


def _catalog(
    monkeypatch,
    manifests,
    products=frozenset(),
    declared=frozenset(),
    catalog_class=frozenset(),
    stems=frozenset(),
    superseded=None,
):
    monkeypatch.setattr(VC, "_data_catalog_manifest_ids", lambda: set(manifests))
    monkeypatch.setattr(VC, "_registered_product_ids", lambda: set(products))
    monkeypatch.setattr(VC, "_manifest_declared_product_ids", lambda: set(declared))
    monkeypatch.setattr(VC, "_catalog_class_input_ids", lambda: set(catalog_class))
    monkeypatch.setattr(VC, "_manifest_id_release_stems", lambda: set(stems))
    # The supersession map defaults to EMPTY, not to the real catalog. Every pre-existing test in
    # this file therefore keeps asserting against "nothing is superseded", which is what makes their
    # clean/warn expectations still mean what they meant before this namespace existed. Leaving it
    # unpatched would have made those tests consult the sibling — the exact hazard the module
    # docstring warns about.
    monkeypatch.setattr(VC, "_manifest_supersession_map", lambda: dict(superseded or {}))


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


# --------------------------------------------------------------------------------------------------
# PRODUCT_ID_SUPERSEDED (2026-09-17) — resolving is not the same as being current
# --------------------------------------------------------------------------------------------------


def test_superseded_product_id_warns_even_though_it_resolves(tmp_path, monkeypatch):
    """The whole point. The id IS in the manifest set — it resolves, so PRODUCT_ID_UNRESOLVED stays
    silent — and the card still fires. What is wrong is the vintage. This is the real
    `mutation-hotspot-frequency` → `pooled-snv-recurrence-v1` case that survived every gate until a
    human read the card, and had to be fixed by hand in #791."""
    _catalog(
        monkeypatch,
        {"pooled-snv-recurrence-v1", "pooled-snv-recurrence-v2"},
        superseded={"pooled-snv-recurrence-v1": ("pooled-snv-recurrence-v2",)},
    )
    r = _validate(tmp_path, _base_card(required_inputs=[{"product_id": "pooled-snv-recurrence-v1"}]))
    w = _warns(r)
    assert r.ok, _errs(r)  # WARNING, never an error
    assert "PRODUCT_ID_SUPERSEDED" in _codes(r)
    assert "PRODUCT_ID_UNRESOLVED" not in _codes(r), (
        "a superseded id resolves; the unresolved check must stay quiet. Asserted on CODES, not on "
        "the joined text — the supersession message itself names PRODUCT_ID_UNRESOLVED"
    )
    assert "pooled-snv-recurrence-v2" in w, "the message must name the replacement to be actionable"


def test_head_of_family_does_not_warn(tmp_path, monkeypatch):
    """The negative control that stops this degenerating into 'warn on anything with a version'. v2 is
    the head — nothing supersedes it — so it must be clean. Without this, a check that warned on every
    `-v1`-looking id would pass the test above and be useless."""
    _catalog(
        monkeypatch,
        {"pooled-snv-recurrence-v1", "pooled-snv-recurrence-v2"},
        superseded={"pooled-snv-recurrence-v1": ("pooled-snv-recurrence-v2",)},
    )
    r = _validate(tmp_path, _base_card(required_inputs=[{"product_id": "pooled-snv-recurrence-v2"}]))
    assert r.ok, _errs(r)
    assert "PRODUCT_ID_SUPERSEDED" not in _warns(r)


def test_multi_hop_chain_names_the_head_not_the_next_hop(tmp_path, monkeypatch):
    """`depmap-predictability-26q1-v1 → -v2 → -v3` is a real 2-hop chain in the catalog. Naming only
    the immediate successor would hand out advice that is itself superseded — the card would be
    'fixed' to another stale vintage. The head must be named; the intermediate hop is shown so the
    reader can see why."""
    _catalog(
        monkeypatch,
        {"dp-v1", "dp-v2", "dp-v3"},
        superseded={"dp-v1": ("dp-v2",), "dp-v2": ("dp-v3",)},
    )
    r = _validate(tmp_path, _base_card(required_inputs=[{"product_id": "dp-v1"}]))
    w = _warns(r)
    assert "PRODUCT_ID_SUPERSEDED" in w
    assert "'dp-v3'" in w, f"head of the chain not named: {w}"
    assert "dp-v2" in w, "the intermediate hop should be visible"


def test_supersession_cycle_does_not_hang(tmp_path, monkeypatch):
    """A malformed catalog can say `a supersedes b` AND `b supersedes a`. Without the cycle guard this
    walk spins forever, turning a data typo in another repo into a hung validator — a far worse
    failure than the warning it was trying to emit. Must terminate and still warn."""
    _catalog(monkeypatch, {"a-v1", "b-v1"}, superseded={"a-v1": ("b-v1",), "b-v1": ("a-v1",)})
    r = _validate(tmp_path, _base_card(required_inputs=[{"product_id": "a-v1"}]))
    assert "PRODUCT_ID_SUPERSEDED" in _warns(r)


def test_superseded_and_unresolvable_yields_one_warning_naming_the_head(tmp_path, monkeypatch):
    """If the superseded manifest was also DELETED, the id both fails to resolve and is superseded.
    Emitting both warnings for one entry is noise; the supersession message is strictly more useful
    because it names where to point instead. Exactly one warning, and it is that one."""
    _catalog(monkeypatch, {"only-v2"}, superseded={"gone-v1": ("only-v2",)})
    r = _validate(tmp_path, _base_card(required_inputs=[{"product_id": "gone-v1"}]))
    w = _warns(r)
    assert _codes(r) & {"PRODUCT_ID_SUPERSEDED", "PRODUCT_ID_UNRESOLVED"} == {"PRODUCT_ID_SUPERSEDED"}, (
        f"expected exactly the supersession warning, got codes {_codes(r)}"
    )
    assert "only-v2" in w


def test_supersession_warning_indexes_the_right_entry(tmp_path, monkeypatch):
    """The `[required_inputs[i]]` index is how a reader finds the line in a card with several inputs.
    An off-by-one here sends them to the wrong product — and both real cards that this check fires on
    today carry the offending id at index 1 and 2, never 0."""
    _catalog(monkeypatch, {"fine-v1", "old-v1", "new-v2"}, superseded={"old-v1": ("new-v2",)})
    r = _validate(
        tmp_path,
        _base_card(required_inputs=[{"product_id": "fine-v1"}, {"product_id": "old-v1"}]),
    )
    assert "PRODUCT_ID_SUPERSEDED [required_inputs[1]]" in _warns(r)


def test_templated_product_id_is_not_checked_for_supersession(tmp_path, monkeypatch):
    """A `{…}` placeholder is resolved at compose time; treating it as an id would warn on a string
    that is not one."""
    _catalog(monkeypatch, {"real-v1"}, superseded={"{release_pin}-somatic": ("new-v2",)})
    r = _validate(tmp_path, _base_card(required_inputs=[{"product_id": "{release_pin}-somatic"}]))
    assert r.ok, _errs(r)
    assert "PRODUCT_ID_SUPERSEDED" not in _warns(r)


def test_supersession_graceful_skips_when_data_catalog_absent(tmp_path, monkeypatch):
    """Same contract as the five namespaces: with no sibling checkout the check must not fire. Note
    this is a real risk of the new code being reached — the map is consulted INSIDE the check, after
    the `manifest_ids is None` return, so the guard has to be the existing one."""
    monkeypatch.setattr(VC, "_data_catalog_manifest_ids", lambda: None)
    monkeypatch.setattr(VC, "_manifest_supersession_map", lambda: {"anything-v1": ("anything-v2",)})
    r = _validate(tmp_path, _base_card(required_inputs=[{"product_id": "anything-v1"}]))
    assert r.ok, _errs(r)
    assert "PRODUCT_ID_SUPERSEDED" not in _warns(r)


def test_real_supersession_loader_finds_all_three_channels():
    """Liveness against the real catalog, mirroring the other real-loader tests: a glob or prefilter
    regression here silently disables the check, and a disabled warning looks exactly like a clean
    repo. Asserts one id from each of the three channels the loader reads:
      * top-level `supersedes:`      → pooled-snv-recurrence-v1 (the #791 case)
      * `cohort.supersedes`          → sc-pseudobulk-donor-celltype-coadread-v1
      * `parameters.supersedes`      → tphp-tumor-vs-normal-protein-per-cohort-v1
    The third is the one data-catalog's own tooling cannot see; if this assert ever fails because the
    declaration MOVED to top level, that is the upstream fix landing and the assert should move with
    it, not be deleted."""
    if VC._data_catalog_manifest_ids() is None:
        return  # sibling absent
    sup = VC._manifest_supersession_map()
    assert isinstance(sup, dict) and sup, "data-catalog present but no supersessions found"
    assert sup.get("pooled-snv-recurrence-v1") == ("pooled-snv-recurrence-v2",)
    assert "sc-pseudobulk-donor-celltype-coadread-v1" in sup, "cohort.supersedes channel not read"
    assert "tphp-tumor-vs-normal-protein-per-cohort-v1" in sup, "parameters.supersedes channel not read"


def test_real_supersession_loader_does_not_lift_prose_from_block_scalars():
    """`normal-tissue-protein-abundance-per-gene-v1.yaml` contains the SENTENCE '…(supersedes the
    primary NORMAL-tissue PROTEIN baseline…' inside a block scalar. A line-scan implementation lifts
    a bogus id out of prose like that and warns on correct cards — the false-positive mode that made
    12 of this check's first 17 warnings wrong. The parse step is what prevents it, so assert the
    property rather than trusting the implementation: every key in the map must be a plausible
    manifest id (the schema's own pattern), never a fragment of English."""
    if VC._data_catalog_manifest_ids() is None:
        return  # sibling absent
    import re

    pattern = re.compile(r"^[a-z0-9][a-z0-9-]*$")  # schema/manifest.schema.json's own pattern
    for old, news in VC._manifest_supersession_map().items():
        assert pattern.match(old), f"non-id key in supersession map (prose leak?): {old!r}"
        for n in news:
            assert pattern.match(n), f"non-id value in supersession map: {n!r}"


def test_real_catalog_fire_set_over_all_cards_is_small_and_named(card_reports):
    """The blast radius, asserted rather than remembered. Originally measured at 2 of 148 cards, both
    naming `tcga-tumor-tpm-per-sample-v1`. As of 2026-09-18 the fire set is DELIBERATELY narrowed to 1:
    the F4 provenance fix dropped the superseded `tcga-tumor-tpm-per-sample-v1` from
    `tumor-vs-normal-percentile-crossing-by-subtype.card.yaml` (it enumerated the real recount3-long +
    assignment-shard ids in its place), clearing that card's PRODUCT_ID_SUPERSEDED warning.
    `tumor-rna-distribution-by-subtype.card.yaml` still names it and remains the sole firing card.
    The point is NOT the count — a count is a ratchet, and a ratchet is not a baseline. The point is
    the NULL DIFF over the other 146: a check that fired broadly would be unlandable, and one that
    fired nowhere would be vacuous. Named, so that when the set changes this test says WHICH."""
    if VC._data_catalog_manifest_ids() is None:
        return  # sibling absent
    firing = {}
    for card, r in card_reports.items():
        hits = [w for w in r.warnings if "PRODUCT_ID_SUPERSEDED" in w]
        if hits:
            firing[card.name] = hits
    assert set(firing) == {
        "tumor-rna-distribution-by-subtype.card.yaml",
    }, f"supersession fire set changed: {sorted(firing)}"
    for name, hits in firing.items():
        assert len(hits) == 1, f"{name}: expected one superseded input, got {hits}"
        assert "tcga-tumor-tpm-recount3-long-v1" in hits[0], hits[0]
