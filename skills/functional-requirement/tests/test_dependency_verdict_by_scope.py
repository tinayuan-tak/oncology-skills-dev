"""Phase 3: the deterministic indication-lineage reduction (dependency_verdict_by_scope).

Unit-tests the SEL-honesty fix — reducing the pan-cancer lineage card to the QUERIED indication's DepMap
lineage — WITHOUT S3/LLM. ADDITIVE + verdict-INERT: the pooled dependency_verdict is unchanged (the
KRAS/COADREAD replay guard in test_functional_requirement_replay.py freezes the spine)."""

from __future__ import annotations

from pathlib import Path

import _skills_common.dependency_indication as DI
from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent

M = load_run_py(SKILL_DIR, "_fr_run_scope")
# Stage 5b: the indication-lineage reduction moved to _skills_common.dependency_indication (single home
# for the `dependency` card preprocessor). Reference the moved functions THERE — monkeypatching M would
# be a no-op because _indication_lineage_read resolves _indication_lineage_map in DI's namespace, not M's.
# _dependency_verdict_by_scope / _subtype_scope_verdict / resolve_cards still live in run.py (= M).


def _cards(*, indication="COADREAD", enriched=None, per_lineage=None):
    """A minimal card set: the lineage card + one indication-echoing card so _infer_indication works."""
    lineage_summary = {}
    if enriched is not None:
        lineage_summary["enriched_lineages"] = enriched
    if per_lineage is not None:
        lineage_summary["per_lineage_stats"] = per_lineage
    return [
        {"card_id": "dependency-lineage-selectivity", "summary": lineage_summary},
        {"card_id": "abundance-dependency", "summary": {"indication": indication} if indication else {}},
    ]


def test_infer_indication_from_card_summary():
    assert DI._infer_indication(_cards(indication="COADREAD")) == "COADREAD"
    assert DI._infer_indication(_cards(indication="luad")) == "LUAD"  # normalized upper
    assert DI._infer_indication(_cards(indication=None)) is None


def test_selective_in_indication_when_queried_lineage_is_an_enrichment_hit():
    # KRAS/COADREAD shape: Bowel IS a significant enrichment hit → the dependency is selective HERE.
    cards = _cards(
        enriched=[
            {"lineage": "Pancreas", "n": 74, "median_chronos": -1.83, "effect_size": 0.73, "q_value": 2.7e-25},
            {"lineage": "Bowel", "n": 88, "median_chronos": -1.18, "effect_size": 0.53, "q_value": 3.8e-16},
        ]
    )
    read = DI._indication_lineage_read(cards, "COADREAD")
    assert read["depmap_lineage"] == "Bowel"
    assert read["class"] == "selective_in_indication" and read["is_enriched"] is True
    assert read["n"] == 88 and read["q_value"] == 3.8e-16


def test_dependent_not_enriched_and_not_dependent_from_per_lineage():
    # Bowel present in the full table but NOT an enrichment hit: deep median → dependent_not_enriched;
    # shallow median → not_dependent_in_indication.
    dep = _cards(
        enriched=[{"lineage": "Pancreas", "n": 74, "q_value": 1e-20}],
        per_lineage=[{"lineage": "Bowel", "n": 60, "median_chronos": -0.8}],
    )
    assert DI._indication_lineage_read(dep, "COADREAD")["class"] == "dependent_not_enriched"
    nod = _cards(
        enriched=[{"lineage": "Pancreas", "n": 74, "q_value": 1e-20}],
        per_lineage=[{"lineage": "Bowel", "n": 60, "median_chronos": -0.1}],
    )
    assert DI._indication_lineage_read(nod, "COADREAD")["class"] == "not_dependent_in_indication"


def test_underpowered_lineage_never_over_read():
    cards = _cards(enriched=[], per_lineage=[{"lineage": "Bowel", "n": 3, "median_chronos": -1.5}])
    read = DI._indication_lineage_read(cards, "COADREAD")
    assert read["class"] == "underpowered"  # n < floor beats the deep median


def test_not_in_panel_only_when_full_table_is_a_real_list():
    cards = _cards(
        enriched=[{"lineage": "Pancreas", "q_value": 1e-9}],
        per_lineage=[{"lineage": "Pancreas", "n": 74, "median_chronos": -1.8}],
    )
    assert DI._indication_lineage_read(cards, "COADREAD")["class"] == "not_in_panel"
    # fixture-style placeholder (per_lineage_stats is a STRING) + no enrichment hit → data_unavailable,
    # NOT a false not_in_panel
    placeholder = _cards(
        enriched=[{"lineage": "Pancreas", "q_value": 1e-9}], per_lineage="__omitted_from_fixture__ (list, 26 items)"
    )
    assert DI._indication_lineage_read(placeholder, "COADREAD")["class"] == "data_unavailable"


def test_shared_lineage_gets_a_caveat():
    # STAD → DepMap "Esophagus/Stomach" (shared with ESCA) → coarse-lineage caveat flagged
    read = DI._indication_lineage_read(
        _cards(
            indication="STAD",
            enriched=[{"lineage": "Esophagus/Stomach", "n": 40, "median_chronos": -0.9, "q_value": 1e-6}],
        ),
        "STAD",
    )
    assert read["depmap_lineage"] == "Esophagus/Stomach"
    assert read["shared_lineage_caveat"] is True


def test_no_indication_is_typed_empty_not_a_crash():
    read = DI._indication_lineage_read(_cards(indication=None), None)
    assert read["class"] == "data_unavailable" and read["scope"] == "indication"


def test_by_scope_structure_pan_cancer_passthrough_and_subtype_placeholder():
    cards = _cards(enriched=[{"lineage": "Bowel", "n": 88, "median_chronos": -1.18, "q_value": 1e-16}])
    by = M._dependency_verdict_by_scope(cards, ("lineage_selective", "lineage-selective-supportive"))
    assert set(by) == {"pan_cancer", "indication", "subtype"}
    # pan-cancer rung is the pooled verdict verbatim (byte-stable)
    assert by["pan_cancer"]["verdict"] == "lineage_selective"
    assert by["pan_cancer"]["driving_rule_id"] == "lineage-selective-supportive"
    # indication rung is the reduced lineage read; subtype is a Phase-4 placeholder (authoritative
    # subtype verdict rides in the --subtypes panorama, resolved after this placeholder)
    assert by["indication"]["class"] == "selective_in_indication"
    assert by["subtype"]["class"] == "not_scoped_this_run"


# --- Phase 4: subtype-scope verdict (power-gated per-stratum call in the --subtypes panorama) --------


def test_subtype_verdict_powered_strata_get_real_calls():
    per = [
        {"stratum": "MSI_H", "class": "strong_dependency", "evidence_state": "measured", "subgroup_n": 30},
        {"stratum": "MSS", "class": "not_dependent", "evidence_state": "measured", "subgroup_n": 106},
    ]
    v = M._subtype_scope_verdict(per)
    assert v["by_stratum"] == {"MSI_H": "dependent", "MSS": "not_dependent"}
    assert v["n_admissible"] == 2
    assert "MSI_H" in v["headline"] and "MSS" in v["headline"]  # subgroup-specific read


def test_subtype_verdict_underpowered_never_over_read():
    # n < floor OR not measured → underpowered, never a subtype-specific call (multiple-testing guard)
    per = [
        {"stratum": "MSI_H", "class": "strong_dependency", "evidence_state": "measured", "subgroup_n": 12},
        {"stratum": "EBV", "class": "strong_dependency", "evidence_state": "underpowered", "subgroup_n": 4},
    ]
    v = M._subtype_scope_verdict(per)
    assert v["by_stratum"] == {"MSI_H": "underpowered", "EBV": "underpowered"}
    assert v["n_admissible"] == 0
    assert "no adequately-powered" in v["headline"]


def test_subtype_verdict_present_in_panorama_block(monkeypatch):
    # the panorama block carries the authoritative subtype rung (dispatcher merges it into headline).
    # Stub resolve_cards so the test is credential-less (no S3): return a synthetic subgroup card.
    def _stub_resolve_cards(card_ids, target, indication, **kw):
        return [
            {
                "card_id": "subgroup-stratified-dependency",
                "summary": {
                    "cross_subgroup_delta_dependency": 0.5,
                    "per_subgroup_metrics": [
                        {
                            "stratum": "MSI_H",
                            "class": "strong_dependency",
                            "evidence_state": "measured",
                            "median_chronos": -0.9,
                            "subgroup_n": 30,
                        },
                        {
                            "stratum": "MSS",
                            "class": "not_dependent",
                            "evidence_state": "measured",
                            "median_chronos": -0.3,
                            "subgroup_n": 106,
                        },
                    ],
                },
            }
        ]

    monkeypatch.setattr(M, "resolve_cards", _stub_resolve_cards)
    pan = M._resolve_dependency_subtype_panorama("KRAS", "COADREAD", ["MSI_H", "MSS"])
    block = pan["subtype_dependency_panorama"]
    assert "subtype_verdict" in block
    assert block["subtype_verdict"]["by_stratum"] == {"MSI_H": "dependent", "MSS": "not_dependent"}
    # descriptive pattern still computed alongside the verdict
    assert block["subtype_dependency_pattern"] == "subgroup_specific_dependency"


# --- Phase 3b consumer: sublineage de-confounding of shared coarse lineages -----------------


def _lineage_card_with_codes(code_rows):
    """A dependency-lineage-selectivity card carrying per_oncotree_code_stats (+ a coarse Esophagus/
    Stomach row so the fallback path is also exercisable)."""
    return [
        {
            "card_id": "dependency-lineage-selectivity",
            "summary": {
                "enriched_lineages": [],
                "per_lineage_stats": [{"lineage": "Esophagus/Stomach", "n": 40, "median_chronos": -0.55}],
                "per_oncotree_code_stats": code_rows,
            },
        },
        {"card_id": "abundance-dependency", "summary": {"indication": "STAD"}},
    ]


def test_sublineage_read_n_weighted_aggregate():
    rows = [
        {"oncotree_code": "STAD", "n": 60, "median_chronos": -0.8, "fraction_strongly_dependent": 0.5},
        {"oncotree_code": "TSTAD", "n": 20, "median_chronos": -0.4, "fraction_strongly_dependent": 0.2},
        {"oncotree_code": "ESCA", "n": 50, "median_chronos": 0.1, "fraction_strongly_dependent": 0.0},
    ]
    sub = DI._sublineage_read(_lineage_card_with_codes(rows), ["STAD", "TSTAD", "DSTAD"])
    assert sub["matched_codes"] == ["STAD", "TSTAD"]  # ESCA excluded; DSTAD absent
    assert sub["n"] == 80
    # n-weighted median = (-0.8*60 + -0.4*20)/80 = -0.7
    assert sub["median_chronos"] == -0.7


def test_indication_read_sublineage_resolves_shared_caveat(monkeypatch):
    # STAD → shared Esophagus/Stomach lineage + a curated code-set → sublineage read RESOLVES the caveat
    monkeypatch.setattr(
        DI,
        "_indication_lineage_map",
        lambda: {
            "STAD": {
                "depmap_lineage": "Esophagus/Stomach",
                "depmap_oncotree_lineage": "Stomach_Adenocarcinoma",
                "depmap_oncotree_codes": ["STAD", "TSTAD", "DSTAD", "SSRCC"],
            }
        },
    )
    rows = [
        {"oncotree_code": "STAD", "n": 60, "median_chronos": -0.9, "fraction_strongly_dependent": 0.6},
        {"oncotree_code": "ESCA", "n": 50, "median_chronos": 0.1, "fraction_strongly_dependent": 0.0},
    ]
    read = DI._indication_lineage_read(_lineage_card_with_codes(rows), "STAD")
    assert read["sublineage_resolved"] is True
    assert read["shared_lineage_caveat"] is False  # resolved, not merely flagged
    assert read["matched_oncotree_codes"] == ["STAD"]  # ESCA de-confounded out
    assert read["class"] == "dependent_not_enriched"  # STAD median -0.9 <= -0.5, de-confounded from ESCA
    assert read["n"] == 60


def test_indication_read_falls_back_to_coarse_without_code_stats(monkeypatch):
    # code-set present but the card has NO per_oncotree_code_stats (e.g. old run) → coarse path, caveat stays
    monkeypatch.setattr(
        DI,
        "_indication_lineage_map",
        lambda: {"STAD": {"depmap_lineage": "Esophagus/Stomach", "depmap_oncotree_codes": ["STAD", "TSTAD"]}},
    )
    cards = [
        {
            "card_id": "dependency-lineage-selectivity",
            "summary": {
                "enriched_lineages": [],
                "per_lineage_stats": [{"lineage": "Esophagus/Stomach", "n": 40, "median_chronos": -0.6}],
            },
        },
        {"card_id": "abundance-dependency", "summary": {"indication": "STAD"}},
    ]
    read = DI._indication_lineage_read(cards, "STAD")
    assert read.get("sublineage_resolved") is not True
    assert read["shared_lineage_caveat"] is True  # unresolved → still flagged (honest)
    assert read["class"] == "dependent_not_enriched"  # coarse Esophagus/Stomach median -0.6


# --- shared_lineage_caveat: the POPULATION the caveat is derived over ------------------------------
# These pin the fix for a caveat that was near-unreachable. It used to be `bool(depmap_oncotree_codes)`
# — a field filled on 6 of 35 indications — so six LIVE indications whose coarse DepMap lineage merges
# ≥2 diseases reported `shared_lineage_caveat: false`, and the only way to observe a True caveat was a
# `_sublineage_read` failure. The old test for the caveat pinned STAD, which is IN the 6 that carry a
# code set, so it passed on exactly the population where the check could not fail.
#
# Every test below reads the REAL crosswalk deliberately. A monkeypatched 1-entry map has lineage
# multiplicity 1 by construction and would make the multiplicity half of the predicate vacuous.

_MULTIPLICITY_ONLY = ["GBM", "LGG", "KIRC", "SKCM", "UCEC", "AML"]  # shared lineage, NO code set
_SUBSET_DECL_ONLY = ["COADREAD", "UVM"]  # sole crosswalk indication on the lineage, code set present
_PURE_LINEAGE = ["BRCA", "PRAD", "OV", "PAAD", "HNSC", "BLCA", "LIHC", "CESC", "DLBC"]


def test_shared_lineage_without_a_code_set_still_gets_a_caveat():
    """The regression this fix closes: GBM and LGG BOTH map to DepMap `CNS/Brain` — they are pooled with
    each other — and neither has an authored `depmap_oncotree_codes`. Under the old `bool(codes)`
    predicate both read `shared_lineage_caveat: false` on a demonstrably confounded coarse read."""
    xw = DI._indication_lineage_map()
    for code in _MULTIPLICITY_ONLY:
        entry = xw[code]
        assert not entry.get("depmap_oncotree_codes"), f"{code} gained a code set — move it out of this list"
        assert DI._lineage_is_shared(entry) is True, f"{code} ({entry['depmap_lineage']}) lost its caveat"

    read = DI._indication_lineage_read(
        _cards(indication="GBM", enriched=[{"lineage": "CNS/Brain", "n": 60, "median_chronos": -0.9, "q_value": 1e-6}]),
        "GBM",
    )
    assert read["depmap_lineage"] == "CNS/Brain"
    assert read["shared_lineage_caveat"] is True
    assert read.get("sublineage_resolved") is not True  # no code set → nothing to resolve WITH


def test_caveat_population_is_derived_and_nonempty_in_both_directions():
    """Anti-vacuity + coverage. Both poles must be populated from the LIVE crosswalk, so the check can
    fail either way, and the confounded set must not shrink silently as the vocabulary is edited."""
    xw = DI._indication_lineage_map()
    shared = {c for c in xw if DI._lineage_is_shared(xw[c])}
    assert shared, "no indication reads as shared — the caveat would be unreachable"
    assert set(xw) - shared, "every indication reads as shared — the caveat would be meaningless"
    missing = [c for c in _MULTIPLICITY_ONLY + _SUBSET_DECL_ONLY if c not in shared]
    assert not missing, f"known-confounded indications no longer flagged: {missing}"


def test_the_two_sharedness_signals_are_a_union_neither_alone_suffices():
    """MULTIPLICITY (≥2 canonical indications on one lineage) and the STRICT-SUBSET DECLARATION
    (`depmap_oncotree_codes`) each cover cases the other cannot. Multiplicity alone regresses COADREAD
    ⊂ Bowel and UVM ⊂ Eye, whose other lineage members (anal squamous, appendiceal, retinoblastoma) are
    not themselves crosswalk indications. The declaration alone misses the six in _MULTIPLICITY_ONLY."""
    xw = DI._indication_lineage_map()
    by_multiplicity = DI._shared_depmap_lineages(xw)

    for code in _SUBSET_DECL_ONLY:
        entry = xw[code]
        assert entry.get("depmap_oncotree_codes"), f"{code} lost its code set"
        assert entry["depmap_lineage"] not in by_multiplicity, (
            f"{code}'s lineage gained a second indication — it is no longer a subset-declaration-only case"
        )
        assert DI._lineage_is_shared(entry) is True

    for code in _MULTIPLICITY_ONLY:
        assert xw[code]["depmap_lineage"] in by_multiplicity


def test_pure_lineages_do_not_get_a_caveat():
    """The negative pole: an indication that is the only disease on its DepMap lineage and declares no
    subset must NOT be flagged, or the caveat degenerates into a banner on every run."""
    xw = DI._indication_lineage_map()
    for code in _PURE_LINEAGE:
        assert DI._lineage_is_shared(xw[code]) is False, f"{code} ({xw[code]['depmap_lineage']}) falsely flagged"


def test_aliases_do_not_inflate_lineage_multiplicity():
    """LUAD and LUSC are ALIASES of NSCLC and inherit its `Lung`. Counting raw map keys would read Lung
    as a 4-way split and, worse, would make any aliased lineage look shared on its own account."""
    xw = DI._indication_lineage_map()
    assert xw["LUAD"]["canonical_code"] == "NSCLC"
    assert xw["LUSC"]["canonical_code"] == "NSCLC"
    lung_canonical = {xw[c]["canonical_code"] for c in xw if xw[c].get("depmap_lineage") == "Lung"}
    assert lung_canonical == {"NSCLC", "SCLC"}, f"Lung multiplicity counted aliases: {lung_canonical}"


def test_sublineage_still_clears_the_caveat_when_a_code_set_resolves():
    """The resolution half is untouched: a shared lineage WITH a code set and per-code stats resolves at
    the sublineage grain and CLEARS the caveat rather than merely flagging it."""
    cards = [
        {
            "card_id": "dependency-lineage-selectivity",
            "summary": {
                "enriched_lineages": [],
                "per_lineage_stats": [{"lineage": "Esophagus/Stomach", "n": 40, "median_chronos": -0.6}],
                "per_oncotree_code_stats": [
                    {"oncotree_code": "STAD", "n": 22, "median_chronos": -1.1},
                    {"oncotree_code": "DSTAD", "n": 9, "median_chronos": -0.95},
                ],
            },
        },
        {"card_id": "abundance-dependency", "summary": {"indication": "STAD"}},
    ]
    read = DI._indication_lineage_read(cards, "STAD")
    assert read["sublineage_resolved"] is True
    assert read["shared_lineage_caveat"] is False


def test_the_coarse_lineage_badge_is_reachable_for_a_confounded_indication():
    """End of the chain. `dependency_question_table` appends `⚠ coarse-lineage (shared)` to the Q3 row
    off `by_scope.indication.shared_lineage_caveat`, so while the caveat was effectively `bool(codes)`
    the badge was near-unreachable in a healthy run — it needed a `_sublineage_read` FAILURE. The Q3
    block is fed from the REAL FR producer here rather than a hand-written `indication` dict: a
    hand-set flag would render the badge under the old predicate too and measure nothing."""
    import sys

    sys.path.insert(0, str(SKILL_DIR.parents[1]))
    from _skills_common.dependency_question_table import dependency_question_table

    cards = _cards(
        indication="GBM",
        enriched=[{"lineage": "CNS/Brain", "n": 60, "median_chronos": -0.9, "q_value": 1e-6}],
    )
    by_scope = M._dependency_verdict_by_scope(cards, ("concordant_dependent", "DEP-R1"))
    ind = by_scope["indication"]
    assert ind["shared_lineage_caveat"] is True
    assert ind["class"] not in (None, "data_unavailable", "not_scoped_this_run"), (
        "Q3 falls back to the target-grain read for these classes and never reaches the badge branch"
    )

    rows = dependency_question_table({"dependency_verdict_by_scope": by_scope}, cards, claim_vector={"SEL": {}})
    q3 = next(r for r in rows if r.get("id") == "Q3")
    assert "⚠ coarse-lineage (shared)" in q3["primary"], q3

    # ...and NOT for a pure lineage, or the badge is decoration rather than a signal.
    pure = M._dependency_verdict_by_scope(
        _cards(indication="BRCA", enriched=[{"lineage": "Breast", "n": 50, "median_chronos": -0.9, "q_value": 1e-6}]),
        ("concordant_dependent", "DEP-R1"),
    )
    assert pure["indication"]["shared_lineage_caveat"] is False
    assert pure["indication"]["class"] not in (None, "data_unavailable", "not_scoped_this_run"), (
        "the negative pole must reach the SAME badge branch — otherwise it passes via the Q3 fallback"
    )
    rows_pure = dependency_question_table({"dependency_verdict_by_scope": pure}, cards, claim_vector={"SEL": {}})
    q3_pure = next(r for r in rows_pure if r.get("id") == "Q3")
    assert "coarse-lineage" not in q3_pure["primary"], q3_pure
