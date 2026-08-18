"""moa_ontology — SIGNOR-mechanism → MoA-class classification table.

Every SIGNOR-tagged edge in OmniPath's interactions.tsv carries an `effect`
column (e.g. "phosphorylation", "binding", "gtpase-activating protein",
"transcriptional regulation"). This module maps each raw mechanism string
to a curated MoA class + modality-relevance tags, so the downstream
mechanism-and-pharmacology skill emits categorical rule-fireable signals
rather than raw text.

Ontology discipline:
  1. Every edge has ONE and only ONE MoA class (no overlap; no orphans).
  2. Unmapped mechanism strings log to `_unmapped_mechanisms.jsonl` in the
     run directory + increment a counter — a `test_signor_moa_ontology_coverage`
     verification test fails CI when >5% of edges are unmapped.
  3. Ontology version bumps IN THIS FILE when the table changes. Consumer
     cards emit `moa_ontology_version` in their summary_fields so target-
     profile downstream can trace which ontology snapshot fired.

Design note (why not adopt the raw SIGNOR mechanism strings verbatim?):
  Raw strings vary by capitalization, punctuation, and OmniPath-vs-SIGNOR
  edit history. A rule-engine consumer needs stable enum values it can
  match against, not free-text. The curated ontology also encodes
  modality-relevance (which MoA classes make what modality actionable) —
  post-hoc lens material that raw SIGNOR does not carry.

Consumer contract:
  from methods.signor_mechanism_network.moa_ontology import classify_edge

  moa_class, modality_relevance = classify_edge(mechanism_string, direction)
  # direction: 'upstream' | 'downstream' (relative to the target being profiled)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


ONTOLOGY_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Classification table.
#
# Each row: (mechanism_string_pattern, direction, moa_class, modality_relevance_tags)
#
# Pattern matching is case-insensitive exact match on the raw SIGNOR mechanism
# string. Free-text-similarity is NOT used — every SIGNOR mechanism string
# reaches this table verbatim, and unmapped strings fall through to the
# "unmapped" logger for curation follow-up.
# ---------------------------------------------------------------------------

# Upstream edges: something → target. The "something" is a candidate MoA hook.
UPSTREAM_ROWS = [
    # GAP / GEF: canonical Ras-family regulator mechanisms
    ("gtpase-activating protein", "upstream_gap_modulation",
     ("small_molecule_allosteric", "degrader")),
    ("guanine nucleotide exchange factor", "upstream_gef_modulation",
     ("small_molecule_allosteric", "degrader")),
    # Generic effect-derived fallback mechanisms (SIGNOR rows with empty
    # MECHANISM but is_stimulation/is_inhibition flags): treat as untyped
    # activity-regulation candidates for downstream reasoning.
    ("stimulation", "upstream_stimulator",
     ("small_molecule",)),
    ("inhibition", "upstream_inhibitor",
     ("small_molecule",)),
    # Direct binding: molecular glue / disruptor tractability
    ("binding", "molecular_glue_disruptor",
     ("small_molecule", "molecular_glue", "protac")),
    # Enzyme-mediated post-translational modifications
    ("phosphorylation", "upstream_kinase_modulation",
     ("small_molecule_kinase_inhibitor",)),
    ("dephosphorylation", "upstream_ppase_modulation",
     ("small_molecule",)),  # rarely tractable, kept for completeness
    ("ubiquitination", "upstream_ubl_modulation",
     ("molecular_glue", "dub_inhibitor")),
    ("deubiquitination", "upstream_dub_modulation",
     ("dub_inhibitor",)),
    ("methylation", "upstream_methyltransferase_modulation",
     ("small_molecule_epigenetic",)),
    ("acetylation", "upstream_hat_modulation",
     ("small_molecule_epigenetic",)),
    ("deacetylation", "upstream_hdac_modulation",
     ("small_molecule_hdac_inhibitor",)),
    # Cleavage: proteolytic activation / inactivation
    ("cleavage", "upstream_protease_modulation",
     ("small_molecule_protease_inhibitor",)),
    # Transcriptional / translational regulation upstream
    ("transcriptional regulation", "upstream_transcriptional_modulation",
     ("rna_therapeutic", "small_molecule_transcription_factor")),
    # CollecTri signed TF→target edges. Splits
    # generic "transcriptional regulation" into signed variants so
    # downstream reasoning can distinguish activator-loss (loss-of-function
    # target when the activating TF is drugged) from repressor-loss.
    ("transcriptional activation", "upstream_transcriptional_activator",
     ("rna_therapeutic", "small_molecule_transcription_factor")),
    ("transcriptional repression", "upstream_transcriptional_repressor",
     ("rna_therapeutic", "small_molecule_transcription_factor")),
    # Kinome-atlas PWM-derived predictions.
    # Distinct from curated `phosphorylation` — these are PREDICTIONS from
    # positional-scanning peptide-array PWMs (Johnson 2023 + Yaron-Barir
    # 2024 Nature). Downstream synthesis should weight lower than curated.
    ("predicted phosphorylation (ser_thr)", "upstream_predicted_kinase_modulation",
     ("small_molecule_kinase_inhibitor_predicted",)),
    ("predicted phosphorylation (tyr)", "upstream_predicted_kinase_modulation",
     ("small_molecule_kinase_inhibitor_predicted",)),
]

# Downstream edges: target → something. The "something" is a candidate PD marker.
DOWNSTREAM_ROWS = [
    ("binding", "downstream_pd_marker",
     ("pd_biomarker",)),
    # Generic effect-derived fallback (empty MECHANISM with is_stim/is_inh flag)
    ("stimulation", "downstream_activation_readout",
     ("pd_biomarker",)),
    ("inhibition", "downstream_repression_readout",
     ("pd_biomarker",)),
    ("phosphorylation", "downstream_pd_kinase",
     ("pd_biomarker_phospho",)),
    ("dephosphorylation", "downstream_pd_dephospho",
     ("pd_biomarker_phospho",)),
    ("ubiquitination", "downstream_pd_ubiquitin",
     ("pd_biomarker_ubiquitin",)),
    ("gtpase-activating protein", "downstream_pd_gap",
     ("pd_biomarker",)),
    ("guanine nucleotide exchange factor", "downstream_pd_gef",
     ("pd_biomarker",)),
    ("transcriptional regulation", "transcriptional_pd_marker",
     ("pd_biomarker_transcriptional", "rna_ihc_readout")),
    # CollecTri signed TF→target edges — when target
    # IS a TF acting on downstream genes, split signed variants for
    # PD-marker reasoning (rna_ihc_readout on activator target ≠ same on
    # repressor target).
    ("transcriptional activation", "downstream_transcriptional_activation_readout",
     ("pd_biomarker_transcriptional", "rna_ihc_readout")),
    ("transcriptional repression", "downstream_transcriptional_repression_readout",
     ("pd_biomarker_transcriptional", "rna_ihc_readout")),
    # Kinome-atlas PWM-derived downstream predictions.
    # Target-as-KINASE case: predicted substrates → phospho PD readouts.
    ("predicted phosphorylation (ser_thr)", "downstream_predicted_phospho_readout",
     ("pd_biomarker_phospho_predicted",)),
    ("predicted phosphorylation (tyr)", "downstream_predicted_phospho_readout",
     ("pd_biomarker_phospho_predicted",)),
    ("cleavage", "downstream_pd_cleavage",
     ("pd_biomarker",)),
    ("methylation", "downstream_pd_methylation",
     ("pd_biomarker_epigenetic",)),
]


@dataclass(frozen=True)
class MoAClassification:
    """Structured MoA classification for a single SIGNOR edge.

    Attributes:
        moa_class: Curated MoA class label. Categorical enum consumed by
            the rules engine.
        modality_relevance: Tuple of modality identifiers this MoA class is
            considered tractable for (e.g., ("small_molecule", "degrader")).
        raw_mechanism: The verbatim SIGNOR mechanism string; preserved for
            audit + downstream provenance.
        direction: 'upstream' or 'downstream' relative to the target.
        ontology_version: The MoA ontology version stamp; downstream cards
            emit this so consumers can trace which classification snapshot fired.
    """
    moa_class: str
    modality_relevance: tuple[str, ...]
    raw_mechanism: str
    direction: str
    ontology_version: str = ONTOLOGY_VERSION


def _build_lookup():
    lookup: dict[tuple[str, str], tuple[str, tuple[str, ...]]] = {}
    for mechanism, moa, mods in UPSTREAM_ROWS:
        lookup[(mechanism.lower().strip(), "upstream")] = (moa, tuple(mods))
    for mechanism, moa, mods in DOWNSTREAM_ROWS:
        lookup[(mechanism.lower().strip(), "downstream")] = (moa, tuple(mods))
    return lookup


_LOOKUP = _build_lookup()


def classify_edge(
    mechanism: str, direction: str
) -> Optional[MoAClassification]:
    """Classify one SIGNOR edge by (mechanism, direction).

    Args:
        mechanism: Raw SIGNOR mechanism string from OmniPath's interactions.tsv.
            Case-insensitive lookup; whitespace-trimmed.
        direction: 'upstream' (something → target) or 'downstream'
            (target → something). Case-insensitive.

    Returns:
        MoAClassification if the (mechanism, direction) pair is in the
        curated table. None if unmapped — the caller MUST log unmapped
        entries so the ontology can be extended.
    """
    if direction is None or mechanism is None:
        return None
    key = (mechanism.lower().strip(), direction.lower().strip())
    hit = _LOOKUP.get(key)
    if hit is None:
        return None
    moa_class, mods = hit
    return MoAClassification(
        moa_class=moa_class,
        modality_relevance=mods,
        raw_mechanism=mechanism,
        direction=direction,
    )


def known_moa_classes() -> set[str]:
    """Return the set of all MoA classes in the ontology.

    Useful for card summary_fields_vocabulary declarations and validators.
    """
    upstream = {row[1] for row in UPSTREAM_ROWS}
    downstream = {row[1] for row in DOWNSTREAM_ROWS}
    return upstream | downstream


def known_mechanisms(direction: Optional[str] = None) -> set[str]:
    """Return the set of raw SIGNOR mechanism strings the ontology covers.

    Useful for the ontology-coverage verification test to detect drift
    when upstream OmniPath adds new mechanism vocabulary.
    """
    if direction is None or direction.lower() == "upstream":
        u = {row[0].lower().strip() for row in UPSTREAM_ROWS}
    else:
        u = set()
    if direction is None or direction.lower() == "downstream":
        d = {row[0].lower().strip() for row in DOWNSTREAM_ROWS}
    else:
        d = set()
    return u | d
