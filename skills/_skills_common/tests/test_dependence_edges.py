"""Unit tests for the first-class typed cross-source DEPENDENCE-EDGE vocabulary (SK#1866, epic #1507
Arm B gap a): the closed {corroborates | contradicts | qualifies} relation set, the DependenceEdge
object, and the shared constructors the L2b concordance claims route through."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _skills_common.dependence_edges import (  # noqa: E402
    CONTRADICTS,
    CORROBORATES,
    DEPENDENCE_RELATIONS,
    QUALIFIES,
    DependenceEdge,
    concordance_edge,
    concordance_relation,
    dependence_edge,
)


def test_relation_vocabulary_is_the_prototypes_closed_three():
    # The vocabulary IS the prototype's three tags, no more, no fewer (a closed, immutable set).
    assert DEPENDENCE_RELATIONS == {"corroborates", "contradicts", "qualifies"}
    assert (CORROBORATES, CONTRADICTS, QUALIFIES) == ("corroborates", "contradicts", "qualifies")
    assert isinstance(DEPENDENCE_RELATIONS, frozenset)


def test_edge_renders_minimal_shape_and_omits_absent_basis():
    e = DependenceEdge("src_a", "src_b", CORROBORATES)
    assert e.as_dict() == {"from_source": "src_a", "to_source": "src_b", "relation": "corroborates"}
    # basis is OMITTED (not null) when absent, so the shape stays byte-stable across the None case.
    assert "basis" not in e.as_dict()


def test_edge_carries_basis_token_when_given():
    e = DependenceEdge("src_a", "src_b", QUALIFIES, basis="bulk_masks_low_coverage")
    assert e.as_dict() == {
        "from_source": "src_a",
        "to_source": "src_b",
        "relation": "qualifies",
        "basis": "bulk_masks_low_coverage",
    }


def test_edge_is_frozen_and_hashable():
    e = DependenceEdge("a", "b", CONTRADICTS)
    assert hash(e)  # hashable (frozen dataclass)
    with pytest.raises(Exception):
        e.relation = QUALIFIES  # type: ignore[misc]  # frozen → cannot mutate


@pytest.mark.parametrize("relation", sorted(DEPENDENCE_RELATIONS))
def test_dependence_edge_constructor_accepts_every_vocabulary_member(relation):
    d = dependence_edge("from_x", "to_y", relation)
    assert d["relation"] == relation
    assert d["from_source"] == "from_x" and d["to_source"] == "to_y"


def test_unknown_relation_is_rejected():
    with pytest.raises(ValueError, match="closed vocabulary"):
        dependence_edge("a", "b", "supports")  # not one of the three
    with pytest.raises(ValueError):
        DependenceEdge("a", "b", "agree")


def test_empty_endpoint_is_rejected():
    with pytest.raises(ValueError, match="from_source and a to_source"):
        dependence_edge("", "b", CORROBORATES)
    with pytest.raises(ValueError):
        dependence_edge("a", "", CORROBORATES)


def test_concordance_relation_maps_disposition_to_relation():
    # concordant → corroborates; a directly-opposed present/absent call → contradicts; anything else
    # (a non-concordant refinement / directional split) → qualifies.
    assert concordance_relation(True) == CORROBORATES
    assert concordance_relation(False) == QUALIFIES
    assert concordance_relation(False, opposed=True) == CONTRADICTS
    # `opposed` is only honoured when NOT concordant — a concordant read always corroborates.
    assert concordance_relation(True, opposed=True) == CORROBORATES


def test_concordance_edge_classifies_and_builds_in_one_call():
    assert concordance_edge("prot", "rna", concordant=True, basis="abundance_concordant") == {
        "from_source": "prot",
        "to_source": "rna",
        "relation": "corroborates",
        "basis": "abundance_concordant",
    }
    assert concordance_edge("sc", "bulk", concordant=False, basis="bulk_masks_low_coverage")["relation"] == "qualifies"
    # the contradicts path is reachable through the shared constructor (a present/absent conflict family).
    assert concordance_edge("ihc", "rna", concordant=False, opposed=True)["relation"] == "contradicts"
