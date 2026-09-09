#!/usr/bin/env python3
"""render_review.py — RETIRED (dashboard consolidation, 2026-09-09).

This bespoke dev reviewer built its OWN static HTML + palette to review a target-profile run
(cross-evidence synthesis + 6-dimension deterministic-vs-literature risk + modality-fit, per-subskill
drill-down). That layout is now the CANONICAL composed dashboard rendered by `report_render` on every
run (`target_profile.html`): the 6-dimension collapsible spine, the lit×omics coherence table, the
cross-evidence causal chain, and the modality matrix all render there. Retired to remove a divergent
second renderer/design (see the consolidation plan; example-gallery was reskinned onto report_render in
the same arc).

Kept as a thin shim so any lingering invocation points at the canonical renderer instead of silently
rendering a stale, diverging design. It no longer builds HTML itself (no `build_html`).
"""

from __future__ import annotations

import sys

_MSG = (
    "render_review.py is RETIRED (dashboard consolidation). The review layout is now the canonical "
    "report_render composed dashboard.\n"
    "  • Every full run already emits <out>/target_profile.html.\n"
    "  • Re-render from a run dir:  python -m _skills_common.report_render <run_dir>/nomination.json "
    "--backend html\n"
    "  • Per-subskill:  <run_dir>/subskills/<skill>/dashboard.html (emitted on every subskill run)."
)


def main(argv=None) -> int:
    print(_MSG, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
