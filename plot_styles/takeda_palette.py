"""Shared Takeda oncology framework plotting palette + helpers.

Every card method imports from here to ensure visual consistency across cards.
Combined with takeda_oncology.mplstyle (loaded via plt.style.use), this defines
the framework's complete visual identity.

Usage in a method CLI:
    from pathlib import Path
    import matplotlib.pyplot as plt
    import sys

    contracts_root = Path("/path/to/target-contracts")
    plt.style.use(contracts_root / "plot_styles" / "takeda_oncology.mplstyle")
    sys.path.insert(0, str(contracts_root / "plot_styles"))
    from takeda_palette import LINEAGE_COLORS, get_lineage_color, REFLINE_NEUTRAL
"""

from __future__ import annotations

# ===== Okabe-Ito 8-color palette (colorblind-safe; deuteranopia/protanopia compatible) =====
OKABE_ITO = [
    "#E69F00",   # orange
    "#56B4E9",   # sky blue
    "#009E73",   # bluish green
    "#F0E442",   # yellow
    "#0072B2",   # blue
    "#D55E00",   # vermillion
    "#CC79A7",   # reddish purple
    "#000000",   # black
]

# ===== Canonical lineage → fixed color map (consistency across all cards) =====
# Priority-anchor lineages get stable, distinctive colors matched to indication
# focus areas. Extended coverage handles the ~28 OncotreeLineage values seen in
# DepMap 26Q1 (was ~12 explicitly mapped; missing lineages collided on default grey).
# Colors chosen from Okabe-Ito + Tol Colorblind + ColorBrewer for colorblind safety.
LINEAGE_COLORS = {
    # ==== Tier-1: priority-indication anchors (Okabe-Ito, high-recognition) ====
    "Bowel": "#D55E00",              # vermillion — COADREAD anchor
    "Lung": "#E69F00",               # orange — NSCLC + SCLC (collapsed in OncotreeLineage)
    "Pancreas": "#009E73",           # bluish green — PDAC anchor
    "Esophagus/Stomach": "#CC79A7",  # reddish purple — GC anchor (canonical OncotreeLineage)
    "Breast": "#56B4E9",             # sky blue

    # ==== Tier-2: common cancer types (Tol-Bright / ColorBrewer accents) ====
    "Liver": "#88CCEE",              # light blue-teal
    "CNS/Brain": "#332288",          # dark indigo (distinct from any blue tier-1)
    "Skin": "#DDCC77",               # tan
    "Ovary/Fallopian Tube": "#AA4499", # magenta-purple
    "Prostate": "#117733",           # dark green (distinct from Pancreas' bluish-green)
    "Kidney": "#882255",             # burgundy
    "Lymphoid": "#44AA99",           # teal
    "Myeloid": "#999933",            # olive
    "Bladder/Urinary Tract": "#661100", # dark brown-red

    # ==== Tier-3: less-common but present in panels ====
    "Head and Neck": "#6699CC",       # dusty blue
    "Bone": "#CC6677",                # rose
    "Soft Tissue": "#DDDDDD",         # very light grey (distinguishable from default)
    "Cervix": "#994455",              # muted plum
    "Uterus": "#EE99AA",              # pink
    "Thyroid": "#004488",             # deep navy
    "Biliary Tract": "#AA7744",       # amber-brown
    "Pleura": "#77AADD",              # pale steel-blue
    "Eye": "#BBCC33",                 # yellow-green
    "Peripheral Nervous System": "#DDDD77", # pale yellow-olive
    "Fibroblast": "#B0B0B0",          # medium grey (fibroblast controls)
    "Testis": "#6B4C93",              # violet
    "Ampulla of Vater": "#7FCC97",    # sea foam
    "Vulva/Vagina": "#EEBBEE",        # light pink
    "Normal": "#000000",              # black (normal cell line reference — always visible)
    "Muscle": "#663333",              # muted mahogany
    "Adrenal Gland": "#DD8855",       # copper

    # ==== Legacy lowercase aliases (backward-compat for synthetic-lineage code paths) ====
    "colorectal": "#D55E00",
    "lung_nsclc": "#E69F00",
    "lung_sclc": "#0072B2",
    "pancreas": "#009E73",
    "gastric": "#CC79A7",
    "breast": "#56B4E9",
    "skin": "#DDCC77",
    "Stomach": "#CC79A7",             # bare "Stomach" kept as legacy; real data uses "Esophagus/Stomach"
}
LINEAGE_DEFAULT_COLOR = "#999999"   # grey — used only when explicit fallback requested

# Extended palette for hash-based deterministic assignment of un-mapped lineages
# (colorblind-friendly; visually distinguishable from tier-1/2/3 mapped colors).
_HASH_FALLBACK_PALETTE = [
    "#5C4D66", "#3F5A50", "#8A5A44", "#4B738C", "#6E4A6E",
    "#8E7B39", "#3E7B7E", "#7A5E4A", "#5B7A4A", "#7E4A5B",
    "#4A7A6E", "#6E5B4A", "#4A6E7A", "#7A6E4A", "#4A4A7A",
]

# ===== Reference-line styles for figure overlays =====
REFLINE_NEUTRAL = {
    "color": "#666666",
    "linestyle": "--",
    "linewidth": 1.0,
    "alpha": 0.7,
}
REFLINE_KILLER = {                  # for "this threshold kills the modality"
    "color": "#B22222",             # deep red
    "linestyle": "--",
    "linewidth": 1.5,
    "alpha": 0.9,
}
REFLINE_GOOD = {                    # for "this threshold supports the modality"
    "color": "#228B22",             # forest green
    "linestyle": ":",
    "linewidth": 1.5,
    "alpha": 0.9,
}
REFLINE_NOMINAL = {                 # neutral guideline (e.g., Chronos = 0)
    "color": "#999999",
    "linestyle": "-",
    "linewidth": 0.8,
    "alpha": 0.5,
}

# ===== Diverging color map for effect-size / log2FC visualizations =====
DIVERGING_CMAP = "RdBu_r"           # red-blue reversed; red=negative, blue=positive
# ===== Sequential color map for Chronos heatmaps =====
SEQUENTIAL_DEPENDENCY_CMAP = "viridis"


def get_lineage_color(lineage: str) -> str:
    """Look up the canonical color for a lineage.

    Fallback order:
      1. Explicit LINEAGE_COLORS mapping (~35 lineages, curated colorblind-safe).
      2. Deterministic hash into _HASH_FALLBACK_PALETTE (15 colors) — same lineage
         always gets the same color across cards + across runs, but colors are
         DISTINCT from tier-1/2/3 mapped anchors so mapped-vs-fallback lineages
         don't collide visually.
      3. LINEAGE_DEFAULT_COLOR only for null/empty/None inputs.

    Previously fell back straight to grey — that caused legend collisions when
    2+ unmapped lineages appeared in the same figure (all rendered as #999999).
    """
    if not lineage or not isinstance(lineage, str):
        return LINEAGE_DEFAULT_COLOR
    if lineage in LINEAGE_COLORS:
        return LINEAGE_COLORS[lineage]
    # Deterministic hash — stable across cards + across runs; distinct from anchors.
    # Use built-in hash() would be non-stable across Python runs (randomized in 3.3+),
    # so use a simple checksum for determinism.
    checksum = sum(ord(c) for c in lineage) % len(_HASH_FALLBACK_PALETTE)
    return _HASH_FALLBACK_PALETTE[checksum]


# ===== Standard figure sizes (inches) — Cell/Nature conventions =====
FIGSIZE_SINGLE_COLUMN = (3.5, 2.625)
FIGSIZE_SINGLE_COLUMN_TALL = (3.5, 4.0)
FIGSIZE_DOUBLE_COLUMN = (7.0, 3.5)
FIGSIZE_DOUBLE_COLUMN_TALL = (7.0, 5.0)
FIGSIZE_SQUARE = (3.5, 3.5)


# ===== Chronos thresholds (DepMap-published conventions, used as reference lines) =====
CHRONOS_STRONG_DEPENDENCY = -1.0    # "common essentials" cutoff per DepMap
CHRONOS_MODERATE_DEPENDENCY = -0.5
CHRONOS_NO_DEPENDENCY = 0.0


# ============================================================================
# VERDICT-STATUS LAYER (figure-redesign 2026-09-03)
# ----------------------------------------------------------------------------
# A RESERVED status palette + badge/takeaway helpers so every card figure can
# carry the verdict its card fired — sourced from the SAME fired_rules the
# narrative reads (see status_for_card), so figure status and written verdict
# are one fact and cannot drift.
#
# Discipline (matches ordinal_view + the dataviz "status is reserved" rule):
#   * Status color is RESERVED — never reused for a data series. Data marks keep
#     their identity colors (TUMOR_*/NORMAL_*/lineage); only the badge + verdict-
#     aligned reference lines carry status color.
#   * Status is NEVER color-alone — the badge always ships an icon AND a text
#     label, so it survives CVD / greyscale print / forced-colors.
#   * The signal vocabulary is the framework's own
#     (supportive / neutral / opposing / killer / insufficient / not_applicable).
# ============================================================================

# Canonical identity pair for tumor vs normal (promoted here so methods stop
# each hardcoding their own blue — the F2 "palette drift" fix).
TUMOR_FILL, TUMOR_LINE = "#1F4E79", "#0A2540"
NORMAL_FILL, NORMAL_LINE = "#A9C5DB", "#5B7F99"

# signal -> visual treatment. `fill` = badge background, `ink` = badge text/border,
# `icon` = a glyph present in DejaVu Sans (SVG keeps text-as-text), `label` = the
# reader-facing word. Hues validated against white; keep distinct from the diverging
# DATA ramp so a negative log2FC bar is never misread as a killer badge.
VERDICT_STATUS = {
    "supportive":     {"fill": "#1A7F5A", "ink": "#0E4A34", "icon": "●", "label": "SUPPORTS"},
    "neutral":        {"fill": "#5B7F99", "ink": "#33505F", "icon": "◐", "label": "NEUTRAL"},
    "opposing":       {"fill": "#C0603A", "ink": "#7A2C20", "icon": "▲", "label": "AGAINST"},
    "killer":         {"fill": "#B2182B", "ink": "#6B0F1A", "icon": "✕", "label": "KILLER"},
    "insufficient":   {"fill": "#9AA3AB", "ink": "#5A626A", "icon": "○", "label": "INSUFFICIENT"},
    "not_applicable": {"fill": "#C9CED3", "ink": "#7D8288", "icon": "–", "label": "N/A"},
    # context/descriptive figures with no fired rule — an honest "no call", not a grey killer.
    "context":        {"fill": "#EDEFF2", "ink": "#5A626A", "icon": "◇", "label": "CONTEXT"},
}

# Display precedence when a card fires several rules: a co-fired killer dominates a
# co-fired supportive (mirrors the ordinal-matrix cell rule); among positives the
# stronger signal shows; off-scale ranks lowest.
_STATUS_SEVERITY = {"killer": 4, "opposing": 3, "supportive": 2, "neutral": 1,
                    "insufficient": 0, "not_applicable": 0, "context": -1}

# Readable rule_id-suffix mnemonic → signal. This is the FALLBACK used when the
# caller cannot pass the rule contract's authoritative `signals:` object; the
# suffix convention is enforced across the presence/expression rule sets.
_RULE_SUFFIX_TO_SIGNAL = [
    ("-veto", "killer"), ("-killer", "killer"),
    ("-opposing", "opposing"), ("-against", "opposing"), ("-caution", "opposing"),
    ("-supportive", "supportive"), ("-support", "supportive"),
    ("-neutral", "neutral"), ("-informative", "neutral"),
    ("-insufficient", "insufficient"), ("-unmeasured", "insufficient"),
]


def resolve_status(signal):
    """One signal string -> its badge treatment dict (fill/ink/icon/label/signal).
    Unknown/None -> `context` (an honest no-call), never a fabricated negative."""
    key = signal if signal in VERDICT_STATUS else "context"
    return {"signal": key, **VERDICT_STATUS[key]}


def _signal_from_rule_id(rule_id):
    rid = (rule_id or "").lower()
    for suffix, sig in _RULE_SUFFIX_TO_SIGNAL:
        if rid.endswith(suffix) or suffix + "-" in rid or (suffix.strip("-") in rid.split("-")):
            return sig
    return None


def status_for_card(card_id, fired_rules, *, signal_by_rule_id=None, takeaway=None):
    """Derive one card's figure status from the SAME `fired_rules` the resolver produced.

    fired_rules: the run's fired-rule dicts (rule_id / card_id / dominant / rationale_summary...).
    signal_by_rule_id: optional {rule_id: signal} from the rule contracts' `signals:` (authoritative);
                       when absent, the rule_id suffix mnemonic is used (see _RULE_SUFFIX_TO_SIGNAL).
    takeaway: optional one-line caption the emitter supplies (usually data-derived, more informative
              than the truncated rule rationale).

    Returns the resolve_status() dict + {rule_id, takeaway}. No fired rule for the card -> `context`.
    """
    mine = [r for r in (fired_rules or []) if r.get("card_id") == card_id]
    if not mine:
        return {**resolve_status(None), "rule_id": None, "takeaway": takeaway}

    def sig_of(r):
        rid = r.get("rule_id")
        if signal_by_rule_id and rid in signal_by_rule_id:
            return signal_by_rule_id[rid]
        return r.get("signal") or _signal_from_rule_id(rid) or "neutral"

    # prefer the dominant rule(s); else all — then take the most-severe by display precedence.
    dominant = [r for r in mine if r.get("dominant")]
    pool = dominant or mine
    chosen = max(pool, key=lambda r: _STATUS_SEVERITY.get(sig_of(r), 0))
    st = resolve_status(sig_of(chosen))
    if takeaway is None:
        rs = (chosen.get("rationale_summary") or "").strip().rstrip("—-").strip()
        takeaway = (rs.split(". ")[0][:150] or None) if rs else None
    return {**st, "rule_id": chosen.get("rule_id"), "takeaway": takeaway}


# ============================================================================
# FIGURE ANNOTATION CONTRACT (unified style guide, 2026-09-03)
# ----------------------------------------------------------------------------
# WHERE + WHAT to annotate, one spec for every card figure. Every emitter builds
# a figure from these four slots and NOTHING else free-floating:
#
#   figure_title(fig, target, indication, view)   top-left, bold. Describes WHAT
#       the figure shows (a fixed `view` phrase per figure type) — NEVER the
#       conclusion/verdict. Formula: "{TARGET} in {INDICATION} — {view}" for an
#       indication-scoped figure; "{TARGET} — {view}" for a target-grain one.
#   provenance_tag(fig, text)   bottom-right, muted, small. The ONLY place the
#       dataset(s), version, and sample counts (n=) live. Lightly tagged.
#   takeaway(fig, text)   bottom-left, dark grey. One plain sentence of the key
#       quantitative finding. NO "Takeaway:" label — just the sentence.
#   axis_label(ax, which, concept, scale)   concept-first: the plain-language
#       concept is the label ("Expression"); the scale/measure ("log2 TPM+1") is
#       a small muted secondary line — never the long jargon string in the label.
#
# The VERDICT does NOT appear on the figure. The report/dashboard layer places
# the verdict badge (verdict_badge / status_for_card, below) BESIDE the figure
# when it composes — so a figure reads as clean evidence and the same figure can
# sit under different call framings without redrawing.
# ============================================================================

# muted ink tokens (text wears ink, never a series color — dataviz rule)
INK_PRIMARY, INK_SECONDARY, INK_MUTED = "#1F2429", "#33383D", "#8A8F94"


def figure_title(fig, target, indication, view, *, x=0.10, y=0.95, subtitle=None):
    """Consistent title: '{TARGET} in {INDICATION} — {view}' (or '{TARGET} — {view}' when indication
    is None). `view` describes WHAT is shown, not the conclusion. Optional muted `subtitle` line."""
    head = f"{target} in {indication} — {view}" if indication else f"{target} — {view}"
    fig.suptitle(head, x=x, ha="left", y=y, fontsize=12.5, weight="bold", color=INK_PRIMARY)
    if subtitle:
        fig.text(x, y - 0.058, subtitle, ha="left", va="top", fontsize=8, color=INK_SECONDARY)


def provenance_tag(fig, text, *, x=0.10, y=0.884):
    """Dataset + version (+ sample counts, where not annotated on the marks), lightly tagged as a
    muted line directly UNDER the title (top-left). Reads as the figure's source caption."""
    if not text:
        return
    fig.text(x, y, text, ha="left", va="top", fontsize=8, color=INK_MUTED)


def axis_label(ax, which, concept, scale=None):
    """Concept-first axis label: the plain-language CONCEPT is the primary label; the scale/measure is
    a small muted secondary line BELOW it (x) / further out (y). The concept uses the native axis
    label (auto-clears ticks); the scale is a POINTS-offset annotation past it — points (not axes
    fraction) so it sits correctly on a short/multi-panel axis too. `scale` None → concept only."""
    if which == "x":
        ax.set_xlabel(concept, fontsize=10.5, labelpad=6, color=INK_SECONDARY)
        if scale:
            ax.annotate(scale, xy=(0.5, 0), xytext=(0, -34), xycoords="axes fraction",
                        textcoords="offset points", ha="center", va="top",
                        fontsize=7.5, color=INK_MUTED, annotation_clip=False)
    else:
        ax.set_ylabel(concept, fontsize=10.5, labelpad=8, color=INK_SECONDARY)
        if scale:
            # offset past the concept label; -58pt clears wide y-tick labels (e.g. "29.0") so the
            # muted scale never overlaps the concept, while staying inside a ≥0.15 left margin.
            ax.annotate(scale, xy=(0, 0.5), xytext=(-58, 0), xycoords="axes fraction",
                        textcoords="offset points", ha="center", va="center", rotation=90,
                        fontsize=7.5, color=INK_MUTED, annotation_clip=False)


# ============================================================================
# figure_frame — the ONE place figure layout + spacing lives. Emitters use it so
# they never hand-set margins; every small adjustment (a margin, the takeaway y,
# the per-box n pattern) is fixed HERE and propagates to every figure at once.
# ============================================================================
from pathlib import Path as _Path

# kind -> figsize + margins. The tuned pilot spacing, defined ONCE. Bespoke figures may override any
# margin via kwargs, or pass make_ax=False and build their own gridspec (title/provenance/takeaway
# + save still apply on exit).
_FRAME_LAYOUT = {
    "single":  {"figsize": FIGSIZE_DOUBLE_COLUMN,          "top": 0.82, "bottom": 0.245, "left": 0.16, "right": 0.965},
    "scatter": {"figsize": FIGSIZE_DOUBLE_COLUMN,          "top": 0.82, "bottom": 0.245, "left": 0.16, "right": 0.965},
    "tall":    {"figsize": (FIGSIZE_DOUBLE_COLUMN[0], 4.4),"top": 0.78, "bottom": 0.220, "left": 0.16, "right": 0.965},
}
_STYLE_PATH = _Path(__file__).parent / "takeda_oncology.mplstyle"


class figure_frame:
    """Standard card-figure scaffold: owns figsize, margins, and the title / provenance / takeaway
    bands, so an emitter only draws data + names axes. All tuned spacing lives HERE (one definition).

        with figure_frame("EPCAM", "COADREAD", "tumor vs. normal expression", out_path=p,
                          provenance="TCGA … · recount3", takeaway="74% …", kind="single") as F:
            F.ax.boxplot(...); F.axis_label("x", "Expression", "log2(TPM + 1)")
            F.n_on_boxes([822, 669])                      # bottom-row first

    Clean exit → draws title/provenance/takeaway (central spacing) + saves the SVG + closes.
    Exception  → closes WITHOUT saving (no half-drawn artifact).
    make_ax=False → frame makes only the styled fig (caller adds its own gridspec, e.g. multi-panel);
    the title/provenance/takeaway + save still happen on exit. `indication=None` → target-grain title."""

    def __init__(self, target, indication, view, *, out_path, provenance=None, takeaway=None,
                 kind="single", make_ax=True, title_x=0.10, figsize=None,
                 top=None, bottom=None, left=None, right=None):
        self.target, self.indication, self.view = target, indication, view
        self.out_path = _Path(out_path)
        self.provenance_text, self.takeaway_text = provenance, takeaway
        self.title_x, self.make_ax = title_x, make_ax
        L = _FRAME_LAYOUT.get(kind, _FRAME_LAYOUT["single"])
        self._figsize = figsize or L["figsize"]
        self._m = {
            "top": L["top"] if top is None else top,
            "bottom": L["bottom"] if bottom is None else bottom,
            "left": L["left"] if left is None else left,
            "right": L["right"] if right is None else right,
        }
        self.fig = self.ax = None

    def __enter__(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        if _STYLE_PATH.exists():
            try:
                plt.style.use(str(_STYLE_PATH))
            except Exception:  # noqa: BLE001
                pass
        self.fig = plt.figure(figsize=self._figsize)
        self.fig.subplots_adjust(**self._m)
        if self.make_ax:
            self.ax = self.fig.add_subplot(111)
        return self

    def axis_label(self, which, concept, scale=None):
        axis_label(self.ax, which, concept, scale)

    def n_on_boxes(self, counts):
        """Annotate per-group n on a horizontal box/strip plot (row i sits at data-y i+1); `counts`
        bottom-row first. This is the captured 'n on the boxes' pattern for distribution figures."""
        for i, n in enumerate(counts):
            self.ax.annotate(f"n = {n}", xy=(0.012, i + 1 + 0.31), xycoords=("axes fraction", "data"),
                             ha="left", va="bottom", fontsize=7.5, color=INK_MUTED, zorder=4)

    def __exit__(self, exc_type, exc, tb):
        import matplotlib.pyplot as plt
        if exc_type is None:
            figure_title(self.fig, self.target, self.indication, self.view, x=self.title_x)
            provenance_tag(self.fig, self.provenance_text, x=self.title_x)
            takeaway(self.fig, self.takeaway_text, x=self.title_x)
            self.fig.savefig(self.out_path)
        plt.close(self.fig)
        return False


def verdict_badge(fig, status, *, loc="upper right", pad=0.012):
    """Reserved status badge (icon + LABEL, colored). REPORT/DASHBOARD-LAYER helper — it is NOT drawn
    on the card figure itself (the verdict is married to the figure at compose time). `context`/None
    renders a quiet grey tag."""
    if not status:
        return
    icon, label, fill, ink = status.get("icon", ""), status.get("label", ""), \
        status.get("fill", "#EDEFF2"), status.get("ink", "#5A626A")
    x, ha = (1 - pad, "right") if "right" in loc else (pad, "left")
    y, va = (1 - pad, "top") if "upper" in loc else (pad, "bottom")
    fig.text(x, y, f" {icon}  {label} ", ha=ha, va=va, fontsize=9, weight="bold",
             color="#FFFFFF" if status.get("signal") not in ("context", "not_applicable") else ink,
             bbox=dict(boxstyle="round,pad=0.45", facecolor=fill, edgecolor=ink, linewidth=1.0),
             zorder=1000)


def takeaway(fig, text, *, x=0.10):
    """The key quantitative finding, one plain sentence, bottom-left (wraps to figure width; never
    clips to a data coordinate). NO 'Takeaway:' label — just the sentence. A thin neutral rule marks
    it as a caption (the rule is NOT status-colored — the verdict lives in the report layer)."""
    if not text:
        return
    # bottom-most line (provenance now lives under the title), so it sits low with clear spacing.
    fig.text(x - 0.02, 0.026, "▎", ha="left", va="bottom", fontsize=11, color=INK_MUTED)
    fig.text(x, 0.028, text, ha="left", va="bottom", fontsize=8.5, color=INK_SECONDARY, wrap=True)


# back-compat alias (old name); prefer takeaway()
def takeaway_caption(fig, text, *, status=None):
    takeaway(fig, text)


# ---- plotly twins (keep the interactive figure in lockstep with the SVG) --------------------------
def plotly_verdict_badge(fig, status):
    """Add the same status badge to a plotly figure (paper-coords annotation + border)."""
    if not status:
        return fig
    signal = status.get("signal")
    txtcolor = "#FFFFFF" if signal not in ("context", "not_applicable") else status.get("ink")
    fig.add_annotation(x=1.0, y=1.12, xref="paper", yref="paper", xanchor="right", yanchor="top",
                       text=f"{status.get('icon','')}  <b>{status.get('label','')}</b>",
                       showarrow=False, font=dict(size=12, color=txtcolor),
                       bgcolor=status.get("fill"), bordercolor=status.get("ink"), borderwidth=1,
                       borderpad=4)
    return fig


def plotly_takeaway(fig, text, status=None):
    """Add the one-line takeaway under a plotly figure (paper-coords annotation)."""
    if not text:
        return fig
    fig.add_annotation(x=0.0, y=-0.22, xref="paper", yref="paper", xanchor="left", yanchor="top",
                       text=f"<b>Takeaway</b>  {text}", showarrow=False, align="left",
                       font=dict(size=11, color="#33383D"))
    return fig


# ===== Provenance text helper =====
def figure_metadata_block(card_id: str, framework_version: str,
                           target: str, indication: str,
                           generated_at: str) -> dict:
    """Return a small metadata dict for embedding into SVG <title>/<desc> for audit trail.
    Used by matplotlib via fig.suptitle or fig._suptitle, or via SVG post-processing."""
    return {
        "card_id": card_id,
        "framework_version": framework_version,
        "target": target,
        "indication": indication,
        "generated_at": generated_at,
    }
