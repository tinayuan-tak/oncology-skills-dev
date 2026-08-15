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
Statically (via ``ast``, never regex) scan every ``methods/*/read.py`` and ``methods/*/cli.py``.
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
_S3_READ_MARKERS = frozenset({
    "get_object", "read_table", "read_parquet", "read_csv", "read_json", "read_feather",
    "S3FileSystem", "s3_client", "download_file", "download_fileobj", "get_bucket",
    "bucket_key_for", "bucket_prefix_for", "s3_uri_for", "sidecar_bucket_key_for",
    "read_resolver_sidecar_map", "open_input_stream", "ParquetDataset", "ParquetFile",
    "list_objects", "list_objects_v2", "head_object",
})

# Names/attrs whose presence in a handler proves it DISCRIMINATES definitive vs transient.
_DISCRIMINATION_NAMES = frozenset({
    "is_definitively_absent", "NoSuchKey", "NoSuchBucket", "AccessDenied", "FileNotFoundError",
    "ClientError", "BotoCoreError", "EndpointConnectionError", "ConnectTimeoutError",
    "ReadTimeoutError", "response", "errno", "__class__",
})
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
    if t is None:                                   # bare `except:`
        return True
    if isinstance(t, ast.Name):
        return t.id in ("Exception", "BaseException")
    if isinstance(t, ast.Tuple):                    # `except (Exception, ...):`
        return any(isinstance(e, ast.Name) and e.id in ("Exception", "BaseException")
                   for e in t.elts)
    return False


def _is_empty_atom(v: ast.AST | None) -> bool:
    if v is None:                                                   # bare `return`
        return True
    if isinstance(v, ast.Constant) and v.value is None:            # `return None`
        return True
    if isinstance(v, ast.Dict) and not v.keys:                     # `return {}`
        return True
    if isinstance(v, (ast.List, ast.Set)) and not v.elts:          # `return []`
        return True
    if isinstance(v, ast.Tuple) and not v.elts:                    # `return ()`
        return True
    if isinstance(v, ast.Call):
        f = v.func
        name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
        if name in ("dict", "list", "tuple", "set", "frozenset", "OrderedDict") \
                and not v.args and not v.keywords:                 # `return dict()` / `tuple()`
            return True
        if name.endswith("DataFrame") or name == "Series":         # `return pd.DataFrame(...)`
            return True
    return False


def _is_empty_return_value(v: ast.AST | None) -> bool:
    if _is_empty_atom(v):
        return True
    # tuple/list of all-empty atoms, e.g. `return pd.DataFrame(), {}`
    if isinstance(v, (ast.Tuple, ast.List)) and v.elts and all(_is_empty_atom(e) for e in v.elts):
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
    return {n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _try_reads_s3(try_node: ast.Try) -> bool:
    names: set[str] = set()
    for stmt in try_node.body:
        names |= _names_and_attrs(stmt)
    return bool(names & _S3_READ_MARKERS)


def _handler_reraises(handler: ast.ExceptHandler) -> bool:
    return any(isinstance(n, ast.Raise) for n in ast.walk(handler))


def _handler_discriminates(handler: ast.ExceptHandler) -> bool:
    if _names_and_attrs(handler) & _DISCRIMINATION_NAMES:
        return True
    if _string_constants(handler) & _DISCRIMINATION_STRINGS:
        return True
    # `type(e).__name__` idiom
    for n in ast.walk(handler):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "type":
            return True
    return False


def _handler_returns_empty(handler: ast.ExceptHandler) -> bool:
    return any(isinstance(n, ast.Return) and _is_empty_return_value(n.value)
               for n in ast.walk(handler))


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
    for rel in sorted(root.glob("*/read.py")) + sorted(root.glob("*/cli.py")):
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
                if _EXEMPT_MARKER in span:                     # inline escape hatch
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
_DEFERRED_ALLOWLIST: dict[str, str] = {
    "cooccurrence_fisher_pancohort/read.py::_load_indexed":
        "RD9 DEFERRED by PR #354: active registry collision with "
        "derive-cooccurrence-fisher-pancohort-v1-1 (do-not-touch). `_load_indexed` returns "
        "`pd.DataFrame(), {}` on a broad except over a cached-parquet read; fix alongside the "
        "collision owner. (NB: sibling `_ensure_derived_cached` also latches 403/AccessDenied as "
        "definitive — the RD8 variant — but is not caught by this return-empty lint.)",
}

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
_BASELINE_RESIDUALS: dict[str, str] = {}

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
        "`# absence-discipline: exempt -- <reason>` on the except line if benign:\n  "
        + "\n  ".join(new)
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


@pytest.mark.parametrize("case", [
    # (source, expect_violation)
    # 1. Naive masking over an S3 read -> VIOLATION.
    ("""
def r():
    try:
        return s3_client().get_object(Bucket=b, Key=k)
    except Exception:
        return {}
""", True),
    # 2. is_definitively_absent + raise -> OK.
    ("""
def r():
    try:
        return s3_client().get_object(Bucket=b, Key=k)
    except Exception as e:
        if not is_definitively_absent(e):
            raise
        return {}
""", False),
    # 3. Inline definitive-vs-transient latch (no is_definitively_absent, no raise) -> OK.
    ("""
def r():
    try:
        return s3_client().get_object(Bucket=b, Key=k)
    except Exception as e:
        code = getattr(e, "response", {}).get("Error", {}).get("Code")
        if code in ("404", "NoSuchKey"):
            return None
        return None
""", False),
    # 4. Broad except that does NOT read S3 (optional Plotly) -> not in scope.
    ("""
def r():
    try:
        import plotly
        return plotly.render(fig)
    except Exception:
        return None
""", False),
    # 5. Narrow except -> never flagged.
    ("""
def r():
    try:
        return read_parquet(path)
    except (ValueError, TypeError):
        return {}
""", False),
    # 6. Tuple-of-empties return -> VIOLATION.
    ("""
def r():
    try:
        return read_parquet(path)
    except Exception:
        return pd.DataFrame(), {}
""", True),
    # 7. Inline escape-hatch marker -> suppressed.
    ("""
def r():
    try:
        return read_parquet(path)
    except Exception:  # absence-discipline: exempt -- benign optional enrichment layer
        return {}
""", False),
])
def test_detector_semantics(case):
    """Guard the detector itself against regressions (fixtures, not the live tree)."""
    source, expect = case
    tree = ast.parse(source)
    lines = source.splitlines()
    qmap = _qualname_by_node_id(tree)
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
