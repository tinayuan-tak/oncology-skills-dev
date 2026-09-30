"""#2261 — the classification cutoff must actually be drawn, not just corrected/relabelled (#2223).

`compute_summary` now carries the cross-protein cutoff that decided `protein_expression_class`
as `protein_high_abundance_class_cutoff`. The three figure emitters (`emit_density_protein`,
`emit_lineage_strip_protein`, `emit_plotly_specs`) must draw a reference line at exactly that
value, DISTINCT from `_panel_high_cutoff`'s within-target spread quantile.

The teeth: each test below re-derives the class cutoff from a synthetic all-protein null via the
real `compute_summary`, then asserts the emitter drew a line at that value. The mutant scenario
the acceptance criteria calls for — handing the emitter the WITHIN-TARGET quantile instead of the
class cutoff — is proven to actually red (not just assumed) by asserting the two values differ on
the fixture, so a wiring bug that draws `_panel_high_cutoff` where the class cutoff belongs cannot
pass silently.
"""

from __future__ import annotations

import matplotlib.axes as maxes
import pytest

from onc_methods.depmap_protein_abundance import cli
from onc_methods.roots import contracts_root

TARGET_CONTRACTS = contracts_root()

# A synthetic per-model abundance vector for the target, and an all-protein null with a clearly
# different center, so the class cutoff (all-protein p70) and the within-target p70
# (`_panel_high_cutoff`) land far apart on purpose — the two lines must be visibly distinguishable,
# not coincidentally equal.
_VALS = [float(v) for v in range(-10, 10)]  # target's own detected values, spread -10..9
_ABUNDANCE_BY_MODEL = {f"ACH-{i:04d}": v for i, v in enumerate(_VALS)}
_LINEAGE_BY_MODEL = {mid: "Lung" for mid in _ABUNDANCE_BY_MODEL}
# All-protein null centred near 0, so its p70 sits well inside the target's own range but far from
# the target's own within-target p70 (which sits near the top of _VALS).
_ALL_PROTEIN_MEDIANS = tuple(float(v) for v in range(-3, 4))  # p70 of this ~ 1.9


@pytest.fixture(scope="module")
def summary():
    return cli.compute_summary(
        "TP53",
        _ABUNDANCE_BY_MODEL,
        _LINEAGE_BY_MODEL,
        n_panel=len(_ABUNDANCE_BY_MODEL),
        all_protein_medians=_ALL_PROTEIN_MEDIANS,
    )


def test_summary_carries_the_class_cutoff_distinct_from_the_within_target_quantile(summary):
    """Anti-vacuity control: the two cutoffs must genuinely differ on this fixture, or a test that
    asserts "the drawn line equals the class cutoff" could pass even if the wrong value were wired
    in by coincidence."""
    class_cutoff = summary["protein_high_abundance_class_cutoff"]
    within_target = cli._panel_high_cutoff(_VALS)
    assert class_cutoff is not None
    assert class_cutoff == pytest.approx(cli._quantile(list(_ALL_PROTEIN_MEDIANS), cli.HIGH_ABUNDANCE_PERCENTILE))
    assert abs(class_cutoff - within_target) > 1.0, (
        f"fixture is not discriminating: class cutoff {class_cutoff} too close to the within-target "
        f"quantile {within_target}"
    )


def _spy_axvline(monkeypatch):
    drawn = []
    orig = maxes.Axes.axvline

    def spy(self, x=None, *a, **kw):
        drawn.append(x)
        return orig(self, x, *a, **kw)

    monkeypatch.setattr(maxes.Axes, "axvline", spy)
    return drawn


def test_emit_density_protein_draws_the_class_cutoff_line(tmp_path, monkeypatch, summary):
    pytest.importorskip("matplotlib")
    drawn = _spy_axvline(monkeypatch)
    cli.emit_density_protein(_ABUNDANCE_BY_MODEL, "TP53", summary, tmp_path, TARGET_CONTRACTS)
    class_cutoff = summary["protein_high_abundance_class_cutoff"]
    assert any(x == pytest.approx(class_cutoff) for x in drawn), (
        f"class cutoff {class_cutoff} was not drawn; lines drawn: {drawn}"
    )
    # the within-target spread line must ALSO still be drawn, and must be a DIFFERENT line from the
    # class cutoff (both present, not one masquerading as the other).
    within_target = cli._panel_high_cutoff(_VALS)
    assert any(x == pytest.approx(within_target) for x in drawn)


def test_emit_density_protein_MUTANT_within_target_quantile_in_place_of_class_cutoff_reds(
    tmp_path, monkeypatch, summary
):
    """Proves the assertion above has teeth: hand the emitter a summary whose
    `protein_high_abundance_class_cutoff` has been swapped for the within-target quantile (the exact
    #2223/#2261 confusion this issue fixes) and confirm the "line drawn equals the true class cutoff"
    check now reds."""
    pytest.importorskip("matplotlib")
    drawn = _spy_axvline(monkeypatch)
    true_class_cutoff = summary["protein_high_abundance_class_cutoff"]
    mutated = dict(summary)
    mutated["protein_high_abundance_class_cutoff"] = cli._panel_high_cutoff(_VALS)  # the wrong population
    cli.emit_density_protein(_ABUNDANCE_BY_MODEL, "TP53", mutated, tmp_path, TARGET_CONTRACTS)
    assert not any(x == pytest.approx(true_class_cutoff) for x in drawn), (
        "mutant should have drawn the within-target quantile in place of the true class cutoff, "
        "but the true class cutoff line still appeared — the test would not have caught the bug #2261 fixes"
    )


def test_emit_lineage_strip_protein_draws_the_class_cutoff_line(tmp_path, monkeypatch, summary):
    pytest.importorskip("matplotlib")
    # enough lines per lineage to clear MIN_LINEAGE_SIZE
    abundance = {f"ACH-{i:04d}": float(v) for i, v in enumerate(range(-10, 10))}
    lineage = {mid: "Lung" for mid in abundance}
    drawn = _spy_axvline(monkeypatch)
    cli.emit_lineage_strip_protein(abundance, lineage, "TP53", summary, tmp_path, TARGET_CONTRACTS)
    class_cutoff = summary["protein_high_abundance_class_cutoff"]
    assert any(x == pytest.approx(class_cutoff) for x in drawn), (
        f"class cutoff {class_cutoff} was not drawn in the lineage strip; lines drawn: {drawn}"
    )


def test_emit_plotly_specs_class_cutoff_line_present_and_correct(tmp_path, summary):
    pytest.importorskip("plotly")
    import json

    written = cli.emit_plotly_specs(_ABUNDANCE_BY_MODEL, _LINEAGE_BY_MODEL, "TP53", summary, tmp_path)
    assert written, "plotly emission produced nothing — cannot check its reference lines"
    class_cutoff = summary["protein_high_abundance_class_cutoff"]
    density_path = tmp_path / "figure_density_protein_abundance.plotly.json"
    assert density_path.exists()
    spec = json.loads(density_path.read_text())
    shapes = (spec.get("layout") or {}).get("shapes") or []
    line_x0s = [s.get("x0") for s in shapes if s.get("type") == "line"]
    assert any(x0 == pytest.approx(class_cutoff) for x0 in line_x0s), (
        f"class cutoff {class_cutoff} not found among the density figure's vline shapes {line_x0s}"
    )
    annotations = (spec.get("layout") or {}).get("annotations") or []
    ann_texts = " ".join(a.get("text", "") for a in annotations)
    assert "class cutoff" in ann_texts
    assert "all-protein p70" in ann_texts


def test_every_drawn_reference_line_names_its_population():
    """Static check on the emitters' own label strings (#2261 acceptance: 'every drawn reference
    line names the population it is a quantile of'). Guards against a future edit re-introducing a
    bare 'p70'/'median' label with no population noun."""
    import inspect

    src_density = inspect.getsource(cli.emit_density_protein)
    src_strip = inspect.getsource(cli.emit_lineage_strip_protein)
    src_plotly = inspect.getsource(cli.emit_plotly_specs)
    for src, name in ((src_density, "emit_density_protein"), (src_strip, "emit_lineage_strip_protein")):
        assert "target median" in src or "target p70" in src, name
        assert "class cutoff" in src, name
        assert "all-protein p70" in src, name
    assert "class cutoff" in src_plotly
    assert "target p70" in src_plotly
    assert "target median" in src_plotly
