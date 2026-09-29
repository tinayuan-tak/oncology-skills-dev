"""framework_health — derive component health from ground truth, flag drift.

A DERIVED artifact (never hand-authored), in the same family as
validators/build_subgroup_coverage_matrix.py: it probes what is actually on
disk across the framework repos (skills + the cards they consume), computes a
deterministic first-match health verdict per component, and flags every place
a component's DECLARED status diverges from its FILE REALITY.

Layering (mirrors the framework's own separation):
  probe.py   — read-only ground-truth probes (AST-based; never trust prose)
  rollup.py  — deterministic first-match verdict + drift, driven by health_rules.yaml
  render_html.py — framework_health.json -> self-contained HTML
  build_framework_health.py — CLI: generate | --check (staleness guard)

Design invariant: a probe NEVER raises. A read failure records an explicit
`"error"` / `None` value so one malformed component can't crash the dashboard —
the same graceful-degradation contract the method live-readers use.
"""

from __future__ import annotations
