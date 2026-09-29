"""methods — deterministic analytical methods for the Takeda v2 oncology
target-evaluation framework.

Each submodule under `methods/<name>/` is a self-contained analysis method with a
`read.py` library entry (consumed by the compose-dashboard dispatcher) and, where it
emits figures, a `cli.py` (CLI + figure emitters). See the repo README for the full
inventory grouped by biology gate.

This package is installable (`pip install -e .`) so downstream consumers — skills,
notebooks, batch jobs — can `import methods.<name>` without sys.path manipulation. A
`sys.path.insert(<repo>)` fallback remains in the skills for editable/uninstalled use.

Namespace-only: importing `methods` does NOT eagerly import the submodules (they carry
heavy optional deps like scipy/R). Import the specific method you need:

    from methods.dge_deseq2 import read
    from methods.depmap_chronos import cli
"""
