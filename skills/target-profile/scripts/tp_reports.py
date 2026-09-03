"""Optional report_render bundle emission for target-profile (the `--reports` flag).

Renders the composed nomination into `report_<preset>.<ext>` files under `<out>/reports/` via the shared
`_skills_common.report_render` engine (landed #951). BEST-EFFORT: a render failure must NEVER abort a
run (mirrors the html artifact) — so `reports` is a BEST_EFFORT kind in tp_emit and every render/write is
wrapped. Returns {"reports"} iff at least one file was written, so the caller can record it in the
run-scoped write-set that assert_write_set checks.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from _skills_common.report_render import render_all, resolve_spec
from _skills_common.report_render.backends import BINARY_BACKENDS, EXTENSIONS

# default forms (fast, no pandoc); callers can add pptx via --report-backends.
DEFAULT_BACKENDS = ("markdown", "html", "json")


def write_reports(out_dir, nomination: dict, presets: Iterable[str],
                  backends: Iterable[str] | None = None) -> set:
    """Render each preset × backend → <out_dir>/reports/report_<preset>.<ext>.

    Returns {"reports"} if ≥1 file was written, else an empty set. Fail-soft at every level (a bad
    preset, a backend that raises, a write error) so one failure never blocks the rest or the run."""
    presets = [p for p in (presets or []) if p]
    backends = list(backends) if backends else list(DEFAULT_BACKENDS)
    if not presets:
        return set()
    reports_dir = Path(out_dir) / "reports"
    wrote_any = False
    for preset in presets:
        try:
            rendered = render_all(nomination, spec=resolve_spec(preset), backends=backends)
        except Exception:
            continue  # unknown preset / build failure → skip this preset, keep going
        for backend, content in rendered.items():
            try:
                reports_dir.mkdir(parents=True, exist_ok=True)
                path = reports_dir / f"report_{preset}.{EXTENSIONS.get(backend, 'txt')}"
                if backend in BINARY_BACKENDS:
                    path.write_bytes(content)
                else:
                    path.write_text(content)
                wrote_any = True
            except Exception:
                continue
    return {"reports"} if wrote_any else set()


__all__ = ["write_reports", "DEFAULT_BACKENDS"]
