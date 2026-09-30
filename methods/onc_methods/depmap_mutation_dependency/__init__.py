"""depmap_mutation_dependency — Card 3 (mutation-stratified-dependency) method.

Asks: across the DepMap panel, does dependency on {target} stratify by {target}'s
OWN mutation status? Drives the oncogene-addiction biomarker hypothesis (mutant cells
strongly dependent ↔ mutation-stratified clinical strategy, e.g. BRAF-V600E + vemurafenib,
KRAS-G12C + sotorasib).

Mirrors DepMap's "Mutation" portal page. Target-only output (Decision 2A): one evidence
package per target serves all indications + modalities; per-indication mutation rates +
indication-specific mutation-stratified dependency are downstream synthesis questions.

Two-tier mutation grouping:
  - hotspot — known oncogenic positions (OmicsSomaticMutationsMatrixHotspot.csv)
  - damaging — broader LOF (OmicsSomaticMutationsMatrixDamaging.csv)
  - any — union of hotspot + damaging

Public API:
    read_mutation_stratified_dependency(target, indication=None) -> dict
"""

__version__ = "0.1.0"

from .read import read_mutation_stratified_dependency

__all__ = ["read_mutation_stratified_dependency"]
