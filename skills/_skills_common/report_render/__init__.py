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
from .ir import ReportIR, build_ir
from .spec import PRESETS, ReportSpec, resolve_spec

__all__ = [
    "render_report", "render_all", "build_ir", "ReportIR",
    "ReportSpec", "PRESETS", "resolve_spec", "backend_names", "string_backend_names", "coverage",
]


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
