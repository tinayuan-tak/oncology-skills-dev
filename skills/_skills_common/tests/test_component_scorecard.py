"""Tests for the component-scorecard instrument (#1987, A0a).

The scorecard is itself an instrument, so it gets the fail-open discipline it exists to enforce:
NULL (unmeasured) must never promote to GREEN anywhere — rollup, render, or the committed baseline —
and NOT_BUILT must stay distinct from RED. The promotion rule is tested EXHAUSTIVELY over the whole
(built × criterion-status^4) space, not on sampled examples, so no unmeasured corner can slip
through unexercised.
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common import component_scorecard as cs

REPO_ROOT = Path(__file__).resolve().parents[3]


def _cell(built, statuses) -> cs.Cell:
    return cs.Cell(
        built=built,
        criteria={name: cs.Criterion(status=status) for name, status in zip(cs.CRITERIA, statuses)},
    )


# ---------------------------------------------------------------------------------------------
# Rollup — exhaustive over the full state space (3 built-states × 3^4 criterion combinations).
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("built", [True, False, None])
@pytest.mark.parametrize("statuses", list(itertools.product([cs.GREEN, cs.RED, cs.NULL], repeat=len(cs.CRITERIA))))
def test_rollup_exhaustive_null_never_promotes(built, statuses):
    """The single promotion rule, checked on EVERY reachable cell state.

    GREEN requires built=True AND all four criteria GREEN — a NULL anywhere (unmeasured) blocks
    GREEN; built=False is NOT_BUILT regardless of criteria; RED wins over NULL on a built cell.
    """
    rollup = cs.cell_rollup(_cell(built, statuses))
    assert rollup in cs.CELL_STATUSES
    if cs.NULL in statuses or built is not True:
        assert rollup != cs.GREEN, f"unmeasured/unbuilt state promoted to GREEN: built={built} statuses={statuses}"
    if built is False:
        assert rollup == cs.NOT_BUILT
        assert rollup != cs.RED, "NOT_BUILT (architecture gap) must stay distinct from RED (defect)"
    elif cs.RED in statuses:
        assert rollup == cs.RED
    elif built is True and all(s == cs.GREEN for s in statuses):
        assert rollup == cs.GREEN
    else:
        assert rollup == cs.NULL


def test_baseline_shard_is_all_null():
    shard = cs.baseline_shard("some-skill")
    cs.validate_shard_dict(shard.to_dict(), expected_skill="some-skill")
    assert set(shard.cells) == set(cs.LAYERS)
    for cell in shard.cells.values():
        assert cell.built is None
        assert cs.cell_rollup(cell) == cs.NULL
        assert all(cell.criteria[c].status == cs.NULL for c in cs.CRITERIA)


# ---------------------------------------------------------------------------------------------
# Schema validation — the committed JSON is the contract.
# ---------------------------------------------------------------------------------------------


def test_measured_criterion_requires_built_true():
    """A GREEN/RED reading on an unbuilt or un-inventoried layer is a fabricated measurement."""
    for built in (None, False):
        shard = cs.baseline_shard("s")
        shard.cells["L1"].built = built
        shard.cells["L1"].criteria["fail_open"] = cs.Criterion(status=cs.GREEN)
        with pytest.raises(cs.ScorecardValidationError, match="requires built=true"):
            cs.validate_shard_dict(shard.to_dict())


def test_not_built_is_a_cell_state_not_a_criterion_status():
    shard = cs.baseline_shard("s")
    data = shard.to_dict()
    data["cells"]["L1"]["criteria"]["accuracy"]["status"] = cs.NOT_BUILT
    with pytest.raises(cs.ScorecardValidationError, match="NOT_BUILT is a CELL-level state"):
        cs.validate_shard_dict(data)


def test_layers_are_a_closed_set_absence_is_explicit():
    """A missing layer key is invalid — 'the layer does not exist' is said with built=false."""
    data = cs.baseline_shard("s").to_dict()
    del data["cells"]["L4"]
    with pytest.raises(cs.ScorecardValidationError, match="exactly the layers"):
        cs.validate_shard_dict(data)
    data = cs.baseline_shard("s").to_dict()
    data["cells"]["L5"] = data["cells"]["L4"]
    with pytest.raises(cs.ScorecardValidationError, match="exactly the layers"):
        cs.validate_shard_dict(data)


def test_criteria_are_a_closed_set():
    data = cs.baseline_shard("s").to_dict()
    data["cells"]["L1"]["criteria"]["moves_a_verdict"] = {"status": cs.GREEN, "evidence": None}
    with pytest.raises(cs.ScorecardValidationError, match="exactly the keys"):
        cs.validate_shard_dict(data)


def test_unknown_status_and_wrong_schema_version_rejected():
    data = cs.baseline_shard("s").to_dict()
    data["cells"]["L1"]["criteria"]["accuracy"]["status"] = "green"  # case matters — closed vocab
    with pytest.raises(cs.ScorecardValidationError, match="not in"):
        cs.validate_shard_dict(data)
    data = cs.baseline_shard("s").to_dict()
    data["schema_version"] = 2
    with pytest.raises(cs.ScorecardValidationError, match="schema_version"):
        cs.validate_shard_dict(data)


def test_shard_filename_must_match_skill_field(tmp_path):
    """load_shards holds every file to 'one file per skill, named for it'."""
    path = tmp_path / "tumor-presence.json"
    data = cs.baseline_shard("tumor-selectivity").to_dict()
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    with pytest.raises(cs.ScorecardValidationError, match="named for"):
        cs.load_shards(tmp_path)


# ---------------------------------------------------------------------------------------------
# Sharded persistence — one file per skill; the adapter write surface touches nothing shared.
# ---------------------------------------------------------------------------------------------


def test_write_skill_shard_writes_exactly_one_file_per_skill(tmp_path):
    before = set(tmp_path.rglob("*"))
    cs.write_skill_shard(tmp_path, cs.baseline_shard("skill-a"))
    after = set(tmp_path.rglob("*"))
    assert after - before == {tmp_path / "skill-a.json"}, "adapter write surface must touch exactly its own shard"
    cs.write_skill_shard(tmp_path, cs.baseline_shard("skill-b"))
    assert (tmp_path / "skill-a.json").exists() and (tmp_path / "skill-b.json").exists()
    assert not (tmp_path / cs.RENDER_FILENAME).exists(), "adapters never write the shared render"
    shards = cs.load_shards(tmp_path)
    assert sorted(shards) == ["skill-a", "skill-b"]


def test_write_skill_shard_refuses_an_invalid_record(tmp_path):
    shard = cs.baseline_shard("skill-a")
    shard.cells["L1"].criteria["accuracy"] = cs.Criterion(status=cs.GREEN)  # measured but built=None
    with pytest.raises(cs.ScorecardValidationError):
        cs.write_skill_shard(tmp_path, shard)
    assert not (tmp_path / "skill-a.json").exists(), "an invalid shard must not be persisted"


# ---------------------------------------------------------------------------------------------
# Render + regenerate — deterministic, and NULL never rendered GREEN.
# ---------------------------------------------------------------------------------------------


def _fake_repo(tmp_path: Path, skills: list[str]) -> Path:
    repo = tmp_path / "repo"
    for skill in skills:
        (repo / "skills" / skill).mkdir(parents=True)
        (repo / "skills" / skill / cs.SKILL_MARKER).write_text(f"# {skill}\n")
    return repo


def test_regenerate_is_deterministic_and_check_clean(tmp_path):
    repo = _fake_repo(tmp_path, ["b-skill", "a-skill"])
    assert cs.regenerate(repo, init_missing=True) == []
    render = repo / cs.SCORECARD_DIRNAME / cs.RENDER_FILENAME
    first = render.read_text()
    shard_bytes = {p.name: p.read_text() for p in (repo / cs.SCORECARD_DIRNAME).glob("*.json")}
    assert sorted(shard_bytes) == ["a-skill.json", "b-skill.json"]
    # Second regenerate (init_missing again) must be byte-identical everywhere: same shards, same render.
    assert cs.regenerate(repo, init_missing=True) == []
    assert render.read_text() == first
    assert {p.name: p.read_text() for p in (repo / cs.SCORECARD_DIRNAME).glob("*.json")} == shard_bytes
    assert cs.regenerate(repo, check=True) == []


def test_check_reports_missing_shard_and_stale_render(tmp_path):
    repo = _fake_repo(tmp_path, ["a-skill", "b-skill"])
    assert cs.regenerate(repo, init_missing=True) == []
    # A new roster skill without a shard = unmeasured coverage — must be a reported problem, not silence.
    (repo / "skills" / "c-skill").mkdir()
    (repo / "skills" / "c-skill" / cs.SKILL_MARKER).write_text("# c\n")
    problems = cs.regenerate(repo, check=True)
    assert any("no shard" in p and "c-skill" in p for p in problems)
    # A shard edit without re-rendering = stale committed render — must be a reported problem.
    cs.regenerate(repo, init_missing=True)
    shard = cs.load_shards(repo / cs.SCORECARD_DIRNAME)["a-skill"]
    shard.cells["L1"].built = False
    cs.write_skill_shard(repo / cs.SCORECARD_DIRNAME, shard)
    problems = cs.regenerate(repo, check=True)
    assert any("stale" in p for p in problems)
    # check mode must not have repaired anything.
    assert any("stale" in p for p in cs.regenerate(repo, check=True))


def test_render_never_shows_green_for_unmeasured_or_partial_cells():
    shard = cs.baseline_shard("x-skill")
    shard.cells["L1"].built = True
    shard.cells["L1"].criteria["accuracy"] = cs.Criterion(status=cs.GREEN)  # 1 GREEN + 3 NULL
    shard.cells["L2a"].built = False  # NOT_BUILT
    rendered = cs.render_markdown({"x-skill": shard})
    row = next(line for line in rendered.splitlines() if line.startswith("| x-skill"))
    cells = [c.strip() for c in row.strip("|").split("|")][1:]
    assert cells[0].startswith(cs.NULL), "a partially-measured cell must render NULL, never GREEN"
    assert "a:G" in cells[0], "the one measured criterion must still be visible"
    assert cells[1] == cs.NOT_BUILT
    assert not any(c.startswith(cs.GREEN) for c in cells)
    assert "- GREEN: 0" in rendered


def test_render_distinguishes_red_from_not_built():
    shard = cs.baseline_shard("x-skill")
    shard.cells["L1"].built = True
    shard.cells["L1"].criteria["fail_open"] = cs.Criterion(status=cs.RED, evidence={"probe": "absence"})
    shard.cells["L2a"].built = False
    rendered = cs.render_markdown({"x-skill": shard})
    assert "- RED: 1" in rendered
    assert "- NOT_BUILT: 1" in rendered
    row = next(line for line in rendered.splitlines() if line.startswith("| x-skill"))
    cells = [c.strip() for c in row.strip("|").split("|")][1:]
    assert cells[0].startswith(cs.RED) and cells[1] == cs.NOT_BUILT


def test_fully_green_cell_renders_green():
    """The positive direction — so the promotion guard is proven able to pass, not vacuously strict."""
    shard = cs.baseline_shard("x-skill")
    shard.cells["L1"].built = True
    for name in cs.CRITERIA:
        shard.cells["L1"].criteria[name] = cs.Criterion(status=cs.GREEN, evidence={"see": "test"})
    rendered = cs.render_markdown({"x-skill": shard})
    row = next(line for line in rendered.splitlines() if line.startswith("| x-skill"))
    cells = [c.strip() for c in row.strip("|").split("|")][1:]
    assert cells[0].startswith(cs.GREEN)
    assert "- GREEN: 1" in rendered


# ---------------------------------------------------------------------------------------------
# The COMMITTED baseline — validated in-repo, exactly as CI will hold every future adapter write.
# ---------------------------------------------------------------------------------------------


def test_committed_scorecard_covers_roster_and_render_is_current():
    """The committed scorecard must be regenerable byte-identically: every roster skill has a valid
    shard, no orphan shards, and SCORECARD.md matches a fresh render. Fails with the exact repair
    command (scripts/regenerate_scorecard.py [--init-missing]) in the problem text."""
    problems = cs.regenerate(REPO_ROOT, check=True)
    assert problems == [], "committed scorecard drifted:\n" + "\n".join(problems)


def test_committed_baseline_has_no_green_without_full_measurement():
    """Instrument-level fail-open guard on the PERSISTED bytes, not just the code path: no committed
    cell may claim GREEN unless built and all four criteria are GREEN (validator + rollup agree)."""
    shards = cs.load_shards(REPO_ROOT / cs.SCORECARD_DIRNAME)
    assert shards, "committed scorecard is empty"
    assert sorted(shards) == cs.discover_skills(REPO_ROOT / "skills")
    for skill, shard in shards.items():
        for layer, cell in shard.cells.items():
            if cs.cell_rollup(cell) == cs.GREEN:
                assert cell.built is True and all(cell.criteria[c].status == cs.GREEN for c in cs.CRITERIA), (
                    f"{skill}/{layer}: GREEN without full measurement"
                )
