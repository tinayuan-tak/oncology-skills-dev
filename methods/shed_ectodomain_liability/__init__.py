"""shed-ectodomain-liability method module.

Surface-window no-go signal: is a surface-present antigen's ectodomain
proteolytically SHED into circulation as a soluble decoy ("antigen sink") that
neutralizes an antibody / ADC / T-cell-engager before tumor delivery?

Two evidence tiers (no clean redistributable structured shedding
system-of-record exists):
  1. RELIABLE `clinical` — curated serum-marker crosswalk
     (target-contracts/vocabularies/shed_antigen_targets.yaml). A serum tumor
     marker IS a shed ectodomain (CA125=MUC16, SMRP=MSLN, shed-HER2-ECD, CEA).
     The ONLY tier that reliably covers shed receptors (HPA misses ERBB2/CEACAM5).
  2. PROXY `secretome_proxy` — HPA v25-1 "Secretome location" column.

Plus a MEASURED facet: Olink NPX in DepMap CONDITIONED MEDIA
(`media.py`) — protein a live cancer cell actually released into supernatant. A
PARALLEL categorical (`measured_shed_class`), additive: it never alters the primary
`shed_liability_class` the two annotation tiers produce. The media panel is bounded +
secretome-preselected, so panel-absence is NON-informative; only a positive
`media_shed_high` is verdict-relevant.

Emits `shed_liability_class` ∈ {clinically_shed | secretome_proxy_shed |
not_shed_membrane_retained | indeterminate} (primary, annotation-based) and
`measured_shed_class` ∈ {media_shed_high | media_shed_low | not_on_secreted_panel |
data_unavailable} (parallel, measured). Signal is `opposing` (drug-sink de-prioritizes),
never `killer` — approved biologics exist against shed antigens.

Modules:
    cli   — loaders (curated vocab + HPA secretome) + classifier + CLI
    media — the MEASURED Olink conditioned-media leg (measured_shed_class facet)
    read  — read_target_summary: the live-mode dispatcher entry
"""

METHOD_VERSION = "0.2.0"

from .read import read_target_summary  # noqa: E402,F401
