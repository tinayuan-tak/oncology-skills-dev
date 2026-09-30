"""#1577 item 2 — onsides_ade_class reaches a consumer (verdict-INERT).

`onsides-adverse-event-safety.onsides_ade_class` (the card's PRIMARY class) was read into the
headline dict at run.py but consumed by NOTHING downstream: absent from `_SYNTHESIS_FACET_KEYS`,
so the composed target-profile fan-out never saw it. This pins the fix — the key now reaches the
one consumer the brief scoped (`_SYNTHESIS_FACET_KEYS`) — without moving the verdict (the card
stays verdict-inert; only the facet projection changes).
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

sf = load_run_py(Path(__file__).resolve().parent.parent, "sf_onsides_ade_class")


def test_onsides_ade_class_registered_as_synthesis_facet():
    assert "onsides_ade_class" in sf._SYNTHESIS_FACET_KEYS


def test_onsides_ade_class_still_read_into_headline():
    # unchanged carve: still read at the headline site, not just newly added to the facet tuple.
    import inspect

    src = inspect.getsource(sf)
    assert '"onsides_ade_class": get_card_field(cards, "onsides-adverse-event-safety"' in src
