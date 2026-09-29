"""cms_classifier cohort scoping — the CMS NTP population must be the catalog's INDICATION narrowed
by OncotreeCode, never the coarse OncotreeLineage, and every scoping input must fail CLOSED.

Hermetic: builds a synthetic DepMap cache (expression CSV + Model.csv) under tmp_path and
monkeypatches `cli.cache_root` — the name in the RESOLVING namespace, since cli.py does
`from ...paths import cache_root`. No R, no network, no real DepMap.

WHY THIS FILE, given test_cms_classifier.py already exists: that suite mocks subprocess.run and hands
`_run_cms_classifier` a ready-made expression frame, so it never exercises the loader that decides
WHICH models are in the matrix. It cannot fail on a population defect. And the population is not a
presentation detail: CMScaller quantile-normalizes across the samples PRESENT and BH-adjusts the
permutation p across those same samples, so every per-sample FDR depends on who else is in the run.

NON-VACUITY: every model the narrowing is supposed to exclude is written into BOTH Model.csv and the
expression matrix, so the coarse `OncotreeLineage == "Bowel"` filter this replaced would have returned
them. `test_narrowing_is_a_strict_subset_of_the_coarse_lineage` asserts that directly, so this file
cannot pass against the implementation it was written to replace.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

pd = pytest.importorskip("pandas")
from methods.subgroup_assigner_classifier import cli  # noqa: E402
from methods.subgroup_common import lineage as _lineage  # noqa: E402

COADREAD_CODES = _lineage.INDICATION_TO_DEPMAP_ONCOTREE_CODES["COADREAD"]

# Illustrative of the real `Bowel` residue (anal squamous, appendiceal, small bowel), but the contract
# under test is only "an OncotreeCode outside the governed COADREAD set is excluded" — the exact
# spellings are not load-bearing, and are asserted rather than assumed by the first test below.
OFF_INDICATION_CODES = ("ANSC", "APAD", "SBC")

# (ModelID, OncotreeLineage, OncotreeCode, OncotreeSubtype, has_expression_row)
_MODELS = [
    ("ACH-C1", "Bowel", "COAD", "Colon Adenocarcinoma", True),
    ("ACH-C2", "Bowel", "READ", "Rectal Adenocarcinoma", True),
    ("ACH-C3", "Bowel", "MACR", "Mucinous Adenocarcinoma of the Colon and Rectum", True),
    ("ACH-C4", "Bowel", "COADREAD", "Colorectal Adenocarcinoma", True),
    # in the population but with no expression row — exercises the n-expression accounting
    ("ACH-C5", "Bowel", "COAD", "Colon Adenocarcinoma", False),
    # same lineage, DIFFERENT catalogued disease: the whole point of the narrowing
    ("ACH-O1", "Bowel", OFF_INDICATION_CODES[0], "Anal Squamous Cell Carcinoma", True),
    ("ACH-O2", "Bowel", OFF_INDICATION_CODES[1], "Appendiceal Adenocarcinoma", True),
    ("ACH-O3", "Bowel", OFF_INDICATION_CODES[2], "Small Bowel Cancer", True),
    # null OncotreeCode → UNCLASSIFIABLE, excluded with a counted disposition (not silently)
    ("ACH-N1", "Bowel", None, "Immortalized Colon Line", True),
    # a different lineage entirely — the lineage boundary must still hold
    ("ACH-L1", "Lung", "LUAD", "Lung Adenocarcinoma", True),
]

_EXPECTED_KEPT = {"ACH-C1", "ACH-C2", "ACH-C3", "ACH-C4"}


def _write_cache(tmp_path: Path, models=_MODELS, write_model_csv: bool = True) -> Path:
    """Write a synthetic framework-depmap-26q3 cache and return the root `cache_root()` should yield."""
    cache = tmp_path / "framework-depmap-26q3"
    cache.mkdir(parents=True, exist_ok=True)

    expressed = [m for m in models if m[4]]
    rows = []
    for i, (model_id, *_rest) in enumerate(expressed):
        rows.append(
            {
                "ModelID": model_id,
                "IsDefaultEntryForModel": "Yes",
                # gene columns MUST carry the '(Entrez)' suffix or _parse_entrez drops them
                "GENEA (1)": 1.0 + i,
                "GENEB (2)": 2.0 + i,
                # a metadata column with no Entrez suffix — must not survive as a "gene"
                "StrippedCellLineName": f"LINE{i}",
            }
        )
    pd.DataFrame(rows).to_csv(cache / "OmicsExpressionProteinCodingGenesTPMLogp1.csv", index=False)

    if write_model_csv:
        pd.DataFrame(
            [
                {"ModelID": m, "OncotreeLineage": lin, "OncotreeCode": code, "OncotreeSubtype": sub}
                for (m, lin, code, sub, _has_expr) in models
            ]
        ).to_csv(cache / "Model.csv", index=False)

    return tmp_path


@pytest.fixture()
def depmap_cache(tmp_path, monkeypatch):
    root = _write_cache(tmp_path)
    monkeypatch.setattr(cli, "cache_root", lambda: root)
    return root


def test_off_indication_fixture_codes_are_really_off_indication():
    """The fixture's 'off-indication' codes must actually be outside the governed COADREAD set.

    Without this, a set that silently grew to include them would make every exclusion assertion below
    vacuous while still reporting green.
    """
    assert not (set(OFF_INDICATION_CODES) & set(COADREAD_CODES))
    assert {"COAD", "READ", "MACR", "COADREAD"} <= set(COADREAD_CODES)


def test_population_is_the_indication_not_the_lineage(depmap_cache, capsys):
    df = cli._load_depmap_expression_full("COADREAD", reference_cohort="depmap_bowel")

    assert set(df.index) == _EXPECTED_KEPT
    # off-indication, null-code and other-lineage models are all gone
    assert not ({"ACH-O1", "ACH-O2", "ACH-O3", "ACH-N1", "ACH-L1"} & set(df.index))
    # metadata column did not survive as a gene
    assert list(df.columns) == ["GENEA (1)", "GENEB (2)"]

    out = capsys.readouterr().out
    assert "narrowed 'Bowel'" in out, out
    # the population is 5 COADREAD models, 4 of which have expression
    assert "4 of 5 COADREAD models" in out, out
    assert "1 have no expression row" in out, out


def test_narrowing_is_a_strict_subset_of_the_coarse_lineage(depmap_cache):
    """The falsification control: the replaced implementation returned the whole Bowel lineage.

    If the loader ever reverts to an `OncotreeLineage == 'Bowel'` filter, `kept` becomes `coarse` and
    the strict-subset assertion fails. A test that cannot distinguish the two implementations would be
    measuring nothing.
    """
    model = pd.read_csv(depmap_cache / "framework-depmap-26q3" / "Model.csv")
    expressed = set(
        pd.read_csv(depmap_cache / "framework-depmap-26q3" / "OmicsExpressionProteinCodingGenesTPMLogp1.csv")["ModelID"]
    )
    coarse = set(model[model["OncotreeLineage"] == "Bowel"]["ModelID"]) & expressed

    kept = set(cli._load_depmap_expression_full("COADREAD", reference_cohort="depmap_bowel").index)

    assert kept < coarse, f"narrowing kept {sorted(kept)}, coarse lineage would give {sorted(coarse)}"
    assert len(coarse) - len(kept) == 4, "expected 3 off-indication + 1 null-code model to be dropped"


def test_missing_reference_cohort_fails_closed(depmap_cache):
    with pytest.raises(ValueError, match="must declare `reference_cohort`"):
        cli._load_depmap_expression_full("COADREAD", reference_cohort=None)


def test_unknown_reference_cohort_fails_closed(depmap_cache):
    """An unrecognised token used to yield lineage=None → NO filter and NO warning at all."""
    with pytest.raises(KeyError, match="Unknown reference_cohort"):
        cli._load_depmap_expression_full("COADREAD", reference_cohort="depmap_notathing")


def test_missing_indication_fails_closed(depmap_cache):
    with pytest.raises(ValueError, match="no `indication`"):
        cli._load_depmap_expression_full(None, reference_cohort="depmap_bowel")


def test_missing_model_csv_fails_closed(tmp_path, monkeypatch):
    """Model.csv absent used to emit a stderr warning and return the WHOLE DepMap panel at exit 0."""
    root = _write_cache(tmp_path, write_model_csv=False)
    monkeypatch.setattr(cli, "cache_root", lambda: root)
    with pytest.raises(FileNotFoundError, match="REQUIRED to scope the CMS cohort"):
        cli._load_depmap_expression_full("COADREAD", reference_cohort="depmap_bowel")


def test_config_lineage_disagreeing_with_catalog_indication_is_loud(depmap_cache):
    """`reference_cohort` and `indication` route the same axis, so one must assert against the other.

    A catalog retargeted to STAD with `reference_cohort: depmap_bowel` left behind would otherwise
    emit a bowel cohort under a gastric label.
    """
    with pytest.raises(ValueError, match="declares OncotreeLineage 'Bowel'"):
        cli._load_depmap_expression_full("STAD", reference_cohort="depmap_bowel")


def test_population_with_no_expression_rows_is_loud(tmp_path, monkeypatch):
    """A code set that matches models the expression matrix lacks must raise, not return empty."""
    models = [m for m in _MODELS if m[0] not in _EXPECTED_KEPT and m[0] != "ACH-C5"]
    models.append(("ACH-C9", "Bowel", "COAD", "Colon Adenocarcinoma", False))
    root = _write_cache(tmp_path, models=models)
    monkeypatch.setattr(cli, "cache_root", lambda: root)
    with pytest.raises(ValueError, match="No expression rows for any of the 1 COADREAD models"):
        cli._load_depmap_expression_full("COADREAD", reference_cohort="depmap_bowel")


def test_unnarrowed_indication_warns_that_expected_n_inherits_the_lineage(tmp_path, monkeypatch, capsys):
    """An indication with no declared OncotreeCode set gets the whole lineage — LOUDLY.

    BRCA is one of `LINEAGE_NOT_VERIFIED_PURE`: it carries a MAF-backed catalog, a null governed
    `depmap_oncotree_codes` lane, and measurable off-indication residue. Reaching this branch needs a
    `_REFERENCE_COHORT_ONCOTREE_LINEAGE` entry, so the map is extended here rather than the branch
    being left unreachable-by-construction and therefore untested.
    """
    assert "BRCA" in _lineage.LINEAGE_NOT_VERIFIED_PURE
    assert "BRCA" not in _lineage.INDICATION_TO_DEPMAP_ONCOTREE_CODES

    models = [
        ("ACH-B1", "Breast", "BRCA", "Invasive Breast Carcinoma", True),
        ("ACH-B2", "Breast", "IDC", "Breast Invasive Ductal Carcinoma", True),
        ("ACH-B3", "Breast", None, "Immortalized Breast Line", True),
    ]
    root = _write_cache(tmp_path, models=models)
    monkeypatch.setattr(cli, "cache_root", lambda: root)
    monkeypatch.setitem(cli._REFERENCE_COHORT_ONCOTREE_LINEAGE, "depmap_breast", "Breast")

    df = cli._load_depmap_expression_full("BRCA", reference_cohort="depmap_breast")

    # the WHOLE lineage, including the null-code immortalized line
    assert set(df.index) == {"ACH-B1", "ACH-B2", "ACH-B3"}
    captured = capsys.readouterr()
    assert "NOT NARROWED" in captured.out, captured.out
    assert "WARNING: CMS population is the WHOLE 'Breast' lineage" in captured.err, captured.err
    assert "expected_n" in captured.err, captured.err
