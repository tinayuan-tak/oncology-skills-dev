"""gdc_dr45_pancohort aggregator — manifest-driven per-aliquot MAF streaming.

Verifies (no S3, no real manifest): the tumor-only file filter, per-gene case-frequency with
case-level dedup, the hotspot rows, and the multi-disease-program guard (CPTAC-3 must raise).
Mocks _load_manifest_files + _stream_maf_genes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from methods.gdc_dr45_pancohort import aggregate as agg  # noqa: E402


def _fake_files():
    # 3 tumor aliquots across 2 CASES (c1 has two aliquots → must dedup to 1 case) + 1 normal (dropped).
    return [
        {
            "project_id": "ALCHEMIST-ALCH",
            "case_id": "c1",
            "path": "p/c1a.maf.gz",
            "description": "primary tumor sample",
        },
        {"project_id": "ALCHEMIST-ALCH", "case_id": "c1", "path": "p/c1b.maf.gz", "description": "ffpe tumor sample"},
        {"project_id": "ALCHEMIST-ALCH", "case_id": "c2", "path": "p/c2.maf.gz", "description": "primary tumor sample"},
    ]


# gene rows per file path: (gene, hgvs, variant_class)
_FILE_ROWS = {
    "p/c1a.maf.gz": [("KRAS", "p.G12C", "Missense_Mutation"), ("TP53", "p.R175H", "Missense_Mutation")],
    "p/c1b.maf.gz": [("KRAS", "p.G12C", "Missense_Mutation")],  # same case c1, same call → dedups
    "p/c2.maf.gz": [("KRAS", "p.G12V", "Missense_Mutation")],
}


def _patch(monkeypatch, files=None):
    # Keyword name mirrors the real signature (data_catalog_repo). The production call site passes
    # it positionally, so a stub with the wrong keyword name would go unnoticed until someone
    # switched to a keyword call — at which point the stub, not the code, is what breaks.
    monkeypatch.setattr(
        agg,
        "_load_manifest_files",
        lambda program, data_catalog_repo=None: files if files is not None else _fake_files(),
    )
    monkeypatch.setattr(agg, "_boto3_client", lambda: object())
    monkeypatch.setattr(agg, "ensure_aws_profile", lambda: None)

    def _fake_stream(s3, key):
        # key is DR45_S3_PREFIX/path → recover the path suffix
        for p, rows in _FILE_ROWS.items():
            if key.endswith(p):
                return rows
        return []

    monkeypatch.setattr(agg, "_stream_maf_genes", _fake_stream)


def test_aggregate_case_dedup_and_frequency(monkeypatch):
    _patch(monkeypatch)
    tbl = agg.aggregate_program("ALCHEMIST-ALCH").to_pylist()
    summary = {r["gene_symbol"]: r for r in tbl if r["hotspot_protein_change"] is None}
    # 2 distinct cases (c1 deduped from its 2 aliquots)
    assert summary["KRAS"]["n_samples_in_indication"] == 2
    # KRAS mutated in BOTH cases (c1 + c2) → freq 1.0; TP53 in only c1 → 0.5
    assert summary["KRAS"]["n_samples_mutated"] == 2 and summary["KRAS"]["overall_mutation_frequency"] == 1.0
    assert summary["TP53"]["n_samples_mutated"] == 1 and summary["TP53"]["overall_mutation_frequency"] == 0.5
    assert summary["KRAS"]["indication"] == "NSCLC"


def test_hotspot_rows_dedup_by_case(monkeypatch):
    _patch(monkeypatch)
    tbl = agg.aggregate_program("ALCHEMIST-ALCH").to_pylist()
    kras_hs = {
        r["hotspot_protein_change"]: r["hotspot_n_samples"]
        for r in tbl
        if r["gene_symbol"] == "KRAS" and r["hotspot_protein_change"]
    }
    # G12C in c1 (two aliquots → 1 case), G12V in c2
    assert kras_hs == {"p.G12C": 1, "p.G12V": 1}


def test_load_manifest_files_filters_tumor_and_program(tmp_path):
    """The tumor-only + program filter lives in _load_manifest_files (description-driven).
    Point it at a synthetic manifest via data_catalog_repo and verify a normal file + an
    off-program file are both dropped."""
    import yaml

    mdir = tmp_path / "manifests" / "sources"
    mdir.mkdir(parents=True)
    (mdir / "gdc-pancohort-somatic-dr45-0.yaml").write_text(
        yaml.safe_dump(
            {
                "files": [
                    {
                        "project_id": "ALCHEMIST-ALCH",
                        "case_id": "c1",
                        "path": "p/c1.maf.gz",
                        "description": "primary tumor sample",
                    },
                    {
                        "project_id": "ALCHEMIST-ALCH",
                        "case_id": "c9",
                        "path": "p/c9n.maf.gz",
                        "description": "blood derived normal",
                    },
                    {
                        "project_id": "OTHER-PROG",
                        "case_id": "x",
                        "path": "p/x.maf.gz",
                        "description": "primary tumor sample",
                    },
                ]
            }
        )
    )
    files = agg._load_manifest_files("ALCHEMIST-ALCH", data_catalog_repo=tmp_path)
    assert [f["case_id"] for f in files] == ["c1"]  # normal + off-program dropped


# ---------- the data-catalog root DEFAULT (previously zero test reach) ----------
#
# Every test above either monkeypatches _load_manifest_files outright or passes
# data_catalog_repo=tmp_path, so none of them ever evaluated the default. That is exactly how a
# Path.home()-anchored root survived the repo-wide portability sweeps here: the value existed, but
# nothing observed it. These four tests observe it.


DATA_CATALOG_SIBLING = REPO.parent / "rnd-computational-biology-oncology-data-catalog"
NOT_THE_CHECKOUT_PARENT = "/tmp/gdc-dr45-fake-home-not-the-checkout-parent"


def test_default_data_catalog_is_derived_from_the_checkout_not_home(monkeypatch):
    """A faked $HOME is the only falsification available: on a dev box Path.home() IS the checkout
    parent, so the old and new resolutions agree there and a local run cannot tell them apart.
    Under a $HOME that is NOT the checkout parent — the CI/runner condition — they diverge."""
    monkeypatch.delenv("DATA_CATALOG_ROOT", raising=False)
    monkeypatch.setenv("HOME", NOT_THE_CHECKOUT_PARENT)

    resolved = agg._default_data_catalog()

    assert resolved == DATA_CATALOG_SIBLING
    assert NOT_THE_CHECKOUT_PARENT not in str(resolved)


def test_default_data_catalog_honours_the_env_override(monkeypatch, tmp_path):
    """POSITIVE CONTROL for the test above. A path that does not move under a faked $HOME is also
    what "the function was never called" looks like, so prove the same resolution DOES move when
    DATA_CATALOG_ROOT names a root."""
    monkeypatch.setenv("DATA_CATALOG_ROOT", str(tmp_path))

    assert agg._default_data_catalog() == tmp_path


def test_default_data_catalog_falls_back_on_an_empty_env_value(monkeypatch):
    """An empty-but-set variable must fall back rather than resolve to Path("") — which is ".",
    the CWD, a wrong root that looks plausible in a log line. This is why the resolution uses `or`
    and not a two-arg os.environ.get(K, default)."""
    monkeypatch.setenv("DATA_CATALOG_ROOT", "")

    assert agg._default_data_catalog() == DATA_CATALOG_SIBLING


def test_load_manifest_files_opens_the_resolved_default(monkeypatch, tmp_path):
    """WIRING: the resolved default must be the path _load_manifest_files actually opens when the
    caller passes no repo — which is how aggregate_program() reaches it in a real run. The
    pre-existing filter test passes data_catalog_repo=tmp_path explicitly, so it can never catch a
    wrong default: it never lets the default be used."""
    import yaml

    mdir = tmp_path / "manifests" / "sources"
    mdir.mkdir(parents=True)
    (mdir / "gdc-pancohort-somatic-dr45-0.yaml").write_text(
        yaml.safe_dump(
            {
                "files": [
                    {
                        "project_id": "ALCHEMIST-ALCH",
                        "case_id": "c1",
                        "path": "p/c1.maf.gz",
                        "description": "primary tumor sample",
                    }
                ]
            }
        )
    )
    monkeypatch.setenv("DATA_CATALOG_ROOT", str(tmp_path))

    files = agg._load_manifest_files("ALCHEMIST-ALCH")  # no data_catalog_repo → default path taken

    assert [f["case_id"] for f in files] == ["c1"]


def test_multi_disease_program_raises():
    # CPTAC-3 is not in PROGRAM_TO_INDICATION (needs per-case disease join) → must raise, not guess.
    with pytest.raises(ValueError, match="per-case disease join"):
        agg._resolve_indication("CPTAC-3")
