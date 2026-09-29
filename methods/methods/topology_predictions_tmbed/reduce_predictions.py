"""Reduce a TMbed prediction file (--out-format=3) to a per-protein topology row.

Input:  TMbed .pred file in format 3 (tabular, per-residue class + probs, with
        i/o inside/outside annotations for non-TM residues).
Output: Parquet with one row per UniProt accession carrying:
    accession              str
    gene_symbol            str    # from FASTA header if present
    length                 int32
    n_tm_alpha_helices     int32  # count of contiguous H segments
    n_tm_beta_strands      int32  # count of contiguous B segments
    signal_peptide         bool
    signal_peptide_end     int32  # 1-indexed last SP residue, -1 if none
    ecd_start              int32  # 1-indexed first residue of longest predicted ECD; -1 if none
    ecd_end                int32
    ecd_length             int32
    ecd_orientation        str    # "outside" | "inside" | "unknown"
    topology_summary       str    # e.g. "SP|TM-alpha|ECD-outside"
    all_h_segments         str    # comma-separated "start-end" 1-indexed
    all_b_segments         str
    tmbed_model_version    str    # "1.0.2"

ECD definition:
    "ECD" = the longest contiguous run of `o` (outside) residues.
    - For type-I/II single-pass TM proteins this is the biologic-relevant
      extracellular domain (typically the N-terminus).
    - For multi-pass TM proteins this is the longest extracellular loop.
    - For proteins with zero TM segments the longest inside run is reported
      instead (orientation='inside'); ecd_length=0 with orientation='unknown'
      only when no residues are labeled `i` or `o`.

TMbed format=3 label alphabet:
    B/b: TM beta strand (IN->OUT / OUT->IN)
    H/h: TM alpha helix (IN->OUT / OUT->IN)
    S:   signal peptide
    i:   non-TM, inside
    o:   non-TM, outside

We normalize H+h to a single H count for `n_tm_alpha_helices` and B+b to B
(format=3 preserves the directed segments; downstream target-eval doesn't
usually need direction, but it's recoverable from all_h_segments if needed).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


def parse_pred_format3(path: Path):
    """Yield (header, [(aa, label), ...]) per protein.

    TMbed format=3 is a tabular per-residue file with per-protein header
    lines starting with '>'. Column-header lines start with 'AA' and are
    skipped. Empty lines are skipped.
    """
    header = None
    rows = []
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith(">"):
                if header is not None:
                    yield header, rows
                header = line[1:]
                rows = []
                continue
            if line.startswith("AA") or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            aa, label = parts[0], parts[1]
            rows.append((aa, label))
    if header is not None:
        yield header, rows


def segments_of(labels, targets):
    """Return list of 1-indexed (start, end) tuples for contiguous runs
    of any label in `targets`.
    """
    out = []
    n = len(labels)
    i = 0
    while i < n:
        if labels[i] in targets:
            j = i
            while j + 1 < n and labels[j + 1] in targets:
                j += 1
            out.append((i + 1, j + 1))
            i = j + 1
        else:
            i += 1
    return out


def longest_ecd(labels):
    """Longest contiguous 'o' (outside) run.

    Returns (start, end, length, orientation) or (-1, -1, 0, 'unknown') if
    there are no 'o' or 'i' residues at all.

    Fallback: if no 'o' runs exist, report the longest 'i' (inside) run with
    orientation='inside'. This gives cytosolic proteins a non-null ECD-like
    coordinate for downstream visualization even though no biologic ECD exists.
    """
    outside = segments_of(labels, {"o"})
    if outside:
        s, e = max(outside, key=lambda x: x[1] - x[0])
        return s, e, e - s + 1, "outside"
    inside = segments_of(labels, {"i"})
    if inside:
        s, e = max(inside, key=lambda x: x[1] - x[0])
        return s, e, e - s + 1, "inside"
    return -1, -1, 0, "unknown"


def summarize(header, residues, model_version):
    """Aggregate one protein's per-residue TMbed labels to a single row dict."""
    labels = [lbl for _, lbl in residues]
    L = len(labels)
    parts = header.split("|")
    accession = parts[0]
    gene = parts[1] if len(parts) >= 2 else ""

    # Merge directed variants (H+h, B+b) into orientation-agnostic counts;
    # detailed directional segments are preserved in all_h_segments / all_b_segments.
    h_segs = segments_of(labels, {"H", "h"})
    b_segs = segments_of(labels, {"B", "b"})
    sp_segs = segments_of(labels, {"S"})
    sp_end = sp_segs[0][1] if sp_segs else -1
    ecd_start, ecd_end, ecd_len, ecd_orient = longest_ecd(labels)

    topology = []
    if sp_segs:
        topology.append("SP")
    if h_segs or b_segs:
        topology.append("TM-alpha" if h_segs else "TM-beta")
    if ecd_orient != "unknown":
        topology.append("ECD-" + ecd_orient)

    return {
        "accession": accession,
        "gene_symbol": gene,
        "length": L,
        "n_tm_alpha_helices": len(h_segs),
        "n_tm_beta_strands": len(b_segs),
        "signal_peptide": bool(sp_segs),
        "signal_peptide_end": sp_end,
        "ecd_start": ecd_start,
        "ecd_end": ecd_end,
        "ecd_length": ecd_len,
        "ecd_orientation": ecd_orient,
        "topology_summary": "|".join(topology) if topology else "no-TM-no-SP",
        "all_h_segments": ",".join(f"{s}-{e}" for s, e in h_segs),
        "all_b_segments": ",".join(f"{s}-{e}" for s, e in b_segs),
        "tmbed_model_version": model_version,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pred", required=True, type=Path, help="TMbed --out-format=3 prediction file.")
    ap.add_argument("--out-parquet", required=True, type=Path)
    ap.add_argument(
        "--model-version",
        default="1.0.2",
        help="TMbed model version tag written into every row (x-amz-meta-tmbed-version equivalent).",
    )
    args = ap.parse_args()

    rows = []
    for header, residues in parse_pred_format3(args.pred):
        if not residues:
            continue
        rows.append(summarize(header, residues, args.model_version))

    df = pd.DataFrame(rows)
    args.out_parquet.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.out_parquet, index=False)
    print(f"[reduce_predictions] wrote {len(df)} rows -> {args.out_parquet}", file=sys.stderr)


if __name__ == "__main__":
    main()
