"""cd_antigen_backbone.classify — CD/immuno-oncology antigen-backbone clinical-precedent (E6-CD).

Answers a question orthogonal to everything surface-modality-fit predicts (topology, density,
window are all PREDICTED biology): is the target on the canonical CD / immuno-oncology antigen
BACKBONE — the antigen class that has actually DELIVERED approved biologics (CD19/CD20/CD22/CD38/
BCMA-class mAb/TCE/CAR-T)? A clinical-PRECEDENT prior, not a predicted property.

Substrate: hgnc-gene-group-471 "CD molecules" (394 canonical CD antigens per HGNC; CC0). The
roster catches immuno-oncology backbone antigens that DON'T carry "CD" in their HGNC symbol
(PDCD1=CD279, CTLA4=CD152, HAVCR2/TIM3=CD366) — which a family-label match on the symbol misses.

CLASSES (clinical-precedent strength, NOT this-target-validated):
  established_io_backbone — a canonical CD antigen with an APPROVED or advanced-clinical biologic
                            against the class (curated precedent set: CD19/CD20/CD22/CD38/CD30/
                            CD33/CD79B/TNFRSF17-BCMA/... ). The strongest tractability prior.
  cd_antigen              — on the HGNC CD-molecule roster (a canonical CD antigen) but not in the
                            curated approved-precedent set. Still a real backbone prior.
  not_cd_antigen          — not on the roster. NOT a negative for biologics — most good ADC/TCE
                            targets (CEACAM5, FOLR1, TROP2, MSLN, CLDN18.2) are NOT CD antigens.
                            The absence of a CD-backbone prior, nothing more.
  data_unavailable        — roster unreadable (infra).

HONEST FRAMING (load-bearing): this is a CLASS-level clinical-precedent prior. "On the backbone"
does NOT mean THIS target is validated; "not_cd_antigen" does NOT count against a target (the
best solid-tumor ADC/TCE antigens are not CD molecules). It's a supportive-only enrichment prior.
"""

from __future__ import annotations

# Curated approved / advanced-clinical IO-backbone antigens (mAb / ADC / TCE / CAR-T precedent).
# HGNC symbols. Deliberately conservative — approved or late-stage clinical only. The point is a
# HIGH-precision "this class delivered drugs" prior, not a comprehensive IO list.
ESTABLISHED_IO_BACKBONE = frozenset(
    {
        "MS4A1",  # CD20 — rituximab/obinutuzumab (mAb), mosunetuzumab (TCE)
        "CD19",  # blinatumomab (TCE), tisagenlecleucel (CAR-T), loncastuximab (ADC)
        "CD22",  # inotuzumab ozogamicin (ADC), moxetumomab
        "CD38",  # daratumumab / isatuximab (mAb)
        "CD30",  # TNFRSF8 — brentuximab vedotin (ADC)
        "TNFRSF8",  # CD30 (HGNC symbol)
        "CD33",  # gemtuzumab ozogamicin (ADC)
        "CD79B",  # polatuzumab vedotin (ADC)
        "TNFRSF17",  # BCMA — belantamab (ADC), teclistamab (TCE), ide-cel/cilta-cel (CAR-T)
        "SLAMF7",  # CD319 — elotuzumab (mAb)
        "CD52",  # alemtuzumab (mAb)
        "CD3E",  # the TCE effector arm (CD3) — backbone of every T-cell engager
    }
)

METHOD_VERSION = "1.0.0"


def classify_cd_backbone(target: str, roster: dict) -> dict:
    """Classify a target's CD/IO-backbone membership from the roster lookup dict.

    `roster`: {UPPER(symbol) -> record} built by read.py (record carries cd/uniprot_ids/
    ensembl_gene_id/gene_group_id). Pure — no S3."""
    t = target.strip().upper()
    rec = roster.get(t)
    on_backbone = rec is not None
    established = t in ESTABLISHED_IO_BACKBONE
    if established:
        cls = "established_io_backbone"
    elif on_backbone:
        cls = "cd_antigen"
    else:
        cls = "not_cd_antigen"
    return {
        "cd_antigen_backbone_class": cls,
        "on_cd_roster": on_backbone,
        "cd_number": (rec or {}).get("cd") if on_backbone else None,
        "cd_roster_uniprot": ((rec or {}).get("uniprot_ids") or [None])[0] if on_backbone else None,
        "cd_gene_groups": (rec or {}).get("gene_group") if on_backbone else None,
        "established_io_precedent": established,
        "method_version": METHOD_VERSION,
    }


def empty(note: str) -> dict:
    return {
        "cd_antigen_backbone_class": "data_unavailable",
        "on_cd_roster": None,
        "cd_number": None,
        "cd_roster_uniprot": None,
        "cd_gene_groups": None,
        "established_io_precedent": None,
        "method_version": METHOD_VERSION,
        "_data_note": note,
    }
