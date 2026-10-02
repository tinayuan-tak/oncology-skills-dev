"""Scorecard shard guard (#1989) — the COMMITTED tumor-selectivity shard stays honest. Copies the
tumor-presence exemplar's shape (#1988, `skills/tumor-presence/tests/test_scorecard_shard.py`).

The shard (`scorecard/tumor-selectivity.json`) is a committed artifact built by
`scripts/scorecard_adapter.py`; A0a's drift guard checks schema + render staleness but deliberately
never interprets adapter-owned evidence. This module supplies the adapter-side guards the exemplar
promises siblings:

  1. every criterion the shard marks GREEN cites at least one test file that EXISTS in the tree —
     evidence naming a phantom test is a fabricated measurement;
  2. the L1 panel_consistency evidence carries the FULL 5-pair roster with computed checks, no
     placeholder residue — a partial or hand-typed panel cannot ship as GREEN;
  3. the panel checks have TEETH: fed a doctored panel (every target emitting one constant class),
     `collect_panel_rows` reds its own checks — the pass is a live function of the package bytes.
  4. L2a/L2b are BUILT-but-UNMEASURED (PR-1d, #2213 exported the source_properties/
     selectivity_concordance sections); L3/L4 stay NOT_BUILT (no l3d story / synthesis layer exists).
  5. (#2070) the `dominant_direction`/`selectivity_class` token-space fix has its own mutation teeth:
     a synthetic degraded HTR1D row (degraded `selectivity_class`, ordinary `dominant_direction`)
     proves `thin_coverage_control_degrades` reads the FIXED field — RED-failing if the dead
     comparison is reintroduced — and `htr1d_matches_expected_archetype` (the applicable clause for
     this skill's DGE vertical) is exercised on a realistic-shaped panel.
  6. panel_consistency can never render GREEN while power/coverage grading is blocked on #1663 —
     it is either RED (an applicable conjunct fails) or NULL/#1663 (all applicable conjuncts pass).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
REPO_ROOT = SKILLS_ROOT.parent

from _skills_common import component_scorecard as cs  # noqa: E402

SHARD_PATH = REPO_ROOT / cs.SCORECARD_DIRNAME / "tumor-selectivity.json"


def _load_adapter():
    spec = importlib.util.spec_from_file_location(
        "t1989_scorecard_adapter_under_test", SKILL_DIR / "scripts" / "scorecard_adapter.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _shard_dict() -> dict:
    return json.loads(SHARD_PATH.read_text())


def test_shard_validates_and_upper_layers_are_not_built():
    shard = cs.shard_from_dict(_shard_dict(), expected_skill="tumor-selectivity")
    for layer in ("L3", "L4"):
        assert cs.cell_rollup(shard.cells[layer]) == cs.NOT_BUILT
    # L1: utilization/fail_open are always measured (never NULL); accuracy is deliberately NULL
    # (re-derivation is separate issue #2001, per this issue's directive). panel_consistency is
    # measured (GREEN/RED) once the whole roster is emitted, else an honest NULL with a disposition.
    l1 = shard.cells["L1"]
    assert l1.built is True
    assert l1.criteria["accuracy"].status == cs.NULL
    assert (l1.criteria["accuracy"].evidence or {}).get("reason")
    for c in ("utilization", "fail_open"):
        assert l1.criteria[c].status != cs.NULL, f"L1/{c} must be measured, not NULL"
    pc = l1.criteria["panel_consistency"]
    if pc.status == cs.NULL:
        assert (pc.evidence or {}).get("null_reason"), "a NULL panel criterion must carry a disposition note"
    evidence = pc.evidence or {}
    checks = evidence.get("checks") or {}
    # If the full roster resolved AND its verdict-bearing cards were reachable, we reached the
    # power-grading-blocked branch (issue #2070 pt.3) regardless of whether the applicable conjuncts
    # passed (-> NULL/#1663) or failed (-> RED) — the blocker must be named either way.
    if checks and not checks.get("all_card_data_unavailable") and checks.get("all_roster_rows_present"):
        assert evidence.get("blocked_on") == "#1663", "power-grading blocker must be named #1663"


def test_committed_shard_equals_the_adapter_output():
    """ROUND-TRIP TEETH: the committed file IS what build_shard() produces. Reds on any drift between
    the adapter and the committed artifact (in either direction), so neither can silently diverge."""
    ad = _load_adapter()
    assert _shard_dict() == ad.build_shard().to_dict(), (
        "scorecard/tumor-selectivity.json has drifted from scorecard_adapter.build_shard() — re-run "
        "`python skills/tumor-selectivity/scripts/scorecard_adapter.py` and re-render."
    )


def test_build_shard_is_deterministic():
    """TEETH against a volatile field re-entering the EQUALITY-CHECKED shard. `status_as_of` was stamped
    with time.gmtime() (#2385), so build_shard() drifted every day and red-failed the merge queue for the
    whole shard; it is now a pinned literal. Two builds in the same process MUST be byte-identical — this
    reds if any run-time/non-deterministic value (date, uuid, …) is reintroduced into the shard."""
    ad = _load_adapter()
    assert ad.build_shard().to_dict() == ad.build_shard().to_dict()


def test_l2_layers_are_built_but_unmeasured():
    """PR-1d (#2213) BUILT L2a/L2b, so NOT_BUILT (built=False) would understate the artifact — but
    building a layer is not measuring it, so every criterion stays NULL with a reason and the cell rolls
    up NULL, never GREEN. The rollup (any NULL blocks GREEN) is what enforces that; this pins the inputs
    to it."""
    shard = cs.shard_from_dict(_shard_dict(), expected_skill="tumor-selectivity")
    for layer in ("L2a", "L2b"):
        cell = shard.cells[layer]
        assert cell.built is True, f"{layer} is exported by run.py::_evidence_sections — built must be True"
        assert cs.cell_rollup(cell) == cs.NULL, f"{layer} rolled up {cs.cell_rollup(cell)}, expected NULL (unmeasured)"
        for name in cs.CRITERIA:
            crit = cell.criteria[name]
            assert crit.status == cs.NULL, f"{layer}/{name} claims {crit.status} with no measurement built"
            assert (crit.evidence or {}).get("null_reason"), f"{layer}/{name} is NULL with no reason recorded"
            assert (crit.evidence or {}).get("structural_pins"), f"{layer}/{name} names no structural pin"


def test_every_l2_structural_pin_cites_an_existing_file():
    """A structural pin naming a file that does not exist is a fabricated guard reference."""
    data = _shard_dict()
    checked = 0
    for layer in ("L2a", "L2b"):
        for name, crit in data["cells"][layer]["criteria"].items():
            for entry in (crit["evidence"] or {}).get("structural_pins", []):
                rel = entry.split(" ")[0]
                assert (REPO_ROOT / rel).exists(), f"{layer}/{name} structural pin cites missing file {rel}"
                checked += 1
    assert checked >= 8, f"suspiciously few structural pins checked ({checked}) — did the evidence shrink?"


def test_every_green_criterion_cites_an_existing_test_file():
    """Evidence naming a phantom test is a fabricated measurement — resolve every cited path."""
    data = _shard_dict()
    checked = 0
    for layer, cell in data["cells"].items():
        for name, crit in cell["criteria"].items():
            if crit["status"] != cs.GREEN:
                continue
            ev = crit["evidence"] or {}
            cited = [ev["test"]] if "test" in ev else list(ev.get("tests", []))
            if name == "panel_consistency":
                continue  # panel evidence is package rows + computed checks, not test citations
            assert cited, f"GREEN {layer}/{name} cites no test at all"
            for entry in cited:
                rel = entry.split("::")[0].split(" ")[0]
                assert (REPO_ROOT / rel).exists(), f"GREEN {layer}/{name} cites missing file {rel}"
                checked += 1
    assert checked >= 4, f"suspiciously few citations checked ({checked}) — did the evidence shrink?"


def test_panel_evidence_is_complete_computed_and_placeholder_free():
    crit = _shard_dict()["cells"]["L1"]["criteria"]["panel_consistency"]
    ev = crit["evidence"]
    status = crit["status"]
    rows = ev["rows"]
    # The evidence ALWAYS carries the full 5-pair roster — a pair whose package is not yet emitted is
    # present as a PACKAGE_MISSING row, never omitted (absence is said, not hidden).
    assert isinstance(rows, list) and len(rows) == 5, "panel evidence must carry the full 5-pair roster"
    assert {(r["target"], r["indication"]) for r in rows} == {
        ("EPCAM", "COADREAD"),
        ("KRAS", "COADREAD"),
        ("ERBB2", "BRCA"),
        ("PLK1", "COADREAD"),
        ("HTR1D", "COADREAD"),
    }
    assert "PLACEHOLDER" not in json.dumps(ev)
    checks = ev["checks"]
    ok_rows = [r for r in rows if r["status"] == "OK"]
    if len(ok_rows) == 5 and checks.get("all_card_data_unavailable"):
        # Full roster emitted, but every row's verdict-bearing cards report a live-read error in
        # this environment (ACCESS_DENIED on the underlying derived product) — honest NULL with a
        # disposition naming the environment cause, never a fabricated pass/fail on unreachable data.
        assert status == cs.NULL
        assert ev.get("null_reason") and ev.get("card_data_unavailable_by_target")
    elif len(ok_rows) == 5:
        # Full roster emitted with reachable card data: every OK row cites its package source. The
        # power/coverage grading dimension is structurally blocked on #1663 (n_tumor stranded
        # panel-wide), so the criterion can never render GREEN here — it reads RED if an applicable
        # conjunct fails, else the honest NULL/#1663 (issue #2070 decision pt.3), never a fabricated
        # GREEN.
        assert all(r["source"] for r in ok_rows)
        assert status in (cs.NULL, cs.RED)
        assert status != cs.GREEN, "panel_consistency must never render GREEN while #1663 blocks power grading"
        if checks["all_pass"]:
            assert status == cs.NULL and ev.get("blocked_on") == "#1663"
        else:
            assert status == cs.RED
    else:
        # Partial roster: honest NULL with a disposition, and the checks cannot claim a pass.
        assert status == cs.NULL, "a partial panel must not carry a measured status"
        assert ev.get("null_reason") and ev.get("packages_missing")
        assert checks["all_pass"] is False


def test_teeth_a_constant_class_panel_reds_the_checks(monkeypatch):
    """Seed the failure the checks exist to catch: every roster target emitting ONE constant class
    (the single-flagship-overfit shape). `collect_panel_rows` must red its own checks — proving the
    committed GREEN is a live function of the package bytes, not a hand-typed verdict."""
    ad = _load_adapter()
    constant_pkg = {
        "cards": [
            {"card_id": "tumor-vs-normal-selectivity", "summary": {"dominant_direction": "tumor_up"}},
            {
                "card_id": "modality-therapeutic-window",
                "summary": {"therapeutic_window_class": "clean_window"},
            },
        ]
    }
    monkeypatch.setattr(ad, "_load_package", lambda t, i: (constant_pkg, "doctored://constant"))
    rows, checks = ad.collect_panel_rows()
    assert len(rows) == 5 and all(r["status"] == "OK" for r in rows)
    assert checks["direction_class_not_constant"] is False
    assert checks["window_class_not_constant"] is False
    assert checks["htr1d_matches_expected_archetype"] is False
    assert checks["thin_coverage_control_degrades"] is False
    assert checks["all_pass"] is False


def test_teeth_a_partial_panel_cannot_pass(monkeypatch):
    ad = _load_adapter()
    monkeypatch.setattr(ad, "_load_package", lambda t, i: (None, None))
    rows, checks = ad.collect_panel_rows()
    assert all(r["status"] == "PACKAGE_MISSING" for r in rows)
    assert checks["all_roster_rows_present"] is False and checks["all_pass"] is False


def test_teeth_htr1d_matches_expected_archetype_on_a_real_shaped_panel(monkeypatch):
    """The #2070 applicable clause: when HTR1D reads its tumor-selectivity-specific expectation
    (measured strong_tumor_selective, concordant comparators) and the rest of the roster varies,
    `htr1d_matches_expected_archetype` fires True and the checks pass (modulo the #1663 power-grading
    blocker, asserted separately at the Criterion level)."""
    ad = _load_adapter()

    def _pkg_for(direction: str, selectivity_class: str, concordance: str, window: str) -> dict:
        return {
            "cards": [
                {
                    "card_id": "tumor-vs-normal-selectivity",
                    "summary": {
                        "dominant_direction": direction,
                        "selectivity_class": selectivity_class,
                        "comparator_concordance": concordance,
                    },
                },
                {"card_id": "modality-therapeutic-window", "summary": {"therapeutic_window_class": window}},
            ]
        }

    shaped = {
        ("EPCAM", "COADREAD"): _pkg_for("up", "field_effect_tumor_selective", "discordant", "narrow_window"),
        ("KRAS", "COADREAD"): _pkg_for("down", "discordant_across_comparators", "discordant", "no_therapeutic_window"),
        ("ERBB2", "BRCA"): _pkg_for("up", "strong_tumor_selective", "concordant", "narrow_window"),
        ("PLK1", "COADREAD"): _pkg_for("up", "strong_tumor_selective", "concordant", "no_therapeutic_window"),
        ("HTR1D", "COADREAD"): _pkg_for("up", "strong_tumor_selective", "concordant", "narrow_window"),
    }
    monkeypatch.setattr(ad, "_load_package", lambda t, i: (shaped[(t, i)], f"doctored://{t.lower()}"))
    rows, checks = ad.collect_panel_rows()
    assert len(rows) == 5 and all(r["status"] == "OK" for r in rows)
    assert checks["htr1d_matches_expected_archetype"] is True
    assert checks["direction_class_not_constant"] is True
    assert checks["window_class_not_constant"] is True
    assert checks["all_pass"] is True
    # thin_coverage_control_degrades correctly reads False: HTR1D genuinely does NOT degrade here.
    assert checks["thin_coverage_control_degrades"] is False


def test_teeth_the_degradation_clause_fires_on_a_synthetic_degraded_row_field_mismatch_guard(monkeypatch):
    """Mutation teeth for the #2070 fix: `thin_coverage_control_degrades` (built on
    `_is_degraded_selectivity_class`) must CAN fire True on a synthetic HTR1D row whose
    `selectivity_class` is degraded while `dominant_direction` is an ordinary up/down token (the
    dead-comparison shape the original bug had: dominant_direction never held a degraded-class
    token, so a check keyed on it could never fire). If the field-mismatch bug is reintroduced (the
    check reads `dominant_direction` instead of `selectivity_class`), this row's
    `dominant_direction="up"` — a NON-degraded token — makes the check read False, and this
    assertion goes RED."""
    ad = _load_adapter()

    def _pkg_for(direction: str, selectivity_class: str, concordance: str) -> dict:
        return {
            "cards": [
                {
                    "card_id": "tumor-vs-normal-selectivity",
                    "summary": {
                        "dominant_direction": direction,
                        "selectivity_class": selectivity_class,
                        "comparator_concordance": concordance,
                    },
                },
                {"card_id": "modality-therapeutic-window", "summary": {"therapeutic_window_class": "narrow_window"}},
            ]
        }

    shaped = {
        ("EPCAM", "COADREAD"): _pkg_for("up", "strong_tumor_selective", "concordant"),
        ("KRAS", "COADREAD"): _pkg_for("down", "strong_tumor_selective", "concordant"),
        ("ERBB2", "BRCA"): _pkg_for("up", "strong_tumor_selective", "concordant"),
        ("PLK1", "COADREAD"): _pkg_for("up", "strong_tumor_selective", "concordant"),
        # HTR1D: selectivity_class IS degraded, but dominant_direction is an ordinary "up" —
        # the exact shape that defeats a check mistakenly keyed on dominant_direction.
        ("HTR1D", "COADREAD"): _pkg_for("up", "discordant_across_comparators", "discordant"),
    }
    monkeypatch.setattr(ad, "_load_package", lambda t, i: (shaped[(t, i)], f"doctored://{t.lower()}"))
    rows, checks = ad.collect_panel_rows()
    assert len(rows) == 5 and all(r["status"] == "OK" for r in rows)
    # Direct token-space unit check: fires on the correct field even when dominant_direction alone
    # would never carry the degraded token.
    assert ad._is_degraded_selectivity_class("discordant_across_comparators") is True
    assert ad._is_degraded_selectivity_class("up") is False
    assert checks["thin_coverage_control_degrades"] is True
    # HTR1D reads degraded here, so it does NOT match its tumor-selectivity expectation.
    assert checks["htr1d_matches_expected_archetype"] is False
