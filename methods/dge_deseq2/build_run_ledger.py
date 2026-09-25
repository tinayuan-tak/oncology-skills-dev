"""dge_deseq2.build_run_ledger — the generated, self-checking batch run ledger.

S5 (github analysis-methods#698, the last child of parent #690). Produces
``run_ledger.json``: one row per catalogued dge_deseq2 derived product, with

    catalog_id, indication, substrate, contrast, role, config_hash, git_sha,
    run_at, product_uri, qc_status  (+ per-row reconciliation flags)

The ledger is **generated** (never hand-maintained) and **self-checking**: it
reconciles the declared config intent against actuality over THREE sources, the
way ``derive_pancan_stack.assert_roster_matches_published`` reconciles the
pancan roster against the published sensitivity prefixes — but generalised to
three sources and to the whole dge_deseq2 product universe:

  (a) the S3 ``data-catalog/derived/`` product prefixes,
  (b) the data-catalog derived manifests whose ``notebook:`` is under
      ``methods/dge_deseq2/`` (the authoritative "authored by this method" set),
  (c) the config intent roster (``config.run_ledger_intent`` — the new
      substrate axis added in S5).

``--self-check`` REDS on ANY asymmetry between the three:

  * present-not-declared   — a product on S3 / in the catalog that the config
                             intent does not declare (incl. *manifest-without-
                             config*: a dge_deseq2 manifest missing from intent,
                             and *s3-orphan*: a dge-shaped S3 prefix with no
                             manifest at all).
  * declared-not-present   — an intent cell with no manifest, or a manifest
                             whose S3 prefix is absent.
  * qc-failure             — a product whose parquet fails an INDEPENDENTLY
                             RE-DERIVED minimal QC (row-count > 0, the value
                             column not all-NaN — the documented all-NaN case —
                             and a per-family sign / positivity sanity check).

The reconciliation core is pure and provider-injectable; the config↔manifest
half runs fully OFFLINE (no creds) so it is the CI-enforceable acceptance. The
S3-prefix presence check and the qc re-derivation are the live layer (they read
S3), so they are exercised by a local live test and skip cleanly offline. A
self-declared ``qc_status`` would be green-for-the-wrong-reason — every
``pass`` here is earned by actually reading the product's bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from .config import _CONFIG_PATH, run_ledger_intent
from .emit_data_package import _SUBSTRATE_INFIX, adj_vs_gtex_catalog_id, prefix_stem_of

# The data-catalog clone (env override + portable sibling default) — same resolution the read
# package uses, so the ledger reads the manifests the rest of the method reads.
from .read import DATA_CATALOG

DGE_NOTEBOOK_PREFIX = "methods/dge_deseq2/"

# id patterns that a dge_deseq2 S3 prefix takes. Used ONLY to spot a dge-shaped prefix that has no
# manifest at all (an uploaded-but-uncatalogued orphan). A prefix that matches one of these but is
# owned by ANOTHER method's manifest (e.g. sclc-…-sensitivity-v1, authored by methods/sclc_dge_…)
# is NOT ours and is skipped — the authoritative universe is the notebook-filtered manifest set.
_DGE_ID_PATTERNS = tuple(
    re.compile(p)
    for p in (
        r"^[a-z]+-dge-tumor-vs-normal-sensitivity(-xenatoil)?-v1$",
        r"^[a-z]+-dge-tumor-vs-normal-sensitivity-by-subgroup-v1$",
        r"^[a-z]+-dge-adj-vs-gtex(-xenatoil)?-v1$",
        r"^pancan-dge-tumor-vs-normal-v1$",
        r"^dge-deseq2-qc-index-v1$",
    )
)

_SINGLETON_CONTRAST = {
    "pancan_rollup": "pancan-rollup",
    "qc_index": "qc-index",
    "reference_gene_lengths": "gene-lengths",
}


def _looks_like_dge_prefix(prefix: str) -> bool:
    return any(pat.match(prefix) for pat in _DGE_ID_PATTERNS)


# --------------------------------------------------------------------------- #
# (c) config intent -> expected products
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ExpectedProduct:
    catalog_id: str
    indication: str | None
    substrate: str | None  # "recount3" | "xena_toil" | None
    contrast: str
    role: str


def _sensitivity_id(indication: str, substrate: str) -> str:
    return f"{indication.lower()}-dge-tumor-vs-normal-sensitivity{_SUBSTRATE_INFIX[substrate]}-v1"


def _subgroup_id(indication: str) -> str:
    return f"{indication.lower()}-dge-tumor-vs-normal-sensitivity-by-subgroup-v1"


def expected_products(intent: dict | None = None) -> dict[str, ExpectedProduct]:
    """Project the config intent roster into the expected ``{catalog_id -> ExpectedProduct}`` map.

    Fail-loud on a duplicate id (two intent cells that would collide) — a silently
    de-duplicated roster is exactly the kind of hole the reconciliation exists to close.
    """
    if intent is None:
        intent = run_ledger_intent()
    out: dict[str, ExpectedProduct] = {}

    def _add(p: ExpectedProduct) -> None:
        if p.catalog_id in out:
            raise ValueError(f"duplicate expected product id {p.catalog_id!r} in run_ledger_intent")
        out[p.catalog_id] = p

    for substrate, inds in intent.get("sensitivity", {}).items():
        role = "verdict-input" if substrate == "recount3" else "secondary-diagnostic"
        for ind in inds:
            _add(ExpectedProduct(_sensitivity_id(ind, substrate), ind.upper(), substrate, "tumor-vs-normal", role))
    for substrate, inds in intent.get("adj_vs_gtex", {}).items():
        for ind in inds:
            _add(
                ExpectedProduct(
                    adj_vs_gtex_catalog_id(ind, substrate),
                    ind.upper(),
                    substrate,
                    "adjacent-vs-gtex",
                    "secondary-diagnostic",
                )
            )
    for substrate, inds in intent.get("subgroup", {}).items():
        for ind in inds:
            _add(
                ExpectedProduct(
                    _subgroup_id(ind), ind.upper(), substrate, "tumor-vs-normal-by-subgroup", "stratified-diagnostic"
                )
            )
    for s in intent.get("singletons", []):
        role = s["role"]
        _add(ExpectedProduct(s["id"], None, s.get("substrate"), _SINGLETON_CONTRAST.get(role, role), role))
    return out


# --------------------------------------------------------------------------- #
# (b) data-catalog manifests
# --------------------------------------------------------------------------- #
@dataclass
class CatalogedProduct:
    catalog_id: str
    notebook: str
    s3_uri: str | None
    git_commit: str | None
    created_date: str | None
    indication: str | None
    substrate_raw: str | None


def scan_manifests(catalog_root: Path) -> tuple[dict[str, CatalogedProduct], set[str]]:
    """Scan ``manifests/derived/*.yaml``.

    Returns ``(dge_products, all_stems)`` where ``dge_products`` are the manifests whose
    ``notebook:`` is under ``methods/dge_deseq2/`` (keyed by id) and ``all_stems`` is the set of
    S3 prefix stems catalogued by ANY manifest (used to tell a truly-uncatalogued S3 orphan from a
    prefix owned by another method).
    """
    derived = Path(catalog_root) / "manifests" / "derived"
    if not derived.is_dir():
        raise FileNotFoundError(f"data-catalog derived manifests dir not found: {derived}")
    dge: dict[str, CatalogedProduct] = {}
    all_stems: set[str] = set()
    for p in sorted(derived.glob("*.yaml")):
        d = yaml.safe_load(p.read_text())
        if not isinstance(d, dict) or "id" not in d:
            continue
        s3_uri = d.get("s3_uri")
        if isinstance(s3_uri, str):
            try:
                all_stems.add(prefix_stem_of(s3_uri))
            except ValueError:
                pass
        nb = str(d.get("notebook", ""))
        if not nb.startswith(DGE_NOTEBOOK_PREFIX):
            continue
        params = d.get("parameters") or {}
        created = d.get("created_date")
        dge[d["id"]] = CatalogedProduct(
            catalog_id=d["id"],
            notebook=nb,
            s3_uri=s3_uri if isinstance(s3_uri, str) else None,
            git_commit=d.get("git_commit"),
            created_date=str(created) if created is not None else None,
            indication=params.get("indication"),
            substrate_raw=params.get("substrate"),
        )
    return dge, all_stems


def _normalize_substrate(raw: str | None) -> str | None:
    if not raw:
        return None
    low = raw.lower()
    if "recount3" in low:
        return "recount3"
    if "xena" in low or "toil" in low:
        return "xena_toil"
    return None


# --------------------------------------------------------------------------- #
# (a) S3 present set
# --------------------------------------------------------------------------- #
def dge_prefixes_on_s3(all_prefixes: set[str], all_stems: set[str], dge_ids: set[str]) -> set[str]:
    """From every derived/ prefix on S3, keep the dge_deseq2-relevant ones.

    A prefix is relevant iff it is a dge_deseq2 manifest's id (``dge_ids``) OR it is dge-SHAPED but
    catalogued by no manifest at all (a genuine uncatalogued orphan). A dge-shaped prefix owned by
    another method's manifest is deliberately excluded.
    """
    relevant: set[str] = set()
    for prefix in all_prefixes:
        if prefix in dge_ids:
            relevant.add(prefix)
        elif _looks_like_dge_prefix(prefix) and prefix not in all_stems:
            relevant.add(prefix)  # dge-shaped but uncatalogued -> a real orphan we must surface
    return relevant


def _real_s3_prefix_lister(catalog_root_unused=None):
    """Live provider: the set of directory basenames under s3://onc-compbio/data-catalog/derived/."""
    import pyarrow.fs as pafs

    from .read import _get_s3fs

    s3 = _get_s3fs()
    base = "onc-compbio/data-catalog/derived"
    selector = pafs.FileSelector(base, recursive=False, allow_not_found=True)
    return {info.base_name for info in s3.get_file_info(selector) if info.type == pafs.FileType.Directory}


# --------------------------------------------------------------------------- #
# qc re-derivation (independent — never trusts a recorded status)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class QcSpec:
    # columns of which AT LEAST ONE must carry a finite, non-null value (not-all-NaN):
    value_cols: tuple[str, ...]
    # first present of these is checked for BOTH signs among finite values (sign sanity):
    signed_cols: tuple[str, ...] = ()
    # if set, the first present column's finite values must ALL be > 0 (a length can't be <= 0):
    positive_col: str | None = None


_QC_BY_CONTRAST = {
    "tumor-vs-normal": QcSpec(
        value_cols=("log2fc_C", "log2fc_A", "max_abs_log2fc"),
        signed_cols=("log2fc_C", "log2fc_A"),
    ),
    "tumor-vs-normal-by-subgroup": QcSpec(
        value_cols=("log2fc_C", "log2fc_A", "max_abs_log2fc"),
        signed_cols=("log2fc_C", "log2fc_A"),
    ),
    "pancan-rollup": QcSpec(
        value_cols=("log2fc_C", "log2fc_A", "max_abs_log2fc"),
        signed_cols=("log2fc_C", "log2fc_A"),
    ),
    "adjacent-vs-gtex": QcSpec(value_cols=("log2FoldChange", "baseMean"), signed_cols=("log2FoldChange",)),
    "qc-index": QcSpec(value_cols=("n_sig_fdr05", "n_tested", "median_abs_lfc_sig")),
    "gene-lengths": QcSpec(value_cols=("effective_length_bp",), positive_col="effective_length_bp"),
}


def derive_qc_status(df, contrast: str) -> tuple[str, list[str]]:
    """Independently re-derive a minimal QC verdict for a product's dataframe.

    Returns ``(status, reasons)`` where status is ``"pass"`` or ``"fail"``. NEVER reads any
    recorded/self-reported status column — the checks are computed from the numeric bytes:

      * row-count > 0,
      * the value column is not entirely NaN (the documented all-NaN degeneracy),
      * sign sanity: the first present signed column carries BOTH a positive and a negative finite
        value (a global sign collapse / all-one-direction fit is a defect), OR — for a length
        product — every finite value is strictly positive.
    """
    import pandas as pd

    spec = _QC_BY_CONTRAST.get(contrast)
    reasons: list[str] = []
    if len(df) == 0:
        return "fail", ["zero-rows"]
    if spec is None:
        # Unknown family: only the row-count floor is enforceable.
        return "pass", []

    present_value_cols = [c for c in spec.value_cols if c in df.columns]
    if not present_value_cols:
        return "fail", [f"no value column present (expected one of {list(spec.value_cols)})"]
    if all(df[c].isna().all() for c in present_value_cols):
        reasons.append(f"all value columns entirely NaN ({present_value_cols})")

    signed = next((c for c in spec.signed_cols if c in df.columns), None)
    if signed is not None:
        vals = pd.to_numeric(df[signed], errors="coerce")
        finite = vals[vals.notna() & ~vals.isin([float("inf"), float("-inf")])]
        if len(finite) == 0:
            reasons.append(f"signed column {signed!r} has no finite values")
        elif not ((finite > 0).any() and (finite < 0).any()):
            reasons.append(f"sign sanity: {signed!r} has no sign variation (all one direction)")

    if spec.positive_col and spec.positive_col in df.columns:
        vals = pd.to_numeric(df[spec.positive_col], errors="coerce")
        finite = vals[vals.notna()]
        if len(finite) == 0:
            reasons.append(f"positive column {spec.positive_col!r} has no finite values")
        elif not (finite > 0).all():
            reasons.append(f"positivity: {spec.positive_col!r} has non-positive value(s)")

    return ("fail", reasons) if reasons else ("pass", [])


# --------------------------------------------------------------------------- #
# reconciliation -> ledger rows
# --------------------------------------------------------------------------- #
@dataclass
class LedgerRow:
    catalog_id: str
    indication: str | None
    substrate: str | None
    contrast: str | None
    role: str | None
    config_hash: str
    git_sha: str | None
    run_at: str | None
    product_uri: str | None
    qc_status: str
    reconciled: bool
    divergences: list[str] = field(default_factory=list)


def _config_hash() -> str:
    return "sha256:" + hashlib.sha256(Path(_CONFIG_PATH).read_bytes()).hexdigest()[:16]


def build_ledger(
    expected: dict[str, ExpectedProduct],
    manifests: dict[str, CatalogedProduct],
    s3_prefixes: set[str] | None,
    *,
    config_hash: str | None = None,
) -> list[LedgerRow]:
    """Reconcile the three sources into ledger rows (one per id in their union).

    ``s3_prefixes`` may be ``None`` (offline: skip S3-presence divergences). QC is layered on
    separately by :func:`apply_qc` so this stays pure. Every asymmetry is recorded on the row's
    ``divergences`` and clears ``reconciled``.
    """
    cfg_hash = config_hash or _config_hash()
    keys = sorted(set(expected) | set(manifests) | (s3_prefixes or set()))
    rows: list[LedgerRow] = []
    for cid in keys:
        exp = expected.get(cid)
        man = manifests.get(cid)
        declared = exp is not None
        has_manifest = man is not None
        in_s3 = None if s3_prefixes is None else (cid in s3_prefixes)
        div: list[str] = []

        if not declared:
            if has_manifest:
                div.append("manifest-without-config")
            elif in_s3:
                div.append("s3-orphan-not-declared")
            else:
                div.append("present-not-declared")
        else:
            if not has_manifest:
                div.append("declared-without-manifest")
            if in_s3 is False:
                div.append("catalogued-not-present-in-s3" if has_manifest else "declared-not-present-in-s3")

        # manifest s3_uri stem must equal the id (mirrors S4's three-way anchor).
        if has_manifest and man.s3_uri:
            try:
                if prefix_stem_of(man.s3_uri) != cid:
                    div.append("manifest-s3-uri-stem-mismatch")
            except ValueError:
                div.append("manifest-s3-uri-not-derived")
        # declared substrate must match the manifest's recorded substrate (a silent substrate drift).
        if declared and has_manifest and exp.substrate is not None:
            got = _normalize_substrate(man.substrate_raw)
            if got is not None and got != exp.substrate:
                div.append(f"substrate-mismatch(declared={exp.substrate},manifest={got})")

        rows.append(
            LedgerRow(
                catalog_id=cid,
                indication=(exp.indication if exp else (man.indication if man else None)),
                substrate=(exp.substrate if exp else (_normalize_substrate(man.substrate_raw) if man else None)),
                contrast=(exp.contrast if exp else None),
                role=(exp.role if exp else None),
                config_hash=cfg_hash,
                git_sha=(man.git_commit if man else None),
                run_at=(man.created_date if man else None),
                product_uri=(man.s3_uri if man else None),
                qc_status="unchecked",
                reconciled=not div,
                divergences=div,
            )
        )
    return rows


def apply_qc(rows: list[LedgerRow], reader) -> None:
    """Fill each row's ``qc_status`` by RE-DERIVING QC from the product's parquet.

    ``reader(product_uri) -> DataFrame`` is injectable. A row with no product_uri or whose read
    fails is marked ``skip:<reason>`` (not a pass — an unread product is never silently green). A
    row that is not reconciled keeps its structural failure but QC is still attempted where a uri
    exists, so a divergent row does not mask a QC signal.
    """
    for row in rows:
        if not row.product_uri:
            row.qc_status = "skip:no-product-uri"
            continue
        try:
            df = reader(row.product_uri)
        except Exception as exc:  # noqa: BLE001 - a read failure is a skip, surfaced verbatim
            row.qc_status = f"skip:read-failed:{type(exc).__name__}"
            continue
        status, reasons = derive_qc_status(df, row.contrast or "")
        row.qc_status = "pass" if status == "pass" else "fail:" + "; ".join(reasons)


def self_check_divergences(rows: list[LedgerRow], expected: dict[str, ExpectedProduct]) -> list[str]:
    """Return every divergence message (empty == green).

    Guards the vacuous-ledger failure mode two ways: an empty intent roster is itself a divergence,
    and the ledger row count must equal the reconciled union (a dropped row can't hide).
    """
    msgs: list[str] = []
    if not expected:
        msgs.append("empty intent roster — run_ledger_intent projected zero expected products")
    for row in rows:
        for d in row.divergences:
            msgs.append(f"{row.catalog_id}: {d}")
        if row.qc_status.startswith("fail"):
            msgs.append(f"{row.catalog_id}: qc {row.qc_status}")
    return msgs


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _real_parquet_reader(product_uri: str):
    import pyarrow.parquet as pq

    from .read import _get_s3fs, _s3_uri_to_path

    table = pq.read_table(_s3_uri_to_path(product_uri), filesystem=_get_s3fs())
    return table.to_pandas()


def build_and_check(
    catalog_root: Path,
    *,
    offline: bool = False,
) -> tuple[list[LedgerRow], list[str]]:
    """Build the ledger and compute divergences. Offline skips S3 presence + qc re-derivation."""
    expected = expected_products()
    manifests, all_stems = scan_manifests(catalog_root)
    if offline:
        rows = build_ledger(expected, manifests, s3_prefixes=None)
        for row in rows:
            row.qc_status = "skip:offline"
    else:
        from .read import ensure_aws_profile

        ensure_aws_profile()
        all_prefixes = _real_s3_prefix_lister()
        s3_present = dge_prefixes_on_s3(all_prefixes, all_stems, set(manifests))
        rows = build_ledger(expected, manifests, s3_prefixes=s3_present)
        apply_qc(rows, _real_parquet_reader)
    return rows, self_check_divergences(rows, expected)


def _write_ledger(rows: list[LedgerRow], out: Path) -> None:
    payload = {
        "schema_version": "1",
        "config_hash": rows[0].config_hash if rows else _config_hash(),
        "n_rows": len(rows),
        "n_reconciled": sum(1 for r in rows if r.reconciled),
        "rows": [asdict(r) for r in rows],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build + self-check the dge_deseq2 batch run ledger.")
    ap.add_argument("--out", type=Path, default=Path("run_ledger.json"), help="Where to write run_ledger.json.")
    ap.add_argument(
        "--catalog-root",
        type=Path,
        default=DATA_CATALOG,
        help="data-catalog clone root (default: DATA_CATALOG_ROOT env or portable sibling).",
    )
    ap.add_argument(
        "--offline",
        action="store_true",
        help="Reconcile config <-> manifests only; skip S3 presence + qc re-derivation (no creds).",
    )
    ap.add_argument(
        "--self-check",
        action="store_true",
        help="Exit non-zero if the ledger diverges from actuality (reds on any asymmetry / qc fail).",
    )
    args = ap.parse_args(argv)

    rows, divergences = build_and_check(args.catalog_root, offline=args.offline)
    _write_ledger(rows, args.out)
    print(
        f"[build_run_ledger] wrote {args.out}: {len(rows)} row(s), "
        f"{sum(1 for r in rows if r.reconciled)} reconciled"
        + ("" if args.offline else f", {sum(1 for r in rows if r.qc_status == 'pass')} qc-pass")
    )
    if divergences:
        print(f"[build_run_ledger] {len(divergences)} DIVERGENCE(S):", file=sys.stderr)
        for m in divergences:
            print(f"  - {m}", file=sys.stderr)
        if args.self_check:
            return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
