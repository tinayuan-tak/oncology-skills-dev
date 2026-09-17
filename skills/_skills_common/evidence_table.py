"""evidence_table.py — the derived readings-table accessor (S1 of the emitted-substrate arc).

NOT an emitted artifact (arc decision #2): this materialises one row per (card, field) reading
from an already-emitted ``evidence_package.json``, ON READ. Because it is derived, the accessor's
OUTPUT SCHEMA — ``READING_COLUMNS`` + per-column dtypes + null semantics — IS the versioned
contract (there is no frozen file to anchor it), pinned by ``READING_SCHEMA_VERSION`` and enforced
by ``tests/test_evidence_table.py``.

Two invariants the tests exist to defend:

  * ZERO field-name literals. Every column derives from ``field_descriptor.describe_summary``; the
    module names no card field. That is the aperture guard: the accessor cannot de-orphan a field
    by hard-coding its name (which would trip the two-sided aperture ratchet in target-contracts).

  * UNMEASURED ⇒ NULL, never 0/""/False. A missing card, an unmeasured field, and a corpus emitted
    without ``--figures`` all produce ``pd.NA`` in the affected columns — never a zero that would
    read as "measured, and it is the bottom of the scale." The gauge columns
    (``level``/``scale``/``distance_to_cut``) and ``availability`` are NULL on today's corpus because
    the emitter does not yet populate the dormant ``gauged_value`` slots / ``claim_record``; they
    fill in as later stages land, with no change to this contract.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from _skills_common import field_descriptor as _fd

READING_SCHEMA_VERSION = "1"

# ── the pinned column contract ──────────────────────────────────────────────────────────────
# Order is load-bearing and asserted literally (never read back off a DataFrame). dtype "string"
# is pandas' nullable string (holds pd.NA); "Float64"/"boolean" are the nullable numeric/bool.
# `value` is object because a reading can be a scalar, a list (per_subgroup_metrics) or a dict.
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("reading_id", "string"),
    ("target", "string"),
    ("indication", "string"),
    ("subtype", "string"),  # NULL at package grain; a per-subgroup arm is a nested reading, not N rows
    ("modality", "string"),  # NULL for modality-blind skills
    ("skill", "string"),
    ("card_id", "string"),
    ("measurement_type", "string"),
    ("field", "string"),
    ("role", "string"),  # ∈ field_descriptor.ROLES (asserted as a SET by the tests)
    ("value", "object"),
    ("level", "string"),  # ordinal band; NULL until the emitter populates gauged_value
    ("scale", "string"),
    ("distance_to_cut", "Float64"),
    ("units", "string"),
    ("direction", "string"),
    ("significance_field", "string"),
    ("measured", "boolean"),
    ("availability", "string"),  # ∈ claim_record._VALID_AVAILABILITY; NULL until claim_record is emitted
    ("card_version", "string"),
    ("resolved_release_digest", "string"),
    ("is_stale", "boolean"),
    ("plot_data_ref", "string"),  # POINTER (path + row count), never inlined rows; NULL when no --figures
)
READING_COLUMNS: tuple[str, ...] = tuple(name for name, _ in _COLUMNS)
_DTYPES: dict[str, str] = dict(_COLUMNS)


# ── non-finite coercion ───────────────────────────────────────────────────────────────────────
def _coerce_nonfinite(obj: Any, counter: list[int]) -> Any:
    """Recursively replace non-finite floats (inf/-inf/nan) with None, counting each. The emitted
    corpus is not strict JSON — 501/504 packages carry NaN — so a naive read would let ±Inf/NaN
    reach a digest or a ranking (``abs(inf)`` wins any argmax). We coerce at load and surface the
    count rather than silently dropping."""
    if isinstance(obj, float):
        if math.isinf(obj) or math.isnan(obj):
            counter[0] += 1
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _coerce_nonfinite(v, counter) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_coerce_nonfinite(v, counter) for v in obj]
    return obj


def _load_package(path: Path) -> tuple[dict, int]:
    raw = json.loads(Path(path).read_text())
    counter = [0]
    return _coerce_nonfinite(raw, counter), counter[0]


# ── context / governance projection (package-level, shared across a package's rows) ────────────
def _skill_of(pkg: dict) -> Optional[str]:
    gb = pkg.get("generated_by")  # e.g. "skills/target-profile@9bc5f66"
    if not isinstance(gb, str):
        return None
    stem = gb.split("@", 1)[0]
    return stem.rsplit("/", 1)[-1] or None


def _context_cols(pkg: dict) -> dict:
    ctx = pkg.get("context") or {}
    target = (ctx.get("target") or {}).get("symbol")
    indication = (ctx.get("indication") or {}).get("oncotree_code")
    return {"target": target, "indication": indication, "skill": _skill_of(pkg)}


def _stale_lookup(pkg: dict) -> dict[str, bool]:
    """manifest_id -> is_stale, folded from governance.resolved_releases (each entry names the
    manifests it `used` + `head` and its own is_stale)."""
    out: dict[str, bool] = {}
    for entry in (pkg.get("governance") or {}).get("resolved_releases", {}).values():
        stale = bool(entry.get("is_stale"))
        for mid in list(entry.get("used") or []) + ([entry["head"]] if entry.get("head") else []):
            out[mid] = out.get(mid, False) or stale
    return out


def _reading_id(target, indication, skill, card_id, field) -> str:
    key = f"{target}|{indication}|{skill}|{card_id}|{field}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


# ── the flattener ──────────────────────────────────────────────────────────────────────────────
def _rows_for_package(pkg: dict) -> list[dict]:
    base = _context_cols(pkg)
    digest = (pkg.get("governance") or {}).get("resolved_release_digest")
    stale = _stale_lookup(pkg)
    rows: list[dict] = []
    for card in pkg.get("cards") or []:
        card_id = card.get("card_id")
        mt = card.get("measurement_type")
        summary = card.get("summary") or {}
        card_stale = any(stale.get(m, False) for m in (card.get("provenance") or {}).get("input_manifest_ids") or [])
        # describe_summary derives role/units/direction/significance_field/measured per field, with
        # NO field name written here — the aperture guard.
        described = _fd.describe_summary(summary, mt)
        for field, d in described.items():
            rows.append(
                {
                    "reading_id": _reading_id(base["target"], base["indication"], base["skill"], card_id, field),
                    "target": base["target"],
                    "indication": base["indication"],
                    "subtype": None,
                    "modality": None,
                    "skill": base["skill"],
                    "card_id": card_id,
                    "measurement_type": d.get("measurement_type") or mt,
                    "field": field,
                    "role": d.get("role"),
                    "value": summary.get(field),
                    "level": None,  # gauged_value dormant on today's corpus
                    "scale": None,
                    "distance_to_cut": None,
                    "units": d.get("units"),
                    "direction": d.get("direction"),
                    "significance_field": d.get("significance_field"),
                    "measured": bool(d.get("measured")),
                    "availability": None,  # claim_record not emitted on today's corpus
                    "card_version": card.get("card_version"),
                    "resolved_release_digest": digest,
                    "is_stale": card_stale,
                    "plot_data_ref": None,  # corpus run without --figures
                }
            )
    return rows


def _frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=list(READING_COLUMNS))
    for col, dtype in _DTYPES.items():
        if dtype == "object":
            continue
        df[col] = df[col].astype(dtype)
    return df


# ── public accessor ────────────────────────────────────────────────────────────────────────────
@dataclass
class EvidenceTable:
    """A queryable view over emitted evidence. ``.readings`` is the one flat grain (a row per
    ``(card, field)``); ``n_nonfinite_coerced`` records how many ±Inf/NaN leaves were coerced to
    None at load (a data-quality signal, surfaced not swallowed)."""

    readings: pd.DataFrame
    n_nonfinite_coerced: int = 0
    schema_version: str = READING_SCHEMA_VERSION

    @classmethod
    def from_package(cls, path: str | Path) -> "EvidenceTable":
        pkg, n_nf = _load_package(Path(path))
        return cls(readings=_frame(_rows_for_package(pkg)), n_nonfinite_coerced=n_nf)

    @classmethod
    def from_corpus(cls, root: str | Path, *, glob: str = "*/evidence_package.json") -> "EvidenceTable":
        rows: list[dict] = []
        n_nf = 0
        for p in sorted(Path(root).glob(glob)):
            pkg, k = _load_package(p)
            rows.extend(_rows_for_package(pkg))
            n_nf += k
        return cls(readings=_frame(rows), n_nonfinite_coerced=n_nf)

    def to_sql(self, query: str):
        """Documented escape hatch: load the readings into an in-memory sqlite and run `query`.
        No file is written (arc decision #2 forbids an emitted artifact)."""
        import sqlite3

        con = sqlite3.connect(":memory:")
        try:
            self.readings.astype(object).where(pd.notna(self.readings), None).to_sql("readings", con, index=False)
            return pd.read_sql_query(query, con)
        finally:
            con.close()


__all__ = ["EvidenceTable", "READING_COLUMNS", "READING_SCHEMA_VERSION"]
