"""Gene-id re-key VERDICT backtest harness — GATE A's instrument (#761 S4).

The #761 epic re-keys the four-cell DGE loaders from a `gene_symbol`-string
collapse (sum every Ensembl gene sharing a symbol; DROP symbol-less genes) onto
the stable unversioned Ensembl id (`gene_stem`). That collapse feeds DESeq2, so
it is VERDICT-AFFECTING: a target whose symbol currently sums >1 ENSG, or whose
symbol drifted between GENCODE-v23 and Ensembl-116, or whose symbol string was
reused for a different gene, can move its tumor-vs-normal-selectivity verdict.

S4 (this module) is the verdict-NEUTRAL INSTRUMENT a human runs at GATE A to
DECIDE whether the re-key is safe to ship (S5). It does NOT flip the loader's
collapse and it NEVER writes a production product. It:

  1. snapshots the current DGE verdict baseline (``snapshot_verdicts`` over the
     shipped products, via the read layer's own composite reader);
  2. runs the re-keyed loaders to a LOCAL SCRATCH prefix and emits shadow
     products (``emit_shadow_products``; opt-in ``--collapse-key gene_stem`` on
     00_load_recount3.R — see the R side), then points the read layer at them
     via a manifest-id override (``reader_pointed_at_local``);
  3. inner-diffs baseline vs shadow per (target, indication), enumerating every
     moved verdict field (``diff_verdicts``);
  4. attributes each moved verdict to a cause via the gene-id authority flags
     (``attribute_moves`` → symbol_drift / symbol_reuse_conflict /
     ensg_ambiguous), tying every move to the 8,221 drift + 441 reuse universe.

MUTATION TEETH (the load-bearing guard): a re-key that silently drops every
joinable target, or a baseline/shadow with no real verdicts to compare, reads
as "0 verdicts moved = safe" — the most dangerous false green. ``diff_verdicts``
raises ``RekeyJoinError`` on an empty or degenerate baseline↔shadow join instead.

DELIBERATELY OUT OF SCOPE (S5, verdict-affecting, separately authorized): the
projection that makes a stem-collapsed product SYMBOL-READABLE — i.e. how a
symbol backed by >1 stem picks its representative row (an `ensg_ambiguous`
pick-policy) and how a drifted symbol is relabeled. The four-cell driver derives
each product row's `gene_symbol` from the count-matrix rowname
(``deseq2_fit`` → ``gene_symbol = rownames(res)``), so a stem-keyed loader emits
a stem-keyed product; turning that into the symbol-keyed product the verdict
reader consumes is the loader/driver rewire S5 owns. This instrument therefore
consumes SYMBOL-KEYED shadow products through the read layer's manifest override
(the general path), and only ATTRIBUTES ambiguity — it does not resolve it.
"""

from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path
from typing import Iterable, Optional, Sequence

import pandas as pd

from onc_methods.dge_deseq2 import read as _read
from onc_methods.gene_id_authority.product import resolve_symbols_to_gene_ids

# --- verdict surface --------------------------------------------------------
# The read-layer-DERIVED categorical decisions that constitute the tumor-vs-normal
# -selectivity verdict. Pure functions of the sensitivity gene row
# (_classify_selectivity_from_sensitivity / _comparator_concordance /
# _independence_fields), so they move only when the re-key changes the row that
# backs a target — exactly what this harness measures.
CORE_VERDICT_FIELDS: tuple[str, ...] = (
    "selectivity_class",
    "comparator_concordance",
    "selectivity_evidence_independence",
    "dominant_direction",
    "sig_all_cells",
    "discordant",
)
# The all-gene selectivity percentile CLASS is also a verdict-facing categorical,
# but it is ranked against the WHOLE product's log2fc column (not just the target
# row), so its read is cached per manifest_id — see reader_pointed_at_local /
# _clear_read_caches, which must run when switching baseline↔shadow (both share
# the manifest_id `{indication}-dge-tumor-vs-normal-sensitivity-v1`).
PERCENTILE_VERDICT_FIELDS: tuple[str, ...] = ("selectivity_allgene_percentile_class",)
VERDICT_FIELDS: tuple[str, ...] = CORE_VERDICT_FIELDS + PERCENTILE_VERDICT_FIELDS

# selectivity_class values that are NOT a real verdict — a product that was not
# read (absent / inaccessible) resolves to one of these. A baseline or shadow
# made ENTIRELY of these has nothing to certify: comparing it would report "0
# moved" vacuously, so diff_verdicts fails loud on it (the degenerate-join teeth).
_NON_VERDICT_CLASSES = frozenset({None, "data_unavailable", "not_applicable"})

PROD_BUCKET = "onc-compbio"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_R_LIVE = _REPO_ROOT / "onc_methods" / "dge_deseq2" / "r" / "live"


class RekeyBacktestError(RuntimeError):
    """A misuse of the backtest harness (e.g. a shadow emit aimed at prod)."""


class RekeyJoinError(ValueError):
    """The baseline↔shadow verdict join is empty or degenerate.

    Raised instead of returning an empty diff that a caller would misread as
    "the re-key moved no verdicts, so it is safe" — the vacuous green this
    harness exists to prevent.
    """


# --- (1) snapshot -----------------------------------------------------------
def _clear_read_caches(read_module=_read) -> None:
    """Drop the read layer's per-manifest lru caches.

    The percentile nulls are cached by manifest_id (+ column), and baseline and
    shadow products share the SAME manifest_id, so a stale cache would make the
    shadow percentile class equal to the baseline's — masking or fabricating a
    move. Call this whenever the bytes behind a manifest_id change (i.e. every
    baseline↔shadow switch)."""
    for name in ("_allgene_log2fc_null", "_sensitivity_cell_null"):
        fn = getattr(read_module, name, None)
        cache_clear = getattr(fn, "cache_clear", None)
        if cache_clear is not None:
            cache_clear()


def read_verdict(target: str, indication: str, *, read_module=_read) -> dict:
    """The verdict fields for one (target, indication) via the composite reader.

    ``read_tumor_vs_normal_selectivity`` never returns None (it yields
    selectivity_class="data_unavailable" when the product is inaccessible), so
    this always returns a full record."""
    v = read_module.read_tumor_vs_normal_selectivity(target, indication)
    out = {"target": target, "indication": indication}
    for f in VERDICT_FIELDS:
        out[f] = v.get(f)
    out["gene_id"] = v.get("gene_id")
    out["gene_stem"] = v.get("gene_stem")
    out["_data_source"] = v.get("_data_source")
    return out


def snapshot_verdicts(
    pairs: Iterable[tuple[str, str]],
    *,
    read_module=_read,
    clear_caches: bool = True,
) -> pd.DataFrame:
    """Snapshot the verdict fields for every (target, indication) in ``pairs``.

    Returns a DataFrame indexed by (target, indication). Use once over the
    shipped products for the baseline, and again with ``read_module`` pointed at
    the shadow products (see ``reader_pointed_at_local``) for the shadow. Clears
    the read layer's manifest caches first so a prior snapshot cannot leak."""
    if clear_caches:
        _clear_read_caches(read_module)
    rows = [read_verdict(t, i, read_module=read_module) for (t, i) in pairs]
    if not rows:
        return pd.DataFrame(
            columns=["target", "indication", *VERDICT_FIELDS, "gene_id", "gene_stem", "_data_source"]
        ).set_index(["target", "indication"])
    return pd.DataFrame(rows).set_index(["target", "indication"])


# --- (3) diff ---------------------------------------------------------------
def _is_na(v) -> bool:
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _equal(a, b) -> bool:
    """Value equality treating NA==NA as equal (a shared absence is not a move)."""
    a_na, b_na = _is_na(a), _is_na(b)
    if a_na or b_na:
        return a_na and b_na
    return a == b


def _n_real_verdicts(df: pd.DataFrame) -> int:
    """Rows whose selectivity_class is a real verdict (not absent/unavailable)."""
    if "selectivity_class" not in df.columns or len(df) == 0:
        return 0
    col = df["selectivity_class"]
    return int(sum(1 for v in col if not _is_na(v) and v not in _NON_VERDICT_CLASSES))


def diff_verdicts(
    baseline: pd.DataFrame,
    shadow: pd.DataFrame,
    *,
    fields: Sequence[str] = VERDICT_FIELDS,
    min_shared: int = 1,
) -> pd.DataFrame:
    """Inner-diff baseline vs shadow per (target, indication); enumerate moves.

    Returns a long-form frame [target, indication, field, baseline_value,
    shadow_value] with one row per MOVED field.

    FAIL-LOUD (the mutation teeth) — raises ``RekeyJoinError`` when the join is
    empty or degenerate, rather than returning an empty diff that reads as "0
    verdicts moved = safe":
      * either side is empty;
      * fewer than ``min_shared`` (target, indication) keys are shared — a re-key
        that drops every joinable target;
      * either side has NO real verdict among the shared keys (all
        absent/data_unavailable) — nothing to certify.
    """
    if len(baseline) == 0 or len(shadow) == 0:
        raise RekeyJoinError(
            f"empty snapshot(s): baseline={len(baseline)} shadow={len(shadow)} row(s). "
            "Refusing to report '0 verdicts moved' from an empty backtest."
        )
    shared = baseline.index.intersection(shadow.index)
    if len(shared) < min_shared:
        raise RekeyJoinError(
            f"baseline↔shadow (target, indication) join is degenerate: "
            f"{len(baseline)} baseline × {len(shadow)} shadow row(s) share only "
            f"{len(shared)} key(s) (< min_shared={min_shared}). A re-key that drops "
            "every joinable target is not a '0 moved = safe' result — it is a broken join."
        )
    b = baseline.loc[shared, list(fields)]
    s = shadow.loc[shared, list(fields)]
    n_real_b = _n_real_verdicts(baseline.loc[shared])
    n_real_s = _n_real_verdicts(shadow.loc[shared])
    if n_real_b == 0 or n_real_s == 0:
        raise RekeyJoinError(
            "no real verdicts to compare across the "
            f"{len(shared)} shared key(s): baseline has {n_real_b} and shadow has "
            f"{n_real_s} non-'data_unavailable' selectivity_class value(s). A backtest "
            "over products that could not be read certifies nothing — refusing to "
            "report it as '0 moved'."
        )
    records = []
    for key in shared:
        tgt, ind = key
        for f in fields:
            bv, sv = b.loc[key, f], s.loc[key, f]
            if not _equal(bv, sv):
                records.append(
                    {
                        "target": tgt,
                        "indication": ind,
                        "field": f,
                        "baseline_value": bv,
                        "shadow_value": sv,
                    }
                )
    return pd.DataFrame(records, columns=["target", "indication", "field", "baseline_value", "shadow_value"])


# --- (4) attribution --------------------------------------------------------
_ATTRIBUTION_COLUMNS = (
    "gene_id",
    "n_authority_genes",
    "mapped",
    "ensg_ambiguous",
    "symbol_drift",
    "symbol_reuse_conflict",
    "attributed_cause",
)


def _flag_true(v) -> bool:
    """True iff an authority boolean flag is truthy, tolerant of dtype.

    ``resolve_symbols_to_gene_ids`` emits ``symbol_drift`` / ``symbol_reuse_conflict``
    as a pandas ``bool`` column when no row is NA (→ numpy ``bool_`` scalars) but as
    ``object`` (python bools) when some row is NA. An identity check (``v is True``)
    silently reads ``numpy.True_`` as False, which would mislabel every real
    drift/reuse-caused move as ``unattributed`` in the GATE-A report. NA (unmapped /
    ambiguous rows, where the flag is undefined) is False."""
    if v is True:
        return True
    try:
        if pd.isna(v):
            return False
    except (TypeError, ValueError):
        pass
    return bool(v)


def _cause(mapped: bool, ambiguous: bool, drift, reuse) -> str:
    """Priority-ordered cause label for a moved verdict.

    ``ensg_ambiguous`` first because it NULLS gene_id (hence drift/reuse are
    unknowable for it); then the cross-release symbol hazards; then a symbol the
    authority does not carry in this substrate's namespace."""
    if not mapped:
        return "unmapped_symbol"
    if ambiguous:
        return "ensg_ambiguous"
    if _flag_true(reuse):
        return "symbol_reuse_conflict"
    if _flag_true(drift):
        return "symbol_drift"
    return "unattributed"


def attribute_moves(
    moves: pd.DataFrame,
    *,
    authority: Optional[pd.DataFrame] = None,
    substrate: str = "recount3",
) -> pd.DataFrame:
    """Attach the gene-id authority cause of each moved verdict.

    Resolves every moved target's symbol through
    ``resolve_symbols_to_gene_ids`` (in the substrate's own symbol namespace) and
    adds the authority flags plus a single ``attributed_cause`` per row, tying
    the move to the drift / reuse / ambiguity universe the authority quantifies.
    """
    if authority is None:
        from onc_methods.gene_id_authority.loader import load_gene_id_authority

        authority = load_gene_id_authority()

    empty_cols = list(moves.columns) + list(_ATTRIBUTION_COLUMNS)
    if len(moves) == 0:
        return pd.DataFrame(columns=empty_cols)

    targets = list(dict.fromkeys(str(t) for t in moves["target"]))
    res = resolve_symbols_to_gene_ids(targets, substrate, authority).set_index("gene_symbol")

    out = moves.copy()
    gene_id, n_auth, mapped, ambiguous, drift, reuse, cause = [], [], [], [], [], [], []
    for t in out["target"]:
        r = res.loc[str(t)]
        m = bool(r["mapped"])
        amb = bool(r["ensg_ambiguous"])
        d, u = r["symbol_drift"], r["symbol_reuse_conflict"]
        gene_id.append(r["gene_id"])
        n_auth.append(int(r["n_authority_genes"]))
        mapped.append(m)
        ambiguous.append(amb)
        drift.append(d)
        reuse.append(u)
        cause.append(_cause(m, amb, d, u))
    out["gene_id"] = gene_id
    out["n_authority_genes"] = n_auth
    out["mapped"] = mapped
    out["ensg_ambiguous"] = ambiguous
    out["symbol_drift"] = drift
    out["symbol_reuse_conflict"] = reuse
    out["attributed_cause"] = cause
    return out


def build_verdict_delta_report(
    baseline: pd.DataFrame,
    shadow: pd.DataFrame,
    *,
    authority: Optional[pd.DataFrame] = None,
    substrate: str = "recount3",
    fields: Sequence[str] = VERDICT_FIELDS,
) -> pd.DataFrame:
    """The GATE-A verdict-delta report: every moved verdict field, attributed.

    Composition of ``diff_verdicts`` (with its fail-loud teeth) and
    ``attribute_moves``. An empty (well-formed, non-degenerate) diff returns an
    empty attributed frame — a genuine "the re-key moved nothing" result, which
    only reaches here AFTER the degenerate-join teeth have passed."""
    moves = diff_verdicts(baseline, shadow, fields=fields)
    return attribute_moves(moves, authority=authority, substrate=substrate)


def summarize_report(report: pd.DataFrame) -> dict:
    """A small dict summary of an attributed verdict-delta report (for the log)."""
    n_moves = int(len(report))
    moved_targets = sorted({str(t) for t in report["target"]}) if n_moves else []
    by_cause = report["attributed_cause"].value_counts().to_dict() if n_moves else {}
    by_field = report["field"].value_counts().to_dict() if n_moves else {}
    summary = {
        "n_moved_fields": n_moves,
        "n_moved_targets": len(moved_targets),
        "moved_targets": moved_targets,
        "moves_by_cause": {str(k): int(v) for k, v in by_cause.items()},
        "moves_by_field": {str(k): int(v) for k, v in by_field.items()},
    }
    summary["selectivity_class_transitions"] = transition_counts(report)
    return summary


# --- (5) transition decomposition (#847 GATE-A v2) --------------------------
# The verdict-delta report enumerates every MOVED field. For the S5 decision the
# sharper cut is what KIND of move a target's headline selectivity_class made:
#   appear       — was absent/data_unavailable, now a real verdict (a gene the
#                  arm newly resolves);
#   disappear    — was a real verdict, now absent/data_unavailable (e.g. an
#                  ambiguous symbol stripped by a no-pick re-key);
#   change_class — a real verdict changed to a DIFFERENT real verdict
#                  (a genuine re-classification, not a subtraction).
# These are counted per arm-diff (C0->C1 identity, C1->C2 universe) so the report
# can say how much of each cause is subtractive vs re-classifying.
CLASS_APPEAR = "appear"
CLASS_DISAPPEAR = "disappear"
CLASS_CHANGE = "change_class"
CLASS_OTHER = "other"


def _is_non_verdict(v) -> bool:
    """True iff a selectivity_class value is NOT a real verdict (absent /
    data_unavailable / not_applicable)."""
    return _is_na(v) or v in _NON_VERDICT_CLASSES


def classify_class_transition(baseline_value, shadow_value) -> str:
    """Bucket a selectivity_class move into appear / disappear / change_class."""
    b_nv = _is_non_verdict(baseline_value)
    s_nv = _is_non_verdict(shadow_value)
    if b_nv and not s_nv:
        return CLASS_APPEAR
    if s_nv and not b_nv:
        return CLASS_DISAPPEAR
    if not b_nv and not s_nv:
        return CLASS_CHANGE
    return CLASS_OTHER  # non-verdict -> non-verdict (should not surface as a move)


def transition_counts(moves: pd.DataFrame) -> dict:
    """Count selectivity_class transitions in a moves/report frame.

    Returns {appear, disappear, change_class, other} and, when the frame carries
    the ``attributed_cause`` column, a nested ``by_cause`` cross-tab
    {cause: {transition: n}}. Non-selectivity_class fields are ignored (they are
    reported separately by ``moves_by_field``)."""
    base = {CLASS_APPEAR: 0, CLASS_DISAPPEAR: 0, CLASS_CHANGE: 0, CLASS_OTHER: 0}
    if len(moves) == 0 or "field" not in moves.columns:
        return {**base, "by_cause": {}}
    sel = moves[moves["field"] == "selectivity_class"]
    by_cause: dict[str, dict[str, int]] = {}
    has_cause = "attributed_cause" in sel.columns
    for _, row in sel.iterrows():
        t = classify_class_transition(row["baseline_value"], row["shadow_value"])
        base[t] += 1
        if has_cause:
            c = str(row["attributed_cause"])
            by_cause.setdefault(c, dict.fromkeys(base, 0))
            by_cause[c][t] += 1
    return {**base, "by_cause": {k: {kk: int(vv) for kk, vv in v.items()} for k, v in by_cause.items()}}


# --- (2) shadow generation — LOCAL scratch only, NEVER prod -----------------
def assert_scratch_prefix(prefix) -> Path:
    """Refuse any output prefix that could be a production write.

    The harness produces shadow products for measurement ONLY; it must never
    touch a prod S3 object or the canonical data-catalog derived tree. A shadow
    prefix must be a LOCAL path outside those."""
    s = str(prefix)
    norm = s.replace("\\", "/")
    if norm.startswith("s3://"):
        raise RekeyBacktestError(
            f"shadow emit target {s!r} is an S3 URI; this harness writes only to a LOCAL "
            "scratch dir and NEVER to production S3."
        )
    if PROD_BUCKET in norm or "data-catalog/derived" in norm:
        raise RekeyBacktestError(
            f"shadow emit target {s!r} resolves under the production data-catalog "
            f"({PROD_BUCKET!r} / data-catalog/derived); refusing — S4 is verdict-neutral "
            "and performs no prod write. Point it at a scratch dir."
        )
    return Path(s)


def rekey_loader_argv(
    *,
    config: str,
    out_rds: str,
    collapse_key: str = "gene_stem",
    gene_universe: str = "all",
    rscript: str = "Rscript",
    extra: Sequence[str] = (),
) -> list[str]:
    """Argv for the re-keyed recount3 loader (00_load_recount3.R --collapse-key).

    ``collapse_key='gene_stem'`` is the re-key under test; the loader's default
    ('gene_symbol') is byte-identical to production. ``gene_universe`` is the
    #847 GATE-A-v2 decomposition toggle, consulted only on the stem path:
    ``'all'`` (default, shipped stem behaviour = symbol-less retained = the C2
    arm) or ``'has_symbol'`` (restrict to the production gene_symbol gene set at
    ENSG grain, distinct genes NOT summed = the C1 arm). Emitting it explicitly
    on every argv keeps the arm self-documenting; the default preserves prior
    behaviour on both keys. Pure (builds argv only) so the wiring is
    unit-testable without invoking R."""
    if collapse_key not in ("gene_symbol", "gene_stem"):
        raise RekeyBacktestError(f"collapse_key must be 'gene_symbol' or 'gene_stem', got {collapse_key!r}")
    if gene_universe not in ("all", "has_symbol"):
        raise RekeyBacktestError(f"gene_universe must be 'all' or 'has_symbol', got {gene_universe!r}")
    assert_scratch_prefix(out_rds)
    return [
        rscript,
        "--vanilla",
        str(_R_LIVE / "00_load_recount3.R"),
        "--config",
        config,
        "--out",
        out_rds,
        "--collapse-key",
        collapse_key,
        "--gene-universe",
        gene_universe,
        *extra,
    ]


def driver_argv(
    *,
    in_rds: str,
    out_dir: str,
    rscript: str = "Rscript",
    extra: Sequence[str] = (),
) -> list[str]:
    """Argv for the four-cell driver (06_four_cell_driver.R) over a scratch bundle."""
    assert_scratch_prefix(out_dir)
    return [
        rscript,
        "--vanilla",
        str(_R_LIVE / "06_four_cell_driver.R"),
        "--in",
        in_rds,
        "--out-dir",
        out_dir,
        *extra,
    ]


def emit_shadow_products(
    *,
    config: str,
    scratch_dir,
    collapse_key: str = "gene_stem",
    gene_universe: str = "all",
    rscript: str = "Rscript",
    check: bool = True,
) -> Path:
    """Run the re-keyed loader + four-cell driver to a LOCAL scratch dir.

    GATE-A orchestration (heavy: DESeq2 is R-only). Returns the product dir under
    ``scratch_dir``. ``gene_universe`` selects the stem-path gene set (C1
    'has_symbol' vs C2 'all'; #847). Guarded by ``assert_scratch_prefix`` so it
    can never write a prod object. Not exercised in CI (needs the R/Bioconductor
    env + real substrate); its argv construction and the prod-write guard ARE
    tested."""
    root = assert_scratch_prefix(scratch_dir)
    root.mkdir(parents=True, exist_ok=True)
    out_rds = str(root / "bundle.rds")
    out_dir = str(root / "products")
    load_cmd = rekey_loader_argv(
        config=config, out_rds=out_rds, collapse_key=collapse_key, gene_universe=gene_universe, rscript=rscript
    )
    subprocess.run(load_cmd, check=check)
    drive_cmd = driver_argv(in_rds=out_rds, out_dir=out_dir, rscript=rscript)
    subprocess.run(drive_cmd, check=check)
    return Path(out_dir)


@contextlib.contextmanager
def reader_pointed_at_local(product_by_manifest_id: dict[str, str], *, read_module=_read):
    """Point the read layer at LOCAL scratch products for the duration.

    ``product_by_manifest_id`` maps a manifest_id (e.g.
    ``coadread-dge-tumor-vs-normal-sensitivity-v1``) to a local
    ``sensitivity.parquet`` path. Monkeypatches the reader's resolution seams
    (``_load_manifest`` / ``_get_s3fs`` / ``ensure_aws_profile`` /
    ``_s3_uri_to_path``) to a local filesystem and clears the per-manifest caches
    on enter AND exit so no null leaks across the baseline↔shadow switch. The
    manifest-id override the brief calls for; usable both in tests and in a
    GATE-A run reading scratch products. Restores every seam on exit."""
    import pyarrow.fs as pafs

    saved = {
        name: getattr(read_module, name)
        for name in ("_load_manifest", "_get_s3fs", "ensure_aws_profile", "_s3_uri_to_path")
    }

    def _load_manifest(manifest_id: str) -> dict:
        try:
            uri = product_by_manifest_id[manifest_id]
        except KeyError:
            raise FileNotFoundError(f"no scratch product registered for manifest_id {manifest_id!r}") from None
        return {"id": manifest_id, "s3_uri": uri}

    read_module._load_manifest = _load_manifest
    read_module.s3_uri_for = lambda manifest_id: _load_manifest(manifest_id)["s3_uri"]
    read_module._get_s3fs = lambda: pafs.LocalFileSystem()
    read_module.ensure_aws_profile = lambda: None
    read_module._s3_uri_to_path = lambda s3_uri: s3_uri
    _clear_read_caches(read_module)
    try:
        yield read_module
    finally:
        for name, fn in saved.items():
            setattr(read_module, name, fn)
        # s3_uri_for is imported into the reader's namespace from catalog_query.
        with contextlib.suppress(Exception):
            from onc_methods.catalog_query.read import s3_uri_for as _real_s3_uri_for

            read_module.s3_uri_for = _real_s3_uri_for
        _clear_read_caches(read_module)
