"""shed-ectodomain-liability method module.

Gate-F surface-window no-go signal: is a surface-present antigen's ectodomain
proteolytically SHED into circulation as a soluble decoy ("antigen sink") that
neutralizes an antibody / ADC / T-cell-engager before tumor delivery?

Two evidence tiers (deep-research verdict 2026-07-19 — no clean redistributable
structured shedding system-of-record exists):
  1. RELIABLE `clinical` — curated serum-marker crosswalk
     (target-contracts/vocabularies/shed_antigen_targets.yaml). A serum tumor
     marker IS a shed ectodomain (CA125=MUC16, SMRP=MSLN, shed-HER2-ECD, CEA).
     The ONLY tier that reliably covers shed receptors (HPA misses ERBB2/CEACAM5).
  2. PROXY `secretome_proxy` — HPA v25-1 "Secretome location" column.

Emits `shed_liability_class` ∈ {clinically_shed | secretome_proxy_shed |
not_shed_membrane_retained | indeterminate}. Signal is `opposing` (drug-sink
de-prioritizes), never `killer` — approved biologics exist against shed antigens.

Modules:
    cli  — loaders (curated vocab + HPA secretome) + classifier + CLI
    read — read_target_summary: the live-mode dispatcher entry
"""
METHOD_VERSION = "0.1.0"

from .read import read_target_summary  # noqa: E402,F401
