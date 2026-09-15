"""No float('nan') may escape the structure-features parquet boundary, and the absence guard must fire.

Measured over the 504-package archetype corpus before this fix: **78 packages / 48 targets** emitted a
non-finite structural feature — `alphafold_plddt_min_domain` 57, `pdb_best_resolution_angstrom` 29, and
`alphafold_plddt_mean` / `_min` / `disordered_fraction` 10 each. All five are float64 columns.

⚠️⚠️ **That figure is a PER-INTERPRETER measurement, not a property of the code**, and this file learned it
the hard way: an earlier draft asserted the dtype difference as an invariant and was **refuted by CI**.
Measured directly at the boundary:

    pandas 2.3.3 / numpy 1.26   missing str cell -> None   bool(pd.isna(empty ndarray)) -> False + DeprecationWarning
    pandas 3.0.3 / numpy 2.5.1  missing str cell -> nan    bool(pd.isna(empty ndarray)) -> ValueError

Under pandas >= 3 the default string dtype is `str`, whose missing-value sentinel is **NaN**, so the leak is
**wider** there — every string column with a null cell leaks, not only the float64 ones. `pixi.toml` pins
`pandas = "*"`, so which regime runs is decided by the lockfile and changes without announcement.

★★ And the widening is not cosmetic: it turns a NON-finding recorded lower in this file into a real defect
worth **50 product rows**. `_classify_pdb_coverage` tests `if row.get("alphafold_prediction_id")` by
TRUTHINESS, and `nan` is truthy — 94 of 20,329 product rows carry a null prediction id and **50 of those
have zero PDB IDs**, so on pandas 3 the pre-fix reader answers `af_only`, asserting an AlphaFold model that
does not exist, where on pandas 2 it correctly answers `none`. Pinned version-free in
`test_a_nan_sentinel_fabricates_af_only_which_is_why_string_columns_need_covering`.

`_none_for_missing` is correct under both regimes **by construction**: it branches on the runtime type of
the value (`isinstance(v, (str, bytes)) or hasattr(v, "__len__")`), never on the column's dtype, so a NaN in
a string column is just a `float` with no `__len__` and reaches the `pd.isna` arm. The code survived a major
pandas bump that its own prose did not — so the assertions below pin version-free invariants wherever the
spelling of a gap is what varies.

★★ The behavioural half is worse than the JSON half. `_classify_alphafold_confidence` opens with
`if mean is None: return "unavailable"`, and NaN walks straight through it — `nan is None` is False,
`float(nan)` does not raise, and every `>=` against NaN is False — so control reached the terminal
`return "low"`. That branch was not merely weak, it was **unreachable**: `alphafold_confidence_class` was
`"unavailable"` in **0 of 20,329 product rows and 0 of 504 corpus packages**. The 4 corpus packages that do
emit `"unavailable"` get there through `_empty_result` instead, carrying
`_data_note="target_not_in_structure_features"` — an absent ROW, not a null CELL. So the card published a
MEASURED structural negative for a value it never measured, on **10 packages / 3 targets (APC, KMT2A, MGA)**,
all of them >2,800 aa (AlphaFold DB length coverage, so the mislabelling is biased toward the largest
proteins). `intracellular-intrinsic.rules.yaml` then keys `alphafold_confidence_class == "low"` to
`small_molecule: opposing` with the rationale *"A MEASURED structural negative for the SM modality, not an
absence"* — asserting exactly the premise the input violates.

★ THE CONSTRUCTION PATH IS THE TEST. A frame built from a Python dict preserves `None` as `None`, so it does
NOT reproduce this bug and a test written that way passes against the broken code. Every frame here is
therefore written to parquet and read back through `pd.read_parquet`, the production path, and
`test_the_fixture_reproduces_the_leak_through_a_real_parquet_round_trip` pins the raw pre-fix behaviour so
the fixture cannot silently stop being a reproduction.

⚠️ The list column is a length-dependent trap, and the safe length is **exactly one**. `pd.isna(ndarray)`
returns an ARRAY, and `bool()` of an array is well-defined only at len 1: len > 1 raises in every version,
len 0 raises under numpy >= 2. So a naive scalar-only conversion breaks on the well-studied targets AND on
the empty ones, and passes only in the middle — **6,954 of 20,329 product rows (34.2%) carry >=2 IDs, max
1,376**.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.structure_features_static import read as R  # noqa: E402

# ARM1 is the well-studied shape (3 PDB IDs — the >=2 case that makes a scalar-only conversion crash).
# GAPX is the defect: pLDDT / resolution / disorder all missing, no AlphaFold model. LOWP is the negative
# control that decides whether the fix over-reaches — a GENUINELY low pLDDT must stay "low".
HOTSPOT_ROWS = [
    {
        "uniprot_ac": "P00001",
        "gene_symbol": "ARM1",
        "hotspot_pocket_adjacency_call": "adjacent",
        "mutation_hotspot_in_druggable_pocket": True,
        "pdb_ids_available": ["1ABC", "2DEF", "3GHI"],
        "pdb_best_resolution_angstrom": 1.8,
        "pdb_best_method": "X-RAY DIFFRACTION",
        "alphafold_plddt_mean": 95.2,
        "alphafold_plddt_min": 71.0,
        "alphafold_plddt_min_domain": 68.4,
        "n_domains_low_plddt": 0,
        "disordered_fraction": 0.04,
        "alphafold_prediction_id": "AF-P00001-F1",
    },
    {
        "uniprot_ac": "P00002",
        "gene_symbol": "GAPX",
        "hotspot_pocket_adjacency_call": None,
        "mutation_hotspot_in_druggable_pocket": None,
        "pdb_ids_available": [],
        "pdb_best_resolution_angstrom": None,
        "pdb_best_method": None,
        "alphafold_plddt_mean": None,
        "alphafold_plddt_min": None,
        "alphafold_plddt_min_domain": None,
        "n_domains_low_plddt": None,
        "disordered_fraction": None,
        "alphafold_prediction_id": None,
    },
    {
        "uniprot_ac": "P00003",
        "gene_symbol": "LOWP",
        "hotspot_pocket_adjacency_call": "no_hotspots_annotated",
        "mutation_hotspot_in_druggable_pocket": False,
        "pdb_ids_available": ["4JKL"],
        "pdb_best_resolution_angstrom": 3.4,
        "pdb_best_method": "ELECTRON MICROSCOPY",
        "alphafold_plddt_mean": 40.0,
        "alphafold_plddt_min": 22.5,
        "alphafold_plddt_min_domain": 21.0,
        "n_domains_low_plddt": 3,
        "disordered_fraction": 0.71,
        "alphafold_prediction_id": "AF-P00003-F1",
    },
]


def _write_hotspot_parquet(tmp_path: Path) -> Path:
    """Write the fixture through parquet — the production serialisation, not a dict."""
    path = tmp_path / "structure_features.parquet"
    pd.DataFrame(HOTSPOT_ROWS).to_parquet(path, index=False)
    return path


@pytest.fixture
def hotspot_product(tmp_path, monkeypatch):
    """Point the reader at the synthetic hotspot parquet; isolate the ligandability leg."""
    monkeypatch.setattr(R, "CACHE_PARQUET", _write_hotspot_parquet(tmp_path))
    monkeypatch.setattr(R, "_DERIVED_STATUS", True)
    monkeypatch.setattr(R, "_LIGAND_STATUS", False)
    monkeypatch.setattr(R, "CACHE_LIGAND_PARQUET", tmp_path / "no_ligandability.parquet")
    R._load_structure_indexed.cache_clear()
    R._load_ligandability_indexed.cache_clear()
    yield
    R._load_structure_indexed.cache_clear()
    R._load_ligandability_indexed.cache_clear()


def _raw_records(tmp_path) -> dict:
    """The frame as the reader sees it BEFORE _none_for_missing — the pre-fix state."""
    df = pd.read_parquet(_write_hotspot_parquet(tmp_path))
    return {row["gene_symbol"]: row.to_dict() for _, row in df.iterrows()}


def test_the_fixture_reproduces_the_leak_through_a_real_parquet_round_trip(tmp_path):
    """Pin the pre-state. If this stops failing, every assertion below is vacuous."""
    raw = _raw_records(tmp_path)["GAPX"]

    # 1. The dtype dependence itself — the fact that makes this fixture a valid reproduction.
    assert isinstance(raw["alphafold_plddt_mean"], float) and math.isnan(raw["alphafold_plddt_mean"]), (
        "a missing float64 cell no longer round-trips as float('nan'); this fixture has stopped "
        f"reproducing the bug (got {raw['alphafold_plddt_mean']!r})"
    )
    # A missing STRING cell is spelled `None` by pandas 2 and `nan` by pandas 3 (module docstring), so
    # assert the version-free part: whichever sentinel is used, it is never usable string data. Asserting
    # `is None` here is what CI refuted — the spelling is the dependency's choice, not this code's.
    method = raw["pdb_best_method"]
    assert not isinstance(method, str), (
        f"a missing string cell arrived as an actual str ({method!r}) — the fixture has stopped reproducing "
        "the gap it exists to reproduce"
    )
    assert pd.isna(method), f"a missing string cell must read as missing, got {method!r}"

    # 2. The behavioural consequence: NaN defeats an `is None` guard, silently.
    mean = raw["alphafold_plddt_mean"]
    assert mean is not None, "the guard's own predicate does not see it"
    assert float(mean) != float(mean), "float() does not raise, so the except branch is unreachable too"
    assert not (float(mean) >= 70), "every >= against NaN is False, so control reaches `return 'low'`"

    # 3. The structural consequence, at the grain Stage 2's writer will enforce.
    with pytest.raises(ValueError, match="Out of range float"):
        json.dumps(raw, indent=2, allow_nan=False, default=str)


def test_missing_numeric_cells_become_none(hotspot_product):
    s = R.read_target_summary("GAPX")
    for field in (
        "alphafold_plddt_mean",
        "alphafold_plddt_min",
        "alphafold_plddt_min_domain",
        "disordered_fraction",
        "pdb_best_resolution_angstrom",
    ):
        assert s[field] is None, f"{field} should abstain with None, got {s[field]!r}"
    # ...and a populated row is untouched, including the value that decides the class.
    armed = R.read_target_summary("ARM1")
    assert armed["alphafold_plddt_mean"] == 95.2
    assert armed["pdb_best_resolution_angstrom"] == 1.8


def test_none_activates_the_unavailable_branch_and_a_measured_low_still_reads_low(hotspot_product):
    """★ The behavioural claim AND the control that decides whether the fix over-reaches.

    10 corpus packages / 3 targets move `low` -> `unavailable`. That is only correct if a genuinely
    low pLDDT keeps reading `low` — otherwise the fix would delete a real structural negative, which is
    the failure mode the plan flagged for the selectivity card.
    """
    assert R.read_target_summary("GAPX")["alphafold_confidence_class"] == "unavailable"
    assert R.read_target_summary("LOWP")["alphafold_confidence_class"] == "low", (
        "a MEASURED pLDDT of 40.0 is a real structural negative and must survive the fix"
    )
    assert R.read_target_summary("ARM1")["alphafold_confidence_class"] == "high"


def test_the_absent_row_and_null_cell_absence_routes_now_agree(hotspot_product):
    """Two routes reach absence; before this fix only one of them worked.

    `_empty_result` (target has no row at all) hardcodes "unavailable" and was the ONLY source of that
    value in the whole corpus. The null-cell route fell through to "low". They must now agree on the
    class while staying distinguishable by their notes, because they are different facts.
    """
    absent_row = R.read_target_summary("NOTATARGET")
    null_cell = R.read_target_summary("GAPX")
    assert absent_row["alphafold_confidence_class"] == "unavailable"
    assert null_cell["alphafold_confidence_class"] == "unavailable"
    assert absent_row["_data_note"] == "target_not_in_structure_features"
    assert "_data_note" not in null_cell, "a row that IS present must not claim the target is missing"
    assert null_cell["_data_source"] == R.DERIVED_MANIFEST_ID


def test_a_multi_element_list_column_does_not_crash_and_a_scalar_only_conversion_would(tmp_path):
    """⚠️ The failure mode is LENGTH-DEPENDENT and only len 1 is safe, so a 1-element fixture misses it.

    `pd.isna(ndarray)` returns an ARRAY, and `bool()` of an array is well-defined only at len 1 — len > 1
    raises in every version, len 0 raises under numpy >= 2. This asserts both directions: the shipped
    conversion survives all three lengths, and the naive spelling breaks on the outer two while passing in
    the middle.

    ⚠️ The len-0 SYMPTOM is version-dependent — numpy 1.26 returned False with a DeprecationWarning, which
    happens to give the right pass-through, while numpy >= 2 raises. So what is asserted here is its
    version-free CAUSE (`pd.isna` hands back an empty array, not a bool) rather than the reaction numpy
    currently chooses. Asserting the reaction is exactly the mistake this file already made once.
    """

    def naive_scalar_only(rec: dict) -> dict:
        return {k: (None if pd.isna(v) else v) for k, v in rec.items()}

    raw = _raw_records(tmp_path)

    # The shipped conversion handles all three lengths.
    for sym in ("ARM1", "GAPX", "LOWP"):
        converted = R._none_for_missing(raw[sym])
        assert list(R._coerce_id_list(converted["pdb_ids_available"])) == list(
            R._coerce_id_list(raw[sym]["pdb_ids_available"])
        ), "the list column must pass through untouched"

    # len 3 — ambiguous, raises in every version. This is the trap the pass-through exists for.
    with pytest.raises(ValueError, match="truth value of an array with more than one element"):
        naive_scalar_only(raw["ARM1"])

    # len 1 — the ONE well-defined case, so the naive spelling happens to work. That is precisely why a
    # fixture built from a single-PDB target would have shown nothing.
    naive_scalar_only(raw["LOWP"])

    # len 0 — an EMPTY ndarray, not None and not a bool. Assert the cause, not numpy's reaction to it.
    empty_isna = pd.isna(raw["GAPX"]["pdb_ids_available"])
    assert not isinstance(empty_isna, bool) and getattr(empty_isna, "size", None) == 0, (
        f"pd.isna on an empty list cell must return an empty ARRAY, got {empty_isna!r} — if this became a "
        "plain bool, `bool()` would be defined at every length and the pass-through could be simplified"
    )


def test_no_non_finite_survives_into_the_card_summary(hotspot_product):
    """The structural claim, quantified over every leaf rather than the fields we happened to name."""
    for target in ("ARM1", "GAPX", "LOWP", "NOTATARGET"):
        s = R.read_target_summary(target)
        bad = [(p, v) for p, v in _walk(s) if isinstance(v, float) and not math.isfinite(v)]
        assert bad == [], f"{target}: non-finite values reached the card summary: {bad}"
        json.dumps(s, indent=2, allow_nan=False, default=str)  # must not raise


def test_declared_defaults_fire_when_a_string_or_int_cell_is_missing(hotspot_product):
    """The `.get(k, default)` -> `or` rewrite.

    ⚠️ Defensive, not a corpus bug: on the shipped product these columns have no missing cells at all
    (`hotspot_pocket_adjacency_call` / `pdb_best_method` are object/0-null and `n_domains_low_plddt` is
    int64, which cannot hold one). The rewrite is here because a `.get` default fires on an ABSENT KEY and
    these keys are always PRESENT, so the declared default could never have fired whatever the value was.
    This fixture supplies the missing cells the product does not, so the spelling is actually exercised.
    """
    s = R.read_target_summary("GAPX")
    assert s["hotspot_pocket_adjacency_call"] == "no_structure"
    assert s["pdb_best_method"] == "none"
    assert s["n_domains_low_plddt"] == 0
    assert s["mutation_hotspot_in_druggable_pocket"] is False
    # A real 0 must not be rewritten by `or` into a different 0-like value, and a real 3 must survive.
    assert R.read_target_summary("LOWP")["n_domains_low_plddt"] == 3
    assert R.read_target_summary("ARM1")["n_domains_low_plddt"] == 0


def test_pdb_coverage_class_reads_the_id_list_not_the_truthiness_of_a_sentinel(hotspot_product):
    """`pdb_coverage_class` must come from the ID list, never from whether a sentinel is truthy.

    ⚠️⚠️ Recorded here originally as a NON-finding — *"`alphafold_prediction_id` is an object column, so it
    was already None and `af_only` was correct (object dtype, 94 null cells, all None)."* That reasoning was
    measured on pandas 2.3 and is **FALSE on pandas 3.0**, where the cell is `nan` and therefore truthy. The
    class assertions below hold under both regimes only because `_none_for_missing` normalises first; the
    fabrication itself is pinned version-free in
    `test_a_nan_sentinel_fabricates_af_only_which_is_why_string_columns_need_covering`.
    """
    assert R.read_target_summary("ARM1")["pdb_coverage_class"] == "partial"  # 3 ids, < 5
    assert R.read_target_summary("LOWP")["pdb_coverage_class"] == "partial"  # 1 id
    assert R.read_target_summary("GAPX")["pdb_coverage_class"] == "none"  # 0 ids, no model
    assert R.read_target_summary("GAPX")["pdb_ids_available"] == []


def test_a_nan_sentinel_fabricates_af_only_which_is_why_string_columns_need_covering():
    """★★ The STRING half of the conversion is load-bearing, and it is worth 50 product rows.

    `_classify_pdb_coverage` tests `if row.get("alphafold_prediction_id")` by TRUTHINESS, and `float('nan')`
    is truthy — so a null prediction id spelled as NaN makes the reader claim an AlphaFold model that does
    not exist, for a protein with no PDB structure either. Measured on the shipped product (20,329 rows):
    **94 null prediction ids, 50 of them with zero PDB IDs** ⇒ 50 rows answer `af_only` instead of `none` on
    any pandas that spells a missing string cell as NaN (>= 3.0 does, 2.x does not).

    ★ The NaN is constructed DIRECTLY rather than round-tripped through parquet, deliberately: which pandas
    produces one is the version-dependent part, while the defect is a property of the truthiness test. So
    this fixture stays a valid reproduction under either regime — the opposite of the assertion that CI
    refuted, which depended on the layer to produce a specific spelling.
    """
    nan_row = {"pdb_ids_available": [], "alphafold_prediction_id": float("nan")}
    assert R._classify_pdb_coverage(nan_row) == "af_only", (
        "the un-normalised path must still be shown to fabricate af_only — if this stops holding, the "
        "truthiness test was fixed at the point of use and this guard is the only thing still asserting it"
    )
    assert R._classify_pdb_coverage(R._none_for_missing(nan_row)) == "none", (
        "the conversion must normalise the sentinel before the truthiness test ever sees it"
    )


def test_infinity_is_preserved_because_it_is_a_value_not_a_gap(tmp_path, monkeypatch):
    """★ `pd.isna` means MISSING, not non-finite, and that is deliberate here.

    The sibling trap runs the other way (`pd.isna(inf) is False` lets an Inf through an absence guard).
    A +/-Inf in a numeric column is a VALUE; nulling it would destroy data. It must be refused at the
    writer under `allow_nan=False`, never laundered at this boundary — so this pins the NON-conversion
    rather than treating it as an oversight.
    """
    rows = [
        dict(HOTSPOT_ROWS[0], gene_symbol="INFX", uniprot_ac="P00009", pdb_best_resolution_angstrom=float("inf")),
        HOTSPOT_ROWS[1],
    ]
    path = tmp_path / "structure_features.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    monkeypatch.setattr(R, "CACHE_PARQUET", path)
    monkeypatch.setattr(R, "_DERIVED_STATUS", True)
    monkeypatch.setattr(R, "_LIGAND_STATUS", False)
    monkeypatch.setattr(R, "CACHE_LIGAND_PARQUET", tmp_path / "no_ligandability.parquet")
    R._load_structure_indexed.cache_clear()
    R._load_ligandability_indexed.cache_clear()
    try:
        s = R.read_target_summary("INFX")
        assert math.isinf(s["pdb_best_resolution_angstrom"]), "Inf is a value and must survive the boundary"
        assert R.read_target_summary("GAPX")["pdb_best_resolution_angstrom"] is None, "a gap is still a gap"
        # ...and the writer is what refuses it, which is the Stage-2 ratchet this fix precedes.
        with pytest.raises(ValueError, match="Out of range float"):
            json.dumps(s, allow_nan=False, default=str)
    finally:
        R._load_structure_indexed.cache_clear()
        R._load_ligandability_indexed.cache_clear()


def test_ligandability_class_default_fires_on_a_missing_cell(tmp_path, monkeypatch):
    """The same `.get` -> `or` rewrite on the second leg, which loads through the shared helper."""
    df = pd.DataFrame(
        [
            {
                "uniprot_id": "P01116",
                "gene_symbol": "KRAS",
                "structural_ligandability_class": "experimental_ligandable",
                "n_ligandability_axes": 2,
                "experimental_cocrystal": True,
                "druggable_pocket": True,
                "virtual_screen_hit": False,
                "cryptic_site": False,
                "annotated_binding_site": False,
                "foldable": True,
                "disorder_tractability_class": "mostly_ordered",
            },
            {
                "uniprot_id": "P09999",
                "gene_symbol": "GAPL",
                "structural_ligandability_class": None,
                "n_ligandability_axes": None,
                "experimental_cocrystal": None,
                "druggable_pocket": None,
                "virtual_screen_hit": None,
                "cryptic_site": None,
                "annotated_binding_site": None,
                "foldable": None,
                "disorder_tractability_class": None,
            },
        ]
    )
    cache = tmp_path / "structure_ligandability_per_protein.parquet"
    df.to_parquet(cache, index=False)
    monkeypatch.setattr(R, "CACHE_LIGAND_PARQUET", cache)
    monkeypatch.setattr(R, "_LIGAND_STATUS", True)
    monkeypatch.setattr(R, "_DERIVED_STATUS", False)
    R._load_ligandability_indexed.cache_clear()
    R._load_structure_indexed.cache_clear()
    try:
        gap = R.read_target_summary("GAPL")
        assert gap["structural_ligandability_class"] == "insufficient_evidence"
        assert gap["n_ligandability_axes"] == 0
        assert gap["has_druggable_pocket"] is False
        assert gap["ligandability_disorder_class"] is None, "a missing class abstains rather than defaulting"
        json.dumps(gap, allow_nan=False, default=str)
        # the populated row is untouched
        assert R.read_target_summary("KRAS")["structural_ligandability_class"] == "experimental_ligandable"
    finally:
        R._load_ligandability_indexed.cache_clear()
        R._load_structure_indexed.cache_clear()


def _walk(obj, path="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, obj
