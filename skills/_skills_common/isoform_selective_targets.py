"""isoform_selective_targets — consumer for the isoform-selective-targets vocabulary.

(2026-07-08): Any card or skill that emits
modality-relevant fields (surface topology, PTM sites, ADC/TCE letter grades,
ectodomain-length-derived features) should call `check_target(symbol)` before
emitting to determine whether the target has a clinically-dominant alternative
isoform that makes gene-level modality reasoning systematically wrong.

Vocabulary source of truth:
  target-contracts/vocabularies/isoform_selective_targets.yaml

Failure mode this addresses:
  A gene-symbol-keyed card can emit `adc_grade: A` for ERBB2 based on full-
  length HER2 ectodomain accessibility, but in a p95HER2-dominant gastric
  tumor, the ADC-relevant N-terminal ectodomain has been proteolytically shed.
  Documenting this in caveats does NOT prevent the wrong categorical from
  reaching target_profile.md.

Usage pattern (from a card dispatcher):

    from _skills_common.isoform_selective_targets import check_target

    warning = check_target(target_symbol)
    if warning is not None:
        summary["_isoform_selective_caveat"] = warning.caveat
        summary["_isoform_selective_severity"] = warning.warning_severity
        # Suppress lens-conditional letter grades
        summary.pop("adc_grade", None)
        summary.pop("tce_grade", None)
        # Include the caveat in warnings emitted by the compose-dashboard
        # validation pass:
        warnings.append({
            "warning_id": "isoform_selective_target_dominant_variant",
            "message": warning.formatted_message(target_symbol),
        })

The consumer chooses how to handle the warning (suppression vs annotation);
this module provides the vocabulary lookup + formatted-message helpers only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

# Canonical vocabulary location: <target-contracts root>/vocabularies/isoform_selective_targets.yaml.
# Overridable via the ISOFORM_SELECTIVE_TARGETS_YAML env var (tests + non-standard layouts).
_VOCAB_ENV_VAR = "ISOFORM_SELECTIVE_TARGETS_YAML"


@dataclass(frozen=True)
class IsoformWarning:
    """Structured warning for a target with a clinically-dominant alt isoform."""

    target_symbol: str
    dominant_isoform: str
    variant_type: str
    warning_severity: str  # "high" | "moderate" | "high_conditional"
    caveat: str
    warning_conditional_on: Optional[str]  # e.g. relapsed-post-CD19-therapy
    primary_source_doi: str
    primary_source_citation: str
    vocabulary_version: str
    oncotree_codes: tuple = ()  # indication-scope (vocab v1.1.0): OncoTree codes where the isoform dominates
    pan_applicable: bool = False  # entry's isoform axis is indication-agnostic (e.g. FGFR2 IIIb/IIIc pan-epithelial)
    modality_epitope_impact: str = ""  # mechanism (vocab v1.2.0): ectodomain_ablating | ectodomain_intact | neoepitope | resistance_acquired | ectodomain_isoform_specific | intracellular
    alt_isoform_dominant: bool = False  # dominance (vocab v1.3.0): is the epitope-ablating alt isoform the DOMINANT species? Only then is the hard fit_class suppression honest (see suppresses_fit_class). ERBB2 p95HER2 is a MINORITY fragment → false.

    def suppresses_fit_class(self, indication: Optional[str]) -> bool:
        """Should the biologics fit_class be HARD-SUPPRESSED to isoform_dependent_undefined?

        Requires ALL THREE: the isoform is clinically established IN THIS indication
        (applies_in_indication), it ABLATES the ectodomain epitope (suppresses_adc_epitope), AND it is
        the DOMINANT species (alt_isoform_dominant). A minority epitope-ablating fragment (p95HER2:
        ~30% HER2+ gastric, ~10-15% breast) leaves the dominant full-length antigen targetable — the
        gene-level fit STANDS with a high-severity caveat rather than being blanked to undefined (T-DXd
        is approved in HER2+ gastric). v1.3.0 dominance gate; below-suppression entries route to caveat."""
        return self.applies_in_indication(indication) and self.suppresses_adc_epitope() and self.alt_isoform_dominant

    def suppresses_adc_epitope(self) -> bool:
        """Does the dominant alt isoform ABLATE the extracellular antibody epitope? (2026-08-14 fix)

        Only an ectodomain-ablating isoform (p95HER2 — the N-terminal ectodomain is proteolytically
        removed) justifies blanking the biologics fit_class. Other in-context mechanisms leave the
        surface epitope targetable and must NOT suppress the verdict:
          ectodomain_intact  — isoform change is intracellular (METex14 juxtamembrane degron)
          neoepitope         — creates a targetable tumor-specific ectodomain (EGFRvIII / depatux-m)
          resistance_acquired— epitope loss is post-therapy acquired, not upfront (CD19 delΔex2)
          ectodomain_isoform_specific — antibody epitope is isoform-dependent (FGFR2 IIIb/IIIc)
          intracellular      — target is not a surface antigen at all (AR/BRAF/MDM2)
        BACKWARD-COMPATIBLE: an entry with no modality_epitope_impact (pre-v1.2.0 vocab) returns True —
        preserving the Stage-1 in-context always-suppress behavior, so either merge order is safe."""
        if not self.modality_epitope_impact:
            return True
        return self.modality_epitope_impact == "ectodomain_ablating"

    def applies_in_indication(self, indication: Optional[str]) -> bool:
        """Is the dominant alt isoform clinically established in THIS indication? (2026-08-14 fix)

        The modality-fit suppression should fire only where the isoform is the clinical reality — off-
        context (e.g. EGFRvIII outside GBM, METex14 outside NSCLC) the gene-level fit_class stands.
        BACKWARD-COMPATIBLE: an entry with no scope metadata (pre-v1.1.0 vocab) OR pan_applicable=True
        returns True — preserving the prior always-suppress behavior, so this is safe against either
        merge order (vocab-first or skills-first)."""
        if self.pan_applicable or not self.oncotree_codes:
            return True
        return str(indication or "").upper().strip() in {c.upper() for c in self.oncotree_codes}

    def formatted_message(self, template_target_ref: Optional[str] = None) -> str:
        """Human-readable message for downstream surfaces (warnings list,
        card panel, target-profile LLM synthesis prompt).
        """
        target = template_target_ref or self.target_symbol
        return (
            f"{target} has a clinically-dominant alternative isoform "
            f"({self.dominant_isoform}, variant type: {self.variant_type}). "
            f"{self.caveat.strip()} "
            f"See vocabularies/isoform_selective_targets.yaml "
            f"v{self.vocabulary_version} — citation: "
            f"{self.primary_source_citation.strip()} "
            f"(doi:{self.primary_source_doi})"
        )


def _resolve_vocab_path() -> Path:
    """Find the vocabulary YAML: ISOFORM_SELECTIVE_TARGETS_YAML env override, else the target-contracts
    root (TARGET_CONTRACTS_ROOT env, else the in-tree contracts/).

    N3-1 #2144 stage 4: was a repo-root walk onto the retired rnd-...-target-contracts geometry
    symlink + a Path.home() clone — which resolved on a dev box but NOT in a fresh CI checkout.
    """
    env = os.environ.get(_VOCAB_ENV_VAR)
    if env:
        return Path(env)
    from _skills_common.paths import target_contracts_root

    p = target_contracts_root() / "vocabularies" / "isoform_selective_targets.yaml"
    if p.exists():
        return p
    raise FileNotFoundError(
        f"isoform_selective_targets.yaml not found. Set {_VOCAB_ENV_VAR} or ensure it exists at "
        f"{p} (target-contracts root resolved via TARGET_CONTRACTS_ROOT / in-tree contracts/)."
    )


@lru_cache(maxsize=1)
def _load_vocabulary() -> dict:
    """Parse the vocabulary YAML once, cache in-process."""
    import yaml

    with _resolve_vocab_path().open() as f:
        vocab = yaml.safe_load(f)
    # (2026-07-09): reject entries: null explicitly. The prior shape
    # check `"entries" not in vocab` passes when entries exists with a null
    # value, and downstream .get(target) crashes with AttributeError.
    if not isinstance(vocab, dict) or not isinstance(vocab.get("entries"), dict):
        raise ValueError(
            f"isoform_selective_targets.yaml: malformed vocabulary — expected "
            f"top-level dict with non-null 'entries' mapping, got vocab type "
            f"{type(vocab).__name__} with entries type "
            f"{type(vocab.get('entries') if isinstance(vocab, dict) else None).__name__}"
        )
    return vocab


def vocabulary_version() -> str:
    """Return the vocabulary version string. Useful for provenance stamping."""
    return str(_load_vocabulary().get("version", "unknown"))


def known_targets() -> set[str]:
    """Return the set of HGNC symbols with a curated isoform-selective entry.
    Useful for tests + validators to check coverage.
    """
    return set((_load_vocabulary().get("entries") or {}).keys())


def check_target(target_symbol: str) -> Optional[IsoformWarning]:
    """Look up a target in the isoform-selective vocabulary.

    Args:
        target_symbol: HGNC gene symbol (case-sensitive; canonical uppercase)

    Returns:
        IsoformWarning if the target has a curated dominant-alt-isoform entry.
        None otherwise (the common case; ~20k HGNC symbols, ~10 entries here).
    """
    vocab = _load_vocabulary()
    entry = (vocab.get("entries") or {}).get(target_symbol)
    if entry is None:
        return None
    return IsoformWarning(
        target_symbol=target_symbol,
        dominant_isoform=str(entry.get("dominant_isoform", "unknown")),
        variant_type=str(entry.get("variant_type", "unknown")),
        warning_severity=str(entry.get("warning_severity", "moderate")),
        caveat=str(entry.get("caveat", "")).strip(),
        warning_conditional_on=entry.get("warning_conditional_on"),
        primary_source_doi=str(entry.get("primary_source_doi", "")),
        primary_source_citation=str(entry.get("primary_source_citation", "")).strip(),
        vocabulary_version=str(vocab.get("version", "unknown")),
        oncotree_codes=tuple(entry.get("oncotree_codes") or ()),
        pan_applicable=bool(entry.get("pan_applicable", False)),
        modality_epitope_impact=str(entry.get("modality_epitope_impact", "")),
        alt_isoform_dominant=bool(entry.get("alt_isoform_dominant", False)),
    )
