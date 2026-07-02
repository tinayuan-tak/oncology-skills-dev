"""Shared-memory transport for the omics bundle.

Fixes the OOM class of failure that killed the 2026-07-02 genome-wide run:
the previous coordinator pickled a ~5 GB omics dict to /tmp and each spawned
worker unpickled its own copy. With N workers this meant N × 5 GB peak RAM,
which exceeded the 62 GB instance ceiling at N=16 and crashed the box.

The fix: publish each numpy array in the omics bundle to a POSIX shared-memory
segment ONCE from the coordinator. Workers attach to the SHM by name and
reconstruct pandas DataFrames as zero-copy views over the shared buffers.
Physical RAM footprint is O(1) in the number of workers instead of O(N).

Non-goals:
  - We do NOT share arbitrary Python objects (only ndarrays). The Model.csv
    metadata frame is small enough (~1 MB) to pass in the handle via pickle.
  - Object-dtype arrays (strings) go through pickle-in-the-handle rather than
    SHM. Index and column labels are typically string arrays and are small.

Cleanup contract:
  - Coordinator MUST call `handle.unlink()` after all workers exit. On abnormal
    coordinator death the SHM segments leak until reboot (tmpfs, so no
    persistent disk usage; but named-SHM slots leak). Best-effort cleanup via
    a filesystem lock file at /dev/shm/e5_shm_registry.lock.
"""

from __future__ import annotations

import pickle
import uuid
from dataclasses import dataclass, field
from multiprocessing import shared_memory
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class _SharedArraySpec:
    """Descriptor for one ndarray backed by SharedMemory."""
    shm_name: str
    shape: tuple
    dtype: str  # np.dtype.str, e.g. '<f4'


@dataclass
class _SharedFrameSpec:
    """Descriptor for one DataFrame: array spec + index + columns."""
    values: _SharedArraySpec       # 2D ndarray (n_rows, n_cols)
    index_pickle: bytes            # small (row labels)
    columns_pickle: bytes          # small (column labels)


@dataclass
class SharedOmicsHandle:
    """Serializable handle passed to workers via initargs.

    Small (~few MB regardless of how much data is in shared memory). Contains
    only the SHM names + shapes/dtypes + pickled index/column labels; workers
    attach to the SHM segments themselves.
    """
    frames: dict[str, _SharedFrameSpec] = field(default_factory=dict)
    extras_pickle: bytes = b""     # pickled dict of small non-array items (Model.csv)

    def unlink_all(self) -> None:
        """Coordinator calls this after workers exit to free SHM segments.
        Idempotent; a segment that was already unlinked is silently ignored.
        """
        for _fname, spec in self.frames.items():
            _safe_unlink_shm(spec.values.shm_name)


def _safe_unlink_shm(name: str) -> None:
    try:
        shm = shared_memory.SharedMemory(name=name)
        shm.close()
        shm.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        # Best-effort. A leaked SHM segment on /dev/shm reclaims at reboot.
        pass


# ---------------------------------------------------------------------------
# Coordinator side — publish an omics dict to SHM
# ---------------------------------------------------------------------------

def publish_omics_to_shm(omics: dict) -> SharedOmicsHandle:
    """Copy each DataFrame's values into shared memory; return a small handle.

    The `omics` dict contains DataFrames + one plain DataFrame (`model_df`)
    used for metadata. We wrap every DataFrame the same way. The 15+ omics
    frames all have numeric dtypes (float32 / int8); model_df is small and
    string-heavy so we send it via `extras_pickle`.
    """
    handle = SharedOmicsHandle()
    extras: dict[str, Any] = {}
    for name, obj in omics.items():
        if not isinstance(obj, pd.DataFrame):
            extras[name] = obj
            continue
        # model_df: small + string-heavy → send via pickle in extras
        if name == "model_df" or obj.select_dtypes(include=["object"]).shape[1] > 0:
            extras[name] = obj
            continue
        # Numeric DataFrame: publish values to SHM, keep labels in-handle
        values = np.ascontiguousarray(obj.values)
        shm_name = f"e5omics_{uuid.uuid4().hex[:12]}_{name}"
        shm = shared_memory.SharedMemory(create=True, size=values.nbytes,
                                             name=shm_name)
        # Copy values into the SHM buffer, viewed as the same dtype/shape
        buf = np.ndarray(values.shape, dtype=values.dtype, buffer=shm.buf)
        buf[:] = values
        shm.close()  # keep segment alive; workers open by name
        handle.frames[name] = _SharedFrameSpec(
            values=_SharedArraySpec(
                shm_name=shm_name,
                shape=values.shape,
                dtype=values.dtype.str,
            ),
            index_pickle=pickle.dumps(obj.index, protocol=pickle.HIGHEST_PROTOCOL),
            columns_pickle=pickle.dumps(obj.columns, protocol=pickle.HIGHEST_PROTOCOL),
        )
    handle.extras_pickle = pickle.dumps(extras, protocol=pickle.HIGHEST_PROTOCOL)
    return handle


# ---------------------------------------------------------------------------
# Worker side — attach to SHM, reconstruct DataFrames
# ---------------------------------------------------------------------------

# Module-level cache: SHM handles are held for the life of the worker so the
# ndarray views stay valid. Attaching once at init avoids the cost of
# opening/closing per-gene.
_ATTACHED_SHM: dict[str, shared_memory.SharedMemory] = {}


def attach_omics_from_shm(handle: SharedOmicsHandle) -> dict:
    """Reconstruct the omics dict from the handle. Numeric DataFrames are
    zero-copy views over the shared memory buffers; extras are unpickled.
    """
    omics: dict = {}
    for name, spec in handle.frames.items():
        shm = shared_memory.SharedMemory(name=spec.values.shm_name)
        _ATTACHED_SHM[name] = shm  # keep alive for the worker's lifetime
        dtype = np.dtype(spec.values.dtype)
        arr = np.ndarray(spec.values.shape, dtype=dtype, buffer=shm.buf)
        index = pickle.loads(spec.index_pickle)
        columns = pickle.loads(spec.columns_pickle)
        df = pd.DataFrame(arr, index=index, columns=columns, copy=False)
        omics[name] = df
    extras = pickle.loads(handle.extras_pickle) if handle.extras_pickle else {}
    for name, val in extras.items():
        omics[name] = val
    return omics


def detach_all() -> None:
    """Called on worker exit (best-effort). Detaches from SHM without unlinking.
    Coordinator owns unlink."""
    for name, shm in list(_ATTACHED_SHM.items()):
        try:
            shm.close()
        except Exception:
            pass
    _ATTACHED_SHM.clear()
