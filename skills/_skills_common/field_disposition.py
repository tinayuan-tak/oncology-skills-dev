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
instrument and must not be quoted as proof (cf. the atlas-exclusion misroute: 17/17 wrong). Two reader
slots were pure name-only when this module was first measured, and they were pure name-only for
OPPOSITE reasons — see ``EXACT_ONLY_KINDS`` for the ``narrative`` half (false credit, withdrawn) and
shape (5) in ``code_readers`` for the ``figure`` half (a real reader missing its card binding).
"""

from __future__ import annotations

import ast
import functools
import json
import re
from collections import defaultdict
from pathlib import Path

import yaml

from _skills_common.paths import target_contracts_root

# An ISO calendar day. Used two ways by `corpus_vintage`, and the distinction is load-bearing:
# `fullmatch` VALIDATES a date taken from a package's own `generated_at`, while `search` RECOVERS one
# from a path string as a fallback. Searching a package stamp would happily accept a date buried in
# unrelated text; full-matching a path would never fire at all.
_ISO_DAY_RE = re.compile(r"20\d\d-\d\d-\d\d")

# ── reader kinds ──────────────────────────────────────────────────────────────────────────────────
# Each kind is its own slot because they fail independently and for different reasons. `strength`
# records whether the kind can bind a field to a SPECIFIC card, or only to a field NAME.
DECLARATIVE_KINDS = ("gating_rule", "display_rule", "capsule", "salience", "metric_gloss")
CODE_KINDS = ("claim_passthrough", "question_table", "narrative", "figure", "skill_code")
READER_KINDS = DECLARATIVE_KINDS + CODE_KINDS

# Kinds that can only ever credit a field NAME (they carry no card_id in their declaration).
NAME_ONLY_KINDS = frozenset({"metric_gloss"})

# ★ Kinds whose name-only evidence is DISCARDED, not merely down-weighted.
#
# The difference from every other kind is what the unbound receiver IS. In a figure emitter the
# receiver genuinely is a card summary, so a name-only hit there is a loose but real upper bound on
# card-field reach. In the narrative layer it is not: `narrative.py` and the `narrator_*` modules read
# FIRED-RULE RECORDS (`card_id = (fr or {}).get("card_id")`) and the lens prose config in
# `narrator_lenses.py` (keyed by SKILL name), so their literal `.get("...")` arguments are their own
# data-structure keys — measured on trunk: `assertion`, `axes`, `cards`, `capsules`, `caveat`,
# `certainty`. Any of those that happens to collide with a declared card field name credits that field
# with a reader it does not have. So narrative is declared here as NOT AN INDEPENDENT FIELD READER: it
# consumes the rule/capsule layer's output, and its reach is whatever the rule and capsule slots
# already report. The slot is KEPT (rather than deleted) so that an exact `get_card_field(...)` read
# appearing in a narrator would still be counted, and so the zero stays visible instead of vanishing.
# NOTE this LOWERS `reached_any_upper_bound`. That is the honest direction: it removes credit, not
# coverage.
EXACT_ONLY_KINDS = frozenset({"narrative"})

# ★★ THE THREE INDEPENDENT INPUTS, grouped by the input each kind is derived FROM.
#
# This grouping exists because a non-vacuity check calibrated on a TOTAL silently degrades into a check
# on the LARGEST mechanism. `skill_code` alone reaches 755 pairs, so a guard asserting only
# "reached_exact > 0" stays green after the entire contracts side stops parsing — and every field it
# used to reach gets reported as a fresh orphan, which reads as a coverage regression rather than as
# the broken instrument it is. That mistake matters most for the ratchet in
# `tests/test_field_disposition.py`, which is a MERGE GATE: a census that returns nothing reports ZERO
# candidate orphans and therefore PASSES a `<= ceiling` assertion. So liveness must be established per
# input, not in aggregate.
#
# The split is by which artifact the reach is scraped from, NOT by DECLARATIVE_KINDS/CODE_KINDS —
# `metric_gloss` is a declarative kind but comes from a python import of a skills-side table, so it
# survives a contracts outage and dies with a skills-side one. Only `census(skills_root=...)` depends
# on the skills tree; `declared_fields`/`rule_readers`/`capsule_readers`/`salience_readers` all take
# `contracts_repo`; `gloss_readers()` takes neither and imports `display_gloss` directly.
READER_SOURCES = {
    "contracts_declarations": frozenset({"gating_rule", "display_rule", "capsule", "salience"}),
    "skills_tree_ast": frozenset({"claim_passthrough", "question_table", "narrative", "figure", "skill_code"}),
    "gloss_table": frozenset({"metric_gloss"}),
}


def reader_sources_alive(per_kind: dict) -> dict:
    """``{source: bool}`` — did each independent census input produce ANY reach at all?

    ANY rather than EVERY, on purpose: `narrative` legitimately reports 0 (see `EXACT_ONLY_KINDS`), so
    requiring every kind in a source to be non-zero would make this permanently red for a declared
    design decision. What is being detected here is an input that has gone entirely dark.

    Takes `summarise()['per_kind']` rather than the census so callers cannot accidentally pass a
    filtered subset and get a confident answer about the whole tree.
    """
    return {src: any(per_kind.get(k, 0) for k in kinds) for src, kinds in READER_SOURCES.items()}


def exact_capable_sources() -> dict:
    """`READER_SOURCES` restricted to kinds that can produce EXACT evidence.

    Anything gating on `census()[pair]["exact"]` — the per-skill ledger reach guard does — can never
    observe a `NAME_ONLY_KINDS` kind, so including `gloss_table` in a liveness check over exact
    evidence would assert a condition that is false by construction. DERIVED from `READER_SOURCES` and
    `NAME_ONLY_KINDS` rather than hand-listed, because a hand-listed copy is what silently decays when
    a kind moves between the two (the tumor-presence guard originally carried two hardcoded sets, and
    the reason `metric_gloss` was absent from both was undocumented).
    """
    out = {src: kinds - NAME_ONLY_KINDS for src, kinds in READER_SOURCES.items()}
    return {src: kinds for src, kinds in out.items() if kinds}


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

    A second, STRICTLY LOWER-PRECEDENCE pass adds the local-helper idiom ``cp = _summary("card-id")``
    — a nested closure over the card list, which tumor-selectivity/scripts/run.py uses for ~9 cards in
    one function. The two attribute/subscript shapes above see a receiver (``c``) and so bind the card
    directly; a call on a bare Name has no receiver to inspect, so the binding was lost and every read
    off that alias fell through to NAME-ONLY credit. Name-only credit is not merely weaker, it is
    credited to EVERY card declaring the name, so an unresolved helper alias does not just under-count
    its own card — it hands false credit to that card's siblings. Resolving it therefore RAISES
    ``candidate_orphans`` wherever the false credit was the only credit a pair had, which is the
    correct direction: it stops crediting a read that never happened.

    Deliberately narrow — exactly one positional argument, no keywords, a literal that names a real
    card. A helper taking more arguments is doing something this cannot verify, and a wrong binding
    would attribute a read to the wrong card, which reads as coverage.
    """
    out: dict[str, str] = {}
    helper_bound: dict[str, str] = {}
    for node in ast.walk(fn_node):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value, card, helper_card = node.value, None, None
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr == "get":
            if value.args:
                card = _literal(value.args[0])
        elif isinstance(value, ast.Subscript):
            card = _literal(value.slice)
        elif isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            if len(value.args) == 1 and not value.keywords:
                helper_card = _literal(value.args[0])
        if _is_card_id(card, known_cards):
            out[target.id] = card
        elif _is_card_id(helper_card, known_cards):
            helper_bound[target.id] = helper_card
    for name, card in helper_bound.items():
        out.setdefault(name, card)
    return out


def _param_field_reads(fn_node, param: str) -> set:
    """Literal field names read off ``param`` (or a local rebound from it) inside ONE function body.

    Only ``.get("f")`` and ``["f"]``, matching shapes (2)/(3) — the same two forms, with the receiver
    identified by PARAMETER rather than by a literal card id at the read site.
    """
    names = {param}
    for _ in range(3):  # `s = summary or {}` then `d = s` — three passes settles any real chain
        for node in ast.walk(fn_node):
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
                continue
            target, value = node.targets[0], node.value
            if not isinstance(target, ast.Name):
                continue
            sources = []
            if isinstance(value, ast.Name):
                sources = [value.id]
            elif isinstance(value, ast.BoolOp):
                sources = [e.id for e in value.values if isinstance(e, ast.Name)]
            if any(s in names for s in sources):
                names.add(target.id)
    fields = set()
    for node in ast.walk(fn_node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            recv = node.func.value
            if node.args and isinstance(recv, ast.Name) and recv.id in names:
                field = _literal(node.args[0])
                if field:
                    fields.add(field)
        elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in names:
            field = _literal(node.slice)
            if field:
                fields.add(field)
    return fields


def _card_dispatch_tables(tree, known_cards: frozenset) -> dict:
    """``{function_name: {card_id, ...}}`` for module-level ``{card_id: function}`` dict literals.

    Keyed on the SHAPE, like shape (4), so a second dispatch table joins the population without
    editing this scraper. Card ids validate against the real card set, so a plain string-keyed dict of
    callbacks is not mistaken for one.
    """
    out: dict[str, set] = defaultdict(set)
    for node in tree.body:
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if not isinstance(value, ast.Dict):
            continue
        for key, val in zip(value.keys, value.values):
            card = _literal(key)
            if isinstance(val, ast.Name) and _is_card_id(card, known_cards):
                out[val.id].add(card)
    return dict(out)


def _import_sources(tree) -> dict:
    """``{local_name: source_module_stem}`` from this module's ``from X import y`` statements."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            stem = node.module.rsplit(".", 1)[-1]
            for alias in node.names:
                out[alias.asname or alias.name] = stem
    return out


def _resolve_def(name: str, imports: dict, defs_by_name: dict):
    """The ONE ``def`` a dispatch-table entry refers to, or ``None`` when it cannot be pinned.

    Names like ``_emit_card_figures`` and ``_emit_section`` are defined more than once in this tree,
    so a bare name lookup can attribute a read to the wrong module (hence the wrong reader KIND) or to
    a function that never saw the card. Ambiguity therefore credits NOTHING — under-credit is the safe
    direction for a metric whose failure mode is looking more open than it is.
    """
    candidates = defs_by_name.get(name) or []
    if len(candidates) == 1:
        return candidates[0]
    stem = imports.get(name)
    if stem:
        same_module = [c for c in candidates if c[0].stem == stem]
        if len(same_module) == 1:
            return same_module[0]
    return None


def _takes_a_summary_dict(fn_node) -> bool:
    """True when the first parameter is annotated ``dict`` — the READER-vs-PRODUCER discriminator.

    Measured need: ``_live_readers.CARD_DISPATCHERS`` is also a ``{card_id: function}`` table of 63
    entries, but its functions are the card PRODUCERS and take ``(target: str, indication: str)``.
    Joining those would attribute reads of a gene symbol to card fields. The annotation is the
    declaration that a function receives a card summary; a producer that grows a dict first argument
    is still filtered by the requirement that every field it reads be DECLARED on that same card.
    """
    params = fn_node.args.args
    if not params:
        return False
    annotation = params[0].annotation
    return isinstance(annotation, ast.Name) and annotation.id == "dict"


def code_readers(skills_root: Path, contracts_repo: Path | None = None) -> tuple[dict, dict]:
    """Scrape static field reads out of skill Python.

    Returns ``(exact, name_only)``, each ``{reader_kind: set(...)}`` — ``exact`` holds
    ``(card_id, field)`` pairs recovered where BOTH the card and the field are statically known;
    ``name_only`` holds bare field names, where the field is a literal but the card is computed at
    runtime. AST, not regex, because a regex over Python mis-parses exactly the nested and
    multi-line calls that matter. Five shapes are recognised:

      ``get_card_field(cards, "card-id", "field")``      -> exact
      ``<expr>["card-id"].get("field")``                 -> exact   (inline ``cbyid`` subscript)
      ``cp = c.get("card-id") ... cp.get("field")``      -> exact   (function-scoped alias)
      ``_patom("card-id", recv, ("f1", "f2", ...), ...)`` -> exact   (evidence-atom PASSTHROUGH)
      ``{"card-id": _emit_x}`` + ``def _emit_x(summary: dict)`` -> exact  (DISPATCH-TABLE join)

    The atom shape matters disproportionately: it is how a field reaches the claim_vector, the eval
    harness, the literature lane and the discordance ledger. It names its fields in a literal tuple
    rather than through a ``.get()``, so a scraper that only understands attribute calls reports the
    passthrough population as orphaned — the exact inversion of CASE-025.

    ★ Shape (5) exists because the ``figure`` slot measured ZERO exact pairs, which read as "no figure
    reads any declared field" and was an INSTRUMENT LIMITATION, not a coverage fact. The reads are
    split across two files by design: ``_figure_emitters/_registry.py`` binds the card id as a dict
    key, and the ``_emit_*`` function that names the fields receives the summary as a parameter and
    never mentions the card. Neither half alone yields a pair; the join does. It is the one shape whose
    binding is INFERRED rather than literal at the read site, so it carries two extra guards — the
    callee must declare a ``dict`` first parameter (see ``_takes_a_summary_dict``), and every field it
    credits must be DECLARED on that card. Both narrow, never widen: a mis-bound table contributes
    nothing instead of a false pair. Neither makes the aperture satisfiable by writing a declaration —
    a field still has to be read by name in code to count.

    Measured limit worth recording: 18 of the 37 registered emitters read NOTHING off the summary in
    this tree, because they hand it to ``render_from_plot_data`` in the analysis-methods repo. Those
    reads live outside ``skills_root`` and stay invisible here — a genuine out-of-tree reader, not a
    scraper bug. Following the callee one or two levels deep was measured and gains exactly 0 pairs.
    """
    known_cards = frozenset(declared_fields(contracts_repo))
    declared = declared_fields(contracts_repo)
    exact: dict[str, set] = defaultdict(set)
    name_only: dict[str, set] = defaultdict(set)

    # Parsed once and kept: shape (5) is a JOIN across two files, so it cannot run inside a
    # single-file loop. A test reading a field does not make it live, so tests stay excluded.
    parsed: list[tuple[Path, ast.Module]] = []
    for path in sorted(skills_root.rglob("*.py")):
        if "/tests/" in str(path) or path.name.startswith("test_"):
            continue
        try:
            parsed.append((path, ast.parse(path.read_text())))
        except SyntaxError:
            continue

    defs_by_name: dict[str, list] = defaultdict(list)
    for path, tree in parsed:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defs_by_name[node.name].append((path, node))

    for path, tree in parsed:
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

    # (5) DISPATCH-TABLE join. The reader KIND comes from the module holding the READ, not the module
    # holding the table, so a dispatch table in one family calling into another attributes correctly.
    for path, tree in parsed:
        imports = _import_sources(tree)
        for fn_name, cards in _card_dispatch_tables(tree, known_cards).items():
            resolved = _resolve_def(fn_name, imports, defs_by_name)
            if resolved is None:
                continue
            def_path, def_node = resolved
            if not _takes_a_summary_dict(def_node):
                continue
            fields = _param_field_reads(def_node, def_node.args.args[0].arg)
            kind = _module_kind(def_path)
            for card in cards:
                for field in fields & set(declared.get(card) or ()):
                    exact[kind].add((card, field))

    # ★ Name-only credit withdrawn for kinds that do not read card summaries at all — see
    # EXACT_ONLY_KINDS. Applied here, at the point of attribution, rather than at the report, so no
    # consumer can pick the un-filtered set up by accident.
    for kind in EXACT_ONLY_KINDS:
        name_only.pop(kind, None)
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
    code produced them. So a coverage gap found here is a HYPOTHESIS about trunk, not a measurement of
    it; confirm against a fresh run before filing one. Use :func:`corpus_vintage` to state the window
    alongside any number taken from this function.

    Re-measured 2026-09-14 from package provenance: ``fd-corpus-20260913`` is 40 of 40 dated
    2026-09-13, with **ZERO packages predating 2026-09-10**, spanning three trunk shas
    (``7353c29`` 20, ``3b720e4`` 19, ``52a46a6`` 1).

    ★★ AN EARLIER VERSION OF THIS DOCSTRING CLAIMED "of the 40 newest-per-`(target, indication)`
    packages, 39 predate 2026-09-10 — up to 18 days behind trunk". Every part of that was wrong, and
    the way it was wrong is the reusable lesson. The 39 NUMERATOR is real but belongs to a DIFFERENT
    POPULATION: newest-per-pair over ``~/dev/framework-runs``, where the denominator is **62, not 40**.
    So 63% was being quoted as 97.5% — a number carried across populations keeps its numerator and
    silently swaps its denominator. The "18 days" span is false against either corpus. And the whole
    claim was unfalsifiable in practice because the function that was supposed to substantiate it,
    :func:`corpus_vintage`, was returning ``unknown`` for all 40 packages at the time it was written.
    DO NOT re-quote a vintage from this docstring; call :func:`corpus_vintage` on the corpus in hand.

    The renamed-card-id caveat still holds and is still worth knowing: two card ids seen in older
    corpora (`cellline-isoform-dominance`, `tumor-splice-expression`) have no card file at all, which
    reads as an alarming contract hole until you check the dates — both are renames already completed
    on trunk (`cellline-isoform-expression`, `tumor-splice-dysregulation`), and later batches emit the
    NEW ids.
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
    """Vintage of a coverage corpus, read from each package's OWN PROVENANCE.

    ``{"n", "oldest", "newest", "by_date", "by_sha", "dated_from", "unreadable"}``.

    A rate needs a frame, and for runtime coverage the frame is WHEN. Without this, "84% of fields are
    measured" gets pasted next to trunk's aperture numbers as though both describe the same tree, and a
    name is the only part of a metric that survives being pasted into a slide. Returned as a sibling of
    the coverage dict rather than folded into it, so it cannot be dropped silently.

    ★ THE VINTAGE COMES FROM THE PACKAGE, NOT FROM ITS PATH, and that is the whole point of this
    function's shape. It reads ``generated_at`` (an ISO stamp the writer emits) and ``generated_by``
    (``skills/target-profile@<sha>``). The original implementation instead searched the PATH STRING for
    ``20\\d\\d-\\d\\d-\\d\\d``, which made it LAYOUT-COUPLED: correct on ``~/dev/framework-runs``, whose
    batch directories happen to be dash-dated, and 100% blind everywhere else. Measured 2026-09-14 on
    the two corpora actually in use: ``fd-corpus-20260913`` returned 40 of 40 ``unknown`` and
    ``target-archetype-corpus-20260911`` returned 298 of 298 ``unknown``. A function that answers
    ``unknown`` for every input still returns a well-formed dict, so nothing downstream noticed.

    ★★ AND WHERE THE PATH REGEX DOES MATCH IT CAN BE WRONG, which is why provenance is not merely a
    coverage improvement. ``target-archetype-corpus-20260911`` carries ``generated_at`` 2026-09-11 for
    10 packages and 2026-09-12 for 288. A dash-dated spelling of that same directory name would have
    labelled all 298 as 2026-09-11 — confidently, and wrong for 288 of them. A DIRECTORY NAME IS A
    HUMAN'S CLAIM ABOUT A CORPUS; ``generated_at`` is the writer's record of it. Prefer the record.

    The path regex is KEPT as an explicit fallback for paths that do not resolve on disk (a caller may
    hold only a manifest of names), and ``dated_from`` reports how many dates came from each source so
    a corpus silently dated entirely by fallback is visible rather than inferred. Packages that cannot
    be read or parsed at all are listed in ``unreadable`` instead of being folded into ``unknown``,
    because "this file is broken" and "this file does not say when it was written" are different
    findings with different fixes — the merged ``unknown`` bucket hid both.

    ``by_sha`` exists because a date is a weaker provenance key than a commit: two packages written the
    same day can straddle a merge, and the atlas arc repeatedly needed to know WHICH TRUNK produced a
    corpus. ``oldest``/``newest`` ignore undated packages rather than defaulting, so an undateable
    corpus reports ``None`` and not a fabricated window.
    """
    by_date: dict[str, int] = defaultdict(int)
    by_sha: dict[str, int] = defaultdict(int)
    dated_from: dict[str, int] = {"provenance": 0, "path": 0, "none": 0}
    unreadable: list[str] = []
    n = 0

    for path in package_paths:
        n += 1
        doc = None
        try:
            doc = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            unreadable.append(str(path))
        if not isinstance(doc, dict):
            doc = {}

        day = str(doc.get("generated_at") or "")[:10]
        if _ISO_DAY_RE.fullmatch(day):
            dated_from["provenance"] += 1
        else:
            # Fallback: a path we could not open (or a package with no stamp) may still be dated by
            # the convention its directory follows. Layout-coupled and therefore never the primary.
            m = _ISO_DAY_RE.search(str(path))
            day = m.group(0) if m else "unknown"
            dated_from["path" if day != "unknown" else "none"] += 1
        by_date[day] += 1

        generated_by = str(doc.get("generated_by") or "")
        by_sha[generated_by.rsplit("@", 1)[1] if "@" in generated_by else "unknown"] += 1

    known = sorted(d for d in by_date if d != "unknown")
    return {
        "n": n,
        "oldest": known[0] if known else None,
        "newest": known[-1] if known else None,
        "by_date": dict(sorted(by_date.items())),
        "by_sha": dict(sorted(by_sha.items())),
        "dated_from": dated_from,
        "unreadable": sorted(unreadable),
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
