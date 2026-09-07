"""placeholder — helper for skills that declare a phase but are not yet wired.

emit_placeholder is the sanctioned structured response for a skill that declares a
phase in the target-evaluation taxonomy but has NO wired dispatcher yet. Rather than
hide the gap by omitting the skill from the catalog, we ship a lightweight placeholder
that:

  1. Declares its intended composition (cards it would consume once wired)
     in SKILL.md front-matter with `status: not_wired`.
  2. Emits a structured error artefact at `<out>/decision.json` naming
     the specific data-gaps blocking implementation + pointers to the
     framework's gaps-and-backlog table.

This keeps the framework's coverage transparent to users — they see the
skill in the catalog, invoke it, and get a defensible "not yet wired
because X, Y, Z" instead of silence or a mysterious card-missing error.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml


def emit_placeholder(
    out_dir: Path,
    skill_name: str,
    skill_version: str,
    target: str,
    indication: str,
    phase: str,
    question: str,
    required_cards: list[str],
    unwired_cards: list[str],
    data_gaps: list[str],
    backlog_reference: Optional[str] = None,
) -> Path:
    """Write a structured placeholder response artefact.

    Args:
        out_dir: destination directory (created if missing)
        skill_name, skill_version: skill identity
        target, indication: original query
        phase: which phase-taxonomy letter this skill claims (A-K)
        question: the phase-question this skill would answer if wired
        required_cards: list of card_ids the skill would consume
        unwired_cards: subset of required_cards whose dispatchers aren't wired
        data_gaps: list of human-readable gap descriptions (e.g. "gnomAD
            constraint table needs a card wired")
        backlog_reference: optional link to the framework's gaps-backlog doc

    Returns:
        Path to written decision.json
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "skill": skill_name,
        "skill_version": skill_version,
        "target": target,
        "indication": indication,
        "phase": phase,
        "question": question,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "not_wired",
        "verdict": "phase_not_yet_wired",
        "explanation": (
            f"This skill answers a Phase-{phase} question in the target-"
            f"evaluation framework, but the underlying evidence cards are "
            f"not yet wired in the shared _skills_common dispatcher registry."
        ),
        "required_cards": required_cards,
        "unwired_cards": unwired_cards,
        "data_gaps": data_gaps,
        "backlog_reference": (backlog_reference or "See ~/.claude/plans/deep-foraging-thompson.md §'Gaps + backlog'."),
    }

    decision_path = out_dir / "decision.json"
    decision_path.write_text(json.dumps(payload, indent=2))

    # Also emit a provenance.yaml so the placeholder tree conforms to the
    # data-package layout convention (even though there's no real data).
    provenance = {
        "skill": skill_name,
        "skill_version": skill_version,
        "target": target,
        "indication": indication,
        "generated_at": payload["generated_at"],
        "status": "not_wired",
        "invoked_lenses": {},
        "cards_resolved": [],
        "cards_missing": unwired_cards,
        "phase_wired": False,
        "data_gaps": data_gaps,
    }
    (out_dir / "provenance.yaml").write_text(yaml.safe_dump(provenance, sort_keys=False))
    return decision_path
