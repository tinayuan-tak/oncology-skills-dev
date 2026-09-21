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

# ★ Frozen 2026-09-14 on `v2-architecture` @ cc7226b1 with target-contracts @ fa372c84 (the CI pin):
# domain 1801 / reached_exact 742 / reached_any_upper_bound 912 / candidate_orphans 889.
#   (prior freeze, same day @ 698c203e / contracts fa372c84: 1801 / 696 / 910 / 891.)
# RE-MEASURED at cc7226b1 rather than carried over from 92f4d4a6, where this branch was cut. Trunk moved
# one commit under it (#1373), and that commit touches skills/target-profile/scripts/tp_gates.py, which
# IS a census input — so the base had to be re-measured, not assumed inert. It is inert: trunk @ cc7226b1
# measures 1801 / 696 / 910 / 891, identical to 92f4d4a6, and this branch on top of cc7226b1 measures
# 889. The reason to check at all is that this ratchet is TWO-SIDED: a trunk commit that IMPROVED the
# aperture would push `orphans` further BELOW the ceiling and fail the SLACK half, so a moving base can
# red this PR by making the metric BETTER. Re-measure on every rebase, not only when git reports a
# conflict — the census reads the whole tree, so there is no textual overlap to warn you.
# Measured against contracts `f5b475e`, one commit AHEAD of the pin, which is sound only because that
# commit is census-inert and was checked rather than assumed: fa372c84..f5b475e touches
# tests/schemas/test_subgroup_catalog_contract.py and vocabularies/subtype_crosswalk.yaml, and the
# census's only contracts inputs are cards/*.card.yaml, coverage/rule_role_partition.yaml and
# interpretation-rules/*.rules.yaml. If you re-measure against a contracts tree that does touch those
# three, the number is a different experiment — diff the paths first.
#
# BOTH SHAs ARE PART OF THE NUMBER, and since #1367 that is enforceable rather than aspirational: the
# contracts checkout in .github/workflows/skills-validate.yml is a PINNED SHA, not `ref: main`. This
# constant is a function of (skills tree, contracts tree) — measured on the same skills tree, the two
# candidate contracts trees give 912 and 891 — so a freeze that names only its own repo records half of
# an experiment. Re-measure against the PIN, not against whatever contracts `main` happens to be.
#
# WHY 891 AND NOT 919. Two separate movements, and only the second was earned here:
#   919 -> 912  peers wired 7 pairs between the 09-13 freeze and 09-14 without re-tightening. This is
#               the decay the slack assertion below exists to catch, and it is why that assertion is
#               not optional: 7 banked-but-unclaimed pairs are 7 that a later regression could spend.
#   912 -> 891  TC#772 declared `capsule:` on the three entirely-exact-dark cards
#               (genomic-instability-state, target-safety-prioritisation, reactome-pathway-membership),
#               wiring 22 pairs to the `capsule` reader.
# `domain` is unchanged at 1801 across that second move, which is the load-bearing check: a `capsule:`
# block is not an `outputs.summary_fields` entry, so it cannot enlarge the domain. The aperture closed
# because more of a FIXED domain became read — the one direction this ratchet is trying to reward.
# The orphan count falls by 21 while `reached_exact` rises by 22 because `genomic-instability-state::
# n_samples` was already credited name-only (a generic field name matched by three code kinds), so it
# moves from `reached_any` into `reached_exact` without leaving the orphan set. Quote 21, not 22.
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
#
# IF THE READER LIVES IN CONTRACTS, MOVE THE PIN IN THE SAME COMMIT. This ratchet is two-sided, so a
# contracts-side wiring change splits into two commits that each fail on a different assertion: bumping
# the pin alone trips the SLACK assert (891 orphans under a 919 ceiling = gap 28), and lowering the
# ceiling alone trips the CEILING assert (the pinned tree still measures 912 > 891). Neither half can
# land first — this pair went in together for exactly that reason. The bump PR from #1367 cannot do it
# either: its quarantine assumes a sibling move is neutral or BREAKING, and here the sibling move is an
# IMPROVEMENT that a lone bump makes look like a break.
#
# WHY 889 AND NOT 891, AND WHY THIS MOVE IS NET OF A RISE. First banked move that is not a pure
# reduction, so the arithmetic is stated rather than left to be re-derived: 3 pairs were wired and 1
# pair BECAME an orphan, for −2. Do not read "wired 3, ceiling moved 2" as an accounting error.
#   −3  `presence_question_table` Q2/Q3 now name WHICH, not only HOW MANY: `most_elevated_cohorts`,
#       `rna_most_elevated_indications` (Q2 printed "protein 4/9 cohorts · RNA 5/13 indications" and
#       named no cohort — the support clause that module's own docstring has always declared for Q2)
#       and `specific_tissues` (Q3 printed "HPA normal: broad_normal_expression" and named no tissue).
#       All three are LISTS, and no generic capsule selector can surface a container: `_sibling_caveats`
#       drops list/dict, `_numeric_anchors`/`_n_basis` require int|float, `_provenance_keys` requires
#       str|int|float, and `_categorical_anchors` — the only list-capable path — fires only for
#       contract-declared fields. A question row was the only reachable surface.
#   +1  `_card_aliases` now resolves the local-helper idiom `cp = _summary("card-id")`, which
#       tumor-selectivity/scripts/run.py uses for ~9 cards in one function. That resolves
#       `spatial_rna = _summary("spatial-region-rna-expression")`, and the RNA card's exact read of
#       `tumour_vs_tme_delta` had been spreading NAME-ONLY credit to every card declaring that name —
#       including `spatial-surface-protein-abundance`, whose own copy no code reads. Withdrawing false
#       credit RAISES the count, and that is the instrument getting more honest, not a regression: the
#       protein arm's magnitude is genuinely unread while the RNA arm's is read (run.py:929).
# So a scraper fix that improves reach CANNOT LAND ALONE under this rule — +43 exact reads arrive with
# +1 orphan, and "only downward" then forbids the very PR that earned the improvement. It is paired
# with the wiring above for exactly that reason. Expect this shape again: any parser fix that resolves
# a binding withdraws name credit somewhere, so budget a wiring partner in the same PR.
#
# WHY 887 AND NOT 889. Two pairs wired, nothing newly orphaned — asserted as a SET DIFFERENCE, not as a
# count, because a net −2 is also what "3 wired, 1 lost" looks like, and that is precisely what the 889
# move above was.
#   −2  `rna_protein_spearman` on BOTH concordance cards (`rna-protein-concordance-tumor` and
#       `cellline-rna-protein-concordance`). The producer classifies `rna_as_biomarker` on SPEARMAN —
#       `depmap_rna_protein_concordance/read.py` does `_classify_r = spear if spear is not None else
#       pear` and records which per row in `rna_proxy_classified_on` — and emitted the Spearman on both
#       arms, but nothing in the fleet read it. Q6 printed the PEARSON beside that Spearman-derived
#       class, so the displayed number's own class contradicted the label next to it in 113 of 375
#       cell-line rows and 31 of 195 tumor rows of the n=504 corpus. Declared-but-unread was not
#       cosmetic here: the metric on the row was never the one that decided.
# MEASURED ACROSS THE PIN, so no pin move is entangled in this one: contracts @ fa372c84 (the tree CI
# actually reads) and contracts @ main 39f04a9 (post-TC#774, the local checkout) BOTH measure 889 → 887
# on domain 1801. TC#774 was aperture-neutral, so unlike the 889 move this bank is skills-only.
#
# ── RE-MEASURED 2026-09-15, when the CI pin moved fa372c84 → c88c6e04 (TC#777 step 3 + TC#779) ─────
# 885 orphans on domain 1801 (reached_exact 744, reached_any 916): gap 2. BOTH halves stay green
# (885 ≤ 887; 887 − 885 = 2 ≤ APERTURE_SLACK 20), SO THE CEILING DOES NOT MOVE — this note records a
# new VINTAGE, not a new number. Trunk had already improved 887 → 885 under this ceiling before the
# pin moved, which is why the gap is 2 rather than 0.
#   ⚠️ A NUMBER THAT DID NOT MOVE STILL HAS A NEW VINTAGE. Leaving "measured at fa372c84" here while
#   the workflow reads c88c6e04 is the same fail-open #1388 closed on the bump-sibling-pins side: the
#   `ref:` advances, the vintage comment keeps its stale date, and nothing reds. An unchanged number
#   is the easiest case to forget, because there is no diff to prompt the edit.
# ATTRIBUTED AS A 2x2, not a before/after pair — the pin move contributes 0 AND the step-3 skills diff
# contributes 0, and a single pair cannot separate those. ROWS vary the skills tree and COLUMNS vary
# the contracts tree, so the pin move is read ACROSS a row and the step-3 diff DOWN a column:
#                              contracts fa372c84    contracts 6d6a14b
#     skills trunk 8117c56a           885                  885
#     skills branch (step 3)          885                  885
# Then re-measured against the sha the workflow ACTUALLY pins — c88c6e04, which is 6d6a14b plus
# TC#779's retraction — on the committed branch: 885, its fa372c84 pair also 885. Those two cells are a
# SEPARATE run on a different skills tree, not two columns of the grid above, and they were run rather
# than inherited: the two contracts shas differ only by a changelog retraction, but "differs only by a
# comment" is an argument about the census's inputs and 885 is a measurement of its output.
# NOT census-inert by path, so it had to be measured rather than argued: the pinned range contains
# TC#774, which edits cards/genomic-instability-state.card.yaml — a census input.
# ★ POSITIVE CONTROL, because four equal numbers are ALSO what a collapsed comparison looks like:
# contracts a716f923 (pre-TC#772) measures 906 on the same skills tree, Δ21 — reproducing exactly the
# 21 pairs TC#772 was banked as wiring, on a DIFFERENT skills base than that bank was taken on. So the
# census demonstrably responds to the contracts axis, and 885 == 885 is a result, not a tautology.
# ★ AND THE FIRST RUN OF THIS 2x2 WAS VACUOUS: the cells were labelled with `git rev-parse HEAD`, but
# the step-3 diff was uncommitted at the time, so the branch cell's HEAD *was* trunk's sha and all four
# cells self-reported identically. A label that cannot distinguish the trees being compared turns an
# attribution into four copies of one measurement. The cells are now keyed on HEAD + a digest of
# `git diff HEAD`, and the script asserts no two cells share an identity.
#
# WHAT THIS NUMBER STILL OVER-COUNTS, MEASURED. `capsule_readers` credits only contract-declared
# `capsule.numeric_anchors`/`categorical_fields`, so the four HINT SCANS in evidence_capsule.py
# (`_numeric_anchors` fallback sorted+cap-4, `_n_basis` cap-3, `_sibling_caveats`, `_provenance_keys`
# cap-5) are invisible here. Running the real `emit_capsules()` over the real epcam_coadread fixture:
# 24 of the 100 fixture-covered orphans ARE displayed, among them `expression_purity_spearman_r` and
# `n_specific_tissues`. So this count conflates "not displayed" with "displayed by an alphabetical
# guess", and the remedy for that class is a contracts-side `capsule:` DECLARATION — which makes the
# display deterministic and earns exact credit at once — not a second reader. Do not wire a field that
# a hint scan already surfaces; that adds a duplicate display to move a counter.
#
# ⚠️ AND THAT WARNING IS LIVE RATHER THAN THEORETICAL, because the override is PER-SLOT, not per-card —
# measured by session 1972e09f, correcting card.schema.json:846 ("when present it OVERRIDES the capsule's
# field-selection heuristics for this card"), which is false as written. With a `capsule:` block present on
# tumor-vs-normal-selectivity, the `_ANCHOR_HINTS` scan STILL RAN and returned
# `cross_subgroup_delta_log2fc` + `log2fc_cell_a/b/c`; and `_sibling_caveats(summary, cfg)` / `_n_basis(summary)`
# take no capsule-contract parameter at all, so no declaration can reach them. Of the four scans the block
# governs exactly one. ⇒ declaring a field never switches the other slots off, so a declaration CAN
# coexist with a hint-scan hit on a different slot and render the field twice. Check the field name
# against the hint tables, not against the presence of a `capsule:` block.
# ── BANKED 2026-09-18 887 → 862, measured against contracts c3eec129 (the SHA skills-validate.yml
# pins for target-contracts at :251, == this session's home checkout HEAD, so the local census equals
# CI's). SKILLS-ONLY, no pin move: the -23 is entirely THIS BRANCH newly reading fields via the
# descriptor-coverage SALIENCE_SPECS mints for 7 dependency/combination measurement_types
# (paralog_buffering, partner_conditional_dependency, cross_consortium_paralog_gi, coessential_module,
# cross_consortium_dependency, patient_model_correspondence, pathway_node_leverage) — their card fields
# were genuinely unread before, so classifying them is real coverage, and the SLACK half requires the
# improvement be banked or the ratchet re-opens by 25. The reader lives in _skills_common (salience), NOT
# contracts, so no pin bump is entangled (cf. the skills-only 889 / TC#774 banks above). Prior vintage:
# 885 @ c88c6e04 (2026-09-15).
# ── BANKED AGAIN 2026-09-18 862 → 836, same method, measured against contracts c3eec129 (the CI pin).
# SKILLS-ONLY: the -26 is THIS BRANCH newly reading fields via the presence/selectivity/spatial
# descriptor-coverage mints (tumor_vs_normal_protein_abundance, spatial_colocalization,
# spatial_region_rna, spatial_surface_protein, sc_tumor_caf_state_expression,
# sc_tumor_myeloid_state_expression, phospho_pathway_activity) — genuinely-unread card fields now
# classified. Reader is skills-side salience, no pin move.
# ── BANKED AGAIN 2026-09-18 836 → 781, same method, measured against contracts c3eec129 (the CI pin,
# skills-validate.yml:251). SKILLS-ONLY, no pin move: the -40 is THIS BRANCH's L2 record-grain identity
# pilot (target-contracts #804/decision #4) newly reading each emitted card's `summary.method_version`
# in _skills_common/dispatcher.py `_l2_method_versions` — that dict becomes claim_record.provenance.versions
# and is hashed into identity.record_revision_id, so a method bump revises the L2 record. Measured: the
# cleared set is EXACTLY 40 pairs, ALL field `method_version` (census diff main 18b0e8d2 → this branch,
# both against c3eec129), and 0 pairs newly orphaned. It is a NAME-ONLY reader (a generic
# `summary["method_version"]` access binds to no single card_id statically), so per the summarise()
# docstring it credits every card declaring the name — the accepted mechanism the salience banks above
# also used; the runtime read is correctly scoped to emitted_cards. Prior vintage: 821 @ 18b0e8d2 was
# 15 below the 836 ceiling (within slack), so trunk was green before this branch.
APERTURE_CEILING = 781

# Slack before the ceiling must be re-tightened. Without an upper bound on the gap, the ceiling decays
# into a number nobody has re-measured, and the ratchet quietly re-opens by exactly the amount of
# progress that was made and never banked. 20 is wide enough that a single wiring PR need not touch
# this file, narrow enough that a batch of them must.
APERTURE_SLACK = 20

# A domain floor, so a census that discovers no cards cannot pass the ceiling by measuring nothing.
# Trunk is 1801; 1500 leaves room for real card retirement without leaving room for an outage.
APERTURE_DOMAIN_FLOOR = 1500

# ★★ A MERGE GATE THAT NAMES A REMEDY MUST BE TESTED AGAINST ITS OWN REMEDY — credited to session
# 1972e09f, who measured it. This message used to advise "declare the field's role in the owning skill's
# field_disposition.yaml", which is the ONE remedy `census()` is deliberately built to ignore:
# field_disposition.py's module docstring says so outright ("THE APERTURE METRIC IS BLIND TO
# DECLARATIONS ... the metric would measure our own paperwork") and `census()`'s own docstring repeats it.
# PROVEN BY EXISTENCE rather than by reading the docstring: of the 891 orphans measured against contracts
# main, 105 ALREADY carry a declared role in tumor-presence/field_disposition.yaml — 55 `context`, 26
# `display`, 23 `provenance`, and 1 `signal`. Declared, and still counted.
#
# Why the wrong string is worse than a stale comment: an untested remedy string reds nothing and breaks
# no test, so it is fail-open in the READER's direction. Whoever obeys it spends a PR, moves the counter
# by exactly zero, and is invited to conclude the ratchet is broken when it is the ADVICE that is. The
# ledger-blindness is CORRECT anti-gaming design; the defect was entirely in this message.
#
# ⚠️ And note what the corrected string must NOT say either: a `numeric_anchors` declaration naming a
# BOOL earns aperture credit and renders nothing, because evidence_capsule.py's declared path filters
# `not isinstance(v, bool)` while `capsule_readers` credits the pair regardless. That is a counter-move
# reachable by obeying the contract — strictly worse than this string was, since it banks a false
# improvement rather than wasting a PR. Bool flags belong in `categorical_fields`, which the card schema
# says explicitly and which has no type filter.
_APERTURE_REMEDY = (
    "wire a declared reader in the same PR (a rule, a capsule projection, a salience ruler, or a "
    "code reader), or — for a display-only field — add it to the owning card's contracts-side "
    "`capsule:` block, which makes the display deterministic and earns exact credit at once. Put "
    "bool flags in `categorical_fields`, never `numeric_anchors` (the renderer type-filters bools out "
    "while the census still credits them, so that combination moves this counter and displays "
    "nothing). Declaring a role in field_disposition.yaml does NOT help: `census()` never reads the "
    "ledger, by design"
)


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
    zero orphans and satisfies the ceiling comfortably. `skill_code` alone reaches 755 pairs, so a
    total would keep this green through a complete contracts-side outage. (Stated as the ceiling, not
    as a literal — a copy of the number in prose goes stale the first time the ratchet is banked.)
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
        f"`outputs.summary_fields` entry with no reader is the usual cause: {_APERTURE_REMEDY}. "
        f"Raising this ceiling is not an option — see APERTURE_CEILING."
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


# ── the alias SCOPE boundary ───────────────────────────────────────────────────────────────────────
#
# `_card_aliases` promises an alias "cannot leak across functions that reuse the same short name",
# and `ast.walk` is not scope-aware, so the promise is only as good as what each scope is handed.
# The module-level scope used to be the raw tree, which unioned every function-local binding in a
# file into one map and then walked every read in that file: on trunk that fabricated 5 (card, field)
# pairs, 3 of them plainly false. These drive both directions from a SYNTHETIC tree so each can be
# falsified by construction — a leak test that cannot see a real read proves nothing.


def _alias_tree(tmp_path: Path, sub: str, body: str) -> Path:
    """A one-file skills tree whose module lands in the default `skill_code` kind."""
    d = tmp_path / sub / "skills" / "some-skill" / "scripts"
    d.mkdir(parents=True)
    (d / "run.py").write_text(body)
    return tmp_path / sub / "skills"


@needs_contracts
def test_an_alias_does_not_leak_from_one_function_to_another(tmp_path):
    """THE LEAK. Two functions, one reused short name: the binder names a card, the reader's `s` is an
    unrelated tuple-unpacked local. Crediting the pair invents a read that does not exist, and an
    invented read reads as COVERAGE — the census stops calling the field an orphan."""
    card, field, _, _ = _two_real_fields()
    leaked = fd.code_readers(
        _alias_tree(
            tmp_path,
            "leak",
            f'def binder(c):\n    s = c.get("{card}")\n    return s\n\n\n'
            f'def reader(rows):\n    for r in rows:\n        s, cf = r["signal"], r["confidence"]\n'
            f'        return s.get("{field}"), cf\n',
        )
    )[0]
    # `.get` because a fully-fixed scraper credits NOTHING here, and `code_readers` omits the key
    # entirely rather than mapping it to an empty set.
    assert (card, field) not in leaked.get("skill_code", set()), (
        "an alias bound in one function credited a read in another — the module-level scope is "
        "unioning function locals again"
    )
    # POSITIVE CONTROL: the identical read, moved INSIDE the binder, must be credited. Without this
    # the test above passes just as well when the scraper has gone blind to the shape entirely.
    honest = fd.code_readers(
        _alias_tree(tmp_path, "honest", f'def binder(c):\n    s = c.get("{card}")\n    return s.get("{field}")\n')
    )[0]
    assert (card, field) in honest["skill_code"], "fixture is not a valid shape (2/3) read at all"


@needs_contracts
def test_an_alias_bound_in_an_enclosing_function_still_reaches_a_nested_closure(tmp_path):
    """THE OTHER DIRECTION, and the reason the fix drops function bodies from the MODULE scope only.
    A nested function really does see its enclosing function's locals, so walking into nested defs is
    correct for a FunctionDef scope. Blanket-scoping every scope loses this, and a lost binding does
    not fail quietly: the read falls through to NAME-ONLY credit, which is credited to every card
    declaring the name and so spreads false credit instead of removing it."""
    card, field, _, _ = _two_real_fields()
    exact, _ = fd.code_readers(
        _alias_tree(
            tmp_path,
            "closure",
            "def outer(cards):\n"
            "    def _summary(cid):\n"
            '        return next((c for c in cards if c["card_id"] == cid), {}).get("summary") or {}\n\n'
            f'    cp = _summary("{card}")\n\n'
            "    def _render():\n"
            f'        return cp.get("{field}")\n\n'
            "    return _render()\n",
        )
    )
    assert (card, field) in exact["skill_code"], (
        "a closure over an enclosing function's card alias lost its binding — this is the ~9-card "
        "idiom in tumor-selectivity/scripts/run.py and it degrades to name-only credit"
    )


@needs_contracts
def test_a_genuine_module_level_alias_read_is_still_credited(tmp_path):
    """The module scope is narrowed, not deleted. Measured on trunk it contributed ZERO correct pairs
    of its own, so this shape has no live witness — which is exactly why it needs a synthetic one: an
    over-narrowed module scope would otherwise go dark with nothing to notice it."""
    card, field, _, _ = _two_real_fields()
    exact, _ = fd.code_readers(
        _alias_tree(
            tmp_path,
            "modlevel",
            f'CARDS = {{}}\nS = CARDS.get("{card}")\nVALUE = S.get("{field}")\n',
        )
    )
    assert (card, field) in exact["skill_code"], "the module-level scope no longer reads anything"


# ── the summary CONTAINER HOP ──────────────────────────────────────────────────────────────────────
#
# Two indexing idioms coexist in the tree and the read site cannot tell them apart:
# `{cid: c.get("summary")}` maps a card id to the SUMMARY, so `cp.get("f")` is a field read, while
# `{cid: c}` maps it to the CARD, so the field read is one hop further in. Under the second idiom
# every read was attributed one level too high: `summary` itself got credited as a FIELD, and the real
# reads off the rebound name fell through to name-only.


@needs_contracts
def test_the_summary_hop_credits_the_field_and_not_the_container(tmp_path):
    card, field, _, _ = _two_real_fields()
    assert "summary" not in set(fd.declared_fields().get(card) or ()), (
        "fixture assumption: this card declares no field called 'summary', which is what makes the "
        "container-hop guard observable — the guard is by DECLARATION, so a card that really declared "
        "it would get the credit back"
    )
    exact, name_only = fd.code_readers(
        _alias_tree(
            tmp_path,
            "hop",
            "def render(cards):\n"
            f'    adc_card = cards.get("{card}")\n'
            '    adc = adc_card.get("summary") or {}\n'
            f'    return adc.get("{field}")\n',
        )
    )
    assert (card, field) in exact.get("skill_code", set()), (
        "the hop was not followed, so the real field read is invisible and falls to name-only credit"
    )
    assert (card, "summary") not in exact.get("skill_code", set()), (
        "the CONTAINER ACCESS was credited as a field read — that is a fabricated (card, field) pair"
    )
    assert "summary" not in name_only.get("skill_code", set()), (
        "name-only credit for 'summary' is worse than useless: it credits every card declaring the name"
    )


@needs_contracts
def test_the_summary_hop_will_not_invent_a_binding_from_an_unbound_receiver(tmp_path):
    """FALSIFIABILITY. The hop must inherit a binding, never manufacture one: a `.get("summary")` off
    a name that is not a known card alias has nothing to inherit, so the reads below it stay
    unresolved. Otherwise the rule would bind any local that happens to touch a `summary` key."""
    card, field, _, _ = _two_real_fields()
    exact, _ = fd.code_readers(
        _alias_tree(
            tmp_path,
            "nohop",
            f'def render(payload):\n    adc = payload.get("summary") or {{}}\n    return adc.get("{field}")\n',
        )
    )
    assert (card, field) not in exact.get("skill_code", set()), "the hop invented a card binding out of nothing"


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


# ── shape (6): the local-helper alias ─────────────────────────────────────────────────────────────
#
# `cis = _s("cis-feature-expression-coherence")` — a nested closure over the card list. Shapes (2)/(3)
# see a RECEIVER (`c.get("card-id")`, `c["card-id"]`) and bind the card off it; a call on a bare Name
# has no receiver to inspect, so every read off such an alias fell through to NAME-ONLY credit. That is
# not merely weaker evidence: name-only credit is granted to every card declaring the name, so the miss
# did not just under-count its own card, it handed false credit to that card's siblings. Two
# `_headline()` builders use the idiom for 19 card binds between them, under two different helper names
# (`_s`, `_summary`), so the match is on SHAPE and never on the helper's name.
#
# Driven from synthetic source, so each guard is falsifiable by construction; then pinned live.

_ALIAS_CARDS = frozenset({"card-alpha", "card-beta"})


def _aliases(src: str, known: frozenset = _ALIAS_CARDS) -> dict:
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef))
    return fd._card_aliases(fn, known)


def test_helper_bound_alias_binds_the_card():
    """The idiom itself. `known_cards` is supplied BY THE TEST, so unlike a hardcoded live card id this
    cannot decay through a card rename — the shape is what is under test here, not the corpus."""
    src = 'def _headline(cards):\n    cis = _s("card-alpha")\n    return cis.get("some_field")\n'
    assert _aliases(src) == {"cis": "card-alpha"}


def test_helper_alias_matches_on_shape_not_on_the_helper_name():
    """The two live call sites use different helper names. Keying on a name would fix one skill and
    leave the other silently name-credited, which is the harder failure to notice of the two."""
    for helper in ("_s", "_summary", "_card", "pick"):
        src = f'def f(cards):\n    a = {helper}("card-alpha")\n    return a\n'
        assert _aliases(src) == {"a": "card-alpha"}, f"{helper}() did not bind"


@pytest.mark.parametrize(
    "call, why",
    [
        ('_s("card-alpha", "extra")', "two positional args — the helper is doing something unverifiable"),
        ('_s("card-alpha", default={})', "a keyword argument, same reason"),
        ("_s(cid)", "a variable, not a literal — the card is not knowable statically"),
        ('_s("log2-fc")', "a kebab-shaped literal that names no real card"),
        ("_s()", "no argument at all"),
    ],
)
def test_helper_alias_is_narrow(call, why):
    """NEGATIVE controls, one per rejected form. A wrong binding attributes a read to the WRONG card,
    and an over-credit reads as coverage — the failure this whole census exists to detect."""
    assert _aliases(f"def f(cards):\n    x = {call}\n    return x\n") == {}, why


def test_a_direct_alias_outranks_a_helper_alias_for_the_same_name():
    """Shape precedence, asserted in BOTH source orders so it is clearly not source-order last-write.

    `ast.walk` is breadth-first, so source order is not available at this layer for free; the two-pass
    split therefore prefers the shape that can SEE a receiver, in either order. That is a deliberate
    tiebreak on a case the tree does not currently contain — see the inertness guard below — because a
    helper's return value is only inferred, while a receiver is observed.
    """
    fwd = 'def f(c):\n    x = c.get("card-alpha")\n    x = _s("card-beta")\n    return x\n'
    rev = 'def f(c):\n    x = _s("card-beta")\n    x = c.get("card-alpha")\n    return x\n'
    assert _aliases(fwd) == {"x": "card-alpha"}
    assert _aliases(rev) == {"x": "card-alpha"}


@needs_contracts
def test_no_live_function_binds_one_name_by_both_alias_shapes():
    """Keeps the tiebreak above INERT, and says so if it ever stops being inert.

    Measured 2026-09-14: 0 of 1944 functions bind one local name both ways, so the precedence rule
    never actually decides anything on this tree. If a function starts doing it, the later helper
    assignment would be OVERRIDDEN by the earlier direct one and the reads below it would be credited
    to the wrong card — silently, as coverage. This test is that alarm, not a style rule.
    """
    known = frozenset(fd.declared_fields())
    scanned, both = 0, []
    for path in sorted(SKILLS_ROOT.rglob("*.py")):
        if "/tests/" in str(path) or "/.pixi/" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            scanned += 1
            direct, helper = set(), set()
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
                    continue
                target, value = node.targets[0], node.value
                if not isinstance(target, ast.Name):
                    continue
                if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr == "get":
                    if value.args and fd._is_card_id(fd._literal(value.args[0]), known):
                        direct.add(target.id)
                elif isinstance(value, ast.Subscript):
                    if fd._is_card_id(fd._literal(value.slice), known):
                        direct.add(target.id)
                elif isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                    if len(value.args) == 1 and not value.keywords:
                        if fd._is_card_id(fd._literal(value.args[0]), known):
                            helper.add(target.id)
            for name in direct & helper:
                both.append(f"{path.relative_to(SKILLS_ROOT)}:{fn.lineno} {fn.name}() name={name!r}")
    assert scanned >= 1500, f"only {scanned} functions scanned — this guard has gone vacuous"
    assert not both, (
        "a local name is bound by both alias shapes; reads below the helper bind to the wrong card:\n" + "\n".join(both)
    )


@needs_contracts
def test_helper_alias_reaches_declared_fields_on_the_live_tree():
    """Live pin, and the reason this shape was worth adding.

    `cis-feature-expression-coherence` measured 0 exact `skill_code` fields before this shape resolved
    and 20 after — 31 fields declared, read off one `_s()` alias in `cis-feature/scripts/run.py`. All
    four pins below are absent on trunk, so this test fails by construction without the shape.
    """
    exact, _ = fd.code_readers(SKILLS_ROOT)
    sk = exact.get("skill_code", set())
    for pin in (
        ("cis-feature-expression-coherence", "cn_expr_spearman_r"),
        ("cis-feature-expression-coherence", "cis_dosage_class"),
        ("spatial-region-rna-expression", "spatial_rna_class"),
        ("spatial-tumor-normal-colocalization", "spatial_coloc_class"),
    ):
        assert pin in sk, f"{pin} is not exact — the helper-alias shape has stopped resolving"
    n = len({f for c, f in sk if c == "cis-feature-expression-coherence"})
    assert n >= 15, f"only {n} exact skill_code fields on cis-feature-expression-coherence (was 20)"


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


# Instruments the aperture failure message is allowed to send a reader to, mapped to the census kind
# that would actually credit the resulting edit. The mapping is the point: it makes the MESSAGE and
# `READER_KINDS` co-vary, so retiring or renaming a kind reds this test and forces the prose to be
# rewritten instead of quietly becoming advice for an instrument that no longer exists.
_REMEDY_INSTRUMENTS = {
    "rule": ("gating_rule", "display_rule"),
    "capsule": ("capsule",),
    "salience": ("salience",),
    "code reader": ("skill_code",),
}


def test_aperture_failure_message_advises_only_instruments_the_census_can_credit():
    """★★ A MERGE GATE THAT NAMES A REMEDY MUST BE TESTED AGAINST ITS OWN REMEDY.
    Found and measured by session `1972e09f`, 2026-09-15.

    The three tests above make the CODE blind to the ledger, strip prose so a comment cannot pass for a
    read, and prove the allowlist is not vacuous — a genuinely well-guarded anti-gaming contract. None
    of them looks at what the gate TELLS a reader to do, and for as long as that was true the failure
    message advised the one remedy the code is built to ignore ("declare the field's role in the owning
    skill's field_disposition.yaml").

    ★ A wrong instruction is fail-open in the READER's direction. It reds nothing and breaks no test, so
    the suite cannot notice it; the cost lands entirely on whoever obeys it, who spends a PR, moves the
    counter by exactly zero, and is then invited to conclude the ratchet is broken when it is the ADVICE
    that is. Measured witness at the time of the fix: of 891 candidate orphans, **105 already carried a
    declared role** in `tumor-presence/field_disposition.yaml` — 55 `context`, 26 `display`, 23
    `provenance`, 1 `signal`. `confusion()` is the supported way to re-derive that (its `unreached`
    buckets), and it is deliberately not re-derived here: this test guards the PROSE, and paying for a
    full census to restate a property three other tests already assert would be duplicated cost.

    The ledger may still be NAMED — the corrected message names it precisely to warn the reader off —
    so a bare substring check would fire on the fix. That is the same trap as a comment documenting an
    absent key grep-matching as a declaration, which `_code_only` exists to handle one layer down; here
    the mention is only legal inside an explicit disclaimer.
    """
    for kinds in _REMEDY_INSTRUMENTS.values():
        for kind in kinds:
            assert kind in fd.READER_KINDS, (
                f"the aperture remedy points readers at {kind!r}, which is no longer a census reader "
                f"kind — rewrite _APERTURE_REMEDY rather than leaving prose for a retired instrument"
            )

    named = [phrase for phrase in _REMEDY_INSTRUMENTS if phrase in _APERTURE_REMEDY]
    assert named, (
        "_APERTURE_REMEDY names no creditable instrument at all; a failure message that does not say "
        f"what would actually work is the defect this test exists for. Expected one of "
        f"{sorted(_REMEDY_INSTRUMENTS)}"
    )

    if "field_disposition.yaml" in _APERTURE_REMEDY:
        assert re.search(r"field_disposition\.yaml[^.]*does NOT help", _APERTURE_REMEDY), (
            "_APERTURE_REMEDY offers the per-skill ledger as a remedy, but `census()` never reads it "
            "(see test_aperture_measurement_never_reads_a_disposition_declaration) — 105 of the 891 "
            "orphans measured 2026-09-15 already carried a declared role. The ledger may only be "
            "mentioned to disclaim it."
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


# ── shape (6): the card-alias SUBSCRIPT read ────────────────────────────────────────────────────────
#
# Shapes 2/3 only fire on a `.get` CALL, and the scrape loop visits only `ast.Call`, so a subscript
# read off a card alias (`cp = c.get("card"); cp["field"]`) was never visited at all. On trunk today
# every such read is SHADOWED by a `.get` of the same field in the same scope (presence_claims.py reads
# `tva["log2_fc"]` at :483 but also `tva.get("log2_fc")` at :196/:239/:477), so adding this shape moves
# the aperture by ZERO pairs — which is exactly why it can only be given teeth by a synthetic tree with
# a subscript-ONLY read. These drive both directions from that tree so each guard falsifies by
# construction.


@needs_contracts
def test_shape_6_alias_subscript_read_is_credited_exact(tmp_path):
    """POSITIVE CONTROL — the read shapes 1-5 miss. A card alias read by SUBSCRIPT and never by `.get`
    is a real field read; before shape 6 it fell through entirely (the loop skips non-Call nodes) and
    the pair read as a candidate_orphan. It must now be credited EXACT, not name-only."""
    card, field, _, _ = _two_real_fields()
    exact, name_only = fd.code_readers(
        _alias_tree(
            tmp_path,
            "sub6",
            f'def render(cards):\n    cp = cards.get("{card}")\n    return cp["{field}"]\n',
        )
    )
    assert (card, field) in exact.get("skill_code", set()), (
        "a subscript read off a bound card alias was not credited — shape 6 is not firing"
    )
    # Not name-only: the receiver resolves to a specific card, so the credit must be bound to it.
    assert field not in name_only.get("skill_code", set()), (
        "the subscript read leaked into name-only credit, which over-credits every card declaring the name"
    )


@needs_contracts
def test_shape_6_double_subscript_read_is_credited(tmp_path):
    """`cards["card-id"]["field"]` — the receiver is a literal-card-id subscript rather than a bound
    alias, so the card binds from the inner slice. Same exact credit."""
    card, field, _, _ = _two_real_fields()
    exact, _ = fd.code_readers(
        _alias_tree(tmp_path, "dsub6", f'def render(cards):\n    return cards["{card}"]["{field}"]\n')
    )
    assert (card, field) in exact.get("skill_code", set()), "the double-subscript read was not credited"


@needs_contracts
def test_shape_6_will_not_invent_a_binding_from_an_unbound_receiver(tmp_path):
    """FALSIFIABILITY, over-credit direction. A subscript off a name that is not a known card alias has
    no card to bind to, so it must credit NOTHING — never fall through to name-only, which would credit
    every card declaring the field name. This is what keeps `d["x"]` on an arbitrary dict from flooding
    the census."""
    card, field, _, _ = _two_real_fields()
    exact, name_only = fd.code_readers(
        _alias_tree(tmp_path, "unbound6", f'def render(payload):\n    return payload["{field}"]\n')
    )
    assert (card, field) not in exact.get("skill_code", set()), "invented a card binding from a bare dict subscript"
    assert field not in name_only.get("skill_code", set()), "an unbound subscript leaked into name-only credit"


@needs_contracts
def test_shape_6_ignores_a_subscript_write(tmp_path):
    """FALSIFIABILITY, wrong-direction. `cp["field"] = v` is a WRITE (ctx=Store), not a read — card
    preprocessors mutate the summary this way. Crediting a write as a read invents coverage for a field
    the code produces rather than consumes."""
    card, field, _, _ = _two_real_fields()
    exact, _ = fd.code_readers(
        _alias_tree(
            tmp_path,
            "write6",
            f'def mutate(cards):\n    cp = cards.get("{card}")\n    cp["{field}"] = 1\n    return cp\n',
        )
    )
    assert (card, field) not in exact.get("skill_code", set()), "a subscript WRITE was credited as a read"
