"""Structural lint: reader S3/read paths must not mask transient failures as "no data".

THE BUG CLASS (RD1-RD9, fixed in PR #354)
-----------------------------------------
A reader that reads a per-target DATA product from S3 and wraps the read in a broad
``except Exception: return <empty>`` swallows EVERY failure as "no data" — including a
transient S3 blip, an expired-creds / AccessDenied error, or a broken-env ImportError.
The card then reports ``data_unavailable`` for a live, present target: a SILENT DEAD AXIS.

PR #354 replaced that anti-pattern in ~13 readers with the repo's absence discipline
(``methods/target_id_sidecar.is_definitively_absent``): swallow ONLY a genuine
NoSuchKey / 404 (honest ``data_unavailable``) and RE-RAISE broken-env / transient / creds
errors so the live-read seam surfaces an honest ``_live_read_error`` instead of a dead axis.

WHAT THIS LINT ENFORCES
-----------------------
Statically (via ``ast``, never regex) scan every ``methods/*/*.py`` — the reader/CLI entrypoints
AND the one-level helper modules they call (``derive.py``, ``loader.py``, ``pull.py``, ``*.py``),
since a masking handler in a helper is just as much a silent dead axis as one in ``read.py``.
Flag an ``except`` handler as a VIOLATION when ALL of the following hold:

  1. it is a BROAD catch — bare ``except:`` or ``except Exception[/BaseException] [as e]:``
     (narrow catches like ``except (ValueError, TypeError):`` are never flagged);
  2. its enclosing ``try`` body performs a real S3 / object read (get_object, read_parquet,
     download_file, S3FileSystem, bucket_key_for, ... — see ``_S3_READ_MARKERS``);
  3. the handler body ``return``s an EMPTY result — ``None`` (incl. a bare ``return``), ``{}``,
     ``[]``, ``()``, ``dict()/list()/tuple()/set()``, ``pd.DataFrame(...)``, ``pd.Series(...)``,
     or a tuple/list whose elements are all such empties (e.g. ``return pd.DataFrame(), {}``);
  4. the handler does NOT DISCRIMINATE definitive-absence from transient failure — it neither
       (a) references ``is_definitively_absent``,
       (b) ``raise``s (re-raises the non-definitive branch), nor
       (c) inspects the exception to tell 404 / NoSuchKey from a creds/transient error
           (references ``e.response`` / ``Error`` / ``Code`` / ``NoSuchKey`` / ``__class__`` /
           ``FileNotFoundError`` / ``ClientError`` / ``type(e)`` ...).
     Any one of (a)/(b)/(c) is an acceptable form of the discipline (PR #354 shipped both the
     ``is_definitively_absent`` + ``raise`` shape AND the inline definitive-vs-transient latch).

ESCAPE HATCH (for legitimately-exempt handlers)
-----------------------------------------------
Either mechanism suppresses a finding:

  * INLINE MARKER — put ``# absence-discipline: exempt -- <reason>`` on the ``except`` line (or
    any line inside the handler). Preferred: the exemption lives next to the code.
  * ALLOWLIST — add the handler key ``"<module>/<file>::<qualified_function>"`` to
    ``_ALLOWLIST`` below with a reason string.

BASELINE (pre-existing debt discovered by this lint)
----------------------------------------------------
When introduced, this lint surfaced 55 pre-existing residual handlers across 34 modules that
match the anti-pattern but were OUT OF SCOPE for PR #354 (which curated ~13 high-value,
verdict-bearing readers). They are recorded in ``_BASELINE_RESIDUALS`` so CI is GREEN today and
the debt is VISIBLE and enumerable in-repo. The lint is therefore a RATCHET: any NEW violation
(a handler not already in the baseline / allowlist / marked exempt) FAILS the build. Burn the
baseline down by converting each handler to the ``is_definitively_absent`` discipline and
deleting its baseline entry (a stale entry — no longer a violation — is reported by
``test_absence_discipline_baseline_not_stale``).

The DEFERRED ``cooccurrence_fisher_pancohort`` module is called out separately in
``_DEFERRED_ALLOWLIST`` because its fix is blocked on an active registry collision
(``derive-cooccurrence-fisher-pancohort-v1-1``), not merely un-prioritised.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

# --------------------------------------------------------------------------------------------
# Detector configuration
# --------------------------------------------------------------------------------------------

# The enclosing `try` must touch one of these to be considered an S3 / object-read path. Keeps
# the lint off unrelated broad-excepts (optional-Plotly render blocks, pure in-memory parsing).
_S3_READ_MARKERS = frozenset(
    {
        "get_object",
        "read_table",
        "read_parquet",
        "read_csv",
        "read_json",
        "read_feather",
        "S3FileSystem",
        "s3_client",
        "download_file",
        "download_fileobj",
        "get_bucket",
        "bucket_key_for",
        "bucket_prefix_for",
        "s3_uri_for",
        "sidecar_bucket_key_for",
        "read_resolver_sidecar_map",
        "open_input_stream",
        "ParquetDataset",
        "ParquetFile",
        "list_objects",
        "list_objects_v2",
        "head_object",
    }
)

# Names/attrs whose presence in a handler proves it DISCRIMINATES definitive vs transient.
_DISCRIMINATION_NAMES = frozenset(
    {
        "is_definitively_absent",
        "NoSuchKey",
        "NoSuchBucket",
        "AccessDenied",
        "FileNotFoundError",
        "ClientError",
        "BotoCoreError",
        "EndpointConnectionError",
        "ConnectTimeoutError",
        "ReadTimeoutError",
        "response",
        "errno",
        "__class__",
    }
)
# String literals that likewise prove discrimination (error-code / boto Error["Code"] checks).
_DISCRIMINATION_STRINGS = frozenset({"404", "403", "NoSuchKey", "AccessDenied", "Code", "Error"})

# Inline escape-hatch marker (see module docstring).
_EXEMPT_MARKER = "absence-discipline: exempt"


def _methods_root() -> Path:
    env = os.environ.get("ANALYSIS_METHODS_ROOT")
    if env and (Path(env) / "methods").is_dir():
        return Path(env) / "methods"
    return Path(__file__).resolve().parents[1] / "methods"


def _is_broad_handler(handler: ast.ExceptHandler) -> bool:
    t = handler.type
    if t is None:  # bare `except:`
        return True
    if isinstance(t, ast.Name):
        return t.id in ("Exception", "BaseException")
    if isinstance(t, ast.Tuple):  # `except (Exception, ...):`
        return any(isinstance(e, ast.Name) and e.id in ("Exception", "BaseException") for e in t.elts)
    return False


def _is_empty_atom(v: ast.AST | None) -> bool:
    if v is None:  # bare `return`
        return True
    if isinstance(v, ast.Constant) and v.value is None:  # `return None`
        return True
    if isinstance(v, ast.Dict) and not v.keys:  # `return {}`
        return True
    if isinstance(v, (ast.List, ast.Set)) and not v.elts:  # `return []`
        return True
    if isinstance(v, ast.Tuple) and not v.elts:  # `return ()`
        return True
    if isinstance(v, ast.Call):
        f = v.func
        name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
        if (
            name in ("dict", "list", "tuple", "set", "frozenset", "OrderedDict") and not v.args and not v.keywords
        ):  # `return dict()` / `tuple()`
            return True
        if name.endswith("DataFrame") or name == "Series":  # `return pd.DataFrame(...)`
            return True
    return False


def _is_diagnostic_string(v: ast.AST | None) -> bool:
    """A plain string literal or f-string — a diagnostic breadcrumb, not a data payload."""
    return (isinstance(v, ast.Constant) and isinstance(v.value, str)) or isinstance(v, ast.JoinedStr)


def _is_empty_return_value(v: ast.AST | None) -> bool:
    if _is_empty_atom(v):
        return True
    if isinstance(v, (ast.Tuple, ast.List)) and v.elts:
        # tuple/list of all-empty atoms, e.g. `return pd.DataFrame(), {}`
        if all(_is_empty_atom(e) for e in v.elts):
            return True
        # empty payload + diagnostic error string(s), e.g. `return {}, f"s3_read_failed: {e}"`:
        # the data slot is an empty atom and the remaining slots only NAME the fault in a string.
        # (the `{}`-with-breadcrumb evasion — the return still fails toward absence).
        if any(_is_empty_atom(e) for e in v.elts) and all(
            _is_empty_atom(e) or _is_diagnostic_string(e) for e in v.elts
        ):
            return True
    return False


def _names_and_attrs(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.alias):
            out.add(n.name)
    return out


def _string_constants(node: ast.AST) -> set[str]:
    return {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _is_loader_call_name(name: str) -> bool:
    """A method-local loader entry point — `load_*` / `_load_*` (e.g. `_cli.load_and_classify`,
    `load_model_csv`, `_load_pathways_from_product`). Its S3 read is usually >=2 levels deep, so
    the try body that merely CALLS it carries no `_S3_READ_MARKERS` token of its own."""
    return name.startswith("load_") or name.startswith("_load_")


def _try_calls_loader(try_node: ast.Try) -> bool:
    """True if the try body calls a method-local loader entry point (see `_is_loader_call_name`).

    Closes the 2-deep-loader reachability hole: a seam ``except`` whose try body is just a call
    into a loader helper (``_cli.load_and_classify``, ``load_model_csv``, ...) hides the actual
    S3 read one+ levels down, so the try body has no direct ``_S3_READ_MARKERS`` name. We follow
    the loader call as S3-reaching, matching the one-level-helper intent documented in the header.
    """
    for stmt in try_node.body:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Call):
                f = n.func
                name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
                if _is_loader_call_name(name):
                    return True
    return False


def _try_reads_s3(try_node: ast.Try) -> bool:
    names: set[str] = set()
    for stmt in try_node.body:
        names |= _names_and_attrs(stmt)
    return bool(names & _S3_READ_MARKERS) or _try_calls_loader(try_node)


def _handler_reraises(handler: ast.ExceptHandler) -> bool:
    return any(isinstance(n, ast.Raise) for n in ast.walk(handler))


def _type_check_drives_control_flow(handler: ast.ExceptHandler) -> bool:
    """True if a ``type(...)`` / ``isinstance(...)`` call appears in a CONTROL-FLOW position —
    the test of an ``if`` / ternary, or inside a ``raise`` arm — i.e. the handler actually
    BRANCHES on the exception type.

    A bare ``type(e).__name__`` baked into a diagnostic f-string (``return _empty(f"...{type(e).
    __name__}")``) NAMES the error without branching on it, so it must NOT count as discipline.
    """
    guards: list[ast.AST] = []
    for n in ast.walk(handler):
        if isinstance(n, (ast.If, ast.IfExp)):
            guards.append(n.test)
        elif isinstance(n, ast.Raise):
            guards.append(n)
    for g in guards:
        for n in ast.walk(g):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("type", "isinstance"):
                return True
    return False


def _handler_discriminates(handler: ast.ExceptHandler) -> bool:
    if _names_and_attrs(handler) & _DISCRIMINATION_NAMES:
        return True
    if _string_constants(handler) & _DISCRIMINATION_STRINGS:
        return True
    # `type(...)` / `isinstance(...)` idiom — counts ONLY when it drives control flow (an `if`/
    # ternary test or a `raise` arm), never a bare `type(e).__name__` breadcrumb in an f-string.
    return _type_check_drives_control_flow(handler)


def _handler_returns_empty(handler: ast.ExceptHandler) -> bool:
    return any(isinstance(n, ast.Return) and _is_empty_return_value(n.value) for n in ast.walk(handler))


def _qualname_by_node_id(tree: ast.AST) -> dict[int, str]:
    """Map every AST node id -> the qualified name of its enclosing def (best-effort)."""
    mapping: dict[int, str] = {}

    def walk(node: ast.AST, stack: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = ".".join(stack + [child.name])
                for n in ast.walk(child):
                    mapping.setdefault(id(n), qual)
                walk(child, stack + [child.name])
            elif isinstance(child, ast.ClassDef):
                walk(child, stack + [child.name])
            else:
                walk(child, stack)

    walk(tree, [])
    return mapping


def _handler_span_lines(handler: ast.ExceptHandler, source_lines: list[str]) -> list[str]:
    start = handler.lineno - 1
    end = getattr(handler, "end_lineno", handler.lineno)
    return source_lines[start:end]


def find_violations() -> list[str]:
    """Return the sorted list of violation keys ``"<module>/<file>::<qualified_function>"``.

    A key is emitted per offending handler that is NOT suppressed by the inline escape-hatch
    marker. (Allowlist filtering is applied by the tests, not here.)
    """
    root = _methods_root()
    assert root.is_dir(), f"methods/ not found at {root}"
    violations: list[str] = []
    for rel in sorted(root.glob("*/*.py")):
        source = rel.read_text()
        source_lines = source.splitlines()
        tree = ast.parse(source, filename=str(rel))
        qmap = _qualname_by_node_id(tree)
        relkey = rel.relative_to(root).as_posix()
        for try_node in ast.walk(tree):
            if not isinstance(try_node, ast.Try) or not _try_reads_s3(try_node):
                continue
            for handler in try_node.handlers:
                if not _is_broad_handler(handler):
                    continue
                if not _handler_returns_empty(handler):
                    continue
                if _handler_reraises(handler) or _handler_discriminates(handler):
                    continue
                span = "\n".join(_handler_span_lines(handler, source_lines))
                if _EXEMPT_MARKER in span:  # inline escape hatch
                    continue
                fn = qmap.get(id(handler), "<module>")
                violations.append(f"{relkey}::{fn}")
    return sorted(set(violations))


# --------------------------------------------------------------------------------------------
# Allowlist
# --------------------------------------------------------------------------------------------

# Deferred fix — blocked on an ACTIVE registry collision, not merely un-prioritised. When the
# `derive-cooccurrence-fisher-pancohort-v1-1` workstream lands/goes stale, convert this handler
# to the is_definitively_absent discipline and move/remove the entry.
# cooccurrence_fisher_pancohort/read.py::_load_indexed — CONVERTED (2026-08-22, data-layer
# hardening). `_load_indexed` (broad `except Exception: return pd.DataFrame(), {}` over a
# cached-parquet read) was retired: the reader now streams one target's rows via
# `_read_target_rows` (pyarrow S3FileSystem pushdown on target_gene_symbol) and applies the
# is_definitively_absent discipline — swallow only NoSuchKey/404, re-raise transient/creds. No
# masking handler remains, so the deferred allowlist entry is removed.
_DEFERRED_ALLOWLIST: dict[str, str] = {}

# Pre-existing debt discovered when this lint was introduced (2026-08-15). OUT OF SCOPE for
# PR #354, which curated ~13 verdict-bearing readers. Recorded so CI is green and the debt is
# enumerable; the lint ratchets against NEW violations. BURN THIS DOWN — convert each handler to
# the is_definitively_absent discipline (or add an inline `# absence-discipline: exempt -- ...`
# with a justification if a handler is genuinely a benign fallback) and delete its entry here.
_BASELINE_REASON = (
    "pre-existing RD-class residual beyond PR #354; broad except over an S3-read path returns "
    "empty without definitive-vs-transient discrimination; tracked for burndown (see PR)."
)
# BURN-DOWN COMPLETE (2026-08-15, PR fix/burndown-p3-masking, Stage 3 of 3). All 55 pre-existing
# residuals surfaced by this lint (PR #356 baseline) have been RESOLVED across Stages 1 (#359),
# 2 (#360), and 3 (this PR's final 34 P3 handlers): each was either FIXED with the
# is_definitively_absent (+FileNotFoundError) discipline over a local/S3 read, or annotated
# `# absence-discipline: exempt -- <reason>` where genuinely benign (fallback-to-another-path,
# breadcrumb-already-surfaced, build-time materialization, or verdict-inert/descriptive). The lint
# now ratchets against a CLEAN baseline — the only remaining allowlisted handler is the DEFERRED
# cooccurrence_fisher_pancohort entry above (blocked on an active registry collision).
#
# GLOB WIDENED (2026-08-16): find_violations() now scans methods/*/*.py, not just */read.py + */cli.py
# — a masking handler in a one-level HELPER module (pull.py / lookup.py / <name>.py) is just as much a
# silent dead axis, but was previously invisible to this ratchet. Widening surfaced 6 helper-file
# residuals below. The 2 verdict-contributing HIGH-danger handlers (pair_selectivity_gate same-cell +
# normal cubes) were FIXED in this PR; the remaining 6 are recorded here for a follow-up burndown.
_BASELINE_RESIDUALS: dict[str, str] = {
    # allgene_percentile_precompute/lookup.py::_depmap_row + ::_tumor_rows — BURNDOWN COMPLETE
    # (fix/allgene-lookup-read-error-vs-absent): both now raise a typed _RankReadError on a READ
    # failure and return None/() ONLY for genuine absence, so the accessors distinguish "rank read
    # failed" from "target absent". No longer masking handlers → removed from the residual allowlist.
    "immune_context/antigen_conditioned.py::_antigen_tpm_by_uuid_study": "broad except masks catalog RESOLUTION (s3_uri_for) → None; the pq.read itself is "
    "unguarded (propagates). Low danger (resolution only), but a transient catalog read is "
    "masked; burndown follow-up.",
    "resistance_emergence/tahoe_adaptation.py::_fetch_program_rows": "broad except over an S3 pushdown read of the Tahoe resistance-program product returns "
    "None. RD-class residual; burndown follow-up.",
    "structure_features_static/pull.py::_load_domains": "DEFERRED — structure_features_static/ is in the scope of active PR #364 "
    "(fix/sweep2-lru-of-failure); fix there to avoid a collision, not in this glob-widening PR.",
    "structure_features_static/pull.py::_load_hotspots": "DEFERRED — see _load_domains: fix under active PR #364, not here.",
    # DETECTOR HARDENING (2026-09-26, PR fix/absence-discipline-lint-reachability-774, #774). Closing
    # the two reachability holes — (1) 2-deep-loader follow in `_try_reads_s3`, (2) the
    # `type(e).__name__`-breadcrumb false-positive in `_handler_discriminates`, plus the
    # `return {}, "<err>"` non-empty-tuple gap in `_is_empty_return_value` — newly SURFACES the
    # residuals below. They masked before purely via those holes (no allowlist entry). Recorded so CI
    # stays green and the ratchet is ARMED against net-new seams; tracked for burndown, NOT fixed here
    # (scope = the guard only). Burndown: #809 (four seams). #796 (marrow-HPA) BURNED DOWN 2026-09-27 —
    # marrow._load now discriminates transient (isinstance(_TRANSIENT_LOAD_ERRORS)/5xx) from definitive
    # config misses, so its handler is no longer a violation and its residual entry was removed.
    "depmap_methylation_silencing/read.py::_load_ccle_methylation_for_gene": '#809 — live CCLE gzip fallback: `except Exception → return {}, f"s3_read_failed: {e}"` '
    "over `s3.get_object` masks a transient/creds blip into methylation_silencing_class="
    "data_unavailable (VERDICT-DRIVING). Sibling _load_methylation_from_product is the reference-good "
    "is_definitively_absent+re-raise form; bring the live fallback to the same discipline.",
    "depmap_rna_protein_concordance/read.py::_paired_rna_protein": '#809 — RNA arm `except Exception → return {}, {}, f"RNA load failed: {type(e).__name__}"` '
    "masks a transient load_depmap_files_for_card4 failure into the rna_as_biomarker data-gap path "
    "(VERDICT-DRIVING). Fix symmetrically with the protein arm (:56-57, same shape, non-empty tuple).",
    "depmap_protein_abundance/cli.py::_all_protein_median_null": "#809 — `except Exception → return tuple()` over the `_load_allgene_null_sidecar()` read: a "
    "transient sidecar fault empties the all-protein null → high_cutoff None → broadly_high cannot "
    "fire (degradation lane). Discriminate genuine absence from transient.",
    "expression_purity_confound/read.py::read_purity_points": "#809 — BENIGN figure-only best-effort: called AFTER the verdict class is computed, already "
    "logger.debug's the drop and returns None, so it cannot produce a false verdict. Right resolution "
    "is an inline `# absence-discipline: exempt -- figure-only, post-verdict` on the except line "
    "(reader-scoped follow-up), then delete this entry — recorded here only because this PR is "
    "guard-file-scoped and cannot edit the reader.",
}

_ALLOWLIST: dict[str, str] = {**_DEFERRED_ALLOWLIST, **_BASELINE_RESIDUALS}


# --------------------------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------------------------


def test_no_new_reader_absence_violations():
    """RATCHET: no reader may introduce a NEW absence-masking handler.

    A broad except over an S3-read path that returns empty without discriminating
    definitive-absence from a transient/creds/broken-env failure is the RD1-RD9 bug class.
    Fix it (mirror methods/target_id_sidecar.is_definitively_absent), or — if genuinely benign
    — mark it with `# absence-discipline: exempt -- <reason>` on the except line.
    """
    current = set(find_violations())
    allowed = set(_ALLOWLIST)
    new = sorted(current - allowed)
    assert not new, (
        "NEW reader-absence-masking violation(s) — a broad `except` over an S3-read path returns "
        "empty without distinguishing genuine absence (404/NoSuchKey) from a transient/creds/"
        "broken-env failure. Route through methods.target_id_sidecar.is_definitively_absent "
        "(swallow only definitive absence; re-raise the rest), or add "
        "`# absence-discipline: exempt -- <reason>` on the except line if benign:\n  " + "\n  ".join(new)
    )


def test_absence_discipline_baseline_not_stale():
    """Baseline hygiene: every allowlisted key must still be a live violation.

    A stale entry means someone fixed a reader (good!) but left its baseline entry behind. Remove
    the listed keys from `_DEFERRED_ALLOWLIST` / `_BASELINE_RESIDUALS` to keep the debt ledger honest.
    """
    current = set(find_violations())
    stale = sorted(set(_ALLOWLIST) - current)
    assert not stale, (
        "Stale absence-discipline allowlist entrie(s) — no longer detected as violations. "
        "Delete them from the baseline/allowlist in this test:\n  " + "\n  ".join(stale)
    )


def test_allowlist_entries_have_reasons():
    """Every allowlist entry must carry a non-empty reason string (documentation discipline)."""
    missing = sorted(k for k, v in _ALLOWLIST.items() if not (v and v.strip()))
    assert not missing, f"Allowlist entries missing a reason: {missing}"


@pytest.mark.parametrize(
    "case",
    [
        # (source, expect_violation)
        # 1. Naive masking over an S3 read -> VIOLATION.
        (
            """
def r():
    try:
        return s3_client().get_object(Bucket=b, Key=k)
    except Exception:
        return {}
""",
            True,
        ),
        # 2. is_definitively_absent + raise -> OK.
        (
            """
def r():
    try:
        return s3_client().get_object(Bucket=b, Key=k)
    except Exception as e:
        if not is_definitively_absent(e):
            raise
        return {}
""",
            False,
        ),
        # 3. Inline definitive-vs-transient latch (no is_definitively_absent, no raise) -> OK.
        (
            """
def r():
    try:
        return s3_client().get_object(Bucket=b, Key=k)
    except Exception as e:
        code = getattr(e, "response", {}).get("Error", {}).get("Code")
        if code in ("404", "NoSuchKey"):
            return None
        return None
""",
            False,
        ),
        # 4. Broad except that does NOT read S3 (optional Plotly) -> not in scope.
        (
            """
def r():
    try:
        import plotly
        return plotly.render(fig)
    except Exception:
        return None
""",
            False,
        ),
        # 5. Narrow except -> never flagged.
        (
            """
def r():
    try:
        return read_parquet(path)
    except (ValueError, TypeError):
        return {}
""",
            False,
        ),
        # 6. Tuple-of-empties return -> VIOLATION.
        (
            """
def r():
    try:
        return read_parquet(path)
    except Exception:
        return pd.DataFrame(), {}
""",
            True,
        ),
        # 7. Inline escape-hatch marker -> suppressed.
        (
            """
def r():
    try:
        return read_parquet(path)
    except Exception:  # absence-discipline: exempt -- benign optional enrichment layer
        return {}
""",
            False,
        ),
        # 8. HOLE 1 (2-deep loader): try body only CALLS a `load_*` entry point (S3 read >=2 levels
        #    down), bare except returns empty, no discrimination -> now VIOLATION (was invisible).
        (
            """
def r():
    try:
        return _cli.load_and_classify(target)
    except Exception:
        return {}
""",
            True,
        ),
        # 8b. `_load_*` (leading underscore) loader entry point, empty-tuple return -> VIOLATION.
        (
            """
def r():
    try:
        return _load_allgene_null_sidecar()
    except Exception:
        return tuple()
""",
            True,
        ),
        # 9. HOLE 2 (breadcrumb): the ONLY `type(e)` use is an f-string diagnostic, no branch on the
        #    exception -> must NOT count as discrimination -> VIOLATION (over a loader call).
        (
            """
def r():
    try:
        return load_model_csv(pin)
    except Exception as e:
        return {}, f"read_failed: {type(e).__name__}"
""",
            True,
        ),
        # 10. type() DRIVING control flow (guard of an `if`) -> genuine discrimination -> OK. Proves
        #     the hole-2 tightening did not over-fire against real type-branching handlers.
        (
            """
def r():
    try:
        return load_model_csv(pin)
    except Exception as e:
        if type(e) is FileNotFoundError:
            return {}
        raise
""",
            False,
        ),
        # 11. `return {}, "<err>"` non-empty-tuple over an S3 read: the data slot is empty and the
        #     other slot only NAMES the fault in a string -> fails toward absence -> VIOLATION.
        (
            """
def r():
    try:
        body = s3_client().get_object(Bucket=b, Key=k)
        return body, "ok"
    except Exception as e:
        return {}, f"s3_read_failed: {e}"
""",
            True,
        ),
        # 12. isinstance() in a `raise` arm -> genuine discrimination -> OK (no over-fire).
        (
            """
def r():
    try:
        return load_model_csv(pin)
    except Exception as e:
        if not isinstance(e, FileNotFoundError):
            raise
        return {}
""",
            False,
        ),
        # 13. Loader-call try body BUT properly disciplined (is_definitively_absent + raise) -> OK.
        #     Proves the loader-follow (hole 1) still respects the absence discipline.
        (
            """
def r():
    try:
        return load_constraint_row(target)
    except Exception as e:
        if not is_definitively_absent(e):
            raise
        return {}
""",
            False,
        ),
    ],
)
def test_detector_semantics(case):
    """Guard the detector itself against regressions (fixtures, not the live tree)."""
    source, expect = case
    tree = ast.parse(source)
    lines = source.splitlines()
    found = False
    for try_node in ast.walk(tree):
        if not isinstance(try_node, ast.Try) or not _try_reads_s3(try_node):
            continue
        for handler in try_node.handlers:
            if not _is_broad_handler(handler):
                continue
            if not _handler_returns_empty(handler):
                continue
            if _handler_reraises(handler) or _handler_discriminates(handler):
                continue
            span = "\n".join(_handler_span_lines(handler, lines))
            if _EXEMPT_MARKER in span:
                continue
            found = True
    assert found is expect


# ============================================================================================
# SIBLING DETECTOR: benign VERDICT-CLASS token laundered from a broad except (the #796/#822 class)
# ============================================================================================
#
# THE SUB-CLASS (distinct from the empty-return detector above)
# -------------------------------------------------------------
# The detector above catches a broad `except` over an S3-read path that returns an EMPTY payload
# ({}, [], None, DataFrame()). A sibling shape escapes it entirely: the handler returns a NON-empty
# dict/`.update`/assignment that sets a ``*_class`` VERDICT field to a benign "no concern / not
# measured" token (``data_unavailable``, ``unknown``, ``indeterminate``, ...). A transient
# S3/creds/import blip then reads downstream as an honest measured-absence verdict instead of being
# penalized — silently dropping a rung or flipping a lane favorably. Filed archetype: analysis-methods
# #796 (marrow-HPA drops the essential-window KILL), #822 (SIGNOR reclassifies errors as benign);
# skills #1556 / #1560 (recurrent_snv_driver -> undetermined); #723.
#
# WHY A SEPARATE DETECTOR (not the empty-return one, not a new file)
# -----------------------------------------------------------------
#   * The empty-return detector keys on ``_handler_returns_empty`` — a ``return {"x_class":
#     "data_unavailable", ...}`` is NON-empty, so it is invisible there.
#   * It also gates on ``_try_reads_s3``. The strongest instance here
#     (``gdc_somatic_hotspot._pooled_recurrence_fields``) does no DIRECT S3 read — it lazily
#     ``import``s + calls ``pooled_recurrence_for_gene`` — so an S3-gated scan misses it. This
#     detector gates on the VERDICT-TOKEN anchor instead, not the read.
#   * It lives in THIS file and REUSES the shared AST discipline helpers (``_is_broad_handler``,
#     ``_handler_reraises``, ``_handler_discriminates``, ``_qualname_by_node_id``,
#     ``_handler_span_lines``, ``_EXEMPT_MARKER``) so the two detectors cannot drift.
#
# DISCLAIMER PROSE IS NOT A SUPPRESSOR (the #796 lesson)
# ------------------------------------------------------
# #796 sat on a handler whose own comment said "graceful data_unavailable". So a nearby prose
# disclaimer NEVER drops a finding here. The ONLY things that clear a handler are: it re-raises, it
# discriminates definitive-absence from transient (``_handler_discriminates`` — and a bare
# ``type(e).__name__`` BREADCRUMB does NOT count, see ``_type_check_drives_control_flow`` above), it
# carries the machine-checkable ``# absence-discipline: exempt`` marker, or it is enumerated in the
# frozen baseline below WITH A REASON. Every allowlisted handler is therefore justified in-repo.

# Benign verdict-class tokens: a ``*_class`` value that reads downstream as "no concern / not
# measured / unavailable". Laundering a transient failure into one of these is the bug.
_BENIGN_CLASS_TOKENS = frozenset(
    {
        "data_unavailable",
        "unavailable",
        "not_available",
        "no_data",
        "unknown",
        "undetermined",
        "not_determined",
        "indeterminate",
        "absent",
        "not_detected",
        "undetected",
        "insufficient_data",
        "no_evidence",
        "insufficient_evidence",
        "tolerant",
        "benign",
        "not_dependent",
        "no_dependency",
        "not_essential",
    }
)


def _handler_class_token_keys(handler: ast.ExceptHandler) -> set[str]:
    """Return the set of ``*_class`` field names this handler assigns a benign token to.

    Covers three shapes: a dict literal ``{"x_class": "data_unavailable"}`` (incl. one passed to
    ``base.update({...})``, reached via ``ast.walk``), a subscript assign ``d["x_class"] = "..."``,
    and an attribute assign ``obj.x_class = "..."``.
    """
    keys: set[str] = set()
    for n in ast.walk(handler):
        if isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if (
                    isinstance(k, ast.Constant)
                    and isinstance(k.value, str)
                    and k.value.endswith("_class")
                    and isinstance(v, ast.Constant)
                    and v.value in _BENIGN_CLASS_TOKENS
                ):
                    keys.add(k.value)
        elif isinstance(n, ast.Assign):
            v = n.value
            if not (isinstance(v, ast.Constant) and v.value in _BENIGN_CLASS_TOKENS):
                continue
            for tgt in n.targets:
                key = None
                if (
                    isinstance(tgt, ast.Subscript)
                    and isinstance(tgt.slice, ast.Constant)
                    and isinstance(tgt.slice.value, str)
                ):
                    key = tgt.slice.value
                elif isinstance(tgt, ast.Attribute):
                    key = tgt.attr
                if key and key.endswith("_class"):
                    keys.add(key)
    return keys


def _handler_launders_class_token(handler: ast.ExceptHandler) -> bool:
    """A broad, non-reraising, non-discriminating, non-exempt handler that sets a benign ``*_class``.

    (Exemption via the inline marker is applied by the caller, which has the source span.)
    """
    if not _is_broad_handler(handler):
        return False
    if not _handler_class_token_keys(handler):
        return False
    if _handler_reraises(handler) or _handler_discriminates(handler):
        return False
    return True


def find_class_token_violations() -> tuple[list[str], int, int]:
    """Scan ``methods/*/*.py`` for the benign-verdict-class-token-on-broad-except sub-class.

    Returns ``(sorted violation keys ``"<module>/<file>::<qualified_function>"``, n_files, n_handlers)``.
    The cardinality counts back the anti-vacuity floor: a guard that silently scans zero files or
    zero handlers is worse than none (see the #1648 anti-vacuity ratchet; #1639/#1640 silent-skip).
    """
    root = _methods_root()
    assert root.is_dir(), f"methods/ not found at {root}"
    violations: list[str] = []
    n_files = 0
    n_handlers = 0
    for rel in sorted(root.glob("*/*.py")):
        source = rel.read_text()
        source_lines = source.splitlines()
        tree = ast.parse(source, filename=str(rel))
        qmap = _qualname_by_node_id(tree)
        relkey = rel.relative_to(root).as_posix()
        n_files += 1
        for handler in ast.walk(tree):
            if not isinstance(handler, ast.ExceptHandler):
                continue
            n_handlers += 1
            if not _handler_launders_class_token(handler):
                continue
            span = "\n".join(_handler_span_lines(handler, source_lines))
            if _EXEMPT_MARKER in span:  # inline escape hatch (shared with the empty-return detector)
                continue
            fn = qmap.get(id(handler), "<module>")
            violations.append(f"{relkey}::{fn}")
    return sorted(set(violations)), n_files, n_handlers


# --------------------------------------------------------------------------------------------
# Frozen baseline (2026-09-26). 27 pre-existing handlers that launder a transient/broken-env failure
# into a benign ``*_class`` token. Recorded so CI is GREEN and the debt is enumerable; the guard
# RATCHETS against any NEW un-allowlisted handler. Key = "<module>/<file>::<qualified_function>"
# (LINE-INDEPENDENT so reader edits do not churn it). BURN THIS DOWN — convert each to the
# is_definitively_absent discipline (swallow only definitive absence, re-raise the rest) or add an
# inline ``# absence-discipline: exempt -- <reason>`` where genuinely benign, then delete its entry
# (a stale entry is reported by ``test_class_token_baseline_not_stale``).
# --------------------------------------------------------------------------------------------
_CLASS_TOKEN_BASELINE_REASON = (
    "pre-existing residual: a broad `except` assigns a benign verdict token to a *_class field "
    "without discriminating genuine absence (404/NoSuchKey) from a transient/creds/broken-env "
    "failure — the RD-class fail-toward-absence expressed via a class token instead of an empty "
    "return. Recorded so CI is green and the debt is enumerable; the ratchet arms against NEW "
    "seams. Burn down via methods.target_id_sidecar.is_definitively_absent or an inline exempt marker."
)

_CLASS_TOKEN_BASELINE: dict[str, str] = {
    # -- CONSUMER-CONFIRMED FAIL-SAFE (2026-09-26): the #796 scanner surfaced these; the downstream
    #    trace shows the token is consumed as a GAP, never as a clean token that drops a veto/KILL, so
    #    they are NOT shipped fail-opens. Kept as residuals for discipline-hardening (adopt
    #    is_definitively_absent) + one observability-parity nit, tracked but not verdict-urgent. ------
    "gdc_somatic_hotspot/read.py::_pooled_recurrence_fields": (
        "FAIL-SAFE (consumer-confirmed 2026-09-26): the recurrent_snv_driver rung is a POSITIVE rescue "
        "keyed on equals:top_1pct (intracellular-intrinsic.rules.yaml:701, 'NOT a killer'); on "
        "data_unavailable it simply does NOT fire, and genomic_alteration.resolver.yaml:185-186 "
        "explicitly refuses to demote drivers on unmeasured recurrence — so a transient failure "
        "under-calls (safe), never flips a verdict. Residual: unlike the abundance arm it does NOT set "
        "_live_read_error, so a transient read is indistinguishable from honest no-cohort (observability "
        "nit, filed MEDIUM). Burndown: is_definitively_absent + set _live_read_error."
    ),
    "gdc_somatic_hotspot/read.py::_genie_recurrence_fields": (
        "FAIL-SAFE (consumer-confirmed 2026-09-26): sibling GENIE leg of the same positive-only "
        "SNV-recurrence rescue lane; identical fail-safe posture and the same _live_read_error "
        "observability nit. Fix with the pooled leg."
    ),
    "depmap_partner_conditional_dependency/read.py::read_partner_conditional_dependency": (
        "PER-PARTNER degrade inside a loop: records partner_stratification_class=data_unavailable + "
        "_live_read_error for THIS partner and continues; not a whole-verdict drop. Low blast radius; "
        "discriminate transient vs absent on burndown."
    ),
    # -- Pre-existing residuals pending triage (shared reason) ----------------------------------------
    "dependency_controls/read.py::control_position_dependency": _CLASS_TOKEN_BASELINE_REASON,
    "depmap_chronos/cli.py::_lineage_omnibus": _CLASS_TOKEN_BASELINE_REASON,
    "depmap_predictability/cli.py::main": _CLASS_TOKEN_BASELINE_REASON,
    "depmap_predictability/read.py::read_predictability": _CLASS_TOKEN_BASELINE_REASON,
    "depmap_protein_abundance/read.py::read_target_summary": _CLASS_TOKEN_BASELINE_REASON,
    "expression_clinical_association/read.py::read_expression_clinical_association": _CLASS_TOKEN_BASELINE_REASON,
    "gnomad_constraint/read.py::read_target_summary": (
        "Pinned-contract test test_read_target_summary_graceful_on_unreadable_source (gnomad_constraint/"
        "tests/test_gnomad_constraint.py) asserts graceful data_unavailable on ANY unreadable source, not "
        "just genuine absence (RuntimeError injection reds an is_definitively_absent conversion) — a "
        "design decision on the reader's degradation contract, out of scope for this burndown pass."
    ),
    "expression_purity_confound/read.py::read_expression_purity_confound": _CLASS_TOKEN_BASELINE_REASON,
    "hpa_normal_tissue_liability/read.py::read_target_summary": _CLASS_TOKEN_BASELINE_REASON,
    "imvigor210_ici_response/read.py::read_target_summary": _CLASS_TOKEN_BASELINE_REASON,
    "pathway_node_leverage/cli.py::read_node_leverage": _CLASS_TOKEN_BASELINE_REASON,
    "patient_model_expression_correspondence/read.py::read_recommended_models": _CLASS_TOKEN_BASELINE_REASON,
    "pharos_tdl/cli.py::read_pharos_tdl": _CLASS_TOKEN_BASELINE_REASON,
    "procan_protein_abundance/read.py::read_target_summary": _CLASS_TOKEN_BASELINE_REASON,
    "shed_ectodomain_liability/read.py::read_target_summary": _CLASS_TOKEN_BASELINE_REASON,
    "shet_selection/read.py::read_target_summary": _CLASS_TOKEN_BASELINE_REASON,
    "tcga_gtex_expression_distribution/read.py::_tumor_allgene_percentile": _CLASS_TOKEN_BASELINE_REASON,
    "tcga_gtex_expression_distribution/read.py::_tumor_control_position": _CLASS_TOKEN_BASELINE_REASON,
    "tumor_presence_controls/read.py::control_position_cellline": _CLASS_TOKEN_BASELINE_REASON,
    "tumor_presence_controls/read.py::control_position_tumor": _CLASS_TOKEN_BASELINE_REASON,
}


# --------------------------------------------------------------------------------------------
# Tests (sibling detector)
# --------------------------------------------------------------------------------------------


def test_class_token_scan_cardinality_floor():
    """ANTI-VACUITY: the scan must actually see files and handlers, else it fails OPEN itself.

    A guard that silently scans zero files (broken glob / moved root) is worse than none. Assert a
    hard N>0 floor on both, plus a soft floor to catch a partial-collection regression (526 files /
    611 handlers at freeze).
    """
    _, n_files, n_handlers = find_class_token_violations()
    assert n_files > 0, "class-token scan found ZERO methods/*/*.py files — glob/root broken"
    assert n_handlers > 0, "class-token scan found ZERO except-handlers — parse/collection broken"
    assert n_files >= 100, f"class-token scan saw only {n_files} files (<100) — partial collection?"
    assert n_handlers >= 100, f"class-token scan saw only {n_handlers} handlers (<100) — partial?"


def test_no_new_class_token_absence_violations():
    """RATCHET: no reader may introduce a NEW broad-except that launders a benign *_class token.

    Fix it (route through methods.target_id_sidecar.is_definitively_absent — swallow only genuine
    absence, re-raise transient/creds/broken-env) or, if genuinely benign, mark it with
    `# absence-discipline: exempt -- <reason>` on the except line.
    """
    current, _, _ = find_class_token_violations()
    new = sorted(set(current) - set(_CLASS_TOKEN_BASELINE))
    assert not new, (
        "NEW benign-verdict-class-token fail-open(s) — a broad `except` sets a *_class field to a "
        "benign token (data_unavailable/unknown/...) without distinguishing genuine absence from a "
        "transient/creds/broken-env failure, so a blip reads downstream as an honest measured-absence "
        "verdict. Route through methods.target_id_sidecar.is_definitively_absent (re-raise the "
        "non-definitive branch), or add `# absence-discipline: exempt -- <reason>` if benign:\n  " + "\n  ".join(new)
    )


def test_class_token_baseline_not_stale():
    """Baseline hygiene: every allowlisted key must still be a live violation.

    A stale entry means a reader was fixed (good!) but its baseline entry was left behind. Remove the
    listed keys from ``_CLASS_TOKEN_BASELINE`` to keep the debt ledger honest.
    """
    current, _, _ = find_class_token_violations()
    stale = sorted(set(_CLASS_TOKEN_BASELINE) - set(current))
    assert not stale, (
        "Stale class-token baseline entrie(s) — no longer detected as violations. Delete them from "
        "`_CLASS_TOKEN_BASELINE`:\n  " + "\n  ".join(stale)
    )


def test_class_token_allowlist_entries_have_reasons():
    """Every baseline entry must carry a non-empty reason string (documentation discipline)."""
    missing = sorted(k for k, v in _CLASS_TOKEN_BASELINE.items() if not (v and v.strip()))
    assert not missing, f"Class-token baseline entries missing a reason: {missing}"


@pytest.mark.parametrize(
    "case",
    [
        # (source, expect_violation)
        # 1. Naive: broad except sets a benign *_class token in a dict literal -> VIOLATION.
        (
            """
def r():
    try:
        return {"x_class": ok(target)}
    except Exception:
        return {"x_class": "data_unavailable", "v": None}
""",
            True,
        ),
        # 2. is_definitively_absent + raise -> OK (disciplined).
        (
            """
def r():
    try:
        return classify(target)
    except Exception as e:
        if not is_definitively_absent(e):
            raise
        return {"x_class": "data_unavailable"}
""",
            False,
        ),
        # 3. Inline definitive-vs-transient latch (boto Error Code) -> OK.
        (
            """
def r():
    try:
        return classify(target)
    except Exception as e:
        code = getattr(e, "response", {}).get("Error", {}).get("Code")
        if code not in ("404", "NoSuchKey"):
            raise
        return {"x_class": "data_unavailable"}
""",
            False,
        ),
        # 4. Narrow except -> never flagged.
        (
            """
def r():
    try:
        return classify(target)
    except (ValueError, TypeError):
        return {"x_class": "data_unavailable"}
""",
            False,
        ),
        # 5. Inline escape-hatch marker -> suppressed.
        (
            """
def r():
    try:
        return classify(target)
    except Exception:  # absence-discipline: exempt -- verdict-inert facet
        return {"x_class": "data_unavailable"}
""",
            False,
        ),
        # 6. Subscript assign (the abundance_dependency `base["x_class"] = ...` shape) -> VIOLATION.
        (
            """
def r():
    base = {}
    try:
        base["x_class"] = classify(target)
        return base
    except Exception as e:
        base["x_class"] = "data_unavailable"
        base["_live_read_error"] = str(e)
        return base
""",
            True,
        ),
        # 7. `base.update({...})` with the token (reached via ast.walk into the call) -> VIOLATION.
        (
            """
def r():
    base = {}
    try:
        return classify(target)
    except Exception as e:
        base.update({"x_class": "data_unavailable", "_live_read_error": str(e)})
        return base
""",
            True,
        ),
        # 8. THE #796 LESSON: the ONLY exception inspection is a `type(e).__name__` BREADCRUMB in an
        #    f-string (no branch) -> must NOT count as discrimination -> still a VIOLATION.
        (
            """
def r():
    try:
        return classify(target)
    except Exception as e:
        return {"x_class": "data_unavailable", "_err": f"failed:{type(e).__name__}"}
""",
            True,
        ),
        # 9. type() DRIVING control flow (guard of an `if`) -> genuine discrimination -> OK (no over-fire).
        (
            """
def r():
    try:
        return classify(target)
    except Exception as e:
        if type(e) is FileNotFoundError:
            return {"x_class": "data_unavailable"}
        raise
""",
            False,
        ),
        # 10. Benign token but NOT on a *_class key (a plain note field) -> NOT flagged (anchor is the
        #     verdict field, not the token alone).
        (
            """
def r():
    try:
        return classify(target)
    except Exception:
        return {"note": "data_unavailable", "x_class": "measured_negative"}
""",
            False,
        ),
        # 11. Non-benign *_class token (a real measured verdict) -> NOT flagged.
        (
            """
def r():
    try:
        return classify(target)
    except Exception:
        return {"x_class": "strong_dependency"}
""",
            False,
        ),
        # 12. Handler re-raises -> OK regardless of the token also being present.
        (
            """
def r():
    try:
        return classify(target)
    except Exception:
        record({"x_class": "data_unavailable"})
        raise
""",
            False,
        ),
    ],
)
def test_class_token_detector_semantics(case):
    """Guard the sibling detector itself against regressions (fixtures, not the live tree)."""
    source, expect = case
    tree = ast.parse(source)
    lines = source.splitlines()
    found = False
    for handler in ast.walk(tree):
        if not isinstance(handler, ast.ExceptHandler):
            continue
        if not _handler_launders_class_token(handler):
            continue
        span = "\n".join(_handler_span_lines(handler, lines))
        if _EXEMPT_MARKER in span:
            continue
        found = True
    assert found is expect
