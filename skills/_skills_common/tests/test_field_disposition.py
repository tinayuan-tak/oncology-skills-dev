"""Anti-vacuity tests for the field-disposition census (Stage 1b).

WHAT IS AND IS NOT GATED HERE. These tests check the INSTRUMENT, never the fleet's coverage numbers.
`skills/_skills_common/tests/` is inside a `pytest` step and `pytest` is a branch-protection REQUIRED
check, so a ratchet on the measured aperture (748 unread pairs today) would turn every PR that adds a
`summary_field` red until someone wires a reader — a merge-gate change that is the user's call, not a
side effect of landing a measurement. So: no coverage thresholds, no orphan ratchet. The per-skill
ratchet pattern already exists, scoped to one skill, at
`skills/tumor-presence/tests/test_field_disposition_complete.py`.

Every test below is written so it CAN fail: each one pins a value that a plausible regression moves.
The three that matter most are the ones that caught real defects while the instrument was being built
(see the docstrings): atom passthrough, card-id validation, and declaration-blindness.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
from pathlib import Path

import pytest
from _skills_common import field_disposition as fd
from _skills_common.paths import target_contracts_root

SKILLS_ROOT = Path(__file__).resolve().parents[2]


def _contracts_absent() -> bool:
    try:
        return not (target_contracts_root() / "cards").is_dir()
    except Exception:
        return True


needs_contracts = pytest.mark.skipif(_contracts_absent(), reason="target-contracts absent")


def _code_only(src: str) -> str:
    """Source with comments and DOCSTRINGS stripped — but every other string literal kept.

    A raw substring scan cannot tell a READ from a docstring SAYING it does not read: `census`'s own
    contract paragraph names `field_disposition.yaml` in order to promise it never opens that file, and
    the first version of the anti-gaming test below failed on exactly that sentence. Matching on prose
    is the failure mode that produced 17/17 atlas misroutes.

    Dropping ALL string tokens would be the opposite error and a worse one — a real read spells the
    filename as a literal, so a blanket string strip makes the guard unfailable. So only strings that
    stand alone as a whole statement (docstrings) are removed.
    """
    import io
    import textwrap
    import tokenize

    kept, pending = [], None
    at_stmt_start = True
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(textwrap.dedent(src)).readline))
    except (tokenize.TokenError, IndentationError):
        return src
    for tok in toks:
        if tok.type in (tokenize.COMMENT, tokenize.NL):
            continue
        if pending is not None:
            # A lone STRING followed by NEWLINE is an expression statement, i.e. a docstring.
            if tok.type != tokenize.NEWLINE:
                kept.append(pending)
            pending = None
        if tok.type == tokenize.STRING and at_stmt_start:
            pending = tok.string
            at_stmt_start = False
            continue
        if tok.type in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING):
            at_stmt_start = True
        elif tok.type != tokenize.STRING:
            at_stmt_start = False
        kept.append(tok.string)
    return " ".join(kept)


# ── is_measured: the sentinel trap ────────────────────────────────────────────────────────────────
# "has a value" is not "is measured". Each case here is a value that a naive `if value:` or
# `pd.isna(value)` guard gets WRONG, in one direction or the other.


@pytest.mark.parametrize(
    "value",
    [
        None,
        "data_unavailable",  # TRUTHY STRING — the CASE-032 sentinel
        "DATA_UNAVAILABLE",
        "  data_unavailable  ",
        "unmeasured",
        "not_assessed",
        "",
        float("inf"),  # a NUMBER — pd.isna(inf) is False, so isna-guards admit it
        float("-inf"),
        float("nan"),
        [],
        {},
    ],
)
def test_is_measured_rejects_non_measurements(value):
    assert fd.is_measured(value) is False, f"{value!r} must not count as a measurement"


@pytest.mark.parametrize("value", [0, 0.0, False, "broadly_neutral", -1.5, ["x"], {"a": 1}, "0"])
def test_is_measured_accepts_real_readings_including_zero(value):
    """Zero is a READING. Treating 0 / 0.0 / False as missing is the mirror-image error, and it is the
    one that silently deletes every "no event detected" call — which for CN is the *correct* answer for
    most targets (`broadly_neutral`), not a gap."""
    assert fd.is_measured(value) is True, f"{value!r} is a measurement and must count"


def test_sentinel_set_is_lowercase_so_the_case_fold_is_not_vacuous():
    """`is_measured` lower-cases before the lookup. If a sentinel were stored with capitals it could
    never match, and the fold would be dead code that looks like it works."""
    assert all(s == s.lower() for s in fd.UNMEASURED_SENTINELS)


# ── run_coverage: present vs measured must stay separate ──────────────────────────────────────────


def _pkg(tmp_path: Path, name: str, cards: list) -> Path:
    p = tmp_path / name
    p.mkdir()
    out = p / "evidence_package.json"
    out.write_text(json.dumps({"cards": cards}))
    return out


def test_run_coverage_counts_a_sentinel_as_present_but_unmeasured(tmp_path):
    """The whole point of the third funnel stage. A card that ran and reported "I could not look" is
    PRESENT (it was asked) and UNMEASURED (it answered nothing) — collapsing the two would report
    blindness as coverage."""
    a = _pkg(tmp_path, "a", [{"card_id": "c1", "summary": {"f": 0.5, "g": "data_unavailable"}}])
    b = _pkg(tmp_path, "b", [{"card_id": "c1", "summary": {"f": "data_unavailable", "g": 1.0}}])
    cov = fd.run_coverage([a, b])
    assert cov[("c1", "f")] == {"present": 2, "measured": 1}
    assert cov[("c1", "g")] == {"present": 2, "measured": 1}


def test_run_coverage_denominator_excludes_runs_where_the_card_never_appeared(tmp_path):
    """A card outside its `applies_when` was never ASKED, so it must not enter the denominator as a
    miss. Otherwise every indication-gated card reads as chronically blind and the number measures
    routing, not data."""
    a = _pkg(tmp_path, "a", [{"card_id": "c1", "summary": {"f": 1}}])
    b = _pkg(tmp_path, "b", [{"card_id": "c2", "summary": {"f": 1}}])
    cov = fd.run_coverage([a, b])
    assert cov[("c1", "f")]["present"] == 1, "c1 was absent from run b — that is not a miss"
    assert cov[("c2", "f")]["present"] == 1


def test_run_coverage_survives_a_malformed_package(tmp_path):
    """A truncated package must not abort the census — it must contribute nothing. A crash here would
    make coverage depend on whether any historical run happened to be corrupt."""
    good = _pkg(tmp_path, "good", [{"card_id": "c1", "summary": {"f": 1}}])
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "evidence_package.json").write_text("{not json")
    assert fd.run_coverage([good, bad, tmp_path / "nope" / "evidence_package.json"]) == {
        ("c1", "f"): {"present": 1, "measured": 1}
    }


def test_run_coverage_ignores_a_card_with_no_id_or_a_non_dict_summary(tmp_path):
    p = _pkg(
        tmp_path,
        "a",
        [
            {"summary": {"f": 1}},  # no card_id — cannot be keyed
            {"card_id": "c1", "summary": ["not", "a", "dict"]},
            {"card_id": "c2", "summary": {"f": 1}},
        ],
    )
    assert set(fd.run_coverage([p])) == {("c2", "f")}


def test_corpus_vintage_reports_the_window_and_flags_unknowns(tmp_path):
    """A rate needs a frame, and for runtime coverage the frame is WHEN. The corpus that produced the
    first coverage numbers was 39-of-40 packages older than 2026-09-10, which is why two long-renamed
    card ids showed up looking like contract holes. The window must be reportable next to the rate."""
    v = fd.corpus_vintage(
        [
            "/runs/2026-08-26-full/evidence_package.json",
            "/runs/2026-09-09-full/evidence_package.json",
            "/runs/2026-09-09-other/evidence_package.json",
            "/runs/nodate/evidence_package.json",
        ]
    )
    assert v["n"] == 4
    assert v["oldest"] == "2026-08-26"
    assert v["newest"] == "2026-09-09"
    assert v["by_date"]["2026-09-09"] == 2
    assert v["by_date"]["unknown"] == 1, "an undateable package must be visible, not silently dropped"


def test_corpus_vintage_on_an_empty_corpus_reports_none_not_a_fake_window():
    """`oldest`/`newest` must be None rather than a default date — a fabricated window would make an
    empty corpus look like a fresh one."""
    v = fd.corpus_vintage([])
    assert v == {"n": 0, "oldest": None, "newest": None, "by_date": {}}


# ── card-id validation: the over-crediting bug ────────────────────────────────────────────────────


@needs_contracts
def test_is_card_id_rejects_kebab_shaped_non_cards():
    """A `"-" in key` shape test admits `log2-fc` and `non-small-cell` and mints reader pairs for cards
    that do not exist — it INFLATES the aperture, which is the direction that lets the measurement
    congratulate itself. Validation is against the real card set."""
    known = frozenset(fd.declared_fields())
    assert known, "no cards discovered — this test would be vacuous"
    for fake in ("log2-fc", "non-small-cell", "not-a-card-at-all", "", None):
        assert not fd._is_card_id(fake, known)
    assert fd._is_card_id(next(iter(known)), known)


# ── reader detection is non-vacuous, in BOTH directions ───────────────────────────────────────────


@needs_contracts
def test_census_reaches_some_fields_but_not_all():
    """A detector that finds everything is as broken as one that finds nothing, and both look like a
    clean pass. Pin the aperture strictly inside (0, domain) rather than at a threshold, so this stays
    true as coverage moves without becoming a merge gate on the number itself."""
    s = fd.summarise(fd.census(SKILLS_ROOT))
    assert s["domain"] > 500, "domain collapsed — cards stopped being discovered"
    assert 0 < s["reached_exact"] < s["domain"]
    assert s["reached_exact"] <= s["reached_any_upper_bound"] <= s["domain"]
    assert s["candidate_orphans"] == s["domain"] - s["reached_any_upper_bound"]


@needs_contracts
def test_atom_passthrough_fields_are_not_reported_orphaned():
    """THE CASE-025 REGRESSION, INVERTED. `p95_log2tpm` is read only as a bare string inside the
    `_patom(...)` field tuple in `presence_claims.py` — no `.get()`, no `get_card_field()`. An AST pass
    that handles only attribute access reports it ORPHANED, i.e. the instrument built to find silent
    drops would itself recommend deleting a live field. Passthrough is its own reader slot per the
    plan; this pins that it fires."""
    cen = fd.census(SKILLS_ROOT)
    key = ("tumor-rna-distribution", "p95_log2tpm")
    if key not in cen:
        pytest.skip("card/field no longer declared — re-pin this test on another _patom tuple member")
    assert "claim_passthrough" in cen[key]["exact"], (
        "atom-passthrough detection is broken: a field named only inside a _patom() tuple is being reported unread"
    )


@needs_contracts
def test_alias_bound_reads_are_exact_not_name_only():
    """`cp = c.get("tumor-protein-abundance-cptac")` then `cp.get("protein_effect_size")` is the
    dominant idiom in the claims modules. Losing the alias binding downgrades every such read to
    name-only evidence, which then over-credits every OTHER card declaring the same field name — the
    substring-misroute failure mode, one layer up."""
    cen = fd.census(SKILLS_ROOT)
    exact_pairs = {k for k, v in cen.items() if "claim_passthrough" in v["exact"]}
    # 40 measured on trunk 2026-09-13. Note this is the EXACT count; `summarise()`'s `per_kind` reports
    # 201 for this kind because it folds name-only evidence in, so do not cross-quote the two.
    assert len(exact_pairs) >= 30, (
        f"only {len(exact_pairs)} exact claim_passthrough pairs (was 40) — alias resolution or the "
        "_patom shape match has regressed, which would report live fields as orphans"
    )


@needs_contracts
def test_every_rule_target_names_a_real_card():
    """Zero dangling rule targets was true when the census was built. A rule pointing at a renamed card
    is a pointer that never resolves, and per the cross-evidence review those look exactly like working
    ones."""
    known = frozenset(fd.declared_fields())
    for kind, pairs in fd.rule_readers().items():
        dangling = sorted({c for c, _ in pairs if c not in known})
        assert not dangling, f"{kind} targets cards that do not exist: {dangling}"


# ── shape (5): the dispatch-table join ────────────────────────────────────────────────────────────
#
# `figure` measured ZERO exact pairs before this shape existed, which read as "no figure reads a
# declared field" and was an instrument limitation instead: the card id is a dict key in
# `_figure_emitters/_registry.py` and the field names live in an `_emit_*` body that receives the
# summary as a parameter and never mentions the card. These tests drive the join from a SYNTHETIC tree
# so each guard can be falsified by construction, then pin the live result.


def _two_real_fields() -> tuple[str, str, str, str]:
    """``(card_a, field_a, card_b, field_b)`` from the real contracts, chosen deterministically.

    Derived rather than hardcoded: a literal card/field pair in a test decays silently through a rename
    (see the golden-snapshot family of traps), and these tests need a field that genuinely IS declared
    on one card and genuinely is NOT on the other.
    """
    declared = fd.declared_fields()
    usable = sorted((c, sorted(f)) for c, f in declared.items() if len(set(f)) >= 2)
    (card_a, fields_a), (card_b, fields_b) = usable[0], usable[-1]
    field_b = next((f for f in fields_b if f not in set(fields_a)), None)
    return card_a, fields_a[0], card_b, field_b


def _synthetic_figure_tree(
    tmp_path: Path,
    *,
    table_key: str,
    field: str,
    annotation: str = "dict",
    decoy_field: str | None = None,
) -> Path:
    """A minimal skills tree carrying the two halves of the join in two files, like the real one."""
    pkg = tmp_path / "skills" / "_skills_common" / "_figure_emitters"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "_registry.py").write_text(f'from ._e import _emit_x\n\nTABLE = {{"{table_key}": _emit_x}}\n')
    (pkg / "_e.py").write_text(
        f"def _emit_x(summary: {annotation}, out_dir, target, indication):\n    return [summary.get({field!r})]\n"
    )
    if decoy_field is not None:
        (pkg / "_other.py").write_text(
            f"def _emit_x(summary: dict, out_dir, target, indication):\n    return [summary.get({decoy_field!r})]\n"
        )
    return tmp_path / "skills"


@needs_contracts
def test_dispatch_table_join_binds_the_card_to_the_field(tmp_path):
    """The shape's whole reason to exist: neither file alone yields a pair, the join does."""
    card, field, _, _ = _two_real_fields()
    exact, _ = fd.code_readers(_synthetic_figure_tree(tmp_path, table_key=card, field=field))
    assert (card, field) in exact.get("figure", set())


@needs_contracts
def test_dispatch_join_goes_dark_when_the_table_key_is_not_a_card(tmp_path):
    """MUTATION control. Break only the binding half — same emitter, same read — and the pair must
    disappear. Without this the test above could pass off any `.get()` anywhere in the tree."""
    card, field, _, _ = _two_real_fields()
    exact, _ = fd.code_readers(_synthetic_figure_tree(tmp_path, table_key="not-a-real-card-id", field=field))
    assert not exact.get("figure"), "a table keyed on a non-card still minted figure pairs"


@needs_contracts
def test_dispatch_join_requires_a_dict_first_parameter(tmp_path):
    """★ The READER-vs-PRODUCER discriminator, and the reason it is not optional.

    `_live_readers.CARD_DISPATCHERS` is the SAME `{card_id: function}` shape with 63 entries, but its
    functions PRODUCE the card from `(target: str, indication: str)`. Joining those would attribute
    reads of a gene symbol to card fields — a pure fabrication of coverage.
    """
    card, field, _, _ = _two_real_fields()
    exact, _ = fd.code_readers(_synthetic_figure_tree(tmp_path, table_key=card, field=field, annotation="str"))
    assert not exact.get("figure")


@needs_contracts
def test_dispatch_join_will_not_credit_a_field_the_card_never_declared(tmp_path):
    """Second narrowing guard. Shape (5) INFERS the card binding rather than reading it at the call
    site, so it is the one shape whose binding could be wrong; requiring the field to be declared on
    that card means a mis-bound table contributes nothing instead of a false pair."""
    card, _, other_card, foreign_field = _two_real_fields()
    if foreign_field is None:
        pytest.skip("no field unique to the comparison card — re-pin on another pair")
    exact, _ = fd.code_readers(_synthetic_figure_tree(tmp_path, table_key=card, field=foreign_field))
    assert (card, foreign_field) not in exact.get("figure", set())
    assert other_card  # the field IS real, just not this card's — that is the point


@needs_contracts
def test_dispatch_join_resolves_a_duplicated_function_name_through_the_import(tmp_path):
    """`_emit_card_figures`, `_emit_section` and `_emit` are each defined more than once in this tree, so
    a bare name lookup can attribute a read to the wrong module — hence the wrong reader KIND — or to a
    function that never saw the card. Resolution goes through the table module's own import."""
    card, field, _, decoy = _two_real_fields()
    if decoy is None:
        pytest.skip("no distinct decoy field available")
    root = _synthetic_figure_tree(tmp_path, table_key=card, field=field, decoy_field=decoy)
    exact, _ = fd.code_readers(root)
    figure = exact.get("figure", set())
    assert (card, field) in figure, "import-based resolution failed on a duplicated function name"
    assert (card, decoy) not in figure, "credited the wrong definition of a duplicated name"


@needs_contracts
def test_figure_emitters_reach_declared_fields_on_the_live_tree():
    """Live pin. 32 pairs over 19 of the 37 registered emitters, measured 2026-09-13. The other 18 hand
    the summary to `render_from_plot_data` in the analysis-methods repo — an out-of-tree reader, not a
    scraper bug — so this floor is well below 37 on purpose."""
    exact, _ = fd.code_readers(SKILLS_ROOT)
    figure = exact.get("figure", set())
    assert ("tumor-rna-distribution", "tumor_expression_class") in figure, (
        "the figure dispatch join is not firing on the live registry"
    )
    assert len(figure) >= 25, f"only {len(figure)} exact figure pairs (was 32) — the registry join has regressed"


@needs_contracts
def test_the_producer_dispatch_table_mints_no_reader_pairs():
    """NEGATIVE control, with its population DERIVED from the live table rather than hardcoded.

    Both halves are asserted: the producers must all fail the discriminator (else the join fabricates
    pairs) AND the registered emitters must all pass it (else a dropped annotation silently under-counts
    the aperture and nothing says so).
    """
    live = SKILLS_ROOT / "_skills_common" / "_live_readers.py"
    registry = SKILLS_ROOT / "_skills_common" / "_figure_emitters" / "_registry.py"
    known = frozenset(fd.declared_fields())

    def _classify(path: Path) -> tuple[int, int]:
        tree = ast.parse(path.read_text())
        imports = fd._import_sources(tree)
        defs: dict[str, list] = {}
        for source in sorted(path.parent.rglob("*.py")):
            for node in ast.walk(ast.parse(source.read_text())):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defs.setdefault(node.name, []).append((source, node))
        takes_dict = other = 0
        for name in fd._card_dispatch_tables(tree, known):
            resolved = fd._resolve_def(name, imports, defs)
            if resolved and fd._takes_a_summary_dict(resolved[1]):
                takes_dict += 1
            else:
                other += 1
        return takes_dict, other

    producers_dict, producers_other = _classify(live)
    assert producers_dict + producers_other >= 50, "CARD_DISPATCHERS population collapsed — this control is now vacuous"
    assert producers_dict == 0, f"{producers_dict} card PRODUCERS look like summary readers"

    emitters_dict, emitters_other = _classify(registry)
    assert emitters_dict + emitters_other >= 30, "the figure registry population collapsed"
    assert emitters_other == 0, f"{emitters_other} registered emitters no longer resolve to a summary reader"


# ── narrative is not an independent field reader ───────────────────────────────────────────────────


@needs_contracts
def test_narrative_contributes_no_name_only_credit():
    """★ FALSE CREDIT, WITHDRAWN. The narrative modules read FIRED-RULE RECORDS and the skill-keyed lens
    prose config, not card summaries, so their literal `.get("...")` arguments are their own data-
    structure keys (`assertion`, `axes`, `cards`, `capsules`, `caveat`, `certainty`). Two of the 86
    collided with declared field names — `indication` and `source` — and credited 9 pairs across 9 cards
    with a reader they do not have. The anti-vacuity half is the second assertion: those literals must
    still BE there, so the empty set is a deliberate withdrawal and not a parse that found nothing.
    """
    _, name_only = fd.code_readers(SKILLS_ROOT)
    assert not name_only.get("narrative"), "narrative name-only credit is back"

    literals = set()
    for path in sorted(SKILLS_ROOT.rglob("*.py")):
        if fd._module_kind(path) != "narrative" or "/tests/" in str(path):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    literals.add(node.args[0].value)
    assert len(literals) >= 20, (
        f"only {len(literals)} literal .get() names found in the narrative modules — the withdrawal "
        "above would be indistinguishable from a scraper that stopped reading them"
    )


def test_the_withdrawn_kind_is_declared_and_keeps_its_slot():
    """Separate from the behaviour test above ON PURPOSE — a declaration pin placed alongside a
    behaviour assertion reds FIRST under a mutation and masks whether the behaviour was ever checked."""
    assert fd.EXACT_ONLY_KINDS == frozenset({"narrative"})
    assert fd.EXACT_ONLY_KINDS <= set(fd.CODE_KINDS)
    assert "narrative" in fd.READER_KINDS, "the slot must stay visible, so its zero is legible"
    assert not fd.EXACT_ONLY_KINDS & fd.NAME_ONLY_KINDS, "a kind cannot be both name-only and exact-only"


@needs_contracts
def test_an_exact_only_kind_still_admits_exact_evidence(tmp_path):
    """The slot is withdrawn from NAME-ONLY credit, not dead-lettered. A narrator that grows a real
    `get_card_field(cards, "<card>", "<field>")` read must still count — otherwise this change would
    hide the very wiring it is asking someone to add."""
    card, field, _, _ = _two_real_fields()
    root = tmp_path / "skills" / "_skills_common"
    root.mkdir(parents=True)
    (root / "narrative.py").write_text(f'def f(cards):\n    return get_card_field(cards, "{card}", "{field}")\n')
    exact, _ = fd.code_readers(tmp_path / "skills")
    assert (card, field) in exact.get("narrative", set())


# ── the anti-gaming contract ──────────────────────────────────────────────────────────────────────


def test_aperture_measurement_never_reads_a_disposition_declaration():
    """★ THE PLAN'S ANTI-GAMING RULE, as a structural check.

    The aperture must be BLIND to declarations, because a metric that counts declared roles is
    satisfied by writing declarations — "declaring all 294 rules would turn the 7.1% aperture green."
    `confusion()` is the one function allowed to read a ledger, because comparing declared role against
    measured reader is its entire job. Any other function touching `field_disposition.yaml` means the
    number can be moved without wiring a reader.
    """
    allowed = {"confusion"}
    for name, fn in vars(fd).items():
        if not callable(fn) or getattr(fn, "__module__", None) != fd.__name__:
            continue
        if name in allowed:
            continue
        try:
            src = inspect.getsource(fn)
        except (OSError, TypeError):
            continue
        assert "field_disposition.yaml" not in _code_only(src), (
            f"{name}() reads a disposition declaration; the aperture would become self-satisfiable"
        )


def test_code_only_strips_prose_but_keeps_a_real_read():
    """Positive control for the guard above. If `_code_only` over-stripped, the anti-gaming test would
    pass no matter what the module did — the strip helper is now load-bearing, so it needs its own
    both-directions check."""
    prose = '''def f():
    """Never reads field_disposition.yaml."""
    return 1  # not field_disposition.yaml either
'''
    real = 'def f():\n    return open(base / "field_disposition.yaml")\n'
    assert "field_disposition.yaml" not in _code_only(prose)
    assert "field_disposition.yaml" in _code_only(real)


def test_confusion_is_the_function_that_does_read_the_ledger():
    """Guards the guard above: if `confusion` stopped reading a ledger, the allowlist would be
    protecting nothing and the test would pass by vacuity."""
    assert "field_disposition.yaml" in inspect.getsource(fd.confusion) or "ledger_path" in (
        inspect.signature(fd.confusion).parameters
    )


def test_name_only_kinds_are_declared_and_disjoint_from_exact_reasoning():
    """Evidence strength is part of the result, not a footnote. `metric_gloss` keys on field NAME only,
    so it credits every card declaring that name and must never be quoted as proof for a specific
    card."""
    assert fd.NAME_ONLY_KINDS
    assert fd.NAME_ONLY_KINDS <= set(fd.DECLARATIVE_KINDS) | set(fd.CODE_KINDS)


def test_reader_kind_lists_do_not_overlap():
    assert not set(fd.DECLARATIVE_KINDS) & set(fd.CODE_KINDS)


# ── tests are not readers ─────────────────────────────────────────────────────────────────────────


@needs_contracts
def test_test_files_are_excluded_from_reader_detection():
    """A test reading a field does not make the field live — if it did, every field with a fixture
    would look wired and the census could never find a silent drop. Checked at the source so it cannot
    quietly regress into an ineffective substring guard."""
    src = inspect.getsource(fd.code_readers)
    assert re.search(r"tests?\b", src), "code_readers no longer mentions test exclusion"
    assert "test_" in src
