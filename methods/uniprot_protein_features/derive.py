"""uniprot_protein_features.derive — reviewed-human UniProt SwissProt DAT → per-UniProt-AC protein
DOMAIN ARCHITECTURE + PROTEIN CLASS parquet + a target-resolution sidecar (via target_id_resolver).

WHY (target-intrinsic dossier follow-on): two molecular-intrinsic axes the user asked for —
DOMAINS ("kinase domain, Ig domains, ...") and PROTEIN CLASS ("enzyme/GPCR/kinase/...") — both live
in the SwissProt DAT already mirrored on S3 (no new ingestion — the GPI pattern):
  - DOMAIN architecture: the `FT DOMAIN` features (curated Pfam-derived domains + their /note names).
  - PROTEIN CLASS: the `KW` keyword lines are a controlled vocabulary that IS a molecular-class signal.
    We map the class-bearing keywords to a compact protein_class taxonomy (kinase / gpcr / protease /
    ion_channel / transcription_factor / receptor / transporter / ...). Keywords cover TP53-type
    proteins that carry no FT DOMAIN, so the two signals are complementary.

Emits (one row per human reviewed UniProt AC that has >=1 domain OR a class-bearing keyword):
  uniprot_ac, n_domains, domain_names (list), domain_architecture (ordered "A; B; C" string),
  protein_class (list of mapped classes), uniprot_keywords_class (the raw class-bearing KWs)
plus a sibling `*.target_resolution.parquet` sidecar (native_key_type='uniprot_accession').

Deterministic per (DAT snapshot, class-keyword map, resolver release). Usage:
    python -m methods.uniprot_protein_features.derive --out /tmp/pf.parquet [--resolver-release resolver_v1.0.0]
"""
from __future__ import annotations

import argparse
import gzip
import io
import os
import re
import sys
from pathlib import Path
from typing import Optional

S3_BUCKET = "onc-compbio"
SOURCE_S3_KEY = ("data-catalog/sources/uniprot-sprot-human/2026_02-snapshot-2026-06-18/"
                 "uniprot_sprot_human.dat.gz")
DEFAULT_AWS_PROFILE = "cbg"
DEFAULT_RESOLVER_RELEASE = "resolver_v1.0.0"
DATA_CATALOG = Path("/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")

# UniProt KEYWORD → compact protein_class taxonomy. A keyword is a controlled-vocab term; several map
# to one class. Only class-BEARING keywords (molecular function/type) are mapped — generic keywords
# (3D-structure, Disease variant, Phosphoprotein, ...) are ignored. Order = specificity for the
# primary-class pick (first match wins when a protein hits several).
_KEYWORD_TO_CLASS = {
    "G protein-coupled receptor": "gpcr",
    "Receptor": "receptor",
    "Tyrosine-protein kinase": "kinase",
    "Serine/threonine-protein kinase": "kinase",
    "Kinase": "kinase",
    "Transferase": "transferase",
    "Protease": "protease",
    "Hydrolase": "hydrolase",
    "Oxidoreductase": "oxidoreductase",
    "Lyase": "lyase",
    "Ligase": "ligase",
    "Isomerase": "isomerase",
    "Ion channel": "ion_channel",
    "Voltage-gated channel": "ion_channel",
    "Potassium channel": "ion_channel",
    "Sodium channel": "ion_channel",
    "Calcium channel": "ion_channel",
    "Transport": "transporter",
    "Ion transport": "transporter",
    "Activator": "transcription_factor",
    "Repressor": "transcription_factor",
    "DNA-binding": "transcription_factor",
    "Transcription": "transcription_factor",
    "Chromatin regulator": "chromatin_regulator",
    "Cell adhesion": "cell_adhesion",
    "Growth factor": "growth_factor",
    "Cytokine": "cytokine",
    "Chaperone": "chaperone",
    "Ubl conjugation pathway": "ubiquitin_system",
}

_DOMAIN_RE = re.compile(r'^FT\s+DOMAIN[^\n]*\n(?:^FT\s+/note="([^"]+)")?', re.M)
_AC_RE = re.compile(r"^AC\s+(\S+?);", re.M)
_KW_RE = re.compile(r"^KW\s+(.+)$", re.M)


def _read_dat_bytes(local_path: Optional[str]) -> bytes:
    if local_path:
        return Path(local_path).read_bytes()
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE
    import boto3
    return boto3.client("s3").get_object(Bucket=S3_BUCKET, Key=SOURCE_S3_KEY)["Body"].read()


def build_payload(local_dat: Optional[str] = None):
    """Return the per-UniProt-AC domain-architecture + protein-class payload DataFrame."""
    import pandas as pd
    raw = _read_dat_bytes(local_dat)
    rows = []
    seen = set()
    cur: list[str] = []
    with gzip.open(io.BytesIO(raw), "rt") as fh:
        for line in fh:
            cur.append(line)
            if not line.startswith("//"):
                continue
            block = "".join(cur)
            cur = []
            acm = _AC_RE.search(block)
            if not acm:
                continue
            ac = acm.group(1).strip()
            if ac in seen:
                continue
            domains = [d for d in _DOMAIN_RE.findall(block) if d]
            kws = [k.strip().rstrip(";.") for ln in _KW_RE.findall(block)
                   for k in ln.split(";") if k.strip()]
            kw_class = [k for k in kws if k in _KEYWORD_TO_CLASS]
            classes = []
            for k in kw_class:
                c = _KEYWORD_TO_CLASS[k]
                if c not in classes:
                    classes.append(c)
            if not domains and not classes:
                continue   # nothing molecular-intrinsic to report for this entry
            seen.add(ac)
            rows.append({
                "uniprot_ac": ac,
                "n_domains": len(domains),
                "domain_names": domains,
                "domain_architecture": "; ".join(domains) if domains else None,
                "protein_class": classes,
                # primary = first class in UniProt's keyword order (a convenience field; the full
                # `protein_class` list is authoritative — a protein legitimately has several, e.g. an
                # adhesion-GPCR is both gpcr AND cell_adhesion). Consumers should read the list, not
                # over-rely on primary.
                "protein_class_primary": classes[0] if classes else None,
                "uniprot_keywords_class": kw_class,
            })
    df = pd.DataFrame(rows, columns=["uniprot_ac", "n_domains", "domain_names", "domain_architecture",
                                     "protein_class", "protein_class_primary", "uniprot_keywords_class"])
    return df.sort_values("uniprot_ac").reset_index(drop=True)


def _emit_sidecar(payload_path: Path, resolver_release: str):
    """Emit the target-resolution sidecar (mirrors cspa_surface_confirmation / uniprot_gpi_anchor)."""
    lib = DATA_CATALOG / "libs" / "target_id_resolver"
    if str(lib) not in sys.path:
        sys.path.insert(0, str(lib))
    from target_id_resolver.sidecar import emit_sidecar
    sidecar_path = Path(str(payload_path).replace(".parquet", ".target_resolution.parquet"))
    stats = emit_sidecar(
        payload_parquet_path=payload_path,
        native_key_column="uniprot_ac",
        native_key_type="uniprot_accession",
        gencode_version_source="n/a",
        out_path=sidecar_path,
        resolver_release=resolver_release,
    )
    return sidecar_path, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--local-dat", default=None)
    ap.add_argument("--resolver-release", default=DEFAULT_RESOLVER_RELEASE)
    ap.add_argument("--no-sidecar", action="store_true")
    args = ap.parse_args(argv)

    df = build_payload(args.local_dat)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.out, engine="pyarrow", compression="snappy", index=False)
    print(f"[uniprot_protein_features] payload: {len(df)} ACs -> {args.out}", file=sys.stderr)
    print("  with-domain:", int((df["n_domains"] > 0).sum()),
          "| with-class:", int(df["protein_class_primary"].notna().sum()), file=sys.stderr)

    if not args.no_sidecar:
        sidecar_path, stats = _emit_sidecar(args.out, args.resolver_release)
        print(f"[uniprot_protein_features] sidecar -> {sidecar_path}\n  resolver stats: {stats}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
