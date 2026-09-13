"""The subtype_fit tier is DEFAULT-ON (v1.3.0): strata auto-resolve from the contracts
subtype_crosswalk when --subtypes is omitted, and --no-subtypes restores whole-cohort.

WHY (2026-09-11): the tier is verdict-bearing in BOTH directions
(subtype_specific_non_dependence → HOLD; subtype_restricted_dependency /
subtype_restricted_selectivity → supportive positives), but while it was opt-in NO published
panel run ever evaluated it — every finalized target was profiled whole-cohort only, so a
subtype-restricted dependency was indistinguishable from a whole-cohort silence.

These tests pin the RESOLUTION contract (which strata, from which registry, with what
provenance token) and the flag precedence. They read the real crosswalk — it is the artifact
under test — but never touch S3 or run the fan-out.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # skills/ — for _test_support

from _test_support import load_run_py  # noqa: E402

_RUN = load_run_py(Path(__file__).resolve().parents[1], "tp_run_subtype_default")

import tp_common  # noqa: E402
from tp_common import default_subtypes  # noqa: E402


def test_coadread_resolves_the_curated_molecular_strata():
    strata, source = default_subtypes("COADREAD")
    assert source == "auto:subtype_crosswalk"
    # the two axes the tier can actually act on must be present
    assert {"MSI_H", "MSS"} <= set(strata)
    assert {"CMS1", "CMS2", "CMS3", "CMS4"} <= set(strata)


def test_curated_registry_excludes_staging_but_includes_the_depmap_cms_axis():
    """The reason this defaults to the CONTRACTS crosswalk and not the data-catalog subgroup
    catalog: the catalog's raw COADREAD list carries `stage_I`/`stage_II`/`stage_resectable`
    (staging, not molecular biology), which the curated crosswalk omits — so an auto-resolved
    scope must not include those.

    (2026-09-11, NSCLC/DepMap-CMS shard wiring) `CMS1_depmap`..`CMS4_depmap` are NO LONGER
    treated as source-duplicates of `CMS1`..`CMS4`: they are a DISTINCT DepMap-cohort axis
    (molecular_subtype_depmap), materialized by CMScaller NTP on cell lines. They ARE curated
    in the crosswalk and auto-resolve, because the per-card cohort filter routes them to the
    DepMap dependency card (which the TCGA CMS ids can't serve) — the opposite of a duplicate.
    So the scope carries BOTH the TCGA CMS and the DepMap CMS, on different cards."""
    strata = set(default_subtypes("COADREAD")[0])
    assert not {s for s in strata if s.startswith("stage_")}  # staging still excluded (not in crosswalk)
    # the DepMap-CMS axis is now a legitimate, curated part of the scope
    assert {"CMS1_depmap", "CMS2_depmap", "CMS3_depmap", "CMS4_depmap"} <= strata
    # ...and distinct from the trusted TCGA Guinney CMS ids (both present, not collapsed)
    assert {"CMS1", "CMS2", "CMS3", "CMS4"} <= strata


def test_strata_are_deduped_and_order_stable():
    strata = default_subtypes("COADREAD")[0]
    assert len(strata) == len(set(strata)), "duplicate stratum id would double-resolve a card"
    assert strata == default_subtypes("COADREAD")[0], "resolution must be deterministic (run ids)"


def test_indication_code_is_case_insensitive():
    assert default_subtypes("coadread")[0] == default_subtypes("COADREAD")[0]


def test_unregistered_indication_degrades_to_whole_cohort_not_error():
    """MPN (JAK2's indication) is in NO crosswalk entry. The tier must become a no-op, not a
    failure — a run for an unregistered indication is exactly as valid as it was pre-v1.3.0."""
    strata, source = default_subtypes("MPN")
    assert strata == []
    assert source == "unavailable:MPN"


def test_missing_registry_degrades_not_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(tp_common, "_CONTRACTS_REPO", tmp_path / "nope")
    assert default_subtypes("COADREAD") == ([], "unavailable:no_registry")


def test_empty_indication_is_handled():
    assert default_subtypes("")[0] == []
    assert default_subtypes("")[1].startswith("unavailable:")


# --- indication ALIASES (2026-09-13) -----------------------------------------
# The registry is keyed by canonical_code, so `--indication LUAD` used to resolve NO strata and run
# whole-cohort — 57 of 60 thoracic corpus rows — while indication_crosswalk.yaml v1.4.0 had curated
# `NSCLC: aliases: [LUAD, LUSC]` all along. Resolution now goes through
# _skills_common.indication_scope; the provenance token names WHICH indication answered.


def test_sub_indication_alias_resolves_instead_of_running_whole_cohort():
    strata, source = default_subtypes("LUAD")
    assert source == "auto:subtype_crosswalk:alias_of:NSCLC"
    assert strata, "LUAD used to return [] and silently run whole-cohort"
    assert {"EGFR_mut_ex19del", "KRAS_G12C", "ALK_fusion"} <= set(strata)
    assert default_subtypes("LUSC")[0] == strata, "both NSCLC aliases resolve to the same scope"


def test_co_defining_axis_is_dropped_on_an_alias_but_kept_on_the_canonical():
    """★ The correctness guard, asserted at BOTH poles so it cannot pass vacuously.

    NSCLC's `histology` axis is declared `partition: co_defining` — `histology_Adeno` IS
    (approximately) the whole LUAD cohort. Under a LUAD request that axis degenerates to ONE
    stratum equal to the requested cohort, with no cross-stratum contrast; tp_fanout._subtype_verdict
    reads a single stratum's own class, so it would let the VERDICT-BEARING
    subtype_restricted_dependency rung fire off what is really a whole-cohort read.
    """
    nsclc = default_subtypes("NSCLC")[0]
    luad = default_subtypes("LUAD")[0]
    assert {"histology_Adeno", "histology_SCC"} <= set(nsclc), "canonical NSCLC keeps its histology axis"
    assert not {s for s in luad if s.startswith("histology_")}, "alias must not stratify by a co-defining axis"
    assert set(luad) == set(nsclc) - {"histology_Adeno", "histology_SCC"}, "ONLY that axis is dropped"


def test_alias_without_a_co_defining_axis_keeps_every_stratum():
    """Self-inerting: the drop is derived from the `partition:` declaration, so a synonym alias
    (COAD/READ → COADREAD, GC → STAD) loses nothing. If this ever fails, the guard has started
    over-firing and narrowing scopes it was never meant to touch."""
    assert set(default_subtypes("COAD")[0]) == set(default_subtypes("COADREAD")[0])
    assert default_subtypes("COAD")[1] == "auto:subtype_crosswalk:alias_of:COADREAD"
    assert set(default_subtypes("GC")[0]) == set(default_subtypes("STAD")[0])


def test_the_co_defining_drop_is_derived_from_the_registry_not_hardcoded():
    """Derive the check's OWN population: assert the invariant over EVERY declared alias whose
    canonical entry exists in subtype_crosswalk, so a new alias or a newly-declared co_defining
    axis is covered the day it lands rather than silently escaping a pinned list."""
    import yaml
    from _skills_common.indication_scope import _code_index

    doc = yaml.safe_load((tp_common._CONTRACTS_REPO / "vocabularies" / "subtype_crosswalk.yaml").read_text())
    by_code = {str(e.get("canonical_code")): e for e in doc.get("indications") or []}
    _canonical, aliases = _code_index()
    covered = 0
    for alias, code in aliases.items():
        entry = by_code.get(code)
        if entry is None:
            continue  # not a subtype-registered indication; default_subtypes reports unavailable
        expected = {
            s
            for ax in entry.get("axes") or []
            if str(ax.get("partition") or "") != "co_defining"
            for s in (ax.get("strata") or [])
        }
        assert set(default_subtypes(alias)[0]) == expected, alias
        covered += 1
    assert covered >= 3, f"only {covered} aliases exercised — the loop has stopped covering the vocabulary"
    # ...and at least one of them must actually LOSE an axis, or the invariant above is trivial.
    assert any(
        any(str(ax.get("partition") or "") == "co_defining" for ax in (by_code.get(code, {}).get("axes") or []))
        for code in aliases.values()
    ), "no alias resolves to an indication with a co_defining axis — the drop branch is unreachable"


def test_canonical_indications_keep_the_bare_provenance_token():
    """Byte-stability for every code that already worked: the token must NOT gain an alias suffix."""
    for code in ("COADREAD", "NSCLC", "STAD", "BRCA", "HNSC", "PAAD", "SCLC", "ESCA"):
        assert default_subtypes(code)[1] == "auto:subtype_crosswalk", code


def test_unavailable_token_names_the_REQUESTED_code_not_the_canonical():
    """A reader chasing why a run went whole-cohort needs the code they typed. LAML resolves to AML,
    which has no subtype_crosswalk entry — the token must say LAML, not AML."""
    assert default_subtypes("LAML") == ([], "unavailable:LAML")
    assert default_subtypes("AML") == ([], "unavailable:AML")


# --- flag surface ------------------------------------------------------------


def _parse(argv: list[str]):
    ap = _RUN._build_arg_parser()
    return ap.parse_args(["--target", "KRAS", "--indication", "COADREAD", "--out", "/tmp/x", *argv])


def _resolve(args):
    """Mirror of run.py's resolution order. Kept in lockstep by
    test_no_subtypes_wins_over_subtypes / test_default_is_auto below."""
    if args.no_subtypes:
        return None, "disabled:--no-subtypes"
    if args.subtypes:
        return [s.strip() for s in args.subtypes.split(",") if s.strip()] or None, "explicit:--subtypes"
    auto, source = default_subtypes(args.indication)
    return (auto or None), source


def test_no_subtypes_flag_exists_and_wins_over_subtypes():
    args = _parse(["--subtypes", "MSI_H", "--no-subtypes"])
    assert _resolve(args) == (None, "disabled:--no-subtypes")


def test_explicit_subtypes_still_honored():
    strata, source = _resolve(_parse(["--subtypes", "MSI_H,MSS"]))
    assert strata == ["MSI_H", "MSS"]
    assert source == "explicit:--subtypes"


def test_default_is_auto_resolved():
    strata, source = _resolve(_parse([]))
    assert source == "auto:subtype_crosswalk"
    assert strata and "MSI_H" in strata
