"""Card-board figure — every tumor-presence card bucketed under its claim (A/B/C/D) into the honest
ternary {signal / no-signal / not-measured} with a reliability channel. The 'what's contributing /
where are the gaps' view — the drill-down beneath the collapsed claim vector.

Honesty discipline: `no-signal` (measured negative) and `not-measured` (coverage gap) are DIFFERENT
facts and rendered distinctly (○ vs ▨) — collapsing them is the most common way presence readouts
mislead. Polarity is ROLE-AWARE: for a PRESENCE claim, expression present = signal; for a
NORMAL-TISSUE comparator the polarity FLIPS (expression present = liability ▲), so a green mark never
means 'high in normal tissue'. Reads only decision['cards'] + headline — deterministic, display-only.

Vocabulary matching is EXACT, per role, and total over the contracts-declared values; anything else
renders ? rather than borrowing a polarity. See the comment above _SIGNAL for the three failures that
bought that rule, and tests/test_presence_cardboard_figure.py for the gate that keeps it true.
"""

from __future__ import annotations

import json
from pathlib import Path

from _skills_common.figure_palette import esc as _esc
from _skills_common.presence_tiers import (  # single-source n-power buckets (#1742)
    POWER_HIGH_N,
    POWER_MODERATE_N,
    SUBGROUP_N_FLOOR,
)
from _skills_common.subtype_axis import SUBTYPE_DIFFERENTIAL_CLASSES, is_differential_axis

# card_id -> (claim, primary field, role). role: signal | reliability | comparator.
_SPEC = [
    ("tumor-rna-distribution", "A", "tumor_expression_class", "signal"),
    ("cellline-rna-distribution", "A", "expression_class", "signal"),
    ("cellline-protein-abundance", "A", "protein_expression_class", "signal"),
    ("tumor-rna-vs-adjacent", "B", "expression_call_class", "signal"),
    ("tumor-protein-abundance-cptac", "B", "protein_expression_class", "signal"),
    ("tumor-scrna-celltype-expression", "C", "sc_expression_class", "signal"),
    ("expression-purity-confound", "C", "purity_confound_class", "signal"),
    ("tumor-elevation-breadth", "D", "tumor_elevation_breadth_class", "signal"),
    ("tumor-rna-distribution-by-subtype", "D", "subtype_stratification_class", "signal"),
    ("rna-protein-concordance-tumor", "R", "rna_as_biomarker", "reliability"),
    ("normal-tissue-liability", "W", "normal_tissue_breadth_class", "comparator"),
    ("sc-normal-celltype-expression", "W", "sc_normal_expression_class", "comparator"),
]
_GROUP = {
    "A": "A · abundance",
    "B": "B · tumor-elevation",
    "C": "C · malignant-intrinsic",
    "D": "D · generality",
    "R": "reliability (RNA↔protein proxy)",
    "W": "normal-tissue comparators (window)",
}
# ── Vocabulary → bucket, keyed by EXACT declared value ────────────────────────────────────────────
# These were substring haystacks until 2026-09-15. Three ways that failed, all measured on the
# 504-package corpus against the contracts-declared vocabulary:
#   1. FALL-THROUGH — an unlisted token hit a terminal default. Each role had its own, pointing a
#      different way, so "the default" was never one thing (see _bucket). Largest instance by far:
#      subtype_axis_unavailable rendered ● favourable on 199 of 504 packages, i.e. the card most
#      often asserted a subtype result on exactly the packages that HAD no subtype axis.
#      That card (tumor-rna-distribution-by-subtype) is also the one target-contracts declares no
#      vocabulary for, so the parametrized gate cannot reach it — its tokens are pinned by name in
#      test_the_undeclared_subtype_vocabulary_is_covered instead. A field nothing declares is the
#      field most likely to fall through, which is the opposite of where a gate naturally looks.
#   2. COLLISION — `ns` (2 chars, a declared legacy key) is a substring of `tumor_intri`ns`ic`, and
#      _NO_SIGNAL was tested first, so an EXACT _SIGNAL member rendered ○ measured-negative on 17
#      packages. An explicitly-declared favourable token, inverted.
#   3. CASE — the token lists are lowercase and sc-normal-celltype-expression declares UPPERCASE, so
#      every one of its four values fell through to ▲ liability: ✓ was unreachable for that card and
#      the column was CONSTANT across all 504 packages. `HIGH_LIABILITY` was the sole uppercase token
#      here, i.e. the one value someone had already hit and patched in place without generalising.
# Membership is now exact, so a token that merely CONTAINS another cannot borrow its polarity, and a
# new contracts value lands in "unknown" (visible ?) rather than inheriting an optimistic default.
# The sibling reader skills/tumor-presence/scripts/run.py already keys this same vocabulary by exact
# dict lookup; this is convergence on that shape, not a new design.
_SIGNAL = frozenset(
    {
        "broadly_high",
        "broadly_moderate",
        "broadly_detected",
        "subset_high",
        "lineage_restricted",
        "sub_broad_detection",  # detected, lineage breadth UNTESTED — detection is still a signal
        "moderately_expressed",
        "strong_up",
        "modest_up",
        "strong_upregulation",
        "modest_upregulation",
        "malignant_broadly_detected",
        "malignant_subset_detected",
        "broadly_tumor_elevated",
        "multi_tumor_elevated",
        "single_tumor_elevated",
        "tumor_intrinsic",  # expression intrinsic to tumour cells — the favourable purity call
        "purity_independent",  # not explained by purity — also supportive; was a fall-through
        "subtype_enriched",
        "pan_subtype_uniform",
        "subtype_restricted",
        "subtype_restricted_with_window",  # restricted AND a clean normal window — the strongest form
        "subtype_differential",  # grouped with enriched/restricted as a positive selection signal
    }
)
_NO_SIGNAL = frozenset(
    {
        "broadly_low",
        "not_informative",
        "not_tumor_elevated",
        "microenvironment_dominant",
        "microenvironment_confounded",  # the read IS confounded — cautionary, was a fall-through → ●
        "not_detected",
        "not_significant",
        "small_effect",
        "strong_down",
        "modest_down",
        "modest_downregulation",
        "strong_downregulation",
        "downregulation",
        "sparsely",
        "ns",  # DECLARED legacy pre-split key (see run.py:884-893); exact-only, so no longer a trap
    }
)
# Tokens where the measurement COULD NOT BE MADE. These are not measured negatives, and this module's
# whole point is that ○ and ▨ are different facts (see the header). Routing them here also suppresses
# the reliability dots, which otherwise rate the confidence of a measurement that never happened. All
# four were previously read as measured values — the exact conflation named above.
#
# EVERY MEMBER IS VERIFIED AT A PRODUCER OR CONSUMER, NEVER FROM THE TOKEN'S NAME. That discipline is
# not decoration: a peer session measured the shape-based shortcut and it does not work. `no_*` matches
# 46 distinct class tokens across this framework, overwhelmingly SUBSTANTIVE measured negatives
# (no_interaction 502, no_extracellular_domain 375, no_recurrent_fusion 360), and `insufficient*`
# matches 11 and splits BOTH ways — insufficient_paired_samples abstains, while
# insufficient_amp_expr_rate (394) and insufficient_mutation_rate (246) are measured RATES BELOW A CUT.
# So a name cannot tell "we looked and found nothing" from "we could not look"; only a declaration can.
# Provenance per member:
#   insufficient_paired_samples  — _figure_emitters/_expression.py:732 groups it with None /
#                                  data_unavailable; independently measured as an abstention (40 pkgs).
#   insufficient_paired_tumors   — THREE consumers agree: tumor-presence/scripts/run.py:707 (the
#                                  sibling mirror, same field) falls it to "unmeasured" and comments
#                                  "→ ignorance (unknown_mass)"; surface-modality-fit/scripts/
#                                  orthogonality.py:47 lists it in _ABSTAIN; _expression.py:497 emits
#                                  no figure for it. Note that mirror's reliability default is
#                                  fail-CLOSED where _bucket's was fail-OPEN — this converges on the
#                                  safe direction rather than inventing one.
#   subtype_axis_unavailable     — the producer states the polarity in words, tp_facets_subtype.py:268:
#                                  "no shard for this indication (coverage gap), not a measured
#                                  negative"; presence_question_table.py:193 groups it likewise.
#   no_subtype_axis              — presence_question_table.py:193, same group, same field.
_NOT_MEASURED = frozenset(
    {
        "insufficient_paired_samples",
        "insufficient_paired_tumors",
        # subtype_stratification_class. The PRODUCER states this polarity itself, in the same terms as
        # this module's header — tp_facets_subtype.py:268: "subtype_axis_unavailable = no shard for
        # this indication (coverage gap), NOT a measured negative". It was the single largest instance
        # of the fall-through defect: 199 of 504 corpus packages rendered ● favourable for a value
        # whose name says the axis was unavailable. presence_question_table.py:193 already groups both
        # of these with data_unavailable for this exact field; this converges on that reading.
        "subtype_axis_unavailable",
        "no_subtype_axis",
    }
)
# Comparator polarity is FLIPPED: presence in normal tissue is a liability, absence is a clean
# window. Both cards' vocabularies are enumerated exactly, including the UPPERCASE one.
_COMPARATOR_LIABILITY = frozenset(
    {
        "broad_normal_expression",
        "moderate_normal_expression",  # moderate normal expression is still a liability
        "ubiquitous",
        "origin_tissue",
        "HIGH_LIABILITY",
        "MODERATE_LIABILITY",
    }
)
_COMPARATOR_CLEAN = frozenset(
    {
        "restricted_normal_expression",
        "not_detected_in_normal",
        "absent",
        "LOW_LIABILITY",  # was ▲ — the case bug; "low liability" is the clean call by name
        "NOT_EXPRESSED",  # was ▲ — likewise
    }
)
_RELIABILITY = {
    "adequate_proxy": "proxy_ok",
    "confirmed": "proxy_ok",
    "partial_proxy": "proxy_partial",
    "poor_proxy": "proxy_poor",
}
# glyph, colour, label — including the polarity-flipped comparator + reliability states.
_GLYPH = {
    "signal": ("●", "#2a78d6"),
    "no_signal": ("○", "#b8bcc2"),
    "not_measured": ("▨", "#c9ccd1"),
    "liability": ("▲", "#d03b3b"),
    "clean_window": ("✓", "#0ca30c"),
    "proxy_ok": ("◆", "#2a78d6"),
    "proxy_partial": ("◆", "#f0a030"),
    "proxy_poor": ("◆", "#d03b3b"),
    # A value this module's vocabulary does not enumerate. Matches the inline render-time fallback,
    # so an unknown bucket looks the same whether it is mapped here or defaulted downstream.
    "unknown": ("?", "#888"),
}
_RELDOT = {"high": 3, "moderate": 2, "low": 1}
# `subtype_stratification_class` values that assert a real cross-subtype DIFFERENTIAL (a positive
# selection handle). The set lives in `subtype_axis.SUBTYPE_DIFFERENTIAL_CLASSES` — one definition
# shared with the question table so the two display surfaces can never disagree (see that module and
# claude-oncology-skills#1553). Rendered as a favourable ● only on a `powered` axis (see the render
# loop); `pan_subtype_uniform` is deliberately absent — it is not a differential claim.
_SUBTYPE_DIFFERENTIAL_CLASSES = SUBTYPE_DIFFERENTIAL_CLASSES


def _bucket(val, role):
    """Map a card summary value to a display bucket by EXACT vocabulary membership.

    An unrecognised value returns "unknown" (rendered ?) for every role. That is deliberate and it
    is the point of the function: this used to be three substring cascades whose terminal defaults
    pointed three different ways — signal → "signal" (favourable), reliability → "proxy_partial"
    (middling), comparator → "liability" (alarming) — so what an unlisted token claimed depended on
    which column it landed in, and a token authored to assert nothing could render as a positive
    result. "unknown" asserts nothing in any direction. The gate in
    tests/test_presence_cardboard_figure.py makes it unreachable for every contracts-declared value,
    so it fires only on a vocabulary that has moved ahead of this map.
    """
    if val in (None, "data_unavailable", "") or val is False:
        return "not_measured"
    v = str(val)
    if v in _NOT_MEASURED:  # role-independent: a coverage gap is a gap in every column
        return "not_measured"
    if role == "comparator":
        if v in _COMPARATOR_LIABILITY:
            return "liability"
        if v in _COMPARATOR_CLEAN:
            return "clean_window"
        return "unknown"
    if role == "reliability":
        return _RELIABILITY.get(v, "unknown")
    if v in _NO_SIGNAL:
        return "no_signal"
    if v in _SIGNAL:
        return "signal"
    return "unknown"


def _subtype_axis_gated_bucket(cid, summary, val, bucket):
    """Downgrade a tumor-rna-distribution-by-subtype differential-class SIGNAL to `not_measured` when
    the subtype axis is not `powered`. Identity for every other card/value/bucket.

    `subtype_stratification_class` is derived from the MEASURED strata alone, so a single
    measured-enriched stratum in an `exploratory` (or weaker) family yields a differential class
    (subtype_enriched/restricted/differential) while `subtype_axis_quality` says the axis is not
    powered — a favourable ● SIGNAL for a hypothesis-grade axis. Route it to ▨ (a coverage/power gap,
    not a measured negative ○), matching _q4_subtype and the two reader consumers that already honor
    the grade (run.py:_subtype_layer_concordance, subgroup_derivation.py). Verdict-inert; display-only.
    """
    if (
        cid == "tumor-rna-distribution-by-subtype"
        and bucket == "signal"
        and val in _SUBTYPE_DIFFERENTIAL_CLASSES
        and not is_differential_axis((summary or {}).get("subtype_axis_quality"))
    ):
        return "not_measured"
    return bucket


def _reliability(cid, s, h):
    def bq(q, n=None):
        if not isinstance(q, (int, float)):
            return "low"
        # POWER_MODERATE_N here is a minimal-sample SANITY floor on calling a strongly-significant
        # q "high" — distinct from (though numerically equal to) the power-bucket moderate floor below.
        return "high" if (q < 1e-10 and (n is None or n >= POWER_MODERATE_N)) else "moderate" if q < 0.05 else "low"

    if cid == "tumor-rna-vs-adjacent":
        return bq(s.get("q_value"))
    if cid == "tumor-protein-abundance-cptac":
        return bq(s.get("protein_bh_q_value"), s.get("n_tumor_samples"))
    if cid == "tumor-scrna-celltype-expression":
        # #1742 SSOT: single-cell donor-group grain -> moderate at POWER_MODERATE_N (20).
        n = h.get("sc_n_donor_groups") or s.get("n_donor_groups")
        return (
            "high"
            if isinstance(n, int) and n >= POWER_HIGH_N
            else "moderate"
            if isinstance(n, int) and n >= POWER_MODERATE_N
            else "low"
        )
    if cid == "tumor-rna-distribution":
        # #1742 SSOT: bulk tumor-sample grain -> moderate at SUBGROUP_N_FLOOR (30), NOT 20.
        n = s.get("n_tumor_samples")
        return (
            "high"
            if isinstance(n, int) and n >= POWER_HIGH_N
            else "moderate"
            if isinstance(n, int) and n >= SUBGROUP_N_FLOOR
            else "low"
        )
    return "moderate"


def render_card_board_svg(cards: list, headline: dict, target: str, indication: str) -> str:
    by_id = {c["card_id"]: (c.get("summary") or {}) for c in (cards or [])}
    groups = {}
    for cid, claim, field, role in _SPEC:
        s = by_id.get(cid, {})
        val = s.get(field)
        b = _subtype_axis_gated_bucket(cid, s, val, _bucket(val, role))
        # No confidence rating on a measurement that did not happen, or on a value we cannot read.
        rel = "" if b in ("not_measured", "unknown") else _reliability(cid, s, headline)
        groups.setdefault(claim, []).append((cid, val, b, rel))
    order = [g for g in "ABCDRW" if g in groups]
    nrows = sum(len(groups[g]) for g in order)
    W = 540
    # +12 vs the original for a SECOND legend line: one line could not hold every glyph the figure
    # actually renders, and the omitted ones were ▲, ✓ and ?. ✓ is not a corner case — post-fix it is
    # drawn on 162 of 504 corpus packages (163 cells; 161 pre-fix, before LOW_LIABILITY stopped
    # rendering ▲). ? is drawn on 0 of 504 and is documented anyway: a glyph that should never appear
    # is exactly the one a reader needs the legend for on the day it does.
    H = 52 + len(order) * 20 + nrows * 18 + 24
    x0 = 14
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'font-family="Inter, Helvetica, Arial, sans-serif"><rect width="{W}" height="{H}" fill="#fff"/>',
        f'<text x="{x0}" y="18" font-size="13" font-weight="700" fill="#1a1a19">{_esc(target)} · {_esc(indication)} — card board</text>',
        f'<text x="{x0}" y="32" font-size="9.5" fill="#6b6f76">every card bucketed under its claim · '
        f"● signal  ○ no signal (measured neg)  ▨ not measured (gap)</text>",
        f'<text x="{x0}" y="43" font-size="9.5" fill="#6b6f76">'
        f"▲ normal-tissue liability  ✓ clean window  ? value outside the declared vocabulary</text>",
    ]
    y = 59
    for g in order:
        out.append(
            f'<text x="{x0}" y="{y + 10}" font-size="10" font-weight="700" fill="#6b6f76">{_esc(_GROUP[g])}</text>'
        )
        y += 18
        for cid, val, b, rel in groups[g]:
            glyph, col = _GLYPH.get(b, ("?", "#888"))
            out.append(f'<text x="{x0 + 10}" y="{y + 10}" font-size="12" fill="{col}">{glyph}</text>')
            out.append(f'<text x="{x0 + 26}" y="{y + 10}" font-size="10" fill="#1a1a19">{_esc(cid)}</text>')
            out.append(f'<text x="{x0 + 250}" y="{y + 10}" font-size="9.5" fill="#555">{_esc(val)}</text>')
            if rel:
                for j in range(3):
                    fill = col if j < _RELDOT.get(rel, 0) else "none"
                    out.append(
                        f'<circle cx="{x0 + 470 + j * 11}" cy="{y + 6}" r="3" fill="{fill}" stroke="#184f95" stroke-width="0.8"/>'
                    )
            y += 18
    out.append("</svg>")
    return "\n".join(out)


def emit_card_board_figure(decision: dict, figures_root) -> list:
    """Emit figure_card_board.{svg,json} — the per-card ternary grouped by claim. Additive /
    best-effort; returns [] when no cards are present."""
    cards = (decision or {}).get("cards") or []
    headline = (decision or {}).get("headline") or {}
    if not cards:
        return []
    figures_root = Path(figures_root)
    figures_root.mkdir(parents=True, exist_ok=True)
    target = decision.get("target", "")
    indication = decision.get("indication", "") or "pan-cancer"
    svg = figures_root / "figure_card_board.svg"
    js = figures_root / "card_board.json"
    # structured twin
    by_id = {c["card_id"]: (c.get("summary") or {}) for c in cards}
    board = {}
    for cid, claim, field, role in _SPEC:
        s = by_id.get(cid, {})
        val = s.get(field)
        b = _bucket(val, role)
        board.setdefault(claim, []).append(
            {
                "card": cid,
                "value": val,
                "bucket": b,
                "reliability": ("" if b in ("not_measured", "unknown") else _reliability(cid, s, headline)),
            }
        )
    svg.write_text(render_card_board_svg(cards, headline, target, indication), encoding="utf-8")
    js.write_text(json.dumps(board, indent=2, default=str), encoding="utf-8")
    return [svg, js]


__all__ = ["render_card_board_svg", "emit_card_board_figure"]
