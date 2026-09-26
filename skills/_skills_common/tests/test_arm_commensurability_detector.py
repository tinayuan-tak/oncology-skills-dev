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

SK#1689 EXTENDS the same mechanism to a SECOND, NON-GENOMIC builder family — the EXPRESSION / PROTEOMICS
multi-arm builders in selectivity_claims.py (tumor-vs-normal RNA window + CPTAC/TPHP protein quorum). See
the block at the bottom of this file; the milestone is that the arm-commensurability audit becomes a
repo-wide standing gate rather than a per-family manual sweep.
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


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# SECOND FAMILY — the EXPRESSION / PROTEOMICS multi-arm builders in selectivity_claims.py (SK#1689)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# SK#1688 made the audit a standing gate for the GENOMIC builders. The same failure class — a builder
# folding arms that are not the same construct — is not genomic-specific. The next family of multi-arm
# builders in _skills_common is EXPRESSION / PROTEOMICS: selectivity_claims.py projects the tumor-vs-
# normal RNA window (DESeq2) and the two independent tumor-vs-normal PROTEIN platforms (CPTAC TMT-MS +
# TPHP DIA-MS) into a claim vector. It has TWO multi-arm builders, audited below.
#
# AUDIT VERDICT (SK#1689): NO incommensurate pairing was found in this family — unlike the three genomic
# cases (#1667/#1674/#1673), both selectivity multi-arm builders already fold COMMENSURATE arms, so this
# is a detector-oracle EXTENSION, not a fix:
#   1. `_int_corroboration` — the ONLY `corroboration_from_arms` caller here — folds FOUR reads of the
#      SAME biological property (is the selective signal MALIGNANT-CELL-INTRINSIC?) across modalities:
#      the sc-tumour malignant read, the sc CAF-vs-malignant read, the bulk purity-confound read, and the
#      in-situ SPATIAL region-RNA read. These are commensurate by the "same property, independent
#      measurement" test (the multi-modal quorum is the deliberate design; the absent-vs-disagreeing arm
#      discipline was already fixed in-file). Folding a DIFFERENT-axis field (e.g. the WIN RNA window
#      class) into this quorum is the analogue of the #1673 construct-mismatch, and the mutation test at
#      the bottom drives exactly that red.
#   2. `_protein_window_quorum` — a hand-rolled 2-arm quorum over CPTAC TMT-MS × TPHP DIA-MS, both bulk
#      tumor-vs-normal PROTEIN abundance (same granularity, same provenance basis), so the two arms are
#      commensurate. It is the `_signal`/demotion MIRROR for this family (the analogue of `_cn_signal`):
#      it imposes a corroboration CAP and emits a conflict NOTE from ≥2 headline fields. The #1673 trap
#      was two SEPARATE functions (`_cn_signal`/`_cn_corroboration`) kept in lockstep BY HAND; here the
#      mirror cannot diverge because it is ONE shared helper consumed by BOTH `_win_signal` (the note) and
#      `_win_corroboration` (the cap). The mirror test below pins that shared-helper coupling structurally,
#      so a future edit that reads the quorum in only ONE of the two — re-opening the self-contradiction
#      risk — fails loudly.
#
# This whole block edits ONLY the test file — no selectivity_claims.py change — so it is verdict
# byte-stable by construction (no decision.json / field_read_health / golden move, no target-contracts
# pin).

_SELECTIVITY_CLAIMS = pathlib.Path(__file__).resolve().parents[1] / "selectivity_claims.py"


# The DECLARED oracle for the expression/proteomics family. Same contract as
# `_DECLARED_CORROBORATION_BUILDERS`: every function that folds ≥2 arms via `corroboration_from_arms` in
# selectivity_claims.py must appear here with its arm pairing, or the enumeration test below fails until
# it is declared — extending the anti-drift gate to this family.
_DECLARED_SELECTIVITY_CORROBORATION_BUILDERS = {
    "_int_corroboration": (
        "sc-tumour malignant read × sc CAF-vs-malignant × bulk purity-confound × in-situ spatial RNA — "
        "four INDEPENDENT reads of the SAME malignant-cell-intrinsic property, one multi-modal quorum "
        "(commensurate by same-property; see _INT_COMMENSURATE_ARM_FIELDS)"
    ),
}

# The headline fields `_int_corroboration` reads to build its arms. Each is a read of the malignant-
# compartment-attribution property at a DIFFERENT modality; the set is what makes the quorum commensurate.
# A re-pointed arm (a field NOT on this list, e.g. a WIN tumor-vs-normal-window class) or a new undeclared
# arm changes this set and fails the commensurability test below.
_INT_COMMENSURATE_ARM_FIELDS = frozenset(
    {
        "sc_tumor_expression_class",  # the sc-tumour malignant read (the claim being corroborated)
        "sc_caf_vs_malignant_class",  # sc CAF vs malignant compartment
        "purity_confound_class",  # bulk purity confound
        "spatial_rna_class",  # in-situ spatial region-RNA (deconvolution-free)
    }
)

# The `_signal`/demotion MIRROR for this family and its two consumers. `_protein_window_quorum` is the
# shared 2-arm protein quorum; it must be read by BOTH the signal builder (`_win_signal`, which surfaces
# its NOTE) and the corroboration builder (`_win_corroboration`, which applies its CAP), or the published
# object could carry a "protein contradicts" note with no matching corroboration cap — the selectivity
# analogue of the #1673 self-contradiction.
_PROTEIN_QUORUM = "_protein_window_quorum"
_PROTEIN_QUORUM_CONSUMERS = ("_win_signal", "_win_corroboration")


def _selectivity_tree() -> ast.Module:
    return _parse(_SELECTIVITY_CLAIMS.read_text())


def _headline_fields_read(func: ast.FunctionDef) -> set[str]:
    """Every `h.get("<field>")` string field read anywhere in `func` (the headline is bound to `h` in
    every claim builder, `def _fn(h, c)`)."""
    found: set[str] = set()
    for n in ast.walk(func):
        field = _headline_get_field(n)
        if field is not None:
            found.add(field)
    return found


def _calls_named(func: ast.FunctionDef, name: str) -> bool:
    """True if `func` calls the module-level function `name` (a bare `name(...)` call)."""
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name for n in ast.walk(func))


def assert_int_arms_are_commensurate(tree: ast.Module) -> None:
    """Raise AssertionError unless `_int_corroboration` folds EXACTLY the declared commensurate malignant-
    compartment arm fields (`_INT_COMMENSURATE_ARM_FIELDS`) — no incommensurate field pulled in, none
    dropped. The predicate the new-family mutation test drives red."""
    funcs = _functions(tree)
    assert "_int_corroboration" in funcs, "_int_corroboration vanished from selectivity_claims.py"
    fields = _headline_fields_read(funcs["_int_corroboration"])
    assert fields == set(_INT_COMMENSURATE_ARM_FIELDS), (
        f"_int_corroboration folds headline fields {sorted(fields)} — expected EXACTLY the commensurate "
        f"malignant-cell-intrinsic arm set {sorted(_INT_COMMENSURATE_ARM_FIELDS)}. An extra field mixes a "
        f"DIFFERENT biological property into the intrinsic quorum (a false agreement/conflict, the "
        f"selectivity analogue of SK#1673); a missing field means an arm was dropped or renamed. "
        f"undeclared = {sorted(fields - set(_INT_COMMENSURATE_ARM_FIELDS))}; "
        f"gone = {sorted(set(_INT_COMMENSURATE_ARM_FIELDS) - fields)}."
    )


# ── the selectivity-family tests ────────────────────────────────────────────────────────────────────
def test_selectivity_multi_arm_builders_are_declared():
    """ENUMERATION / anti-drift for the expression/proteomics family: every function that folds arms via
    `corroboration_from_arms` in selectivity_claims.py must be declared. A NEW multi-arm builder fails
    here until its arm pairing is declared in `_DECLARED_SELECTIVITY_CORROBORATION_BUILDERS`."""
    discovered = _corroboration_builders(_selectivity_tree())
    declared = set(_DECLARED_SELECTIVITY_CORROBORATION_BUILDERS)
    assert discovered == declared, (
        f"selectivity multi-arm corroboration builders drifted from the declared oracle: "
        f"undeclared (add its arm pairing) = {sorted(discovered - declared)}; "
        f"declared-but-gone (remove it) = {sorted(declared - discovered)}"
    )


def test_int_corroboration_folds_the_commensurate_malignant_compartment_arms():
    """GREEN on today's selectivity_claims.py: `_int_corroboration` folds exactly the four commensurate
    malignant-cell-intrinsic reads. Also anti-vacuity — the declared arm set is non-empty."""
    assert _INT_COMMENSURATE_ARM_FIELDS, "the declared INT arm set is empty — the test would pin nothing"
    assert_int_arms_are_commensurate(_selectivity_tree())


def test_protein_window_quorum_is_the_shared_signal_and_corroboration_mirror():
    """The selectivity `_signal`/demotion MIRROR, as a structural invariant no single behavioural fixture
    spans: the 2-arm protein quorum must exist and be consumed by BOTH `_win_signal` (its note) and
    `_win_corroboration` (its cap). Reading it in only one re-opens the #1673-class self-contradiction (a
    "protein contradicts" note with no matching corroboration cap)."""
    funcs = _functions(_selectivity_tree())
    assert _PROTEIN_QUORUM in funcs, f"{_PROTEIN_QUORUM} not found in selectivity_claims.py"
    for consumer in _PROTEIN_QUORUM_CONSUMERS:
        assert consumer in funcs, f"{consumer} not found in selectivity_claims.py"
        assert _calls_named(funcs[consumer], _PROTEIN_QUORUM), (
            f"{consumer} no longer reads {_PROTEIN_QUORUM} — the shared signal/corroboration mirror is "
            f"broken (SK#1673-class self-contradiction risk for the tumor-vs-normal protein window)"
        )


# The mutation the new-family detector exists to catch: one INT arm re-pointed from the in-situ spatial
# read to the WIN tumor-vs-normal-window RNA class — a DIFFERENT biological property (window, not
# intrinsic compartment). Applied to a COPY of the source string, so the real module is never mutated.
def _mutant_int_arm_repointed_to_win_window(source: str) -> str:
    mutated = source.replace("spatial_rna_class", "axis_a_selectivity_class")
    assert mutated != source, "mutation was a no-op — the spatial arm field is no longer present to re-point"
    return mutated


def test_detector_bites_an_int_arm_repointed_to_a_different_axis():
    """MUTATION TEST for the new family — the corpus alone has no teeth here, so prove the detector bites.
    With one INT arm re-pointed to the WIN tumor-vs-normal-window class (an incommensurate different-
    property field), `_int_corroboration`'s read set no longer equals the declared commensurate arms and
    `assert_int_arms_are_commensurate` FAILS. Confirms both the RED (on the mutant) and — via
    `test_int_corroboration_folds_the_commensurate_malignant_compartment_arms` — the GREEN on real source."""
    mutant = _parse(_mutant_int_arm_repointed_to_win_window(_SELECTIVITY_CLAIMS.read_text()))
    # sanity: the mutant genuinely re-points an INT arm to the incommensurate window field
    fields = _headline_fields_read(_functions(mutant)["_int_corroboration"])
    assert "axis_a_selectivity_class" in fields and "spatial_rna_class" not in fields, (
        "the mutation did not re-point the INT arm as intended"
    )
    # …and the detector rejects it
    with pytest.raises(AssertionError, match="_int_corroboration"):
        assert_int_arms_are_commensurate(mutant)
