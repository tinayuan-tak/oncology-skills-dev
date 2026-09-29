"""Raw-input fixtures for the gene-ID authority tests.

Per the project's fixture discipline: store the RAW INPUT (the two source-file
text blobs) and RE-DERIVE the authority in the test. A fixture of pre-computed
authority rows could never fail — it would just echo whatever build() produced.
So these are byte-level source snippets (real Ensembl IDs, symbols chosen to
exercise every branch) written to disk and fed through the real reader.

Genes covered:
  ENSG00000133703  KRAS      clean — same symbol in both releases
  ENSG00000000460  C1orf112/FIRRM   symbol DRIFT (real v23→v116 rename)
  ENSG00000258399  MEG8 (v23) / OTHERX (v116)   reuse pair A
  ENSG00000225746  SNHG23 (v23) / MEG8 (v116)   reuse pair B
       → symbol string "MEG8" is REASSIGNED: v23 gene A, v116 gene B (disjoint)
  ENSG00000111111  v23-only (no Ensembl-116 row)
  ENSG00000222222  Ensembl-116-only WITH HGNC symbol (absent from v23)
  ENSG00000333333  Ensembl-116-only, NULL HGNC, absent from v23
       → no symbol in either source; MUST be dropped (inert for both products)
"""

from __future__ import annotations

from pathlib import Path

# Ensembl-116 id-mapping TSV: Gene stable ID, Gene stable ID version, HGNC ID,
# HGNC symbol, Gene name. Versioned column present but the reader keys on the
# unversioned stable id.
_ENS116_TSV = """\
Gene stable ID\tGene stable ID version\tHGNC ID\tHGNC symbol\tGene name
ENSG00000133703\tENSG00000133703.13\tHGNC:6407\tKRAS\tKRAS
ENSG00000000460\tENSG00000000460.17\tHGNC:25565\tFIRRM\tFIRRM
ENSG00000258399\tENSG00000258399.5\t\t\tnovel transcript
ENSG00000225746\tENSG00000225746.8\tHGNC:14574\tMEG8\tMEG8
ENSG00000222222\tENSG00000222222.2\tHGNC:99999\tBARONLY\tBARONLY
ENSG00000333333\tENSG00000333333.1\t\t\tsome lincRNA
"""

# GENCODE v23 probemap: id (versioned Ensembl), gene, chrom, chromStart,
# chromEnd, strand.
_V23_PROBEMAP = """\
id\tgene\tchrom\tchromStart\tchromEnd\tstrand
ENSG00000133703.11\tKRAS\tchr12\t25205246\t25250929\t-
ENSG00000000460.12\tC1orf112\tchr1\t169631245\t169823221\t+
ENSG00000258399.3\tMEG8\tchr14\t101300000\t101310000\t+
ENSG00000225746.5\tSNHG23\tchr14\t101400000\t101410000\t+
ENSG00000111111.4\tFOOONLY\tchr7\t1000\t2000\t+
"""


def write_sources(tmp_path: Path) -> tuple[Path, Path]:
    """Write the two raw source files under tmp_path; return their paths."""
    ens = tmp_path / "ens116.tsv"
    v23 = tmp_path / "v23.probemap"
    ens.write_text(_ENS116_TSV)
    v23.write_text(_V23_PROBEMAP)
    return ens, v23
