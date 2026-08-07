"""domain_modality_relevance.read — per-target domain→MODALITY implication (roadmap #3).

The domain ARCHITECTURE inventory already exists (uniprot_protein_features / protein-domains-class
card: domain_names, protein_class, InterPro hits). What was MISSING is the interpretive step the
roadmap #3 note asked for: does a target's domain FUNCTION favor a catalytic-site inhibitor, or
does it call for REMOVAL (degrader / molecular glue) because the therapeutic function is
scaffolding / non-catalytic? The canonical case is RIPK1 — a kinase whose pathological signalling
is largely kinase-INDEPENDENT scaffolding, so an inhibitor and a degrader are not interchangeable.

This method emits `modality_implication_class` for a target by fusing two signals:
  1. CURATED override (target-contracts/vocabularies/domain_modality_targets.yaml) — the
     catalytic-independent / scaffolding biology the data cannot infer (RIPK1, STAT3, BRD4, ...).
     A curated entry takes PRECEDENCE and its mechanism_context is surfaced verbatim.
  2. CLASS-DRIVEN heuristic over the already-extracted protein_class + domain architecture, for
     everything not curated (a pure single-domain enzyme → inhibitor_sufficient; a non-enzyme /
     transcription-factor / multi-domain adhesion-receptor → removal_favored; etc.).

modality_implication_class:
  inhibitor_sufficient          — catalytic-site inhibition addresses the therapeutic function
                                  (single clean enzyme class; catalytic pocket is the point)
  removal_favored               — inhibition is partial; removal (degrader) engages more biology
                                  (multi-domain enzyme with interaction domains, or a non-enzyme)
  removal_required_scaffolding  — catalytic inhibition INSUFFICIENT; scaffolding/non-catalytic
                                  function dominates → degrader/disruptor needed (curated only)
  context_dependent             — mechanism depends on pathway/indication (curated only)
  data_unavailable              — no domain/class signal to reason from (coverage gap)

Additive / verdict-inert DISPLAY facet — informs the modality skills' LLM synthesis + reviewer;
fires no resolver rung.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

DEFAULT_TARGET_CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT",
                   "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))
VOCAB_RELPATH = "vocabularies/domain_modality_targets.yaml"

METHOD_VERSION = "0.1.0"

# protein_class values that are fundamentally CATALYTIC (a catalytic-site inhibitor has a target).
_ENZYME_CLASSES = {
    "kinase", "protease", "hydrolase", "transferase", "oxidoreductase",
    "lyase", "ligase", "isomerase",
}
# protein_class values with NO catalytic pocket — function is binding/scaffolding/regulatory, so
# catalytic inhibition is not the lever; removal (degrader/glue) is the natural modality.
_NONCATALYTIC_CLASSES = {
    "transcription_factor", "chromatin_regulator", "cell_adhesion",
    "receptor", "chaperone", "growth_factor", "cytokine",
}


@lru_cache(maxsize=1)
def _load_vocab(target_contracts_dir: str = None) -> dict:
    """Load the curated domain→modality vocabulary (entries keyed by HGNC symbol). {} on failure."""
    import yaml
    path = Path(target_contracts_dir or DEFAULT_TARGET_CONTRACTS) / VOCAB_RELPATH
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:  # noqa: BLE001 — curated layer is optional; degrade to heuristic-only
        return {}
    return data.get("entries", {}) or {}


def _uniprot_features(target: str) -> dict:
    """Read the domain-architecture summary (protein_class + domain names) for a target.
    Returns {} on any failure (heuristic then yields data_unavailable)."""
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        from methods.uniprot_protein_features.read import read_target_summary
        return read_target_summary(target) or {}
    except Exception:  # noqa: BLE001
        return {}


def _as_list(v):
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _heuristic_class(protein_class: list, features_class: Optional[str], n_domains: int,
                     has_any_domain: bool) -> str:
    """Class-driven modality implication for a NON-curated target.

    - a catalytic class present + single clean domain architecture → inhibitor_sufficient
      (the pocket is the therapeutic lever)
    - a catalytic class but MULTI-domain (extra interaction/regulatory domains) → removal_favored
      (inhibition is partial; the non-catalytic domains carry biology a degrader also removes)
    - a non-catalytic class (TF / chromatin / adhesion / receptor / chaperone) → removal_favored
      (no catalytic pocket to inhibit; removal is the natural lever)
    - nothing to reason from → data_unavailable
    """
    classes = {c.lower() for c in protein_class}
    if not classes and not has_any_domain:
        return "data_unavailable"
    is_enzyme = bool(classes & _ENZYME_CLASSES)
    is_noncatalytic = bool(classes & _NONCATALYTIC_CLASSES)
    if is_enzyme:
        # a single-domain enzyme is the clean inhibitor case; multi-domain enzymes carry
        # interaction/regulatory domains whose biology a degrader additionally removes.
        return "inhibitor_sufficient" if n_domains <= 1 else "removal_favored"
    if is_noncatalytic:
        return "removal_favored"
    # a class we don't map as enzyme/non-enzyme (transporter, ion_channel, ubiquitin_system, ...):
    # if it has domains but no catalytic class, lean removal_favored; else insufficient signal.
    if has_any_domain:
        return "removal_favored"
    return "data_unavailable"


def domain_modality_for_gene(target: str, target_contracts_dir: Optional[str] = None,
                             features: Optional[dict] = None, vocab: Optional[dict] = None) -> dict:
    """Per-target domain→modality implication. Curated override > class-driven heuristic.

    `features` / `vocab` may be injected for tests; production reads uniprot_protein_features +
    the curated YAML. DISPLAY facet, verdict-inert."""
    sym = (target or "").strip().upper()
    vocab = vocab if vocab is not None else _load_vocab(target_contracts_dir)
    curated = vocab.get(sym)

    feats = features if features is not None else _uniprot_features(sym)
    protein_class = _as_list(feats.get("protein_class"))
    n_domains = int(feats.get("n_domains") or 0)
    interpro_n = int(feats.get("interpro_n_domains") or 0)
    has_any_domain = n_domains > 0 or interpro_n > 0 or bool(feats.get("protein_features_class")
                                                             not in (None, "data_unavailable"))

    if curated is not None:
        klass = curated.get("preferred_mechanism", "context_dependent")
        return {
            "modality_implication_class": klass,
            "modality_implication_basis": "curated",
            "scaffolding_function": klass in ("removal_required_scaffolding", "removal_favored"),
            "protein_class": protein_class or _as_list(curated.get("protein_class")),
            "functional_domains": _as_list(curated.get("functional_domains")),
            "n_domains": n_domains,
            "modality_context": (curated.get("mechanism_context") or "").strip() or None,
            "_primary_source_doi": curated.get("primary_source_doi"),
            "method_version": METHOD_VERSION,
        }

    klass = _heuristic_class(protein_class, feats.get("protein_features_class"), n_domains,
                             has_any_domain)
    return {
        "modality_implication_class": klass,
        "modality_implication_basis": "heuristic" if klass != "data_unavailable" else "none",
        "scaffolding_function": None,   # heuristic does NOT assert scaffolding (curated-only claim)
        "protein_class": protein_class,
        "functional_domains": _as_list(feats.get("domain_names")) or _as_list(
            feats.get("interpro_domain_names")),
        "n_domains": n_domains,
        "modality_context": _heuristic_context(sym, klass, protein_class, n_domains),
        "method_version": METHOD_VERSION,
    }


def _heuristic_context(sym: str, klass: str, protein_class: list, n_domains: int) -> Optional[str]:
    pc = ", ".join(protein_class) if protein_class else "no mapped class"
    if klass == "inhibitor_sufficient":
        return (f"{sym}: single-domain {pc} — catalytic-site inhibition is the natural modality "
                f"(no curated scaffolding caveat). Class-driven heuristic; verify for known "
                f"kinase-independent functions.")
    if klass == "removal_favored":
        return (f"{sym}: {pc}{' (multi-domain)' if n_domains >= 2 else ''} — removal (degrader) "
                f"may engage more biology than catalytic inhibition. Class-driven heuristic; not a "
                f"curated scaffolding claim.")
    if klass == "data_unavailable":
        return None
    return f"{sym}: {klass} (class-driven heuristic)."
