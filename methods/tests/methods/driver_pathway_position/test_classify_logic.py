"""Pure-logic classification teeth for driver_pathway_position (no live data, runs in CI).

Monkeypatches the three cross-read seams (_load_membership_table, _frequently_altered,
_signor_summary, _reactome_summary) so every output class is pinned deterministically. These are the
real teeth: a mutation of the position logic (e.g. swapping the up/downstream SIGNOR semantics, or
dropping the honest-null discriminator) fails here, credential-less.
"""

from __future__ import annotations

import pandas as pd
import pytest

from onc_methods.driver_pathway_position import read as dpp

# A tiny synthetic Sanchez-Vega per-gene membership table. KRAS/BRAF/EGFR in RTK-RAS; APC in WNT;
# TP53 in TP53; MYSTERY in nothing.
_MEMBERSHIP = pd.DataFrame(
    [
        {"gene_symbol": "KRAS", "pathway": "RTK-RAS", "og_tsg_role": "OG", "mutsig_driver": True},
        {"gene_symbol": "BRAF", "pathway": "RTK-RAS", "og_tsg_role": "OG", "mutsig_driver": True},
        {"gene_symbol": "EGFR", "pathway": "RTK-RAS", "og_tsg_role": "OG", "mutsig_driver": True},
        {"gene_symbol": "APC", "pathway": "WNT", "og_tsg_role": "TSG", "mutsig_driver": True},
        {"gene_symbol": "TP53", "pathway": "TP53", "og_tsg_role": "TSG", "mutsig_driver": True},
    ]
)


@pytest.fixture
def patched(monkeypatch):
    def _set(freq_pathways, signor=None, reactome=None, membership=_MEMBERSHIP):
        monkeypatch.setattr(dpp, "_load_membership_table", lambda membership_path=None: membership)
        monkeypatch.setattr(
            dpp,
            "_frequently_altered",
            lambda target, indication: {
                "oncogenic_pathway_class": "frequently_altered" if freq_pathways else "profiled",
                "frequently_altered_pathways": list(freq_pathways),
            },
        )
        monkeypatch.setattr(
            dpp, "_signor_summary", lambda target: signor or {"upstream_regulators": [], "downstream_effectors": []}
        )
        monkeypatch.setattr(dpp, "_reactome_summary", lambda target: reactome or {"pathway_count": 0})

    return _set


def test_member_of_frequently_altered_pathway(patched):
    # KRAS in RTK-RAS, RTK-RAS frequently altered -> member (the acceptance case, offline).
    patched(freq_pathways=["RTK-RAS", "WNT", "TP53"])
    out = dpp.read_driver_pathway_position(target="KRAS", indication="COADREAD")
    assert out["driver_pathway_position_class"] == "member_of_frequently_altered_pathway"
    assert out["member_altered_pathways"] == ["RTK-RAS"]
    assert out["target_og_tsg_role"] == "OG"


def test_member_tolerates_pathway_name_punctuation_mismatch(patched):
    # REAL-DATA GUARD: the membership product spells it 'RTK-RAS' (hyphen) but the per-indication
    # alteration product spells the SAME pathway 'RTK RAS' (space). Compared verbatim the intersection
    # is empty and KRAS reads a FALSE downstream position; normalized, it is correctly a member.
    patched(freq_pathways=["RTK RAS", "WNT", "TP53"])  # space-spelled, as the alteration product emits
    out = dpp.read_driver_pathway_position(target="KRAS", indication="COADREAD")  # membership is 'RTK-RAS'
    assert out["driver_pathway_position_class"] == "member_of_frequently_altered_pathway"
    assert out["member_altered_pathways"] == ["RTK-RAS"]  # display keeps the membership product's spelling


def test_downstream_of_frequently_altered_pathway(patched):
    # Target not a member; a MEMBER of the altered pathway REGULATES it (upstream_regulators) -> downstream.
    patched(
        freq_pathways=["RTK-RAS"],
        signor={"upstream_regulators": [{"partner_gene_symbol": "KRAS"}], "downstream_effectors": []},
    )
    out = dpp.read_driver_pathway_position(target="MAPK1", indication="COADREAD")
    assert out["driver_pathway_position_class"] == "downstream_of_frequently_altered_pathway"
    assert out["upstream_altered_members"] == ["KRAS"]
    assert out["n_upstream_altered_members"] == 1


def test_upstream_of_frequently_altered_pathway(patched):
    # Target not a member; it REGULATES a member of the altered pathway (downstream_effectors) -> upstream.
    patched(
        freq_pathways=["RTK-RAS"],
        signor={"upstream_regulators": [], "downstream_effectors": [{"partner_gene_symbol": "BRAF"}]},
    )
    out = dpp.read_driver_pathway_position(target="SOS1", indication="COADREAD")
    assert out["driver_pathway_position_class"] == "upstream_of_frequently_altered_pathway"
    assert out["downstream_altered_members"] == ["BRAF"]


def test_pathway_not_frequently_altered_when_member_but_not_altered(patched):
    # TP53 has a Sanchez-Vega pathway, but TP53 is NOT in the frequently-altered set here.
    patched(freq_pathways=["RTK-RAS"])
    out = dpp.read_driver_pathway_position(target="TP53", indication="COADREAD")
    assert out["driver_pathway_position_class"] == "pathway_not_frequently_altered"


def test_pathway_not_frequently_altered_via_reactome(patched):
    # No Sanchez-Vega membership, no SIGNOR link, but Reactome shows a (non-oncogenic) pathway assignment.
    patched(freq_pathways=["RTK-RAS"], reactome={"pathway_count": 7})
    out = dpp.read_driver_pathway_position(target="MYSTERY", indication="COADREAD")
    assert out["driver_pathway_position_class"] == "pathway_not_frequently_altered"


def test_no_pathway_assignment_is_the_honest_null(patched):
    # No Sanchez-Vega membership, no SIGNOR link, no Reactome assignment -> honest null (NOT fabricated).
    patched(freq_pathways=["RTK-RAS"], reactome={"pathway_count": 0})
    out = dpp.read_driver_pathway_position(target="MYSTERY", indication="COADREAD")
    assert out["driver_pathway_position_class"] == "no_pathway_assignment"


def test_data_unavailable_when_indication_absent(monkeypatch):
    monkeypatch.setattr(dpp, "_load_membership_table", lambda membership_path=None: _MEMBERSHIP)
    monkeypatch.setattr(
        dpp, "_frequently_altered", lambda target, indication: {"oncogenic_pathway_class": "data_unavailable"}
    )
    out = dpp.read_driver_pathway_position(target="KRAS", indication="NOTACODE")
    assert out["driver_pathway_position_class"] == "data_unavailable"
    # even on data_unavailable, the target's membership is still reported honestly
    assert out["target_pathways"] == ["RTK-RAS"]


def test_data_unavailable_when_membership_product_absent(monkeypatch):
    monkeypatch.setattr(dpp, "_load_membership_table", lambda membership_path=None: None)
    out = dpp.read_driver_pathway_position(target="KRAS", indication="COADREAD")
    assert out["driver_pathway_position_class"] == "data_unavailable"


def test_requires_target_and_indication():
    assert (
        dpp.read_driver_pathway_position(target=None, indication="COADREAD")["driver_pathway_position_class"]
        == "data_unavailable"
    )
    assert (
        dpp.read_driver_pathway_position(target="KRAS", indication=None)["driver_pathway_position_class"]
        == "data_unavailable"
    )
