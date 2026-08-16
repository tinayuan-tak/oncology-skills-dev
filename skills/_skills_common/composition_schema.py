"""composition_schema — validator for the `composition:` block in SKILL.md
front-matter.

Every compositional skill declares its shape in structured front-matter so
the framework can enforce consistency, audit coverage, and populate
navigation surfaces. This module defines the allowed enum values and
validates a parsed `composition` block. Skills missing required fields or
using invalid enum values raise CompositionError at load-time.

The allowed enum values and required fields defined in this module are the
canonical field reference for the `composition` block.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# --- Enum values ------------------------------------------------------------

DATA_MODES = {"live_read", "derived_read", "batch_compute", "catalog_read"}

PHASES = {"A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K"}

SYNTHESIS_KINDS = {"none", "rule_engine", "structured_llm"}

OUTPUT_SHAPES = {"data_package", "target_profile", "evidence_package", "text_report"}

STEPS = {1, 2, 3, 4, 5, 6}

OPTIONAL_LENSES = {"modality", "therapeutic_hypothesis", "subgroup"}

STATUSES = {"wired", "not_wired", "partial"}

# Behavior a composed skill takes when a dependency card is `status: partial`
# (i.e., graduated from placeholder but not yet fully wired). Reviewer-driven
# arch upgrade A4 (2026-07-08) — makes the placeholder → partial → wired
# migration path safe for composed skills like target-profile that fan out
# across many cards. Values:
#   skip_section      — omit the section that consumes this dep; log a note
#   fail              — refuse to run; surface the partial dep as an error
#   emit_with_caveat  — run + include the section + auto-emit a caveat naming
#                       the partial dep so downstream readers know the epistemic
#                       ceiling
DEPENDENCY_STATUS_BEHAVIORS = {"skip_section", "fail", "emit_with_caveat"}


class CompositionError(ValueError):
    """Raised when a SKILL.md's composition block is invalid."""


@dataclass
class Composition:
    """Structured composition declaration for a skill.

    Instantiated by `validate()` from a parsed YAML dict. Every field has
    a validation rule; failures raise CompositionError with a message that
    names the offending field.
    """
    data_mode: str
    phase: list[str]
    cards_used: list[str]
    rules_scope: list[str]
    synthesis: list[str]
    output_shape: list[str]
    steps_covered: list[int]
    optional_lenses: list[str] = field(default_factory=list)
    status: str = "wired"
    # Composed skills only: per-dependency behavior when a card is `partial`.
    # Map card_id -> one of DEPENDENCY_STATUS_BEHAVIORS. Skills that consume
    # only fully-wired cards may leave this empty. Enforced by
    # test_composed_skill_status_matrix (verification Test 9).
    on_dependency_status: dict = field(default_factory=dict)


def validate(raw: dict, skill_name: Optional[str] = None) -> Composition:
    """Parse + validate a composition dict. Raises CompositionError on any
    issue. Returns a Composition dataclass on success.
    """
    label = f"skill {skill_name!r}" if skill_name else "composition block"

    if not isinstance(raw, dict):
        raise CompositionError(
            f"{label}: composition must be a YAML mapping, got {type(raw).__name__}"
        )

    def _require(key: str):
        if key not in raw:
            raise CompositionError(f"{label}: missing required key {key!r}")
        return raw[key]

    def _list_of_str(val, key: str) -> list[str]:
        if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
            raise CompositionError(
                f"{label}: {key!r} must be a list of strings, got {val!r}"
            )
        return val

    def _one_of(val, allowed: set, key: str):
        if val not in allowed:
            raise CompositionError(
                f"{label}: {key!r} value {val!r} not in {sorted(allowed)}"
            )

    def _all_in(vals: list, allowed: set, key: str):
        bad = [v for v in vals if v not in allowed]
        if bad:
            raise CompositionError(
                f"{label}: {key!r} contains invalid entries {bad!r}, "
                f"allowed: {sorted(allowed)}"
            )

    # data_mode
    data_mode = _require("data_mode")
    _one_of(data_mode, DATA_MODES, "data_mode")

    # Utility skills (data_mode == 'catalog_read') are NOT evidence-composing skills:
    # they answer no biology gate, compose no cards, and fire no rules. For them the
    # evidence-skill fields (phase / cards_used / rules_scope / steps_covered) are
    # OPTIONAL — validated if present, defaulted to empty otherwise — while the fields
    # a utility skill does carry (synthesis / output_shape / status) are still validated.
    is_utility = data_mode == "catalog_read"

    def _require_or_empty(key: str):
        """Required for evidence skills; optional (default []) for utility skills."""
        return raw.get(key, []) if is_utility else _require(key)

    # phase
    phases_raw = _require_or_empty("phase")
    phases = _list_of_str(phases_raw, "phase")
    _all_in(phases, PHASES, "phase")

    # cards_used
    cards_used = _list_of_str(_require_or_empty("cards_used"), "cards_used")

    # rules_scope
    rules_scope = _list_of_str(_require_or_empty("rules_scope"), "rules_scope")

    # synthesis
    synthesis = _list_of_str(_require("synthesis"), "synthesis")
    _all_in(synthesis, SYNTHESIS_KINDS, "synthesis")

    # output_shape
    output_shape = _list_of_str(_require("output_shape"), "output_shape")
    _all_in(output_shape, OUTPUT_SHAPES, "output_shape")

    # steps_covered
    steps_raw = _require_or_empty("steps_covered")
    if not isinstance(steps_raw, list) or not all(isinstance(x, int) for x in steps_raw):
        raise CompositionError(
            f"{label}: 'steps_covered' must be a list of ints (1-6), got {steps_raw!r}"
        )
    bad_steps = [s for s in steps_raw if s not in STEPS]
    if bad_steps:
        raise CompositionError(
            f"{label}: 'steps_covered' contains invalid entries {bad_steps!r}, "
            f"allowed: {sorted(STEPS)}"
        )

    # optional_lenses (optional field)
    optional_lenses = raw.get("optional_lenses", [])
    if optional_lenses:
        optional_lenses = _list_of_str(optional_lenses, "optional_lenses")
        _all_in(optional_lenses, OPTIONAL_LENSES, "optional_lenses")

    # status (optional field, defaults to 'wired')
    status = raw.get("status", "wired")
    _one_of(status, STATUSES, "status")

    # on_dependency_status (optional; composed skills only)
    # W3b fix (2026-07-09): `raw.get(key, {})` returns None when the key
    # exists with a YAML-null value (`on_dependency_status: null` or a bare
    # `on_dependency_status:` line). Coerce None → {} explicitly.
    on_dependency_status = raw.get("on_dependency_status") or {}
    if on_dependency_status:
        if not isinstance(on_dependency_status, dict):
            raise CompositionError(
                f"{label}: 'on_dependency_status' must be a mapping of "
                f"card_id -> behavior, got {type(on_dependency_status).__name__}"
            )
        for card_id, behavior in on_dependency_status.items():
            if not isinstance(card_id, str):
                raise CompositionError(
                    f"{label}: 'on_dependency_status' key {card_id!r} must be a string"
                )
            if behavior not in DEPENDENCY_STATUS_BEHAVIORS:
                raise CompositionError(
                    f"{label}: 'on_dependency_status[{card_id!r}]' value "
                    f"{behavior!r} not in {sorted(DEPENDENCY_STATUS_BEHAVIORS)}"
                )
            if card_id not in cards_used:
                raise CompositionError(
                    f"{label}: 'on_dependency_status' references card_id "
                    f"{card_id!r} not in cards_used ({cards_used!r})"
                )

    return Composition(
        data_mode=data_mode,
        phase=phases,
        cards_used=cards_used,
        rules_scope=rules_scope,
        synthesis=synthesis,
        output_shape=output_shape,
        steps_covered=steps_raw,
        optional_lenses=optional_lenses,
        status=status,
        on_dependency_status=on_dependency_status,
    )


def parse_skill_md_frontmatter(skill_md_path) -> Optional[dict]:
    """Extract the top-level YAML front-matter from a SKILL.md file.

    Returns the parsed dict, or None if the file has no front-matter block.
    Front-matter is the region between the first two `---` lines at the top
    of the file — same convention Jekyll / Hugo use, which every SKILL.md in
    this framework already follows.
    """
    from pathlib import Path
    import yaml

    text = Path(skill_md_path).read_text()
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    fm_text = text[4:end]
    try:
        return yaml.safe_load(fm_text)
    except Exception:
        return None


def validate_skill_md(skill_md_path) -> Composition:
    """Load a SKILL.md, parse its front-matter, validate the composition
    block. Returns the Composition dataclass. Raises CompositionError with
    a skill-name-tagged message on any issue.
    """
    from pathlib import Path

    fm = parse_skill_md_frontmatter(skill_md_path)
    if fm is None:
        raise CompositionError(
            f"{Path(skill_md_path)}: no YAML front-matter block found"
        )
    skill_name = fm.get("name", Path(skill_md_path).parent.name)
    composition = fm.get("composition")
    if composition is None:
        raise CompositionError(
            f"skill {skill_name!r}: front-matter missing 'composition' block"
        )
    return validate(composition, skill_name=skill_name)
