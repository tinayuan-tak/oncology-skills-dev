"""Phase 3: the deterministic indication-lineage reduction (dependency_verdict_by_scope).

Unit-tests the SEL-honesty fix — reducing the pan-cancer lineage card to the QUERIED indication's DepMap
lineage — WITHOUT S3/LLM. ADDITIVE + verdict-INERT: the pooled dependency_verdict is unchanged (the
KRAS/COADREAD replay guard in test_functional_requirement_replay.py freezes the spine)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))


def _run_mod():
    spec = importlib.util.spec_from_file_location("_fr_run_scope", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _run_mod()


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
    assert M._infer_indication(_cards(indication="COADREAD")) == "COADREAD"
    assert M._infer_indication(_cards(indication="luad")) == "LUAD"          # normalized upper
    assert M._infer_indication(_cards(indication=None)) is None


def test_selective_in_indication_when_queried_lineage_is_an_enrichment_hit():
    # KRAS/COADREAD shape: Bowel IS a significant enrichment hit → the dependency is selective HERE.
    cards = _cards(enriched=[{"lineage": "Pancreas", "n": 74, "median_chronos": -1.83,
                              "effect_size": 0.73, "q_value": 2.7e-25},
                             {"lineage": "Bowel", "n": 88, "median_chronos": -1.18,
                              "effect_size": 0.53, "q_value": 3.8e-16}])
    read = M._indication_lineage_read(cards, "COADREAD")
    assert read["depmap_lineage"] == "Bowel"
    assert read["class"] == "selective_in_indication" and read["is_enriched"] is True
    assert read["n"] == 88 and read["q_value"] == 3.8e-16


def test_dependent_not_enriched_and_not_dependent_from_per_lineage():
    # Bowel present in the full table but NOT an enrichment hit: deep median → dependent_not_enriched;
    # shallow median → not_dependent_in_indication.
    dep = _cards(enriched=[{"lineage": "Pancreas", "n": 74, "q_value": 1e-20}],
                 per_lineage=[{"lineage": "Bowel", "n": 60, "median_chronos": -0.8}])
    assert M._indication_lineage_read(dep, "COADREAD")["class"] == "dependent_not_enriched"
    nod = _cards(enriched=[{"lineage": "Pancreas", "n": 74, "q_value": 1e-20}],
                 per_lineage=[{"lineage": "Bowel", "n": 60, "median_chronos": -0.1}])
    assert M._indication_lineage_read(nod, "COADREAD")["class"] == "not_dependent_in_indication"


def test_underpowered_lineage_never_over_read():
    cards = _cards(enriched=[], per_lineage=[{"lineage": "Bowel", "n": 3, "median_chronos": -1.5}])
    read = M._indication_lineage_read(cards, "COADREAD")
    assert read["class"] == "underpowered"     # n < floor beats the deep median


def test_not_in_panel_only_when_full_table_is_a_real_list():
    cards = _cards(enriched=[{"lineage": "Pancreas", "q_value": 1e-9}],
                   per_lineage=[{"lineage": "Pancreas", "n": 74, "median_chronos": -1.8}])
    assert M._indication_lineage_read(cards, "COADREAD")["class"] == "not_in_panel"
    # fixture-style placeholder (per_lineage_stats is a STRING) + no enrichment hit → data_unavailable,
    # NOT a false not_in_panel
    placeholder = _cards(enriched=[{"lineage": "Pancreas", "q_value": 1e-9}],
                         per_lineage="__omitted_from_fixture__ (list, 26 items)")
    assert M._indication_lineage_read(placeholder, "COADREAD")["class"] == "data_unavailable"


def test_shared_lineage_gets_a_caveat():
    # STAD → DepMap "Esophagus/Stomach" (shared with ESCA) → coarse-lineage caveat flagged
    read = M._indication_lineage_read(_cards(indication="STAD",
                                             enriched=[{"lineage": "Esophagus/Stomach", "n": 40,
                                                        "median_chronos": -0.9, "q_value": 1e-6}]),
                                      "STAD")
    assert read["depmap_lineage"] == "Esophagus/Stomach"
    assert read["shared_lineage_caveat"] is True


def test_no_indication_is_typed_empty_not_a_crash():
    read = M._indication_lineage_read(_cards(indication=None), None)
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
    per = [{"stratum": "MSI_H", "class": "strong_dependency", "evidence_state": "measured", "subgroup_n": 30},
           {"stratum": "MSS", "class": "not_dependent", "evidence_state": "measured", "subgroup_n": 106}]
    v = M._subtype_scope_verdict(per)
    assert v["by_stratum"] == {"MSI_H": "dependent", "MSS": "not_dependent"}
    assert v["n_admissible"] == 2
    assert "MSI_H" in v["headline"] and "MSS" in v["headline"]   # subgroup-specific read


def test_subtype_verdict_underpowered_never_over_read():
    # n < floor OR not measured → underpowered, never a subtype-specific call (multiple-testing guard)
    per = [{"stratum": "MSI_H", "class": "strong_dependency", "evidence_state": "measured", "subgroup_n": 12},
           {"stratum": "EBV", "class": "strong_dependency", "evidence_state": "underpowered", "subgroup_n": 4}]
    v = M._subtype_scope_verdict(per)
    assert v["by_stratum"] == {"MSI_H": "underpowered", "EBV": "underpowered"}
    assert v["n_admissible"] == 0
    assert "no adequately-powered" in v["headline"]


def test_subtype_verdict_present_in_panorama_block(monkeypatch):
    # the panorama block carries the authoritative subtype rung (dispatcher merges it into headline).
    # Stub resolve_cards so the test is credential-less (no S3): return a synthetic subgroup card.
    def _stub_resolve_cards(card_ids, target, indication, **kw):
        return [{"card_id": "subgroup-stratified-dependency",
                 "summary": {"cross_subgroup_delta_dependency": 0.5,
                             "per_subgroup_metrics": [
                                 {"stratum": "MSI_H", "class": "strong_dependency",
                                  "evidence_state": "measured", "median_chronos": -0.9, "subgroup_n": 30},
                                 {"stratum": "MSS", "class": "not_dependent",
                                  "evidence_state": "measured", "median_chronos": -0.3, "subgroup_n": 106}]}}]
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
        {"card_id": "dependency-lineage-selectivity",
         "summary": {"enriched_lineages": [], "per_lineage_stats": [
             {"lineage": "Esophagus/Stomach", "n": 40, "median_chronos": -0.55}],
                     "per_oncotree_code_stats": code_rows}},
        {"card_id": "abundance-dependency", "summary": {"indication": "STAD"}},
    ]


def test_sublineage_read_n_weighted_aggregate():
    rows = [{"oncotree_code": "STAD", "n": 60, "median_chronos": -0.8, "fraction_strongly_dependent": 0.5},
            {"oncotree_code": "TSTAD", "n": 20, "median_chronos": -0.4, "fraction_strongly_dependent": 0.2},
            {"oncotree_code": "ESCA", "n": 50, "median_chronos": 0.1, "fraction_strongly_dependent": 0.0}]
    sub = M._sublineage_read(_lineage_card_with_codes(rows), ["STAD", "TSTAD", "DSTAD"])
    assert sub["matched_codes"] == ["STAD", "TSTAD"]        # ESCA excluded; DSTAD absent
    assert sub["n"] == 80
    # n-weighted median = (-0.8*60 + -0.4*20)/80 = -0.7
    assert sub["median_chronos"] == -0.7


def test_indication_read_sublineage_resolves_shared_caveat(monkeypatch):
    # STAD → shared Esophagus/Stomach lineage + a curated code-set → sublineage read RESOLVES the caveat
    monkeypatch.setattr(M, "_indication_lineage_map", lambda: {
        "STAD": {"depmap_lineage": "Esophagus/Stomach", "depmap_oncotree_lineage": "Stomach_Adenocarcinoma",
                 "depmap_oncotree_codes": ["STAD", "TSTAD", "DSTAD", "SSRCC"]}})
    rows = [{"oncotree_code": "STAD", "n": 60, "median_chronos": -0.9, "fraction_strongly_dependent": 0.6},
            {"oncotree_code": "ESCA", "n": 50, "median_chronos": 0.1, "fraction_strongly_dependent": 0.0}]
    read = M._indication_lineage_read(_lineage_card_with_codes(rows), "STAD")
    assert read["sublineage_resolved"] is True
    assert read["shared_lineage_caveat"] is False          # resolved, not merely flagged
    assert read["matched_oncotree_codes"] == ["STAD"]      # ESCA de-confounded out
    assert read["class"] == "dependent_not_enriched"       # STAD median -0.9 <= -0.5, de-confounded from ESCA
    assert read["n"] == 60


def test_indication_read_falls_back_to_coarse_without_code_stats(monkeypatch):
    # code-set present but the card has NO per_oncotree_code_stats (e.g. old run) → coarse path, caveat stays
    monkeypatch.setattr(M, "_indication_lineage_map", lambda: {
        "STAD": {"depmap_lineage": "Esophagus/Stomach", "depmap_oncotree_codes": ["STAD", "TSTAD"]}})
    cards = [{"card_id": "dependency-lineage-selectivity",
              "summary": {"enriched_lineages": [],
                          "per_lineage_stats": [{"lineage": "Esophagus/Stomach", "n": 40, "median_chronos": -0.6}]}},
             {"card_id": "abundance-dependency", "summary": {"indication": "STAD"}}]
    read = M._indication_lineage_read(cards, "STAD")
    assert read.get("sublineage_resolved") is not True
    assert read["shared_lineage_caveat"] is True           # unresolved → still flagged (honest)
    assert read["class"] == "dependent_not_enriched"       # coarse Esophagus/Stomach median -0.6
