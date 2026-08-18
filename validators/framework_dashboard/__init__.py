"""framework_dashboard — the consolidated framework dashboard (health + architecture).

ONE self-contained HTML product with an executive Overview that drills into:
  - Explorer  : Miller-columns wiring (skill → cards → datasets · methods · outputs · rules → verdict)
  - Health    : the framework_health skill matrix (derived verdict, drift, runs-clean)
  - Cards     : per-card inventory (inputs, outputs, verdict, health)
  - Datasets  : catalog-resolution inventory (manifest / non-manifest / uncataloged, indication families)

Data sources (read fresh at build time):
  - target-contracts : cards/*.card.yaml, interpretation-rules/*.rules.yaml, resolvers/*.resolver.yaml
  - claude-oncology-skills : skills/*/SKILL.md composition
  - data-catalog : manifests/**.yaml + subgroup-catalogs/ + resolver-releases/
  - framework_health.generate() : the derived health overlay (imported, not modified)

Entry point:  python -m validators.framework_dashboard.build
"""
__version__ = "0.1.0"
