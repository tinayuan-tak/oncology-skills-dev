"""living — the Framework Atlas (the living architecture document).

Adds three tabs on top of the base wiring/health/coverage build (`build_unified_dashboard.py`
— retained as the internal module name; the product-facing surface is the Framework Atlas):
  · Gaps      — one ranked "missing pieces" list (validators + framework_health + coverage)
  · Concepts  — the ~8 component types, each with concept + schema + real example + where-defined
  · Docs      — the prose design docs, keyed to the component types they describe

Plus a baked-in LEGIBILITY layer: every machine token is glossed to plain language, and the
build fails (glossary-coverage test) if a surfaced token is not glossed.

All generated from the contracts + committed JSON feeds; drift-guarded like the unified
dashboard (`--check`) and framework_health (`--self-check`).
"""
