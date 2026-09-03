# Framework figure style guide

One contract for every card figure, so the whole figure set reads as one system and small
adjustments propagate from a single place. The rules here are **executable** — they live in
`takeda_palette.py` (`figure_frame` + helpers) and `takeda_oncology.mplstyle`. Build figures with
those; don't hand-set margins, colors, or fonts.

## How to build a figure

```python
import sys; sys.path.insert(0, "<target-contracts>/plot_styles")
import takeda_palette as pal

with pal.figure_frame(target, indication, view="tumor vs. normal expression",
                      out_path=svg_path, kind="single",
                      provenance="TCGA COADREAD tumor · GTEx Colon normal · recount3 / GENCODE v26",
                      takeaway="74% of COADREAD tumors express EPCAM above the normal 95th percentile.") as F:
    F.ax.boxplot(...)                       # draw the DATA (identity colors, see below)
    F.axis_label("x", "Expression", "log2(TPM + 1)")
    F.n_on_boxes([822, 669])                # distribution plots: n on the boxes, bottom-row first
```

`figure_frame` owns figsize, margins, and the title/provenance/takeaway bands, and saves the SVG on
clean exit. **Never set `subplots_adjust`, figsize, titles, or the takeaway/provenance placement in an
emitter** — change them in `_FRAME_LAYOUT` / the helpers so every figure moves together.

`kind`: `single` (horizontal box/strip, wide left gutter for group labels) · `scatter` (x+y concept
labels) · `tall` (multi-panel; pass `make_ax=False` and build your own gridspec — the frame still owns
title/provenance/takeaway + save). Override any margin via kwargs only for a genuine one-off.

## The four annotation slots — and nothing else free-floating

| Slot | Where | What | Rule |
|------|-------|------|------|
| **Title** | top-left, bold | `{TARGET} in {INDICATION} — {view}` (or `{TARGET} — {view}` for target-grain) | Describes **what the figure shows**, never the conclusion. **Be specific about the measurement type** — say "RNA" / "protein", not a bare "expression". No class tokens (`broadly_high`), no verdict. |
| **Provenance** | muted line under the title | dataset(s) + version (+ `n=` when not on the marks) | The source caption. Light, unobtrusive. |
| **Takeaway** | bottom-left | the key quantitative finding, one sentence | **No "Takeaway:" label** — just the sentence. Factual (a number), not a judgment. |
| **Axis label** | on the axis | concept primary + scale/measure muted secondary | `axis_label(ax, "x", "RNA Expression", "log2(TPM + 1)")`. Concept is plain + specific; the unit/scale is the small muted line — **below** the concept (x) or to the **right/inner** of it (y). |

## Sample counts (`n=`)

- **Distribution plots with per-sample values** (box / strip / violin): annotate `n=` **on/near each
  box** via `F.n_on_boxes([...])`. Keep it off the axis/tick labels and out of provenance.
- **Everything else** (scatter with a single paired count, bars, atlases): put `n=` in the
  **provenance** line.

## Color

- **Data marks use IDENTITY colors** from the palette — `TUMOR_*` / `NORMAL_*`, `get_lineage_color()`,
  sequential ramps for magnitude, the diverging map for signed effect sizes. Never hardcode a hex.
- **Verdict/status color is RESERVED** and does **NOT** go on the figure. The verdict is applied as a
  badge **beside** the figure by the report/dashboard layer (`verdict_badge` / `status_for_card` are
  report-layer helpers). A figure is clean evidence; the call is composed around it.
- Reference lines: `REFLINE_NEUTRAL` for an orientation marker; `REFLINE_GOOD` / `REFLINE_KILLER` only
  where a threshold genuinely helps/hurts. Don't let a red line imply "bad" on a neutral plot.

## Principles distilled from figure review

These generalize the per-figure feedback — apply them to every figure, not just the one that
prompted them.

1. **Show WHY the conclusion holds — put the driving metric on the plot.** The takeaway states a
   finding; the figure should carry the number(s) that produced it. A distribution → annotate the
   fraction-above-threshold + median that set the class (e.g. "expressed ≥1: 63%", "highly ≥5: 43%",
   median marker). A categorical/ladder → annotate the source metric that *decides* the category
   ("decided by HPA IHC call: 'Detected in many'"). Never make the reader take the takeaway on faith.

2. **No legend when the marks can be labeled directly.** ≤ ~3 reference lines / series → annotate each
   at the line (threshold lines get their label + value at the line; flag colors get direct labels).
   Reserve a legend box for genuinely un-labelable multi-series cases.

3. **In-plot stat annotations go in an EMPTY corner, never over the data.** For a positive-correlation
   scatter the bottom-right is clear (points ride the diagonal); pick the corner with no marks and
   confirm by eye. An annotation that overlaps points is a bug.

4. **Be specific and concise in labels.** Titles + axes name the exact measurement ("RNA Expression",
   "Protein Expression", "Tumor purity") — specific, but no jargon strings as the primary label (the
   unit/scale is the muted secondary line).

5. **Be honest about data limits — don't fabricate a scale.** If the source has no absolute
   High/Med/Low (e.g. HPA gives a *relative* enrichment score), say so on the axis and surface the
   qualitative call the data *does* provide (HPA specificity) rather than inventing bands.

6. **One message per figure — cut redundant views.** Two figures that carry the same message is one
   too many (the cell-line ranked waterfall was retired — the annotated density already showed the
   thresholds + shape; the per-lineage strip stayed because it adds a distinct dimension). Prefer
   annotating one figure over adding a second.

7. **Legibility: fonts sized for a slide, not a thumbnail.** Ticks ≥10, axis concept ~11.5, title
   ~12.5 (set centrally in the mplstyle + `axis_label`; don't override per figure).

## Do / don't

- ✅ concept-first + measurement-specific axes · ✅ `n` on boxes for distributions · ✅ one-sentence
  factual takeaway · ✅ the driving metric annotated on the plot · ✅ direct mark labels over a legend ·
  ✅ stat annotations in an empty corner · ✅ identity colors from the palette · ✅ `figure_frame` for layout.
- ❌ class tokens or the verdict in the title · ❌ a verdict badge drawn on the figure ·
  ❌ jargon axis strings as the primary label · ❌ a bare "expression" where "RNA"/"protein" is meant ·
  ❌ `n=` in axis labels · ❌ an annotation over the data · ❌ a fabricated High/Med/Low the source
  doesn't provide · ❌ two figures carrying the same message · ❌ hand-set margins/figsize/hex in an emitter.

Enforced by `tests/test_figure_frame_contract.py`.
