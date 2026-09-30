"""sweep2 Fix 6: catalog_query head resolution must be VERSION-aware, not lexical.

`resolve_release(..., 'latest_approved'|'exploratory')` picks the family head via
`sorted(members)[-1]`. A lexical sort mis-orders exactly the tokens that distinguish sibling
releases — `-v10` sorts before `-v9`, `26q10` before `26q2` — so it can return an OLDER manifest
as the "latest" head. These tests lock the natural-order key (`_version_key`) + the family-strip
generalization that lets multi-digit release tokens share a family.
"""

from __future__ import annotations

from onc_methods.catalog_query.read import _family_of, _version_key


def test_v_suffix_double_digit_beats_single_digit():
    ids = ["foo-v1", "foo-v2", "foo-v9", "foo-v10", "foo-v11"]
    assert sorted(ids, key=_version_key)[-1] == "foo-v11"
    # the specific lexical trap: v10/v11 must beat v9
    assert _version_key("foo-v10") > _version_key("foo-v9")
    assert _version_key("foo-v11") > _version_key("foo-v10")


def test_release_token_double_digit_beats_single_digit():
    ids = ["bar-26q1", "bar-26q2", "bar-26q9", "bar-26q10"]
    assert sorted(ids, key=_version_key)[-1] == "bar-26q10"
    assert _version_key("bar-26q10") > _version_key("bar-26q2")


def test_release_and_version_compose():
    ids = [
        "baz-26q1-v1",
        "baz-26q2-v1",
        "baz-26q2-v2",
        "baz-26q10-v1",
        "baz-26q10-v2",
    ]
    assert sorted(ids, key=_version_key)[-1] == "baz-26q10-v2"


def test_lexical_would_have_been_wrong():
    """Sanity: the plain lexical sort DOES pick the wrong head here — proving the key matters."""
    ids = ["foo-v9", "foo-v10"]
    assert sorted(ids)[-1] == "foo-v9"  # lexical: '9' > '1' → wrong
    assert sorted(ids, key=_version_key)[-1] == "foo-v10"  # version-aware: correct


def test_family_strip_handles_multi_digit_release_token():
    """`_family_of` must strip -26q10 (two-digit quarter suffix) so `foo-26q2` and `foo-26q10`
    resolve to the SAME family — otherwise the head comparison never sees them as siblings."""
    assert _family_of("foo-26q10") == "foo"
    assert _family_of("foo-26q2") == "foo"
    assert _family_of("foo-26q10") == _family_of("foo-26q2")
