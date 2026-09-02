"""exon_skip_carrier — identify samples carrying a curated exon-skipping / splice-driver event.

The missing PRIMITIVE for biomarker-conditional splice drivers (CASE-002: MET exon-14
skipping / METex14). Exon-skipping events are invisible to the SNV/hotspot-centric genomics
and to the pan-line dependency distribution: METex14 is a ~3-4% splice-site subset of NSCLC,
so gene-level MET reads pan-line `non_dependent` despite being an approved TKI/ADC target.
This module classifies which SAMPLES carry the event, so a downstream consumer can stratify a
dependency / prevalence signal on carrier status.

Method:
  events.py    — curated registry (ExonSkipEvent): gene locus + genomic WINDOW + splice
                 classifications. Seeded with METex14 (hg38 chr7 window around exon 14).
  classify.py  — pure, source-agnostic classifier: a sample carries an event iff it has a
                 splice-classified variant positioned INSIDE the window (position REQUIRED —
                 splice classification alone over-calls distant splice sites).
  read.py      — DepMap live loader (streams the position-bearing raw somatic MAF; the derived
                 parquet drops coordinates) + a source-agnostic wrapper for MC3/GENIE.

Why a genomic window and not `effect=='splice_site' && exon==14`: the exon predicate cannot
run on DepMap (no exon column in its variant table) and splice classification alone is not
exon-specific. See events.py for the full rationale + validation against EBC-1/Hs746T.

METHOD_VERSION 0.1.0 — carrier classifier only. Verdict wiring (dependency stratification /
patient prevalence / resolver rung) lands as backtested follow-ups.
"""
from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .events import EXON_SKIP_EVENTS, ExonSkipEvent  # noqa: E402,F401
from .classify import VariantObs, carriers_for_event  # noqa: E402,F401
from .read import (  # noqa: E402,F401
    depmap_carriers, carriers_from_observations, exon_skip_landscape_summary,
)
