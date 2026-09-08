"""shed_ectodomain_liability.media — the MEASURED wet-lab shed tier (Olink conditioned-media).

The third evidence leg of shed-ectodomain-liability.
The curated `clinical` tier (7 serum markers) and the HPA `secretome_proxy` tier are both
ANNOTATION-derived. This leg adds a MEASURED signal: Olink NPX (normalized protein
expression) in CONDITIONED MEDIA across the DepMap cell-line panel — protein that a live
cancer cell actually released into its supernatant, i.e. an empirical shed/secreted readout.

Substrate: `harmonized_olink_media_26Q1_filtered.csv` in the LANDED source
`depmap-consortium-26q1-proteomics` (system-of-record; the same manifest whose Gygi-TMT
whole-cell leg feeds cellline-protein-abundance). Wide matrix: rows = ModelID (ACH-*),
columns = UniProt accessions, values = media NPX. Keyed to HGNC symbols via the Olink-panel
id map `uniprot_hugo_entrez_id_mapping_26q1.csv`.

DESIGN — a PARALLEL categorical facet, NOT a new precedence rung.
  This leg emits `measured_shed_class` INDEPENDENTLY of the primary `shed_liability_class`
  (which stays byte-identical for every gene). Mirrors the tce_homogeneity_class-alongside-
  sc_expression_class pattern: an additive facet cannot flip the primary class.

MS / PANEL ASYMMETRY (load-bearing, mirrors the pMHC + Gygi readers):
  The media panel is BOUNDED (1,038 proteins) and 100% HPA-secretome-preselected — it is the
  Olink secreted-protein panel, not a proteome-wide scan. So ABSENCE from the panel is NON-
  INFORMATIVE (`not_on_secreted_panel`), never a measured "not shed". Only a POSITIVE strong
  detection (`media_shed_high`) is verdict-relevant. Low on-panel NPX is informational-only.

THRESHOLD — self-calibrating (relative-to-what, not a magic number):
  "High" = the panel's own per-protein p75 mean-NPX, computed live from the matrix each load.
  A target clears `media_shed_high` iff its mean media NPX >= that p75 AND it is detected in
  >= MIN_LINES_DETECTED cell lines (guards a high mean off 1-2 noisy wells).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from methods.catalog_query.read import bucket_prefix_for

PROT_SOURCE_MANIFEST_ID = "depmap-consortium-26q1-proteomics"
MEDIA_FILENAME = "harmonized_olink_media_26Q1_filtered.csv"
IDMAP_FILENAME = "uniprot_hugo_entrez_id_mapping_26q1.csv"

DEFAULT_AWS_PROFILE = "cbg"
MIN_LINES_DETECTED = 3  # a high mean must rest on >= this many detected lines
MEDIA_PANEL_HIGH_QUANTILE = 0.75  # panel per-protein mean-NPX quantile that defines "high"


from methods.target_id_sidecar import ensure_aws_profile


def _s3_bucket_key(filename: str):
    bucket, prefix = bucket_prefix_for(PROT_SOURCE_MANIFEST_ID)
    return bucket, f"{prefix.rstrip('/')}/{filename}"


def _read_csv_s3(filename: str):
    """Read a proteomics-source CSV from S3 into a DataFrame (boto3 — same idiom as the
    HPA leg in cli.py; avoids an s3fs dependency)."""
    import io

    import boto3

    ensure_aws_profile()
    bucket, key = _s3_bucket_key(filename)
    body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
    import pandas as pd

    return pd.read_csv(io.BytesIO(body), index_col=0, low_memory=False)


@lru_cache(maxsize=1)
def _load_media(media_path: Optional[str] = None):
    """Load the Olink media matrix + derive per-protein stats. Cached (one ~6MB read).

    Returns (per_protein_df, panel_high_threshold) where per_protein_df is indexed by the
    matrix column (UniProt accession, possibly isoform/phospho-suffixed) with columns
    mean_npx / n_detected. `media_path` overrides S3 for tests (a local CSV).
    """
    import pandas as pd

    if media_path is not None:
        df = pd.read_csv(media_path, index_col=0, low_memory=False)
    else:
        df = _read_csv_s3(MEDIA_FILENAME)
    df = df.apply(pd.to_numeric, errors="coerce")
    per = pd.DataFrame(
        {
            "mean_npx": df.mean(axis=0, skipna=True),
            "n_detected": df.notna().sum(axis=0),
        }
    )
    panel_high = float(per["mean_npx"].quantile(MEDIA_PANEL_HIGH_QUANTILE))
    return per, panel_high


@lru_cache(maxsize=1)
def _load_idmap(idmap_path: Optional[str] = None) -> dict:
    """UPPER(HGNC symbol) -> UniProt accession, from the Olink-panel id map. {} if unreadable."""
    import io

    import pandas as pd

    try:
        if idmap_path is not None:
            idm = pd.read_csv(idmap_path)
        else:
            import boto3

            ensure_aws_profile()
            bucket, key = _s3_bucket_key(IDMAP_FILENAME)
            body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
            idm = pd.read_csv(io.BytesIO(body))
    except Exception as e:  # noqa: BLE001
        # Genuine object-absence (S3 404/NoSuchKey, or a missing local id map) → {} (target then
        # reads not_on_secreted_panel, non-informative). A transient/creds/broken-env failure is
        # RE-RAISED — not masked as an empty map that @lru_cache would memoize process-wide (one blip
        # → every gene silently not_on_secreted_panel for the whole process). Raise → not memoized.
        from methods.target_id_sidecar import is_definitively_absent

        if not (is_definitively_absent(e) or isinstance(e, FileNotFoundError)):
            raise
        return {}
    out = {}
    for uni, sym in zip(idm["UniprotID"], idm["Symbol"]):
        if sym is not None and str(sym).strip() and str(sym) != "nan":
            out.setdefault(str(sym).upper().strip(), str(uni))
    return out


def _match_column(uniprot: str, per_index) -> Optional[str]:
    """Match an id-map UniProt accession to a media matrix column, tolerating the matrix's
    isoform/phospho suffixes (id map gives Q13421-2; matrix column is the base Q13421; the
    Gygi leg carries e.g. P04626_Phospho_Y1248). Prefer exact, then base-accession."""
    if uniprot in per_index:
        return uniprot
    base = uniprot.split("-")[0].split("_")[0]
    if base in per_index:
        return base
    # matrix column may itself be suffixed off the base (e.g. base_Phospho_...)
    for col in per_index:
        if str(col).split("-")[0].split("_")[0] == base:
            return col
    return None


def classify_measured_shed(
    gene_symbol: str, media_path: Optional[str] = None, idmap_path: Optional[str] = None
) -> dict:
    """MEASURED shed facet for a gene from the Olink conditioned-media panel.

    Returns a dict of parallel-facet fields (never raises for an absent gene — that is a
    valid `not_on_secreted_panel` state). Classes:
      media_shed_high      — mean media NPX >= panel p75 AND detected in >= MIN_LINES_DETECTED
                             lines: empirically released into supernatant across the panel.
      media_shed_low       — on the secreted panel but below the high bar (informational only).
      not_on_secreted_panel— target is not a column on the Olink secreted panel: NON-INFORMATIVE
                             (the panel is bounded + secretome-preselected), NOT a measured negative.
      data_unavailable     — the media matrix / id map could not be read (infra failure).
    """
    try:
        per, panel_high = _load_media(media_path)
    except Exception as e:  # noqa: BLE001 — infra failure is data_unavailable, not a negative
        return {
            "measured_shed_class": "data_unavailable",
            "media_mean_npx": None,
            "media_n_lines_detected": None,
            "media_panel_high_npx": None,
            "media_uniprot": None,
            "_measured_read_error": f"olink_media_read_failed: {e}",
        }
    idmap = _load_idmap(idmap_path)
    uni = idmap.get(gene_symbol.strip().upper())
    col = _match_column(uni, per.index) if uni else None
    if col is None:
        return {
            "measured_shed_class": "not_on_secreted_panel",
            "media_mean_npx": None,
            "media_n_lines_detected": None,
            "media_panel_high_npx": round(panel_high, 3),
            "media_uniprot": uni,
        }
    mean_npx = float(per.loc[col, "mean_npx"])
    n_det = int(per.loc[col, "n_detected"])
    is_high = (mean_npx >= panel_high) and (n_det >= MIN_LINES_DETECTED)
    return {
        "measured_shed_class": "media_shed_high" if is_high else "media_shed_low",
        "media_mean_npx": round(mean_npx, 3),
        "media_n_lines_detected": n_det,
        "media_panel_high_npx": round(panel_high, 3),
        "media_uniprot": uni,
    }
