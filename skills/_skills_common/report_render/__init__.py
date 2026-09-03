"""report_render — the declarative report-spec renderer over the skill_report[] spine.

Decide the content once (the spine: `target_report.skill_reports` + `target_call`), present many ways.
One pipeline:

    nomination (dict)  →  build_ir(nomination, spec)  →  ReportIR  →  backend.render(ir)  →  str

Three orthogonal dials on the spec — level (L0-L3), medium (text/figure/both), scope (all/gating/list)
+ lead — plus named presets. Selection logic lives ONLY in `ir.build_ir`; backends are dumb
{block-kind → syntax} emitters (text/markdown/json today; html/pptx to follow). See
docs/UNIFIED_OUTPUT_CONTRACT.md §241-275.

Public API:
    render_report(nomination, *, preset=None, backend="text", spec=None, target=None,
                  indication=None, **spec_overrides) -> str
    build_ir(...), ReportSpec, PRESETS, resolve_spec, backend_names()
"""
from __future__ import annotations

from typing import Optional

from . import backends as _backends
from .backends import backend_names, coverage, string_backend_names
from .ir import ReportIR, build_ir, build_ir_for_skill
from .spec import PRESETS, ReportSpec, resolve_spec

__all__ = [
    "render_report", "render_all", "render_skill_report", "build_ir", "build_ir_for_skill",
    "build_ir_auto", "ReportIR", "ReportSpec", "PRESETS", "resolve_spec",
    "backend_names", "string_backend_names", "coverage",
]


def _extract_skill(data):
    """If `data` is a standalone skill artifact, return (skill_report, skill_name); else None.
    Handles a decision.json ({"skill":…, "headline":{"skill_report":…}}) and a bare skill_report dict.
    A nomination (has target_report) is NOT a skill artifact."""
    if not isinstance(data, dict):
        return None
    hb = data.get("headline")
    if isinstance(hb, dict) and isinstance(hb.get("skill_report"), dict):
        return hb["skill_report"], data.get("skill")
    if "role" in data and "claim_chips" in data and "target_report" not in data:
        return data, data.get("_skill_name")
    return None


def build_ir_auto(data: dict, spec: ReportSpec, *, target=None, indication=None) -> ReportIR:
    """Build the IR from either a nomination.json (composed target report) OR a standalone skill
    artifact (decision.json / bare skill_report) — auto-detected."""
    sk = _extract_skill(data)
    if sk is not None:
        report, name = sk
        return build_ir_for_skill(report, spec, skill_name=name,
                                  target=target or data.get("target"),
                                  indication=indication or data.get("indication"))
    return build_ir(data, spec, target=target, indication=indication)


def render_report(nomination: dict, *, preset: Optional[str] = None, backend: str = "text",
                  spec: Optional[ReportSpec] = None, target: Optional[str] = None,
                  indication: Optional[str] = None, **spec_overrides) -> str:
    """Render one nomination to one backend's string. Provide a `preset` name and/or explicit
    `spec_overrides` (level/medium/scope/lead/bump_deciding), or pass a full `spec`."""
    if spec is None:
        spec = resolve_spec(preset, **spec_overrides)
    elif spec_overrides:
        raise ValueError("pass either an explicit spec OR spec_overrides, not both")
    ir = build_ir(nomination, spec, target=target, indication=indication)
    return _backends.render(ir, backend)


def render_all(nomination: dict, *, preset: Optional[str] = None, spec: Optional[ReportSpec] = None,
               backends: Optional[list] = None, target: Optional[str] = None,
               indication: Optional[str] = None, **spec_overrides) -> dict:
    """Render one nomination once (single IR) into several backends. Returns {backend_name: str}."""
    if spec is None:
        spec = resolve_spec(preset, **spec_overrides)
    ir = build_ir(nomination, spec, target=target, indication=indication)
    names = backends or backend_names()
    return {name: _backends.render(ir, name) for name in names}


def render_skill_report(source: dict, *, preset: Optional[str] = None, backend: str = "text",
                        spec: Optional[ReportSpec] = None, skill_name: Optional[str] = None,
                        short: Optional[str] = None, target: Optional[str] = None,
                        indication: Optional[str] = None, **spec_overrides) -> str:
    """Render a SINGLE skill. `source` may be a standalone decision.json, or a bare skill_report dict
    (then pass `skill_name`/`short` for a nice title)."""
    if spec is None:
        spec = resolve_spec(preset, **spec_overrides)
    elif spec_overrides:
        raise ValueError("pass either an explicit spec OR spec_overrides, not both")
    sk = _extract_skill(source)
    if sk is not None:
        report, name = sk
        target = target or source.get("target")
        indication = indication or source.get("indication")
    else:
        report, name = source, skill_name
    ir = build_ir_for_skill(report, spec, skill_name=name or skill_name, short=short,
                            target=target, indication=indication)
    return _backends.render(ir, backend)
