"""opentargets_mouse_phenotype — mouse-KO normal-physiology safety (with the
developmental-vs-adult guardrail).

Reads Open Targets 26.06 `mouse_phenotype` (MGI knockout phenotypes, ENSG-keyed, ~11,869 genes ×
avg 17 phenotype rows) → ko_phenotype_class. The normal-physiology safety question: does knocking
out the gene in a mouse cause death or severe organ dysfunction — implying an essential function a
full-KO therapy might recapitulate?

THE DEVELOPMENTAL GUARDRAIL: lethal labels split into two
developmentally-distinct buckets, and conflating them OVER-estimates adult on-target tox:
  - DEVELOPMENTAL lethality (prenatal / embryonic / fetal / perinatal / neonatal / preweaning) —
    reflects a role in DEVELOPMENT; a gene essential for embryogenesis may be dispensable in adult
    tissue. → `developmental_only` (a CAVEAT, never the adult-tox killer).
  - ADULT/POSTNATAL lethality (postnatal / postweaning, NOT qualified as pre-weaning) — death after
    weaning implies an adult-essential function. → `lethal_ko` (the safety-relevant signal).
Without this split, every embryonic-lethal gene would false-flag an adult safety hold.

EVIDENCE TIER = inferred (mouse is a MODEL of human physiology, not a direct human measurement) — so
the card must NOT fire a measured-strength killer; its warning is inferred-tier context.

data_unavailable-safe.
"""
from __future__ import annotations

from typing import Optional

from ..opentargets_common import read_entity, symbol_to_ensembl

METHOD_VERSION = "0.1.0"

# Developmental-stage tokens: lethality AT or BEFORE weaning reflects development, not adult essentiality.
_DEVELOPMENTAL_TOKENS = ("prenatal", "embryonic", "fetal", "perinatal", "neonatal", "preweaning",
                         "implantation", "somite", "organogenesis", "tooth bud")
# Adult tokens: lethality AFTER birth/weaning that is NOT qualified as pre-weaning → adult-essential.
_ADULT_LETHAL_TOKENS = ("postnatal", "postweaning")

# Severe adult-organ phenotype classes (MGI top-level system phenotypes) — a non-lethal but serious
# safety signal when the KO survives to adulthood with major organ dysfunction.
_SEVERE_ORGAN_CLASSES = {
    "cardiovascular system phenotype", "nervous system phenotype", "hematopoietic system phenotype",
    "immune system phenotype", "liver/biliary system phenotype", "renal/urinary system phenotype",
    "respiratory system phenotype", "digestive/alimentary phenotype", "endocrine/exocrine gland phenotype",
}

_FIELDS = ["targetFromSourceId", "modelPhenotypeLabel", "modelPhenotypeClasses"]


def _is_lethal(label: str) -> bool:
    return "lethal" in label.lower()


def _lethal_stage(label: str) -> str:
    """'developmental' | 'adult' | 'unspecified' for a lethal label."""
    low = label.lower()
    if any(tok in low for tok in _DEVELOPMENTAL_TOKENS):
        return "developmental"
    if any(tok in low for tok in _ADULT_LETHAL_TOKENS):
        return "adult"
    return "unspecified"   # bare "lethality" with no stage → conservatively NOT an adult killer


def _class_labels(model_phenotype_classes) -> set:
    """Extract the set of phenotype-class labels from the struct-list field."""
    out = set()
    if model_phenotype_classes is None:
        return out
    try:
        for c in model_phenotype_classes:
            if isinstance(c, dict) and c.get("label"):
                out.add(str(c["label"]).strip().lower())
    except TypeError:
        return out
    return out


def classify_ko_phenotype(rows: list) -> dict:
    """Pure classifier: a gene's mouse-KO phenotype rows → ko_phenotype_class + evidence.

    Priority (most-severe adult signal first):
      1. ANY adult/postnatal lethal label            → lethal_ko (adult-essential; the safety signal).
      2. ELSE any developmental lethal label          → developmental_only (caveat, NOT adult tox).
      3. ELSE any severe adult-organ phenotype class   → severe_organ_phenotype.
      4. ELSE phenotype rows exist but none of the above → mild_phenotype.
      5. no rows                                        → no_phenotype (KO tolerated / not modeled).
    """
    if not rows:
        return {"ko_phenotype_class": "no_phenotype", "n_rows": 0, "n_lethal": 0,
                "lethal_stages": [], "top_lethal_label": None, "organ_classes": []}

    lethal = [(r.get("modelPhenotypeLabel", ""), _lethal_stage(r.get("modelPhenotypeLabel", "")))
              for r in rows if _is_lethal(r.get("modelPhenotypeLabel", ""))]
    adult_lethal = [l for l in lethal if l[1] == "adult"]
    dev_lethal = [l for l in lethal if l[1] == "developmental"]
    unspec_lethal = [l for l in lethal if l[1] == "unspecified"]

    organ = set()
    for r in rows:
        organ |= (_class_labels(r.get("modelPhenotypeClasses")) & _SEVERE_ORGAN_CLASSES)

    if adult_lethal:
        cls = "lethal_ko"
        top = adult_lethal[0][0]
    elif dev_lethal or unspec_lethal:
        # developmental (or unstaged) lethality → caveat, NOT an adult-tox killer (the guardrail)
        cls = "developmental_only"
        top = (dev_lethal or unspec_lethal)[0][0]
    elif organ:
        cls = "severe_organ_phenotype"
        top = None
    else:
        cls = "mild_phenotype"
        top = None

    return {
        "ko_phenotype_class": cls,
        "n_rows": len(rows),
        "n_lethal": len(lethal),
        "n_adult_lethal": len(adult_lethal),
        "n_developmental_lethal": len(dev_lethal),
        "lethal_stages": sorted({l[1] for l in lethal}),
        "top_lethal_label": top,
        "organ_classes": sorted(organ),
    }


def read_mouse_ko_phenotype(target: str, indication: Optional[str] = None) -> dict:
    """Mouse-KO normal-physiology safety summary for `target` (HGNC symbol or ENSG).

    `indication` accepted for signature-uniformity but NOT used — mouse-KO phenotype is per-gene.
    """
    ensg = symbol_to_ensembl(target)
    base = {"target": target, "ensembl_gene_id": ensg, "method_version": METHOD_VERSION,
            "source": "opentargets-26-06/mouse_phenotype", "evidence_tier": "inferred"}
    if ensg is None:
        return {**base, "ko_phenotype_class": "insufficient",
                "_note": "target not resolvable to an Ensembl gene id via the OT resolver sidecar"}

    df = read_entity("mouse_phenotype", columns=_FIELDS)
    if df.empty:
        return {**base, "ko_phenotype_class": "insufficient",
                "_note": "mouse_phenotype entity not available"}
    hit = df[df["targetFromSourceId"] == ensg]
    if hit.empty:
        return {**base, "ko_phenotype_class": "no_phenotype",
                "n_rows": 0, "_note": f"{ensg} has no mouse-KO phenotype rows (KO not modeled / tolerated)"}

    return {**base, **classify_ko_phenotype(hit.to_dict("records"))}


def _main(argv=None):
    import argparse
    import json
    ap = argparse.ArgumentParser(description="OT mouse-KO normal-physiology safety for a target.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", default=None)
    args = ap.parse_args(argv)
    print(json.dumps(read_mouse_ko_phenotype(args.target, args.indication), indent=2, default=str))


if __name__ == "__main__":
    _main()
