"""living — the living architecture document (superset of the unified dashboard).

Adds three tabs on top of the unified dashboard's wiring/health/coverage:
  · Gaps      — one ranked "missing pieces" list (validators + framework_health + coverage)
  · Concepts  — the ~8 component types, each with concept + schema + real example + where-defined
  · Docs      — the prose design docs, keyed to the component types they describe

Plus a baked-in LEGIBILITY layer: every machine token is glossed to plain language, and the
build fails (glossary-coverage test) if a surfaced token is not glossed.

All generated from the contracts + committed JSON feeds; drift-guarded like the unified
dashboard (`--check`) and framework_health (`--self-check`).
"""
