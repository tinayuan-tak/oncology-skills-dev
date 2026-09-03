"""The report spec — a small DECLARATIVE selection over the skill_report[] spine.

Three orthogonal dials (contract docs/UNIFIED_OUTPUT_CONTRACT.md §241-275). Decide the content once
(the spine), present many ways:

  1. level  — progressive disclosure: L0 headline · L1 summary · L2 evidence · L3 trace
  2. medium — per-slot text ⇄ figure form (figure degrades to caption+table when text-only)
  3. scope  — which skills (all | gating | an explicit list) + how to lead the report

This object carries NO rendering logic and NO business logic — it is the ONLY place the
include/omit/limit decisions live. The IR builder reads it; the backends never see a raw spec dial,
only the already-selected blocks. That keeps depth/medium orthogonal to format (a new backend needs
zero selection logic; a new dial changes only the builder).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, Union

# level vocabulary — cumulative tiers (L2 ⊇ L1 ⊇ L0). See vocab.TIER for the slot→tier map.
LEVELS = ("L0", "L1", "L2", "L3")
_LEVEL_INT = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}

# medium — how a slot with both a text and a figure form is rendered.
MEDIA = ("text", "figure", "both")

# lead — what the report opens with (skill ORDER is always role-first; this is the header emphasis).
LEADS = ("recommendation", "deciding_axis", "none")

# scope sentinels (besides an explicit tuple of skill shorts).
SCOPE_ALL = "all"
SCOPE_GATING = "gating"


@dataclass(frozen=True)
class ReportSpec:
    """One declarative report request. Frozen + hashable so it can key a cache / golden snapshot."""
    level: str = "L1"
    medium: str = "text"
    scope: Union[str, tuple] = SCOPE_ALL       # SCOPE_ALL | SCOPE_GATING | tuple(shorts)
    lead: str = "recommendation"
    # bump the single deciding-axis skill one level deeper than `level` (the reviewer-dossier pattern:
    # "L2, deciding axis L3"). A pure selection knob — the builder resolves which skill is deciding.
    bump_deciding: bool = False

    def __post_init__(self):
        if self.level not in LEVELS:
            raise ValueError(f"level must be one of {LEVELS}, got {self.level!r}")
        if self.medium not in MEDIA:
            raise ValueError(f"medium must be one of {MEDIA}, got {self.medium!r}")
        if self.lead not in LEADS:
            raise ValueError(f"lead must be one of {LEADS}, got {self.lead!r}")
        if not (self.scope in (SCOPE_ALL, SCOPE_GATING) or isinstance(self.scope, tuple)):
            raise ValueError(
                f"scope must be {SCOPE_ALL!r}, {SCOPE_GATING!r}, or a tuple of shorts, got {self.scope!r}")

    @property
    def level_int(self) -> int:
        return _LEVEL_INT[self.level]

    def level_int_for(self, short: str, is_deciding: bool) -> int:
        """The effective detail depth for one skill — `level`, bumped +1 for the deciding axis when
        `bump_deciding` is set (capped at L3)."""
        base = self.level_int
        if self.bump_deciding and is_deciding:
            return min(base + 1, _LEVEL_INT["L3"])
        return base


# Named presets — a preset is just a bundle of dial values, never a code path. `render_report`
# accepts a preset name or an explicit ReportSpec; overrides compose on top of a preset.
PRESETS: dict[str, ReportSpec] = {
    # one page, no figures, every skill as a one-liner, opens on the recommendation.
    "exec-brief": ReportSpec(level="L0", medium="text", scope=SCOPE_ALL, lead="recommendation"),
    # the decision-driving skills at evidence depth, deciding axis to the trace, figures where useful.
    "reviewer-dossier": ReportSpec(level="L2", medium="both", scope=SCOPE_GATING,
                                   lead="deciding_axis", bump_deciding=True),
    # slide-friendly: gating skills, summary depth, figure-forward.
    "deck": ReportSpec(level="L1", medium="figure", scope=SCOPE_GATING, lead="recommendation"),
    # everything, deepest, both forms — the full dossier / machine view source.
    "full": ReportSpec(level="L3", medium="both", scope=SCOPE_ALL, lead="deciding_axis"),
}


def resolve_spec(preset: Optional[str] = None, **overrides) -> ReportSpec:
    """Build a ReportSpec from an optional preset name plus explicit dial overrides. Unknown preset →
    ValueError (never a silent default). `overrides` are applied on top of the preset (or the default
    ReportSpec when no preset is given)."""
    base = PRESETS[preset] if preset is not None else ReportSpec()
    if not overrides:
        return base
    # normalize a list scope to a tuple so the result stays hashable/frozen.
    if "scope" in overrides and isinstance(overrides["scope"], list):
        overrides["scope"] = tuple(overrides["scope"])
    return replace(base, **overrides)


__all__ = ["ReportSpec", "PRESETS", "resolve_spec", "LEVELS", "MEDIA", "LEADS",
           "SCOPE_ALL", "SCOPE_GATING"]
