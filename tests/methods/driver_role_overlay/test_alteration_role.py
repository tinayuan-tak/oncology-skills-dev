"""alteration_role overlay — the OncoKB × IntOGen join + 4-role classification. No S3 (loaders
are monkeypatched with synthetic OncoKB dict + IntOGen DataFrame)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.driver_role_overlay import read as R  # noqa: E402


def _wire(monkeypatch, oncokb: dict, intogen_rows: list):
    # clear the lru_cache only if the real (cached) fn is still in place — guarded so a prior
    # test's monkeypatched lambda (no cache_clear) doesn't error.
    for fn in (R._load_oncokb_roles, R._load_intogen_compendium):
        if hasattr(fn, "cache_clear"):
            fn.cache_clear()
    monkeypatch.setattr(R, "_load_oncokb_roles", lambda: oncokb)
    cols = ["SYMBOL", "CANCER_TYPE", "ROLE", "QVALUE_COMBINATION", "%_SAMPLES_COHORT", "IS_DRIVER"]
    monkeypatch.setattr(R, "_load_intogen_compendium", lambda: pd.DataFrame(intogen_rows, columns=cols))


def test_gof_driver_oncogene_plus_intogen_act(monkeypatch):
    _wire(
        monkeypatch,
        {"KRAS": "ONCOGENE"},
        [
            {
                "SYMBOL": "KRAS",
                "CANCER_TYPE": "COAD",
                "ROLE": "Act",
                "QVALUE_COMBINATION": 1e-30,
                "%_SAMPLES_COHORT": 0.4,
                "IS_DRIVER": True,
            }
        ],
    )
    o = R.read_alteration_role("KRAS", "COADREAD")
    assert o["alteration_role"] == "direct_driver_gof"
    assert o["functional_direction"] == "activating"
    assert o["intogen_scope"] == "indication" and o["intogen_min_qvalue"] == 1e-30


def test_lof_driver_tsg_plus_intogen_lof(monkeypatch):
    _wire(
        monkeypatch,
        {"APC": "TSG"},
        [
            {
                "SYMBOL": "APC",
                "CANCER_TYPE": "COAD",
                "ROLE": "LoF",
                "QVALUE_COMBINATION": 1e-20,
                "%_SAMPLES_COHORT": 0.7,
                "IS_DRIVER": True,
            }
        ],
    )
    o = R.read_alteration_role("APC", "COADREAD")
    assert o["alteration_role"] == "direct_driver_lof" and o["functional_direction"] == "loss_of_function"


def test_dual_role_is_predictive_biomarker(monkeypatch):
    # OncoKB ONCOGENE_AND_TSG → ambiguous direction → predictive_biomarker
    _wire(monkeypatch, {"NOTCH1": "ONCOGENE_AND_TSG"}, [])
    o = R.read_alteration_role("NOTCH1", "HNSC")
    assert o["alteration_role"] == "predictive_biomarker"


def test_conflicting_directions_is_predictive_biomarker(monkeypatch):
    # OncoKB ONCOGENE but IntOGen LoF in this indication → conflict → marker, not a clean driver
    _wire(
        monkeypatch,
        {"X": "ONCOGENE"},
        [
            {
                "SYMBOL": "X",
                "CANCER_TYPE": "COAD",
                "ROLE": "LoF",
                "QVALUE_COMBINATION": 1e-10,
                "%_SAMPLES_COHORT": 0.2,
                "IS_DRIVER": True,
            }
        ],
    )
    o = R.read_alteration_role("X", "COADREAD")
    assert o["alteration_role"] == "predictive_biomarker"


def test_passenger_known_gene_no_driver_role(monkeypatch):
    _wire(monkeypatch, {"ACTB": "NEITHER"}, [])
    o = R.read_alteration_role("ACTB", "COADREAD")
    assert o["alteration_role"] == "passenger" and o["functional_direction"] is None


def test_data_unavailable_absent_from_both(monkeypatch):
    _wire(monkeypatch, {}, [])
    o = R.read_alteration_role("GHOST", "COADREAD")
    assert o["alteration_role"] == "data_unavailable"


def test_pan_cancer_scope_when_indication_absent(monkeypatch):
    # gene is an IntOGen driver but not in THIS indication's cohorts → pan_cancer scope, still classified
    _wire(
        monkeypatch,
        {"IDH1": "ONCOGENE"},
        [
            {
                "SYMBOL": "IDH1",
                "CANCER_TYPE": "GBM",
                "ROLE": "Act",
                "QVALUE_COMBINATION": 1e-15,
                "%_SAMPLES_COHORT": 0.8,
                "IS_DRIVER": True,
            }
        ],
    )
    o = R.read_alteration_role("IDH1", "COADREAD")  # COADREAD maps to COAD/READ, not GBM
    assert o["intogen_scope"] == "pan_cancer"
    assert o["alteration_role"] == "direct_driver_gof"  # OncoKB ONCOGENE + pan-cancer Act


def test_cli_build_and_figure(tmp_path, monkeypatch):
    import importlib

    pytest.importorskip("matplotlib")
    cli = importlib.import_module("methods.driver_role_overlay.cli")
    _wire(
        monkeypatch,
        {"KRAS": "ONCOGENE"},
        [
            {
                "SYMBOL": "KRAS",
                "CANCER_TYPE": "COAD",
                "ROLE": "Act",
                "QVALUE_COMBINATION": 1e-30,
                "%_SAMPLES_COHORT": 0.4,
                "IS_DRIVER": True,
            }
        ],
    )
    s = cli.build_summary("KRAS", "COADREAD")
    assert s["alteration_role"] == "direct_driver_gof" and "method_version" in s
    svg = cli.emit_svg("KRAS", "COADREAD", s, tmp_path)
    assert svg is not None and svg.exists()
    # data_unavailable (absent from both sources) → no figure (passenger DOES render — it's a real call)
    _wire(monkeypatch, {}, [])
    assert cli.emit_svg("GHOST", "COADREAD", cli.build_summary("GHOST", "COADREAD"), tmp_path) is None


# ---------------------------------------------------------------------------------------------
# CURATION IS NOT MEASUREMENT (2026-09-12). Three defects in the OncoKB x IntOGen join, each
# reproduced here on the real gene configuration that exposed it.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sym", "gene_type", "direction"),
    [("CD19", "ONCOGENE", "activating"), ("FOLR1", "ONCOGENE", "activating"), ("KEAP1X", "TSG", "loss_of_function")],
)
def test_curated_gene_list_membership_alone_is_not_a_driver_call(monkeypatch, sym, gene_type, direction):
    """DEFECT A. OncoKB gene-list membership with ZERO IntOGen rows used to read direct_driver_gof /
    direct_driver_lof — an in-indication driver claim from curation alone, for 440 of 1242 OncoKB
    genes. CD19/FOLR1/TACSTD2 are the live cases: oncokb=ONCOGENE, no driver call in ANY cohort."""
    _wire(monkeypatch, {sym: gene_type}, [])
    o = R.read_alteration_role(sym, "COADREAD")
    assert o["alteration_role"] == "curated_cancer_gene"
    assert o["intogen_role"] is None and o["intogen_scope"] is None
    # the curated DIRECTION is still honest evidence and is still reported...
    assert o["functional_direction"] == direction
    # ...but the ROLE withholds the driver claim, which is what gates the downstream rationale.
    assert o["alteration_role"] not in ("direct_driver_gof", "direct_driver_lof")
    assert "no patient-scale driver evidence" in o["_data_note"]


def test_curated_only_gene_cannot_reach_allele_selective_eligibility(monkeypatch):
    """The blast radius that makes DEFECT A more than a labelling nit: direct_driver_gof is a member
    of wt_loss_safety_conditioning.yaml's allele_selective_eligibility_rules (via
    alteration-role-gof-driver-supportive), so gene-list membership was buying an allele-selective
    WT-loss safety downgrade for targets with no measured selectable allele. It also feeds
    genomic-alteration-profile's modality_scope projection."""
    _wire(monkeypatch, {"TACSTD2": "ONCOGENE"}, [])
    assert R.read_alteration_role("TACSTD2", "BRCA")["alteration_role"] != "direct_driver_gof"


def _rows(sym, spec, cancer="COAD", q=1e-8):
    """spec = {'Act': n, 'LoF': m} → n+m compendium rows for one gene."""
    out = []
    for role, n in spec.items():
        for _ in range(n):
            out.append(
                {
                    "SYMBOL": sym,
                    "CANCER_TYPE": cancer,
                    "ROLE": role,
                    "QVALUE_COMBINATION": q,
                    "%_SAMPLES_COHORT": 0.05,
                    "IS_DRIVER": True,
                }
            )
    return out


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ({"LoF": 3, "Act": 2}, "ambiguous"),  # ROS1's real pan-cancer tally — near-tie, NOT a direction
        ({"Act": 5, "LoF": 4}, "ambiguous"),  # MET's real pan-cancer tally — won by ONE row
        ({"LoF": 2, "Act": 2}, "ambiguous"),  # CCND1 / MYC — tie
        ({"Act": 8, "LoF": 2}, "Act"),  # ALK — a genuinely dominant vote still resolves
        ({"Act": 29, "LoF": 1}, "Act"),  # ERBB2
        ({"LoF": 4}, "LoF"),  # unanimous
    ],
)
def test_split_per_cohort_vote_is_not_a_direction(spec, expected):
    """DEFECT B. _majority_role took a BARE row-count majority while its docstring claimed to weight
    confident calls, forcing a direction for 228 of the 274 IntOGen driver genes (43% of 633) whose
    per-cohort ROLE rows disagree."""
    df = pd.DataFrame(
        _rows("G", spec),
        columns=["SYMBOL", "CANCER_TYPE", "ROLE", "QVALUE_COMBINATION", "%_SAMPLES_COHORT", "IS_DRIVER"],
    )
    assert R._majority_role(df) == expected


def test_role_vote_is_deliberately_unweighted_by_significance():
    """Rejected alternative, pinned so it is not "fixed" later: weighting by q-value flips MET the
    WRONG way. MET/LUAD's LoF rows are the MORE significant ones (q=5.7e-6, 1.1e-2) and its Act row
    is weaker (q=9.0e-3), so a significance-weighted vote is MORE confidently wrong than a count."""
    cols = ["SYMBOL", "CANCER_TYPE", "ROLE", "QVALUE_COMBINATION", "%_SAMPLES_COHORT", "IS_DRIVER"]
    met = pd.DataFrame(
        [
            {
                "SYMBOL": "MET",
                "CANCER_TYPE": "LUAD",
                "ROLE": "LoF",
                "QVALUE_COMBINATION": 5.7e-6,
                "%_SAMPLES_COHORT": 0.013,
                "IS_DRIVER": True,
            },
            {
                "SYMBOL": "MET",
                "CANCER_TYPE": "LUAD",
                "ROLE": "Act",
                "QVALUE_COMBINATION": 9.0e-3,
                "%_SAMPLES_COHORT": 0.081,
                "IS_DRIVER": True,
            },
            {
                "SYMBOL": "MET",
                "CANCER_TYPE": "LUAD",
                "ROLE": "LoF",
                "QVALUE_COMBINATION": 1.1e-2,
                "%_SAMPLES_COHORT": 0.027,
                "IS_DRIVER": True,
            },
        ],
        columns=cols,
    )
    import math

    weighted = {r: sum(-math.log10(q) for q in met[met.ROLE == r]["QVALUE_COMBINATION"]) for r in ("Act", "LoF")}
    assert weighted["LoF"] > weighted["Act"], "premise of this guard: significance favours the WRONG direction here"
    # the vote itself stays a count, and the conflict rule (not the vote) is what saves MET:
    assert R._majority_role(met) == "LoF"
    assert R._resolve_direction("LoF", "ONCOGENE") == "ambiguous"


@pytest.mark.parametrize(
    ("intogen_role", "gene_type", "expected"),
    [
        ("Act", "TSG", "ambiguous"),  # SMARCA2: single Act row vs curated TSG
        ("LoF", "ONCOGENE", "ambiguous"),  # MET/LUAD, CDK4, ABL1, CD274, ERBB4
        ("Act", "ONCOGENE", "activating"),  # agreement → IntOGen leads, unchanged
        ("LoF", "TSG", "loss_of_function"),
        ("Act", None, "activating"),  # only IntOGen speaks
        (None, "TSG", "loss_of_function"),  # only OncoKB speaks
        # An UNRESOLVED IntOGen vote is the absence of a direction, not evidence against curation,
        # so it defers to the curated one (ROS1, CCND1, MYC — split or tied per-cohort rows).
        ("ambiguous", "ONCOGENE", "activating"),
        ("ambiguous", "TSG", "loss_of_function"),
        ("ambiguous", None, "ambiguous"),  # nothing to defer to
        ("ambiguous", "NEITHER", "ambiguous"),
        ("Act", "ONCOGENE_AND_TSG", "activating"),
        (None, None, None),
    ],
)
def test_inferred_direction_does_not_silently_outrank_curation(intogen_role, gene_type, expected):
    """DEFECT C, the root cause. IntOGen's inferred direction used to win unconditionally, so 80
    genes published alteration_role=predictive_biomarker ("direction not resolved") beside a fully
    definite functional_direction: 41 TSGs as activating (CHEK2, BARD1, CDKN2C, FANCA) and 39
    oncogenes as loss_of_function (CDK4, ABL1, CD274, ERBB4)."""
    assert R._resolve_direction(intogen_role, gene_type) == expected


def test_role_and_direction_can_never_contradict_each_other():
    """The invariant DEFECT C violated, swept over every (intogen_role x geneType) input the join can
    see: if the ROLE says the direction is unresolved, the DIRECTION may not name one."""
    contradictions = []
    for ir in (None, "Act", "LoF", "ambiguous"):
        for gt in (None, "ONCOGENE", "TSG", "ONCOGENE_AND_TSG", "NEITHER", "INSUFFICIENT_EVIDENCE"):
            role = R._classify_alteration_role(gt, ir, "indication" if ir else None)
            d = R._resolve_direction(ir, gt)
            if role == "predictive_biomarker" and d in ("activating", "loss_of_function"):
                contradictions.append((ir, gt, role, d))
            if role == "direct_driver_gof" and d == "loss_of_function":
                contradictions.append((ir, gt, role, d))
            if role == "direct_driver_lof" and d == "activating":
                contradictions.append((ir, gt, role, d))
            # ...and the converse, which the panel caught: a direct_driver_* role NAMES a direction,
            # so it may not sit beside a direction field that withholds one while a definite curated
            # direction was available to fall back on (ROS1/LUAD, CCND1, MYC).
            if role.startswith("direct_driver_") and d == "ambiguous" and gt in ("ONCOGENE", "TSG"):
                contradictions.append((ir, gt, role, d))
    assert not contradictions, f"role/direction contradictions: {contradictions}"


def test_every_role_the_classifier_emits_is_in_the_card_vocabulary():
    """Mirror guard: a role token the method can emit but the card does not declare fails validation
    downstream (fail-closed), so pin the two in sync here where the change is made."""
    import os

    import yaml

    root = Path(
        os.environ.get("TARGET_CONTRACTS_ROOT", Path.home() / "rnd-computational-biology-oncology-target-contracts")
    )
    card = root / "cards" / "alteration-role.card.yaml"
    if not card.exists():
        pytest.skip("target-contracts checkout not available")
    declared = set(yaml.safe_load(card.read_text())["outputs"]["summary_fields_vocabulary"]["alteration_role"])
    emitted = {
        R._classify_alteration_role(gt, ir, "indication" if ir else None)
        for ir in (None, "Act", "LoF", "ambiguous")
        for gt in (None, "ONCOGENE", "TSG", "ONCOGENE_AND_TSG", "NEITHER", "INSUFFICIENT_EVIDENCE")
    }
    assert "curated_cancer_gene" in emitted, "the new token must actually be reachable"
    assert emitted <= declared, f"emitted but NOT declared by the card: {sorted(emitted - declared)}"
