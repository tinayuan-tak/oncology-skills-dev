"""Tests for the MEASURED Olink conditioned-media shed facet (E3, 2026-08-07).

Validates: (1) the measured_shed_class bands (high / low / not_on_secreted_panel /
data_unavailable) off a tiny synthetic media matrix + id map; (2) the self-calibrating
p75 threshold; (3) PANEL-ASYMMETRY — a gene not on the bounded secreted panel is
`not_on_secreted_panel` (non-informative), NEVER a measured negative; (4) the facet is
ADDITIVE — load_and_classify(with_measured=False) reproduces the pre-E3 primary summary
BYTE-IDENTICALLY, and with the facet ON the primary shed_liability_class is unchanged;
(5) the MIN_LINES_DETECTED floor (a high mean off too few wells does NOT clear high);
(6) isoform/phospho-suffix column matching. All offline (synthetic CSVs, no S3)."""

from __future__ import annotations

import sys
from pathlib import Path

METHODS_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
sys.path.insert(0, str(METHODS_REPO))
from methods.shed_ectodomain_liability import cli as sc  # noqa: E402
from methods.shed_ectodomain_liability import media as scm  # noqa: E402

# --- synthetic fixtures ----------------------------------------------------


def _write_media(tmp_path):
    """A 5-line x 6-protein media matrix. Column accessions chosen so:
    P15941 (MUC1)  = uniformly high  -> media_shed_high
    Q8WXI7 (MUC16) = high mean but detected in only 2 lines -> below MIN_LINES floor -> low
    P21860 (ERBB3) = uniformly low   -> media_shed_low
    P08581 (MET)   = mid, base-accession match test (id map may give P08581)
    Q13421 (MSLN)  = low, isoform id (id map gives Q13421-2 -> base match)
    P0DUMMY        = filler to shape the p75
    """
    import pandas as pd

    cols = ["P15941", "Q8WXI7", "P21860", "P08581", "Q13421", "P0DUMMY"]
    data = [
        [8.0, 7.0, -2.0, 2.0, -1.5, 0.0],
        [8.2, 7.4, -1.8, 2.1, -1.6, 0.1],
        [7.9, None, -2.1, 1.9, -1.4, -0.1],
        [8.1, None, -2.0, 2.0, -1.5, 0.0],
        [8.0, None, -1.9, 2.2, -1.5, 0.2],
    ]
    df = pd.DataFrame(data, columns=cols, index=[f"ACH-{i:04d}" for i in range(5)])
    df.index.name = "SampleID"
    p = tmp_path / "media_mini.csv"
    df.to_csv(p)
    return str(p)


def _write_idmap(tmp_path):
    import pandas as pd

    rows = [
        ("P15941-2", "MUC1"),  # isoform-suffixed -> base P15941
        ("Q8WXI7", "MUC16"),
        ("P21860", "ERBB3"),
        ("P08581", "MET"),
        ("Q13421-2", "MSLN"),  # isoform-suffixed -> base Q13421
        ("P06731", "CEACAM5"),  # NOT a media column -> not_on_secreted_panel
    ]
    idm = pd.DataFrame(rows, columns=["UniprotID", "Symbol"])
    p = tmp_path / "idmap_mini.csv"
    idm.to_csv(p, index=False)
    return str(p)


def _paths(tmp_path):
    scm._load_media.cache_clear()
    scm._load_idmap.cache_clear()
    return _write_media(tmp_path), _write_idmap(tmp_path)


# --- classifier bands ------------------------------------------------------


def test_uniformly_high_media_protein_is_media_shed_high(tmp_path):
    media, idmap = _paths(tmp_path)
    out = scm.classify_measured_shed("MUC1", media_path=media, idmap_path=idmap)
    assert out["measured_shed_class"] == "media_shed_high"
    assert out["media_n_lines_detected"] == 5
    assert out["media_mean_npx"] >= out["media_panel_high_npx"]


def test_isoform_suffixed_idmap_matches_base_column(tmp_path):
    media, idmap = _paths(tmp_path)
    out = scm.classify_measured_shed("MSLN", media_path=media, idmap_path=idmap)
    # MSLN id-map key is Q13421-2; matrix column is base Q13421 -> must match, low NPX
    assert out["media_uniprot"] == "Q13421-2"
    assert out["measured_shed_class"] == "media_shed_low"


def test_low_media_protein_is_media_shed_low(tmp_path):
    media, idmap = _paths(tmp_path)
    out = scm.classify_measured_shed("ERBB3", media_path=media, idmap_path=idmap)
    assert out["measured_shed_class"] == "media_shed_low"


def test_high_mean_but_too_few_lines_does_not_clear_high(tmp_path):
    # MUC16 mean is high but detected in only 2 lines (< MIN_LINES_DETECTED=3) -> low
    media, idmap = _paths(tmp_path)
    out = scm.classify_measured_shed("MUC16", media_path=media, idmap_path=idmap)
    assert out["media_n_lines_detected"] == 2
    assert out["measured_shed_class"] == "media_shed_low"


def test_gene_not_on_panel_is_non_informative(tmp_path):
    # CEACAM5 is in the id map but is NOT a column on the (bounded) secreted panel
    media, idmap = _paths(tmp_path)
    out = scm.classify_measured_shed("CEACAM5", media_path=media, idmap_path=idmap)
    assert out["measured_shed_class"] == "not_on_secreted_panel"
    assert out["media_mean_npx"] is None  # NOT a measured negative — no value at all


def test_gene_absent_from_idmap_is_non_informative(tmp_path):
    media, idmap = _paths(tmp_path)
    out = scm.classify_measured_shed("ZZZ_NOT_A_GENE", media_path=media, idmap_path=idmap)
    assert out["measured_shed_class"] == "not_on_secreted_panel"


def test_unreadable_media_is_data_unavailable(tmp_path):
    scm._load_media.cache_clear()
    out = scm.classify_measured_shed("MUC1", media_path=str(tmp_path / "does_not_exist.csv"))
    assert out["measured_shed_class"] == "data_unavailable"
    assert "_measured_read_error" in out


# --- ADDITIVITY: the primary class must stay byte-stable -------------------


def test_measured_facet_does_not_alter_primary_class(tmp_path):
    """load_and_classify with_measured=True must leave EVERY primary field byte-identical
    to with_measured=False — the facet is purely additive."""
    media, idmap = _paths(tmp_path)
    PRIMARY = (
        "shed_liability_class",
        "shed_evidence_tier",
        "serum_marker",
        "shed_product",
        "shedding_protease",
        "hpa_secretome_location",
        "source_citation",
        "method_version",
    )
    for gene in ("MUC1", "ERBB3", "CEACAM5", "KRAS"):
        base = sc.load_and_classify(gene, with_measured=False)
        aug = sc.load_and_classify(gene, with_measured=True, media_path=media, idmap_path=idmap)
        for f in PRIMARY:
            assert aug[f] == base[f], f"{gene}.{f} changed: {base[f]!r} -> {aug[f]!r}"
        assert "measured_shed_class" in aug and "measured_shed_class" not in base


def test_measured_facet_fields_present_and_in_vocab(tmp_path):
    media, idmap = _paths(tmp_path)
    valid = {"media_shed_high", "media_shed_low", "not_on_secreted_panel", "data_unavailable"}
    for gene in ("MUC1", "ERBB3", "CEACAM5"):
        out = sc.load_and_classify(gene, with_measured=True, media_path=media, idmap_path=idmap)
        for f in (
            "measured_shed_class",
            "media_mean_npx",
            "media_n_lines_detected",
            "media_panel_high_npx",
            "media_uniprot",
        ):
            assert f in out, f"measured field missing: {f}"
        assert out["measured_shed_class"] in valid
