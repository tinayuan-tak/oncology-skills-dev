"""cd_antigen_backbone — CD / immuno-oncology antigen-backbone clinical-precedent signal (E6-CD).

Reads hgnc-gene-group-471 (394 canonical CD antigens, CC0). Emits cd_antigen_backbone_class ∈
{established_io_backbone | cd_antigen | not_cd_antigen | data_unavailable} — a CLASS-level clinical-
precedent prior (the antigen class delivered approved biologics), orthogonal to the predicted-biology
axes surface-modality-fit scores. Supportive-only: not_cd_antigen is NOT a negative (most solid-tumor
ADC/TCE antigens — CEACAM5/FOLR1/TROP2/MSLN — are not CD molecules).
"""

from .read import read_cd_antigen_backbone  # noqa: F401

METHOD_VERSION = "1.0.0"
