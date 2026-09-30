"""hcmi_model_availability — per-indication HCMI patient-derived model availability (translational bridge).

Scientific-gap #1 (2026-08-14), lighter-v1: "for indication Y, how many patient-derived (HCMI organoid /
next-gen cancer) models exist to preclinically validate a nominated target?" An INDICATION-level
translational-readiness signal (target-independent) crosswalked from the 805 HCMI-CMDC DR45 case
ClinicalData JSONs. The genotype-MATCHED v2 (does a model carry target X's alteration?) joins the HCMI
WXS MAFs on top of this crosswalk.

Validated 2026-08-14: 376/805 models map to the 4 TSS-core indications — COADREAD 209 (deep), PAAD 115
(deep), NSCLC 27 (moderate), GC 25 (moderate).
"""

# Re-export the card read-entrypoint at package level so compose-dashboard generic-dispatch resolution
# (getattr(import_module(module), entrypoint)) resolves `hcmi_model_availability.read_model_availability`
# — the target-model-availability card's declared method call. (Convention learned in AM#343: a card
# entrypoint that lives only in a submodule breaks test_generic_routed_card_resolves_to_real_callable.)
from .read import read_genotype_matched_model, read_model_availability

__all__ = ["read_model_availability", "read_genotype_matched_model"]
