#!/usr/bin/env python3
"""build_wiring_reconciliation.py — I.3: is the DECLARE layer load-bearing?

Three independently-derived sets per card, reconciled:

    READS     what the method actually loads (AST over the dispatch module closure)
    DECLARES  what the card names in `required_inputs[].product_id`
    EMITS     whether the card appears in coverage/emission_ledger.yaml (the I.1 census)

The hole this closes is documented at validate_cards.py:1106-1112 — `required_inputs[].product_id`
is NOT used to route the read, so a card can name an unresolvable id and still fire, or read a
dataset it never declares. Findings:

    DECLARED_UNREAD   a declared product_id no read (nor a read's lineage source) covers  -> GATE
    READ_UNDECLARED   a concrete catalog read no declared id (nor its lineage) covers     -> GATE

CONFIDENCE GATE — THE TRUSTWORTHINESS MECHANISM. A static reads oracle over this codebase is
UNSOUND in general: reads flow through param-passed manifest ids, `aws s3 cp` subprocesses, direct
`data-catalog/derived/{id}` path construction, and local caches — none visible to a catalog_query
AST scan. Asserting DECLARED_UNREAD on such a card would ship an EXTRACTION ARTIFACT as a violation
(measured: the plan's hand-counted ~16 declared-unread were mostly this). So reconciliation is
ASSERTED only on the SOUND tier — cards whose ENTIRE read surface is catalog_query-visible:
`opaque_calls == 0 AND n_reads > 0 AND no bespoke-read-primitive (escape hatch)`. Every other routed
card is reported `READS_UNDETERMINED` with a reason — a dimension, never a finding. This never claims
false teeth; each undetermined card promoted to sound later is a one-line snapshot change.

Measured (2026-09-20, 20260915 siblings): 68 dispatcher-routed cards; 14 SOUND; 54 UNDETERMINED;
DECLARED_UNREAD 0; READ_UNDECLARED 0 (the single genuine finding, known-drug-tractability reading
dgidb-drug-target-directional-v1, was FIXED in the card rather than baselined).

BENIGNNESS FILTERING, so a SOUND finding is a real defect and not a lineage artifact:
  lineage    a declared SOURCE is "read" if a read product transitively derives from it
             (data-catalog `derived_from` closure); a read is "declared" if a declared id is
             upstream of it. Pre-expanded at BUILD time into per-read `read_closures` so the
             hermetic half needs no data-catalog sibling to re-derive findings.
  template   per-indication shards: a declared id matching a reader's f-string template
             (`...-{indication}-...` -> `...-*-...`) counts as read.

WHAT EACH HALF OF --self-check CAN AND CANNOT SEE (unstated limitations are how a gate goes green
for the wrong reason):

  HERMETIC half — runs in CI on every PR, no siblings, no credentials. Re-reads today's cards and
                  re-derives the findings from the committed `reads`/`read_closures`/`templates`
                  against today's `declares`. Catches DECLARATION-side drift: a card dropping a
                  required_input a read still needs, or adding one nothing reads. Trusts the committed
                  reads (only the live half proves them) but re-derives the FINDINGS.
  LIVE half     — needs the three siblings (analysis-methods, skills, data-catalog). Re-extracts
                  reads, re-resolves routing/confidence/lineage, and diffs the whole snapshot.
                  Catches READ-side drift: a method starting/stopping a read, a card flipping
                  sound<->undetermined. Announced-skip (never silent) when siblings are absent, as in
                  the checkout-only contracts-validate runner.

METHOD_MODULE_MISSING for a card's declared `methods[].call` is owned by validate_cards.py
(_method_entrypoint_check); not re-gated here. This file reports a *reads-side* variant:
a dispatch fn that `_import_method('X')`s a methods package with no files on disk.

Usage:
    python validators/build_wiring_reconciliation.py                # regenerate the snapshot (live)
    python validators/build_wiring_reconciliation.py --self-check   # CI: hermetic drift gate (+live if siblings present)

Modelled on build_emission_ledger.py (committed snapshot + --self-check, a pattern CI already gates),
including its rule: the generator writes its inputs into the snapshot for diff visibility but the
guard NEVER derives its own scope from the artifact it checks — `declares` is re-read from cards/ at
check time.
"""

from __future__ import annotations

import argparse
import ast
import glob
import re
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CARDS = ROOT / "cards"
SNAPSHOT_PATH = ROOT / "coverage" / "wiring_reconciliation.yaml"
EMISSION_LEDGER_PATH = ROOT / "coverage" / "emission_ledger.yaml"

# Reuse validate_cards' env-overridable sibling paths, availability guard, dispatcher routing and
# catalog-id helpers rather than re-deriving them (they carry the CI-portability contract: the same
# ANALYSIS_METHODS_ROOT / CLAUDE_ONCOLOGY_SKILLS_ROOT / DATA_CATALOG_ROOT env vars, graceful-skip
# when absent). Path insert is __file__-relative so it does not depend on the caller's cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_cards as vc  # noqa: E402

AM = vc._ANALYSIS_METHODS_REPO
DC = vc._DATA_CATALOG_REPO
LIVE_READERS_PATH = vc._LIVE_READERS_PATH

# Anti-vacuity floors. A snapshot with ~no routed cards, or ~no sound cards, reads exactly like a
# clean repo — the failure this file exists to remove. Both trip against an empty/broken snapshot.
MIN_ROUTED_CARDS = 40
MIN_SOUND_CARDS = 10

# catalog-query resolvers whose first str arg is a manifest id (the read's identity)
CATALOG_FUNCS = {
    "s3_uri_for",
    "bucket_key_for",
    "bucket_prefix_for",
    "load_manifest",
    "sidecar_bucket_key_for",
    "resolve_release",
}
# Infra packages that DEFINE the catalog funcs or are pure plumbing; scanning them adds only
# param-passed (opaque) calls, never real card reads.
INFRA_PKGS = {"catalog_query", "target_id_sidecar"}

# Bespoke read primitives that BYPASS catalog_query -> reads INVISIBLE to the AST oracle. Their
# presence in a card's package closure means the catalog-derived read set is INCOMPLETE, so it is
# unsound to assert DECLARED_UNREAD -> the card is UNDETERMINED. Detected as source-text markers.
ESCAPE_MARKERS = (
    "manifests/derived",
    "manifests/sources",  # direct manifest-yaml path construction
    "data-catalog/derived",
    "data-catalog/sources",  # direct S3-prefix construction
    '"s3", "cp"',
    "'s3', 'cp'",
    "s3 cp",  # subprocess aws s3 cp
)


# ---------------------------------------------------------------------------
# catalog + lineage (LIVE: needs data-catalog sibling)
# ---------------------------------------------------------------------------
def load_catalog() -> tuple[set[str], dict[str, list[str]]]:
    """(all manifest ids, {id -> direct derived_from sources}). id == manifest yaml `id:` field
    (also the filename stem, per validate_cards._data_catalog_manifest_ids)."""
    ids: set[str] = set()
    derived_from: dict[str, list[str]] = {}
    for f in glob.glob(str(DC / "manifests/**/*.yaml"), recursive=True):
        try:
            d = yaml.safe_load(Path(f).read_text()) or {}
        except Exception:
            continue
        i = d.get("id")
        if not i:
            continue
        ids.add(i)
        df = d.get("derived_from") or []
        if isinstance(df, list) and df:
            derived_from[i] = [x for x in df if isinstance(x, str)]
    return ids, derived_from


def upstreams(mid: str, derived_from: dict[str, list[str]], seen: set | None = None) -> set[str]:
    """Transitive closure of derived_from — the source ids `mid` ultimately derives from."""
    if seen is None:
        seen = set()
    for up in derived_from.get(mid, []):
        if up not in seen:
            seen.add(up)
            upstreams(up, derived_from, seen)
    return seen


# ---------------------------------------------------------------------------
# _live_readers dispatch: card_id -> dispatch fn -> methods.* modules
# ---------------------------------------------------------------------------
def _fn_name(v):
    if isinstance(v, ast.Name):
        return v.id
    if isinstance(v, (ast.Tuple, ast.List)) and v.elts:
        return _fn_name(v.elts[0])
    return None


def card_to_fn_and_fndefs() -> tuple[dict[str, str], dict[str, ast.FunctionDef]]:
    tree = ast.parse(LIVE_READERS_PATH.read_text())
    card_fn: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if not any(n.endswith("DISPATCHERS") for n in names):
                continue
            for k, v in zip(node.value.keys, node.value.values):
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    fn = _fn_name(v)
                    if fn:
                        card_fn[k.value] = fn
    fndefs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    return card_fn, fndefs


def _callee(func):
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def modules_for_fn(fn_name: str, fndefs: dict, seen: set | None = None) -> set[str]:
    """`_import_method('<mod>')` literals reachable from fn_name, following local fn calls."""
    if seen is None:
        seen = set()
    if fn_name in seen or fn_name not in fndefs:
        return set()
    seen.add(fn_name)
    mods, node = set(), fndefs[fn_name]
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            cal = _callee(n.func)
            if (
                cal == "_import_method"
                and n.args
                and isinstance(n.args[0], ast.Constant)
                and isinstance(n.args[0].value, str)
            ):
                mods.add(n.args[0].value)
            elif cal in fndefs and cal != fn_name:
                mods |= modules_for_fn(cal, fndefs, seen)
    return mods


# ---------------------------------------------------------------------------
# analysis-methods package READS extraction
# ---------------------------------------------------------------------------
def _resolve_arg(a, consts):
    """-> literal str, or template with '*' for interpolations, or None (opaque)."""
    if isinstance(a, ast.Constant) and isinstance(a.value, str):
        return a.value
    if isinstance(a, ast.Name):
        return consts.get(a.id)
    if isinstance(a, ast.JoinedStr):
        parts = []
        for v in a.values:
            parts.append(v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "*")
        return "".join(parts)
    return None


def _pkg_files(top: str) -> list[Path]:
    files: list[Path] = []
    if (AM / "onc_methods" / f"{top}.py").exists():
        files.append(AM / "onc_methods" / f"{top}.py")
    pkg = AM / "onc_methods" / top
    if pkg.is_dir():
        # sorted() so the walk order is deterministic, not filesystem-inode dependent. Without it the
        # per-file constant scope below still resolves each file's own reads correctly, but the walk
        # order would otherwise vary between a CI checkout and a local clone — the exact shape that let
        # a package-wide constant collision (two files defining the same name) regenerate a DIFFERENT
        # committed ledger on CI vs locally (hpa-rna-tissue-consensus-v25-1 drift). Deterministic here.
        files += sorted(pkg.rglob("*.py"))
    return files


def _pkg_trees(top: str) -> list[ast.AST]:
    trees = []
    for f in _pkg_files(top):
        try:
            trees.append(ast.parse(f.read_text()))
        except Exception:
            continue
    return trees


def _methods_dirs() -> set[str]:
    return {p.name for p in (AM / "onc_methods").iterdir() if p.is_dir()}


def _imported_methods_pkgs(trees, dirs: set[str]) -> set[str]:
    """Every methods.<X> top package imported anywhere — absolute (`methods.X`), function-local, OR
    relative (`from ..X import`, level>=1 whose first seg names a real methods/<pkg> dir), which the
    cross-package delegation here uses heavily. Missing relative imports was a measured false-positive
    source (opentargets_common read via `from ..opentargets_common import`)."""
    out: set[str] = set()
    for t in trees:
        for node in ast.walk(t):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("onc_methods."):
                    out.add(node.module.split(".")[1])
                elif node.level and node.level >= 1 and node.module:
                    seg = node.module.split(".")[0]
                    if seg in dirs:
                        out.add(seg)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("onc_methods."):
                        out.add(a.name.split(".")[1])
    return out


def _closure_escape_hatch(scanned: set[str]) -> bool:
    """True if any scanned package reads via a primitive the catalog_query oracle cannot see."""
    for top in scanned:
        for f in _pkg_files(top):
            try:
                txt = f.read_text()
            except Exception:
                continue
            if any(m in txt for m in ESCAPE_MARKERS):
                return True
    return False


def reads_for_card(mods: set[str], dirs: set[str]) -> tuple[set[str], set[str], int, set[str], bool]:
    """Transitive methods.* package closure from the dispatch modules; union catalog_query reads with
    each package's own package-wide str-constant map. Over-approximates reads (conservative for
    DECLARED_UNREAD). Returns (literals, templates, opaque_calls, scanned_pkgs, escape_hatch)."""
    worklist = {m.split(".")[0] for m in mods}
    scanned: set[str] = set()
    trees_by_pkg: dict[str, list] = {}
    while worklist:
        top = worklist.pop()
        if top in scanned or top in INFRA_PKGS:
            continue
        scanned.add(top)
        trees = _pkg_trees(top)
        trees_by_pkg[top] = trees
        worklist |= _imported_methods_pkgs(trees, dirs) - scanned
    literals, templates, opaque = set(), set(), 0
    for trees in trees_by_pkg.values():
        # Constant scope is PER FILE with a package-wide FALLBACK, not a single shared package-wide map.
        # A shared map made whichever file was walked LAST win a given name, so two files in one package
        # each defining `MANIFEST_ID = "<their own id>"` (e.g. tcga_gtex_tpm_quantiles/marrow.py ->
        # "hpa-rna-tissue-consensus-v25-1" and read.py -> "tcga-gtex-tpm-tissue-quantiles-v1") both
        # resolved to the last writer's value — dropping the other file's read entirely, with the winner
        # decided by unsorted rglob order (CI captured hpa-rna, a local clone did not: the drift this
        # fixes). Resolving each file's calls against its OWN constants first, falling back to the
        # package-wide map only for names it does not define locally, keeps genuine cross-file constants
        # working while making a same-name collision resolve correctly and deterministically.
        file_consts: list[tuple[ast.AST, dict[str, str]]] = []
        pkg_consts: dict[str, str] = {}  # package-wide fallback (last-writer) for true cross-file names
        for t in trees:
            fc: dict[str, str] = {}
            for node in ast.walk(t):
                if (
                    isinstance(node, ast.Assign)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    for tg in node.targets:
                        if isinstance(tg, ast.Name):
                            fc[tg.id] = node.value.value
            file_consts.append((t, fc))
            pkg_consts.update(fc)
        for t, fc in file_consts:
            consts = {**pkg_consts, **fc}  # file-local names take precedence over the package-wide fallback
            for node in ast.walk(t):
                if isinstance(node, ast.Call) and _callee(node.func) in CATALOG_FUNCS and node.args:
                    r = _resolve_arg(node.args[0], consts)
                    if r is None:
                        opaque += 1
                    elif "*" in r:
                        templates.add(r)
                    else:
                        literals.add(r)
    return literals, templates, opaque, scanned, _closure_escape_hatch(scanned)


def tmpl_re(t: str) -> re.Pattern:
    return re.compile("^" + "".join(".*" if c == "*" else re.escape(c) for c in t) + "$")


def card_declares(card_id: str) -> list[str]:
    p = CARDS / f"{card_id}.card.yaml"
    try:
        d = yaml.safe_load(p.read_text()) or {}
    except Exception:
        return []
    return [
        ri["product_id"] for ri in (d.get("required_inputs") or []) if isinstance(ri, dict) and ri.get("product_id")
    ]


# ---------------------------------------------------------------------------
# reconciliation
# ---------------------------------------------------------------------------
def _reconcile(reads, read_closures, templates, declares) -> tuple[list[str], list[str]]:
    """(DECLARED_UNREAD, READ_UNDECLARED) from a card's reads, per-read lineage closures, reader
    templates and TODAY's declares. Pure over these inputs — no catalog needed — so the hermetic
    half re-runs it against the committed closures."""
    tmpl_res = [tmpl_re(t) for t in templates]
    declared_set = set(declares)

    def dec_read(d):
        # covered if d is a read or an upstream source of some read (union of the closures), or if a
        # per-indication reader template matches it
        if any(d in cl for cl in read_closures.values()):
            return True
        return any(rx.match(d) for rx in tmpl_res)

    du = sorted(d for d in declares if not dec_read(d))
    ru = sorted(r for r in reads if not (set(read_closures.get(r, [r])) & declared_set))
    return du, ru


def _emitting_cards() -> set[str] | None:
    """card_ids the I.1 emission ledger records observations for. None if the ledger is absent."""
    if not EMISSION_LEDGER_PATH.exists():
        return None
    try:
        led = yaml.safe_load(EMISSION_LEDGER_PATH.read_text()) or {}
    except yaml.YAMLError:
        return None
    return set((led.get("by_card") or {}).keys())


def _sibling_shas() -> dict[str, str]:
    import subprocess

    out: dict[str, str] = {}
    for name, path in (("analysis-methods", AM), ("skills", vc._SKILLS_REPO), ("data-catalog", DC)):
        try:
            sha = subprocess.run(
                ["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
        except Exception:
            sha = ""
        out[name] = sha or "unknown"
    return out


def _siblings_available() -> bool:
    return vc._analysis_methods_available() and LIVE_READERS_PATH.exists() and (DC / "manifests").is_dir()


def compute_reconciliation() -> dict:
    cat_ids, derived_from = load_catalog()
    card_fn, fndefs = card_to_fn_and_fndefs()
    dirs = _methods_dirs()
    emit_cards = _emitting_cards()

    by_card: dict[str, dict] = {}
    n_sound = 0
    findings_du: list[str] = []
    findings_ru: list[str] = []
    missing_modules: list[str] = []

    for card, fn in sorted(card_fn.items()):
        mods = modules_for_fn(fn, fndefs)
        for m in sorted(mods):
            top = m.split(".")[0]
            if top not in INFRA_PKGS and not _pkg_files(top):
                missing_modules.append(f"{card}::{top}")
        lit, tmpl, opq, scanned, escape = reads_for_card(mods, dirs)
        reads = sorted(r for r in lit if r in cat_ids)
        off = sorted(r for r in lit if r not in cat_ids)
        declares = sorted(set(card_declares(card)))
        confident = opq == 0 and len(reads) > 0 and not escape

        entry: dict = {
            "confidence": "sound" if confident else "undetermined",
            "declares": declares,
            "modules": sorted(mods),
            # links the third set (EMITS). None when the ledger is absent — unknown, not False.
            "emits_in_ledger": (card in emit_cards) if emit_cards is not None else None,
        }
        if confident:
            n_sound += 1
            read_closures = {r: sorted({r} | upstreams(r, derived_from)) for r in reads}
            du, ru = _reconcile(reads, read_closures, sorted(tmpl), declares)
            entry.update(
                {
                    "reads": reads,
                    "read_closures": read_closures,
                    "templates": sorted(tmpl),
                    "off_contract_reads": off,
                    "findings": [f"DECLARED_UNREAD::{d}" for d in du] + [f"READ_UNDECLARED::{r}" for r in ru],
                }
            )
            findings_du += [f"{card}::DECLARED_UNREAD::{d}" for d in du]
            findings_ru += [f"{card}::READ_UNDECLARED::{r}" for r in ru]
        else:
            reasons = []
            if len(reads) == 0:
                reasons.append("0 concrete catalog reads")
            if opq:
                reasons.append(f"{opq} opaque catalog call(s)")
            if escape:
                reasons.append("bespoke read primitive (manifest-path/s3-cp)")
            entry["reason"] = "; ".join(reasons)
        by_card[card] = entry

    not_in_ledger = sorted(c for c, e in by_card.items() if e["emits_in_ledger"] is False)
    return {
        "_doc": (
            "I.3 wiring reconciliation: per card, READS (AST over the dispatch closure) vs DECLARES "
            "(required_inputs[].product_id) vs EMITS (emission_ledger). Findings asserted only on the "
            "SOUND tier (reads fully catalog_query-visible: no opaque call, >0 reads, no bespoke read "
            "primitive); other routed cards are READS_UNDETERMINED (a dimension, not a finding). "
            "Regenerate with validators/build_wiring_reconciliation.py; --self-check gates drift."
        ),
        "sibling_shas": _sibling_shas(),
        "n_dispatcher_routed_cards": len(card_fn),
        "counts": {
            "sound": n_sound,
            "undetermined": len(card_fn) - n_sound,
            "declared_unread": len(findings_du),
            "read_undeclared": len(findings_ru),
            "reads_side_module_missing": len(missing_modules),
            "cards_not_in_emission_ledger": len(not_in_ledger),
        },
        # A dispatch fn _import_method's a methods package with no files — a reads-side wiring break.
        # (Card methods[].call resolution is validate_cards' METHOD_MODULE_MISSING; not re-gated here.)
        "reads_side_module_missing": sorted(missing_modules),
        # Routed+sound cards the emission ledger records 0 observations for — a dead-wiring CANDIDATE,
        # reported not gated: the census corpus may simply not exercise the card. Unknown when the
        # ledger is absent.
        "sound_cards_not_in_emission_ledger": not_in_ledger,
        # Dated so each removal is a one-line PR and trunk lands green (contracts-validate is not
        # branch-protection-required, so a red trunk silently taints every open PR).
        "known_violations": {
            "as_of": date.today().isoformat(),
            "keys": sorted(findings_du + findings_ru),
        },
        "by_card": by_card,
    }


# ---------------------------------------------------------------------------
# self-check
# ---------------------------------------------------------------------------
def _floors(snap: dict) -> list[str]:
    nr = snap.get("n_dispatcher_routed_cards") or 0
    ns = (snap.get("counts") or {}).get("sound") or 0
    errs = []
    if nr < MIN_ROUTED_CARDS:
        errs.append(
            f"vacuous: n_dispatcher_routed_cards={nr} < {MIN_ROUTED_CARDS} — the dispatch parse "
            f"found ~no routed cards, which reads identically to a clean repo"
        )
    if ns < MIN_SOUND_CARDS:
        errs.append(
            f"vacuous: sound cards={ns} < {MIN_SOUND_CARDS} — nothing is asserted, so the gate has "
            f"no teeth and cannot be distinguished from all-undetermined"
        )
    return errs


def self_check_hermetic(snap: dict) -> list[str]:
    """Re-derive findings from committed reads/closures/templates against TODAY's cards. No siblings.

    LIMITATION, stated so it cannot become a green for the wrong reason: this half cannot know whether
    the committed reads match the methods on disk. It re-derives the FINDINGS against today's declares
    and checks the baseline is neither under- nor over-listed. Only the live half proves the reads."""
    errs = _floors(snap)
    known = set((snap.get("known_violations") or {}).get("keys") or [])
    live: set[str] = set()

    for card, entry in sorted((snap.get("by_card") or {}).items()):
        if entry.get("confidence") != "sound":
            continue
        declares = sorted(set(card_declares(card)))
        reads = entry.get("reads") or []
        closures = entry.get("read_closures") or {}
        templates = entry.get("templates") or []
        for r in reads:
            if r not in closures or r not in (closures.get(r) or []):
                errs.append(
                    f"internally inconsistent {card}::{r}: read_closures missing its own read — the "
                    f"row was hand-edited or partially regenerated"
                )
        du, ru = _reconcile(reads, closures, templates, declares)
        derived = {f"{card}::DECLARED_UNREAD::{d}" for d in du}
        derived |= {f"{card}::READ_UNDECLARED::{r}" for r in ru}
        live |= derived
        committed_findings = set(entry.get("findings") or [])
        derived_local = {f.split("::", 1)[1] for f in derived}
        if committed_findings != derived_local:
            errs.append(
                f"findings drift {card}: committed {sorted(committed_findings)} but today's declares "
                f"imply {sorted(derived_local)} — regenerate, or fix the card"
            )

    for key in sorted(live - known):
        errs.append(f"unlisted wiring violation {key} — fix the card/method or add it to known_violations")
    for key in sorted(known - live):
        errs.append(
            f"known_violations lists {key} but it is no longer a violation — regenerate so the "
            f"baseline cannot accumulate fixed entries and go vacuous"
        )
    return errs


def self_check_live(snap: dict) -> tuple[list[str], str | None]:
    """Re-extract reads from the siblings and diff the whole snapshot. Returns (errors, skip_reason).

    Catches EMISSION/READ-side drift the hermetic half is blind to: a method starting or stopping a
    read, a card flipping sound<->undetermined, lineage moving. Skipped (announced) when a sibling is
    absent — the same epistemic position as the checkout-only CI runner."""
    if not _siblings_available():
        return [], "one or more siblings (analysis-methods/skills/data-catalog) absent"
    fresh = compute_reconciliation()
    errs: list[str] = []
    if fresh["n_dispatcher_routed_cards"] != snap.get("n_dispatcher_routed_cards"):
        errs.append(
            f"routed-card drift: live {fresh['n_dispatcher_routed_cards']} vs committed "
            f"{snap.get('n_dispatcher_routed_cards')} — the dispatch registry changed; regenerate"
        )
    fb, cb = fresh["by_card"], snap.get("by_card") or {}
    for card in sorted(set(fb) | set(cb)):
        f, c = fb.get(card, {}), cb.get(card, {})
        if f.get("confidence") != c.get("confidence"):
            errs.append(
                f"confidence drift {card}: live {f.get('confidence')} vs committed {c.get('confidence')} — regenerate"
            )
            continue
        if f.get("confidence") == "sound":
            for k in ("reads", "read_closures", "templates", "findings"):
                if (f.get(k) or ([] if k != "read_closures" else {})) != (
                    c.get(k) or ([] if k != "read_closures" else {})
                ):
                    errs.append(f"{k} drift {card}: live vs committed differ — regenerate")
    return errs, None


# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--self-check",
        action="store_true",
        help="CI-safe: hermetic drift gate (+ live half when siblings are present)",
    )
    args = ap.parse_args(argv)

    if args.self_check:
        if not SNAPSHOT_PATH.exists():
            print(f"missing {SNAPSHOT_PATH.name} — run without --self-check to generate it")
            return 1
        snap = yaml.safe_load(SNAPSHOT_PATH.read_text()) or {}
        errs = self_check_hermetic(snap)
        print("build_wiring_reconciliation.py --self-check (hermetic: cards vs committed reads)")
        live_errs, skipped = self_check_live(snap)
        errs += live_errs
        if skipped:
            print(f"  ~ live half SKIPPED: {skipped} (read-side drift unchecked)")
        else:
            print("  + live half: re-extracted reads from siblings")
        for e in errs:
            print(f"  [DRIFT] {e}")
        print("  OK" if not errs else "  FAILED")
        return 0 if not errs else 1

    if not _siblings_available():
        print("cannot regenerate: analysis-methods/skills/data-catalog siblings not all present")
        return 1
    snap = compute_reconciliation()
    fatal = _floors(snap)
    if fatal:
        print("build_wiring_reconciliation.py: REFUSING to write — fix these first:")
        for e in fatal:
            print(f"  [ERROR] {e}")
        return 1
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(yaml.safe_dump(snap, sort_keys=False, width=100))
    c = snap["counts"]
    print(
        f"wrote {SNAPSHOT_PATH.relative_to(ROOT)} — {snap['n_dispatcher_routed_cards']} routed cards, "
        f"{c['sound']} sound / {c['undetermined']} undetermined; "
        f"DECLARED_UNREAD {c['declared_unread']}, READ_UNDECLARED {c['read_undeclared']}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
