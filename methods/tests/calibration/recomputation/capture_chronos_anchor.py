"""LIVE capture tool for the depmap-chronos-distribution T3 recomputation anchor.

NOT collected by pytest (no ``test_`` prefix): it needs live DepMap 26Q1 (AWS ``cbg`` creds); the
committed sibling test ``test_chronos_distribution_recomputation.py`` is fully offline and reads only the
fixtures this tool writes.

What it freezes — the IRREPRODUCIBLE input: for each anchor gene, the per-cell-line Chronos gene-effect
vector (one column of the ~564 MB CRISPRGeneEffect matrix) plus each line's resolved OncotreeLineage.
That slice cannot be reconstructed offline. From it the tool re-derives the pan-cancer-crispr-dependency-
distribution card's summary fields through the REAL library entry point
``read_pan_cancer_distribution`` → ``compute_summary_stats`` and records them as the anchor's expected values.

Two independent guards make the anchor honest before it is committed:
  1. FIDELITY — the offline re-derivation (frozen slice, monkeypatched loaders) must reproduce the LIVE
     compute byte-for-byte; if the frozen lineage/slice loses information the classifier uses, it aborts.
  2. CROSS-REPO — for anchors the calibration roster already records (KRAS carries a full
     ``_crispr_provenance`` block), the re-derived provenance must equal that independently-captured
     record; a drift aborts rather than silently re-baselining.

Run:
    env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \
        PYTHONPATH=<analysis-methods-root> python3 <this file>
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
AM_ROOT = HERE.parents[2]
if str(AM_ROOT) not in sys.path:
    sys.path.insert(0, str(AM_ROOT))

import methods.depmap_chronos_distribution.cli as cli  # noqa: E402
import methods.depmap_chronos_distribution.read as rd  # noqa: E402

RELEASE_PIN = "26q1"
FIXTURE_REL = "chronos_vectors/depmap_26q1__chronos_panels.parquet"
ANCHOR_DIR = HERE / "anchors"

# Anchor genes. Seven are the functional-requirement calibration roster's own targets (so the gene choice
# is grounded in the committed roster, not invented); RPL3 is a canonical DepMap curated core-essential —
# the standard positive control for the pan-essential branch (the compute itself anchors that branch on
# AchillesCommonEssentialControls.csv), the same role the off-roster CD3D negative anchor plays for pooled
# SNV recurrence. The set is designed to span >= 3 dependency_class branches (selective / non-dependent /
# common-essential); the actual classes are whatever the real compute returns and are asserted non-vacuous
# below, never assumed.
ANCHOR_GENES = ["KRAS", "CTNNB1", "MET", "TEAD1", "WWTR1", "SMARCA2", "EPAS1", "RPL3"]
ROSTER_INDICATION = {
    "KRAS": "COADREAD",
    "CTNNB1": "COADREAD",
    "MET": "LUAD",
    "TEAD1": "MESO",
    "WWTR1": "MESO",
    "SMARCA2": "LUAD",
    "EPAS1": "RCC",
    "RPL3": None,  # off-roster core-essential control
}
CONTRACTS_ROOT = AM_ROOT.parent / "rnd-computational-biology-oncology-target-contracts"
SNAPSHOT_DIR = CONTRACTS_ROOT / "tests" / "calibration" / "snapshots"

# The fields this anchor re-derives (all produced by compute_summary_stats).
_FIELDS = (
    "n_cell_lines_evaluated",
    "median_chronos_panel",
    "fraction_strongly_dependent",
    "dependency_class",
    "distribution_shape",
)


def _resolve_lineage(meta_row: dict) -> str:
    """The lineage compute_summary_stats actually groups on: OncotreeLineage, else lineage, else
    PrimaryDisease, else 'unknown'. Freeze the RESOLVED value so a slice carrying only OncotreeLineage
    reproduces the exact grouping the live full-Model.csv metadata produced."""
    return meta_row.get("OncotreeLineage") or meta_row.get("lineage") or meta_row.get("PrimaryDisease") or "unknown"


def _live_load(curated: frozenset | None) -> dict:
    """Live-read each anchor gene's Chronos vector + resolved lineage, and the live summary."""
    out: dict[str, dict] = {}
    for gene in ANCHOR_GENES:
        chronos, meta, errs = cli.load_depmap_files(release_pin=RELEASE_PIN, target_symbol=gene)
        if errs:
            raise SystemExit(f"ABORT: live load failed for {gene}: {errs[0].get('_live_read_error')}")
        if not chronos:
            raise SystemExit(f"ABORT: {gene} absent from CRISPRGeneEffect — confirm HGNC symbol")
        lineage = {m: _resolve_lineage(meta.get(m, {})) for m in chronos}
        cc = (gene in curated) if curated is not None else None
        if cc is None:
            raise SystemExit("ABORT: curated core-essential control set unreachable — cannot pin the anchor input")
        live_summary = cli.compute_summary_stats(chronos, meta, curated_common_essential=cc)
        out[gene] = {"chronos": chronos, "lineage": lineage, "curated": cc, "live_summary": live_summary}
    return out


def _offline_rederive(gene: str, chronos: dict, lineage: dict, curated: bool) -> dict:
    """Re-derive through read_pan_cancer_distribution using ONLY the frozen slice — the identical seam the
    committed offline test uses. load_depmap_files → frozen (chronos, {OncotreeLineage: lineage}, []);
    the curated set → a set reproducing the frozen boolean; the additive control axis → inert/deterministic."""
    frozen_meta = {m: {"OncotreeLineage": lineage[m]} for m in chronos}
    curated_set = frozenset({gene}) if curated else frozenset()
    with (
        mock.patch.object(
            cli, "load_depmap_files", lambda release_pin, target_symbol: (dict(chronos), dict(frozen_meta), [])
        ),
        mock.patch.object(cli, "_load_curated_common_essentials", lambda release_pin=RELEASE_PIN: curated_set),
        mock.patch("methods.dependency_controls.control_position_dependency", lambda *a, **k: {}),
    ):
        return rd.read_pan_cancer_distribution(gene)


def _snapshot_provenance(gene: str) -> dict | None:
    ind = ROSTER_INDICATION.get(gene)
    if ind is None:
        return None
    path = SNAPSHOT_DIR / f"{gene.lower()}_{ind.lower()}.functional-requirement.json"
    if not path.exists():
        return None
    prov = json.loads(path.read_text()).get("_crispr_provenance")
    return {"source": str(path.relative_to(CONTRACTS_ROOT.parent)), **prov} if prov else None


def main() -> None:
    curated = cli._load_curated_common_essentials(RELEASE_PIN)
    if curated is None:
        raise SystemExit("ABORT: curated core-essential control set unreachable")
    live = _live_load(curated)

    # --- write the frozen slice (full per-line vectors + resolved lineage), one row per (gene, model) ---
    rows_gene, rows_model, rows_chronos, rows_lineage = [], [], [], []
    for gene in ANCHOR_GENES:
        chronos = live[gene]["chronos"]
        lineage = live[gene]["lineage"]
        for model_id in sorted(chronos):
            rows_gene.append(gene)
            rows_model.append(model_id)
            rows_chronos.append(float(chronos[model_id]))
            rows_lineage.append(lineage[model_id])
    table = pa.table(
        {
            "gene_symbol": pa.array(rows_gene, pa.string()),
            "model_id": pa.array(rows_model, pa.string()),
            "chronos_score": pa.array(rows_chronos, pa.float64()),
            "lineage": pa.array(rows_lineage, pa.string()),
        }
    )
    fixture_path = HERE / FIXTURE_REL
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, fixture_path)
    md5 = hashlib.md5(fixture_path.read_bytes()).hexdigest()
    captured_utc = datetime.now(timezone.utc).isoformat()
    print(f"fixture: {fixture_path.name} rows={table.num_rows} md5={md5}")

    ANCHOR_DIR.mkdir(parents=True, exist_ok=True)
    classes: set[str] = set()
    for gene in ANCHOR_GENES:
        chronos = live[gene]["chronos"]
        lineage = live[gene]["lineage"]
        cc = live[gene]["curated"]
        live_summary = live[gene]["live_summary"]

        # GUARD 1 (fidelity): the offline re-derivation from the frozen slice must reproduce live exactly.
        off = _offline_rederive(gene, chronos, lineage, cc)
        for f in _FIELDS:
            if off[f] != live_summary[f]:
                raise SystemExit(
                    f"ABORT [{gene}]: offline slice re-derivation != live compute on {f!r}: "
                    f"{off[f]!r} != {live_summary[f]!r} — the frozen slice lost information the classifier uses"
                )

        # GUARD 2 (cross-repo): where the roster already recorded this gene's provenance, it must agree.
        snap = _snapshot_provenance(gene)
        if snap is not None:
            for f in _FIELDS:
                if snap.get(f) != off[f]:
                    raise SystemExit(
                        f"ABORT [{gene}]: re-derived {f!r}={off[f]!r} disagrees with the committed calibration "
                        f"snapshot {snap['source']} ({snap.get(f)!r}) — investigate drift, do not re-baseline"
                    )

        classes.add(off["dependency_class"])
        anchor = {
            "target": gene,
            "indication": None,  # this card is pan-cancer; indication is not consumed
            "roster_indication": ROSTER_INDICATION.get(gene),
            "release_pin": RELEASE_PIN,
            "counts_fixture": FIXTURE_REL,
            "curated_common_essential": cc,
            "n_cell_lines_evaluated": off["n_cell_lines_evaluated"],
            "expected_median_chronos_panel": off["median_chronos_panel"],
            "expected_fraction_strongly_dependent": off["fraction_strongly_dependent"],
            "expected_dependency_class": off["dependency_class"],
            "expected_distribution_shape": off["distribution_shape"],
            "snapshot_cross_ref": snap,
            "_source": {
                "product": "depmap-consortium-26q1 CRISPRGeneEffect (Chronos) via depmap-26q1-parquet-v1",
                "curated_control_set": "AchillesCommonEssentialControls.csv",
                "curated_set_size": len(curated),
                "captured_utc": captured_utc,
                "counts_fixture_md5": md5,
            },
        }
        (ANCHOR_DIR / f"{gene.lower()}.chronos_distribution.json").write_text(json.dumps(anchor, indent=2) + "\n")
        print(
            f"  {gene:8} n={anchor['n_cell_lines_evaluated']} "
            f"med={anchor['expected_median_chronos_panel']:.4f} "
            f"frac={anchor['expected_fraction_strongly_dependent']:.4f} "
            f"class={anchor['expected_dependency_class']} shape={anchor['expected_distribution_shape']} "
            f"curated={cc}{' [x-ref roster]' if snap else ''}"
        )
    print(f"classes spanned ({len(classes)}): {sorted(classes)}")
    if len(classes) < 3:
        raise SystemExit(f"ABORT: anchor set spans only {len(classes)} dependency_class branch(es); need >= 3")

    # Anti-vacuity for GUARD 2 itself: at least one anchor gene is known to carry a roster
    # _crispr_provenance block (KRAS). If NONE was cross-checked, the roster was unreachable (a missing
    # target-contracts sibling) and the cross-repo guard silently did nothing — refuse to ship a toothless
    # anchor rather than record every snapshot_cross_ref as null.
    n_xref = sum(1 for g in ANCHOR_GENES if _snapshot_provenance(g) is not None)
    if n_xref == 0:
        raise SystemExit(
            "ABORT: no anchor cross-checked against a roster _crispr_provenance block — the target-contracts "
            "sibling is unreachable, so GUARD 2 never ran. Symlink it beside the worktree and re-capture."
        )
    print(f"cross-referenced against roster: {n_xref} anchor(s)")


if __name__ == "__main__":
    main()
