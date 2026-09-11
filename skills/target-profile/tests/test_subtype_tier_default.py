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


def test_curated_registry_excludes_staging_and_source_duplicated_ids():
    """The reason this defaults to the CONTRACTS crosswalk and not the data-catalog subgroup
    catalog: the catalog's raw COADREAD list carries `stage_I`/`stage_II`/`stage_resectable`
    (staging, not molecular biology) and `CMS1_depmap`..`CMS4_depmap` alongside `CMS1`..`CMS4`.
    The tier's semantics are molecular, so an auto-resolved scope must not include those."""
    strata = set(default_subtypes("COADREAD")[0])
    assert not {s for s in strata if s.startswith("stage_")}
    assert not {s for s in strata if s.endswith("_depmap")}


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
