"""Field-disposition census — WHICH declared downstream reader reaches each ``(card_id, field)``.

The existing per-skill ``field_disposition.yaml`` ledger (tumor-presence, 278 rows) asserts a
HUMAN JUDGEMENT about a field's role (``signal`` / ``context`` / ``provenance`` / ``display``) and
its CI guard enforces only COMPLETENESS — every emitted field carries *some* role. Nothing checks
that a field tagged ``signal`` is read by anything at all. This module supplies the missing half:
the MEASURED reader set, derived from the readers' own declarations.

WHY NOT "referenced by a rule". A rule-linkage-only predicate fails every legitimately display-only
field and invites a blanket waiver — 15's four phospho ``summary_fields`` are consumed by no rule BY
DESIGN. Measured on trunk, the rule layer is in fact the SMALLEST of the declared readers (gating
rules reach 61 of 1787 pairs; the salience rulers reach 314). So the predicate here is "reachable by
SOME declared downstream reader", and the census reports WHICH — the reader kinds fail independently
and a field can be narrated on a dashboard while invisible to every eval harness (CASE-025).

★ SAFETY CONTRACT, mirroring ``reachability.py``. An empty reader set means "no reader DECLARES this
field", NEVER "this field is dead". REACHABLE-BUT-UNEXERCISED is not UNREACHABLE-BY-CONSTRUCTION:
the code readers are recovered by AST inspection of static call sites, so a field read through a
computed card_id or a ``**kwargs`` splat is invisible here. Unreached pairs are therefore classified
``candidate_orphan`` — a QUEUE FOR REVIEW, never an authorisation to delete.

★ THE APERTURE METRIC IS BLIND TO DECLARATIONS. ``census()`` never reads a
``field_disposition.yaml`` role. If a declaration could count toward "covered", declaring all 296
display-only rules would turn the aperture green — the metric would measure our own paperwork.
Declared-role-vs-measured-reader is a SEPARATE axis, joined only by ``confusion()``, whose whole
purpose is to surface where the two disagree.

★ EVIDENCE STRENGTH IS PART OF THE RESULT. ``exact`` evidence binds a literal card_id to a literal
field. ``name_only`` evidence knows the field name but not which card it came from, so it credits
EVERY card declaring that name — an over-credit by construction. They are separate slots and
``reached_exact`` is the conservative number; a name-only match is a substring-on-a-population
instrument and must not be quoted as proof (cf. the atlas-exclusion misroute: 17/17 wrong).
"""

from __future__ import annotations

import ast
import functools
import json
from collections import defaultdict
from pathlib import Path

import yaml

from _skills_common.paths import target_contracts_root

# ── reader kinds ──────────────────────────────────────────────────────────────────────────────────
# Each kind is its own slot because they fail independently and for different reasons. `strength`
# records whether the kind can bind a field to a SPECIFIC card, or only to a field NAME.
DECLARATIVE_KINDS = ("gating_rule", "display_rule", "capsule", "salience", "metric_gloss")
CODE_KINDS = ("claim_passthrough", "question_table", "narrative", "figure", "skill_code")
READER_KINDS = DECLARATIVE_KINDS + CODE_KINDS

# Kinds that can only ever credit a field NAME (they carry no card_id in their declaration).
NAME_ONLY_KINDS = frozenset({"metric_gloss"})

# Module-family -> reader kind. The plan enumerates these as distinct readers; deriving the kind
# from the module that performs the read is what gives `claim_passthrough` its own slot without a
# second parallel declaration to keep in sync.
_MODULE_FAMILIES = (
    ("_claims.py", "claim_passthrough"),
    ("_question_table.py", "question_table"),
    ("question_table_core.py", "question_table"),
    ("narrative.py", "narrative"),
    ("narrator_", "narrative"),
    ("headline_", "narrative"),
    ("_figure_emitters", "figure"),
)


def _module_kind(path: Path) -> str:
    hay = f"{path.parent.name}/{path.name}"
    for needle, kind in _MODULE_FAMILIES:
        if needle in hay:
            return kind
    return "skill_code"


# ── the DOMAIN: every declared (card_id, field) ───────────────────────────────────────────────────
@functools.lru_cache(maxsize=4)
def declared_fields(contracts_repo: Path | None = None) -> dict:
    """``{card_id: [field, ...]}`` from each card's ``outputs.summary_fields``.

    This is the DENOMINATOR — the fields a card promises to emit. Entries are either a bare string
    or a ``{name, lens_conditional_on}`` mapping (lens-gated); both contribute their name, because a
    lens-gated field is still emitted under its lens and can still be silently dropped.
    """
    root = Path(contracts_repo) if contracts_repo is not None else target_contracts_root()
    out: dict[str, list[str]] = {}
    for f in sorted((root / "cards").glob("*.card.yaml")):
        doc = yaml.safe_load(f.read_text()) or {}
        cid = doc.get("card_id")
        if not cid:
            continue
        fields = []
        for x in ((doc.get("outputs") or {}).get("summary_fields")) or []:
            if isinstance(x, str):
                fields.append(x)
            elif isinstance(x, dict) and x.get("name"):
                fields.append(x["name"])
        out[cid] = fields
    return out


@functools.lru_cache(maxsize=4)
def _card_measurement_types(contracts_repo: Path | None = None) -> dict:
    """``{measurement_type: {card_id, ...}}`` — the card's OWN declared ``measurement_type``, which
    is how a SALIENCE_SPECS entry (keyed by measurement_type) binds to the cards it gauges."""
    root = Path(contracts_repo) if contracts_repo is not None else target_contracts_root()
    out: dict[str, set] = defaultdict(set)
    for f in sorted((root / "cards").glob("*.card.yaml")):
        doc = yaml.safe_load(f.read_text()) or {}
        if doc.get("card_id") and doc.get("measurement_type"):
            out[doc["measurement_type"]].add(doc["card_id"])
    return dict(out)


# ── declarative readers ───────────────────────────────────────────────────────────────────────────
def rule_readers(contracts_repo: Path | None = None) -> dict:
    """``{"gating_rule": {(card, field)}, "display_rule": {...}}``.

    Split by ``coverage/rule_role_partition.yaml`` (``gating`` = referenced by a resolver rung, so
    verdict-moving; ``display`` = referenced by no resolver). The split is the point: conflating
    them is what makes the aperture look twice as open as it is.
    """
    root = Path(contracts_repo) if contracts_repo is not None else target_contracts_root()
    part = yaml.safe_load((root / "coverage" / "rule_role_partition.yaml").read_text()) or {}
    gating = set(part.get("gating") or ())
    out = {"gating_rule": set(), "display_rule": set()}
    for f in sorted((root / "interpretation-rules").glob("*.rules.yaml")):
        for rule in (yaml.safe_load(f.read_text()) or {}).get("rules", []) or []:
            when = rule.get("when") or {}
            if not isinstance(when, dict) or not (when.get("card_id") and when.get("field")):
                continue
            kind = "gating_rule" if rule.get("rule_id") in gating else "display_rule"
            out[kind].add((when["card_id"], when["field"]))
    return out


def capsule_readers(contracts_repo: Path | None = None) -> set:
    """(card, field) pairs a card's own ``capsule:`` projection block names."""
    root = Path(contracts_repo) if contracts_repo is not None else target_contracts_root()
    pairs = set()
    for f in sorted((root / "cards").glob("*.card.yaml")):
        doc = yaml.safe_load(f.read_text()) or {}
        cid, cap = doc.get("card_id"), doc.get("capsule") or {}
        if not (cid and cap):
            continue
        if cap.get("primary_class"):
            pairs.add((cid, cap["primary_class"]))
        for key in ("categorical_fields", "numeric_anchors"):
            for field in cap.get(key) or []:
                pairs.add((cid, field))
    return pairs


_SALIENCE_SCALAR_SLOTS = ("effect_field", "significance_field", "n_field", "omnibus_field", "strata_array")
_SALIENCE_LIST_SLOTS = ("categorical", "extra_scalars")


def salience_readers(contracts_repo: Path | None = None) -> set:
    """(card, field) pairs the SALIENCE_SPECS rulers gauge.

    A spec is keyed by ``measurement_type``, so it is joined to cards two ways: the cards declaring
    that measurement_type, plus any card named explicitly by a ``reference_frame.cut.card_id``.
    """
    from _skills_common.evidence_salience import SALIENCE_SPECS

    mt2cards = _card_measurement_types(contracts_repo)
    pairs = set()
    for mt, spec in SALIENCE_SPECS.items():
        names = [spec[s] for s in _SALIENCE_SCALAR_SLOTS if spec.get(s)]
        for slot in _SALIENCE_LIST_SLOTS:
            names += list(spec.get(slot) or ())
        targets = set(mt2cards.get(mt) or ())
        frames = spec.get("reference_frame") or {}
        for frame in frames if isinstance(frames, list) else [frames]:
            if not isinstance(frame, dict):
                continue
            if frame.get("value_field"):
                names.append(frame["value_field"])
            cut = frame.get("cut") or {}
            if isinstance(cut, dict) and cut.get("card_id"):
                targets.add(cut["card_id"])
        for cid in targets:
            for name in names:
                pairs.add((cid, name))
    return pairs


def gloss_readers() -> set:
    """Field NAMES carrying a METRIC_GLOSS entry. Name-keyed by construction — the gloss table has
    no card_id — so this kind lands in NAME_ONLY_KINDS and never counts as exact evidence."""
    from _skills_common.display_gloss import METRIC_GLOSS

    return set(METRIC_GLOSS)


# ── code readers (AST, never regex) ───────────────────────────────────────────────────────────────
def _literal(node) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _is_card_id(value: str | None, known_cards: frozenset) -> bool:
    """A literal is treated as a card id only if a CARD BY THAT NAME EXISTS.

    Derived from the contracts card set rather than a kebab-case shape test. A shape test admits any
    hyphenated dict key (``"log2-fc"``, ``"non-small-cell"``) and would mint (card, field) pairs for
    cards that do not exist — an over-credit that reads as coverage.
    """
    return bool(value) and value in known_cards


def _card_aliases(fn_node, known_cards: frozenset) -> dict:
    """``{local_name: card_id}`` for the ``cp = c.get("card-id")`` / ``cp = c["card-id"]`` idiom.

    Scoped to ONE function body, so an alias cannot leak across functions that reuse the same short
    name (``cp``, ``h``, ``bc`` are reused constantly). Reassignment wins last-write, which matches
    how the reads below it will actually resolve.
    """
    out: dict[str, str] = {}
    for node in ast.walk(fn_node):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value, card = node.value, None
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr == "get":
            if value.args:
                card = _literal(value.args[0])
        elif isinstance(value, ast.Subscript):
            card = _literal(value.slice)
        if _is_card_id(card, known_cards):
            out[target.id] = card
    return out


def code_readers(skills_root: Path, contracts_repo: Path | None = None) -> tuple[dict, dict]:
    """Scrape static field reads out of skill Python.

    Returns ``(exact, name_only)``, each ``{reader_kind: set(...)}`` — ``exact`` holds
    ``(card_id, field)`` pairs recovered where BOTH the card and the field are statically known;
    ``name_only`` holds bare field names, where the field is a literal but the card is computed at
    runtime. AST, not regex, because a regex over Python mis-parses exactly the nested and
    multi-line calls that matter. Four shapes are recognised:

      ``get_card_field(cards, "card-id", "field")``      -> exact
      ``<expr>["card-id"].get("field")``                 -> exact   (inline ``cbyid`` subscript)
      ``cp = c.get("card-id") ... cp.get("field")``      -> exact   (function-scoped alias)
      ``_patom("card-id", recv, ("f1", "f2", ...), ...)`` -> exact   (evidence-atom PASSTHROUGH)

    The atom shape matters disproportionately: it is how a field reaches the claim_vector, the eval
    harness, the literature lane and the discordance ledger. It names its fields in a literal tuple
    rather than through a ``.get()``, so a scraper that only understands attribute calls reports the
    passthrough population as orphaned — the exact inversion of CASE-025.
    """
    known_cards = frozenset(declared_fields(contracts_repo))
    exact: dict[str, set] = defaultdict(set)
    name_only: dict[str, set] = defaultdict(set)
    for path in sorted(skills_root.rglob("*.py")):
        if "/tests/" in str(path) or path.name.startswith("test_"):
            continue  # a test reading a field does not make it live
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        kind = _module_kind(path)
        # Alias maps are per-function; walk function bodies first, then the module top level.
        scopes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        scopes.append(tree)
        for scope in scopes:
            aliases = _card_aliases(scope, known_cards)
            for node in ast.walk(scope):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                # (1) get_card_field(cards, <card>, <field>)
                if isinstance(fn, ast.Name) and fn.id == "get_card_field" and len(node.args) >= 3:
                    card, field = _literal(node.args[1]), _literal(node.args[2])
                    if field and _is_card_id(card, known_cards):
                        exact[kind].add((card, field))
                    elif field:
                        name_only[kind].add(field)
                    continue
                # (2/3) <recv>.get("<field>") where recv is a literal subscript or a bound alias
                if isinstance(fn, ast.Attribute) and fn.attr == "get" and node.args:
                    field = _literal(node.args[0])
                    if not field:
                        continue
                    recv, card = fn.value, None
                    if isinstance(recv, ast.Subscript):
                        card = _literal(recv.slice)
                    elif isinstance(recv, ast.Name):
                        card = aliases.get(recv.id)
                    if _is_card_id(card, known_cards):
                        exact[kind].add((card, field))
                    else:
                        name_only[kind].add(field)
                    continue
                # (4) atom PASSTHROUGH: a literal card id anywhere in the args, plus a literal
                #     tuple/list of field names. Keyed on the shape, not on the callee's name, so a
                #     second atom helper joins the population without editing this scraper.
                card_args = [c for c in (_literal(a) for a in node.args) if _is_card_id(c, known_cards)]
                if not card_args:
                    continue
                for arg in node.args:
                    if not isinstance(arg, (ast.Tuple, ast.List)):
                        continue
                    names = [_literal(e) for e in arg.elts]
                    if names and all(names):
                        for card in card_args:
                            for name in names:
                                exact[kind].add((card, name))
    return dict(exact), dict(name_only)


# ── the census ────────────────────────────────────────────────────────────────────────────────────
def census(skills_root: Path, contracts_repo: Path | None = None) -> dict:
    """Per-(card, field) reader sets over the FULL declared domain.

    Returns ``{(card_id, field): {"exact": {kind, ...}, "name_only": {kind, ...}}}``. A pair with an
    empty ``exact`` set and an empty ``name_only`` set is a ``candidate_orphan`` — see the module
    SAFETY CONTRACT; it is a review queue, not a delete list.

    Deliberately does NOT read any ``field_disposition.yaml`` role: the aperture must not be
    satisfiable by writing a declaration.
    """
    domain = {(c, f) for c, fields in declared_fields(contracts_repo).items() for f in fields}

    exact: dict[str, set] = dict(rule_readers(contracts_repo))
    exact["capsule"] = capsule_readers(contracts_repo)
    exact["salience"] = salience_readers(contracts_repo)
    code_exact, code_name_only = code_readers(skills_root, contracts_repo)
    exact.update(code_exact)

    name_only: dict[str, set] = dict(code_name_only)
    name_only["metric_gloss"] = gloss_readers()

    out = {}
    for pair in sorted(domain):
        _, field = pair
        out[pair] = {
            "exact": {k for k, pairs in exact.items() if pair in pairs},
            "name_only": {k for k, names in name_only.items() if field in names},
        }
    return out


def summarise(cen: dict) -> dict:
    """Counts per reader kind + the three headline aperture numbers.

    ``reached_exact`` is the conservative, quotable figure. ``reached_any`` folds in name-only
    evidence and is an UPPER BOUND, because a name-only match credits every card declaring the name.
    """
    per_kind = {k: 0 for k in READER_KINDS}
    reached_exact = reached_any = 0
    for readers in cen.values():
        for kind in readers["exact"]:
            per_kind[kind] = per_kind.get(kind, 0) + 1
        for kind in readers["name_only"]:
            per_kind[kind] = per_kind.get(kind, 0) + 1
        if readers["exact"]:
            reached_exact += 1
        if readers["exact"] or readers["name_only"]:
            reached_any += 1
    return {
        "domain": len(cen),
        "per_kind": per_kind,
        "reached_exact": reached_exact,
        "reached_any_upper_bound": reached_any,
        "candidate_orphans": len(cen) - reached_any,
    }


# ── stage 3 of the funnel: is the field actually POPULATED in real runs? ───────────────────────────
# Declared sentinels that occupy a field without measuring anything. "has a value" is NOT "is
# measured": `data_unavailable` is a TRUTHY STRING and ±Inf is a NUMBER, so a naive presence check
# (or a `pd.isna` guard) counts both as coverage and reports blindness as data. Kept as a set so a
# new sentinel joins by declaration.
UNMEASURED_SENTINELS = frozenset(
    {"data_unavailable", "unmeasured", "not_measured", "not_assessed", "insufficient", "unknown", "none", ""}
)


def is_measured(value) -> bool:
    """True when a summary value carries an actual measurement.

    Rejects None, the declared unavailability sentinels (case-insensitively), non-finite floats, and
    empty containers. A 0, a 0.0 and a False are all MEASURED — zero is a reading, and treating it as
    missing is the mirror-image error.
    """
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in UNMEASURED_SENTINELS
    if isinstance(value, float):
        return value == value and value not in (float("inf"), float("-inf"))
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return True


def run_coverage(package_paths) -> dict:
    """``{(card_id, field): {"present": n, "measured": n}}`` over a set of ``evidence_package.json``.

    ``present`` counts runs whose package contains the card at all (the honest denominator — a card
    outside its ``applies_when`` was never asked); ``measured`` counts those where the field carries a
    real reading per :func:`is_measured`. A field can be reader-reached and still measured in 0 runs,
    which is a BLIND AXIS rather than a wiring gap — the two need different fixes, so the census must
    not merge them.

    ★ CORPUS VINTAGE IS PART OF THIS RESULT, and it is the one caveat that changes how the number may
    be quoted. Stages 1 and 2 of the funnel (declared, reader-reached) are computed against the LIVE
    tree, so they describe trunk. This stage reads runs that ALREADY HAPPENED, so it describes whatever
    code produced them. Measured 2026-09-13: of the 40 newest-per-`(target, indication)` packages on
    disk, **39 predate 2026-09-10** — up to 18 days behind trunk. Two card ids in that corpus
    (`cellline-isoform-dominance`, `tumor-splice-expression`) have no card file at all, which reads as
    an alarming contract hole until you check the dates: both are renames already completed on trunk
    (`cellline-isoform-expression`, `tumor-splice-dysregulation`), and the 2026-09-11 batches emit the
    NEW ids. So a coverage gap found here is a HYPOTHESIS about trunk, not a measurement of it; confirm
    against a fresh run before filing one. Use :func:`corpus_vintage` to state the window alongside any
    number taken from this function.
    """
    out: dict[tuple, dict] = defaultdict(lambda: {"present": 0, "measured": 0})
    for path in package_paths:
        try:
            doc = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            continue
        for card in doc.get("cards") or []:
            cid = card.get("card_id")
            summary = card.get("summary") or {}
            if not cid or not isinstance(summary, dict):
                continue
            for field, value in summary.items():
                rec = out[(cid, field)]
                rec["present"] += 1
                if is_measured(value):
                    rec["measured"] += 1
    return dict(out)


def corpus_vintage(package_paths) -> dict:
    """``{"n": int, "oldest": date, "newest": date, "by_date": {date: n}}`` for a coverage corpus.

    A rate needs a frame, and for runtime coverage the frame is WHEN. Without this, "84% of fields are
    measured" gets pasted next to trunk's aperture numbers as though both describe the same tree, and a
    name is the only part of a metric that survives being pasted into a slide. Returned as a sibling of
    the coverage dict rather than folded into it, so it cannot be dropped silently.
    """
    import re as _re

    dates = []
    for path in package_paths:
        m = _re.search(r"20\d\d-\d\d-\d\d", str(path))
        dates.append(m.group(0) if m else "unknown")
    counts: dict[str, int] = defaultdict(int)
    for d in dates:
        counts[d] += 1
    known = sorted(d for d in dates if d != "unknown")
    return {
        "n": len(dates),
        "oldest": known[0] if known else None,
        "newest": known[-1] if known else None,
        "by_date": dict(sorted(counts.items())),
    }


def confusion(cen: dict, ledger_path: Path) -> dict:
    """Join a ``field_disposition.yaml`` DECLARED role against the MEASURED reader set.

    The only place the two axes meet, and the reason it exists is disagreement: a field declared
    ``signal`` with no reader is either a detector blind spot or a real silent drop, and a field
    declared ``display`` that a GATING rule reads is a verdict moving on something documented as
    verdict-inert. Returns ``{(role, "reached"|"unreached"): [(card, field), ...]}``.
    """
    doc = yaml.safe_load(ledger_path.read_text()) or {}
    out: dict[tuple, list] = defaultdict(list)
    for cid, entry in doc.items():
        if cid.startswith("_") or not isinstance(entry, dict):
            continue
        for field, spec in entry.items():
            if field.startswith("_") or not isinstance(spec, dict):
                continue
            readers = cen.get((cid, field))
            if readers is None:
                out[(spec.get("role"), "not_in_domain")].append((cid, field))
                continue
            bucket = "reached" if readers["exact"] else "unreached"
            out[(spec.get("role"), bucket)].append((cid, field))
    return dict(out)
