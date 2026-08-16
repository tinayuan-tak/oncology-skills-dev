"""Shared loader for MATERIALIZED single-file derived products.

Several per-indication readers (progeny / stemness / oncogenic-pathway / pancanatlas-DDR /
tcga-mc3-signatures / precog / ...) materialize their derived product as ONE small parquet
object in the data-catalog and load it by streaming ``aws s3 cp <uri> -`` into ``pd.read_parquet``.
Each reader had copy-pasted the same ``_load_product`` block (subprocess cp → read_parquet →
optional dev-build fallback). This is the single shared implementation.

The per-reader ``_load_product`` / ``_resolve_derived_uri`` wrappers are intentionally KEPT (their
tests monkeypatch ``_load_product`` and inspect ``_resolve_derived_uri`` by name); they now delegate
here rather than re-implementing the fetch.
"""
from __future__ import annotations

import io
import subprocess
from typing import Callable, Optional


def load_materialized_product(uri: str, *, dev_build: Optional[Callable] = None, timeout: int = 120):
    """Load a materialized single-file parquet product.

    Streams the object via ``aws s3 cp <uri> -`` and returns ``pd.read_parquet`` of the bytes.
    When the object is unreachable or empty:
      * with a ``dev_build`` thunk → fall back to building the table locally (dev convenience);
      * without one → raise ``RuntimeError``.

    Preserves the byte-for-byte behavior of the per-reader ``_load_product`` blocks it replaces:
    a subprocess/read exception or an empty payload routes to ``dev_build`` if given, else raises.
    """
    import pandas as pd
    try:
        raw = subprocess.run(["aws", "s3", "cp", uri, "-"], capture_output=True, timeout=timeout).stdout
        if raw:
            return pd.read_parquet(io.BytesIO(raw))
    except Exception:
        if dev_build is None:
            raise
        return dev_build()
    if dev_build is not None:
        return dev_build()
    raise RuntimeError(f"could not load materialized product from {uri}")
