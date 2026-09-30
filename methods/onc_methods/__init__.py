"""onc_methods — deterministic analytical methods for the Takeda v2 oncology
target-evaluation framework.

Each submodule under `methods/onc_methods/<name>/` is a self-contained analysis method
with a `read.py` library entry (consumed by the compose-dashboard dispatcher) and, where
it emits figures, a `cli.py` (CLI + figure emitters). See the repo README for the full
inventory grouped by biology gate.

The import package is `onc_methods` while the distribution DIRECTORY stays `methods/`
(skills#2237). The names must differ: a package dir named `methods` inside `methods/`
would be shadowed by the monorepo-root `methods/` directory whenever it lands on
sys.path, because PathFinder precedes the editable-install finder on sys.meta_path
(skills#2196). Since the names differ, `import onc_methods` can ONLY resolve through the
editable install — there is no sys.path fallback and none is wanted: every call site
imports the installed package (`pixi install` / `pip install -e methods/`).

Namespace-only: importing `onc_methods` does NOT eagerly import the submodules (they carry
heavy optional deps like scipy/R). Import the specific method you need:

    from onc_methods.dge_deseq2 import read
    from onc_methods.depmap_chronos import cli
"""
