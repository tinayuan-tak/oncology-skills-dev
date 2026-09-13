"""Hermetic tests for harvest_literature — stubs the fan-out; NO live S3 / NO Bedrock.

Runs via: pixi run pytest eval/tests/test_harvest_literature.py -q   (from the home checkout).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

_EVAL = Path(__file__).resolve().parents[1]
if str(_EVAL) not in sys.path:
    sys.path.insert(0, str(_EVAL))

import harvest_literature as hl  # noqa: E402


def test_parse_pairs():
    assert hl._parse_pairs("KRAS/COADREAD, MET/LUAD") == [("KRAS", "COADREAD"), ("MET", "LUAD")]
    assert hl._parse_pairs("") == []


def test_normalize_verdict():
    assert hl._normalize_verdict(("lineage_selective", "rule-x")) == ("lineage_selective", "rule-x")
    assert hl._normalize_verdict(None) == (None, None)
    assert hl._normalize_verdict(("v",)) == ("v", None)


def test_harvest_pair_projects_records(monkeypatch):
    """Stub _run_sub_skills so harvest_pair runs with no network. Only sub-skills whose lane
    actually ran (literature_synthesis present) yield a record."""
    fake = {
        "dependency": {
            "skill_dir": "functional-requirement",
            "verdict": ("lineage_selective", "lineage-selective-supportive"),
            "fired": [{"rule_id": "lineage-selective-supportive"}, {"rule_id": "x-neutral"}],
            "synthesis_facet": {
                "claim_vector": {"DEP": {"signal": "strong", "corroboration": "high"}},
                "literature_synthesis": {
                    "overall_consistency": "concordant",
                    "key_divergence": "none",
                    "axes": [],
                    "blind_spots": [],
                    "_model_id": "us.anthropic.claude-opus-4-8",
                    "_prompt_hash": "h1",
                },
            },
        },
        # a skill with no lane (no literature_synthesis) → skipped
        "target_intrinsic": {
            "skill_dir": "target-intrinsic",
            "verdict": None,
            "fired": [],
            "synthesis_facet": {"claim_vector": {}},
        },
    }
    stub = types.ModuleType("tp_fanout")
    stub._run_sub_skills = lambda *a, **k: fake  # noqa: E731
    monkeypatch.setitem(sys.modules, "tp_fanout", stub)

    recs = hl.harvest_pair("KRAS", "COADREAD", literature_scope="gating")
    assert len(recs) == 1
    r = recs[0]
    assert r["target"] == "KRAS" and r["indication"] == "COADREAD"
    assert r["skill"] == "functional-requirement"  # skill DIR id, not the short
    assert r["sub_verdict"]["verdict"] == "lineage_selective"
    assert r["sub_verdict"]["driving_rule_id"] == "lineage-selective-supportive"
    assert r["sub_verdict"]["fired_rule_ids"] == ["lineage-selective-supportive", "x-neutral"]
    assert r["claim_vector"]["DEP"]["signal"] == "strong"
    assert r["_provenance"]["model_id"] == "us.anthropic.claude-opus-4-8"


def test_canonical_symbol_maps_aliases():
    """The calibration-set alias KEYS resolve to their HGNC-canonical gene symbol; canonical /
    unknown symbols pass through unchanged (CASE-011)."""
    assert hl._canonical_symbol("HER2") == "ERBB2"
    assert hl._canonical_symbol("TROP2") == "TACSTD2"
    assert hl._canonical_symbol("BCMA") == "TNFRSF17"
    assert hl._canonical_symbol("CD20") == "MS4A1"
    assert hl._canonical_symbol(" HER2 ") == "ERBB2"  # whitespace-tolerant
    assert hl._canonical_symbol("KRAS") == "KRAS"  # already canonical → unchanged
    assert hl._canonical_symbol("NOT_A_GENE") == "NOT_A_GENE"


def test_harvest_pair_runs_on_canonical_symbol_but_labels_the_alias(monkeypatch):
    """CASE-011 regression: the fan-out is invoked on the HGNC symbol (ERBB2), so gene-keyed
    readers resolve, while the emitted record stays LABELLED with the calibration alias (HER2) —
    calibration_gap tagging + the snapshot filename remain keyed by the display symbol."""
    seen = {}

    def _capture(target, indication, **kw):
        seen["target"] = target
        seen["indication"] = indication
        return {
            "tractability_sm": {
                "skill_dir": "tractability-small-molecule",
                "verdict": ("chemically_active", "prism-clinically-active-supportive-sm"),
                "fired": [{"rule_id": "prism-clinically-active-supportive-sm"}],
                "synthesis_facet": {
                    "claim_vector": {},
                    "literature_synthesis": {
                        "overall_consistency": "concordant",
                        "axes": [],
                        "blind_spots": [],
                        "_model_id": "m",
                        "_prompt_hash": "h",
                    },
                },
            },
        }

    stub = types.ModuleType("tp_fanout")
    stub._run_sub_skills = _capture
    monkeypatch.setitem(sys.modules, "tp_fanout", stub)

    recs = hl.harvest_pair("HER2", "BRCA")
    assert seen["target"] == "ERBB2"  # fan-out ran on the HGNC symbol
    assert len(recs) == 1
    assert recs[0]["target"] == "HER2"  # record keeps the alias label
    assert recs[0]["resolved_symbol"] == "ERBB2"  # audit trail records the resolution
    assert recs[0]["sub_verdict"]["verdict"] == "chemically_active"


def test_harvested_records_feed_the_aggregator(monkeypatch, tmp_path):
    """End-to-end (offline): harvest → snapshot → build_discordance_ledger."""
    import json

    import build_discordance_ledger as bdl

    fake = {
        "genomic_alteration": {
            "skill_dir": "genomic-alteration-profile",
            "verdict": ("passenger_or_absent", "no-recurrent-driver-neutral"),
            "fired": [{"rule_id": "no-recurrent-driver-neutral"}],
            "synthesis_facet": {
                "claim_vector": {},
                "literature_synthesis": {
                    "overall_consistency": "discordant",
                    "key_divergence": "METex14 driver",
                    "axes": [
                        {
                            "axis_key": "A",
                            "literature_read": "strongly_supports",
                            "assertion": "METex14 is a validated driver.",
                            "agreement_vs_omics": "contradicts",
                            "confidence": "high",
                            "citations": [{"label": "Paik 2020", "pmid": "32469185", "verified": True}],
                        }
                    ],
                    "blind_spots": [],
                    "_model_id": "m",
                    "_prompt_hash": "h",
                },
            },
        },
    }
    stub = types.ModuleType("tp_fanout")
    stub._run_sub_skills = lambda *a, **k: fake  # noqa: E731
    monkeypatch.setitem(sys.modules, "tp_fanout", stub)

    recs = hl.harvest_pair("MET", "LUAD")
    snap = tmp_path / "MET__LUAD.json"
    snap.write_text(json.dumps(recs))
    ledger = bdl.build_ledger(tmp_path, calibration_targets={"MET"})
    assert ledger["n_rows"] == 1
    assert ledger["rows"][0]["gap_class"] == bdl.GAP_CALIBRATION


def test_pairs_from_calibration_dict_keyed(tmp_path):
    """(target,indication) pairs come from dict-keyed sections; composites + `multi` skipped."""
    cal = tmp_path / "cal.yaml"
    cal.write_text(
        "reference_profiles:\n  PARP1:\n    indication: OV\n  CDK4_6:\n    indication: BRCA\n"
        "  ADAR1:\n    indication: multi\n"
        "known_gap_watchlist:\n  MET:\n    indication: LUAD\n"
    )
    pairs = hl._pairs_from_calibration(cal)
    assert ("PARP1", "OV") in pairs
    assert ("MET", "LUAD") in pairs
    assert not any(t == "CDK4_6" for t, _ in pairs)  # composite skipped
    assert not any(i == "multi" for _, i in pairs)  # non-specific indication skipped


def test_harvest_pair_threads_skills_subset(monkeypatch):
    """--skills / panel skills must reach _run_sub_skills as the `skills` kwarg (the compute subset)."""
    seen = {}

    def _capture(target, indication, **kw):
        seen["skills"] = kw.get("skills")
        return {}

    stub = types.ModuleType("tp_fanout")
    stub._run_sub_skills = _capture
    monkeypatch.setitem(sys.modules, "tp_fanout", stub)
    hl.harvest_pair("CD274", "COADREAD", skills=["tumor-presence"])
    assert seen["skills"] == ["tumor-presence"]


def test_panels_registry_is_wellformed():
    """Every curated panel binds a non-empty skills list to a list of (target, indication) pairs."""
    assert _known_panels(), "no panels registered"
    for name, p in hl._PANELS.items():
        assert isinstance(p.get("skills"), list) and p["skills"], f"{name}: skills must be a non-empty list"
        assert isinstance(p.get("pairs"), list) and p["pairs"], f"{name}: pairs must be a non-empty list"
        for pair in p["pairs"]:
            assert isinstance(pair, tuple) and len(pair) == 2 and all(pair), f"{name}: bad pair {pair}"


def _known_panels():
    return set(hl._PANELS)


def test_select_active_sub_skills_filters(monkeypatch):
    """_select_active_sub_skills(skills) → only the named sub-skills (dir OR short); None → all
    (byte-stable full fan-out); an unmatched subset raises. Pure over SUB_SKILLS (no live read)."""
    import importlib

    import pytest

    tpf = importlib.import_module("tp_fanout")
    monkeypatch.setattr(
        tpf,
        "SUB_SKILLS",
        [
            ("tumor-presence", "expression"),
            ("functional-requirement", "dependency"),
            ("tumor-selectivity", "selectivity"),
        ],
        raising=True,
    )
    assert tpf._select_active_sub_skills(["tumor-presence"]) == [("tumor-presence", "expression")]  # by dir
    assert {sh for _, sh in tpf._select_active_sub_skills(["dependency", "selectivity"])} == {
        "dependency",
        "selectivity",
    }  # by short
    assert len(tpf._select_active_sub_skills(None)) == 3  # None → full fan-out (byte-stable)
    with pytest.raises(ValueError):
        tpf._select_active_sub_skills(["no-such-skill"])


def test_panel_skills_are_real_sub_skill_dirs():
    """Each panel's skills must be real SUB_SKILLS dir ids (so --panel actually selects a lane)."""
    import importlib

    tpf = importlib.import_module("tp_fanout")
    dirs = {sd for sd, _ in tpf.SUB_SKILLS}
    for name, p in hl._PANELS.items():
        for sk in p["skills"]:
            assert sk in dirs, f"panel {name}: '{sk}' is not a SUB_SKILLS dir id {sorted(dirs)}"


def _crosswalk_indication_codes():
    """Every indication STRING a panel may legitimately pass — canonical_codes plus the aliases lane
    (target-contracts indication_crosswalk.yaml v1.4.0+). None when the sibling repo isn't on disk."""
    import yaml

    # Resolve via the canonical helper (honours TARGET_CONTRACTS_ROOT, then the sibling checkout) rather
    # than counting `parents` off this file: in a /tmp worktree a relative hop lands in /tmp/wt, which
    # holds no sibling repos, so the guard would SKIP exactly where it is being developed.
    sys.path.insert(0, str(_EVAL.parents[1] / "skills"))
    from _skills_common.paths import target_contracts_root

    xw = target_contracts_root() / "vocabularies" / "indication_crosswalk.yaml"
    if not xw.exists():
        return None
    doc = yaml.safe_load(xw.read_text()) or {}
    codes = set()
    for e in doc.get("indications", []):
        if e.get("canonical_code"):
            codes.add(str(e["canonical_code"]))
        codes |= {str(a) for a in (e.get("aliases") or [])}
    return codes or None


def test_panel_indications_resolve_in_the_crosswalk():
    """The MIRROR of test_panel_skills_are_real_sub_skill_dirs, for the other half of a pair.

    A panel indication that is not a crosswalk canonical_code or alias does NOT fail loudly — the skill
    resolves no DepMap lineage and quietly returns a PAN-SCOPE read, so the panel silently stops probing
    the indication it names. That is how ("EPAS1", "RCC") survived here: the codes are KIRC/KIRP/KICH, and
    the skills side was guarded while the indication side was not. Anything genuinely un-curated must be
    added to the crosswalk (or the panel), never left to degrade silently.
    """
    codes = _crosswalk_indication_codes()
    if codes is None:
        import pytest

        pytest.skip("sibling target-contracts crosswalk not readable")
    bad = {
        name: sorted({ind for _t, ind in p["pairs"] if ind not in codes})
        for name, p in hl._PANELS.items()
        if any(ind not in codes for _t, ind in p["pairs"])
    }
    assert not bad, (
        "panel indications that resolve to NO DepMap lineage (each silently degrades that pair to a "
        f"pan-scope read instead of the within-indication probe the panel intends): {bad}"
    )


# ── CASE-034 part B: the harvest record carries the skill_report projection ──────────────────────────
# Before this, the corpus recorded claim_vector + the raw sub-verdict but NOT the spine, so every
# pre-registered prediction about `polarity` / `honest_phrase` / `top_tension` came back NOT MEASURABLE:
# the surface the prediction was about was never written down. The fixture below is built by calling the
# REAL build_skill_report rather than hand-typing a dict, so it cannot drift from the shipped shape.


def _real_skill_report() -> dict:
    """A genuine build_skill_report output (not an invented dict), plus the bulky keys the record drops."""
    _skills = Path(__file__).resolve().parents[2] / "skills"
    if str(_skills) not in sys.path:
        sys.path.insert(0, str(_skills))
    from _skills_common.skill_report import build_skill_report

    sr = build_skill_report(
        role="gating",
        verdict="lineage_selective",
        driving_rule_id="lineage-selective-supportive",
        headline_block={"verdict": {"phrase": "selectively dependent"}, "confidence": "well_supported"},
        claim_vector={"DEP": {"signal": "strong", "corroboration": "high", "informs": "genetic dependency"}},
        question_table=[{"question_id": "q1"}],
        fired_rule_ids=["lineage-selective-supportive"],
        axis_labels={"DEP": "genetic dependency"},
    )
    sr["evidence_graph"] = {"nodes": [1, 2, 3]}  # attached downstream by tp_fanout, and bulky
    return sr


def test_harvest_record_carries_the_skill_report_projection(monkeypatch):
    sr = _real_skill_report()
    fake = {
        "dependency": {
            "skill_dir": "functional-requirement",
            "verdict": ("lineage_selective", "lineage-selective-supportive"),
            "fired": [{"rule_id": "lineage-selective-supportive"}],
            "synthesis_facet": {
                "claim_vector": {"DEP": {"signal": "strong"}},
                "skill_report": sr,
                "literature_synthesis": {"overall_consistency": "concordant", "_prompt_hash": "h1"},
            },
        }
    }
    stub = types.ModuleType("tp_fanout")
    stub._run_sub_skills = lambda *a, **k: fake  # noqa: E731
    monkeypatch.setitem(sys.modules, "tp_fanout", stub)

    r = hl.harvest_pair("KRAS", "COADREAD")[0]
    proj = r["skill_report"]
    assert proj is not None, "the skill_report was dropped from the record again (CASE-034 part B)"
    # the decision-bearing coordinates the panel's predictions were ABOUT
    for k in ("call", "role", "polarity", "honest_phrase", "confidence", "top_tension", "claim_chips"):
        assert k in proj, f"skill_report.{k} missing from the harvest projection"
    assert proj["call"] == "lineage_selective"
    assert proj["honest_phrase"] == "selectively dependent"
    assert proj["provenance"]["driving_rule_id"] == "lineage-selective-supportive"


def test_the_projection_drops_only_the_declared_bulk_keys(monkeypatch):
    """The exclusion set is DECLARED and the drop is RECORDED, so an omission is auditable. An
    include-list would instead silently omit any key added to the spine later."""
    sr = _real_skill_report()
    fake = {
        "dependency": {
            "skill_dir": "functional-requirement",
            "verdict": ("v", "r"),
            "fired": [],
            "synthesis_facet": {"skill_report": sr, "literature_synthesis": {"_prompt_hash": "h"}},
        }
    }
    stub = types.ModuleType("tp_fanout")
    stub._run_sub_skills = lambda *a, **k: fake  # noqa: E731
    monkeypatch.setitem(sys.modules, "tp_fanout", stub)

    r = hl.harvest_pair("KRAS", "COADREAD")[0]
    proj, dropped = r["skill_report"], r["_skill_report_dropped_keys"]
    assert set(sr) - set(proj) == set(dropped), "the record under-reports what it dropped"
    assert set(dropped) <= hl._SKILL_REPORT_BULK_KEYS, f"dropped a non-bulk key: {dropped}"
    assert "evidence_graph" in dropped and "question_table" in dropped
    # ANTI-VACUITY: the exclusion must actually bite on a real spine, or this check proves nothing.
    assert dropped, "no bulk key was present, so the exclusion set was never exercised"
    # and every non-excluded key survives — the projection is a filter, not a whitelist
    assert set(proj) == set(sr) - hl._SKILL_REPORT_BULK_KEYS


def test_a_skill_with_no_skill_report_records_None_not_an_empty_dict(monkeypatch):
    """`gap != absent`: a sub-skill that composes no spine must be distinguishable from one that
    composed an empty one, or the corpus prices a coverage gap as a measured blank."""
    fake = {
        "dependency": {
            "skill_dir": "functional-requirement",
            "verdict": ("v", "r"),
            "fired": [],
            "synthesis_facet": {"claim_vector": {}, "literature_synthesis": {"_prompt_hash": "h"}},
        }
    }
    stub = types.ModuleType("tp_fanout")
    stub._run_sub_skills = lambda *a, **k: fake  # noqa: E731
    monkeypatch.setitem(sys.modules, "tp_fanout", stub)

    r = hl.harvest_pair("KRAS", "COADREAD")[0]
    assert r["skill_report"] is None
    assert r["_skill_report_dropped_keys"] == []
