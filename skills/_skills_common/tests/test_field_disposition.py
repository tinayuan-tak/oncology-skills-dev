"""Anti-vacuity tests for the field-disposition census (Stage 1b).

WHAT IS AND IS NOT GATED HERE. Most tests below check the INSTRUMENT, not the fleet's coverage numbers.
The ONE exception is `test_fleet_aperture_does_not_grow`, a deliberate MERGE GATE added later by
decision: `skills/_skills_common/tests/` is inside a `pytest` step and `pytest` is a branch-protection
REQUIRED check, so that ratchet turns any PR which adds a `summary_field` red until the same PR wires a
reader. That is its purpose, not a side effect. Everything else here still pins instrument behaviour
only, with no coverage thresholds. A per-skill ratchet over a `field_disposition.yaml` ledger is a
separate, narrower mechanism at `skills/tumor-presence/tests/test_field_disposition_complete.py`.

★★ THE APERTURE IS NOT 748. An earlier version of this docstring called 748 "the measured aperture",
which was a conflation of two numbers reported one line apart in #1347: the fleet aperture was
`domain 1787 / reached_any 881 / candidate_orphans 906`, while **748 is the corpus-restricted subset** —
unread fields observed over the 40-run `(target, indication)` corpus, of which 649 were computed and
shipped. 748 counts FIELDS seen in runs; the aperture counts DECLARED (card, field) PAIRS across the
whole tree. Do not use 748 as a fleet number, and do not calibrate the ratchet against it.

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


def _write_package(path: Path, **provenance) -> Path:
    """A minimal `evidence_package.json` carrying whatever provenance the caller names."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cards": [], **provenance}))
    return path


def test_corpus_vintage_reads_the_window_from_package_provenance(tmp_path):
    """★ THE GUARD MUST ENTER WHERE A REAL RUN ENTERS. This is the test whose absence let the original
    implementation ship: it derived the vintage from a `20\\d\\d-\\d\\d-\\d\\d` search over the PATH, and
    real corpus directories are named `fd-corpus-20260913` — UNDASHED — so the regex never fired on the
    trees actually in use. Measured 2026-09-14: `unknown` for 40 of 40 packages in `fd-corpus-20260913`
    and 298 of 298 in `target-archetype-corpus-20260911`, while the old test passed because it fed
    synthetic `/runs/2026-08-26-full/...` paths, a shape no real corpus emits.

    Note the third package is dated 09-12 inside a directory named `...20260913`: real corpora do
    contain that disagreement, and provenance is what resolves it.
    """
    corpus = tmp_path / "fd-corpus-20260913"  # undashed, exactly as the real corpora are named
    for pair, stamp, by in (
        ("ABL1-CML", "2026-09-13T22:18:57Z", "skills/target-profile@3b720e4"),
        ("EGFR-LUAD", "2026-09-13T23:01:02Z", "skills/target-profile@3b720e4"),
        ("KRAS-PAAD", "2026-09-12T08:00:00Z", "skills/target-profile@7353c29"),
    ):
        _write_package(corpus / pair / "evidence_package.json", generated_at=stamp, generated_by=by)

    v = fd.corpus_vintage(sorted(corpus.rglob("evidence_package.json")))
    assert v["n"] == 3
    assert v["by_date"] == {"2026-09-12": 1, "2026-09-13": 2}
    assert v["oldest"] == "2026-09-12"
    assert v["newest"] == "2026-09-13"
    assert v["by_sha"] == {"3b720e4": 2, "7353c29": 1}, "a sha is a stronger provenance key than a day"
    assert v["dated_from"] == {"provenance": 3, "path": 0, "none": 0}, (
        "every date must come from the PACKAGE — a corpus dated entirely by the path fallback is the "
        "original bug wearing a passing test"
    )
    assert v["unreadable"] == []


def test_provenance_beats_a_dashed_directory_name_that_disagrees(tmp_path):
    """★★ WHERE THE PATH REGEX DOES MATCH, IT CAN BE CONFIDENTLY WRONG — so the fallback must never
    outrank the record. `target-archetype-corpus-20260911` really carries `generated_at` 2026-09-11 for
    10 packages and 2026-09-12 for 288; a dash-dated spelling of that same name would have labelled all
    298 as 2026-09-11 and been wrong for 288 of them. A directory name is a HUMAN'S CLAIM about a
    corpus; `generated_at` is the WRITER'S RECORD of it. This test is the one that reddens if anyone
    reorders the two sources."""
    pkg = _write_package(
        tmp_path / "runs-2026-09-11-batch" / "ABL1-CML" / "evidence_package.json",
        generated_at="2026-09-12T08:00:00Z",
        generated_by="skills/target-profile@59d1452",
    )
    v = fd.corpus_vintage([pkg])
    assert v["by_date"] == {"2026-09-12": 1}, "the 2026-09-11 in the PATH must not win"
    assert v["dated_from"] == {"provenance": 1, "path": 0, "none": 0}


def test_corpus_vintage_separates_unreadable_from_undated(tmp_path):
    """A file we could not open and a file that never said when it was written are different
    findings with different fixes, and the original single `unknown` bucket merged them: a corpus of
    corrupt JSON and a corpus of stampless packages produced identical output."""
    dated = _write_package(
        tmp_path / "corpus-20260913" / "A-X" / "evidence_package.json",
        generated_at="2026-09-13T00:00:00Z",
        generated_by="skills/target-profile@3b720e4",
    )
    stampless = _write_package(tmp_path / "corpus-20260913" / "B-X" / "evidence_package.json")
    corrupt = tmp_path / "corpus-20260913" / "C-X" / "evidence_package.json"
    corrupt.parent.mkdir(parents=True, exist_ok=True)
    corrupt.write_text("{not json")
    missing = tmp_path / "corpus-20260913" / "D-X" / "evidence_package.json"

    v = fd.corpus_vintage([dated, stampless, corrupt, missing])
    assert v["n"] == 4
    assert sorted(v["unreadable"]) == sorted([str(corrupt), str(missing)]), (
        "a package that cannot be parsed must be NAMED, not folded into the undated bucket"
    )
    assert v["by_date"] == {"2026-09-13": 1, "unknown": 3}
    assert v["dated_from"] == {"provenance": 1, "path": 0, "none": 3}
    assert v["by_sha"] == {"3b720e4": 1, "unknown": 3}
    assert v["oldest"] == v["newest"] == "2026-09-13", "undated packages must not widen the window"


def test_corpus_vintage_falls_back_to_the_path_only_when_the_package_cannot_be_read(tmp_path):
    """The path regex is retained DELIBERATELY, for callers holding names rather than files — but it is
    a fallback, and `dated_from` must say so. Scoping this to unopenable paths is the point: the
    original function applied it to EVERYTHING, which is why it was layout-coupled."""
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
    assert v["dated_from"] == {"provenance": 0, "path": 3, "none": 1}, (
        "these four never resolved on disk, so ALL of them are fallback dates — and a caller reading "
        "`dated_from` can tell that this corpus was never actually opened"
    )
    assert len(v["unreadable"]) == 4


def test_corpus_vintage_on_an_empty_corpus_reports_none_not_a_fake_window():
    """`oldest`/`newest` must be None rather than a default date — a fabricated window would make an
    empty corpus look like a fresh one."""
    v = fd.corpus_vintage([])
    assert v == {
        "n": 0,
        "oldest": None,
        "newest": None,
        "by_date": {},
        "by_sha": {},
        "dated_from": {"provenance": 0, "path": 0, "none": 0},
        "unreadable": [],
    }


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


# ── THE FLEET RATCHET (the one merge gate in this file) ───────────────────────────────────────────

# ★ Frozen 2026-09-13 on `v2-architecture` @ ee910fec: domain 1801 / reached_exact 667 /
# reached_any 882 / candidate_orphans 919.
#
# WHY 919 AND NOT 906. #1347 measured 906 on a domain of 1787. The 906 -> 919 move is not drift in the
# instrument: 14 (card, field) pairs were declared in between and 13 of them arrived with no reader, so
# the delta is fully explained by declarations outrunning readers — which is exactly the behaviour this
# ratchet exists to stop.
#
# WHY A SINGLE CONSTANT AND NOT A WAIVER LIST. The domain GROWS, so an orphan ceiling forces a new
# declared field to arrive with its reader in the same PR. The alternative — a by-name allowlist of
# permitted orphans — can be silently appended to, and an appended line is the cheapest thing in a diff
# to miss. Lowering one number is a one-line diff that a reviewer cannot skim past.
#
# HOW TO CHANGE IT: only downward, and in the PR that earned it. Wire a reader (or delete a dead
# declaration), re-measure, lower this number. If you are here because your PR declared a new
# `summary_field`, the gate is working: wire it, mark it `role: context`, or waive it with a named
# reason in that skill's `field_disposition.yaml` — do not raise this ceiling.
APERTURE_CEILING = 919

# Slack before the ceiling must be re-tightened. Without an upper bound on the gap, the ceiling decays
# into a number nobody has re-measured, and the ratchet quietly re-opens by exactly the amount of
# progress that was made and never banked. 20 is wide enough that a single wiring PR need not touch
# this file, narrow enough that a batch of them must.
APERTURE_SLACK = 20

# A domain floor, so a census that discovers no cards cannot pass the ceiling by measuring nothing.
# Trunk is 1801; 1500 leaves room for real card retirement without leaving room for an outage.
APERTURE_DOMAIN_FLOOR = 1500


@needs_contracts
def test_reader_sources_partition_every_reader_kind():
    """`reader_sources_alive` is the liveness half of the ratchet, and it can only see kinds that some
    source claims. A kind added to `READER_KINDS` but not to any `READER_SOURCES` entry would be
    invisible to it — so the population is derived from `READER_KINDS` and coverage asserted, rather
    than the check trusting a hand-kept list to have been updated."""
    claimed = [k for kinds in fd.READER_SOURCES.values() for k in kinds]
    assert sorted(claimed) == sorted(fd.READER_KINDS), (
        f"READER_SOURCES does not partition READER_KINDS: unclaimed={sorted(set(fd.READER_KINDS) - set(claimed))}, "
        f"duplicated-or-unknown={sorted(k for k in claimed if claimed.count(k) > 1 or k not in fd.READER_KINDS)}"
    )


@needs_contracts
def test_fleet_aperture_does_not_grow():
    """MERGE GATE: the count of declared-but-unread (card, field) pairs may only fall.

    Liveness is asserted BEFORE the ceiling, and per input rather than in aggregate, because the
    failure mode of a ratchet is passing for the wrong reason: a census that parses nothing reports
    zero orphans and satisfies `<= 919` comfortably. `skill_code` alone reaches 755 pairs, so a total
    would keep this green through a complete contracts-side outage.
    """
    s = fd.summarise(fd.census(SKILLS_ROOT))
    alive = fd.reader_sources_alive(s["per_kind"])
    dark = sorted(src for src, ok in alive.items() if not ok)
    assert not dark, (
        f"census input(s) {dark} produced ZERO reach — the instrument is broken, not the coverage. "
        f"per_kind={s['per_kind']}. Fix the parser; do not re-baseline the ceiling against a dark input."
    )
    assert s["domain"] >= APERTURE_DOMAIN_FLOOR, (
        f"domain collapsed to {s['domain']} (floor {APERTURE_DOMAIN_FLOOR}) — cards stopped being "
        "discovered, so an orphan count measured against it means nothing"
    )

    orphans = s["candidate_orphans"]
    assert orphans <= APERTURE_CEILING, (
        f"declared-but-unread pairs rose to {orphans} (ceiling {APERTURE_CEILING}). A new "
        f"`outputs.summary_fields` entry with no reader is the usual cause: wire a reader in the same "
        f"PR, or declare the field's role in the owning skill's field_disposition.yaml. Raising this "
        f"ceiling is not an option — see APERTURE_CEILING."
    )
    assert APERTURE_CEILING - orphans <= APERTURE_SLACK, (
        f"aperture is now {orphans}, {APERTURE_CEILING - orphans} below the ceiling — bank it: set "
        f"APERTURE_CEILING = {orphans}. An un-tightened ceiling silently re-opens the ratchet."
    )


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
