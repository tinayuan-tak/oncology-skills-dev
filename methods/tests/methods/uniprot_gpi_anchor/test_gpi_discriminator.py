"""Guard: the GPI discriminator is SPECIFIC — GPI-anchor LIPID note (or the 'Lipid-anchor, GPI-anchor'
subcellular phrase), NOT bare lipid-anchor. Pins that a synthetic NRAS-like block (cytoplasmic
S-farnesyl lipid-anchor, NO GPI) is NOT called GPI, while an MSLN-like block (GPI-anchor amidated
serine) IS. S3-free — build_payload reads a local DAT-format fixture."""

from __future__ import annotations

import gzip
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.uniprot_gpi_anchor.derive import build_payload  # noqa: E402

# Two synthetic SwissProt DAT entries: one GPI (MSLN-like), one cytoplasmic lipid-anchor (NRAS-like).
_FIXTURE = """\
ID   GPIPROT_HUMAN           Reviewed;         500 AA.
AC   Q000001;
GN   Name=GPIPROT;
CC   -!- SUBCELLULAR LOCATION: Cell membrane; Lipid-anchor, GPI-anchor.
FT   LIPID           500
FT                   /note="GPI-anchor amidated serine"
SQ   SEQUENCE   1 AA;
     M
//
ID   LIPIDCYT_HUMAN          Reviewed;         189 AA.
AC   Q000002;
GN   Name=LIPIDCYT;
CC   -!- SUBCELLULAR LOCATION: Cell membrane; Lipid-anchor; Cytoplasmic side.
FT   LIPID           186
FT                   /note="S-farnesyl cysteine"
SQ   SEQUENCE   1 AA;
     M
//
"""


def test_gpi_discriminator_specific(tmp_path):
    dat = tmp_path / "fix.dat.gz"
    with gzip.open(dat, "wt") as fh:
        fh.write(_FIXTURE)
    df = build_payload(local_dat=str(dat))
    acs = set(df["uniprot_ac"])
    assert "Q000001" in acs, "GPI-anchored entry (MSLN-like) must be detected"
    assert "Q000002" not in acs, "cytoplasmic lipid-anchor (NRAS-like) must NOT be called GPI"
    row = df[df["uniprot_ac"] == "Q000001"].iloc[0]
    assert row["is_gpi_anchored"] is True or row["is_gpi_anchored"] == True  # noqa: E712
    assert "GPI-anchor" in (row["gpi_lipid_note"] or "")
