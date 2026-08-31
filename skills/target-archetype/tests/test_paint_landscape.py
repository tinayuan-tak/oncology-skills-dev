"""Guards for the portfolio-landscape painter (offline analysis tool; DESCRIPTIVE, verdict-inert)."""
import importlib.util
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2]
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))
from _skills_common.archetype_core import Atlas   # noqa: E402

ATLAS = Path(__file__).resolve().parents[1] / "atlas" / "atlas.json"
PAINT = Path(__file__).resolve().parents[1] / "scripts" / "paint_landscape.py"


def _paint():
    spec = importlib.util.spec_from_file_location("paint_landscape", PAINT)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def test_portfolio_table_covers_corpus_with_soft_mixtures():
    atlas = Atlas.load(ATLAS)
    pl = _paint()
    rows = pl.portfolio_table(atlas)
    assert len(rows) == len(atlas.targets)
    anchor_labels = {a["label"] for a in atlas.anchors}
    for r in rows:
        assert r["dominant_phenotype"] in anchor_labels          # dominant is an anchor phenotype
        assert abs(sum(r["mixture"].values()) - 1.0) < 1e-2       # convex mixture
        assert 0.0 <= r["coverage"] <= 1.0
        assert isinstance(r["inconsistent"], bool)


def test_portfolio_dominant_is_biologically_sensible():
    atlas = Atlas.load(ATLAS)
    rows = {(r["target"], r["indication"]): r for r in _paint().portfolio_table(atlas)}
    # canonical anchors + a couple of well-known drivers land in the right phenotype
    assert rows[("KRAS", "COADREAD")]["dominant_phenotype"] == "snv_driver"
    assert rows[("VHL", "KIRC")]["dominant_phenotype"] == "tsg_loss"
    assert rows[("EPCAM", "COADREAD")]["dominant_phenotype"] == "expression_surface"


def test_extra_target_can_be_added():
    atlas = Atlas.load(ATLAS)
    pl = _paint()
    feat = {k: v for k, v in zip(atlas.feature_order, atlas.X[0]) if v is not None}
    rows = pl.portfolio_table(atlas, extra=[("NEWGENE", "LUAD", feat)])
    assert rows[-1]["target"] == "NEWGENE" and rows[-1]["dominant_phenotype"] is not None
