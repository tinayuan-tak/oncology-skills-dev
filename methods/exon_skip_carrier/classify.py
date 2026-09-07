"""exon_skip_carrier.classify — pure, source-agnostic carrier classifier.

The classification primitive, decoupled from any data source. Callers supply variant
observations as `VariantObs` (sample id + genomic locus + splice classification); the
classifier returns the set of samples carrying a registered exon-skip event.

Deterministic, no I/O — unit-testable against fixed rows. Live/build loaders (read.py)
adapt a specific MAF into VariantObs and delegate here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from .events import EXON_SKIP_EVENTS, ExonSkipEvent


@dataclass(frozen=True)
class VariantObs:
    sample_id: str
    chrom: str  # "chr7" or "7" — normalized on ingest
    pos: Optional[int]  # 1-based genomic start; None => cannot be windowed
    classification: str  # variant classification / consequence token (any case)


def _norm_chrom(c: str) -> str:
    c = (c or "").strip()
    return c if c.lower().startswith("chr") else f"chr{c}"


def _is_splice(classification: str, event: ExonSkipEvent) -> bool:
    """True if the classification token indicates a splice-disrupting variant for the event.
    Matches on membership of any comma/&-delimited sub-token (VEP compound consequences like
    'splice_acceptor_variant&coding_sequence_variant&intron_variant')."""
    if not classification:
        return False
    toks = classification.lower().replace("&", ",").replace("|", ",").split(",")
    toks = {t.strip() for t in toks}
    if toks & event.splice_classifications:
        return True
    # tolerate free-form 'Splice_Site'/'splice' style single tokens
    return any("splice" in t for t in toks)


def carriers_for_event(observations: Iterable[VariantObs], event_id: str) -> set:
    """Return the set of sample ids carrying `event_id`.

    A sample is a carrier iff it has >=1 observation that is (a) on the event's chromosome,
    (b) positioned INSIDE the event window, and (c) splice-classified for the event.

    Position is REQUIRED: an observation with pos=None is never a carrier (splice
    classification alone is not exon-specific). This is the deliberate design that keeps
    METex14 from over-calling distant MET splice sites — see events.py.
    """
    if event_id not in EXON_SKIP_EVENTS:
        raise KeyError(f"unknown exon-skip event: {event_id!r} (known: {sorted(EXON_SKIP_EVENTS)})")
    ev = EXON_SKIP_EVENTS[event_id]
    chrom = _norm_chrom(ev.chrom)
    out = set()
    for o in observations:
        if o.pos is None:
            continue
        if _norm_chrom(o.chrom) != chrom:
            continue
        if not (ev.window_start <= o.pos <= ev.window_end):
            continue
        if not _is_splice(o.classification, ev):
            continue
        out.add(o.sample_id)
    return out
