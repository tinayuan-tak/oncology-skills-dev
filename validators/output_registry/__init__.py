"""output_registry — derived cross-tier index of framework outputs (the output spine).

Scans the governed data-products repo (evidence packages) + the exploratory skill-runs S3
index, and emits a unified `catalog.json` (+ CATALOG.md + coverage.html). Its card-level
firing index (`card_firings`) is the authoritative source that framework_health's probe
consumes for the merged `fires_in_any_run` liveness signal.
"""
