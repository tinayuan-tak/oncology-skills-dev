"""First-class TYPED cross-source DEPENDENCE EDGES — the shared vocabulary a cross-source
integration claim uses to link two evidence sources by an explicit *relation*, rather than
encoding that relation implicitly in a bespoke per-claim `stance` string or a concordance-class name.

WHY THIS EXISTS (SK#1866, evidence-property architecture epic #1507, Arm B gap (a)):
The evidence-property PROTOTYPE claim graph (`evidence-property-prototype/preregistration.md` L88-96)
links sources with EXPLICIT relations tagged `[corroborates | contradicts | qualifies]`. In shipped
code that relation lived only implicitly — as `concordance_class` names (`coverage_concordant`,
`bulk_masks_low_coverage`, `rna_high_protein_low`, ...) and as `stance` strings in each claim's
`source_support` (`positive`, `concordant`, `qualifying`, `higher_rank`, `lower_rank`). There was NO
reusable typed edge object `{from_source, to_source, relation}` linking two source NODES. This module
is that first-class object + its closed relation vocabulary, so every L2b concordance claim can carry
its cross-source dependence as TYPED EDGES the same way, and NOT re-implement the mapping per claim.

THE RELATION VOCABULARY (closed set, the prototype's three tags):
  * ``corroborates`` — the two sources land on the SAME cross-source read: an independent source
    CONFIRMS the anchor (agreeing arms → high corroboration). The stronger, encouraging relation.
  * ``contradicts``  — the two sources make DIRECTLY OPPOSING categorical calls on the SAME shared
    property (one asserts the property, the other its negation — e.g. one platform measures the
    antigen ABSENT where another measures it PRESENT). A head-to-head conflict, not a caveat.
  * ``qualifies``    — a non-concordant refinement that is NOT a head-to-head negation: one source
    adds a caveat / limitation on a dimension the anchor is blind to, or reports a directional
    rank/masking split, TEMPERING the anchor without asserting its negation (e.g. single-cell LOW
    malignant coverage qualifying a broadly-present bulk read; MS-protein ranking below the RNA the
    transcript implies). The least-committal disagreement — informative, never nullifying.

DESIGN NOTE (why the shipped L2b concordance claims emit only ``corroborates`` / ``qualifies``):
the three tumor-presence L2b claims all integrate REFINEMENTS of an already-present target — a
concordant read corroborates; every non-concordant read the code models is framed by its own prose as
a QUALIFICATION ("not nullification", "tempering", "an RNA-only restriction to surface", the literal
`qualifying` stance), never as a present/absent negation. So ``qualifies`` is the faithful backing of
their existing non-concordant stance strings. ``contradicts`` is a first-class member of the
vocabulary reserved for a genuine present/absent opposition (a relation those three claim families do
not currently produce, but a future cross-source family — e.g. an IHC-absent vs RNA-present hard
conflict — would). It is exercised through the shared constructor here and its tests.

VERDICT-INERT: a dependence edge is PRESENTATION/provenance structure. It names no signal tier, is
never averaged into a claim, feeds no rule / resolver / veto / verdict. It is an ADDITIVE, richer
representation of the SAME dependence the `corroboration` tier and `source_support` already encode.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ── the closed relation vocabulary (the prototype's three tags) ──────────────────────────────────
CORROBORATES = "corroborates"
CONTRADICTS = "contradicts"
QUALIFIES = "qualifies"

# A closed set — the ONLY relations a typed dependence edge may carry. A frozenset so a consumer can
# validate membership without mutating it.
DEPENDENCE_RELATIONS = frozenset({CORROBORATES, CONTRADICTS, QUALIFIES})


@dataclass(frozen=True)
class DependenceEdge:
    """A first-class TYPED cross-source dependence edge: ``from_source`` bears ``relation`` toward
    ``to_source`` (read "from_source {corroborates|contradicts|qualifies} to_source"). ``basis`` is an
    optional short machine token naming the specific concordance-class / stance the edge was derived
    from, so the typed edge is strictly RICHER than the stance string it backs (no directional nuance
    lost). Immutable + hashable; ``as_dict()`` renders the JSON-serialisable presentation shape."""

    from_source: str
    to_source: str
    relation: str
    basis: Optional[str] = None

    def __post_init__(self) -> None:
        if self.relation not in DEPENDENCE_RELATIONS:
            raise ValueError(
                f"dependence-edge relation {self.relation!r} is not in the closed vocabulary "
                f"{sorted(DEPENDENCE_RELATIONS)}"
            )
        if not self.from_source or not self.to_source:
            raise ValueError("a dependence edge needs both a from_source and a to_source node id")

    def as_dict(self) -> dict:
        """The presentation shape: relation-typed edge between two source nodes. ``basis`` is omitted
        (not null) when absent so the shape stays minimal + byte-stable across the None case."""
        d = {
            "from_source": self.from_source,
            "to_source": self.to_source,
            "relation": self.relation,
        }
        if self.basis is not None:
            d["basis"] = self.basis
        return d


def dependence_edge(from_source: str, to_source: str, relation: str, *, basis: Optional[str] = None) -> dict:
    """Build ONE typed dependence edge as its JSON-serialisable dict. Validates ``relation`` against
    the closed vocabulary (raises on an unknown relation). The single constructor every L2b
    concordance claim routes through, so the mapping is centralised, never re-implemented per claim."""
    return DependenceEdge(from_source, to_source, relation, basis=basis).as_dict()


def concordance_relation(concordant: bool, *, opposed: bool = False) -> str:
    """Map a cross-source integration DISPOSITION to a typed dependence relation — the one place the
    concordance→relation semantics live, so the three L2b concordance functions share it rather than
    re-implementing it.

      * ``concordant``       → ``corroborates`` (the two sources land on the same read);
      * ``opposed``          → ``contradicts``  (a direct present/absent negation on the shared
                                property — the caller asserts a head-to-head conflict);
      * otherwise            → ``qualifies``    (a non-concordant refinement / directional split /
                                blind-dimension caveat that tempers but does not negate).

    ``opposed`` is only honoured when NOT concordant. No L2b *family fold* passes ``opposed=True``
    (their non-concordant classes are qualifications, per this module's design note) — but
    ``presence_claims._provider_call_corroboration`` is a live exception: it passes
    ``opposed=(concordance == "direction_discordant")`` and reaches ``contradicts`` for real on a
    provider/re-derived direction conflict. That edge currently has no reader (verify before relying
    on it); the flag also makes ``contradicts`` reachable for the tests."""
    if concordant:
        return CORROBORATES
    if opposed:
        return CONTRADICTS
    return QUALIFIES


def concordance_edge(
    from_source: str,
    to_source: str,
    *,
    concordant: bool,
    opposed: bool = False,
    basis: Optional[str] = None,
) -> dict:
    """Convenience: classify a cross-source disposition with :func:`concordance_relation` and build the
    typed edge in one call. The L2b concordance claims use this so the class→relation mapping is not
    duplicated at each call site."""
    return dependence_edge(from_source, to_source, concordance_relation(concordant, opposed=opposed), basis=basis)
