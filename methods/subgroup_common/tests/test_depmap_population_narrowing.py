"""Guards for indication-level narrowing of the DepMap lineage slice.

Two design notes, because both are load-bearing and neither is obvious:

1. THE FROZEN CENSUS CARRIES THE LOAD. Every population size below is asserted against
   a literal transcription of DepMap 26Q3 Model.csv, not against a live read. A live-only
   guard would `skip` wherever S3/the cache is absent, and a SKIP is not a PASS — the
   suite would go green on a machine that never evaluated the invariant. The one live leg
   (`test_frozen_census_matches_live_model_csv`) is opportunistic and checks DRIFT only;
   it is allowed to skip precisely because nothing else depends on it.

2. THE NEGATIVE CONTROL IS THE POINT. The defect this module fixes produced two BYTE-
   IDENTICAL parquets for ESCA and STAD (md5 0d0562a3...), i.e. the two indications were
   literally the same model set. `test_indications_sharing_a_lineage_are_disjoint` is the
   assertion that identity violated; reverting the narrowing must turn it RED. A guard
   that passes both with and against the fix measures nothing.

Mirroring tests/methods/depmap_chronos/test_lineage_map_single_source.py.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from methods.subgroup_common.lineage import (
    INDICATION_TO_DEPMAP_ONCOTREE_CODES,
    INDICATION_TO_DEPMAP_ORGAN,
    INDICATION_TO_DEPMAP_SUBTYPE_CLAIMS,
    LINEAGE_NOT_VERIFIED_PURE,
    SHARED_LINEAGE_NOT_NARROWED,
    depmap_population_for,
)

# DepMap 26Q3 Model.csv, transcribed 2026-09-26 for the three lineages that merge
# distinct catalogued indications. (OncotreeSubtype, OncotreeCode, n_models); a None
# code is a genuinely null cell in the CSV, not a transcription gap.
MODEL_CSV_26Q3: dict[str, list[tuple[str, str | None, int]]] = {
    "Lung": [
        ("Lung Adenocarcinoma", "LUAD", 147),
        ("Small Cell Lung Cancer", "SCLC", 86),
        ("Lung Squamous Cell Carcinoma", "LUSC", 32),
        ("Non-Small Cell Lung Cancer", "NSCLC", 17),
        ("Large Cell Lung Carcinoma", "LCLC", 14),
        ("Lung Adenosquamous Carcinoma", "LUAS", 6),
        ("Mucoepidermoid Carcinoma of the Lung", "LUMEC", 6),
        ("Giant Cell Carcinoma of the Lung", "GCLC", 4),
        ("Lung Carcinoid", "LUCA", 4),
        ("NUT Carcinoma of the Lung", "NUTCL", 4),
        ("Poorly Differentiated Non-Small Cell Lung Cancer", "NSCLCPD", 1),
        ("Immortalized Epithelial Cells, Lung", None, 4),
        ("SMARCA4-deficient undifferentiated tumor", None, 4),
        ("Immortalized Lung Cells", None, 1),
        ("Immortalized MPLC Cells", None, 1),
    ],
    # NOTE the OncotreeSubtype strings are VERBATIM, abbreviations and all: DepMap
    # writes "AML, NOS" and "AML with Minimal Differentiation", not the expanded
    # "Acute Myeloid Leukemia ...". Expanding them here (which the first draft of this
    # file did) is invisible to the population sizes — those four are selected by
    # OncotreeCode — but it breaks the drift leg and, more importantly, it would break
    # INDICATION_TO_DEPMAP_SUBTYPE_CLAIMS, which matches on the EXACT string.
    "Myeloid": [
        ("Acute Myeloid Leukemia", "AML", 62),
        ("Chronic Myeloid Leukemia, BCR-ABL1+", "CMLBCRABL1", 20),
        ("AML, NOS", "AMLNOS", 7),
        ("AML with Myelodysplasia-Related Changes", "AMLMRC", 5),
        ("Acute Monoblastic/Monocytic Leukemia", "AMOL", 5),
        ("Acute Leukemias of Ambiguous Lineage", "ALAL", 4),
        ("Acute Megakaryoblastic Leukemia", "AMKL", 3),
        ("Myeloid Leukemia Associated with Down Syndrome", "MLADS", 3),
        ("AML with Minimal Differentiation", "AMLMD", 1),
        ("Acute Myelomonocytic Leukemia", "AMML", 1),
        ("Mixed Phenotype Acute Leukemia with t(v;11q23.3); KMT2A Rearranged", "MPALKMT2A", 1),
        ("Acute Promyelocytic Leukemia", None, 1),
        ("Immortalized Blood", None, 2),
        ("Spherocytosis", None, 1),
    ],
    # Bowel and Eye merge no catalogued PEER, so they are absent from
    # COLLAPSED_LINEAGE_PEERS below, but they are still narrowed: a lineage can be impure
    # without merging a second catalogued indication.
    "Bowel": [
        ("Colon Adenocarcinoma", "COAD", 84),
        ("Colorectal Adenocarcinoma", "COADREAD", 31),
        ("Rectal Adenocarcinoma", "READ", 15),
        ("Mucinous Adenocarcinoma of the Colon and Rectum", "MACR", 4),
        ("Anal Squamous Cell Carcinoma", "ANSC", 3),
        ("Duodenal Adenocarcinoma", "DA", 2),
        ("Signet Ring Cell Type of the Appendix", "SRAP", 2),
        ("High-Grade Neuroendocrine Carcinoma of the Colon and Rectum", "HGNEC", 1),
        ("Small Bowel Cancer", "SBC", 1),
        ("Small Intestinal Carcinoma", "SIC", 1),
        ("Tubular Adenoma of the Colon", "TAC", 1),
        ("Immortalized Colon Mucosal Epithelial Cells", None, 1),
        ("Sessile Serrated Adenoma", None, 1),
        ("Tubulovillous adenoma", None, 1),
    ],
    "Eye": [
        ("Uveal Melanoma", "UM", 17),
        ("Immortalized Epithelial Cells, Retinal", None, 6),
        ("Retinoblastoma", "RBL", 6),
        ("Immortalized Epithelial Cells, Corneal", None, 1),
    ],
    "Esophagus/Stomach": [
        ("Stomach Adenocarcinoma", "STAD", 75),
        ("Esophageal Adenocarcinoma", "ESCA", 69),
        ("Esophageal Squamous Cell Carcinoma", "ESCC", 31),
        ("Tubular Stomach Adenocarcinoma", "TSTAD", 9),
        ("Diffuse Type Stomach Adenocarcinoma", "DSTAD", 7),
        ("Signet Ring Cell Carcinoma of the Stomach", "SSRCC", 3),
        ("Small Cell Carcinoma of the Stomach", "STSC", 2),
        ("Adenosquamous Carcinoma of the Stomach", "STAS", 1),
        ("Mucinous Stomach Adenocarcinoma", "MSTAD", 1),
        ("Adenocarcinoma of the Gastroesophageal Junction", "GEJ", 1),
    ],
}

# Lineage totals, restated independently of the census so a transcription slip in either
# one shows up as a disagreement rather than cancelling out.
LINEAGE_TOTALS = {
    "Lung": 331,
    "Myeloid": 116,
    "Esophagus/Stomach": 199,
    "Bowel": 148,
    "Eye": 30,
}

# Which indications each collapsed lineage merges. The whole defect is that the lineage
# filter returned the union of these rather than one of them.
COLLAPSED_LINEAGE_PEERS = {
    "Lung": ["NSCLC", "SCLC"],
    "Myeloid": ["AML", "CML"],
    "Esophagus/Stomach": ["ESCA", "STAD"],
}

# Pinned BY VALUE, not derived from the code sets: deriving would make the test a
# restatement of the implementation and any roster growth would be self-ratifying.
EXPECTED_POPULATION = {
    "NSCLC": 231,
    "SCLC": 86,
    "AML": 88,  # 87 by code + 1 Acute Promyelocytic Leukemia claimed by subtype
    "CML": 20,
    "ESCA": 101,
    "STAD": 98,
    "COADREAD": 134,  # 148 Bowel - 14 (11 off-indication incl. 3 anal squamous + 3 null-code)
    "UVM": 17,  # 30 Eye - 6 retinoblastoma - 7 immortalized: the largest relative cut
}

# The governed target-contracts `depmap_oncotree_codes` lane, transcribed 2026-09-14 for
# every indication where it is FILLED (6 of 35). Frozen rather than read live: no CI job
# sees both repos, so a live-only comparison degrades to a vacuous skip exactly where it
# would matter. The live leg below checks this literal for drift.
GOVERNED_CROSSWALK_CODES = {
    "COADREAD": {"COAD", "COADREAD", "READ", "MACR"},
    "NSCLC": {"LUAD", "LUSC", "NSCLC", "LCLC", "LUAS", "LUMEC", "GCLC", "NUTCL", "NSCLCPD"},
    "SCLC": {"SCLC"},
    "STAD": {"STAD", "TSTAD", "DSTAD", "SSRCC", "MSTAD", "STAS", "STSC"},
    "ESCA": {"ESCA"},
    "UVM": {"UM"},
}

# Divergences from the governed lane, each one DECLARED with its reason and its measured
# cost. Anything not listed here must match the lane byte-for-byte.
DECLARED_CROSSWALK_DIVERGENCES = {
    "ESCA": (
        "lane holds ['ESCA'] alone (69 models); adopting it would drop the 31 ESCC and 1 "
        "GEJ models the production organ substring has always included, narrowing the "
        "population 1.46x. The lane is under-curated; fix it in target-contracts."
    ),
}

# Sibling REPO root: derived from this file, never from $HOME. Under a /tmp/wt worktree
# Path.home() would reach past the worktree's own siblings into the home checkout, so the
# guard would validate a different tree than the one under test.
_TARGET_CONTRACTS_ROOT = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT")
    or Path(__file__).resolve().parents[3].parent / "rnd-computational-biology-oncology-target-contracts"
)
CROSSWALK_PATH = _TARGET_CONTRACTS_ROOT / "vocabularies" / "indication_crosswalk.yaml"

# Path.home() IS correct here: a per-user cache, not a sibling checkout.
LIVE_MODEL_CSV = Path.home() / ".cache" / "framework-depmap-26q3" / "Model.csv"


def _frozen_model_df() -> pd.DataFrame:
    """Build a Model.csv-shaped frame from the frozen census.

    Also emits 11 Pancreas/PAAD rows so the NOT-NARROWED branch is reachable offline.
    PAAD's lineage merges nothing, so it is the un-narrowed control: without it that
    branch would only ever be exercised by a live read.
    """
    rows = []

    def _add(lineage: str, code: str | None, subtype: str, n: int) -> None:
        # ModelID is a bare sequence number, NOT derived from code/subtype: a derived id
        # collides (the four Lung "Immortalized *" subtypes all share a null code and a
        # common prefix), and duplicate ids would make the disjointness and partition
        # assertions below silently weaker.
        for _ in range(n):
            rows.append(
                {
                    "ModelID": f"ACH-{len(rows):06d}",
                    "OncotreeLineage": lineage,
                    "OncotreeCode": code,
                    "OncotreeSubtype": subtype,
                }
            )

    for lineage, census in MODEL_CSV_26Q3.items():
        for subtype, code, n in census:
            _add(lineage, code, subtype, n)
    _add("Pancreas", "PAAD", "Pancreatic Adenocarcinoma", 11)
    df = pd.DataFrame(rows)
    assert df["ModelID"].is_unique, "frozen census must not fabricate duplicate ModelIDs"
    return df


@pytest.fixture(scope="module")
def model_df() -> pd.DataFrame:
    return _frozen_model_df()


def test_frozen_census_totals_agree_with_the_declared_lineage_sizes(model_df):
    for lineage, total in LINEAGE_TOTALS.items():
        assert sum(n for _, _, n in MODEL_CSV_26Q3[lineage]) == total, lineage
        assert int((model_df["OncotreeLineage"] == lineage).sum()) == total, lineage


@pytest.mark.parametrize("indication,expected", sorted(EXPECTED_POPULATION.items()), ids=sorted(EXPECTED_POPULATION))
def test_narrowed_population_size_is_pinned(indication, expected, model_df):
    pop = depmap_population_for(indication, model_df)
    assert pop.narrowed is True
    assert pop.kept == expected, f"{indication}: {pop.note}"


def test_narrowing_is_a_strict_reduction_for_every_narrowed_indication(model_df):
    """0 < kept < total. `kept == total` is the bug; `kept == 0` is the mirror bug.

    Iterates EXPECTED_POPULATION rather than COLLAPSED_LINEAGE_PEERS: COADREAD and UVM
    are narrowed without merging a catalogued peer, so a peers-only loop would have left
    the two newest code sets structurally unchecked.
    """
    for indication in EXPECTED_POPULATION:
        pop = depmap_population_for(indication, model_df)
        assert pop.lineage_total == LINEAGE_TOTALS[pop.lineage], pop.lineage
        assert 0 < pop.kept < pop.lineage_total, f"{indication} did not narrow {pop.lineage}: {pop.note}"


def test_every_lineage_model_is_accounted_for(model_df):
    """kept + off_indication + unclassifiable == lineage_total.

    The partition identity catches silent INCLUSION and silent EXCLUSION with one
    assertion, which matters because a shrinking denominator reads as a more careful
    cohort and would otherwise pass unremarked.

    NOTE this identity does NOT discriminate the merge defect it was written alongside:
    with narrowing reverted it holds trivially (kept == total, other two zero). Measured
    by the falsification run, and recorded here so a green result on this test is not
    mistaken for evidence that narrowing happened at all — that is
    test_indications_sharing_a_lineage_are_disjoint's job.
    """
    for indication in EXPECTED_POPULATION:
        pop = depmap_population_for(indication, model_df)
        assert pop.kept + pop.off_indication + pop.unclassifiable == pop.lineage_total, (
            f"{indication}: {pop.kept} + {pop.off_indication} + {pop.unclassifiable} != {pop.lineage_total}"
        )


def test_code_sets_match_the_governed_crosswalk_lane_or_declare_a_divergence():
    """The vocabulary is the source of truth; a fork must be DECLARED, not silent.

    Both directions are checked. Adopting a lane blindly is not safe either — ESCA's
    lane is a 1.46x silent narrowing — so a divergence is allowed, but only with a
    written reason, which is what makes it reviewable instead of invisible.
    """
    for indication, governed in GOVERNED_CROSSWALK_CODES.items():
        mine = INDICATION_TO_DEPMAP_ONCOTREE_CODES.get(indication)
        assert mine is not None, (
            f"{indication} has a FILLED governed depmap_oncotree_codes lane but no code "
            f"set here, so its slice is still the whole lineage"
        )
        if indication in DECLARED_CROSSWALK_DIVERGENCES:
            assert set(mine) != governed, (
                f"{indication} is listed as a declared divergence but now MATCHES the "
                f"governed lane — delete the stale declaration"
            )
            assert DECLARED_CROSSWALK_DIVERGENCES[indication].strip()
        else:
            assert set(mine) == governed, (
                f"{indication} diverges from the governed crosswalk lane without a "
                f"declaration: here {sorted(mine)}, lane {sorted(governed)}"
            )
    # A declaration for an indication with no governed lane would be meaningless.
    assert set(DECLARED_CROSSWALK_DIVERGENCES) <= set(GOVERNED_CROSSWALK_CODES)


@pytest.mark.skipif(not CROSSWALK_PATH.exists(), reason="target-contracts sibling absent")
def test_governed_crosswalk_literal_matches_the_sibling_repo():
    """DRIFT check on GOVERNED_CROSSWALK_CODES. Allowed to skip — see the module docstring.

    Deliberately asserts the FILLED SET too, not just the values: if the lane gains an
    entry (e.g. HNSC or AML get curated) this goes red, which is the signal to narrow a
    population that is currently lineage-wide.
    """
    import yaml

    doc = yaml.safe_load(CROSSWALK_PATH.read_text())
    entries = doc.get("indications", doc)
    if isinstance(entries, dict):
        items = entries.items()
    else:
        items = [(e.get("canonical_code"), e) for e in entries]
    live = {
        code: set(v["depmap_oncotree_codes"])
        for code, v in items
        if isinstance(v, dict) and v.get("depmap_oncotree_codes")
    }
    assert live == GOVERNED_CROSSWALK_CODES, (
        "governed depmap_oncotree_codes lane drifted from the frozen literal; "
        f"only in lane: {set(live) - set(GOVERNED_CROSSWALK_CODES)}, "
        f"only frozen: {set(GOVERNED_CROSSWALK_CODES) - set(live)}"
    )


def test_indications_sharing_a_lineage_are_disjoint(model_df):
    """THE negative control. Pre-fix, ESCA and STAD were byte-identical model sets."""
    for lineage, peers in COLLAPSED_LINEAGE_PEERS.items():
        pops = {ind: depmap_population_for(ind, model_df) for ind in peers}
        for i, a in enumerate(peers):
            for b in peers[i + 1 :]:
                overlap = pops[a].model_ids & pops[b].model_ids
                assert not overlap, (
                    f"{a} and {b} both claim {len(overlap)} models of {lineage!r}; "
                    f"an indication-keyed population cannot overlap a peer's"
                )


def test_unclassifiable_models_are_excluded_from_every_peer(model_df):
    """A null OncotreeCode belongs to no indication, and the count is REPORTED.

    Two distinct numbers per lineage, pinned separately on purpose: how many models
    carry a null code at all, and how many are still unclaimed once the declared
    subtype claims have run. Collapsing them would let a claim appear or disappear
    without moving any asserted value.
    """
    null_code_models = {"Lung": 10, "Myeloid": 4, "Esophagus/Stomach": 0}
    unclaimed_after_claims = {"Lung": 10, "Myeloid": 3, "Esophagus/Stomach": 0}
    for lineage, peers in COLLAPSED_LINEAGE_PEERS.items():
        in_lineage = model_df[model_df["OncotreeLineage"] == lineage]
        null_ids = set(in_lineage[in_lineage["OncotreeCode"].isna()]["ModelID"])
        assert len(null_ids) == null_code_models[lineage], lineage
        claimed = set()
        for indication in peers:
            pop = depmap_population_for(indication, model_df)
            mine = pop.model_ids & null_ids
            claimed |= mine
            # Reported `unclassifiable` must be exactly the null-code models this
            # indication did NOT claim, so the excluded count is never a silent drop.
            assert pop.unclassifiable == len(null_ids) - len(mine), (
                f"{indication} miscounted its unclassifiable disposition: {pop.note}"
            )
        # Only the declared subtype claims may reach back into the null-code set.
        assert len(null_ids) - len(claimed) == unclaimed_after_claims[lineage], lineage


def test_the_apl_claim_is_exercised_and_is_the_only_one(model_df):
    """Acute Promyelocytic Leukemia is definitionally AML but carries a null code."""
    assert set(INDICATION_TO_DEPMAP_SUBTYPE_CLAIMS) == {"AML"}
    aml = depmap_population_for("AML", model_df)
    assert aml.claimed_by_subtype == 1, aml.note
    assert "claimed by exact OncotreeSubtype" in aml.note
    # Without the claim AML would be 87; the claim is what makes the pinned 88 correct.
    assert aml.kept == 87 + aml.claimed_by_subtype
    for other in ("CML", "NSCLC", "SCLC", "ESCA", "STAD"):
        assert depmap_population_for(other, model_df).claimed_by_subtype == 0, other


def test_code_sets_reproduce_the_production_organ_substrings(model_df):
    """The superseded substring map and the new code sets must select the SAME models.

    `two files route the same axis`: subgroup_assigner_directly_tagged still reads
    INDICATION_TO_DEPMAP_ORGAN, so a divergence would silently give the two lanes
    different populations for the same indication.
    """
    for indication, organ in INDICATION_TO_DEPMAP_ORGAN.items():
        pop = depmap_population_for(indication, model_df)
        in_lineage = model_df[model_df["OncotreeLineage"] == pop.lineage]
        by_substring = frozenset(
            in_lineage[in_lineage["OncotreeSubtype"].str.lower().str.contains(organ, na=False)]["ModelID"]
        )
        assert pop.model_ids == by_substring, (
            f"{indication}: code set selects {pop.kept} models, organ substring {organ!r} selects {len(by_substring)}"
        )


def test_declared_codes_all_exist_in_the_census(model_df):
    """No declared code may be a typo — an unmatched code silently contributes zero."""
    live_codes = set(model_df["OncotreeCode"].dropna())
    for indication, codes in INDICATION_TO_DEPMAP_ONCOTREE_CODES.items():
        pop_lineage = depmap_population_for(indication, model_df).lineage
        in_lineage = set(model_df[model_df["OncotreeLineage"] == pop_lineage]["OncotreeCode"].dropna())
        unknown = set(codes) - live_codes
        assert not unknown, f"{indication} declares codes absent from Model.csv: {unknown}"
        misplaced = set(codes) - in_lineage
        assert not misplaced, f"{indication} declares codes outside {pop_lineage!r}: {misplaced}"


def test_declared_subtype_claims_all_exist_in_the_census(model_df):
    live_subtypes = set(model_df["OncotreeSubtype"])
    for indication, claims in INDICATION_TO_DEPMAP_SUBTYPE_CLAIMS.items():
        unknown = set(claims) - live_subtypes
        assert not unknown, f"{indication} claims subtypes absent from Model.csv: {unknown}"
        # A claim only has effect on a null-code row; asserting that keeps the mechanism
        # honest (a claim on a coded row would double-count against the code set).
        rows = model_df[model_df["OncotreeSubtype"].isin(claims)]
        assert rows["OncotreeCode"].isna().all(), (
            f"{indication} claims a subtype that already carries an OncotreeCode; "
            f"use INDICATION_TO_DEPMAP_ONCOTREE_CODES instead"
        )


def test_unnarrowed_shared_lineage_roster_is_exact():
    """Pinned by value so the roster cannot grow in silence.

    Every name here is an indication whose lineage merges >=2 diseases and that has NO
    code set, i.e. it still receives a lineage-wide population. Adding a name must be a
    deliberate edit to this list, not a side effect of leaving a code set out.
    """
    assert SHARED_LINEAGE_NOT_NARROWED == frozenset(
        {
            "ACC",
            "PCPG",
            "GBM",
            "LGG",
            "KICH",
            "KIRC",
            "KIRP",
            "BCC",
            "MELANOMA",
            "SKCM",
            "UCEC",
            "UCS",
        }
    )
    # Disjoint from the narrowed set by construction: an indication cannot be both.
    assert not SHARED_LINEAGE_NOT_NARROWED & set(INDICATION_TO_DEPMAP_ONCOTREE_CODES)


def test_not_verified_pure_roster_is_exact_and_disjoint():
    """The three indications with a MAF catalog, a null lane, and measured residue."""
    assert LINEAGE_NOT_VERIFIED_PURE == frozenset({"BRCA", "HNSC", "PAAD"})
    # An indication cannot be both narrowed and un-narrowed, nor in both rosters.
    assert not LINEAGE_NOT_VERIFIED_PURE & set(INDICATION_TO_DEPMAP_ONCOTREE_CODES)
    assert not LINEAGE_NOT_VERIFIED_PURE & SHARED_LINEAGE_NOT_NARROWED
    # None of them may have a governed lane — if one gains codes, narrow it instead.
    assert not LINEAGE_NOT_VERIFIED_PURE & set(GOVERNED_CROSSWALK_CODES), (
        "an indication with a filled governed lane must be narrowed, not merely flagged"
    )


def test_an_unnarrowed_indication_returns_the_whole_lineage_and_never_claims_purity(model_df):
    """PAAD receives its whole lineage, and the note says so WITHOUT implying purity.

    The wording is asserted, not just the flag: the first draft said the lineage "is not
    declared as merging indications", which reads as a purity claim. PAAD's `Pancreas`
    does merge no catalogued peer and is still impure (1 PANET, 1 immortalized stromal),
    so that phrasing was actively misleading on this exact indication.
    """
    pop = depmap_population_for("PAAD", model_df)
    assert pop.narrowed is False
    assert pop.kept == 11 == pop.lineage_total
    assert "NOT NARROWED" in pop.note
    assert "not verified pure" in pop.note.lower(), pop.note
    assert pop.off_indication == 0 and pop.unclassifiable == 0


@pytest.mark.skipif(not LIVE_MODEL_CSV.exists(), reason="DepMap 26Q3 Model.csv not cached")
def test_frozen_census_matches_live_model_csv():
    """DRIFT check only. Allowed to skip; the offline legs above carry the invariant."""
    live = pd.read_csv(LIVE_MODEL_CSV)
    for lineage, census in MODEL_CSV_26Q3.items():
        in_lineage = live[live["OncotreeLineage"] == lineage]
        observed = in_lineage.groupby(in_lineage["OncotreeSubtype"], dropna=False).size().to_dict()
        expected = {subtype: n for subtype, _, n in census}
        assert observed == expected, f"{lineage} census drifted from the frozen literal"
        codes = {
            subtype: (None if pd.isna(c) else c)
            for subtype, c in in_lineage.set_index("OncotreeSubtype")["OncotreeCode"].to_dict().items()
        }
        assert codes == {subtype: code for subtype, code, _ in census}, (
            f"{lineage} subtype->code mapping drifted from the frozen literal"
        )
    for indication, expected in EXPECTED_POPULATION.items():
        pop = depmap_population_for(indication, live)
        assert pop.kept == expected, f"live {indication}: {pop.note}"
