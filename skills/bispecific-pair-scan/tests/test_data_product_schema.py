"""Emitted data-product contract guard for bispecific-pair-scan (AUX, GATELESS-DESCRIPTIVE ranking scan).

Pins the emitted shape against the SELF-CONTAINED generated schema
`target-contracts/schemas/skills/bispecific-pair-scan.decision.schema.json`. Shared helpers in
`_skills_common.data_product_contract`. Gateless-descriptive (a ranked pair list, NOT a scalar verdict →
`skill_report.call` null, `role=descriptive`, `polarity=not_scored`).

Conformance target = the FRESH emit. bispecific-pair-scan does NOT resolve cards through the live
dispatcher (unlike the fan-out skills) — it drives `methods.pair_selectivity_gate` directly (a ~60-90s/
pair TCGA-vs-GTEx background scan against live S3). So there is no frozen dispatcher summary to replay;
instead this harness runs the REAL run.py end-to-end with the method module replaced by a small in-test
double (no S3, no credentials), exercising the whole emitter — headline → headline_block → skill_report →
provenance → run_health → write_package — exactly as a live run assembles it. The double supplies only
the ranked rows the scan would compute; the ENVELOPE SHAPE under test is the skill's own code (this is a
shape/contract lock, and — being gateless — there is no verdict to guard, so a synthetic ranking is a
sound test input). A second case forces the method unimportable to lock the data_unavailable degrade emit.
CI-liveness: schema unresolvable → SKIP locally, FAIL in CI.
"""

from __future__ import annotations

import json
import os
import runpy
import sys
import tempfile
import types
from pathlib import Path

import pytest

SKILL = "bispecific-pair-scan"
SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"

if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))
from _skills_common.data_product_contract import (  # noqa: E402
    conformance_errors,
    is_full_decision,
    load_schema,
    schema_path,
)


def _schema_or_gate() -> dict:
    schema = load_schema(SKILL)
    if schema is not None:
        return schema
    reason = (
        f"data-product schema not found at {schema_path(SKILL)} — set TARGET_CONTRACTS_ROOT / "
        f"land the contracts schema PR first"
    )
    if os.environ.get("CI"):
        pytest.fail(reason + " [CI: the ratchet must be live, not skipped]")
    pytest.skip(reason)


# ── in-test method double: the ranked rows a live scan would compute (no S3) ──────────────────────
def _scan_partner_set(target, partners, indication, gate):
    """Synthetic ranked pair rows (descending selectivity), one per partner — the shape run.py reads."""
    rows = []
    for i, p in enumerate(partners):
        rows.append(
            {
                "partner": p,
                "selectivity": round(5.0 - i, 1),
                "tumor_fraction": 1.0,
                "essential_normal_fraction": 0.2,
                "call": "tumor_selective",
                "gate": gate,
                "_avidity_caveat": (
                    "bulk co-expression is necessary but NOT sufficient for same-cell "
                    "co-expression; confirm on single-cell / spatial"
                ),
            }
        )
    return rows


def _confirm_pair_samecell(target, partner, indication):
    return {"samecell_avidity_call": "same_cell_supported", "samecell_both_fraction_median": 0.42}


def _install_method_double(mp, scored: bool) -> None:
    """Replace `_skills_common._live_readers._import_method` + only the `methods.pair_selectivity_gate`
    SUBMODULE so the REAL run.py runs credential-less. scored=False forces the method unimportable,
    driving run.py's honest data_unavailable degrade path.

    IMPORTANT: the top-level `methods` package is NOT shadowed — build_subskill_provenance resolves the
    envelope-required `provenance.resolved_releases` via the real `methods.catalog_query` catalog helper
    (same dependency genomic-alteration-profile's data-product test relies on), so the fresh emit's
    resolved-release block is genuinely resolved against the live catalog, exactly as in a real run."""
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    live_readers = types.ModuleType("_skills_common._live_readers")
    if scored:
        # Keep the REAL analysis-methods `methods` package importable (for methods.catalog_query), then
        # override ONLY pair_selectivity_gate with the in-test double.
        from _skills_common.envelope import ANALYSIS_METHODS_ROOT_DEFAULT

        mp.syspath_prepend(os.environ.get("ANALYSIS_METHODS_ROOT", ANALYSIS_METHODS_ROOT_DEFAULT))
        live_readers._import_method = lambda name: None  # no-op: repo "already on path"
        pkg = types.ModuleType("methods.pair_selectivity_gate")
        read_mod = types.ModuleType("methods.pair_selectivity_gate.read")
        samecell_mod = types.ModuleType("methods.pair_selectivity_gate.samecell")
        read_mod.scan_partner_set = _scan_partner_set
        samecell_mod.confirm_pair_samecell = _confirm_pair_samecell
        pkg.read = read_mod
        pkg.samecell = samecell_mod
        for name, mod in (
            ("methods.pair_selectivity_gate", pkg),
            ("methods.pair_selectivity_gate.read", read_mod),
            ("methods.pair_selectivity_gate.samecell", samecell_mod),
        ):
            mp.setitem(sys.modules, name, mod)
    else:

        def _boom(name):
            raise ImportError(f"forced-test-failure: cannot import method {name}")

        live_readers._import_method = _boom
    mp.setitem(sys.modules, "_skills_common._live_readers", live_readers)


def _fresh_emit(*, scored: bool, gate: str = "AND", target: str = "EPCAM", indication: str = "COADREAD") -> dict:
    out_dir = Path(tempfile.mkdtemp(prefix="bps-dp-"))
    mp = pytest.MonkeyPatch()
    _install_method_double(mp, scored=scored)
    argv = [
        "run.py",
        "--target",
        target,
        "--indication",
        indication,
        "--gate",
        gate,
        "--partners",
        "CEACAM5,ERBB2",
        "--out",
        str(out_dir),
    ]
    mp.setattr(sys, "argv", argv)
    try:
        runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit as e:
        assert e.code in (0, None), f"run.py exited non-zero ({e.code})"
    finally:
        mp.undo()
    decision_path = out_dir / "decision.json"
    assert decision_path.exists(), "run.py wrote no decision.json"
    return json.loads(decision_path.read_text())


def _assert_gateless_descriptive(decision: dict) -> None:
    assert is_full_decision(decision), (
        "emit is not a full decision (missing envelope provenance/run_health/generated_at or "
        "headline.skill_report) — the emitter regressed"
    )
    sr = decision["headline"]["skill_report"]
    assert sr["call"] is None, f"gateless ranking must have null call, got {sr['call']!r}"
    assert sr["role"] == "descriptive" and sr["polarity"] == "not_scored", (
        f"expected descriptive/not_scored spine, got role={sr['role']!r} polarity={sr['polarity']!r}"
    )
    assert isinstance(sr["honest_phrase"], str) and sr["honest_phrase"], "honest_phrase must be non-empty"
    assert (sr.get("confidence") or {}).get("level"), "confidence.level must be present"


def test_schema_is_wellformed():
    jsonschema = pytest.importorskip("jsonschema")
    schema = _schema_or_gate()
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema.get("version"), "data-product schema must carry a contract `version`"


def test_fresh_emit_conforms():
    """The primary conformance target: a fresh, non-vacuous scored emit validates against the schema and
    carries the gateless-descriptive spine (null call, descriptive, not_scored)."""
    pytest.importorskip("jsonschema")
    schema = _schema_or_gate()
    decision = _fresh_emit(scored=True)
    _assert_gateless_descriptive(decision)
    # non-vacuous: a top-ranked pair was actually scored + surfaced on the headline
    top = (decision["headline"] or {}).get("top_pair")
    assert top and top.get("partner"), "scored emit must surface a ranked top_pair"
    assert decision["run_health"]["status"] == "ok"
    errors = conformance_errors(schema, decision)
    assert not errors, "fresh emit violates the data-product schema:\n  " + "\n  ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:15]
    )


def test_data_unavailable_emit_conforms():
    """The honest degrade path (method unimportable → no pair scored) is still a full, conforming
    envelope — the gateless spine and provenance/run_health hold with zero scored pairs."""
    pytest.importorskip("jsonschema")
    schema = _schema_or_gate()
    decision = _fresh_emit(scored=False)
    _assert_gateless_descriptive(decision)
    assert decision["run_health"]["status"] == "degraded"
    assert (decision["headline"] or {}).get("top_pair") is None, "no pair should be scored on degrade"
    errors = conformance_errors(schema, decision)
    assert not errors, "data_unavailable emit violates the data-product schema:\n  " + "\n  ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:15]
    )
