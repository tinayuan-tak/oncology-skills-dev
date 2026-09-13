"""indication_scope: curated ALIAS → canonical-code resolution for the subtype-scope path.

The defect these pin: every subtype-scope entry point EXACT-MATCHED the indication code, so a
`--indication LUAD` run resolved no strata and matched no subgroup-assignments shard — even though
`indication_crosswalk.yaml` v1.4.0 has curated `NSCLC: aliases: [LUAD, LUSC]` all along, and the
`depmap-subgroup-assignments-nsclc-v1` / `tcga-subgroup-assignments-nsclc-*` shards are built.

These read the REAL crosswalk (it is the artifact under test) and never touch S3.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # skills/

from _skills_common import indication_scope  # noqa: E402
from _skills_common.indication_scope import canonical_subtype_code, registry_get  # noqa: E402

# --- resolution contract -----------------------------------------------------


def test_canonical_code_resolves_to_itself_as_exact():
    assert canonical_subtype_code("NSCLC") == ("NSCLC", "exact")
    assert canonical_subtype_code("COADREAD") == ("COADREAD", "exact")


def test_curated_alias_resolves_to_its_canonical():
    assert canonical_subtype_code("LUAD") == ("NSCLC", "alias")
    assert canonical_subtype_code("LUSC") == ("NSCLC", "alias")
    assert canonical_subtype_code("COAD") == ("COADREAD", "alias")
    assert canonical_subtype_code("READ") == ("COADREAD", "alias")


def test_oncotree_synonym_spelling_resolves():
    """`DLBCL`/`UM` are the crosswalk's own `oncotree_code` for DLBC/UVM — a different spelling of
    the SAME cohort, so they belong in the alias lane, not the unknown lane."""
    assert canonical_subtype_code("DLBCL") == ("DLBC", "alias")
    assert canonical_subtype_code("UM") == ("UVM", "alias")


def test_case_and_whitespace_insensitive_but_returns_the_declared_spelling():
    assert canonical_subtype_code(" luad ") == ("NSCLC", "alias")
    assert canonical_subtype_code("nsclc") == ("NSCLC", "exact")


def test_unregistered_code_returns_none_never_a_guess():
    """The resolver only ever returns a code the crosswalk declares. MPN is in no entry; a
    spelling-based guess (e.g. stripping a suffix) would be exactly the wrong failure mode."""
    assert canonical_subtype_code("MPN") == (None, "unknown")
    assert canonical_subtype_code("") == (None, "unknown")
    assert canonical_subtype_code(None) == (None, "unknown")


def test_missing_crosswalk_degrades_to_unknown_not_raises(tmp_path):
    """Fail-soft: every caller keeps its pre-alias whole-cohort behaviour when the vocab is gone."""
    assert canonical_subtype_code("LUAD", str(tmp_path / "nope")) == (None, "unknown")


def test_alias_never_shadows_a_canonical_code():
    """Two-pass indexing: if some entry ever listed a live canonical code as its own alias, the
    canonical meaning must still win. Asserted over the WHOLE live vocabulary, not one example."""
    canonical, aliases = indication_scope._code_index()
    assert canonical, "crosswalk read must not be empty — the rest of this file would be vacuous"
    assert not (set(canonical) & set(aliases)), "an alias key collides with a canonical code"
    for key in canonical:
        assert canonical_subtype_code(key)[1] == "exact"


def test_every_declared_alias_resolves():
    """Coverage, derived from the vocabulary rather than a hardcoded list (a pinned list decays
    silently when the crosswalk grows a new alias)."""
    canonical, aliases = indication_scope._code_index()
    assert len(aliases) >= 8, f"expected the curated alias lane to be populated, saw {len(aliases)}"
    for alias, code in aliases.items():
        assert canonical_subtype_code(alias) == (code, "alias")


# --- registry lookup ---------------------------------------------------------


def test_registry_get_prefers_an_explicit_raw_key_over_the_crosswalk():
    """Several live registries carry BOTH `COADREAD` and its `COAD`/`READ` aliases with distinct
    values. An explicit entry must never be overridden by crosswalk redirection."""
    mapping = {"COADREAD": "canonical-shard", "COAD": "explicit-coad-shard"}
    assert registry_get(mapping, "COAD") == ("explicit-coad-shard", "COAD", "exact")
    assert registry_get(mapping, "READ") == ("canonical-shard", "COADREAD", "alias")


def test_registry_get_reports_the_key_that_actually_answered():
    mapping = {"NSCLC": "nsclc-shard"}
    assert registry_get(mapping, "LUAD") == ("nsclc-shard", "NSCLC", "alias")
    assert registry_get(mapping, "NSCLC") == ("nsclc-shard", "NSCLC", "exact")


def test_registry_get_miss_is_a_miss_even_for_a_registered_code():
    """AML IS a registered indication but has no assignments shard — the lookup must miss, not
    fabricate one. (This is why AML is out of scope for the wiring fix: its catalog strata exist
    but no `*-subgroup-assignments-aml-*` manifest does.)"""
    assert registry_get({"NSCLC": "x"}, "AML") == (None, None, "unknown")
    assert registry_get({}, "LUAD") == (None, None, "unknown")
    assert registry_get({"NSCLC": "x"}, None) == (None, None, "unknown")


# --- the shards the fix actually unlocks -------------------------------------


def test_luad_now_reaches_the_nsclc_assignments_shards():
    """The measured symptom: a LUAD run got `no subgroup-assignments shard for
    indication='LUAD'` while these shards sat there built. Both poles asserted, so the test
    cannot pass by the registries being empty."""
    from _skills_common import _live_readers as lr

    dep, cohort = lr._shard_for_indication(lr._DEPENDENCY_ASSIGNMENTS_SHARDS, "LUAD")
    assert cohort == "NSCLC"
    assert dep and any("nsclc" in manifest for manifest, _strata in dep)

    mol, cohort = lr._shard_for_indication(lr._MUTATION_MOLECULAR_ASSIGNMENTS_SHARDS, "LUSC")
    assert cohort == "NSCLC"
    assert mol and any("nsclc" in manifest for manifest, _strata in mol)

    lot, cohort = lr._shard_for_indication(lr._MUTATION_LOT_ASSIGNMENTS_MANIFEST, "LUAD")
    assert (lot, cohort) == ("genie-bpc-subgroup-assignments-nsclc-v1", "NSCLC")


def test_canonical_indication_routing_is_unchanged():
    """Byte-stability for the codes that already worked: an exact hit reports the requested code
    as the cohort, so no `_indication_scope` note is attached and the panorama label is untouched."""
    from _skills_common import _live_readers as lr

    for registry, code in (
        (lr._DEPENDENCY_ASSIGNMENTS_SHARDS, "NSCLC"),
        (lr._DEPENDENCY_ASSIGNMENTS_SHARDS, "COADREAD"),
        (lr._MUTATION_ASSIGNMENTS_MANIFEST, "COADREAD"),
        (lr._MUTATION_LOT_ASSIGNMENTS_MANIFEST, "NSCLC"),
    ):
        entry, cohort = lr._shard_for_indication(registry, code)
        assert entry is not None and cohort == code


def test_unregistered_indication_still_gets_no_shard():
    """The fix must not turn a miss into a hit for an indication with no shard — the honest
    data-note path stays reachable (it is the only thing standing between a JAK2/MPN run and a
    fabricated cohort)."""
    from _skills_common import _live_readers as lr

    assert lr._shard_for_indication(lr._DEPENDENCY_ASSIGNMENTS_SHARDS, "MPN") == (None, None)
