"""Ordinal projection of the signal vocabulary — a labeled DISPLAY/RANKING VIEW (gap #3 "now").

WHAT THIS IS: a projection of the 6-value signal vocabulary
(supportive/opposing/killer/neutral/insufficient/not_applicable) onto an integer ordinal scale,
so the categorical evidence can be ORDERED and laid out as a matrix for human reading + ranking.

WHAT THIS IS NOT — and the honesty discipline that makes it safe (plan gap #3):
  * NOT calibrated measurement. The framework DELIBERATELY deleted a numeric score (ScholarEval)
    to force categorical-first honesty. This projection must never be presented as "quantitative
    scoring achieved". The integers preserve the ORDER (killer < opposing < neutral < supportive);
    the GAPS between them are NOT metric — a +2 is not "twice as good" as +1.
  * NOT a verdict input. This is a one-way VIEW over already-resolved signals. It must NEVER feed
    back into a rule, a resolver, a gate, or a nomination. Doing so would let a display artifact
    move a decision — exactly the hard-thresholding trap the categorical-first design avoids.
  * insufficient / not_applicable are OFF-SCALE (→ None), NOT a negative number. This is the
    framework's core measured-vs-null discipline: an ABSENCE of measurement is not a low score.
    Mapping insufficient to, say, -1 would let "we didn't look" masquerade as "we looked and it's
    mildly bad" and would corrupt any ranking. Off-scale cells are reported as coverage, not value.

Every public function stamps an explicit `_disclaimer` into its output so a downstream consumer
(or an LLM prompt) cannot lose the labeling.
"""

from __future__ import annotations

from typing import Optional

# Ordinal scale — ORDER-PRESERVING, not metric. killer is the most negative (it vetoes);
# supportive the most positive. insufficient / not_applicable are OFF-SCALE (absence, not value).
_ORDINAL: dict[str, Optional[int]] = {
    "supportive": 2,
    "neutral": 0,
    "opposing": -1,
    "killer": -3,  # strictly below opposing: a killer vetoes, an opposing signal only weakens
    "insufficient": None,  # OFF-SCALE — coverage gap, never a number
    "not_applicable": None,  # OFF-SCALE — not on this axis for this target/modality
}

_DISCLAIMER = (
    "ORDINAL VIEW — an order-preserving projection of categorical signals for display "
    "and ranking ONLY. NOT calibrated measurement (gaps between ranks are not metric); "
    "NOT a verdict input; insufficient/not_applicable are off-scale (coverage gaps, not "
    "low scores). The categorical signal is the source of truth."
)


def ordinal_of(signal: Optional[str]) -> Optional[int]:
    """Map one signal value to its ordinal, or None if off-scale / unknown. Unknown strings →
    None (never guessed) so a new vocabulary value can't silently acquire a fabricated rank."""
    if signal is None:
        return None
    return _ORDINAL.get(signal)


def project_signals(signal_by_key: dict) -> dict:
    """Project a {key -> signal_string} map onto ordinals. Returns a labeled VIEW:
      { "cells": { key: {"signal": s, "ordinal": int|None, "on_scale": bool} },
        "ordered": [keys sorted most-supportive → most-negative, off-scale last],
        "off_scale": [keys whose signal is insufficient/not_applicable/unknown],
        "_disclaimer": ... }
    `key` is caller-defined (e.g. a gate short, or a (gate, modality) tuple rendered as a string).
    Pure; does not mutate input; carries NO verdict.
    """
    cells: dict = {}
    off_scale: list = []
    for key, signal in signal_by_key.items():
        o = ordinal_of(signal)
        cells[key] = {"signal": signal, "ordinal": o, "on_scale": o is not None}
        if o is None:
            off_scale.append(key)
    # Rank on-scale cells high→low; off-scale cells trail (stable, by key) — they are NOT
    # ranked as "worst", they are simply not on the axis.
    on_scale_keys = [k for k in signal_by_key if cells[k]["ordinal"] is not None]
    ordered = sorted(on_scale_keys, key=lambda k: (-cells[k]["ordinal"], str(k))) + sorted(off_scale, key=str)
    return {
        "cells": cells,
        "ordered": ordered,
        "off_scale": sorted(off_scale, key=str),
        "_disclaimer": _DISCLAIMER,
    }


def scale_legend() -> dict:
    """The ordinal legend + disclaimer — for rendering a matrix key. On-scale values only;
    off-scale values are reported separately as coverage."""
    return {
        "on_scale": {k: v for k, v in _ORDINAL.items() if v is not None},
        "off_scale": [k for k, v in _ORDINAL.items() if v is None],
        "_disclaimer": _DISCLAIMER,
    }


def _cell_glyph(cell: dict) -> str:
    """Render one matrix cell: the signed ordinal for an on-scale signal, a `·` for a cell with
    no signal, or a short off-scale marker (insf / n/a) that is visibly NOT a number."""
    if cell.get("signal") is None:
        return "·"
    if cell.get("ordinal") is None:
        return {"insufficient": "insf", "not_applicable": "n/a"}.get(cell["signal"], "off")
    return f"{cell['ordinal']:+d}"


def render_matrix_md(matrix: dict, target: str, indication: str) -> str:
    """Render a gate × modality ordinal matrix (the shape target-profile's _ordinal_matrix emits)
    as portable GFM: a header disclaimer, the table, a legend, and an explicit note that the
    per-cell ordinal is a raw-signal DISPLAY value that can differ from the gate's resolved
    categorical verdict (the verdict, not the cell, is the decision)."""
    cols = matrix["axes"]["columns"]
    lines = [
        f"# Ordinal evidence matrix — {target} × {indication}",
        "",
        f"> **{matrix['_disclaimer']}**",
        "",
        "| gate (sub-skill) | " + " | ".join(cols) + " | resolved verdict |",
        "|" + "---|" * (len(cols) + 2),
    ]
    for row in matrix["rows"]:
        cells = row["cells"]
        glyphs = " | ".join(_cell_glyph(cells[m]) for m in cols)
        lines.append(f"| {row['short']} | {glyphs} | {row.get('verdict') or '—'} |")
    leg = matrix["legend"]
    on = ", ".join(f"{k}={v:+d}" for k, v in sorted(leg["on_scale"].items(), key=lambda t: -t[1]))
    lines += [
        "",
        f"**Scale (order-preserving, NOT metric):** {on}. "
        f"Off-scale (coverage, not a low score): {', '.join(leg['off_scale'])} "
        f"(shown `insf`/`n/a`); `·` = the gate emits no signal on that modality.",
        "",
        "**Why a cell can differ from the verdict:** a cell shows the *strongest raw signal* the "
        "gate's rules emit for that modality (a co-fired killer dominates a co-fired supportive). "
        "The *resolved verdict* is the gate's ordered-precedence outcome over all its fired rules. "
        "They legitimately differ — e.g. a paralog-buffering rule emits `small_molecule: opposing, "
        "degrader: supportive` (degrader-preferred), visible as a modality split in the row even "
        "when the verdict is a single positive. The verdict, not the cell, is the decision.",
    ]
    return "\n".join(lines) + "\n"
