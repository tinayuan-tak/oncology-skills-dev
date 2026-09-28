"""Component scorecard — cell-record schema, sharded persistence, deterministic aggregation (#1987, A0a).

The recompute-able instrument for the component-iterator walk (epic #1985, plan
``~/.claude/plans/modular-swinging-dahl.md``). Every component cell ``(skill × layer)`` carries FOUR
independent per-criterion statuses — never a single all-or-nothing bit, and never "does it move a
verdict" (that criterion is deprecated and deliberately absent):

    (a) accuracy           — emitted numbers reconcile against an independent re-derivation from raw
                             substrate;
    (b) utilization        — every emitted field is consumed or explicitly dispositioned;
    (c) fail_open          — absent/unreachable inputs degrade CONSERVATIVELY (no reassuring output on
                             unmeasured data);
    (d) panel_consistency  — holds across the whole target panel, not one flagship (no overfit).

Each criterion is independently ``GREEN | RED | NULL``. ``NULL`` means NOT YET MEASURED — it is the
honest baseline state, and the instrument itself is fail-open-closed: **a NULL can never render or
roll up as GREEN**. A cell additionally distinguishes ``built``:

    built=False  →  cell rolls up NOT_BUILT — the layer does not exist for this skill. That is an
                    architecture gap, NOT a defect: distinct from RED by construction, and such a cell
                    may not carry any measured (non-NULL) criterion.
    built=None   →  not yet inventoried; rolls up NULL.
    built=True   →  rolls up from the criteria: any RED → RED; all four GREEN → GREEN;
                    otherwise (some criterion unmeasured) → NULL.

PERSISTENCE IS SHARDED — this is what makes the adapter wave parallel-safe by construction. Each
skill's adapter writes EXACTLY ONE file, ``scorecard/<skill>.json``, via :func:`write_skill_shard`.
No adapter ever writes a shared file. The only shared artifact, ``scorecard/SCORECARD.md``, is an
AGGREGATE rendered at read time by the single regenerate entrypoint
(``scripts/regenerate_scorecard.py``) — a pure, deterministic function of the shard contents (no
timestamps, sorted keys, stable ordering), so regeneration from unchanged shards is byte-identical
and a stale committed render is machine-detectable (``--check``).

ADAPTER INTERFACE (normative example = the tumor-presence exemplar, A0c #1988):

    from _skills_common import component_scorecard as cs

    shard = cs.baseline_shard("tumor-presence")            # all layers: built=None, criteria NULL
    cell = shard.cells["L1"]
    cell.built = True
    cell.criteria["utilization"] = cs.Criterion(status=cs.RED, evidence={...})   # evidence: free-form
    cs.write_skill_shard(scorecard_dir, shard)             # writes ONLY scorecard/tumor-presence.json

Adapters MUST NOT write ``SCORECARD.md`` (run the regenerate entrypoint instead) and MUST NOT touch a
sibling skill's shard. The skill roster is discovered from the tree (``skills/<skill>/SKILL.md`` is
the marker), so a newly added skill fails the coverage check until a baseline shard exists —
unmeasured coverage is surfaced, never silently absent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1

# Layers, in walk (dependency) order. The cell grain is the layer, per the issue; finer sub-layer
# evidence (L3d vs L3f, per-target panel rows, probe transcripts) belongs in a criterion's `evidence`.
LAYERS: tuple[str, ...] = ("L1", "L2a", "L2b", "L3", "L4")

# The four criteria, in (a)..(d) order. Closed set — in particular, "moves a verdict" is NOT a
# criterion and must never become one (governing directive, plan `modular-swinging-dahl.md`).
CRITERIA: tuple[str, ...] = ("accuracy", "utilization", "fail_open", "panel_consistency")

# Per-criterion statuses.
GREEN = "GREEN"
RED = "RED"
NULL = "NULL"  # not yet measured — must never promote to GREEN anywhere downstream
CRITERION_STATUSES: frozenset[str] = frozenset({GREEN, RED, NULL})

# Cell-level rollup vocabulary = the three above plus NOT_BUILT (architecture gap, distinct from RED).
NOT_BUILT = "NOT_BUILT"
CELL_STATUSES: frozenset[str] = frozenset({GREEN, RED, NULL, NOT_BUILT})

SCORECARD_DIRNAME = "scorecard"
RENDER_FILENAME = "SCORECARD.md"
SKILL_MARKER = "SKILL.md"


class ScorecardValidationError(ValueError):
    """A shard (or in-memory record) violates the cell-record schema."""


@dataclass
class Criterion:
    """One criterion's status for one cell, plus its acceptance evidence.

    ``evidence`` is a free-form JSON-serialisable dict owned by the adapter (probe transcripts,
    reconciliation tables, per-target panel rows, pointers to test names). It must justify the
    status; the schema does not interpret it. ``None`` is the baseline (nothing measured yet).
    """

    status: str = NULL
    evidence: dict | None = None

    def to_dict(self) -> dict:
        return {"status": self.status, "evidence": self.evidence}


@dataclass
class Cell:
    """One ``(skill × layer)`` component cell."""

    built: bool | None = None
    criteria: dict[str, Criterion] = field(default_factory=lambda: {c: Criterion() for c in CRITERIA})
    notes: str | None = None

    def to_dict(self) -> dict:
        return {
            "built": self.built,
            "criteria": {name: crit.to_dict() for name, crit in self.criteria.items()},
            "notes": self.notes,
        }


@dataclass
class SkillShard:
    """All layer cells for one skill — the unit of persistence (one file, one writer)."""

    skill: str
    cells: dict[str, Cell]
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "skill": self.skill,
            "cells": {layer: cell.to_dict() for layer, cell in self.cells.items()},
        }


def baseline_shard(skill: str) -> SkillShard:
    """The empty-but-valid baseline for one skill: every layer built=None, every criterion NULL."""
    return SkillShard(skill=skill, cells={layer: Cell() for layer in LAYERS})


# ---------------------------------------------------------------------------------------------
# Validation — the committed JSON is the contract; validate at the dict level so a hand-edited or
# adapter-written shard is held to the same rules as one built through the dataclasses.
# ---------------------------------------------------------------------------------------------


def _validate_cell_dict(skill: str, layer: str, cell: dict) -> None:
    where = f"shard '{skill}', layer '{layer}'"
    if not isinstance(cell, dict):
        raise ScorecardValidationError(f"{where}: cell must be an object, got {type(cell).__name__}")
    extra = set(cell) - {"built", "criteria", "notes"}
    if extra:
        raise ScorecardValidationError(f"{where}: unknown cell keys {sorted(extra)}")
    built = cell.get("built")
    if built not in (True, False, None):
        raise ScorecardValidationError(f"{where}: 'built' must be true/false/null, got {built!r}")
    criteria = cell.get("criteria")
    if not isinstance(criteria, dict) or set(criteria) != set(CRITERIA):
        got = sorted(criteria) if isinstance(criteria, dict) else criteria
        raise ScorecardValidationError(f"{where}: 'criteria' must have exactly the keys {list(CRITERIA)}, got {got}")
    notes = cell.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise ScorecardValidationError(f"{where}: 'notes' must be a string or null")
    for name in CRITERIA:
        crit = criteria[name]
        cwhere = f"{where}, criterion '{name}'"
        if not isinstance(crit, dict) or set(crit) - {"status", "evidence"}:
            raise ScorecardValidationError(f"{cwhere}: must be an object with keys 'status'/'evidence'")
        status = crit.get("status")
        if status not in CRITERION_STATUSES:
            raise ScorecardValidationError(
                f"{cwhere}: status {status!r} not in {sorted(CRITERION_STATUSES)} "
                f"(NOT_BUILT is a CELL-level state — set built=false, not a criterion status)"
            )
        evidence = crit.get("evidence")
        if evidence is not None and not isinstance(evidence, dict):
            raise ScorecardValidationError(f"{cwhere}: 'evidence' must be an object or null")
        # A criterion may only be MEASURED (GREEN/RED) on a cell known to be built. built=False
        # (architecture gap) and built=None (not yet inventoried) both mean "there is nothing this
        # measurement could have run against" — a measured status there is a fabricated reading.
        if status != NULL and built is not True:
            raise ScorecardValidationError(
                f"{cwhere}: status {status} requires built=true (built={json.dumps(built)}); "
                f"an unbuilt or un-inventoried layer cannot carry a measured criterion"
            )


def validate_shard_dict(data: dict, expected_skill: str | None = None) -> None:
    """Validate one shard dict against the schema; raise :class:`ScorecardValidationError`."""
    if not isinstance(data, dict):
        raise ScorecardValidationError(f"shard must be an object, got {type(data).__name__}")
    extra = set(data) - {"schema_version", "skill", "cells"}
    if extra:
        raise ScorecardValidationError(f"unknown top-level keys {sorted(extra)}")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ScorecardValidationError(f"schema_version must be {SCHEMA_VERSION}, got {data.get('schema_version')!r}")
    skill = data.get("skill")
    if not isinstance(skill, str) or not skill:
        raise ScorecardValidationError("'skill' must be a non-empty string")
    if expected_skill is not None and skill != expected_skill:
        raise ScorecardValidationError(
            f"shard 'skill' field is {skill!r} but the file is named for {expected_skill!r} "
            f"(one file per skill; adapters never write another skill's shard)"
        )
    cells = data.get("cells")
    if not isinstance(cells, dict) or set(cells) != set(LAYERS):
        got = sorted(cells) if isinstance(cells, dict) else cells
        raise ScorecardValidationError(
            f"shard '{skill}': 'cells' must have exactly the layers {list(LAYERS)}, got {got} "
            f"(a layer that does not exist is expressed as built=false, never by omission)"
        )
    for layer in LAYERS:
        _validate_cell_dict(skill, layer, cells[layer])


def shard_from_dict(data: dict, expected_skill: str | None = None) -> SkillShard:
    """Parse + validate a shard dict into dataclasses."""
    validate_shard_dict(data, expected_skill=expected_skill)
    cells: dict[str, Cell] = {}
    for layer in LAYERS:
        raw = data["cells"][layer]
        cells[layer] = Cell(
            built=raw.get("built"),
            criteria={
                name: Criterion(status=raw["criteria"][name]["status"], evidence=raw["criteria"][name].get("evidence"))
                for name in CRITERIA
            },
            notes=raw.get("notes"),
        )
    return SkillShard(skill=data["skill"], cells=cells)


# ---------------------------------------------------------------------------------------------
# Rollup — the ONLY place a cell-level status is computed. NULL never promotes.
# ---------------------------------------------------------------------------------------------


def cell_rollup(cell: Cell) -> str:
    """Roll one cell's built-state + four criterion statuses into a single cell status.

    Fail-open-closed by construction: GREEN requires built=True AND all four criteria GREEN — any
    NULL (unmeasured) blocks GREEN; it never counts toward it.
    """
    if cell.built is False:
        return NOT_BUILT
    statuses = [cell.criteria[name].status for name in CRITERIA]
    if RED in statuses:
        return RED
    if cell.built is True and all(s == GREEN for s in statuses):
        return GREEN
    return NULL


# ---------------------------------------------------------------------------------------------
# Sharded persistence — one file per skill; adapters call write_skill_shard and NOTHING else.
# ---------------------------------------------------------------------------------------------


def shard_path(scorecard_dir: Path, skill: str) -> Path:
    return Path(scorecard_dir) / f"{skill}.json"


def write_skill_shard(scorecard_dir: Path, shard: SkillShard) -> Path:
    """Write ONE skill's shard to ``scorecard/<skill>.json`` (validated, sorted keys, deterministic).

    This is the entire adapter write surface: it touches exactly one file, derived from
    ``shard.skill``, so concurrent adapters for different skills cannot contend by construction.
    """
    data = shard.to_dict()
    validate_shard_dict(data, expected_skill=shard.skill)
    path = shard_path(scorecard_dir, shard.skill)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return path


def load_shards(scorecard_dir: Path) -> dict[str, SkillShard]:
    """Read-time aggregation: load + validate every ``*.json`` shard, keyed by skill, sorted."""
    scorecard_dir = Path(scorecard_dir)
    shards: dict[str, SkillShard] = {}
    for path in sorted(scorecard_dir.glob("*.json")):
        data = json.loads(path.read_text())
        shards[path.stem] = shard_from_dict(data, expected_skill=path.stem)
    return shards


def discover_skills(skills_root: Path | None = None) -> list[str]:
    """The skill roster: every ``skills/<skill>/`` carrying a ``SKILL.md`` marker, sorted."""
    root = Path(skills_root) if skills_root is not None else Path(__file__).resolve().parents[1]
    return sorted(p.parent.name for p in root.glob(f"*/{SKILL_MARKER}"))


def roster_drift(shards: dict[str, SkillShard], roster: list[str]) -> tuple[list[str], list[str]]:
    """``(missing, extra)`` — roster skills with no shard, and shards for no roster skill."""
    have, want = set(shards), set(roster)
    return sorted(want - have), sorted(have - want)


# ---------------------------------------------------------------------------------------------
# Deterministic render — a pure function of the shard contents. No timestamps, stable ordering.
# ---------------------------------------------------------------------------------------------

_CRITERION_ABBREV = {"accuracy": "a", "utilization": "u", "fail_open": "f", "panel_consistency": "p"}
_STATUS_ABBREV = {GREEN: "G", RED: "R", NULL: "-"}


def _cell_display(cell: Cell) -> str:
    rollup = cell_rollup(cell)
    if rollup == GREEN:
        # Belt-and-braces instrument guard: rendering GREEN re-checks the promotion condition, so a
        # future rollup regression cannot slip an unmeasured cell into the committed render as GREEN.
        assert cell.built is True and all(cell.criteria[c].status == GREEN for c in CRITERIA), (
            "cell_rollup returned GREEN for a cell that is not fully measured GREEN — NULL must never render as GREEN"
        )
    if rollup in (NOT_BUILT, NULL) and all(cell.criteria[c].status == NULL for c in CRITERIA):
        return rollup
    detail = " ".join(f"{_CRITERION_ABBREV[c]}:{_STATUS_ABBREV[cell.criteria[c].status]}" for c in CRITERIA)
    return f"{rollup} ({detail})"


def render_markdown(shards: dict[str, SkillShard]) -> str:
    """Render the aggregate scorecard as markdown — deterministic (byte-stable for equal shards)."""
    lines = [
        "# Component scorecard",
        "",
        "GENERATED — do not edit. Source of truth = the per-skill shards in `scorecard/<skill>.json`;",
        "regenerate with `pixi run python scripts/regenerate_scorecard.py` (verify with `--check`).",
        "",
        "Cell = (skill × layer). Per-criterion statuses: (a) accuracy vs re-derivation ·",
        "(b) utilization/disposition · (c) fail-open · (d) panel-consistency — each GREEN/RED/NULL.",
        "NULL = not yet measured and NEVER counts as GREEN. NOT_BUILT = the layer does not exist for",
        "this skill (architecture gap, not a defect — distinct from RED). A cell is GREEN only when",
        "built and all four criteria are GREEN. Cells are never scored by verdict movement.",
        "",
        "| skill | " + " | ".join(LAYERS) + " |",
        "|---| " + " | ".join("---" for _ in LAYERS) + " |",
    ]
    counts = dict.fromkeys((GREEN, RED, NULL, NOT_BUILT), 0)
    for skill in sorted(shards):
        shard = shards[skill]
        row = [skill]
        for layer in LAYERS:
            cell = shard.cells[layer]
            counts[cell_rollup(cell)] += 1
            row.append(_cell_display(cell))
        lines.append("| " + " | ".join(row) + " |")
    total = sum(counts.values())
    lines += [
        "",
        "## Summary",
        "",
        f"- cells: {total} ({len(shards)} skills × {len(LAYERS)} layers)",
    ]
    lines += [f"- {status}: {counts[status]}" for status in (GREEN, RED, NULL, NOT_BUILT)]
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# Regenerate — the single entrypoint's engine (CLI wrapper: scripts/regenerate_scorecard.py).
# ---------------------------------------------------------------------------------------------


def regenerate(repo_root: Path, init_missing: bool = False, check: bool = False) -> list[str]:
    """Aggregate the shards and (re)write ``scorecard/SCORECARD.md``; return a list of problems.

    - ``init_missing=True``: first write a baseline (all-NULL) shard for every roster skill that has
      none. Never overwrites an existing shard.
    - ``check=True``: write NOTHING; report drift instead (missing/extra shards, stale render).
    - Roster drift is always a reported problem — a skill without a shard is unmeasured coverage and
      must be visible, not silently absent from the aggregate.
    """
    repo_root = Path(repo_root)
    scorecard_dir = repo_root / SCORECARD_DIRNAME
    skills_root = repo_root / "skills"
    roster = discover_skills(skills_root)
    problems: list[str] = []

    if init_missing and not check:
        existing = {p.stem for p in scorecard_dir.glob("*.json")} if scorecard_dir.is_dir() else set()
        for skill in roster:
            if skill not in existing:
                write_skill_shard(scorecard_dir, baseline_shard(skill))

    shards = load_shards(scorecard_dir) if scorecard_dir.is_dir() else {}
    missing, extra = roster_drift(shards, roster)
    if missing:
        problems.append(f"roster skills with no shard (run with --init-missing to create baselines): {missing}")
    if extra:
        problems.append(f"shards for skills not in the roster (retired skill? remove or re-roster): {extra}")

    rendered = render_markdown(shards)
    render_path = scorecard_dir / RENDER_FILENAME
    if check:
        committed = render_path.read_text() if render_path.exists() else None
        if committed != rendered:
            problems.append(f"{RENDER_FILENAME} is stale — regenerate with scripts/regenerate_scorecard.py")
    else:
        scorecard_dir.mkdir(parents=True, exist_ok=True)
        render_path.write_text(rendered)
    return problems
