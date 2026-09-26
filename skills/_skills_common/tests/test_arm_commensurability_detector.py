"""STANDING STRUCTURAL DETECTOR for arm commensurability in genomic_claims.py (SK#1688, epic #1507).

The arm-commensurability audit (#1667/#1674/#1673) kept finding the SAME class of bug BY HAND: a
two-arm builder compares a cell-line construct against a patient construct that is not the same
construct — a different GRANULARITY (focal vs broad) or a different PROVENANCE basis (GISTIC homdel-only
vs any-loss). #1673 was the sharpest case: `_cn_corroboration` and `_cn_signal` were DELIBERATELY
MIRRORED, so fixing one alone would have shipped a self-contradictory published object (corroboration
`high` while signal `weak` on the same SMAD4/COADREAD call). A hand audit caught the mirror.

This module makes that audit a STANDING GATE rather than a recurring manual sweep. It STATIC-PARSES
genomic_claims.py (never imports the verdict path — verdict-INERT), enumerates every multi-arm builder,
and asserts each arm pair reads COMMENSURATE fields against a small DECLARED oracle table, so a NEW
builder or a re-pointed field fails loudly until its pairing is declared.

WHY STATIC/AST, not behavioural. `test_corroboration_two_arm_axes.py` and `test_genomic_claims.py`
already pin the BEHAVIOUR exhaustively (given inputs → correct corroboration). This detector pins the
STRUCTURE — WHICH headline field each direction of each builder reads — which is (a) the level the #1673
bug lived at, (b) where a NEW un-audited builder would silently appear, and (c) a mirror-coupling check
between the two CN builders that no single behavioural fixture spans.

The oracle below is pure declared DATA that the runtime never reads into any verdict path (it lives only
in this test), so this whole module is verdict-inert: it moves no decision.json, no field_read_health,
and needs no target-contracts pin.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_GENOMIC_CLAIMS = pathlib.Path(__file__).resolve().parents[1] / "genomic_claims.py"


# ── the DECLARED commensurability oracle ─────────────────────────────────────────────────────────────
# Every function that folds ≥2 arms through `corroboration_from_arms`. DISCOVERED from the AST by
# `_corroboration_builders` below and cross-checked against this table, so a NEW multi-arm corroboration
# builder fails `test_every_multi_arm_builder_is_declared` until its arm pairing is declared here.
_DECLARED_CORROBORATION_BUILDERS = {
    "_role_corroboration": "curated role-call arm × functional-direction arm — same curated-annotation basis",
    "_snv_corroboration": (
        "MC3 exome `driver_recurrence_class` × GENIE panel `genie_driver_recurrence_class` — both "
        "cohort variant-recurrence; the GENIE arm is judged against the INDEPENDENT MC3 band, NEVER the "
        "pooled superset that already absorbed it (SK#1667)"
    ),
    "_cn_corroboration": (
        "cell-line `copy_number_class` × patient CN, matched PER DIRECTION to the commensurate patient "
        "measure (SK#1673) — see _CN_DIRECTION_ARM"
    ),
    "_spl_corroboration": (
        "curated splice-registry arm × live DepMap pan-cancer carrier arm — the carrier arm leaves the "
        "frame when incommensurate with an indication-scoped negative (SK#1674)"
    ),
    "_fus_corroboration": "`fusion_class` × GENIE-SV `genie_sv_recurrence_class` — both rearrangement recurrence",
    "_recurrence_concordance_claim": (
        "MC3 exome × GENIE panel INDEPENDENT cohorts; the pooled superset is evidence, NEVER an arm"
    ),
}

# The two patient copy-number arms, each tagged with the (granularity, provenance_basis) that makes it
# COMMENSURATE with a cell-line direction. `patient_focal_cn_class` is the GISTIC high-level (homdel/+2)
# FOCAL call; `patient_copy_number_class` is the GISTIC |CN|≥1 ANY-loss/any-gain BROAD call.
_PATIENT_CN_ARM = {
    "patient_focal_cn_class": ("focal", "patient_gistic_high_level"),
    "patient_copy_number_class": ("broad_any_loss", "patient_gistic_any_loss"),
}

# The cell-line `copy_number_class` score is ASYMMETRIC by construction (depmap_cn_distribution
# `_classify_cn`): the AMP score counts only focal/high gain (relative CN > 1.5, shallow arm-level gain
# EXCLUDED) → FOCAL; the DEL score folds deep AND shallow hemizygous loss → BROAD any-loss. So each
# direction has a DIFFERENT commensurate patient arm — the whole point of SK#1673.
_CN_CELLLINE_BASIS_GRANULARITY = {
    "recurrently_amplified": "focal",
    "recurrently_deleted": "broad_any_loss",
}

# The known-good pairing (post-SK#1673). A cell-line direction → the patient field it MUST read.
_CN_DIRECTION_ARM = {
    "recurrently_amplified": "patient_focal_cn_class",  # focal ↔ focal
    "recurrently_deleted": "patient_copy_number_class",  # broad any-loss ↔ broad any-loss
}

# The CN builders whose per-direction patient-arm reads must match `_CN_DIRECTION_ARM`. `_cn_corroboration`
# folds the arms through `corroboration_from_arms`; `_cn_signal` emits the deliberately-MIRRORED demotion
# from the SAME two headline fields (a `_signal`/demotion from ≥2 fields, per the issue's second builder
# class), so it must repoint IDENTICALLY or the published object is self-contradictory — exactly the #1673
# SMAD4/COADREAD trap (corroboration `high` while signal `weak`).
_CN_DIRECTIONAL_BUILDERS = ("_cn_corroboration", "_cn_signal")

_DIRECTION_TOKENS = frozenset(_CN_DIRECTION_ARM)
_PATIENT_CN_FIELDS = frozenset(_PATIENT_CN_ARM)


# ── static extraction (no import of the verdict path) ────────────────────────────────────────────────
def _parse(source: str) -> ast.Module:
    return ast.parse(source)


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def _calls_corroboration_from_arms(func: ast.FunctionDef) -> bool:
    return any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "corroboration_from_arms"
        for n in ast.walk(func)
    )


def _corroboration_builders(tree: ast.Module) -> set[str]:
    """Every function in the module that folds arms via `corroboration_from_arms` — the AST is the
    source of truth, so a newly-added builder is DISCOVERED, not assumed."""
    return {name for name, fn in _functions(tree).items() if _calls_corroboration_from_arms(fn)}


def _headline_get_field(node: ast.AST) -> str | None:
    """`h.get("<field>")` → "<field>", else None. The headline is bound to the local `h` in every
    multi-arm builder (`def _fn(h, c)`)."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "h"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        return node.args[0].value
    return None


def _patient_field_aliases(func: ast.FunctionDef) -> dict[str, str]:
    """Map each local name bound to `<name> = h.get("<patient CN field>")` → that field, so a branch that
    reads the field THROUGH a local (`focal = h.get(...)`; later `focal in _CN_FOCAL_NEG`) is resolved to
    the same field as an inline `h.get(...)`. Restricted to the patient CN fields the oracle governs."""
    aliases: dict[str, str] = {}
    for n in ast.walk(func):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            field = _headline_get_field(n.value)
            if field in _PATIENT_CN_FIELDS:
                aliases[n.targets[0].id] = field
    return aliases


def _patient_fields_in(subtree: ast.AST, aliases: dict[str, str]) -> set[str]:
    """Every patient CN field read within `subtree` — directly via `h.get("...")` or through a resolved
    local alias (`Name` load)."""
    found: set[str] = set()
    for n in ast.walk(subtree):
        field = _headline_get_field(n)
        if field in _PATIENT_CN_FIELDS:
            found.add(field)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in aliases:
            found.add(aliases[n.id])
    return found


def _direction_tokens_in(test: ast.AST) -> set[str]:
    """The cell-line direction token(s) a branch `test` guards on, e.g. `cls == "recurrently_deleted"`."""
    return {
        n.value
        for n in ast.walk(test)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in _DIRECTION_TOKENS
    }


def cn_direction_patient_fields(func: ast.FunctionDef) -> dict[str, set[str]]:
    """The heart of the detector: direction → {patient CN fields read under that direction}.

    Walks every `if`/`elif` clause (each is its own `ast.If` node; the `elif` chain nests through
    `orelse`, so per-node `test` + `body` isolates one clause). A clause guarded by a direction token
    contributes the patient CN fields read in its test + body (inline or via a resolved alias). Clauses
    with no direction token (e.g. `_cn_signal`'s `if focal in _CN_FOCAL_POS:`, which applies to BOTH
    directions) are ignored — the per-direction commensurability question does not apply to them.
    """
    aliases = _patient_field_aliases(func)
    out: dict[str, set[str]] = {d: set() for d in _DIRECTION_TOKENS}
    for node in ast.walk(func):
        if not isinstance(node, ast.If):
            continue
        directions = _direction_tokens_in(node.test)
        if not directions:
            continue
        fields = _patient_fields_in(node.test, aliases)
        for stmt in node.body:
            fields |= _patient_fields_in(stmt, aliases)
        for d in directions:
            out[d] |= fields
    return out


def assert_cn_builders_are_commensurate(tree: ast.Module) -> None:
    """Raise AssertionError unless every CN directional builder reads EXACTLY the commensurate patient
    field per direction (`_CN_DIRECTION_ARM`) and reads no INCOMMENSURATE patient field. This is the
    predicate the mutation test drives red."""
    funcs = _functions(tree)
    for name in _CN_DIRECTIONAL_BUILDERS:
        assert name in funcs, f"CN directional builder {name!r} vanished from genomic_claims.py"
        got = cn_direction_patient_fields(funcs[name])
        for direction, expected_field in _CN_DIRECTION_ARM.items():
            fields = got[direction]
            assert fields == {expected_field}, (
                f"{name}: the {direction!r} arm must read EXACTLY the commensurate patient field "
                f"{expected_field!r} ({_PATIENT_CN_ARM[expected_field][0]} granularity, "
                f"{_PATIENT_CN_ARM[expected_field][1]}); read {sorted(fields) or 'nothing'} instead. "
                f"A cell-line {direction!r} call is {_CN_CELLLINE_BASIS_GRANULARITY[direction]!r} "
                f"(depmap_cn_distribution._classify_cn), so pairing it with an incommensurate patient "
                f"granularity manufactures a false conflict/agreement (SK#1673)."
            )


# ── the tests ────────────────────────────────────────────────────────────────────────────────────────
def _tree() -> ast.Module:
    return _parse(_GENOMIC_CLAIMS.read_text())


def test_every_multi_arm_builder_is_declared():
    """ENUMERATION / anti-drift: every function that folds arms via `corroboration_from_arms` must be in
    the declared oracle. A NEW multi-arm builder (or a rename) fails here until its arm pairing is
    declared in `_DECLARED_CORROBORATION_BUILDERS` — turning the recurring manual sweep into a gate."""
    discovered = _corroboration_builders(_tree())
    declared = set(_DECLARED_CORROBORATION_BUILDERS)
    assert discovered == declared, (
        f"multi-arm corroboration builders drifted from the declared oracle: "
        f"undeclared (add its arm pairing) = {sorted(discovered - declared)}; "
        f"declared-but-gone (remove it) = {sorted(declared - discovered)}"
    )


def test_cn_directional_builders_exist_and_feed_the_two_field_classes():
    """Anti-vacuity: both CN builders must exist and actually read the two governed patient CN fields, or
    the commensurability assertion below would be pinning nothing. `_cn_corroboration` folds the arms;
    `_cn_signal` is the demotion mirror that reads ≥2 headline fields."""
    funcs = _functions(_tree())
    for name in _CN_DIRECTIONAL_BUILDERS:
        assert name in funcs, f"{name} not found in genomic_claims.py"
        got = cn_direction_patient_fields(funcs[name])
        read = set().union(*got.values())
        assert read == _PATIENT_CN_FIELDS, (
            f"{name} reads patient CN fields {sorted(read)} — expected both {sorted(_PATIENT_CN_FIELDS)}"
        )


def test_cn_oracle_is_internally_granularity_and_provenance_commensurate():
    """The declared table itself encodes the commensurability rule: focal ↔ focal, broad ↔ broad. Each
    direction's declared patient arm must share the cell-line score's GRANULARITY basis. Guards the
    oracle against a typo that would make the whole detector assert the wrong pairing."""
    for direction, patient_field in _CN_DIRECTION_ARM.items():
        patient_granularity = _PATIENT_CN_ARM[patient_field][0]
        cellline_granularity = _CN_CELLLINE_BASIS_GRANULARITY[direction]
        assert patient_granularity == cellline_granularity, (
            f"{direction!r}: cell-line score is {cellline_granularity!r} but its declared patient arm "
            f"{patient_field!r} is {patient_granularity!r} — the pairing is not commensurate"
        )
    # amp and del must consult DIFFERENT patient arms — that asymmetry is the SK#1673 fix, not an accident.
    assert _CN_DIRECTION_ARM["recurrently_amplified"] != _CN_DIRECTION_ARM["recurrently_deleted"]


def test_cn_builders_read_the_commensurate_patient_field_per_direction():
    """GREEN on today's genomic_claims.py: amp ↔ `patient_focal_cn_class`, del ↔
    `patient_copy_number_class`, in BOTH CN builders."""
    assert_cn_builders_are_commensurate(_tree())


def test_cn_signal_and_cn_corroboration_use_the_SAME_direction_split():
    """The #1673 mirror-coupling, as a structural invariant no single behavioural fixture spans: the
    demotion builder (`_cn_signal`) and the corroboration builder (`_cn_corroboration`) must repoint the
    deletion (and amplification) arm to the SAME patient field. Fixing one without the other is precisely
    what would re-ship the self-contradictory SMAD4/COADREAD object (corroboration `high`, signal
    `weak`)."""
    funcs = _functions(_tree())
    sig = cn_direction_patient_fields(funcs["_cn_signal"])
    corr = cn_direction_patient_fields(funcs["_cn_corroboration"])
    assert sig == corr, (
        f"_cn_signal and _cn_corroboration disagree on the direction→patient-field split — the deliberate "
        f"mirror is broken (SK#1673 self-contradiction risk): signal={sig}, corroboration={corr}"
    )


# The mutation the detector exists to catch: the del arm re-pointed BACK to the homdel-only focal call
# (the pre-#1673 incommensurate pairing). Applied to a COPY of the source string, so the real module is
# never mutated. A blanket rename of the any-loss field to the focal field re-points the deletion branch
# of BOTH CN builders — exactly the mispairing #1673 removed — and the detector must go red.
def _mutant_del_repointed_to_focal_homdel(source: str) -> str:
    mutated = source.replace("patient_copy_number_class", "patient_focal_cn_class")
    assert mutated != source, "mutation was a no-op — the any-loss field is no longer present to re-point"
    return mutated


def test_detector_bites_a_del_arm_repointed_to_focal_homdel():
    """MUTATION TEST — the corpus alone has no teeth here, so prove the detector actually bites. With the
    deletion arm re-pointed to the incommensurate homdel-only `patient_focal_cn_class`, the deletion
    direction reads the focal field and the commensurability assertion FAILS. Confirms both the RED (on
    the mutant) and — via `test_cn_builders_read_the_commensurate_patient_field_per_direction` — the GREEN
    on the real source."""
    mutant = _parse(_mutant_del_repointed_to_focal_homdel(_GENOMIC_CLAIMS.read_text()))
    # sanity: the mutant genuinely re-points the deletion arm to the focal field
    got = cn_direction_patient_fields(_functions(mutant)["_cn_corroboration"])
    assert got["recurrently_deleted"] == {"patient_focal_cn_class"}, (
        "the mutation did not re-point the deletion arm as intended"
    )
    # …and the detector rejects it
    with pytest.raises(AssertionError, match="recurrently_deleted"):
        assert_cn_builders_are_commensurate(mutant)
