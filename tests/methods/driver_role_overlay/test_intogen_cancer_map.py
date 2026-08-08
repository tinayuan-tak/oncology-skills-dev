"""Guards for INDICATION_TO_INTOGEN_CANCER — the framework-indication → IntOGen CANCER_TYPE map.

The 2026-08-08 genomic-alteration review found the map was built by GUESSING variant code names:
~10 phantom codes that don't exist in IntOGen (harmless-but-dead), and two that were phantom-ONLY
(`OV`→nothing, `LIHC`/`HC`→nothing) so ovarian + liver silently got ZERO indication-scoped driver
evidence while APPEARING mapped. It also missed IntOGen's literal `COADREAD` code and omitted SCLC.

test_all_codes_are_real is the durable guard (runs live against the IntOGen source when creds are
available; skips cleanly otherwise). The pure-function tests below pin the specific regressions so
they fail without S3 too.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.driver_role_overlay.read import INDICATION_TO_INTOGEN_CANCER as M  # noqa: E402


# ── regression pins (no S3) ──────────────────────────────────────────────────
def test_coadread_includes_the_literal_intogen_code():
    # BUG fixed 2026-08-08: IntOGen HAS a `COADREAD` code; the map used to omit it.
    assert "COADREAD" in M["COADREAD"]


def test_sclc_is_mapped():
    # BUG fixed 2026-08-08: SCLC was absent though IntOGen has an SCLC code (SCLC vertical is non-TCGA).
    assert M["SCLC"] == ("SCLC",)


def test_ovarian_maps_to_the_real_ovt_code_not_phantom_ov():
    # BUG fixed 2026-08-08: `OV` is NOT an IntOGen code → ovarian got zero evidence. Real code = OVT.
    assert M["OV"] == ("OVT",)


def test_liver_maps_to_real_hcc_not_phantom_lihc():
    # BUG fixed 2026-08-08: `LIHC`/`HC` are not IntOGen codes → liver got zero evidence. Real code = HCC.
    assert M["LIHC"] == ("HCC",)


def test_no_known_phantom_codes_remain():
    # codes confirmed ABSENT from IntOGen v2024-09-20 (must never be re-introduced by a guess)
    phantom = {"COREAD", "PDAC", "OV", "KIRC", "RCCC", "LIHC", "HC", "ST", "ESAD", "HNSCC"}
    used = {code for codes in M.values() for code in codes}
    assert not (used & phantom), f"phantom IntOGen codes re-introduced: {sorted(used & phantom)}"


# ── the durable guard: every mapped code exists in the real IntOGen source ───
def test_all_codes_are_real():
    """Every code in the map must be a real CANCER_TYPE in the IntOGen Compendium. Live-gated:
    skips if S3/creds are unavailable (mirrors the other live readers' test discipline)."""
    boto3 = pytest.importorskip("boto3")
    import io, zipfile, csv
    try:
        s3 = boto3.Session().client("s3")
        key = "data-catalog/sources/intogen/v2024-09-20/IntOGen-Drivers-20240920.zip"
        raw = s3.get_object(Bucket="onc-compbio", Key=key)["Body"].read()
    except Exception as e:  # noqa: BLE001 — no creds / no network → skip, not fail
        pytest.skip(f"IntOGen source unreachable ({type(e).__name__}); live map check skipped")
    z = zipfile.ZipFile(io.BytesIO(raw))
    name = [n for n in z.namelist() if n.endswith("Compendium_Cancer_Genes.tsv")][0]
    rows = csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8"), delimiter="\t")
    real = {r["CANCER_TYPE"] for r in rows}
    used = {code for codes in M.values() for code in codes}
    missing = used - real
    assert not missing, f"map references CANCER_TYPE codes absent from IntOGen: {sorted(missing)}"
