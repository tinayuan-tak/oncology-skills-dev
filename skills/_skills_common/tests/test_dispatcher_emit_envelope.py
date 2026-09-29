"""D1b: run_wired_skill(--emit-envelope) emits a governance-grade evidence_package.json
around a focused subskill's OWN resolver verdict — opt-in, purely additive.

Pins:
  1. WITH --emit-envelope: a sibling evidence_package.json is written, VALIDATES against
     target-contracts/schemas/evidence_package.schema.json, and its synthesis.headline
     (+ the structured verdict/driving_rule_id extras) carry the resolver verdict.
  2. WITHOUT --emit-envelope (default): NO evidence_package.json is written — the flag is a
     complete no-op, so every existing invocation is byte-for-byte unchanged.

Live S3 is avoided the same way the other dispatcher tests do it: monkeypatch resolve_cards /
fired_rules / write_package so the run exercises the REAL run_wired_skill code path offline.
The stubbed target-identity read returns a realistic resolved identity (as a live read would),
so context.target.hgnc_id is a real integer >= 1 and the package validates.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import _skills_common.dispatcher as D  # noqa: E402
from _skills_common.paths import TARGET_CONTRACTS_ROOT_DEFAULT

CONTRACTS = Path(os.environ.get("TARGET_CONTRACTS_ROOT", TARGET_CONTRACTS_ROOT_DEFAULT))
PKG_SCHEMA = json.loads((CONTRACTS / "schemas" / "evidence_package.schema.json").read_text())


def _patch_common(monkeypatch):
    """Stub the three live-touching seams; run_wired_skill's own logic runs for real."""

    def fake_resolve(card_ids, target, indication, **k):
        # The envelope path issues a SECOND resolve for the foundational identity card.
        if list(card_ids) == ["target-identity-summary"]:
            return [
                {
                    "card_id": "target-identity-summary",
                    "summary": {
                        "resolved_hgnc_symbol": "KRAS",
                        "resolved_hgnc_id": 6407,
                        "resolved_ensembl_id": "ENSG00000133703",
                        "resolution_status": "resolved",
                    },
                    "interpretation_call": None,
                }
            ]
        return [
            {
                "card_id": "crispr-dependency-distribution",
                "summary": {"dependency_class": "strong_dependency"},
                "interpretation_call": "strong_dependency",
            }
        ]

    monkeypatch.setattr(D, "resolve_cards", fake_resolve)
    monkeypatch.setattr(
        D,
        "fired_rules",
        lambda card_outputs, axis, card_id_filter=None: [
            {
                "rule_id": "crispr-strong-dependency",
                "card_id": "crispr-dependency-distribution",
                "field": "dependency_class",
                "value": "strong_dependency",
                "dominant": True,
                "rationale": "strong Chronos dependency across the lineage",
            },
        ],
    )
    monkeypatch.setattr(D, "write_package", lambda **kw: {"tables": [], "figures": []})


def _run(monkeypatch, out_dir: Path, emit: bool):
    _patch_common(monkeypatch)
    argv = ["--target", "KRAS", "--indication", "COADREAD", "--out", str(out_dir)]
    if emit:
        argv.append("--emit-envelope")
    rc = D.run_wired_skill(
        skill_name="functional-requirement",
        skill_version="9.9.9",
        cards=["crispr-dependency-distribution"],
        axis="intracellular_intrinsic",
        question="Is {target} required in {indication}?",
        verdict_fn=lambda fired: ("strong_dependency", "crispr-strong-dependency"),
        headline_fn=lambda cards, fired, vp: {"verdict": vp[0], "driving_rule_id": vp[1]},
        argv=argv,
    )
    return rc


def test_emit_envelope_writes_valid_package_carrying_the_verdict(monkeypatch, tmp_path):
    out_dir = tmp_path / "fr"
    rc = _run(monkeypatch, out_dir, emit=True)
    assert rc == 0

    ep_path = out_dir / "evidence_package.json"
    assert ep_path.exists(), "--emit-envelope must write a sibling evidence_package.json"
    ep = json.loads(ep_path.read_text())

    # (1) VALIDATES against the canonical schema.
    errors = sorted(e.message for e in Draft202012Validator(PKG_SCHEMA).iter_errors(ep))
    assert errors == [], f"evidence_package failed schema validation: {errors}"

    # (2) synthesis.headline carries the resolver verdict + driving rule; structured extras too.
    syn = ep["synthesis"]
    assert syn["headline"] == "functional-requirement: strong_dependency (crispr-strong-dependency)"
    assert syn["verdict"] == "strong_dependency"
    assert syn["driving_rule_id"] == "crispr-strong-dependency"
    assert syn["gate"] == "functional-requirement"
    assert "crispr-strong-dependency" in syn["fired_rule_ids"]

    # (3) envelope identity + provenance are subskill-shaped.
    assert ep["dashboard_spec_ref"] == "skill:functional-requirement"
    assert ep["context"]["target"]["hgnc_id"] == 6407
    assert ep["generated_by"].startswith("skills/functional-requirement@")
    # data_mode default "live" is carried into governance mapped to the schema enum.
    assert ep["governance"]["data_mode"] == "exploratory"


def test_default_writes_no_envelope(monkeypatch, tmp_path):
    out_dir = tmp_path / "fr_default"
    rc = _run(monkeypatch, out_dir, emit=False)
    assert rc == 0
    assert not (out_dir / "evidence_package.json").exists(), (
        "without --emit-envelope the dispatcher must be a complete no-op — no envelope written"
    )


def test_data_mode_and_release_pin_carry_into_governance(monkeypatch, tmp_path):
    """--data-mode/--release-pin are carried into governance ONLY (no manifest pinning)."""
    _patch_common(monkeypatch)
    out_dir = tmp_path / "fr_pinned"
    rc = D.run_wired_skill(
        skill_name="functional-requirement",
        skill_version="9.9.9",
        cards=["crispr-dependency-distribution"],
        axis="intracellular_intrinsic",
        question="Is {target} required in {indication}?",
        verdict_fn=lambda fired: ("strong_dependency", "crispr-strong-dependency"),
        headline_fn=lambda cards, fired, vp: {"verdict": vp[0], "driving_rule_id": vp[1]},
        argv=[
            "--target",
            "KRAS",
            "--indication",
            "COADREAD",
            "--out",
            str(out_dir),
            "--emit-envelope",
            "--data-mode",
            "pinned",
            "--release-pin",
            "2026-Q2",
        ],
    )
    assert rc == 0
    ep = json.loads((out_dir / "evidence_package.json").read_text())
    assert ep["governance"]["data_mode"] == "pinned"
    assert ep["governance"]["release_pin"] == "2026-Q2"
    # validates too
    errors = sorted(e.message for e in Draft202012Validator(PKG_SCHEMA).iter_errors(ep))
    assert errors == [], f"pinned-mode envelope failed schema validation: {errors}"
