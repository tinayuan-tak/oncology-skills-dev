"""The TRUTH HALF of the `claim_axis` registry (structure arc #2210 Wave-0d; epic #1507).

`contracts/validators/validate_claim_axis.py` checks that `contracts/vocabularies/claim_axis.enum.yaml`
is internally coherent and pinned to the property catalog. Nothing in contracts/ can check the one thing
that actually matters — whether the registry AGREES with the code — because the dependency direction is
skills/ -> contracts/ and never the reverse. That is this module. It re-derives every axis from the
skills' own `HeadlineSpec` declarations and reconciles the two in BOTH directions.

Why both directions. A registry that declares an axis no skill has is fiction; a skill axis the registry
does not know about is a FALSE ABSENCE — the file would report a complete fleet roster while silently
having stopped covering one. Neither is catchable from one side, so the comparison is set EQUALITY over
`(skill, axis_key)` pairs, and the label / `critical` / gate / display-order comparisons are equality
too.

DISCOVERY IS FAIL-LOUD, NOT BEST-EFFORT. `_discover()` walks `skills/*/scripts/run.py` for
`HeadlineSpec(` — never a hard-coded skill list, which silently stops covering a new skill the day one
lands. A file that names `HeadlineSpec(` in a shape it cannot read raises `UnreadableHeadlineSpec`; it
does not return a partial roster. A guard whose population can silently become empty is worse than no
guard, and the cardinality floors below are the second line of that defence.

WHY THE PAIR AND NOT THE TOKEN. `DEP` is *genetic dependency* in functional-requirement and
*alteration-conferred dependency* in genomic-alteration-profile — one token, two properties. Everything
here keys on `(skill, axis_key)`. This is the same result Wave-0b measured one level down, where
`single_source_only` is emitted by 5 concordance families and means a different comparison in each.

DISCIPLINE. Verdict-INERT and byte-stable: this module only READS declarations and mints nothing, and
asserts nothing about any verdict in either direction (SK#2091). Every floor names its subject INSIDE the
assert with a `len()` call, because `skills/tests/test_discovery_guards_carry_floors.py` reads floors
statically and a floor bound to a local first is invisible to it (and to the next refactor). A missing or
empty registry RAISES at import rather than degrading to an empty population.

NO `sys.path` INSERT AND NO REPO IMPORT AT ALL (#2144). Its siblings in this directory each open with two
`sys.path.insert` calls, and they have to: `skills/_skills_common/pytest.ini` makes THIS directory the
rootdir, so pytest's confcutdir never reaches `skills/conftest.py` and `_skills_common` is not importable
here. This module needs neither, because it is an AST reader by construction — `CLAIM_INFORMS` is read
out of `presence_claims.py`'s syntax tree exactly as the `HeadlineSpec`s are. That also keeps it clear of
the live `methods` -> `onc_methods` package rename (#2237), which it has no reason to touch.
"""

from __future__ import annotations

import ast
import pathlib
import shutil

import pytest
import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_SKILLS_ROOT = _REPO_ROOT / "skills"
_ENUM_PATH = _REPO_ROOT / "contracts" / "vocabularies" / "claim_axis.enum.yaml"
_CATALOG_DIR = _REPO_ROOT / "contracts" / "vocabularies" / "property_catalog"

# The floors. Deliberate module-level constants so the static floor-reader can follow them back to the
# assert that uses them, and deliberately BELOW the measured population (15 / 61) so additive growth
# never reds — the equality clauses are what catch drift; these only catch a glob matching nothing.
MIN_SKILLS = 15
MIN_AXES = 50


class UnreadableHeadlineSpec(RuntimeError):
    """A `run.py` names `HeadlineSpec(` in a shape this module cannot read.

    Raised rather than skipped on purpose. Returning a partial roster would make every equality clause
    below compare against a population that silently lost a member, and the registry would read as
    complete. The 0b coverage module's `UnreadableEmission` is the same decision for the same reason.
    """


def _load_registry() -> dict:
    """Fail-loud load. An unreadable or empty registry RAISES: every assertion below is relative to this
    document, so an empty one would make the whole module vacuously green — the exact failure the
    governance is meant to prevent."""
    if not _ENUM_PATH.is_file():
        raise RuntimeError(f"governed registry missing at {_ENUM_PATH} — this suite cannot run without it")
    doc = yaml.safe_load(_ENUM_PATH.read_text()) or {}
    if not isinstance(doc, dict) or not doc.get("axes") or not doc.get("skills"):
        raise RuntimeError(f"{_ENUM_PATH} has no axes/skills — refusing to examine an empty population")
    return doc


def _discover(skills_root: pathlib.Path) -> dict:
    """{(skill, axis_key): {label, critical, gate, position}} re-derived from the skills' ASTs.

    Discovery is by GLOB over `skills/*/scripts/run.py`, never a hard-coded roster. `position` records the
    index within the skill's `axis_keys`, because display order is part of what the registry declares and
    a set comparison would lose it.
    """
    out: dict = {}
    for path in sorted(skills_root.glob("*/scripts/run.py")):
        source = path.read_text()
        if "HeadlineSpec(" not in source:
            continue
        skill = path.parent.parent.name
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:  # pragma: no cover - a syntax error reds the whole suite anyway
            raise UnreadableHeadlineSpec(f"{path}: could not be parsed ({exc})") from exc
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "HeadlineSpec"
        ]
        if not calls:
            raise UnreadableHeadlineSpec(
                f"{path}: the source names `HeadlineSpec(` but no HeadlineSpec CALL is reachable by AST "
                f"walk — the declaration has moved to a shape this discovery cannot read, and a partial "
                f"roster would read as a complete one"
            )
        if len(calls) > 1:
            raise UnreadableHeadlineSpec(
                f"{path}: {len(calls)} HeadlineSpec calls. The registry keys on (skill, axis_key), so a "
                f"skill declaring two specs needs a deliberate decision about which axes are the skill's "
                f"— not a silent first-wins"
            )
        node = calls[0]
        kw: dict = {}
        for k in node.keywords:
            if k.arg not in ("gate", "axis_keys", "axis_labels", "critical_axes"):
                continue
            try:
                kw[k.arg] = ast.literal_eval(k.value)
            except ValueError as exc:
                raise UnreadableHeadlineSpec(
                    f"{path}: `{k.arg}` is not a literal this module can read ({exc}). It must stay a "
                    f"literal or the registry cannot be pinned to it"
                ) from exc
        for required in ("gate", "axis_keys", "axis_labels"):
            if required not in kw:
                raise UnreadableHeadlineSpec(f"{path}: HeadlineSpec declares no literal `{required}`")
        keys = list(kw["axis_keys"])
        # `critical_axes` DEFAULTS TO axis_keys in HeadlineSpec — an omitted kwarg means EVERY axis is
        # critical, not none. Reading the absence as an empty set would silently understate 2 of 15 skills.
        crit = set(kw["critical_axes"]) if kw.get("critical_axes") is not None else set(keys)
        for i, axis in enumerate(keys):
            if axis not in kw["axis_labels"]:
                raise UnreadableHeadlineSpec(f"{path}: axis {axis!r} is in `axis_keys` but has no `axis_labels` entry")
            out[(skill, axis)] = {
                "label": kw["axis_labels"][axis],
                "critical": axis in crit,
                "gate": kw["gate"],
                "position": i,
            }
    return out


def _claim_informs_keys() -> set:
    """The live `CLAIM_INFORMS` key set, read from `presence_claims.py`'s AST rather than imported.

    Fail-loud for the same reason `_discover` is: if the map were renamed or built dynamically, an
    import-based read would either crash for an unrelated reason or quietly return something else, and
    the both-directions clause below would stop meaning anything.
    """
    path = _SKILLS_ROOT / "_skills_common" / "presence_claims.py"
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "CLAIM_INFORMS" for t in node.targets):
            try:
                return set(ast.literal_eval(node.value))
            except ValueError as exc:
                raise UnreadableHeadlineSpec(f"{path}: CLAIM_INFORMS is not a literal mapping ({exc})") from exc
    raise UnreadableHeadlineSpec(
        f"{path}: no module-level `CLAIM_INFORMS` assignment. It is the one place the fleet's "
        f"axis->downstream-lens gloss lived, and this registry's coverage of it cannot be checked blind"
    )


def _registry_map(doc: dict) -> dict:
    """The same shape as `_discover`, read off the registry, so the two are directly comparable."""
    out: dict = {}
    order = {s: list(spec.get("axis_keys") or []) for s, spec in (doc.get("skills") or {}).items()}
    for a in doc.get("axes") or []:
        skill, axis = a.get("skill"), a.get("axis_key")
        keys = order.get(skill, [])
        out[(skill, axis)] = {
            "label": a.get("label"),
            "critical": a.get("critical"),
            "gate": (doc.get("skills") or {}).get(skill, {}).get("gate"),
            "position": keys.index(axis) if axis in keys else None,
        }
    return out


def _reconcile(discovered: dict, declared: dict) -> "list[str]":
    """Every disagreement between the code and the registry, as a list of messages.

    A pure function over the two maps so the mutation teeth below can feed a mutated version of EITHER
    side and watch the same comparator that the population test uses go red. A tooth that exercises a
    private copy of the logic proves nothing about the guard.
    """
    problems: list = []
    undeclared = sorted(set(discovered) - set(declared))
    unreal = sorted(set(declared) - set(discovered))
    if undeclared:
        problems.append(
            f"{len(undeclared)} axis pair(s) are declared by a skill's HeadlineSpec but MISSING from "
            f"claim_axis.enum.yaml: {undeclared}. That is a FALSE ABSENCE — the registry would report a "
            f"complete fleet roster while having stopped covering one"
        )
    if unreal:
        problems.append(
            f"{len(unreal)} axis pair(s) are declared in claim_axis.enum.yaml but NO skill's HeadlineSpec "
            f"has them: {unreal}. The code is authoritative for the roster"
        )
    for key in sorted(set(discovered) & set(declared)):
        code, reg = discovered[key], declared[key]
        for field in ("label", "critical", "gate", "position"):
            if code[field] != reg[field]:
                problems.append(
                    f"{key}: `{field}` disagrees — HeadlineSpec says {code[field]!r}, the registry says "
                    f"{reg[field]!r}. The code is authoritative; the registry is a projection of it"
                )
    return problems


REGISTRY = _load_registry()
DISCOVERED = _discover(_SKILLS_ROOT)
DECLARED = _registry_map(REGISTRY)


# ── the population ────────────────────────────────────────────────────────────────────────────────────
def test_the_discovery_glob_found_the_fleet():
    """Anti-vacuity floors. Without them a glob that silently matched nothing would make every equality
    clause below pass over an empty population — the classic fail-open. Both floors name their subject
    inside the assert with `len()` so the repo's static floor-reader can see them."""
    assert len({s for s, _ in DISCOVERED}) >= MIN_SKILLS, (
        f"only {len({s for s, _ in DISCOVERED})} skill(s) declare a HeadlineSpec; the glob "
        f"skills/*/scripts/run.py has stopped matching the fleet"
    )
    assert len(DISCOVERED) >= MIN_AXES, f"only {len(DISCOVERED)} axes discovered"


def test_the_registry_and_the_HeadlineSpecs_agree_in_BOTH_directions():
    """★ The load-bearing clause. Set equality over `(skill, axis_key)` plus field equality on `label`,
    `critical`, `gate` and display `position`. A new axis in any `run.py` reds here until it is declared;
    a declared axis no skill has reds too."""
    assert _reconcile(DISCOVERED, DECLARED) == [], _reconcile(DISCOVERED, DECLARED)
    assert len(DISCOVERED) == len(DECLARED) == 61, (len(DISCOVERED), len(DECLARED))


def test_the_labels_are_pinned_BYTE_FOR_BYTE_and_are_not_all_identical():
    """The label is a second copy of a display string, which is only safe because it is pinned to
    equality. The second assert is the anti-vacuity half: a comparator bug that made every comparison
    trivially true would pass the first."""
    assert all(DECLARED[k]["label"] == DISCOVERED[k]["label"] for k in DISCOVERED)
    assert len({v["label"] for v in DISCOVERED.values()}) >= 50, "labels collapsed — the pin is comparing nothing"


def test_critical_axis_membership_agrees_and_is_a_PROPER_subset_of_the_fleet():
    """`critical_axes` floors confidence in `headline_core.derive_confidence`, so a wrong flag here is a
    behavioural claim. The second assert stops a comparator that read every axis as critical (which is
    what an omitted `critical_axes` kwarg means) from passing the first."""
    assert all(DECLARED[k]["critical"] == DISCOVERED[k]["critical"] for k in DISCOVERED)
    n_crit = sum(1 for v in DISCOVERED.values() if v["critical"])
    assert 0 < n_crit < len(DISCOVERED), f"{n_crit} of {len(DISCOVERED)} critical — neither all nor none is expected"


def test_the_pair_is_the_identity_and_the_DEP_collision_is_the_reason():
    """Measured, not assumed: 61 pairs over 60 distinct tokens. If a roster keyed on the bare token, the
    two `DEP` axes — genetic vs alteration-conferred dependency — would silently conflate."""
    tokens = {ax for _s, ax in DISCOVERED}
    assert len(tokens) == 60 and len(DISCOVERED) == 61, (len(tokens), len(DISCOVERED))
    dep_skills = {s for s, ax in DISCOVERED if ax == "DEP"}
    assert dep_skills == {"functional-requirement", "genomic-alteration-profile"}, dep_skills
    assert (
        DISCOVERED[("functional-requirement", "DEP")]["label"]
        != DISCOVERED[("genomic-alteration-profile", "DEP")]["label"]
    )


def test_every_resolves_id_exists_in_the_property_catalog():
    """The `resolves:` join re-checked from the skills side, in the QUALIFIED form
    `<catalog_id>.<entry_id>`. Qualified because the catalog's bare-id namespace collides: `selectivity`
    and `subtype_restriction` each name one l2a_property AND one unrelated l2b_family."""
    entries: dict = {}
    for path in sorted(_CATALOG_DIR.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text()) or {}
        entries[doc["catalog_id"]] = set(doc.get("properties") or {}) | set(doc.get("families") or {})
    assert len(entries) >= 3, entries
    cited = {r for a in REGISTRY["axes"] for r in (a.get("resolves") or [])}
    assert len(cited) >= 10, f"only {len(cited)} propert(ies) cited — the join has gone nearly empty"
    unresolved = sorted(
        r
        for r in cited
        if r.partition(".")[0] not in entries or r.partition(".")[2] not in entries[r.partition(".")[0]]
    )
    assert unresolved == [], unresolved


def test_the_registry_supersedes_the_one_module_that_held_the_informs_gloss():
    """`CLAIM_INFORMS` lived in exactly ONE module and covered exactly ONE skill's four axes. Its key set
    must be exactly the tumour-presence axis set, both directions, so a 5th key added there without a
    registry entry reds. The WORDING is deliberately NOT pinned: `CLAIM_INFORMS` values are lens names and
    `informs:` values are questions, and a substring pin across two different shapes would be
    green-for-the-wrong-reason theatre."""
    live = _claim_informs_keys()
    presence_axes = {ax for s, ax in DISCOVERED if s == "tumor-presence"}
    assert live == presence_axes == {"A", "B", "C", "D"}, (live, presence_axes)
    declared = {a["axis_key"] for a in REGISTRY["axes"] if a["skill"] == "tumor-presence"}
    assert declared == live, (declared, live)
    assert all(str(a.get("informs", "")).strip() for a in REGISTRY["axes"]), "an axis with no `informs` gloss"


def test_tumor_presence_is_still_the_SOLE_letter_scheme_outlier():
    """The measurement that motivated the item, kept as a number so #2229 has a baseline and so "the
    letters stay" remains a legible outcome rather than a forgotten inconsistency. Not a gate: this module
    may not demand a rename it is forbidden to perform (`claim_vector.<axis>` keys are wire names and a
    mismatch degrades SILENTLY to `unmeasured`)."""
    letters = {s for s, ax in DISCOVERED if len(ax) == 1}
    assert letters == {"tumor-presence"}, (
        f"the letter-scheme population changed: {sorted(letters)}. If it is now empty, #2229 landed and "
        f"this baseline should be retired deliberately; if it grew, a new skill copied the outlier"
    )


# ── mutation teeth ────────────────────────────────────────────────────────────────────────────────────
def _mirror_skills(tmp_path: pathlib.Path) -> pathlib.Path:
    """A tmp `skills/` tree holding only the `*/scripts/run.py` files — everything `_discover` reads.
    Copying the whole tree would be slow and would prove nothing extra."""
    root = tmp_path / "skills"
    for path in sorted(_SKILLS_ROOT.glob("*/scripts/run.py")):
        dest = root / path.parent.parent.name / "scripts" / "run.py"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    return root


def test_the_mirror_itself_rediscovers_the_real_fleet(tmp_path):
    """The clean control. Without it every mutant below could be red merely because the mirror is broken."""
    assert _discover(_mirror_skills(tmp_path)) == DISCOVERED


def test_renaming_an_axis_key_in_a_run_py_goes_RED(tmp_path):
    """★ Tooth 1 from the issue, end to end: the real discovery over a real (copied) `run.py` with one
    axis key renamed, through the same comparator the population test uses."""
    root = _mirror_skills(tmp_path)
    target = root / "literature-context" / "scripts" / "run.py"
    text = target.read_text()
    assert text.count('"VOLUME"') >= 2, "fixture drift: VOLUME no longer appears in axis_keys + axis_labels"
    target.write_text(text.replace('"VOLUME"', '"CITATION_VOLUME"'))
    problems = _reconcile(_discover(root), DECLARED)
    assert any("FALSE ABSENCE" in p for p in problems), problems
    assert any("NO skill's HeadlineSpec has them" in p for p in problems), problems


def test_changing_an_axis_LABEL_in_a_run_py_goes_RED(tmp_path):
    root = _mirror_skills(tmp_path)
    target = root / "immune-context" / "scripts" / "run.py"
    target.write_text(target.read_text().replace('"TCE effector context"', '"something else entirely"'))
    problems = _reconcile(_discover(root), DECLARED)
    assert any("`label` disagrees" in p for p in problems), problems


def test_dropping_a_registry_entry_goes_RED():
    """★ Tooth 2 from the issue. The registry side mutated instead of the code side, so the OTHER
    direction of the equality is proven to bite."""
    trimmed = {k: v for k, v in DECLARED.items() if k != ("on-target-safety-liability", "PAN_ESSENTIAL")}
    problems = _reconcile(DISCOVERED, trimmed)
    assert any("FALSE ABSENCE" in p for p in problems), problems


def test_flipping_a_registry_critical_flag_goes_RED():
    mutated = dict(DECLARED)
    key = ("functional-requirement", "DEP")
    mutated[key] = {**DECLARED[key], "critical": not DECLARED[key]["critical"]}
    assert any("`critical` disagrees" in p for p in _reconcile(DISCOVERED, mutated)), "critical is not compared"


def test_reordering_a_registry_axis_key_list_goes_RED():
    """Display order is information the flat roster would lose, so `position` is compared too."""
    doc = yaml.safe_load(_ENUM_PATH.read_text())
    doc["skills"]["literature-context"]["axis_keys"].reverse()
    assert any("`position` disagrees" in p for p in _reconcile(DISCOVERED, _registry_map(doc))), "order is not compared"


def test_an_UNREADABLE_headline_spec_RAISES_rather_than_shrinking_the_roster(tmp_path):
    """★ The fail-loud contract. A `run.py` that still names `HeadlineSpec(` but whose `axis_keys` is no
    longer a literal must RAISE — if `_discover` degraded to skipping it, the skill would vanish from the
    population and the registry would read as complete while covering 14 of 15 skills. The cardinality
    floor would not catch it either: 14 is still >= the floor."""
    root = _mirror_skills(tmp_path)
    target = root / "immune-context" / "scripts" / "run.py"
    target.write_text(target.read_text().replace('axis_keys=("IMMUNE",)', "axis_keys=tuple(_computed_at_runtime)"))
    with pytest.raises(UnreadableHeadlineSpec):
        _discover(root)


def test_a_run_py_naming_HeadlineSpec_with_no_reachable_CALL_RAISES(tmp_path):
    root = _mirror_skills(tmp_path)
    target = root / "immune-context" / "scripts" / "run.py"
    target.write_text('spec = "HeadlineSpec(" + _built_some_other_way\n')
    with pytest.raises(UnreadableHeadlineSpec):
        _discover(root)


def test_an_empty_skills_root_discovers_NOTHING_and_the_floor_is_what_catches_it(tmp_path):
    """The failure mode the floors exist for, made explicit: `_discover` over an empty tree returns {} —
    no exception, because there is no `HeadlineSpec(` to fail on — and `_reconcile({}, DECLARED)` would
    then report only the 'declared but unreal' direction. The floor test is the only thing standing
    between that and a green suite."""
    empty = tmp_path / "skills"
    empty.mkdir()
    assert _discover(empty) == {}
    assert len({s for s, _ in _discover(empty)}) < MIN_SKILLS
