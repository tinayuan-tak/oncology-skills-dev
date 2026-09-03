#!/usr/bin/env python3
"""risk_rollup — PROJECTION [3A]: the 6-dim risk roll-up (grounded-substrate two-projection design).

A sibling projection to the cross-evidence hypothesis. Each risk dimension =
  bin:      DETERMINISTIC, a pure function of the evidence-package sub_verdicts — a modality-CONDITIONED
            worst-case CONJUNCTION over the relevant axes. Reproducible + cross-target comparable; the
            LLM/literature NEVER sets the bin. (Safety is on-target-safety ∧ surface-normal-antigen ∧
            tumor-selectivity-normal-breadth — validated to catch the FOLR1 ADC safety false-LOW that a
            1:1 on-target-only mapping misses.)
  findings: GROUNDED escalate-only findings from ground_axis substrate blocks (PMID-traceable). Findings
            can only RAISE a flag; they NEVER change the deterministic bin (escalate-only).
  discordance: per-dim engine↔literature flag (from the grounded block's contradicts_deterministic).
  blind_spots: what the engine bin does not cover (→ the grounded findings / Tier-2 fill these).

RE-HOME (2026-09-03): the PURE deterministic core (deterministic_bins + AXIS_TO_DIM + _mod + the package
accessors + RANK/INV/SURFACE) MOVED to `_skills_common/risk_projection.py` so target-profile computes
`target_report.risk_6dim` directly from in-memory sub_results (no disk round-trip / no network). This
module RE-EXPORTS them (so this file's CLI, tests, and the gold harness are unchanged) and keeps the
LITERATURE-GROUNDING overlay (`project()` + the escalate-only findings + the engine-blind pseudo-card
literature bin), which needs ground_axis.SEVERITY_HIGH. The standalone CLI below is kept as a lit-only
ad-hoc query path.

THRESHOLDS ARE ILLUSTRATIVE (v0). The CONTRACT is the contribution: modality-conditioned conjunction +
escalate-only fusion + declared blind-spots + reproducible bin. Thresholds are to be calibrated; the
tests pin the STRUCTURE (conjunction, escalate-only, discordance), not the exact thresholds.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Path setup: the module's own scripts dir (for `ground_axis`) AND skills/ (so `_skills_common` — the
# home of the re-homed deterministic core — resolves when this file is loaded by path in a test/CLI).
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
_SKILLS = _SCRIPTS.parents[1]        # .../skills
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))

# The deterministic core, re-homed to the shared layer (single source of truth). Re-exported here so
# `import risk_rollup as rr; rr.deterministic_bins` (validate_gold + tests) and the CLI keep working.
from _skills_common.risk_projection import (  # noqa: E402,F401
    RANK, INV, SURFACE, AXIS_TO_DIM, _mod, _sv, _calls, _card, _q, deterministic_bins,
)

# Single source of truth for pseudo-card escalation lives with the PRODUCER (ground_axis owns the
# grounded-finding contract). Guarded, cheap import — ground_axis has no heavy/network deps at module
# load (its Bedrock/PubMed imports are lazy). Consumer-depends-on-producer, so the severity vocabulary
# can never drift out of sync with the schema the model is actually asked to fill.
from ground_axis import SEVERITY_HIGH  # noqa: E402


def _findings_of(block: dict) -> list:
    g = block.get("grounded", block) or {}
    return g.get("findings") or g.get("liability_findings") or []   # tolerant of both field names


def _pseudo_literature_bin(findings: list) -> str:
    """Coarse literature-only bin for engine-blind pseudo-card dims (decision 2): a finding the model
    graded severity=='high' → HIGH; any finding → MED; none → LOW. Uncalibrated (literature-only).
    Keys on the controlled `severity` enum (exact membership) — NOT a substring-grep of free-text
    `kind`, which mis-binned prose that didn't happen to contain an escalator token."""
    if not findings:
        return "LOW"
    if any(str(f.get("severity", "")).lower() == SEVERITY_HIGH for f in findings):
        return "HIGH"
    return "MED"


def project(pkg: dict, modality: str, substrate: dict | None = None) -> dict:
    """Fuse deterministic bins with grounded escalate-only findings + discordance. For ENGINE-anchored
    dims, findings NEVER change the deterministic bin (escalate-only). For engine-BLIND pseudo-card dims
    (clinical/commercial), a COARSE literature-only bin is derived from the findings (tagged uncalibrated)."""
    dims = deterministic_bins(pkg, _mod(modality))
    for axis, block in (substrate or {}).items():
        dim = AXIS_TO_DIM.get(axis)
        if not dim or dim not in dims:
            continue
        dims[dim].setdefault("grounded_findings", [])
        dims[dim]["grounded_findings"] += _findings_of(block)
        g = block.get("grounded", block) or {}
        if g.get("contradicts_deterministic"):
            dims[dim]["engine_literature_discordance"] = True
        # engine-blind pseudo-card dim → derive the coarse literature bin (never for engine dims)
        if dims[dim].get("bin") == "ENGINE-BLIND":
            dims[dim]["bin"] = _pseudo_literature_bin(dims[dim]["grounded_findings"])
            dims[dim]["bin_basis"] = "literature-only (uncalibrated)"
    return dims


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-package", required=True)
    ap.add_argument("--modality", required=True)
    ap.add_argument("--substrate", nargs="*", default=[], help="axis=path grounded substrate blocks")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    sub = {}
    for spec in a.substrate:
        ax, p = spec.split("=", 1); sub[ax] = json.loads(Path(p).read_text())
    dims = project(json.loads(Path(a.evidence_package).read_text()), a.modality, sub)
    if a.out: Path(a.out).write_text(json.dumps(dims, indent=2))
    print(json.dumps(dims, indent=2))
