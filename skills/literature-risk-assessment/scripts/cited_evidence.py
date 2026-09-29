"""cited_evidence — verdict-INERT gene×indication CITED-LITERATURE card (SHIM).

The compose logic now lives ONCE in analysis-methods
(methods/cited_literature_evidence/read.py) — it composes two analysis-methods readers, so it belongs
in the method layer, and the target-contracts card `cited-literature-evidence` references it as a
single `methods:` entrypoint (home skill: literature-context). This module is a thin BACK-COMPAT shim
re-exporting the pure assembler + the live composer so the standalone CLI (documented in this skill's
SKILL.md) and any legacy caller keep working; it holds no compose logic of its own.

  - build_cited_evidence_card(target, indication, epmc, relations, *, top_cited=8) : the PURE
    (offline-testable) NESTED-card assembler.
  - cited_evidence(target, indication, *, top_cited=8) : the LIVE nested composer (best-effort per lane).

See analysis-methods methods/cited_literature_evidence/read.py for the implementation +
read_cited_literature_evidence (the flattened CARD entrypoint the target-contracts card dispatches).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# analysis-methods holds the single source of truth (methods/cited_literature_evidence/). Put its repo
# root on sys.path (repo convention: ANALYSIS_METHODS_ROOT, mirrors _skills_common/_live_readers.py) so
# the top-level re-export resolves whether this shim is imported standalone (CLI / importlib) or in-process.
# Repo-root-relative default (this file lives at <repo>/skills/literature-risk-assessment/scripts/, so
# parents[3] is the repo root, where methods/ now lives — SK#2063 monorepo consolidation). Inlined
# rather than importing _skills_common.paths since this shim must resolve before skills/ is
# necessarily on sys.path (standalone CLI invocation) — never a hardcoded $HOME/rnd-... literal
# (SK#2137: that literal is the ARCHIVED pre-merge clone).
_ANALYSIS_METHODS_ROOT_DEFAULT = str(Path(__file__).resolve().parents[3] / "methods")
_METHODS_REPO = os.environ.get("ANALYSIS_METHODS_ROOT", _ANALYSIS_METHODS_ROOT_DEFAULT)
if _METHODS_REPO not in sys.path:
    sys.path.insert(0, _METHODS_REPO)

from methods.cited_literature_evidence.read import (  # noqa: E402 — path set above; single source of truth
    CARD_VERSION,
    DEFAULT_TOP_CITED,
    build_cited_evidence_card,
    cited_evidence,
)

__all__ = ["build_cited_evidence_card", "cited_evidence", "DEFAULT_TOP_CITED", "CARD_VERSION"]


def _main(argv=None):
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Verdict-inert gene×indication cited-literature card.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--top-cited", type=int, default=DEFAULT_TOP_CITED)
    args = ap.parse_args(argv)
    print(json.dumps(cited_evidence(args.target, args.indication, top_cited=args.top_cited), indent=2, default=str))


if __name__ == "__main__":
    _main()
