"""Hermetic tests for the reviewer disposition ledger. No network, no run dirs, no S3.

Every check here is paired with an ANTI-VACUITY assertion — a mutation that must make it fire. A
guard that cannot fail is worse than no guard: it reassures without protecting, and this repo has
already shipped three of them (a fail-closed rung nothing could reach, a `must_not_nominate` panel
assertion with no `nominate` in the precedence table, and a ruler whose ladder returned a constant).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_EVAL = Path(__file__).resolve().parents[1]
if str(_EVAL) not in sys.path:
    sys.path.insert(0, str(_EVAL))

import dispositions as D  # noqa: E402
import loop_health as lh  # noqa: E402


def _row(**kw):
    base = {
        "grain": "verdict",
        "judgment": "agree",
        "skill": "tumor-selectivity",
        "target": "EPCAM",
        "indication": "COADREAD",
        "axis": "SEL",
        "measuredness": "measured",
        "rater": "r1",
    }
    base.update(kw)
    return base


# --------------------------------------------------------------------------- vocabulary is CLOSED


def test_unknown_judgment_is_rejected_not_coerced():
    with pytest.raises(D.DispositionError, match="not legal for grain"):
        D.validate_row(_row(judgment="banana"))


def test_unknown_grain_is_rejected():
    with pytest.raises(D.DispositionError, match="unknown grain"):
        D.validate_row(_row(grain="vibes"))


def test_unknown_measuredness_is_rejected():
    with pytest.raises(D.DispositionError, match="unknown measuredness"):
        D.validate_row(_row(measuredness="probably"))


def test_judgment_legal_elsewhere_is_still_rejected_for_the_wrong_grain():
    """`noise` is a real token, but a VERDICT cannot be noise. A flat enum would have accepted this.

    This is the check that makes the vocabulary a type rather than a spelling list.
    """
    assert "noise" in D.ALL_JUDGMENTS  # the token is real…
    with pytest.raises(D.DispositionError, match=r"is a real judgment, but not for grain"):
        D.validate_row(_row(grain="verdict", judgment="noise"))
    # …and the converse: a verdict token is illegal on an atom.
    with pytest.raises(D.DispositionError, match="not legal for grain"):
        D.validate_row(_row(grain="atom", judgment="wrong_verdict"))


def test_every_grain_has_a_nonempty_vocabulary_and_they_do_not_overlap():
    assert set(D.JUDGMENTS_BY_GRAIN) == set(D.GRAINS)
    for grain, vocab in D.JUDGMENTS_BY_GRAIN.items():
        assert vocab, f"{grain} has no judgments — every row filed under it would be rejected"
    seen: dict[str, str] = {}
    for grain, vocab in D.JUDGMENTS_BY_GRAIN.items():
        for j in vocab:
            assert j not in seen, f"{j!r} is legal for both {seen[j]} and {grain} — grain becomes unrecoverable"
            seen[j] = grain


def test_abstention_is_a_distinct_judgment_from_being_wrong():
    """`unreadable` (should have abstained) must not be the same token as `wrong_verdict`.

    Collapsing them would score a coverage gap as a biology error — the same defect as giving an
    off-axis tier a number on the measurement ordinal.
    """
    v = D.JUDGMENTS_BY_GRAIN["verdict"]
    assert "unreadable" in v and "wrong_verdict" in v
    assert "unreadable" not in D.CORRECT_BY_GRAIN["verdict"]
    assert "wrong_verdict" not in D.CORRECT_BY_GRAIN["verdict"]


def test_artifact_is_distinct_from_noise_for_atoms():
    """The salience kill-criterion is an ARTIFACT rate, not a noise rate — they need separate tokens."""
    a = D.JUDGMENTS_BY_GRAIN["atom"]
    assert "artifact" in a and "noise" in a and "restatement" in a


def test_declaration_ORDER_of_the_vocabulary_carries_no_meaning(tmp_path, monkeypatch):
    """The judgment vocabulary is a SET, not an ordinal — nothing may read a token's tuple index.

    This is the guard that keeps the abstention invariant from decaying. `measuredness` + a separate
    `unreadable` token only protect a coverage gap from being scored as a biology error for as long as
    no consumer does arithmetic ACROSS tokens. The precedent is `evidence_capsule._cross_card_conflicts`,
    which flags `max(tier) - min(tier) >= 2`: the moment a non-measurement got any position on that
    ordinal, unmeasured cards started "disagreeing" with strong ones by 3 — contradictions fabricated
    out of missing data. So: permuting the declaration order must not move a single number.
    """
    # Counts are deliberately ASYMMETRIC. A balanced fixture (1 agree / 1 wrong of 3) makes both
    # polarities score 0.333, so the anti-vacuity mutation below would be invisible — which is exactly
    # how a check ends up passing for the wrong reason.
    # `sampled` throughout so BOTH output shapes are exercised: the all-selections counts and the one
    # quotable rate. A targeted-only fixture would leave `per_grain_agreement_sampled` empty, and the
    # permutation below would then be compared against a dict of zeros.
    rows = [
        D.validate_row(_row(judgment="agree", target="A", selection="sampled")),
        D.validate_row(_row(judgment="agree", target="B", selection="sampled")),
        D.validate_row(_row(judgment="unreadable", target="C", measuredness="blind", selection="sampled")),
        D.validate_row(_row(judgment="wrong_verdict", target="D", selection="sampled")),
        D.validate_row(_row(grain="atom", judgment="signal", target="E", axis="DEP", selection="sampled")),
        D.validate_row(_row(grain="atom", judgment="signal", target="F", axis="DEP", selection="sampled")),
        D.validate_row(_row(grain="atom", judgment="artifact", target="G", axis="DEP", selection="sampled")),
    ]
    baseline = D.summarize(rows)
    counts = baseline["per_grain_filed_counts_all_selections"]
    assert counts["verdict"] == {"n": 4, "n_correct": 2}
    assert counts["atom"] == {"n": 3, "n_correct": 2}
    assert baseline["per_grain_agreement_sampled"]["verdict"]["agreement"] == 0.5  # 2 of 4
    assert baseline["per_grain_agreement_sampled"]["atom"]["agreement"] == 0.667  # 2 of 3

    reversed_vocab = {g: tuple(reversed(v)) for g, v in D.JUDGMENTS_BY_GRAIN.items()}
    monkeypatch.setattr(D, "JUDGMENTS_BY_GRAIN", reversed_vocab)
    assert D.summarize(rows) == baseline, "something is reading a judgment's POSITION as a value"

    # ANTI-VACUITY: the test must be able to see a change at all. Reversing which tokens count as
    # CORRECT does move the numbers — so the comparison above is not trivially true.
    monkeypatch.setattr(D, "CORRECT_BY_GRAIN", {"verdict": ("wrong_verdict",), "atom": ("artifact",), "precedence": ()})
    assert D.summarize(rows) != baseline


def test_an_abstention_row_is_never_averaged_into_a_measured_rate():
    """A `blind`/`unreadable` row must not silently become a low score on a measured scale."""
    rows = [
        D.validate_row(_row(judgment="agree", target="A", measuredness="measured", selection="sampled")),
        D.validate_row(_row(judgment="unreadable", target="B", measuredness="blind", selection="sampled")),
    ]
    s = D.summarize(rows)
    # measuredness is reported on its OWN axis, not folded into the agreement figure…
    assert s["by_measuredness"] == {"measured": 1, "blind": 1}
    # …and `unreadable` is counted as its own token, never as a degree of `wrong_verdict`.
    assert s["by_grain"]["verdict"] == {"agree": 1, "unreadable": 1}
    assert "wrong_verdict" not in s["by_grain"]["verdict"]


def test_precedence_has_no_correctness_pole():
    """A preference is not a correctness claim; asserting an agreement rate over it would be a lie."""
    assert D.CORRECT_BY_GRAIN["precedence"] == ()


def test_precedence_requires_both_rules_and_they_must_differ():
    with pytest.raises(D.DispositionError, match="needs both rule_id and loser_rule_id"):
        D.validate_row(_row(grain="precedence", judgment="a_beats_b", rule_id="r-a"))
    with pytest.raises(D.DispositionError, match="the same rule"):
        D.validate_row(_row(grain="precedence", judgment="a_beats_b", rule_id="r-a", loser_rule_id="r-a"))
    ok = D.validate_row(_row(grain="precedence", judgment="a_beats_b", rule_id="r-a", loser_rule_id="r-b"))
    assert ok["judgment"] == "a_beats_b"


def test_missing_address_is_rejected():
    with pytest.raises(D.DispositionError, match="missing required field"):
        D.validate_row(_row(target=None))


# ------------------------------------------------------------------- selection: a rate needs a frame


def test_unknown_selection_is_rejected():
    with pytest.raises(D.DispositionError, match="unknown selection"):
        D.validate_row(_row(selection="i_just_felt_like_it"))


def test_selection_defaults_to_targeted_not_sampled():
    """The pessimistic default is the whole point: an unrecorded selection must not become a rate.

    If absence defaulted to `sampled`, every row filed during a defect hunt would silently enter the
    quotable denominator — the same failure as a fail-closed branch that defaults to open.
    """
    assert D.validate_row(_row())["selection"] == "targeted"
    assert "targeted" not in D.RATEABLE_SELECTION
    assert D.RATEABLE_SELECTION == ("sampled",)


def test_targeted_rows_are_excluded_from_the_quotable_rate():
    """ANTI-VACUITY: the same judgments must produce a rate when sampled and no rate when targeted."""
    wrong = [
        D.validate_row(_row(judgment="wrong_verdict", target="A", selection="targeted")),
        D.validate_row(_row(judgment="wrong_verdict", target="B", selection="targeted")),
    ]
    s = D.summarize(wrong)
    # Descriptively these WERE wrong — but that is reported as a COUNT, never as a ratio. There is no
    # key in the output that divides these two rows by anything.
    assert s["per_grain_filed_counts_all_selections"]["verdict"] == {"n": 2, "n_correct": 0}
    assert s["n_sampled"] == 0
    assert s["per_grain_agreement_sampled"] == {}, "a defect hunt yields no quotable rate at all"

    # Flip only `selection` — identical judgments now DO produce a rate. Proves the filter is the
    # selection field and not something incidental about the rows.
    sampled = [D.validate_row({**r, "selection": "sampled"}) for r in wrong]
    s2 = D.summarize(sampled)
    assert s2["n_sampled"] == 2
    assert s2["per_grain_agreement_sampled"]["verdict"] == {"n": 2, "agreement": 0.0}


def test_mixed_selection_keeps_the_two_denominators_apart():
    rows = [
        D.validate_row(_row(judgment="wrong_verdict", target="A", selection="targeted")),
        D.validate_row(_row(judgment="agree", target="B", selection="sampled")),
    ]
    s = D.summarize(rows)
    assert s["per_grain_filed_counts_all_selections"]["verdict"] == {"n": 2, "n_correct": 1}
    assert s["per_grain_agreement_sampled"]["verdict"] == {"n": 1, "agreement": 1.0}
    assert s["by_selection"] == {"targeted": 1, "sampled": 1}


def test_report_warns_when_a_filed_rate_is_not_a_sampled_rate(tmp_path):
    """The caveat must appear for a targeted ledger and must NOT appear once every row is sampled."""
    p = tmp_path / "d.jsonl"
    D.append_row(_row(judgment="wrong_verdict", target="A"), p)  # default: targeted
    md = lh.render_md(lh.compute({"a|T|I|X|calibration_gap": "fixed"}), lh.load_reviewer_ledger(p))
    assert "No framework-accuracy figure is available yet" in md

    q = tmp_path / "s.jsonl"
    D.append_row(_row(judgment="wrong_verdict", target="A", selection="sampled"), q)
    md2 = lh.render_md(lh.compute({"a|T|I|X|calibration_gap": "fixed"}), lh.load_reviewer_ledger(q))
    assert "No framework-accuracy figure" not in md2, "the warning must clear, or it becomes wallpaper"
    assert "the only quotable rate here" in md2


def test_cli_accepts_selection(tmp_path):
    p = tmp_path / "d.jsonl"
    argv = [
        "--ledger",
        str(p),
        "--grain",
        "verdict",
        "--judgment",
        "agree",
        "--skill",
        "s",
        "--target",
        "T",
        "--indication",
        "I",
        "--axis",
        "SEL",
        "--selection",
        "sampled",
    ]
    assert D.main(argv) == 0
    assert D.load(p)[0]["selection"] == "sampled"


# --------------------------------------------------------------------------- append-only


def test_append_writes_one_line_and_preserves_prior_bytes(tmp_path):
    p = tmp_path / "d.jsonl"
    D.append_row(_row(target="A"), p)
    first = p.read_bytes()
    D.append_row(_row(target="B"), p)
    after = p.read_bytes()
    assert after.startswith(first), "an append must not disturb a single prior byte"
    assert len(p.read_text().strip().splitlines()) == 2
    assert [r["target"] for r in D.load(p)] == ["A", "B"]


def test_chain_verifies_on_an_untampered_ledger(tmp_path):
    p = tmp_path / "d.jsonl"
    D.append_row(_row(target="A"), p)
    D.append_row(_row(target="B"), p)
    D.append_row(_row(target="C"), p)
    assert D.verify_chain(p) == 3
    rows = D.load(p)
    assert rows[0]["prev"] == D.GENESIS
    assert rows[1]["prev"] != D.GENESIS


def test_rewriting_a_filed_judgment_is_DETECTED(tmp_path):
    """ANTI-VACUITY for append-only: an in-place edit of row 1 must be caught, naming the line.

    This is the whole point of the chain. Without it, revising a past judgment to agree with the
    current build would be invisible — and the ledger would still read as evidence.
    """
    p = tmp_path / "d.jsonl"
    D.append_row(_row(target="A"), p)
    D.append_row(_row(target="B"), p)
    lines = p.read_text().splitlines()
    r0 = json.loads(lines[0])
    r0["judgment"] = "wrong_verdict"  # the reviewer "changed their mind" retroactively
    lines[0] = json.dumps(r0, sort_keys=True, separators=(",", ":"))
    p.write_text("\n".join(lines) + "\n")

    # Caught at line 1 by the row's OWN content digest — before the positional chain even matters.
    with pytest.raises(D.AppendOnlyViolation, match=r"d\.jsonl:1 content was REWRITTEN after filing"):
        D.verify_chain(p)
    with pytest.raises(D.AppendOnlyViolation):
        D.load(p)  # the strict read refuses too, so no consumer counts a rewritten ledger


def test_a_rewrite_that_fixes_up_the_chain_is_STILL_detected(tmp_path):
    """The sophisticated tamper: edit row 1 AND recompute every downstream `prev` so the walk is clean.

    Position-chaining alone cannot catch this — which is why each row binds its own content too.
    """
    p = tmp_path / "d.jsonl"
    D.append_row(_row(target="A", judgment="wrong_verdict"), p)
    D.append_row(_row(target="B"), p)
    rows = [json.loads(l) for l in p.read_text().splitlines()]
    rows[0]["judgment"] = "agree"  # the retroactive change of heart
    out, expected = [], D.GENESIS
    for r in rows:  # diligently re-chain so `prev` is internally consistent
        r["prev"] = expected
        line = json.dumps(r, sort_keys=True, separators=(",", ":"))
        out.append(line)
        expected = D._digest(line)
    p.write_text("\n".join(out) + "\n")

    with pytest.raises(D.AppendOnlyViolation, match="content was REWRITTEN"):
        D.verify_chain(p)


def test_deleting_a_row_is_DETECTED(tmp_path):
    """A dropped row is the other half of the tamper surface — an inconvenient judgment removed."""
    p = tmp_path / "d.jsonl"
    for t in ("A", "B", "C"):
        D.append_row(_row(target=t), p)
    lines = p.read_text().splitlines()
    p.write_text("\n".join([lines[0], lines[2]]) + "\n")  # drop row 2
    with pytest.raises(D.AppendOnlyViolation, match="breaks the append-only chain"):
        D.verify_chain(p)


def test_reordering_rows_is_DETECTED(tmp_path):
    p = tmp_path / "d.jsonl"
    for t in ("A", "B"):
        D.append_row(_row(target=t), p)
    lines = p.read_text().splitlines()
    p.write_text("\n".join(reversed(lines)) + "\n")
    with pytest.raises(D.AppendOnlyViolation, match="breaks the append-only chain"):
        D.verify_chain(p)


def test_chain_survives_an_honest_append_after_many_rows(tmp_path):
    """ANTI-VACUITY the other way: the guard must not fire on legitimate use, or it gets waived."""
    p = tmp_path / "d.jsonl"
    for i in range(25):
        D.append_row(_row(target=f"T{i}"), p)
    assert D.verify_chain(p) == 25
    D.append_row(_row(target="T25"), p)
    assert D.verify_chain(p) == 26


def test_torn_file_without_trailing_newline_refuses_append(tmp_path):
    p = tmp_path / "d.jsonl"
    p.write_text('{"partial": true')  # no newline: a half-written line
    with pytest.raises(D.AppendOnlyViolation, match="torn write"):
        D.append_row(_row(), p)


def test_load_rejects_a_hand_smuggled_token(tmp_path):
    """A hand edit must not be able to introduce a token the writer would have refused."""
    p = tmp_path / "d.jsonl"
    D.append_row(_row(), p)
    with p.open("a") as fh:
        fh.write(json.dumps({**_row(judgment="looks_fine_to_me"), "key": "x"}) + "\n")
    with pytest.raises(D.DispositionError, match=r"d\.jsonl:2"):
        D.load(p)
    assert len(D.load(p, strict=False)) == 2  # …but a forensic read still works


def test_load_of_absent_ledger_is_empty_not_an_error(tmp_path):
    assert D.load(tmp_path / "nope.jsonl") == []


def test_blank_lines_are_skipped(tmp_path):
    p = tmp_path / "d.jsonl"
    D.append_row(_row(), p)
    with p.open("a") as fh:
        fh.write("\n\n")
    assert len(D.load(p)) == 1


# ------------------------------------------------------- merge repair (the committed-ledger reality)


def _merge_interleave(a: Path, b: Path, out: Path):
    """Simulate `git merge` keeping both branches' hunks: two chains concatenated, order preserved."""
    out.write_text(a.read_text() + b.read_text())


def test_a_merged_ledger_is_broken_and_rechain_repairs_it(tmp_path):
    """The realistic failure: two reviewers append on two branches, git keeps both hunks.

    Both halves are honest rows. The CHAIN is what breaks, not the content — so the repair must be a
    re-chain, never a hand edit.
    """
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    D.append_row(_row(target="MINE1"), a)
    D.append_row(_row(target="MINE2"), a)
    D.append_row(_row(target="THEIRS1", rater="r2"), b)
    merged = tmp_path / "m.jsonl"
    _merge_interleave(a, b, merged)

    # ANTI-VACUITY: the merge really does break the chain, so the repair is doing something.
    with pytest.raises(D.AppendOnlyViolation, match="breaks the append-only chain"):
        D.verify_chain(merged)

    before = [json.loads(l) for l in merged.read_text().splitlines()]
    changed = D.rechain(merged, dry_run=False)
    assert changed == [3], "only the grafted row's prev was wrong"
    assert D.verify_chain(merged) == 3

    # The repair must not have touched a single judgment, key, rater or timestamp.
    after = [json.loads(l) for l in merged.read_text().splitlines()]
    for x, y in zip(before, after):
        assert {k: v for k, v in x.items() if k != "prev"} == {k: v for k, v in y.items() if k != "prev"}


def test_rechain_dry_run_does_not_write(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    D.append_row(_row(target="A"), a)
    D.append_row(_row(target="B", rater="r2"), b)
    merged = tmp_path / "m.jsonl"
    _merge_interleave(a, b, merged)
    original = merged.read_bytes()
    assert D.rechain(merged, dry_run=True) == [2]
    assert merged.read_bytes() == original, "a dry run must not write"


def test_rechain_is_a_noop_on_a_healthy_ledger(tmp_path):
    """ANTI-VACUITY the other way: it must not rewrite a ledger that was never broken."""
    p = tmp_path / "d.jsonl"
    for t in ("A", "B", "C"):
        D.append_row(_row(target=t), p)
    original = p.read_bytes()
    assert D.rechain(p, dry_run=False) == []
    assert p.read_bytes() == original


def test_rechain_REFUSES_to_launder_an_invalid_row(tmp_path):
    """The repair must not become a way to legitimize a smuggled token by re-chaining over it."""
    p = tmp_path / "d.jsonl"
    D.append_row(_row(), p)
    with p.open("a") as fh:
        fh.write(json.dumps({**_row(judgment="looks_fine_to_me"), "key": "x", "prev": "whatever"}) + "\n")
    with pytest.raises(D.DispositionError, match="refusing to re-chain an invalid ledger"):
        D.rechain(p, dry_run=False)


def test_rechain_REFUSES_a_content_rewrite_so_the_repair_is_not_an_ERASER(tmp_path):
    """The hole this closes: without a per-row content digest, `edit a judgment then --rechain --apply`
    would leave a ledger that verifies clean. The merge repair must fix ORDER only."""
    p = tmp_path / "d.jsonl"
    D.append_row(_row(target="A", judgment="wrong_verdict"), p)
    D.append_row(_row(target="B"), p)
    lines = p.read_text().splitlines()
    r0 = json.loads(lines[0])
    r0["judgment"] = "agree"
    lines[0] = json.dumps(r0, sort_keys=True, separators=(",", ":"))
    p.write_text("\n".join(lines) + "\n")

    with pytest.raises(D.DispositionError, match="not a way to relabel a filed judgment"):
        D.rechain(p, dry_run=False)
    # ANTI-VACUITY: refusal means refusal — the file is untouched and still fails verification.
    assert json.loads(p.read_text().splitlines()[0])["judgment"] == "agree"
    with pytest.raises(D.AppendOnlyViolation):
        D.verify_chain(p)


def test_content_sha_ignores_position_so_a_merge_does_not_trip_it(tmp_path):
    """ANTI-VACUITY: content binding must survive a legitimate re-chain, or every merge looks like fraud."""
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    D.append_row(_row(target="A"), a)
    D.append_row(_row(target="B", rater="r2"), b)
    merged = tmp_path / "m.jsonl"
    _merge_interleave(a, b, merged)
    assert D.rechain(merged, dry_run=False) == [2]
    assert D.verify_chain(merged) == 2, "an honest merge repair must produce a fully valid ledger"


def test_cli_verify_reports_and_fails_loudly(tmp_path, capsys):
    p = tmp_path / "d.jsonl"
    D.append_row(_row(target="A"), p)
    assert D.main(["--ledger", str(p), "--verify"]) == 0
    assert "chain OK" in capsys.readouterr().out
    lines = p.read_text().splitlines()
    r = json.loads(lines[0])
    r["prev"] = "tampered"
    p.write_text(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n")
    assert D.main(["--ledger", str(p), "--verify"]) == 2
    assert "CHAIN BROKEN" in capsys.readouterr().err


def test_cli_rechain_defaults_to_dry_run(tmp_path, capsys):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    D.append_row(_row(target="A"), a)
    D.append_row(_row(target="B", rater="r2"), b)
    merged = tmp_path / "m.jsonl"
    _merge_interleave(a, b, merged)
    original = merged.read_bytes()
    assert D.main(["--ledger", str(merged), "--rechain"]) == 0
    assert "would re-chain" in capsys.readouterr().out
    assert merged.read_bytes() == original
    assert D.main(["--ledger", str(merged), "--rechain", "--apply"]) == 0
    assert merged.read_bytes() != original


# ---------------------------------------------------- the git anchor (the only non-forgeable check)


def _git_ledger(tmp_path, rows_):
    """A real git repo with a COMMITTED ledger — the only way to test the external anchor honestly."""
    import subprocess

    repo = tmp_path / "repo"
    (repo / "eval").mkdir(parents=True)
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@example.com"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(cmd, cwd=repo, check=True, capture_output=True)
    p = repo / "eval" / "dispositions.jsonl"
    for r in rows_:
        D.append_row(r, p)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=repo, check=True, capture_output=True)
    return p


def _rewrite(p, rows_):
    p.write_text("\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rows_) + "\n")


def _read(p):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def test_git_anchor_CATCHES_a_TAIL_relabel_that_recomputes_its_own_digest(tmp_path):
    """The attack the in-file checks genuinely cannot see: relabel the LAST row, recompute its digest.

    `content_sha` is UNKEYED and stored in the same file as the data, so recomputing it is free. What
    limits the damage is that `prev` binds FORWARD — rewriting row i also invalidates row i+1's link,
    so an interior relabel does trip `verify_chain` (asserted below, so this test knows the difference).
    The tail row is the hole: nothing points at it, so its digest is the only thing binding it, and the
    editor owns that. The only check an editor cannot defeat lives outside the file — git has the bytes.

    SCOPE OF "only the tail is unbound": that is true of `verify_chain`, NOT of this module. `rechain`
    recomputes every link, so an attacker who runs the repair path first faces no forward binding at
    all — an interior relabel then survives the in-file layer too. What stops that is `rechain`'s own
    git anchor, pinned separately by `test_rechain_REFUSES_when_git_says_a_judgment_went_missing`.
    Weaken that anchor and this test plus `test_an_INTERIOR_relabel_is_caught_by_the_chain_alone` would
    both still pass while the tail-only hole quietly became a whole-file hole. Read the three together.
    (Found by 70, who reproduced the original interior-row bypass only because they ran
    `--rechain --apply` in between — the configuration difference that made us each right about a
    different thing.)
    """
    p = _git_ledger(tmp_path, [_row(target="A"), _row(target="B", judgment="wrong_verdict")])
    rows_ = _read(p)
    rows_[-1]["judgment"] = "agree"
    rows_[-1]["content_sha"] = D.content_sha(rows_[-1])  # the exported function — no secret to withhold
    _rewrite(p, rows_)

    # ANTI-VACUITY: prove the in-file checks really are defeated, so the git check is load-bearing.
    # `verify_chain` IS the whole in-file story — the per-row digest plus the `prev` links — and it
    # reports a clean two-row ledger over a relabelled judgment. (Not `rechain`: that also enforces the
    # git anchor, so calling it here would pass for the wrong reason, by tripping the very check under
    # test rather than by showing the in-file layer failing to trip.)
    assert D.verify_chain(p) == 2, "the in-file checks must be DEFEATED here, or the git check is decoration"
    with pytest.raises(D.ProvenanceGap, match="committed in git are GONE"):
        D.verify_provenance(p)


def test_an_INTERIOR_relabel_is_caught_by_the_chain_alone(tmp_path):
    """The bound on the hole above: `prev` binds forward, so only the tail is unbound in-file.

    Worth pinning separately, because it is the difference between "the in-file chain is theatre" and
    "the in-file chain covers all but the last row". If a future change makes `prev` point backward-only
    at a position rather than at a digest, this fails and the tail hole silently becomes a whole-file
    hole — with the git anchor as the only remaining check and no test saying so.
    """
    p = _git_ledger(tmp_path, [_row(target="A", judgment="wrong_verdict"), _row(target="B")])
    rows_ = _read(p)
    rows_[0]["judgment"] = "agree"
    rows_[0]["content_sha"] = D.content_sha(rows_[0])
    _rewrite(p, rows_)
    with pytest.raises(D.AppendOnlyViolation, match="breaks the append-only chain"):
        D.verify_chain(p)


def test_git_anchor_CATCHES_a_deletion(tmp_path):
    """Deletion is cheaper than an edit — nothing to recompute — and dropping `wrong_verdict` rows is
    the move that most flatters the framework. Multiset preservation catches it."""
    p = _git_ledger(tmp_path, [_row(target="A"), _row(target="B", judgment="wrong_verdict"), _row(target="C")])
    rows_ = _read(p)
    del rows_[1]
    _rewrite(p, rows_)
    with pytest.raises(D.ProvenanceGap, match="committed in git are GONE"):
        D.verify_provenance(p)


def test_rechain_REFUSES_when_git_says_a_judgment_went_missing(tmp_path):
    """The repair path must enforce the same anchor, or it becomes the laundering route.

    This is the load-bearing one of the three git tests, and it is easy to mistake for a duplicate of
    them. `rechain` recomputes EVERY `prev`, so it dissolves the forward binding that
    `test_an_INTERIOR_relabel_is_caught_by_the_chain_alone` relies on: without the anchor asserted here,
    an attacker relabels an interior row, runs the repair, and the ledger verifies clean end to end.
    That is precisely the bypass 70 demonstrated against the pre-anchor version. So the tail-only hole
    described in the sibling test is a property of `verify_chain`, not of the module, and THIS is the
    test that keeps it that way.
    """
    p = _git_ledger(tmp_path, [_row(target="A", judgment="wrong_verdict"), _row(target="B")])
    rows_ = _read(p)
    rows_[0]["judgment"] = "agree"
    rows_[0]["content_sha"] = D.content_sha(rows_[0])
    _rewrite(p, rows_)
    with pytest.raises(D.ProvenanceGap, match="does not relabel or drop them"):
        D.rechain(p, dry_run=False)


def test_git_anchor_PERMITS_an_honest_reorder_and_an_honest_append(tmp_path):
    """ANTI-VACUITY: a merge legitimately reorders and appends. If the anchor fired on that, it would
    be waived within a week — so the invariant is multiset-preservation, not prefix-equality."""
    p = _git_ledger(tmp_path, [_row(target="A"), _row(target="B")])
    rows_ = list(reversed(_read(p)))
    _rewrite(p, rows_)
    assert D.verify_provenance(p)["anchored"] is True  # reorder alone is fine
    assert D.rechain(p, dry_run=False), "the reorder still needs a prev repair"
    assert D.verify_chain(p) == 2
    D.append_row(_row(target="C"), p)
    assert D.verify_provenance(p)["anchored"] is True
    assert D.verify_chain(p) == 3


def test_unanchored_is_reported_not_silently_passed(tmp_path):
    """An uncommitted ledger cannot be anchored. That must READ as unverified, not as a pass."""
    p = tmp_path / "d.jsonl"
    D.append_row(_row(), p)
    prov = D.verify_provenance(p)
    assert prov["anchored"] is False
    assert "not committed" in prov["reason"]


def test_cli_verify_says_whether_it_is_anchored(tmp_path, capsys):
    p = tmp_path / "d.jsonl"
    D.append_row(_row(), p)
    assert D.main(["--ledger", str(p), "--verify"]) == 0
    assert "NOT git-anchored" in capsys.readouterr().out, "must not imply a guarantee it did not check"

    q = _git_ledger(tmp_path, [_row(target="A")])
    assert D.main(["--ledger", str(q), "--verify"]) == 0
    assert "git-anchored" in capsys.readouterr().out


def test_cli_verify_exits_nonzero_on_a_provenance_gap(tmp_path, capsys):
    """The gap must be reported EVEN WHEN the in-file chain is perfectly intact.

    Truncating the TAIL is the deletion the chain cannot see: every surviving row still points at its
    real predecessor, so `verify_chain` passes and returns first in `main`. Deleting an interior row
    instead would trip the chain check and this test would pass on the wrong guard's message.
    """
    p = _git_ledger(
        tmp_path,
        [_row(target="A"), _row(target="B"), _row(target="C", judgment="wrong_verdict")],
    )
    rows_ = _read(p)
    del rows_[-1]
    _rewrite(p, rows_)
    assert D.verify_chain(p) == 2, "the tail truncation must leave the in-file chain clean"
    assert D.main(["--ledger", str(p), "--verify"]) == 2
    assert "PROVENANCE GAP" in capsys.readouterr().err


def test_cli_rechain_REFUSES_instead_of_tracebacking_on_a_provenance_gap(tmp_path, capsys):
    """`ProvenanceGap` is a RuntimeError, so it does not fall under `except DispositionError`.

    Uncaught, the git refusal — the only check that stops the repair tool being used as an eraser —
    would print a traceback, which reads as a broken tool and invites someone to hand-edit `prev`
    instead: precisely the silent rewrite the chain exists to detect.
    """
    p = _git_ledger(tmp_path, [_row(target="A", judgment="wrong_verdict"), _row(target="B")])
    rows_ = _read(p)
    rows_[0]["judgment"] = "agree"
    rows_[0]["content_sha"] = D.content_sha(rows_[0])
    _rewrite(p, rows_)
    assert D.main(["--ledger", str(p), "--rechain", "--apply"]) == 2
    assert "REFUSED" in capsys.readouterr().err


# ------------------------------------------------------- concurrency: the guard must not self-inflict


def test_two_concurrent_appenders_both_land_and_the_chain_survives(tmp_path):
    """Without a lock, both writers read the same `prev`; the loser lands with a stale link and the CLI
    reports REFUSED for a row that IS on disk — so the reviewer re-files it and the ledger gains a
    duplicate on top of a broken chain. The detection would create the corruption it reports."""
    import concurrent.futures as cf

    p = tmp_path / "d.jsonl"
    D.append_row(_row(target="SEED"), p)
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda i: D.append_row(_row(target=f"T{i}"), p), range(24)))
    assert D.verify_chain(p) == 25, "every concurrent append must be chained, none lost or duplicated"
    assert len({r["target"] for r in D.load(p)}) == 25


# --------------------------------------------------------------------------- key + summary math


def test_fact_key_uses_the_legacy_pipe_convention(tmp_path):
    rec = D.validate_row(_row())
    assert rec["key"] == "tumor-selectivity|EPCAM|COADREAD|SEL|verdict"
    assert len(rec["key"].split("|")) == 5, "must stay joinable with loop_dispositions.yaml row keys"


def test_summary_reports_per_grain_and_never_pools(tmp_path):
    rows = [
        D.validate_row(_row(grain="verdict", judgment="agree", target="A")),
        D.validate_row(_row(grain="verdict", judgment="wrong_verdict", target="B")),
        D.validate_row(_row(grain="atom", judgment="artifact", target="C", axis="DEP")),
    ]
    s = D.summarize(rows)
    assert s["n"] == 3
    assert s["per_grain_filed_counts_all_selections"]["verdict"] == {"n": 2, "n_correct": 1}
    assert s["per_grain_filed_counts_all_selections"]["atom"] == {"n": 1, "n_correct": 0}
    assert "overall" not in s and "precision" not in s, "a pooled scalar over two questions is meaningless"


def test_the_word_agreement_appears_in_exactly_ONE_key_and_it_is_the_sampled_one():
    """A name outlives every caveat printed beside it.

    The earlier version emitted a pooled ratio under `per_grain_agreement`, so a 3-row defect hunt
    stated "the framework agrees 0.0% of the time" as the most authoritative-looking key in the JSON —
    the exact artefact this module's docstring says pooling would manufacture. Two keys of the same
    shape with different referents is its own bug class; the fix is to make the name carry the referent.
    """
    rows = [D.validate_row(_row(judgment="wrong_verdict", target="A"))]  # targeted by default
    s = D.summarize(rows)
    agreement_keys = [k for k in s if "agreement" in k and not k.startswith("intra_rater")]
    assert agreement_keys == ["per_grain_agreement_sampled"], agreement_keys
    # …and on an all-targeted ledger that one key is EMPTY rather than 0.0.
    assert s["per_grain_agreement_sampled"] == {}
    assert s["per_grain_filed_counts_all_selections"]["verdict"] == {"n": 1, "n_correct": 0}


def test_rechain_reports_every_line_whose_bytes_move(tmp_path):
    """A repair tool whose printed scope is narrower than its written scope invites a skimmed review."""
    p = tmp_path / "d.jsonl"
    D.append_row(_row(target="A"), p)
    D.append_row(_row(target="B"), p)
    # A hand-edited file with non-canonical spacing: re-serialization rewrites line 1 too, even though
    # only line 2's `prev` is wrong.
    rows_ = _read(p)
    rows_[1]["prev"] = "wrong"
    p.write_text("\n".join(json.dumps(r, sort_keys=True, indent=None, separators=(", ", ": ")) for r in rows_) + "\n")
    before = p.read_text().splitlines()
    changed = D.rechain(p, dry_run=False)
    after = p.read_text().splitlines()
    actual = [i for i, (b, a) in enumerate(zip(before, after), 1) if b != a]
    assert changed == actual, f"reported {changed} but bytes moved on {actual}"


def test_summary_can_actually_REPORT_an_unknown_token(tmp_path, capsys):
    """`unknown_judgment` was unreachable: --summary loaded strict, which raises before summarize runs.

    A field that looks like a detector and can never fire on the path anyone uses is the
    reassurance-without-protection shape this repo has shipped three times.
    """
    p = tmp_path / "d.jsonl"
    D.append_row(_row(), p)
    with p.open("a") as fh:
        fh.write(json.dumps({**_row(judgment="looks_fine_to_me"), "key": "k", "prev": "x"}) + "\n")
    assert D.main(["--ledger", str(p), "--summary"]) == 2, "a compromised ledger must exit nonzero"
    out = json.loads(capsys.readouterr().out)
    assert out["unknown_judgment"] == ["looks_fine_to_me"], "the field must be reachable, not decorative"
    assert out["chain"] != "ok"


def test_summary_of_a_clean_ledger_still_exits_zero(tmp_path, capsys):
    """ANTI-VACUITY for the above: the nonzero exit must be the detection, not --summary being broken."""
    p = tmp_path / "d.jsonl"
    D.append_row(_row(), p)
    assert D.main(["--ledger", str(p), "--summary"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["unknown_judgment"] == [] and out["chain"] == "ok"


def test_precedence_agreement_is_none_not_zero():
    """ANTI-VACUITY: 0.0 would read as `always wrong`; None reads as `not a correctness question`."""
    rows = [
        D.validate_row(
            _row(grain="precedence", judgment="a_beats_b", rule_id="a", loser_rule_id="b", selection="sampled")
        )
    ]
    s = D.summarize(rows)
    assert s["per_grain_agreement_sampled"]["precedence"]["agreement"] is None
    # …and the counts view must not quietly supply the 0 the rate refuses to: `n_correct` is 0 because
    # the grain has NO correct pole, so it is only ever read next to the None above.
    assert s["per_grain_filed_counts_all_selections"]["precedence"] == {"n": 1, "n_correct": 0}
    assert D.CORRECT_BY_GRAIN["precedence"] == ()


def test_intra_rater_agreement_counts_only_repeated_facts():
    same = dict(target="A", axis="SEL", skill="s", indication="I")
    rows = [
        D.validate_row(_row(rater="r1", judgment="agree", **same)),
        D.validate_row(_row(rater="r1", judgment="agree", is_replicate=True, **same)),
        D.validate_row(_row(rater="r1", judgment="agree", target="B", axis="SEL", skill="s", indication="I")),
    ]
    s = D.summarize(rows)
    assert s["n_repeated_facts"] == 1 and s["intra_rater_agreement"] == 1.0
    assert s["n_replicate_rows"] == 1

    # ANTI-VACUITY: a rater who contradicts themselves must drop the rate off 1.0.
    rows[1] = D.validate_row(_row(rater="r1", judgment="wrong_verdict", is_replicate=True, **same))
    assert D.summarize(rows)["intra_rater_agreement"] == 0.0


def test_intra_rater_is_none_when_nothing_was_rejudged():
    rows = [D.validate_row(_row(target="A")), D.validate_row(_row(target="B"))]
    assert D.summarize(rows)["intra_rater_agreement"] is None


def test_two_raters_on_one_fact_are_not_intra_rater():
    same = dict(target="A", axis="SEL", skill="s", indication="I")
    rows = [
        D.validate_row(_row(rater="r1", judgment="agree", **same)),
        D.validate_row(_row(rater="r2", judgment="wrong_verdict", **same)),
    ]
    assert D.summarize(rows)["n_repeated_facts"] == 0


# --------------------------------------------------------------------------- loop_health integration


def test_legacy_precision_is_unchanged_by_this_feature():
    """The shipped YAML must still read 32 rows / 29 sharp / 0.483. This feature adds, never moves."""
    disp = lh.load_dispositions(_EVAL / "loop_dispositions.yaml")
    assert len(disp) == 32
    m = lh.compute(disp)
    assert m["n_auto_demoted"] == 3
    assert m["n_sharp"] == 29
    assert m["precision_strict"] == 0.483
    assert m["unknown_disposition"] == []


def test_render_md_is_explicit_when_the_ledger_is_absent():
    md = lh.render_md(lh.compute({"a|T|I|X|calibration_gap": "fixed"}), {"present": False, "n": 0})
    assert "Not yet created" in md
    assert "precision_strict" in md  # the legacy section survives


def test_render_md_reports_the_ledger_without_pooling(tmp_path):
    p = tmp_path / "d.jsonl"
    D.append_row(_row(grain="verdict", judgment="agree", target="A"), p)
    D.append_row(_row(grain="atom", judgment="artifact", target="B", axis="DEP"), p)
    reviewer = lh.load_reviewer_ledger(p)
    md = lh.render_md(lh.compute({"a|T|I|X|calibration_gap": "fixed"}), reviewer)
    assert "Reviewer disposition ledger" in md
    assert "**rows:** 2" in md
    assert "precision_strict" in md  # legacy section intact and still separate
    assert reviewer["per_grain_filed_counts_all_selections"]["verdict"] == {"n": 1, "n_correct": 1}
    # The pooling guard, stated as a property of the OUTPUT rather than of one key: the word
    # "agreement" may appear in exactly one key, and that key is the sampled-only one.
    assert [k for k in reviewer if "agreement" in k and not k.startswith("intra_rater")] == [
        "per_grain_agreement_sampled"
    ]


def test_loop_health_ledger_absent_is_fail_soft(tmp_path):
    s = lh.load_reviewer_ledger(tmp_path / "absent.jsonl")
    assert s == {"present": False, "n": 0}


def test_loop_health_surfaces_a_malformed_ledger_rather_than_counting_it(tmp_path):
    """Fail-soft on ABSENCE, loud on MALFORMATION — the distinction the S3-skip trap gets wrong."""
    p = tmp_path / "d.jsonl"
    p.write_text(json.dumps({**_row(judgment="nope"), "key": "k"}) + "\n")
    with pytest.raises(D.DispositionError):
        lh.load_reviewer_ledger(p)


def test_main_appends_and_refuses(tmp_path):
    p = tmp_path / "d.jsonl"

    def _argv(judgment):
        return [
            "--ledger",
            str(p),
            "--grain",
            "verdict",
            "--judgment",
            judgment,
            "--skill",
            "s",
            "--target",
            "T",
            "--indication",
            "I",
            "--axis",
            "SEL",
        ]

    assert D.main(_argv("agree")) == 0
    assert len(D.load(p)) == 1
    assert D.main(_argv("banana")) == 2, "an illegal judgment must exit nonzero, not append"
    assert len(D.load(p)) == 1, "a refused row must leave the ledger byte-identical"
    # ANTI-VACUITY: the same call with a legal token DOES append, so the refusal above is the
    # vocabulary check firing and not the CLI being broken.
    assert D.main(_argv("wrong_verdict")) == 0
    assert len(D.load(p)) == 2


def test_summary_mode_runs_on_an_absent_ledger(tmp_path, capsys):
    assert D.main(["--ledger", str(tmp_path / "none.jsonl"), "--summary"]) == 0
    assert json.loads(capsys.readouterr().out)["n"] == 0


def test_resolve_run_context_is_failsoft_on_a_missing_dir(tmp_path):
    ctx = D.resolve_run_context(tmp_path / "no-such-run")
    assert list(ctx) == ["path"], "must return no invented metadata"


def test_resolve_run_context_reads_real_provenance(tmp_path):
    run = tmp_path / "EPCAM-COADREAD-2026-09-03"
    run.mkdir()
    (run / "provenance.yaml").write_text(
        "skill: tumor-selectivity\n"
        "skill_version: 1.17.0\n"
        "target: EPCAM\n"
        "indication: COADREAD\n"
        "governance:\n"
        "  skills_repo_sha: 541100f\n"
        "  data_mode: live\n"
        "  resolved_content_digest: 62e0b4632468fb57\n"
    )
    ctx = D.resolve_run_context(run)
    assert ctx["skill"] == "tumor-selectivity"
    assert ctx["skills_repo_sha"] == "541100f"
    assert ctx["resolved_content_digest"] == "62e0b4632468fb57"
    assert ctx["skill_version"] == "1.17.0"
