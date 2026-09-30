#!/usr/bin/env python3
"""catalog-query — thin front end over methods/catalog_query (analysis-methods).

Per the framework rule (skills call methods; methods don't know about skills),
the query engine lives in analysis-methods. This shim locates that repo, puts it
on sys.path, and hands argv straight to the method's CLI main(). All flags,
subcommands, and exit codes are the method's — see
methods/catalog_query/cli.py or `run.py <subcommand> -h`.

READ-ONLY: the method imports no boto3/s3fs and never writes; this shim adds no
compute of its own.

Repo location resolves via ANALYSIS_METHODS_ROOT (the established env-override
convention across this skills repo), defaulting to the standard checkout.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Repo-root-relative default — this file lives at <repo>/skills/catalog-query/scripts/, so
# parents[3] is the repo root, where methods/ now lives (SK#2063 monorepo consolidation).
# Standalone script (no assumption skills/ is on sys.path yet), so this does not import
# _skills_common.paths — it mirrors that module's ANALYSIS_METHODS_ROOT_DEFAULT inline instead
# of a hardcoded $HOME/rnd-... literal (SK#2137: that literal is the ARCHIVED pre-merge clone).
_ANALYSIS_METHODS_ROOT_DEFAULT = str(Path(__file__).resolve().parents[3] / "methods")

METHODS_REPO = Path(
    os.environ.get(
        "ANALYSIS_METHODS_ROOT",
        _ANALYSIS_METHODS_ROOT_DEFAULT,
    )
)


def main() -> int:
    if not (METHODS_REPO / "onc_methods" / "catalog_query" / "cli.py").exists():
        sys.stderr.write(
            f"error: analysis-methods checkout not found at {METHODS_REPO}.\n"
            f"set ANALYSIS_METHODS_ROOT to your analysis-methods repo path.\n"
        )
        return 2
    from onc_methods.catalog_query.cli import main as cli_main

    return cli_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
