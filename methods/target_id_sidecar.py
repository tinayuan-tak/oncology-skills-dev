"""Shared target-id resolver-sidecar loader + S3 client, with a definitive-vs-transient error
discipline. Consolidates the copy-pasted `read symbol→native-id sidecar parquet → build map →
except Exception: return {}` logic that lived in gene_ontology_annotation, reactome_pathway_context,
uniprot_protein_features, ppi_interactome, and opentargets_common (P5.1, 2026-08-11).

WHY the discipline matters (ref methods/expression_clinical_association/read.py:44-76 + the
feedback_bare_except_masks_broken_env lesson): a resolver crosswalk either loads or it does NOT.
An EMPTY crosswalk silently fails EVERY target — every gene reads `data_unavailable`, framework-wide
— which is exactly the bare-`except: return {}` bug class. So `read_resolver_sidecar_map` RAISES on
any read/parse failure (broken env: missing pandas/pyarrow; transient S3: creds/throttle/network;
schema drift: missing columns; empty result) instead of returning {}. The compose-dashboard live-read
seam wraps every reader in `try/except -> {"_live_read_error": str(e)}`, so a raise surfaces as an
HONEST per-card `_live_read_error` (the skill still completes) rather than a silent dead axis.
Callers MUST NOT re-wrap this in `except: return {}`.

For per-target DATA products (not the crosswalk) where a genuinely-absent object IS an honest
data gap, use `is_definitively_absent(exc)` to swallow only NoSuchKey/404 and re-raise everything
else (broken env / transient / creds).
"""
from __future__ import annotations

import io
import os
from typing import Optional

DEFAULT_AWS_PROFILE = "cbg"

# value tokens that are never a real native id (guards stringified nulls in the sidecar)
_BAD_VALUES = {"", "nan", "none", "null", "na", "<na>"}


def s3_client(profile: Optional[str] = None):
    """boto3 s3 client with a preferred AWS profile (default `cbg`) and an ADAPTIVE-retry Config.

    The retry Config absorbs transient throttling (SlowDown / 503 / RequestTimeout) — the batch-read
    failure mode that silently dropped ~5/19 cards on a full target-intrinsic run (EGFR, 2026-08-11):
    near-concurrent per-card S3 reads got throttled, the readers' bare excepts converted the throttle
    into `data_unavailable`, and a quarter of the dossier vanished with no diagnostic. Adaptive mode
    adds client-side rate-limiting on top of standard retries.

    PROFILE FALLBACK (2026-08-15): `cbg` is a developer SSO profile — it does NOT exist in CI, prod,
    or on an instance-role host. The reader-hardening burndown routed several readers (uniprot_gpi_anchor,
    cspa_surface_confirmation, surfaceome_family_fusion, ...) from a bare `boto3.client("s3")` (which
    used the ambient credential chain) onto this helper; that surfaced a latent break where an UNMOCKED
    live read in a non-`cbg` environment raised `ProfileNotFound` instead of using ambient creds — first
    caught by the skills compose-dashboard CI. So: try the preferred profile, but if it is not configured
    fall back to the default credential chain (env / OIDC / instance role), exactly as the bare client
    it replaced did. An explicitly-passed `profile=` still raises if missing (caller asked for it)."""
    import boto3
    from botocore.exceptions import ProfileNotFound
    from botocore.config import Config
    cfg = Config(retries={"max_attempts": 8, "mode": "adaptive"})
    prof = profile or os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)
    try:
        return boto3.Session(profile_name=prof).client("s3", config=cfg)
    except ProfileNotFound:
        if profile is not None:
            raise  # caller explicitly demanded this profile — do not silently substitute
        # Preferred/default profile absent (CI / prod / instance-role): use the ambient chain.
        # A bare Session() still reads AWS_PROFILE from the env, so strip a bad value first
        # (restored after) — otherwise the fallback re-raises the same ProfileNotFound.
        saved = os.environ.pop("AWS_PROFILE", None)
        try:
            return boto3.Session().client("s3", config=cfg)
        finally:
            if saved is not None:
                os.environ["AWS_PROFILE"] = saved


def is_definitively_absent(exc: BaseException) -> bool:
    """True IFF `exc` means the S3 object genuinely does not exist (NoSuchKey / 404 / NoSuchBucket).

    Use to swallow ONLY genuine absence when reading a per-target DATA product (honest
    data_unavailable), while re-raising everything else — ImportError (broken env), ExpiredToken /
    AccessDenied (creds), Throttling / SlowDown / timeouts (transient) — so it surfaces as
    _live_read_error instead of a silent dead axis:

        try:
            ... read product ...
        except Exception as e:
            if not is_definitively_absent(e):
                raise            # broken env / transient / creds -> honest _live_read_error
            return _empty()      # genuine absence -> honest data_unavailable
    """
    try:
        from botocore.exceptions import ClientError
    except Exception:  # botocore somehow unavailable -> treat as NOT absent (propagate)
        return False
    if isinstance(exc, ClientError):
        code = str(exc.response.get("Error", {}).get("Code", ""))
        return code in {"NoSuchKey", "404", "NoSuchBucket", "NoSuchBucketPolicy"}
    return False


def read_resolver_sidecar_map(bucket: str, key: str, key_col: str, val_col: str, *,
                              local_path: Optional[str] = None, upper_key: bool = True) -> dict:
    """Return a {key_col -> val_col} crosswalk dict from a target-id resolver sidecar parquet.

    RAISES on any failure (see module docstring) — never returns an empty crosswalk silently, because
    an empty crosswalk fails every target. `local_path` (test fixture / warm cache) is read directly.
    First value wins (setdefault); keys upper-cased when `upper_key`; stringified-null values skipped.
    """
    import pandas as pd  # ImportError here == broken env -> propagates (correct)
    if local_path is not None:
        df = pd.read_parquet(local_path)                                   # fixture / cache: direct
    else:
        body = s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()
        df = pd.read_parquet(io.BytesIO(body))
    if key_col not in df.columns or val_col not in df.columns:
        raise ValueError(
            f"resolver sidecar s3://{bucket}/{key} missing expected columns "
            f"{key_col!r}/{val_col!r} (present: {list(df.columns)[:10]}) — schema drift")
    out: dict[str, str] = {}
    for k, v in zip(df[key_col].values, df[val_col].values):
        if isinstance(k, str) and isinstance(v, str):
            ks, vs = k.strip(), v.strip()
            if ks and vs and vs.lower() not in _BAD_VALUES:
                out.setdefault(ks.upper() if upper_key else ks, vs)
    if not out and local_path is None:
        # a non-empty parquet that yielded no usable pairs from S3 = a broken/misdescribed product,
        # not a data gap. (Injected local_path fixtures are test-controlled, so not gated here.)
        raise ValueError(f"resolver sidecar s3://{bucket}/{key} produced an EMPTY crosswalk")
    return out
