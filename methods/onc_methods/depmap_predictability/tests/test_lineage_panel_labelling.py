"""The lineage panel must say what its parenthetical IS, and must not print one it cannot support.

A consumer reported on 2026-09-16: "I couldn't figure out what RF feature was displayed on the
by-lineage-predictability bar chart. If it is the top feature within an indication, own_hotspot should
have been the top feature for most lineages in the KRAS analysis." Both halves of that sentence are a
bug report:

  - the IDENTIFICATION half — the figure printed "0.11  (expr_KRT83)" with no legend, caption or axis
    note, and there are THREE different feature rankings in this card (global SHAP top-features,
    pred_dominant_feature, and a separate within-lineage RF refit). A reader could not tell which.
  - the CONTENT half — the value shown was in fact the argmax of an unpredictive refit (r²=0.108,
    below the r²=0.16 DepMap high-confidence floor THE SAME FIGURE DRAWS as a dashed line).

The producer-side fix lives in depmap_predictability_precompute and withholds top_feature below the
floor. But this reader gates on r² INDEPENDENTLY rather than trusting the new top_feature_status
field, and test_a_legacy_product_predating_the_status_field_is_still_rendered_honestly is why: every
product materialized before 2026-09-16 names a feature at every r² and has no status field at all.
Gating on r² here means those existing runs render honestly with no re-materialization.

INSTRUMENT NOTE (read before adding an assertion here): matplotlib's default svg.fonttype is 'path',
which converts text to glyph outlines and would make every "string not in svg" assertion below pass
VACUOUSLY. _load_takeda_palette sets it to 'none' so SVG text stays editable downstream. That is a
deliberate palette choice this test DEPENDS ON, so test_the_svg_text_instrument_is_not_vacuous pins it
as a precondition, and every absence assertion here is paired with a presence assertion in the same
figure.
"""

from __future__ import annotations

from onc_methods.depmap_predictability import cli as e5cli

FLOOR = e5cli.R2_LINEAGE_LABEL_FLOOR


def _summary(rows):
    return {"per_lineage_predictability": rows}


def _svg(rows, tmp_path, target="KRAS"):
    return e5cli.emit_lineage_conditional_panel(_summary(rows), target, tmp_path).read_text()


# --------------------------------------------------------------------------------------------------
# 0. The instrument itself
# --------------------------------------------------------------------------------------------------


def test_the_svg_text_instrument_is_not_vacuous(tmp_path):
    """Every absence assertion in this file is only meaningful if a PRESENT feature name is findable.

    Pin that directly. If the palette ever reverts svg.fonttype to matplotlib's 'path' default, this
    fails LOUDLY here instead of silently turning the rest of the file green-for-nothing.
    """
    import matplotlib

    txt = _svg([{"lineage": "Pancreas", "n_cell_lines": 45, "r2": 0.42, "top_feature": "own_mut_hotspot"}], tmp_path)
    assert matplotlib.rcParams["svg.fonttype"] == "none", (
        "the palette no longer keeps SVG text as text, so 'name not in svg' assertions are vacuous"
    )
    assert "own_mut_hotspot" in txt, "a feature name that IS rendered must be findable in the SVG source"


# --------------------------------------------------------------------------------------------------
# 1. Do not print an unsupportable feature name
# --------------------------------------------------------------------------------------------------


def test_a_feature_from_a_below_floor_refit_is_not_printed(tmp_path):
    """The exact consumer case: KRAS/Bowel, r²=0.108, top_feature=expr_KRT83."""
    txt = _svg(
        [
            {"lineage": "Bowel", "n_cell_lines": 88, "r2": 0.108, "top_feature": "expr_KRT83"},
            {"lineage": "Pancreas", "n_cell_lines": 45, "r2": 0.42, "top_feature": "own_mut_hotspot"},
        ],
        tmp_path,
    )
    assert "own_mut_hotspot" in txt, "the ABOVE-floor label must still render (else this test is vacuous)"
    assert "expr_KRT83" not in txt, (
        "a feature named by a refit at r²=0.108 — below the r²=0.16 floor this figure itself draws — "
        "is still being printed as if it were a finding"
    )


def test_a_withheld_label_is_shown_as_a_dash_not_silently_dropped(tmp_path):
    """A blank parenthetical would read as "no feature exists". An em dash reads as "not shown"."""
    txt = _svg([{"lineage": "Bowel", "n_cell_lines": 88, "r2": 0.108, "top_feature": "expr_KRT83"}], tmp_path)
    assert "0.11  (—)" in txt, "the withheld row must be visibly marked as withheld"


def test_a_legacy_product_predating_the_status_field_is_still_rendered_honestly(tmp_path):
    """The backward-compatibility claim, tested.

    Rows here carry NO top_feature_status key at all — the shape of every product materialized before
    2026-09-16. The reader must still withhold, which is only true because it gates on r² rather than
    on the status field.
    """
    rows = [
        {"lineage": "Bowel", "n_cell_lines": 88, "r2": 0.108, "top_feature": "expr_KRT83"},
        {"lineage": "Lung", "n_cell_lines": 111, "r2": 0.021, "top_feature": "expr_TAS2R46"},
        {"lineage": "Pancreas", "n_cell_lines": 45, "r2": 0.42, "top_feature": "own_mut_hotspot"},
    ]
    assert all("top_feature_status" not in r for r in rows), "fixture must model the LEGACY shape"
    txt = _svg(rows, tmp_path)
    assert "expr_KRT83" not in txt
    assert "expr_TAS2R46" not in txt
    assert "own_mut_hotspot" in txt


def test_a_null_top_feature_from_a_new_product_does_not_render_the_word_none(tmp_path):
    """The new producer writes top_feature=None below the floor. `f"({tf})"` on a None would print
    the literal string "None", which reads like a gene name."""
    txt = _svg(
        [
            {
                "lineage": "Bowel",
                "n_cell_lines": 88,
                "r2": 0.108,
                "top_feature": None,
                "top_feature_status": "withheld_r2_below_high_conf_floor",
            },
        ],
        tmp_path,
    )
    assert "(None)" not in txt and "(none)" not in txt
    assert "0.11  (—)" in txt


def test_a_feature_at_exactly_the_floor_is_printed(tmp_path):
    """Boundary direction: the floor is inclusive, matching >= in the producer's gate. Pinned because
    a silent flip to > would make the two sides of this fix disagree by one row."""
    txt = _svg([{"lineage": "Bowel", "n_cell_lines": 88, "r2": FLOOR, "top_feature": "own_mut_hotspot"}], tmp_path)
    assert "own_mut_hotspot" in txt


# --------------------------------------------------------------------------------------------------
# 2. Say what the parenthetical IS
# --------------------------------------------------------------------------------------------------


def test_the_figure_names_the_parenthetical_and_the_floor(tmp_path):
    """The identification half of the consumer's report.

    Three separate claims have to be legible from the figure ALONE, because that is what gets pasted
    into a deck: what the parenthetical is, that it is NOT the global dominant feature, and what the
    dashed line is.
    """
    txt = _svg(
        [
            {"lineage": "Bowel", "n_cell_lines": 88, "r2": 0.108, "top_feature": "expr_KRT83"},
            {"lineage": "Pancreas", "n_cell_lines": 45, "r2": 0.42, "top_feature": "own_mut_hotspot"},
        ],
        tmp_path,
    )
    assert "within-lineage" in txt, "the caption must say the parenthetical comes from a within-lineage refit"
    assert "NOT the global dominant feature" in txt, "it must rule out the ranking a reader would otherwise assume"
    assert "high-confidence floor" in txt, "the dashed line must be labelled"
    assert f"{FLOOR:g}" in txt, "the floor's numeric value must appear"


def test_the_caption_explains_the_dash(tmp_path):
    """An unexplained em dash is the same defect as an unexplained parenthetical."""
    txt = _svg([{"lineage": "Bowel", "n_cell_lines": 88, "r2": 0.108, "top_feature": "expr_KRT83"}], tmp_path)
    assert "withheld" in txt


# --------------------------------------------------------------------------------------------------
# 3. Do not regress the existing paths
# --------------------------------------------------------------------------------------------------


def test_an_all_below_floor_card_still_renders_every_row(tmp_path):
    """Withholding LABELS must not drop BARS — the r² values are real measurements and dropping the
    rows would misrepresent which lineages were evaluated. This is the KRAS shape: 13 of 14 below.
    """
    rows = [{"lineage": f"L{i}", "n_cell_lines": 30 + i, "r2": 0.01 * i, "top_feature": f"expr_N{i}"} for i in range(8)]
    txt = _svg(rows, tmp_path)
    for i in range(8):
        assert f"L{i}" in txt, f"lineage L{i} lost its bar"
        assert f"expr_N{i}" not in txt


def test_an_empty_lineage_list_still_renders(tmp_path):
    """Pre-existing graceful path, kept green."""
    out = e5cli.emit_lineage_conditional_panel(_summary([]), "GHOST", tmp_path)
    assert out.exists() and out.stat().st_size > 0
