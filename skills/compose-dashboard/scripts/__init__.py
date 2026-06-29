"""compose-dashboard scripts — phase-1 implementation modules.

Phase 1 of compose-dashboard: resolve dashboard_spec + modality module + subgroup_catalog
into a deterministic run_plan.yaml. NO method execution; NO synthesis. Just the run plan.

See plan § Dashboard, Interpretation, and Inference Layers § Implementation discipline.

Modules:
  _resolution.py   — axis lookup, dashboard_spec selection, modality module loading
  _composition.py  — card set assembly, threshold overlay merging, method-call binding
  _validation.py   — validate run_plan against run_plan.schema.json
  compose_phase1.py — CLI entry point
"""
