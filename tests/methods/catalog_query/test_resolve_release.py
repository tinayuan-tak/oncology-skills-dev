"""T4 (2026-08-11 engineering review): catalog_query.resolve_release — data_mode/release_pin
actually select a manifest.

Before this, compose-dashboard's data_mode (latest_approved|pinned|exploratory) + release_pin
flowed only into ID strings — 'pinned' and 'exploratory' resolved the SAME data. resolve_release
turns (family, data_mode, release_pin) into a concrete manifest_id via the existing catalog +
supersedes graph. These tests run against the REAL catalog (families with coexisting siblings).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_METHODS = Path(__file__).resolve().parents[3] / "methods"
sys.path.insert(0, str(_METHODS))

from catalog_query.read import (  # noqa: E402
    ReleaseResolutionError,
    _family_of,
    load_catalog,
    resolve_release,
)

# A family known to carry multiple coexisting siblings in the catalog.
_MULTI_FAMILY = "depmap-consortium"


def _members(family: str) -> list[str]:
    idx = load_catalog()
    return sorted(m for m in idx.manifests if _family_of(m) == family)


@pytest.fixture(scope="module")
def multi_members():
    ms = _members(_MULTI_FAMILY)
    if len(ms) < 2:
        pytest.skip(f"family {_MULTI_FAMILY!r} no longer has >=2 coexisting members ({ms})")
    return ms


def test_family_strip():
    assert _family_of("depmap-predictability-26q1-v2") == "depmap-predictability"
    assert _family_of("prism-oncref-dmc-25q4") == "prism-oncref-dmc"
    assert _family_of("sc-pseudobulk-donor-celltype-coadread-v2") == "sc-pseudobulk-donor-celltype-coadread"


def test_family_strip_dotted_release():
    """A release with a minor component writes the dot as a hyphen. Leaving the trailing `-0`/`-1` in
    the family key meant a card declaring the release-free logical id (the CORRECT shape when the card
    supplies its own release_pin) found no members, and the run published a resolution_error instead
    of a head + staleness verdict."""
    assert _family_of("gdc-pancohort-somatic-dr45-0") == "gdc-pancohort-somatic"
    assert _family_of("tcga-gdc-dr45-0") == "tcga-gdc"
    assert _family_of("genie-public-v19-0") == "genie-public"
    assert _family_of("hpa-v25-1") == "hpa"
    assert _family_of("toxcast-invitrodb-v3-3") == "toxcast-invitrodb"


def test_family_strip_does_not_eat_a_descriptive_tail():
    """Over-stripping is the dangerous direction: it would merge unrelated products into one family
    and silently change which manifest resolves as the head. Only version/release-SHAPED tokens go."""
    for mid in (
        "sc-pseudobulk-donor-celltype-coadread",  # bare logical id — already a family
        "hpa-rna-tissue-consensus",
        "mc3-public",
        "gdc-pancohort-somatic",  # the stem itself must be a fixed point
    ):
        assert _family_of(mid) == mid, f"_family_of stripped a real word from {mid!r}"


def test_dotted_release_family_change_moves_no_head():
    """The 13 ids whose family changed are all SINGLETONS, so no family gained or lost members and no
    head selection moved. Guards the regex against a future widening that silently re-points a
    resolved release — the failure mode would be a verdict change with no code change near it."""
    idx = load_catalog()
    members = [m for m in idx.manifests if _family_of(m) == "gdc-pancohort-somatic"]
    assert members == ["gdc-pancohort-somatic-dr45-0"], members
    # a fully-pinned declaration still resolves, via the `family in idx.manifests` fallback
    assert resolve_release("gdc-pancohort-somatic-dr45-0", "latest_approved") == "gdc-pancohort-somatic-dr45-0"
    assert resolve_release("gdc-pancohort-somatic", "latest_approved") == "gdc-pancohort-somatic-dr45-0"


# ---------------------------------------------------------------------------
# #1768 — mid-string release token (DepMap parquet derived product)
# ---------------------------------------------------------------------------
# `depmap-<release>-parquet-v<N>` puts the quarter token MID-string; before the fix the two releases
# resolved to distinct family keys, were never siblings, and `is_stale` (envelope's `head not in used`)
# could never fire for that family. See _family_of docstring.
_PARQUET_26Q1 = "depmap-26q1-parquet-v1"
_PARQUET_26Q3 = "depmap-26q3-parquet-v1"


def test_family_strip_parquet_mid_string_release():
    """Acceptance: the two parquet releases collapse to ONE family (are siblings)."""
    assert _family_of(_PARQUET_26Q1) == _family_of(_PARQUET_26Q3)
    assert _family_of(_PARQUET_26Q1) == "depmap-parquet"


def test_parquet_family_staleness_fires_when_behind_head():
    """A `-26q1-parquet` id reads as STALE when a newer `-26q3-parquet` sibling exists, and the newer
    id reads as fresh — the detector half of #1768. Mirrors envelope's `is_stale = head not in used`."""
    idx = load_catalog()
    present = {m for m in idx.manifests if m in (_PARQUET_26Q1, _PARQUET_26Q3)}
    if present != {_PARQUET_26Q1, _PARQUET_26Q3}:
        pytest.skip(f"parquet sibling releases not both in catalog: {sorted(present)}")
    fam = _family_of(_PARQUET_26Q1)
    head = resolve_release(fam, "latest_approved")
    assert head == _PARQUET_26Q3, head  # natural-order head is the newest release
    # a run that read only the OLD release is stale; the current head is not
    assert head not in {_PARQUET_26Q1}  # is_stale == True for the 26q1 read
    assert head in {_PARQUET_26Q3}  # is_stale == False for the 26q3 read


def test_mid_release_fix_moves_no_other_family():
    """Blast radius: the fix changes the family key for EXACTLY the two parquet ids and no other
    manifest in the live catalog — so no other family's key or head selection moves (verdict-inert).
    Asserts on the full catalog, not a sampled subset."""
    idx = load_catalog()

    def _trailing_only(mid: str) -> str:
        # the pre-#1768 _family_of: trailing-token strips only (no mid-string quarter rule)
        import re

        mid = re.sub(r"-dr\d+(?:-\d+)?$", "", mid, flags=re.IGNORECASE)
        mid = re.sub(r"-v\d+(?:-\d+)?$", "", mid, flags=re.IGNORECASE)
        mid = re.sub(r"-\d{2}q\d+$", "", mid, flags=re.IGNORECASE)
        return mid

    changed = {m: (_trailing_only(m), _family_of(m)) for m in idx.manifests if _trailing_only(m) != _family_of(m)}
    assert set(changed) == {_PARQUET_26Q1, _PARQUET_26Q3}, changed


def test_source_family_staleness_unregressed():
    """No regression to the source family: `depmap-consortium` still resolves its head via the
    trailing-token path and a behind-head release still reads stale. This is the family that genomic
    DepMap cards actually stamp in provenance.input_manifest_ids (they declare `depmap-consortium-*`,
    not the parquet id), so the source-family head is what gates their staleness."""
    idx = load_catalog()
    members = sorted(m for m in idx.manifests if _family_of(m) == "depmap-consortium")
    if len(members) < 2:
        pytest.skip(f"depmap-consortium has <2 coexisting members: {members}")
    head = resolve_release("depmap-consortium", "latest_approved")
    assert head == members[-1]  # newest release is the head
    behind = members[0]
    assert head != behind  # is_stale == True for a run that read the oldest release


def test_representative_family_keys_unchanged():
    """A representative set of unrelated families keeps its exact key (over-stripping guard)."""
    cases = {
        "depmap-consortium-26q1": "depmap-consortium",
        "depmap-consortium-26q1-paralogs": "depmap-consortium-26q1-paralogs",  # no trailing -vN: untouched
        "depmap-consortium-26q1-crispr-supplementary": "depmap-consortium-26q1-crispr-supplementary",
        "depmap-coessentiality-26q1-v1": "depmap-coessentiality",  # trailing-adjacent quarter: already ok
        "allgene-depmap-rank-26q3-v1": "allgene-depmap-rank",
        "depmap-predictability-26q1-v2": "depmap-predictability",
        "gdc-pancohort-somatic-dr45-0": "gdc-pancohort-somatic",
        "genie-public-v19-0": "genie-public",
        "prism-repurposing-19q3-primary": "prism-repurposing-19q3-primary",  # no trailing -vN: untouched
    }
    for mid, want in cases.items():
        assert _family_of(mid) == want, f"{mid!r} -> {_family_of(mid)!r}, expected {want!r}"


def test_latest_approved_picks_head(multi_members):
    """latest_approved resolves to a real member and is >= every other member by id sort
    (newest release wins when there are no supersedes edges)."""
    resolved = resolve_release(_MULTI_FAMILY, "latest_approved")
    assert resolved in multi_members
    assert resolved == multi_members[-1], f"expected head {multi_members[-1]}, got {resolved}"


def test_pinned_selects_specific_sibling(multi_members):
    """pinned resolves to the sibling matching the pin — including an OLDER one (real selection)."""
    oldest = multi_members[0]
    # derive the pin token from the oldest member id (its release suffix)
    pin = oldest[len(_MULTI_FAMILY) + 1 :]
    assert resolve_release(_MULTI_FAMILY, "pinned", pin) == oldest


def test_pinned_requires_pin():
    with pytest.raises(ReleaseResolutionError):
        resolve_release(_MULTI_FAMILY, "pinned")


def test_pinned_unknown_pin_fails_loud(multi_members):
    with pytest.raises(ReleaseResolutionError):
        resolve_release(_MULTI_FAMILY, "pinned", "99q9-nonexistent")


def test_exploratory_pin_takes_precedence_else_head(multi_members):
    oldest = multi_members[0]
    pin = oldest[len(_MULTI_FAMILY) + 1 :]
    # with a resolvable pin, exploratory honors it
    assert resolve_release(_MULTI_FAMILY, "exploratory", pin) == oldest
    # with no pin, exploratory falls to head (same as latest_approved)
    assert resolve_release(_MULTI_FAMILY, "exploratory") == multi_members[-1]


def test_unknown_family_fails_loud():
    with pytest.raises(ReleaseResolutionError):
        resolve_release("no-such-family-xyz", "latest_approved")


def test_concrete_id_as_family_is_accepted():
    """A single-release product often IS its own family id; passing the concrete id resolves to it."""
    idx = load_catalog()
    # pick any manifest whose id == its own family (no version siblings)
    concrete = next(m for m in idx.manifests if _family_of(m) == m)
    assert resolve_release(concrete, "latest_approved") == concrete


# --- product_id resolution (2026-08-14) --------------------------------------
# A card that reads an indication-dispatched product declares the stable products.yaml product_id,
# not a per-indication manifest id, so provenance stamps the product_id. resolve_release must map a
# product_id (matching no manifest-id family and no concrete id) to the head among the OUTPUT
# manifests whose own `product_id:` field equals it — NOT via idx.consumers, which lists a product's
# INPUT sources (resolving there wrongly returns the upstream raw source, e.g. a TCGA GDC release).
# Drift-guard for the tumor-presence provenance warning:
# input_manifest_ids=['expression-rna-tumor-vs-adjacent'] used to raise ReleaseResolutionError.


def _output_manifests_for(idx, pid: str) -> list[str]:
    """Manifests whose OWN product_id field == pid (the product's output manifests)."""

    def _declares(rec):
        v = rec.raw.get("product_id")
        return v == pid or (isinstance(v, list) and pid in v)

    return sorted(m for m, rec in idx.manifests.items() if _declares(rec))


def _a_product_id_with_output_manifest() -> tuple[str, list[str]]:
    """Return (product_id, [output_manifest_ids...]) for a product with >=1 OUTPUT manifest whose
    product_id is not itself a manifest-id family/concrete id, or skip."""
    idx = load_catalog()
    seen: dict[str, list[str]] = {}
    for mid, rec in idx.manifests.items():
        v = rec.raw.get("product_id")
        for pid in [v] if isinstance(v, str) else (v or []):
            seen.setdefault(pid, []).append(mid)
    for pid in sorted(seen):
        members = [m for m in idx.manifests if _family_of(m) == pid]
        if not members and pid not in idx.manifests:
            return pid, sorted(seen[pid])
    pytest.skip("no product_id (distinct from a manifest-id family) declared by any manifest")


def test_product_id_resolves_to_its_output_manifest():
    """A product_id resolves to a manifest whose OWN product_id field declares it (the output
    artifact), instead of raising ReleaseResolutionError or resolving to an input source."""
    pid, output_manifests = _a_product_id_with_output_manifest()
    resolved = resolve_release(pid, "latest_approved")
    assert resolved in output_manifests, (
        f"product_id {pid!r} resolved to {resolved!r}, not among its OUTPUT manifests {output_manifests}"
    )


def test_expression_rna_tumor_vs_adjacent_resolves_to_dge_output_not_source():
    """The exact tumor-presence provenance-warning case: product_id 'expression-rna-tumor-vs-adjacent'
    must resolve to the DGE OUTPUT manifest (which carries product_id in its own field, e.g.
    coadread-dge-*), NOT to a products.yaml source input (e.g. a tcga-gdc-* raw release). Skips if the
    product declares no output manifest in this catalog checkout."""
    idx = load_catalog()
    pid = "expression-rna-tumor-vs-adjacent"
    outputs = _output_manifests_for(idx, pid)
    if not outputs:
        pytest.skip(f"{pid!r} declared by no manifest in this catalog checkout")
    resolved = resolve_release(pid, "latest_approved")
    assert resolved in outputs, f"expected a DGE output manifest {outputs}, got {resolved!r}"
    assert not resolved.startswith("tcga-gdc-"), (
        f"resolved to an upstream SOURCE {resolved!r}, not the product output — regression of the "
        f"idx.consumers (input-sources) bug."
    )


def test_unknown_string_still_fails_loud():
    """A string that is neither a manifest-id family, a concrete id, nor a product_id still raises —
    the product_id fallback must not swallow genuinely-unresolvable inputs."""
    with pytest.raises(ReleaseResolutionError):
        resolve_release("definitely-not-a-product-or-family-xyz", "latest_approved")
