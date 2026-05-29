"""Layer 3 — Jinja2 renderer.

Pure function: context dict in, markdown string out. The template is
loaded from `templates/integrated_report.md.j2` relative to the workflow
skill root.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined


SKILL_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = SKILL_ROOT / "templates"
DEFAULT_TEMPLATE = "integrated_report.md.j2"


def render_integrated_report(
    context: dict[str, Any],
    template_name: str = DEFAULT_TEMPLATE,
) -> str:
    """Render the integrated-report markdown.

    Uses StrictUndefined: unknown context keys raise rather than silently
    produce empty strings. That's what catches "template references
    risk.foo but context only has risk.bar" at render time, not at
    PDF-parse time.
    """
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    template = env.get_template(template_name)
    return template.render(**context)
