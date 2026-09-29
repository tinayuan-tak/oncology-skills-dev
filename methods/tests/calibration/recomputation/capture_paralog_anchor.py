"""LIVE capture tool for the depmap-paralog-buffering T3 recomputation anchor.

NOT collected by pytest (no ``test_`` prefix): it needs the live DepMap 26Q1 paralog screen
(``ParalogGeneEffect.csv``, ~69 MB, AWS ``cbg`` creds). The committed sibling test
``test_paralog_buffering_recomputation.py`` is fully offline and reads only the fixtures this tool writes.

What it freezes — the IRREPRODUCIBLE input: a COLUMN SLICE of the raw ParalogGeneEffect.csv holding, for
every anchor target, all of that target's dual-KO pair columns AND the single-KO baseline columns for the
target and every partner in those pairs, across all 282 cell-line rows. From that slice the offline test
re-parses through the REAL ``_load_paralog_indexed`` — so the per-pair median dual-KO effect, the
min()-single baseline (the corrected buffering metric; a max() baseline manufactured buffering on
essential members — see read.py), the delta, and the class are all RE-DERIVED, never echoed.

The reader PREFERS a pre-computed derived product; that path serves stored deltas, not a recompute, so it
is not what a T3 "prove the number" anchor can pin. This tool forces the raw-CSV recompute path
(``_read_from_derived_product`` → None) — the same fallback the offline test exercises — and anchors that.

Two independent guards make the anchor honest before it is committed:
  1. FIDELITY — the offline re-derivation from the column slice must reproduce the LIVE full-CSV recompute
     exactly for every asserted field; if the slice dropped a pair/baseline column the compute needs, it aborts.
  2. CROSS-REPO — KRAS's functional-requirement calibration snapshot headline independently records
     paralog_buffering_class + strongest_paralog_symbol; the re-derived values must equal it, or it aborts
     rather than silently re-baselining. Aborts too if NO anchor was cross-checked (roster unreachable).

Run:
    env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \
        PYTHONPATH=<analysis-methods-root> python3 <this file>
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
AM_ROOT = HERE.parents[2]
if str(AM_ROOT) not in sys.path:
    sys.path.insert(0, str(AM_ROOT))

import methods.depmap_paralog_aggregator.read as rd  # noqa: E402

FIXTURE_REL = "paralog_effects/depmap_26q1__paralog_gene_effect_slice.csv"
ANCHOR_DIR = HERE / "anchors"

# Anchor targets. All are canonical literature paralog-synthetic-lethal genes from the functional-requirement
# 20-target panel the reader's own docstring calibrates against (VPS4A/VPS4B, ASF1A/ASF1B, KRAS/NRAS,
# STAG1/STAG2, MAPK1/MAPK3, ARID1A/ARID1B, RPL22/RPL22L1, CDK4/CDK6, ME1/ME2, SMARCA2/SMARCA4) — the gene
# choice is grounded, not invented. The set is designed to span all four paralog_buffering_class branches
# (strong / partial / none / data_unavailable); the actual classes are whatever the real compute returns and
# are asserted non-vacuous below, never assumed. DDX3X is absent from the paralog screens → the data_unavailable
# branch (an honest absence anchor, no delta to re-derive).
ANCHOR_TARGETS = [
    "VPS4A",  # strong
    "ASF1A",  # strong
    "KRAS",  # strong (+ roster cross-ref)
    "CDK4",  # strong
    "ARID1A",  # partial
    "RPL22",  # partial
    "ME2",  # none
    "SMARCA4",  # none
    "DDX3X",  # data_unavailable (not in paralog screens)
]

CONTRACTS_ROOT = AM_ROOT.parent / "rnd-computational-biology-oncology-target-contracts"
SNAPSHOT_DIR = CONTRACTS_ROOT / "tests" / "calibration" / "snapshots"
# KRAS is the one anchor the roster records paralog headline fields for (kras_coadread.functional-requirement).
ROSTER_SNAPSHOT = {"KRAS": "kras_coadread.functional-requirement.json"}

# Fields this anchor re-derives from the raw recompute.
_FIELDS = (
    "paralog_buffering_class",
    "strongest_paralog_symbol",
    "strongest_paralog_delta",
    "n_paralogs_annotated",
    "n_paralogs_functionally_buffering",
)
# The two the roster snapshot headline carries (its headline stores the class + the strongest partner only).
_ROSTER_FIELDS = ("paralog_buffering_class", "strongest_paralog_symbol")

_CONTROL_MARKERS = {"AAVS1", "CHR2", "NONTARGET", "SAFE"}


def _classify_column(col_name: str):
    """Mirror read._load_paralog_indexed's header classification so the slice keeps exactly the columns the
    recompute reads. Returns ('single', GENE) | ('pair', (A,B) sorted) | None (control / skip)."""
    tokens = [t.strip().upper() for t in col_name.strip().split("_")]
    if len(tokens) == 1:
        g = tokens[0]
        return ("single", g) if g and g not in _CONTROL_MARKERS else None
    if len(tokens) != 2:
        return None
    a, b = tokens
    if not a or not b or a in _CONTROL_MARKERS or b in _CONTROL_MARKERS or a == b:
        return None
    return ("pair", tuple(sorted([a, b])))


def _select_slice_columns(header: list[str]) -> list[int]:
    """Column indices to freeze: col 0 (ModelID) + every dual-KO pair column involving an anchor target +
    every single-KO baseline column for an anchor target or any partner appearing in those pairs. Keeping
    ALL of a target's pairs (not just its strongest) is required — n_paralogs_annotated and the strongest
    partner are re-derived over the full pair list."""
    anchors = {t.upper() for t in ANCHOR_TARGETS}
    keep = {0}
    genes_needing_single: set[str] = set(anchors)
    # Pass 1: keep every pair column touching an anchor; record the genes involved (need their singles).
    for idx, name in enumerate(header):
        if idx == 0:
            continue
        cls = _classify_column(name)
        if cls and cls[0] == "pair" and (cls[1][0] in anchors or cls[1][1] in anchors):
            keep.add(idx)
            genes_needing_single.update(cls[1])
    # Pass 2: keep the single-KO baseline column for every gene the kept pairs (or anchors) reference.
    for idx, name in enumerate(header):
        if idx == 0 or idx in keep:
            continue
        cls = _classify_column(name)
        if cls and cls[0] == "single" and cls[1] in genes_needing_single:
            keep.add(idx)
    return sorted(keep)


def _write_slice(raw_csv: Path, keep_idx: list[int], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        raw_csv.open("r", encoding="utf-8", newline="") as fin,
        out_path.open("w", encoding="utf-8", newline="") as fout,
    ):
        reader = csv.reader(fin)
        writer = csv.writer(fout)
        for row in reader:
            writer.writerow([row[i] if i < len(row) else "" for i in keep_idx])


def _live_summary(target: str) -> dict:
    """LIVE recompute from the full raw CSV, raw path forced (product off)."""
    with mock.patch.object(rd, "_read_from_derived_product", lambda t: None):
        rd._load_paralog_indexed.cache_clear()
        return rd.read_target_summary(target)


def _offline_summary(slice_csv: Path, target: str) -> dict:
    """OFFLINE recompute from the frozen column slice — the identical seam the committed test uses:
    _ensure_paralog_cached → the slice CSV, the parse cache cleared, the derived-product path forced off."""
    with (
        mock.patch.object(rd, "_ensure_paralog_cached", lambda: slice_csv),
        mock.patch.object(rd, "_read_from_derived_product", lambda t: None),
    ):
        rd._load_paralog_indexed.cache_clear()
        return rd.read_target_summary(target)


def _roster_cross_ref(target: str) -> dict | None:
    name = ROSTER_SNAPSHOT.get(target)
    if name is None:
        return None
    path = SNAPSHOT_DIR / name
    if not path.exists():
        return None
    headline = json.loads(path.read_text()).get("headline") or {}
    have = {f: headline[f] for f in _ROSTER_FIELDS if f in headline}
    return {"source": str(path.relative_to(CONTRACTS_ROOT.parent)), **have} if have else None


def _slim(summary: dict) -> dict:
    return {f: summary.get(f) for f in _FIELDS}


def main() -> None:
    raw_csv = rd._ensure_paralog_cached()
    if raw_csv is None:
        raise SystemExit("ABORT: ParalogGeneEffect.csv unreachable (creds / S3) — cannot capture the anchor input")

    # --- LIVE full-CSV recompute for every anchor (raw path) ---
    live = {t: _live_summary(t) for t in ANCHOR_TARGETS}

    # --- freeze the column slice ---
    with raw_csv.open("r", encoding="utf-8", newline="") as f:
        header = next(csv.reader(f))
    keep_idx = _select_slice_columns(header)
    fixture_path = HERE / FIXTURE_REL
    _write_slice(raw_csv, keep_idx, fixture_path)
    md5 = hashlib.md5(fixture_path.read_bytes()).hexdigest()
    n_rows = sum(1 for _ in fixture_path.open()) - 1
    captured_utc = datetime.now(timezone.utc).isoformat()
    print(f"fixture: {fixture_path.name} cols={len(keep_idx)} model_rows={n_rows} md5={md5}")

    ANCHOR_DIR.mkdir(parents=True, exist_ok=True)
    classes: set[str] = set()
    n_xref = 0
    for target in ANCHOR_TARGETS:
        live_s = _slim(live[target])
        off = _slim(_offline_summary(fixture_path, target))

        # GUARD 1 (fidelity): offline slice recompute must reproduce the live full-CSV recompute exactly.
        for fld in _FIELDS:
            if off[fld] != live_s[fld]:
                raise SystemExit(
                    f"ABORT [{target}]: offline slice recompute != live compute on {fld!r}: "
                    f"{off[fld]!r} != {live_s[fld]!r} — the column slice lost a pair/baseline column the "
                    f"recompute reads"
                )

        # GUARD 2 (cross-repo): where the roster records paralog headline fields, they must agree.
        snap = _roster_cross_ref(target)
        if snap is not None:
            n_xref += 1
            for fld in _ROSTER_FIELDS:
                if snap.get(fld) != off[fld]:
                    raise SystemExit(
                        f"ABORT [{target}]: re-derived {fld!r}={off[fld]!r} disagrees with the committed "
                        f"calibration snapshot {snap['source']} ({snap.get(fld)!r}) — investigate, do not re-baseline"
                    )

        classes.add(off["paralog_buffering_class"])
        anchor = {
            "target": target,
            "indication": None,  # paralog buffering is indication-agnostic
            "release_pin": "26q1",
            "counts_fixture": FIXTURE_REL,
            "expected_paralog_buffering_class": off["paralog_buffering_class"],
            "expected_strongest_paralog_symbol": off["strongest_paralog_symbol"],
            "expected_strongest_paralog_delta": off["strongest_paralog_delta"],
            "expected_n_paralogs_annotated": off["n_paralogs_annotated"],
            "expected_n_paralogs_functionally_buffering": off["n_paralogs_functionally_buffering"],
            "snapshot_cross_ref": snap,
            "_source": {
                "product": "depmap-consortium-26q1-paralogs/ParalogGeneEffect.csv (raw dual-KO gene effect)",
                "read_path": "raw-CSV recompute (_read_from_raw_csv); derived product forced off",
                "delta_definition": "min(single_a, single_b) - median_dual_ko  [strong>0.5, partial>=0.2]",
                "captured_utc": captured_utc,
                "counts_fixture_md5": md5,
            },
        }
        (ANCHOR_DIR / f"{target.lower()}.paralog_buffering.json").write_text(json.dumps(anchor, indent=2) + "\n")
        d = off["strongest_paralog_delta"]
        print(
            f"  {target:8} class={off['paralog_buffering_class']:16} "
            f"strongest={off['strongest_paralog_symbol'] or '-':8} "
            f"delta={d if d is None else round(d, 4)} n_ann={off['n_paralogs_annotated']}"
            f"{' [x-ref roster]' if snap else ''}"
        )

    print(f"classes spanned ({len(classes)}): {sorted(classes)}")
    if len(classes) < 3:
        raise SystemExit(f"ABORT: anchor set spans only {len(classes)} paralog_buffering_class branch(es); need >= 3")
    # Anti-vacuity for GUARD 2: KRAS is known to carry roster paralog headline fields. If NONE cross-checked,
    # the target-contracts sibling is unreachable and GUARD 2 silently did nothing — refuse to ship a
    # toothless anchor (the lesson from the chronos arc's missing target-contracts symlink).
    if n_xref == 0:
        raise SystemExit(
            "ABORT: no anchor cross-checked against a roster snapshot — the target-contracts sibling is "
            "unreachable, so GUARD 2 never ran. Symlink it beside the worktree and re-capture."
        )
    print(f"cross-referenced against roster: {n_xref} anchor(s)")


if __name__ == "__main__":
    main()
