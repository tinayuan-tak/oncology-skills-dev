"""Extract per-protein FASTA from the catalog's UniProt SwissProt human DAT snapshot.

Reads uniprot_sprot_human.dat.gz from S3 (or a local cache), parses each entry
with Biopython SwissProt, and writes FASTA where the header is:
    >{accession}|{primary_gene_name}|{length}

Sequences carrying selenocysteine (U) or unresolved residues (Z, O, B) are
replaced with X per Rostlab convention — required because ProtT5-XL-U50's
SentencePiece tokenizer will otherwise reject these characters at some
positions.

Design notes:
    - Length filter (20 <= L <= 4200) matches TMbed's 12 GB VRAM guardrail.
      Retained on CPU too for output parity across GPU/CPU reruns.
    - `--max-records` supports pilot runs (100-seq sanity check).
    - Emits diagnostic counts to stderr: total_read / emitted / skipped_length.
"""
from __future__ import annotations

import argparse
import gzip
import re
import sys
from pathlib import Path

from Bio import SwissProt


AMBIGUOUS = re.compile(r"[UZOB]")


def clean_seq(seq: str) -> str:
    """Replace selenocysteine + unresolved residues with X (ProtT5 convention)."""
    return AMBIGUOUS.sub("X", seq)


def iter_records(path: Path):
    """Yield (accession, primary_gene_name, cleaned_sequence) tuples.

    Handles gzip transparently based on file suffix. Extracts the first
    'Name=<symbol>' occurrence from UniProt's GN block as the gene name.
    """
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as fh:
        for rec in SwissProt.parse(fh):
            acc = rec.accessions[0]
            gene = ""
            if rec.gene_name:
                gn = rec.gene_name if isinstance(rec.gene_name, str) else str(rec.gene_name)
                m = re.search(r"Name=([^;\s]+)", gn)
                if m:
                    gene = m.group(1)
            yield acc, gene, clean_seq(rec.sequence)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dat-gz", required=True, type=Path,
                    help="Path to uniprot_sprot_human.dat.gz "
                         "(from data-catalog S3: uniprot-sprot-human-* manifest).")
    ap.add_argument("--out-fasta", required=True, type=Path)
    ap.add_argument("--max-records", type=int, default=None,
                    help="Emit only the first N records (for pilot benchmarks).")
    ap.add_argument("--min-len", type=int, default=20,
                    help="Skip sequences shorter than N residues.")
    ap.add_argument("--max-len", type=int, default=4200,
                    help="Skip sequences longer than N residues "
                         "(TMbed OOM guardrail; retained on CPU for parity).")
    args = ap.parse_args()

    args.out_fasta.parent.mkdir(parents=True, exist_ok=True)
    n_emit = n_skip_len = n_total = 0
    with open(args.out_fasta, "w") as out:
        for acc, gene, seq in iter_records(args.dat_gz):
            n_total += 1
            L = len(seq)
            if L < args.min_len or L > args.max_len:
                n_skip_len += 1
                continue
            out.write(f">{acc}|{gene}|{L}\n{seq}\n")
            n_emit += 1
            if args.max_records and n_emit >= args.max_records:
                break

    print(f"[prepare_fasta] total_read={n_total} emitted={n_emit} "
          f"skipped_length={n_skip_len}", file=sys.stderr)


if __name__ == "__main__":
    main()
