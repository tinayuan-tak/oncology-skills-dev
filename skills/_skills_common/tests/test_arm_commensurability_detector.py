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
multi-arm builders in selectivity_claims.py (tumor-vs-normal RNA window + CPTAC/TPHP protein quorum).
SK#1675 EXTENDS it to a THIRD family — the TUMOR-PRESENCE multi-arm builders in presence_claims.py
(`_claim_B`'s RNA-DGE × CPTAC protein tumor-elevation fold, plus the L2b cross-source claims). Both later
families proved COMMENSURATE by design (detector-oracle extensions, not fixes). SK#1600 EXTENDS it to a
FOURTH family — the LITERATURE-CONTEXT corroboration builder in literature_context_claims.py — which,
unlike the selectivity/presence extensions, was a genuine FIX (a non-independent n_diseases pleiotropy
arm, the #1667 shape): literature is a one-armed axis capped at single_arm. See the family blocks at
the bottom of this file; the milestone is that the arm-commensurability audit becomes a repo-wide standing
gate rather than a per-family manual sweep.
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
    "_selectivity_concordance_claim": (
        "bulk-RNA tumor-vs-normal window (recount3 TCGA/GTEx) × protein-MS tumor-vs-normal window (CPTAC "
        "TMT-MS) — the two INDEPENDENT arms of the L2b-5 selectivity_concordance family (SK#1752). Two "
        "reads of the SAME tumor-vs-normal-window property at DIFFERENT molecular layers (commensurate by "
        "same-property, cross-modality). The protein arm is one arm supplied by a same-modality group "
        "{cptac_tmt, tphp_dia}; TPHP DIA-MS is corroboration-INELIGIBLE (never a third independent arm), "
        "so corroboration_from_arms folds EXACTLY [rna_arm, protein_arm] — never a TPHP third arm."
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


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# THIRD FAMILY — the TUMOR-PRESENCE multi-arm builders in presence_claims.py (SK#1675)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# SK#1688/#1689 made the audit a standing gate for the GENOMIC and EXPRESSION/PROTEOMICS families. The
# presence family is the last open sibling of the arm-commensurability audit (#1507). Its lead multi-arm
# builder is `_claim_B` (tumor-elevation): it folds a tumor-vs-normal DIRECTION from TWO arms —
#   * RNA-DGE  — tumor-rna-vs-adjacent.expression_call_class, and
#   * CPTAC    — tumor-protein-abundance-cptac.protein_expression_class —
# and awards corroboration `high` when BOTH arms are up (`len(ups) >= 2`). The deferred finding asked
# whether that fold conflates agreement-on-signal with agreement-on-COMPARATOR (the reference each arm is
# scored against differing across arms).
#
# AUDIT VERDICT (SK#1675): NO incommensurate pairing was found — like the selectivity family (#1689),
# `_claim_B`'s two direction arms are COMMENSURATE, so this is a detector-oracle EXTENSION, not a fix:
#   * BOTH arms are scored against MATCHED-ADJACENT normal — RNA vs TCGA adjacent-normal (the
#     tumor-rna-vs-adjacent card question is literally "…upregulated in tumor vs matched adjacent normal";
#     the class bins a DESeq2 `tumor_vs_adjacent` contrast), and CPTAC protein vs the cohort's own
#     Solid-Tissue-Normal aliquots (the tumor-protein-abundance-cptac card question is "…vs matched
#     normals per CPTAC"; the class thresholds an MSstatsTMT Tumor−Normal effect where the analysis-methods
#     input-prep maps "Solid Tissue Normal"/"Blood Derived Normal" → "Normal"). So the two arms share the
#     SAME comparator basis and differ only in MODALITY (RNA vs protein) — commensurate by the
#     "same-basis, different-measurement" test, the analogue of the selectivity multi-modal quorum.
#   * MEASURED (no vote flip): both-arms-up → corroboration `high` is a genuine cross-modality
#     corroboration of tumor-elevation-vs-adjacent, NOT a comparator conflation; a single arm reads
#     `moderate`; a direction disagreement (up/down) and a modality/post-transcriptional discordance
#     (one arm up, one measured-flat vs the SAME adjacent basis) are already surfaced as conflicts. No
#     alternative same-basis pairing exists that would change the fold, so no vote flips → no `_claim_B`
#     change.
#   * "The author already partially handled the comparator basis": the RNA card ALSO carries a
#     gtex_log2_fc/gtex_q_value tumor-vs-GTEx-POPULATION contrast — a DIFFERENT comparator basis — but it
#     is DISPLAY-ONLY (verdict-inert; no rule keys on it and the class stays adjacent-driven), and
#     `_claim_B` surfaces it as `comparator_detail` / a "flat vs adjacent but elevated vs GTEx-population"
#     NOTE, never as a `_dir` direction arm. Folding that population contrast (or any population field) as
#     a direction arm — mixing matched-adjacent RNA with population protein — is the presence analogue of
#     the #1673 construct-mismatch; the mutation test at the bottom drives exactly that red.
#     (An in-file code comment on `_claim_B` loosely paraphrases the CPTAC arm as "vs population-normal";
#     that phrasing is imprecise — the authoritative basis is matched-adjacent — but it is a comment only,
#     moves no published object, and is left untouched to keep the change verdict byte-stable.)
#
# SHAPE DIFFERENCES from the earlier families (why the presence detectors below are keyed differently):
#   1. `_claim_B` folds arms through the presence DIRECTION primitive `_dir(...)`, NOT
#      `corroboration_from_arms`, and computes corroboration inline (`len(ups) >= 2`); so the direction
#      builders are discovered by counting `_dir(...)` calls.
#   2. `_claim_B` reads its arms from the CARD dict (`c.get("<card>", {}).get("<field>")`), NOT the
#      headline `h`; so the arm extractor resolves card aliases and returns (card_id, field) pairs.
#   3. presence ALSO has two `corroboration_from_arms` callers, but IMPORTED UNDER AN ALIAS
#      (`corroboration_from_arms as _corr_from_arms`): the L2b cross-source claims
#      `_coverage_concordance_claim` (two orthogonal facets of the SAME single-cell assay) and
#      `_abundance_concordance_claim` (GRAIN-ANCHORED same-grain RNA×MS-protein, cross-grain as an
#      independent corroborating arm, compared on within-population rank per #1512). Both are commensurate
#      by construction; the enumeration below resolves the import alias so a NEW aliased caller is caught.
#
# This whole block edits ONLY the test file — no presence_claims.py change — so it is verdict byte-stable
# by construction (no decision.json / field_read_health / golden move, no target-contracts pin).

_PRESENCE_CLAIMS = pathlib.Path(__file__).resolve().parents[1] / "presence_claims.py"


# The DECLARED oracle for the presence DIRECTION builders (the `_claim_B` shape): every function that
# folds ≥2 tumor-vs-normal direction arms via the `_dir(...)` primitive must appear here with its arm
# pairing, or the enumeration test fails until it is declared — the anti-drift gate for this family.
_DECLARED_PRESENCE_DIRECTION_BUILDERS = {
    "_claim_B": (
        "tumor-vs-normal ELEVATION from two arms: RNA-DGE (tumor-rna-vs-adjacent.expression_call_class) "
        "× CPTAC protein (tumor-protein-abundance-cptac.protein_expression_class) — BOTH scored vs "
        "MATCHED-ADJACENT normal (TCGA adjacent for RNA, CPTAC solid-tissue-normal for protein), "
        "commensurate by same-basis / different-modality; see _CLAIM_B_ARM_BASIS (SK#1675)"
    ),
}

# The two direction arms `_claim_B` folds, each (card_id, field) → comparator BASIS. The set is what
# makes the fold commensurate: BOTH arms are 'matched_adjacent'. A re-pointed arm (a field NOT on this
# list) or a new undeclared arm changes this set and fails the commensurability test below.
_CLAIM_B_ARM_BASIS = {
    ("tumor-rna-vs-adjacent", "expression_call_class"): "matched_adjacent",
    ("tumor-protein-abundance-cptac", "protein_expression_class"): "matched_adjacent",
}

# The RNA card's tumor-vs-GTEx-POPULATION contrast fields — a DIFFERENT comparator basis, DISPLAY-ONLY
# (verdict-inert). They must NEVER be folded as a `_dir` direction arm (that would mix matched-adjacent
# with population, the #1673-class construct-mismatch). The mutation test re-points an arm to one of these.
_PRESENCE_POPULATION_FIELDS = frozenset({"gtex_log2_fc", "gtex_q_value"})

# The DECLARED oracle for presence's `corroboration_from_arms` callers (imported aliased as
# `_corr_from_arms`). Same contract as the genomic/selectivity families.
_DECLARED_PRESENCE_CORROBORATION_BUILDERS = {
    "_coverage_concordance_claim": (
        "single-cell within-tumour coverage arm × antigen-escape arm — BOTH orthogonal facets of the "
        "SAME single-cell malignant-coverage assay (tumor-scrna-celltype-expression); a same-assay "
        "corroboration, commensurate by construction"
    ),
    "_abundance_concordance_claim": (
        "primary-grain RNA×MS-protein magnitude concordance × the INDEPENDENT cross-grain read — "
        "GRAIN-ANCHORED (tumor RNA×CPTAC, or cell-line RNA×Gygi/ProCan), ALWAYS same-grain within an arm "
        "and compared on WITHIN-POPULATION rank CLASS not raw TMT-vs-TPM (#1512); the second grain is an "
        "independent cross-grain corroborating arm — commensurate by construction"
    ),
    "_subtype_restriction_concordance_claim": (
        "bulk-RNA-by-subtype subtype-restriction (recount3 TCGA, `tumor-rna-distribution-by-subtype`) × "
        "protein-MS-by-subtype subtype-restriction (CPTAC TMT, `tumor-protein-distribution-by-subtype`) — "
        "the two INDEPENDENT arms of the L2b subtype_restriction_concordance family (SK#1830). Two reads "
        "of the SAME subtype-restriction property at DIFFERENT molecular layers at the SAME patient-tumor "
        "grain and subtype axis (commensurate by same-property, cross-modality). The RNA arm is one arm "
        "supplied by a same-modality group {tumor_rna, cellline_rna}; cellline-RNA-by-subtype is "
        "corroboration-INELIGIBLE (a same-modality cross-grain sibling, never a third independent arm), so "
        "corroboration_from_arms folds EXACTLY [rna_arm, protein_arm] — never a cell-line RNA third arm."
    ),
    "_protein_presence_concordance_claim": (
        "antibody-IHC protein presence (HPA Pathology `hpa-pathology-cancer-ihc` per-patient staining "
        "distribution) × mass-spec protein presence (CPTAC TMT `tumor-protein-abundance-cptac`) — the two "
        "INDEPENDENT arms of the L2b protein_presence_concordance family (SK#1851). Two reads of the SAME "
        "protein-presence property at DIFFERENT detection TECHNOLOGIES (antibody immunostaining vs peptide "
        "mass-spectrometry), independent cohorts and independent failure modes — commensurate by same-"
        "property, cross-technology (MS presence read off the WITHIN-POPULATION rank CLASS, never a raw "
        "TMT-vs-IHC magnitude, #1512). The mass-spec arm is one arm supplied by a same-modality group "
        "{cptac_protein, gygi_protein, procan_protein}; DepMap-Gygi (`cellline-protein-abundance`) and "
        "ProCan (`cellline-protein-abundance-procan`) are corroboration-INELIGIBLE same-modality cross-"
        "grain siblings (all three are mass-spectrometry — ONE arm, never a second independent replication), "
        "so corroboration_from_arms folds EXACTLY [antibody_arm, mass_spec_arm] — never a cell-line MS "
        "third arm."
    ),
    "_tumor_presence_concordance_claim": (
        "bulk-RNA tumor presence (`tumor-rna-distribution.tumor_expression_class`, population-averaged "
        "transcriptome) × single-cell MALIGNANT-compartment presence "
        "(`tumor-scrna-celltype-expression.sc_expression_class`, per-cell resolution) × antibody-IHC "
        "protein presence (`hpa-pathology-cancer-ihc`, per-patient staining, reusing `_ihc_presence_call`) "
        "— the THREE INDEPENDENT arms of the HEADLINE L2b tumor_presence_integration family (SK#1867, the "
        "Arm-B prototype's central `tumor_presence = tumor_rna + sc_malignant + ihc` node). Three reads of "
        "the SAME tumor-presence property at DIFFERENT detection layers (population-averaged RNA vs single-"
        "cell malignant RNA vs antibody immunostaining), different grain and independent failure modes — "
        "commensurate by same-property, cross-source. Each arm is its OWN independent modality group; there "
        "are NO same-modality dependent siblings in this family, so corroboration_from_arms folds EXACTLY "
        "[bulk_rna_arm, sc_malignant_arm, antibody_ihc_arm] — three genuinely independent groups → HIGH "
        "corroboration when they agree."
    ),
}


def _presence_tree() -> ast.Module:
    return _parse(_PRESENCE_CLAIMS.read_text())


def _corr_from_arms_local_name(tree: ast.Module) -> str:
    """The local name that `corroboration_from_arms` is imported under in this module. presence aliases
    it (`from … import corroboration_from_arms as _corr_from_arms`); genomic/selectivity import it
    unaliased. Resolving the alias keeps the enumeration correct regardless of import style."""
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            for a in n.names:
                if a.name == "corroboration_from_arms":
                    return a.asname or a.name
    return "corroboration_from_arms"


def _presence_corroboration_builders(tree: ast.Module) -> set[str]:
    """Every function that folds arms via the (aliased) `corroboration_from_arms` in presence_claims.py."""
    local = _corr_from_arms_local_name(tree)
    return {name for name, fn in _functions(tree).items() if _calls_named(fn, local)}


def _card_aliases(func: ast.FunctionDef) -> dict[str, str]:
    """Map each local bound to `<name> = c.get("<card>", …)` → that card_id. `_claim_B` reads its arm
    cards through these locals (`tva = c.get("tumor-rna-vs-adjacent", {})`), so a `_dir` arg that reads
    the field THROUGH a local is resolved to its card."""
    aliases: dict[str, str] = {}
    for n in ast.walk(func):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            v = n.value
            if (
                isinstance(v, ast.Call)
                and isinstance(v.func, ast.Attribute)
                and v.func.attr == "get"
                and isinstance(v.func.value, ast.Name)
                and v.func.value.id == "c"
                and v.args
                and isinstance(v.args[0], ast.Constant)
                and isinstance(v.args[0].value, str)
            ):
                aliases[n.targets[0].id] = v.args[0].value
    return aliases


def _dir_call_count(func: ast.FunctionDef) -> int:
    return sum(
        1 for n in ast.walk(func) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_dir"
    )


def _direction_builders(tree: ast.Module) -> set[str]:
    """Every function that folds ≥2 direction arms via the presence `_dir(...)` primitive — the AST is
    the source of truth, so a newly-added manual multi-arm direction builder is DISCOVERED, not assumed."""
    return {name for name, fn in _functions(tree).items() if _dir_call_count(fn) >= 2}


def claim_b_direction_arms(func: ast.FunctionDef) -> set[tuple[str, str]]:
    """The (card_id, field) pairs `_claim_B` folds as direction arms: each `_dir(<alias>.get("<field>"))`
    resolved through the card aliases."""
    aliases = _card_aliases(func)
    arms: set[tuple[str, str]] = set()
    for n in ast.walk(func):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_dir" and n.args):
            continue
        arg = n.args[0]
        if (
            isinstance(arg, ast.Call)
            and isinstance(arg.func, ast.Attribute)
            and arg.func.attr == "get"
            and isinstance(arg.func.value, ast.Name)
            and arg.func.value.id in aliases
            and arg.args
            and isinstance(arg.args[0], ast.Constant)
            and isinstance(arg.args[0].value, str)
        ):
            arms.add((aliases[arg.func.value.id], arg.args[0].value))
    return arms


def assert_claim_b_arms_are_commensurate(tree: ast.Module) -> None:
    """Raise AssertionError unless `_claim_B` folds EXACTLY the declared commensurate matched-adjacent
    direction arms (`_CLAIM_B_ARM_BASIS`) — no incommensurate/population field pulled in, none dropped.
    The predicate the presence-family mutation test drives red."""
    funcs = _functions(tree)
    assert "_claim_B" in funcs, "_claim_B vanished from presence_claims.py"
    arms = claim_b_direction_arms(funcs["_claim_B"])
    declared = set(_CLAIM_B_ARM_BASIS)
    undeclared = arms - declared
    population = {f for (_card, f) in undeclared if f in _PRESENCE_POPULATION_FIELDS}
    assert arms == declared, (
        f"_claim_B folds direction arms {sorted(arms)} — expected EXACTLY the commensurate matched-"
        f"adjacent arm set {sorted(declared)}. An extra arm mixes a DIFFERENT comparator basis into the "
        f"tumor-elevation fold (a false agreement/conflict, the presence analogue of SK#1673); a missing "
        f"arm means an arm was dropped or renamed. undeclared = {sorted(undeclared)}"
        + (
            f" — INCLUDING the DISPLAY-ONLY population contrast {sorted(population)}: the tumor-vs-GTEx-"
            f"population reference is a different comparator basis and must never be a `_dir` direction arm"
            if population
            else ""
        )
        + f"; gone = {sorted(declared - arms)}."
    )


# ── the presence-family tests ─────────────────────────────────────────────────────────────────────
def test_presence_direction_builders_are_declared():
    """ENUMERATION / anti-drift for the presence DIRECTION family: every function folding ≥2 tumor-vs-
    normal arms via the `_dir(...)` primitive must be declared. A NEW manual multi-arm direction builder
    fails here until its arm pairing is declared in `_DECLARED_PRESENCE_DIRECTION_BUILDERS`."""
    discovered = _direction_builders(_presence_tree())
    declared = set(_DECLARED_PRESENCE_DIRECTION_BUILDERS)
    assert discovered == declared, (
        f"presence direction builders drifted from the declared oracle: "
        f"undeclared (add its arm pairing) = {sorted(discovered - declared)}; "
        f"declared-but-gone (remove it) = {sorted(declared - discovered)}"
    )


def test_presence_corroboration_builders_are_declared():
    """ENUMERATION / anti-drift for presence's `corroboration_from_arms` callers (imported ALIASED as
    `_corr_from_arms`). Every such builder must be declared, or this fails until its arm pairing is
    added to `_DECLARED_PRESENCE_CORROBORATION_BUILDERS`."""
    discovered = _presence_corroboration_builders(_presence_tree())
    declared = set(_DECLARED_PRESENCE_CORROBORATION_BUILDERS)
    assert discovered == declared, (
        f"presence multi-arm corroboration builders drifted from the declared oracle: "
        f"undeclared (add its arm pairing) = {sorted(discovered - declared)}; "
        f"declared-but-gone (remove it) = {sorted(declared - discovered)}"
    )


def test_claim_b_oracle_is_internally_same_comparator_basis():
    """The declared table itself encodes the commensurability rule: both `_claim_B` arms share the SAME
    comparator basis (matched-adjacent) and differ only by MODALITY. Guards the oracle against a typo
    that would make the whole detector assert the wrong pairing."""
    bases = set(_CLAIM_B_ARM_BASIS.values())
    assert bases == {"matched_adjacent"}, (
        f"the declared _claim_B arms must all be the SAME comparator basis (matched_adjacent); got {bases}"
    )
    cards = {card for (card, _f) in _CLAIM_B_ARM_BASIS}
    assert len(cards) == 2, (
        f"the two arms must be different-MODALITY cards (RNA vs protein), commensurate on basis but "
        f"independent measurements; got cards {sorted(cards)}"
    )
    # the display-only population fields must NOT be in the commensurate arm set (they are a different basis).
    assert not (_PRESENCE_POPULATION_FIELDS & {f for (_c, f) in _CLAIM_B_ARM_BASIS}), (
        "a tumor-vs-GTEx-population field leaked into the declared matched-adjacent arm set"
    )


def test_claim_b_folds_the_commensurate_matched_adjacent_arms():
    """GREEN on today's presence_claims.py: `_claim_B` folds exactly the two commensurate matched-adjacent
    direction arms. Also anti-vacuity — the declared arm set is non-empty."""
    assert _CLAIM_B_ARM_BASIS, "the declared _claim_B arm set is empty — the test would pin nothing"
    assert_claim_b_arms_are_commensurate(_presence_tree())


# The mutation the presence-family detector exists to catch: the RNA-DGE arm re-pointed from the matched-
# adjacent `expression_call_class` to the DISPLAY-ONLY tumor-vs-GTEx-POPULATION `gtex_log2_fc` — folding a
# population-basis contrast against the matched-adjacent CPTAC protein arm (incommensurate comparator
# bases, the presence analogue of #1673). Applied to a COPY of the source string, so the real module is
# never mutated.
def _mutant_claim_b_arm_repointed_to_gtex_population(source: str) -> str:
    mutated = source.replace('_dir(tva.get("expression_call_class"))', '_dir(tva.get("gtex_log2_fc"))')
    assert mutated != source, "mutation was a no-op — the matched-adjacent RNA arm is no longer present to re-point"
    return mutated


def test_detector_bites_a_claim_b_arm_repointed_to_the_population_contrast():
    """MUTATION TEST for the presence family — the corpus alone has no teeth here, so prove the detector
    bites. With the RNA-DGE arm re-pointed to the population `gtex_log2_fc` contrast (an incommensurate
    different-basis field), `_claim_B`'s direction-arm set no longer equals the declared matched-adjacent
    arms and `assert_claim_b_arms_are_commensurate` FAILS. Confirms both the RED (on the mutant) and — via
    `test_claim_b_folds_the_commensurate_matched_adjacent_arms` — the GREEN on real source."""
    mutant = _parse(_mutant_claim_b_arm_repointed_to_gtex_population(_PRESENCE_CLAIMS.read_text()))
    # sanity: the mutant genuinely re-points the RNA arm to the population field
    arms = claim_b_direction_arms(_functions(mutant)["_claim_B"])
    assert ("tumor-rna-vs-adjacent", "gtex_log2_fc") in arms and (
        "tumor-rna-vs-adjacent",
        "expression_call_class",
    ) not in arms, "the mutation did not re-point the RNA arm as intended"
    # …and the detector rejects it
    with pytest.raises(AssertionError, match="_claim_B"):
        assert_claim_b_arms_are_commensurate(mutant)


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# FOURTH FAMILY — the LITERATURE-CONTEXT corroboration builder in literature_context_claims.py (SK#1600)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# SK#1688/#1689/#1675 covered the GENOMIC / EXPRESSION-PROTEOMICS / PRESENCE families. literature-context
# is the Tier-1 literature family of the same audit. Unlike the selectivity/presence extensions (which
# proved COMMENSURATE by design), this family was a genuine FIX (#1600, the #1667 non-independent-arm
# shape):
#   `_corr` built its corroboration from `corroboration_from_arms([True, multi_disease_arm])`, where the
#   ONLY route to `high` was `n_diseases >= 3 AND tier == "strong"`. That "second arm" is NOT independent:
#   the card documents `paper_disease_mentions` is SUMMED over the `n_diseases` disease subtypes, so
#   n_diseases is the DENOMINATOR the volume was summed across — a component of the SAME europePMC read,
#   never an independent corroborating measurement. It also (a) rewarded pleiotropy that run.py's own
#   confidence caveat flags NEGATIVE (`_PLEIOTROPY_MIN_DISEASES=8`, the low-specificity TP53 pattern) and
#   (b) was cross-axis mis-wired (that VOLUME-scope field was the second arm for RECENCY and RELATION too).
#
# THE FIX (#1600): literature is a ONE-ARMED axis — a single corpus read has nothing INDEPENDENT to agree
# with — so `_corr` now folds `corroboration_from_arms([True])` and is capped at `single_arm`, mirroring
# translational_readiness_claims `_one_arm`. The COMMENSURABILITY invariant this block pins is therefore:
# `_corr` reads NO headline field as an arm (the declared commensurate arm set is EMPTY) and folds a single
# literal `True` arm. Re-introducing ANY headline-field second arm (the removed `n_diseases`, or any other)
# re-opens the non-independent double-count — the mutation test at the bottom drives exactly that red.
#
# SHAPE NOTE: the corroboration builder here is the FACTORY `_corr` (its inner closure calls
# `corroboration_from_arms`); `_functions`/`ast.walk` attribute the call to the enclosing `_corr`, which is
# how the fleet enumeration already discovers this file. This block edits ONLY the test file (the
# literature_context_claims.py fix lands in the same PR but is asserted, not authored, here).

_LITERATURE_CLAIMS = pathlib.Path(__file__).resolve().parents[1] / "literature_context_claims.py"


# The DECLARED oracle for the literature family. Same contract as the earlier families: every function
# that folds arms via `corroboration_from_arms` in literature_context_claims.py must appear here.
_DECLARED_LITERATURE_CORROBORATION_BUILDERS = {
    "_corr": (
        "the single europePMC co-occurrence read per axis (VOLUME/RECENCY/RELATION) — a ONE-ARMED axis "
        "capped at single_arm: one corpus read has nothing INDEPENDENT to agree with. NO headline field is "
        "folded as a second arm (see _LITERATURE_COMMENSURATE_ARM_FIELDS); #1600 removed the non-independent "
        "n_diseases arm (a sub-field of the SAME read, the #1667 shape); mirrors translational _one_arm"
    ),
}

# literature corroboration is a SINGLE-ARM axis, so the declared commensurate arm set is EMPTY: no headline
# field is an independent second arm (n_diseases is the denominator the volume was summed across). A
# re-pointed/re-added arm reads SOME headline field here and fails the commensurability assertion below.
_LITERATURE_COMMENSURATE_ARM_FIELDS = frozenset()


def _literature_tree() -> ast.Module:
    return _parse(_LITERATURE_CLAIMS.read_text())


def _corroboration_from_arms_calls(func: ast.FunctionDef) -> list[ast.Call]:
    """Every `corroboration_from_arms(...)` call anywhere in `func` (incl. its inner closures)."""
    return [
        n
        for n in ast.walk(func)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "corroboration_from_arms"
    ]


def assert_literature_is_single_arm(tree: ast.Module) -> None:
    """Raise AssertionError unless `_corr` is a genuine SINGLE-ARM fold: it reads NO headline field as an
    arm (the declared EMPTY commensurate set) and folds exactly one literal `True` arm. The predicate the
    literature-family mutation test drives red."""
    funcs = _functions(tree)
    assert "_corr" in funcs, "_corr vanished from literature_context_claims.py"
    corr = funcs["_corr"]
    # (a) no headline field is folded as a (non-independent) second arm.
    fields = _headline_fields_read(corr)
    assert fields == set(_LITERATURE_COMMENSURATE_ARM_FIELDS), (
        f"_corr reads headline fields {sorted(fields)} — expected NONE. literature corroboration is a "
        f"ONE-ARMED axis (one europePMC corpus read has nothing INDEPENDENT to agree with); folding ANY "
        f"headline field as a second arm re-opens the #1600 non-independent double-count (n_diseases is the "
        f"denominator paper_disease_mentions was summed across, a component of the SAME read — the #1667 "
        f"shape). undeclared = {sorted(fields - set(_LITERATURE_COMMENSURATE_ARM_FIELDS))}."
    )
    # (b) the fold is a single literal `True` arm → capped at single_arm.
    calls = _corroboration_from_arms_calls(corr)
    assert len(calls) == 1, f"_corr must fold arms in exactly one corroboration_from_arms call; found {len(calls)}"
    arg = calls[0].args[0] if calls[0].args else None
    is_single_true = (
        isinstance(arg, ast.List)
        and len(arg.elts) == 1
        and isinstance(arg.elts[0], ast.Constant)
        and arg.elts[0].value is True
    )
    assert is_single_true, (
        "_corr must fold `corroboration_from_arms([True])` — a single literal-True arm capped at "
        "single_arm. A multi-element arm list re-introduces a second arm (the #1600 non-independent "
        "n_diseases route or any other), which literature has no INDEPENDENT measurement to supply."
    )


# ── the literature-family tests ─────────────────────────────────────────────────────────────────────
def test_literature_multi_arm_builders_are_declared():
    """ENUMERATION / anti-drift for the literature family: every function that folds arms via
    `corroboration_from_arms` in literature_context_claims.py must be declared. A NEW multi-arm builder
    fails here until its arm pairing is declared in `_DECLARED_LITERATURE_CORROBORATION_BUILDERS`."""
    discovered = _corroboration_builders(_literature_tree())
    declared = set(_DECLARED_LITERATURE_CORROBORATION_BUILDERS)
    assert discovered == declared, (
        f"literature multi-arm corroboration builders drifted from the declared oracle: "
        f"undeclared (add its arm pairing) = {sorted(discovered - declared)}; "
        f"declared-but-gone (remove it) = {sorted(declared - discovered)}"
    )


def test_literature_corroboration_is_single_arm():
    """GREEN on today's literature_context_claims.py: `_corr` folds a single literal-True arm and reads no
    headline field as a second arm — a one-armed axis capped at single_arm (#1600)."""
    assert_literature_is_single_arm(_literature_tree())


# The mutation the literature detector exists to catch: the removed #1600 non-independent second arm
# (n_diseases, a sub-field of the SAME europePMC read) re-introduced into the fold. Applied to a COPY of
# the source string, so the real module is never mutated.
def _mutant_literature_readds_n_diseases_arm(source: str) -> str:
    mutated = source.replace(
        "return corroboration_from_arms([True])",
        'return corroboration_from_arms([True, (True if (h.get("n_diseases") or 0) >= 3 '
        'and tier == "strong" else None)])',
    )
    assert mutated != source, "mutation was a no-op — the single-arm fold is no longer present to re-point"
    return mutated


def test_detector_bites_a_readded_non_independent_n_diseases_arm():
    """MUTATION TEST for the literature family — the corpus alone has no teeth here, so prove the detector
    bites. With the non-independent n_diseases second arm re-introduced, `_corr` reads a headline field and
    folds a two-element arm list, so `assert_literature_is_single_arm` FAILS. Confirms both the RED (on the
    mutant) and — via `test_literature_corroboration_is_single_arm` — the GREEN on real source."""
    mutant = _parse(_mutant_literature_readds_n_diseases_arm(_LITERATURE_CLAIMS.read_text()))
    # sanity: the mutant genuinely re-adds the n_diseases arm
    assert "n_diseases" in _headline_fields_read(_functions(mutant)["_corr"]), (
        "the mutation did not re-introduce the n_diseases arm as intended"
    )
    # …and the detector rejects it
    with pytest.raises(AssertionError, match="_corr"):
        assert_literature_is_single_arm(mutant)


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# FIFTH FAMILY — the DEPENDENCY (essentiality-concordance) builder in dependency_claims.py (SK#1709)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# `_essentiality_concordance_claim` (L2b-2 #1533) folds `corroboration_from_arms([crispr_arm, rnai_arm])`,
# where each arm is the resolved direction of an ORTHOGONAL loss-of-function dependency screen:
#   * CRISPR — pan-cancer-crispr-dependency-distribution.dependency_class      (Chronos, Cas9 knockout)
#   * RNAi   — pan-cancer-rnai-dependency-distribution.rnai_dependency_class   (DEMETER2, shRNA knockdown)
#
# AUDIT VERDICT (SK#1709): COMMENSURATE by design — a detector-oracle EXTENSION, not a fix.
#   * SAME CONSTRUCT: both resolve gene essentiality (a dependency call) via the shared `_ess_resolve`
#     token→direction map; the fold agrees/disagrees on the SAME dependency question.
#   * SAME GRANULARITY: both are the PAN-CANCER dependency class per gene (not a subtype-scoped or
#     lineage-scoped read on one side and pan-cancer on the other).
#   * INDEPENDENT: two distinct DepMap datasets produced by two distinct perturbation platforms
#     (CRISPR/Cas9 knockout scored by Chronos vs RNAi/shRNA knockdown scored by DEMETER2). Neither arm is
#     a subset/superset of the other and neither is DERIVED from the other — they are the textbook pair of
#     orthogonal knockdown modalities of the same essentiality construct.
#   * MEASURED (no vote flip): two agreeing arms → corroboration `high`; a discordance → `low`; one
#     measured arm with the other unresolved → `single_arm`. The claim carries NO `signal` key, reads no
#     verdict and feeds no rule (VERDICT-INERT, key omitted/byte-stable when neither arm resolves). So this
#     declaration moves no decision.json — a pure detector extension.
# The commensurability invariant this block pins: `_essentiality_concordance_claim` folds EXACTLY the two
# declared dependency-distribution card/field arms — two DISTINCT independent-screen cards. Re-pointing one
# arm to read the OTHER arm's card (a subset / one-derived-from-the-other relationship, collapsing the two
# independent modalities into one) reds the commensurability assertion; the mutation test drives that red.

_DEPENDENCY_CLAIMS = pathlib.Path(__file__).resolve().parents[1] / "dependency_claims.py"


# The DECLARED oracle for the dependency family. Same contract as the earlier families: every function
# that folds arms via `corroboration_from_arms` in dependency_claims.py must appear here with its pairing.
_DECLARED_DEPENDENCY_CORROBORATION_BUILDERS = {
    "_essentiality_concordance_claim": (
        "CRISPR `dependency_class` (Chronos/Cas9-KO) × RNAi `rnai_dependency_class` (DEMETER2/shRNA-KD) — "
        "two INDEPENDENT orthogonal loss-of-function screen modalities of the SAME pan-cancer essentiality "
        "construct at the SAME granularity; neither a subset/superset nor derived from the other "
        "(commensurate by same-construct/same-granularity/independent; see _DEPENDENCY_COMMENSURATE_ARM_PAIRS)"
    ),
}

# The (card_id, field) arms the fold reads. Two DISTINCT dependency-distribution cards — the set is what
# makes the two arms commensurate-yet-independent. A re-pointed arm (an arm reading the OTHER card, or a
# card that is not a dependency-distribution read) changes this set and fails the assertion below.
_DEPENDENCY_COMMENSURATE_ARM_PAIRS = frozenset(
    {
        ("pan-cancer-crispr-dependency-distribution", "dependency_class"),
        ("pan-cancer-rnai-dependency-distribution", "rnai_dependency_class"),
    }
)


def _dependency_tree() -> ast.Module:
    return _parse(_DEPENDENCY_CLAIMS.read_text())


def _card_field_get_pairs(func: ast.FunctionDef) -> set[tuple[str, str]]:
    """Every `(c.get("<card>") or {}).get("<field>")` arm read in `func` → {(card_id, field)}. The
    dependency builder reads its arms from the CARD dict `c` (not the headline `h`), unwrapping the
    `… or {}` guard, so this resolves the (card, field) pair each arm is scored from."""
    pairs: set[tuple[str, str]] = set()
    for n in ast.walk(func):
        if not (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "get"
            and n.args
            and isinstance(n.args[0], ast.Constant)
            and isinstance(n.args[0].value, str)
        ):
            continue
        field = n.args[0].value
        obj = n.func.value
        if isinstance(obj, ast.BoolOp) and isinstance(obj.op, ast.Or) and obj.values:
            obj = obj.values[0]  # unwrap `(<inner> or {})`
        if (
            isinstance(obj, ast.Call)
            and isinstance(obj.func, ast.Attribute)
            and obj.func.attr == "get"
            and isinstance(obj.func.value, ast.Name)
            and obj.func.value.id == "c"
            and obj.args
            and isinstance(obj.args[0], ast.Constant)
            and isinstance(obj.args[0].value, str)
        ):
            pairs.add((obj.args[0].value, field))
    return pairs


def assert_dependency_arms_are_commensurate(tree: ast.Module) -> None:
    """Raise AssertionError unless `_essentiality_concordance_claim` folds EXACTLY the declared two
    dependency-distribution card/field arms — no incommensurate card pulled in, none dropped, and the two
    arms read two DISTINCT independent-screen cards. The predicate the dependency-family mutation drives red."""
    funcs = _functions(tree)
    assert "_essentiality_concordance_claim" in funcs, (
        "_essentiality_concordance_claim vanished from dependency_claims.py"
    )
    pairs = _card_field_get_pairs(funcs["_essentiality_concordance_claim"])
    declared = set(_DEPENDENCY_COMMENSURATE_ARM_PAIRS)
    assert pairs == declared, (
        f"_essentiality_concordance_claim folds card/field arms {sorted(pairs)} — expected EXACTLY the two "
        f"commensurate orthogonal-screen arms {sorted(declared)}. An arm reading a DIFFERENT card mixes an "
        f"incommensurate construct into the essentiality fold, and an arm reading the OTHER arm's card "
        f"collapses the two independent modalities into one (a subset/one-derived-from-the-other double-"
        f"count, the #1667 shape). undeclared = {sorted(pairs - declared)}; gone = {sorted(declared - pairs)}."
    )


# ── the dependency-family tests ───────────────────────────────────────────────────────────────────
def test_dependency_multi_arm_builders_are_declared():
    """ENUMERATION / anti-drift for the dependency family: every function that folds arms via
    `corroboration_from_arms` in dependency_claims.py must be declared. A NEW multi-arm builder fails here
    until its arm pairing is declared in `_DECLARED_DEPENDENCY_CORROBORATION_BUILDERS`."""
    discovered = _corroboration_builders(_dependency_tree())
    declared = set(_DECLARED_DEPENDENCY_CORROBORATION_BUILDERS)
    assert discovered == declared, (
        f"dependency multi-arm corroboration builders drifted from the declared oracle: "
        f"undeclared (add its arm pairing) = {sorted(discovered - declared)}; "
        f"declared-but-gone (remove it) = {sorted(declared - discovered)}"
    )


def test_dependency_oracle_is_two_independent_screen_modalities():
    """The declared table itself encodes the commensurability rule: the two arms are two DISTINCT
    dependency-distribution cards (independent screens), same essentiality construct. Guards the oracle
    against a typo that would make the detector assert the wrong pairing (e.g. one card read twice)."""
    cards = {card for (card, _f) in _DEPENDENCY_COMMENSURATE_ARM_PAIRS}
    assert len(cards) == 2, (
        f"the two dependency arms must read two DISTINCT independent-screen cards (CRISPR vs RNAi), not one "
        f"card twice (which would be a subset/one-derived double-count); got cards {sorted(cards)}"
    )
    assert all("dependency-distribution" in card for card in cards), (
        f"both dependency arms must read a dependency-distribution card (the SAME essentiality construct); "
        f"got {sorted(cards)}"
    )


def test_dependency_folds_the_commensurate_essentiality_arms():
    """GREEN on today's dependency_claims.py: `_essentiality_concordance_claim` folds exactly the two
    commensurate orthogonal-screen arms. Also anti-vacuity — the declared arm set is non-empty."""
    assert _DEPENDENCY_COMMENSURATE_ARM_PAIRS, "the declared dependency arm set is empty — the test would pin nothing"
    assert_dependency_arms_are_commensurate(_dependency_tree())


# The mutation the dependency detector exists to catch: the RNAi arm re-pointed to read the SAME CRISPR
# dependency card — collapsing the two independent screen modalities into one card (a subset/one-derived-
# from-the-other relationship, the #1667 shape). Applied to a COPY of the source string.
def _mutant_dependency_repoints_rnai_arm_to_crispr_card(source: str) -> str:
    mutated = source.replace(
        'c.get("pan-cancer-rnai-dependency-distribution")',
        'c.get("pan-cancer-crispr-dependency-distribution")',
    )
    assert mutated != source, "mutation was a no-op — the RNAi arm card read is no longer present to re-point"
    return mutated


def test_detector_bites_a_dependency_arm_repointed_to_the_other_screen_card():
    """MUTATION TEST for the dependency family — the corpus alone has no teeth here, so prove the detector
    bites. With the RNAi arm re-pointed to the CRISPR card, the folded card set collapses to a single
    dependency card (the two independent modalities become one — a subset/one-derived double-count) and
    `assert_dependency_arms_are_commensurate` FAILS. Confirms both the RED (on the mutant) and — via
    `test_dependency_folds_the_commensurate_essentiality_arms` — the GREEN on real source."""
    mutant = _parse(_mutant_dependency_repoints_rnai_arm_to_crispr_card(_DEPENDENCY_CLAIMS.read_text()))
    # sanity: the mutant genuinely collapses the two arms onto one card
    pairs = _card_field_get_pairs(_functions(mutant)["_essentiality_concordance_claim"])
    cards = {card for (card, _f) in pairs}
    assert cards == {"pan-cancer-crispr-dependency-distribution"}, "the mutation did not collapse the arms as intended"
    # …and the detector rejects it
    with pytest.raises(AssertionError, match="_essentiality_concordance_claim"):
        assert_dependency_arms_are_commensurate(mutant)


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# SIXTH FAMILY — the SAFETY (normal-tissue liability quorum) builder in safety_claims.py (SK#1709)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# `_normal_liability_concordance_claim` (L2b-3 #1546) folds `corroboration_from_arms([_arm(sk) for sk, *_
# in _LIAB_SOURCES])` — a THREE-source normal-tissue safety-liability quorum, one arm per source in the
# module constant `_LIAB_SOURCES`:
#   * GTEx bulk RNA   — normal-tissue-liability-gtex.liability_class                  (pooled tissue transcriptome)
#   * scRNA cell-type — sc-normal-celltype-expression.sc_normal_safety_essential_class (single-cell atlas)
#   * HPA-IHC protein — normal-tissue-liability.essential_tissue_flag                 (antibody protein staining)
#
# AUDIT VERDICT (SK#1709): COMMENSURATE by design — a detector-oracle EXTENSION, not a fix — and the
# #1673 "quorum over non-commensurate modalities manufactures agreement" concern was ACTIVELY AVOIDED at
# field-selection time (documented in the source, not stumbled into):
#   * SAME CONSTRUCT: each source resolves a CRITICAL-ORGAN / essential-tissue normal-safety-liability
#     DIRECTION (high / clean / None-abstain) via `_liab_direction`. The fold agrees/disagrees on the SAME
#     organ-aware liability question.
#   * GRANULARITY reconciled, not conflated: the three sources are DIFFERENT modalities (bulk vs single-
#     cell vs protein-IHC), but each was DELIBERATELY mapped to the SAME organ-aware categorical basis. The
#     scRNA arm uses the categorical `sc_normal_safety_essential_class` (`{critical_organ_liability}`→high,
#     `{none}`→clean) — the direct organ-aware analogue of the GTEx/HPA categorical calls — NOT the broader
#     breadth field (which fired 'high' on detection in ANY normal cell type, incl. non-critical/origin
#     epithelium, a SYSTEMATICALLY BROADER basis that would MANUFACTURE (dis)concordance) and NOT the
#     graded veto sibling `sc_normal_essential_veto_grade` (which folds SEVERITY into the token). The
#     abstain semantics are likewise aligned (scRNA `origin_tissue_liability` ABSTAINS, matching what GTEx/
#     HPA can resolve) so a source never votes on a call the others cannot make. This is the same
#     "same-basis, different-measurement" multi-modal quorum as the selectivity family (#1689).
#   * INDEPENDENT: three genuinely independent data sources/assays (GTEx consortium bulk RNA-seq, a single-
#     cell normal atlas, HPA antibody IHC); none derived from another.
#   * MEASURED (no vote flip): ≥2 agreeing → corroboration `high`; any cross-source disagreement → `low`;
#     one measured arm → `single_arm`. VERDICT-INERT — no `signal` key, reads no verdict, feeds no rule;
#     the scRNA arm reads a DISPLAY class (`sc_normal_safety_essential_class`, SK#1575) that no rule keys
#     on for any axis, and the sc-normal veto is not a safety.resolver rung — so both the scalar and per-
#     modality safety verdicts stay byte-stable. This declaration moves no decision.json.
# The commensurability invariant this block pins: the fold folds EXACTLY the three declared source
# card/field arms (`_LIAB_SOURCES`, resolved statically), and the builder folds over `_LIAB_SOURCES`. Re-
# pointing the scRNA arm to the graded-veto (or breadth) field the author explicitly rejected — the #1673
# shape — changes the source set and reds the assertion; the mutation test drives exactly that red.

_SAFETY_CLAIMS = pathlib.Path(__file__).resolve().parents[1] / "safety_claims.py"


# The DECLARED oracle for the safety family. Same contract: every function folding arms via
# `corroboration_from_arms` in safety_claims.py must appear here with its pairing.
_DECLARED_SAFETY_CORROBORATION_BUILDERS = {
    "_normal_liability_concordance_claim": (
        "GTEx-bulk `liability_class` × scRNA-normal `sc_normal_safety_essential_class` × HPA-IHC "
        "`essential_tissue_flag` — three INDEPENDENT normal-tissue reads of the SAME organ-aware critical-"
        "organ liability construct, each mapped to the SAME organ-aware categorical basis (the scRNA arm "
        "uses the categorical class, NOT the broader breadth field nor the graded veto — the #1673 "
        "manufactured-agreement shape was actively avoided); commensurate by same-construct/same-basis/"
        "independent, one multi-modal quorum (see _SAFETY_COMMENSURATE_SOURCE_ARMS)"
    ),
}

# The (card_id, field) source arms the quorum reads, from the `_LIAB_SOURCES` module constant. The set is
# what makes the three-modality quorum commensurate: each arm is an organ-aware liability read at a
# DIFFERENT modality. A re-pointed arm (e.g. the scRNA arm on the broader breadth / graded-veto field) or a
# new/dropped source changes this set and fails the assertion below.
_SAFETY_COMMENSURATE_SOURCE_ARMS = frozenset(
    {
        ("normal-tissue-liability-gtex", "liability_class"),  # GTEx bulk RNA — pooled tissue transcriptome
        ("sc-normal-celltype-expression", "sc_normal_safety_essential_class"),  # scRNA cell-type atlas
        ("normal-tissue-liability", "essential_tissue_flag"),  # HPA-IHC protein staining
    }
)


def _safety_tree() -> ast.Module:
    return _parse(_SAFETY_CLAIMS.read_text())


def _liab_sources_pairs(tree: ast.Module) -> set[tuple[str, str]]:
    """Static-read the `_LIAB_SOURCES` module constant → {(card_id, field)} (indices 3,4 of each 5-tuple
    `(source_key, property, assay, card_id, field)`). The safety quorum reads its arms by iterating this
    constant, so it — not a literal `.get` in the builder — is the arm source of truth."""
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_LIAB_SOURCES" for t in n.targets):
            tup = n.value
            assert isinstance(tup, ast.Tuple), "_LIAB_SOURCES is no longer a tuple literal"
            pairs: set[tuple[str, str]] = set()
            for elt in tup.elts:
                assert isinstance(elt, ast.Tuple) and len(elt.elts) == 5, (
                    "each _LIAB_SOURCES entry must be a 5-tuple (source_key, property, assay, card_id, field)"
                )
                cid, field = elt.elts[3], elt.elts[4]
                assert (
                    isinstance(cid, ast.Constant)
                    and isinstance(cid.value, str)
                    and isinstance(field, ast.Constant)
                    and isinstance(field.value, str)
                ), "the card_id/field of a _LIAB_SOURCES entry must be string constants"
                pairs.add((cid.value, field.value))
            return pairs
    raise AssertionError("_LIAB_SOURCES constant not found in safety_claims.py")


def _folds_over_liab_sources(func: ast.FunctionDef) -> bool:
    """True if `func` folds `corroboration_from_arms([… for … in _LIAB_SOURCES])` — the arms iterate the
    declared source constant, tying the fold to `_SAFETY_COMMENSURATE_SOURCE_ARMS`."""
    for n in ast.walk(func):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "corroboration_from_arms":
            arg = n.args[0] if n.args else None
            if isinstance(arg, ast.ListComp):
                for gen in arg.generators:
                    if isinstance(gen.iter, ast.Name) and gen.iter.id == "_LIAB_SOURCES":
                        return True
    return False


def assert_safety_arms_are_commensurate(tree: ast.Module) -> None:
    """Raise AssertionError unless the safety quorum folds EXACTLY the three declared source card/field
    arms (from `_LIAB_SOURCES`) and the builder folds over `_LIAB_SOURCES`. The predicate the safety-family
    mutation drives red."""
    funcs = _functions(tree)
    assert "_normal_liability_concordance_claim" in funcs, (
        "_normal_liability_concordance_claim vanished from safety_claims.py"
    )
    assert _folds_over_liab_sources(funcs["_normal_liability_concordance_claim"]), (
        "_normal_liability_concordance_claim no longer folds corroboration_from_arms over _LIAB_SOURCES — "
        "the arm source is no longer the declared source constant"
    )
    pairs = _liab_sources_pairs(tree)
    declared = set(_SAFETY_COMMENSURATE_SOURCE_ARMS)
    assert pairs == declared, (
        f"the normal-tissue liability quorum folds source arms {sorted(pairs)} — expected EXACTLY the three "
        f"commensurate organ-aware source arms {sorted(declared)}. Re-pointing a source arm to a broader-"
        f"basis field (e.g. the scRNA breadth field or the graded veto `sc_normal_essential_veto_grade`) "
        f"mixes a DIFFERENT basis into the quorum and MANUFACTURES agreement (the #1673 shape); a new/"
        f"dropped source changes the quorum. undeclared = {sorted(pairs - declared)}; "
        f"gone = {sorted(declared - pairs)}."
    )


# ── the safety-family tests ───────────────────────────────────────────────────────────────────────
def test_safety_multi_arm_builders_are_declared():
    """ENUMERATION / anti-drift for the safety family: every function that folds arms via
    `corroboration_from_arms` in safety_claims.py must be declared. A NEW multi-arm builder fails here
    until its arm pairing is declared in `_DECLARED_SAFETY_CORROBORATION_BUILDERS`."""
    discovered = _corroboration_builders(_safety_tree())
    declared = set(_DECLARED_SAFETY_CORROBORATION_BUILDERS)
    assert discovered == declared, (
        f"safety multi-arm corroboration builders drifted from the declared oracle: "
        f"undeclared (add its arm pairing) = {sorted(discovered - declared)}; "
        f"declared-but-gone (remove it) = {sorted(declared - discovered)}"
    )


def test_safety_oracle_is_three_independent_modalities_same_construct():
    """The declared table itself encodes the commensurability rule: three DISTINCT cards (independent
    modalities), each a normal-tissue liability read. Guards the oracle against a typo that would make the
    detector assert the wrong pairing."""
    cards = {card for (card, _f) in _SAFETY_COMMENSURATE_SOURCE_ARMS}
    assert len(cards) == 3, (
        f"the safety quorum must read three DISTINCT independent-modality cards (GTEx-bulk / scRNA / HPA-"
        f"IHC), not fewer; got cards {sorted(cards)}"
    )
    # the deliberately-rejected broader-basis fields must NOT be in the declared arm set.
    rejected = {"sc_normal_essential_veto_grade"}
    assert not (rejected & {f for (_c, f) in _SAFETY_COMMENSURATE_SOURCE_ARMS}), (
        "a deliberately-rejected broader-basis field (the graded veto) leaked into the declared quorum arms"
    )


def test_safety_folds_the_commensurate_source_arms():
    """GREEN on today's safety_claims.py: the quorum folds exactly the three commensurate organ-aware
    source arms and folds over `_LIAB_SOURCES`. Also anti-vacuity — the declared arm set is non-empty."""
    assert _SAFETY_COMMENSURATE_SOURCE_ARMS, "the declared safety arm set is empty — the test would pin nothing"
    assert_safety_arms_are_commensurate(_safety_tree())


# The mutation the safety detector exists to catch: the scRNA arm re-pointed from the organ-aware
# categorical `sc_normal_safety_essential_class` to the graded veto `sc_normal_essential_veto_grade` — the
# broader/severity basis the author explicitly rejected because it would MANUFACTURE cross-source
# (dis)concordance (the #1673 shape). Applied to a COPY of the source string.
def _mutant_safety_repoints_sc_arm_to_graded_veto(source: str) -> str:
    mutated = source.replace("sc_normal_safety_essential_class", "sc_normal_essential_veto_grade")
    assert mutated != source, "mutation was a no-op — the scRNA categorical arm field is no longer present to re-point"
    return mutated


def test_detector_bites_a_safety_arm_repointed_to_the_rejected_basis():
    """MUTATION TEST for the safety family — the corpus alone has no teeth here, so prove the detector
    bites. With the scRNA arm re-pointed to the graded veto (a broader/severity basis that manufactures
    agreement, the #1673 shape the author avoided), the folded source set no longer equals the declared
    organ-aware arms and `assert_safety_arms_are_commensurate` FAILS. Confirms both the RED (on the mutant)
    and — via `test_safety_folds_the_commensurate_source_arms` — the GREEN on real source."""
    mutant = _parse(_mutant_safety_repoints_sc_arm_to_graded_veto(_SAFETY_CLAIMS.read_text()))
    # sanity: the mutant genuinely re-points the scRNA arm to the rejected field
    pairs = _liab_sources_pairs(mutant)
    assert ("sc-normal-celltype-expression", "sc_normal_essential_veto_grade") in pairs and (
        "sc-normal-celltype-expression",
        "sc_normal_safety_essential_class",
    ) not in pairs, "the mutation did not re-point the scRNA arm as intended"
    # …and the detector rejects it
    with pytest.raises(AssertionError, match="liability quorum"):
        assert_safety_arms_are_commensurate(mutant)


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# SEVENTH FAMILY — the COMBINATION (CODEP co-dependency) builder in combination_vulnerability_claims.py (SK#1709)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# `_codep_corroboration` folds `corroboration_from_arms([True, dede, in4mer])` (mirrors genomic
# `_cn_corroboration`): the PRIMARY DepMap ParalogV2 paralog-SL call is the `True` arm, and the two
# orthogonal paralog dual-KO consortia are the 2nd/3rd arms:
#   * dede   — cross-consortium-paralog-gi.dede_class    (Dede consortium, zdLFC scoring)
#   * in4mer — cross-consortium-paralog-gi.in4mer_class  (in4mer consortium, normZ scoring)
#
# AUDIT VERDICT (SK#1709): COMMENSURATE by design — a detector-oracle EXTENSION, not a fix. The two audit
# concerns the #1703 filing rule flags are both ANSWERED negative:
#   * The `True` first arm is NOT an inflating free sentinel. The fold is REACHED only after an early
#     return gate: `_codep_corroboration` returns `unmeasured`/`single_arm` and NEVER reaches
#     `corroboration_from_arms` unless the DepMap `combinatorial_dependency_class` is already a POSITIVE
#     (paralog-SL) `strong`/`moderate` call. So `True` encodes the CONFIRMED primary positive arm at this
#     path — exactly like the `_cn_corroboration` primary. With both consortia absent it stands as `[True]`
#     → `single_arm` (no inflation); one agreeing consortium lifts to `high`; a suppressive/no-interaction
#     consortium caps at `low`.
#   * dede and in4mer are NOT the same underlying signal. They are two SEPARATE consortia with DIFFERENT
#     scoring methods (Dede/zdLFC vs in4mer/normZ), read from two DISTINCT fields, both resolving the SAME
#     paralog-SL interaction_class construct at the SAME granularity via the shared `arm_from_class`
#     vocabulary — independent orthogonal reads, not one derived from the other.
#   * MEASURED (no vote flip for this declaration): this PR edits only the test file; `_codep_corroboration`
#     is unchanged, so the corroboration tier is byte-stable. (The tier is a confidence dimension, not the
#     signal chip.)
# The commensurability invariant this block pins: the fold reads EXACTLY the two DISTINCT declared
# consortium fields and folds EXACTLY ONE literal-`True` primary arm (no extra inflating sentinel). Re-
# pointing in4mer to read dede's field (collapsing the two independent consortia into one — a double-count)
# reds the assertion; the mutation test drives that red.

_COMBINATION_CLAIMS = pathlib.Path(__file__).resolve().parents[1] / "combination_vulnerability_claims.py"


# The DECLARED oracle for the combination family. Same contract: every function folding arms via
# `corroboration_from_arms` in combination_vulnerability_claims.py must appear here with its pairing.
_DECLARED_COMBINATION_CORROBORATION_BUILDERS = {
    "_codep_corroboration": (
        "PRIMARY DepMap ParalogV2 paralog-SL call (`True`, reached ONLY for a positive strong/moderate "
        "combinatorial_dependency_class — a confirmed arm, not an inflating sentinel) × Dede `dede_class` "
        "(zdLFC) × in4mer `in4mer_class` (normZ) — two INDEPENDENT orthogonal consortia (different scoring, "
        "distinct fields) resolving the SAME paralog-SL interaction_class construct; commensurate by same-"
        "construct/same-granularity/independent (see _COMBINATION_CONSORTIUM_ARM_FIELDS)"
    ),
}

# The two consortium arm fields the fold reads via `xc.get("<field>")`. Two DISTINCT fields — the set is
# what makes the two orthogonal-consortium arms independent. Re-pointing one arm to the other's field
# collapses them to one (a double-count) and changes this set, failing the assertion below.
_COMBINATION_CONSORTIUM_ARM_FIELDS = frozenset({"dede_class", "in4mer_class"})


def _combination_tree() -> ast.Module:
    return _parse(_COMBINATION_CLAIMS.read_text())


def _xc_get_fields(func: ast.FunctionDef) -> set[str]:
    """Every `xc.get("<field>")` string read in `func` — the consortium arms are read from the dispatched
    cross-consortium card bound to the local `xc`."""
    found: set[str] = set()
    for n in ast.walk(func):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "get"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "xc"
            and n.args
            and isinstance(n.args[0], ast.Constant)
            and isinstance(n.args[0].value, str)
        ):
            found.add(n.args[0].value)
    return found


def _corroboration_arm_list(func: ast.FunctionDef) -> ast.List:
    """The single `corroboration_from_arms([...])` list argument in `func`."""
    calls = _corroboration_from_arms_calls(func)
    assert len(calls) == 1, f"expected exactly one corroboration_from_arms call in {func.name}; found {len(calls)}"
    arg = calls[0].args[0] if calls[0].args else None
    assert isinstance(arg, ast.List), "corroboration_from_arms is no longer folded over a list literal of arms"
    return arg


def assert_combination_arms_are_commensurate(tree: ast.Module) -> None:
    """Raise AssertionError unless `_codep_corroboration` folds EXACTLY ONE literal-`True` primary arm plus
    the two DISTINCT declared consortium fields — no inflating extra sentinel, no consortium double-count.
    The predicate the combination-family mutation drives red."""
    funcs = _functions(tree)
    assert "_codep_corroboration" in funcs, "_codep_corroboration vanished from combination_vulnerability_claims.py"
    corr = funcs["_codep_corroboration"]
    # (a) exactly one literal-True primary arm (the confirmed DepMap call), not an inflating sentinel.
    arm_list = _corroboration_arm_list(corr)
    n_true = sum(1 for e in arm_list.elts if isinstance(e, ast.Constant) and e.value is True)
    assert n_true == 1, (
        f"_codep_corroboration must fold EXACTLY ONE literal-`True` primary arm (the confirmed DepMap "
        f"paralog-SL call, reached only on a positive strong/moderate call); found {n_true} literal-True "
        f"arms. More than one would INFLATE the quorum with a free sentinel vote."
    )
    # (b) the consortium arms read exactly the two DISTINCT declared fields (independent, no double-count).
    fields = _xc_get_fields(corr)
    declared = set(_COMBINATION_CONSORTIUM_ARM_FIELDS)
    assert fields == declared, (
        f"_codep_corroboration folds consortium arm fields {sorted(fields)} — expected EXACTLY the two "
        f"DISTINCT orthogonal-consortium fields {sorted(declared)}. Re-pointing one arm to the OTHER "
        f"consortium's field collapses the two independent reads into one (a double-count of the SAME "
        f"signal); a new/dropped field changes the quorum. undeclared = {sorted(fields - declared)}; "
        f"gone = {sorted(declared - fields)}."
    )


# ── the combination-family tests ────────────────────────────────────────────────────────────────────
def test_combination_multi_arm_builders_are_declared():
    """ENUMERATION / anti-drift for the combination family: every function that folds arms via
    `corroboration_from_arms` in combination_vulnerability_claims.py must be declared. A NEW multi-arm
    builder fails here until its arm pairing is declared in `_DECLARED_COMBINATION_CORROBORATION_BUILDERS`."""
    discovered = _corroboration_builders(_combination_tree())
    declared = set(_DECLARED_COMBINATION_CORROBORATION_BUILDERS)
    assert discovered == declared, (
        f"combination multi-arm corroboration builders drifted from the declared oracle: "
        f"undeclared (add its arm pairing) = {sorted(discovered - declared)}; "
        f"declared-but-gone (remove it) = {sorted(declared - discovered)}"
    )


def test_combination_oracle_is_two_independent_consortia():
    """The declared table itself encodes the commensurability rule: two DISTINCT consortium fields
    (independent orthogonal reads). Guards the oracle against a typo (e.g. one field twice)."""
    assert len(_COMBINATION_CONSORTIUM_ARM_FIELDS) == 2, (
        f"the two consortium arms must read two DISTINCT fields (Dede vs in4mer), not one field twice (a "
        f"double-count of the SAME signal); got {sorted(_COMBINATION_CONSORTIUM_ARM_FIELDS)}"
    )


def test_combination_folds_the_primary_and_two_consortium_arms():
    """GREEN on today's combination_vulnerability_claims.py: `_codep_corroboration` folds one literal-True
    primary arm and the two commensurate consortium fields. Also anti-vacuity — the declared set is non-empty."""
    assert _COMBINATION_CONSORTIUM_ARM_FIELDS, "the declared combination consortium set is empty — pins nothing"
    assert_combination_arms_are_commensurate(_combination_tree())


# The mutation the combination detector exists to catch: the in4mer arm re-pointed to read dede's field —
# collapsing the two independent consortia into one (a double-count of the SAME signal). Applied to a COPY
# of the source string.
def _mutant_combination_repoints_in4mer_to_dede_field(source: str) -> str:
    mutated = source.replace('xc.get("in4mer_class")', 'xc.get("dede_class")')
    assert mutated != source, "mutation was a no-op — the in4mer consortium arm read is no longer present to re-point"
    return mutated


def test_detector_bites_a_combination_arm_repointed_to_the_other_consortium():
    """MUTATION TEST for the combination family — the corpus alone has no teeth here, so prove the detector
    bites. With the in4mer arm re-pointed to dede's field, the folded consortium field set collapses to one
    (the two independent reads become one — a double-count) and `assert_combination_arms_are_commensurate`
    FAILS. Confirms both the RED (on the mutant) and — via
    `test_combination_folds_the_primary_and_two_consortium_arms` — the GREEN on real source."""
    mutant = _parse(_mutant_combination_repoints_in4mer_to_dede_field(_COMBINATION_CLAIMS.read_text()))
    # sanity: the mutant genuinely collapses the two consortium arms onto one field
    fields = _xc_get_fields(_functions(mutant)["_codep_corroboration"])
    assert fields == {"dede_class"}, "the mutation did not collapse the consortium arms as intended"
    # …and the detector rejects it
    with pytest.raises(AssertionError, match="_codep_corroboration"):
        assert_combination_arms_are_commensurate(mutant)


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# EIGHTH FAMILY — the CIS-COHERENCE (cis-dosage cross-grain) builder in cis_coherence_claims.py (SK#1781)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# `_cis_dosage_concordance_claim` (L2b #1781, epic #1779; protein arm SK#1783) folds
# `corroboration_from_arms([cellline_arm, patient_arm])` over the SAME cis-dosage-coupling property, plus a
# THIRD same-grain MODALITY arm (protein) surfaced as graded corroboration. The arms:
#   * cell-line MODEL grain, bulk-RNA — cis-feature-expression-coherence.cis_dosage_class    (DepMap panel)
#   * patient TUMOUR grain, bulk-RNA  — patient-cis-coherence.patient_cis_dosage_class       (TCGA cohort)
#   * cell-line MODEL grain, MS-protein — cis-feature-protein-coherence.cis_protein_dosage_class (DepMap-Gygi)
#     (independent by MODALITY only — SAME cell-line grain/dependence_group as the RNA arm, NOT a third
#     independent grain-replicate; a DISTINCT card, not a re-read of the RNA card)
#
# AUDIT VERDICT (SK#1781): COMMENSURATE by design — a detector-oracle EXTENSION (first cis-domain family).
#   * SAME CONSTRUCT: both resolve the SAME cis-dosage-coupling property (does the target's copy number
#     drive its own expression?) via the SAME `compute_cis_dosage` kernel and the SAME shared token
#     vocabulary; the fold agrees/disagrees on the SAME cis-coupling question.
#   * SAME GRANULARITY, DIFFERENT GRAIN (first-class): each arm is the per-target cis-dosage class — one at
#     the cell-line MODEL grain, one at the patient TUMOUR grain. Grain is a FIRST-CLASS axis, recorded in
#     source_support[].grain; a same-grain restatement would NOT be a second arm. The patient amplified
#     edge (GISTIC +1) is coarser than the cell-line focal-amp cut, so the arms are comparable in
#     DIRECTION not thresholds — carried in provenance.independence_note.
#   * INDEPENDENT: two genuinely distinct sample contexts (DepMap cell-line panel vs TCGA patient cohort);
#     neither arm is a subset/superset of the other and neither is DERIVED from the other.
#   * MEASURED (no vote flip): two agreeing grains → `high`; a grain discordance → `low`; one measured
#     grain with the other unresolved → `single_arm`. Carries NO `signal` key, reads no verdict, feeds no
#     rule (VERDICT-INERT, key omitted/byte-stable when neither grain resolves). Declaration moves no
#     decision.json — a pure detector extension.
# The commensurability invariant this block pins: `_cis_dosage_concordance_claim` folds EXACTLY the three
# declared card/field arms — three DISTINCT cis-coherence cards across two grains. Re-pointing the patient
# arm to the cell-line card (collapsing two independent GRAINS into one — the #1667 shape) OR re-pointing
# the protein arm to the RNA card (collapsing the distinct MODALITY into a same-card double-count) reds the
# commensurability assertion; the two mutation tests drive those reds.

_CIS_COHERENCE_CLAIMS = pathlib.Path(__file__).resolve().parents[1] / "cis_coherence_claims.py"


# The DECLARED oracle for the cis-coherence family. Every function that folds arms via
# `corroboration_from_arms` in cis_coherence_claims.py must appear here with its pairing.
_DECLARED_CIS_CORROBORATION_BUILDERS = {
    "_cis_dosage_concordance_claim": (
        "cell-line `cis_dosage_class` (DepMap model panel, bulk-RNA) × patient `patient_cis_dosage_class` "
        "(TCGA cohort, bulk-RNA) × cell-line `cis_protein_dosage_class` (DepMap-Gygi MS-protein, SK#1783) — "
        "the SAME cis-dosage-coupling property (same compute_cis_dosage construct) read on THREE (card, "
        "field) arms across TWO sample-context GRAINS. The protein arm is a SECOND ASSAY MODALITY of the "
        "cell-line grain (MS-protein vs bulk-RNA): independent by MODALITY but SAME grain as the cell-line "
        "RNA arm — a DISTINCT card, NOT a re-read of the RNA card — so it shares the cell-line "
        "dependence_group and never counts as a third independent grain-replicate; only the patient arm is "
        "the cross-GRAIN corroborator. None a subset/superset nor derived from another (commensurate by "
        "same-construct/same-granularity; grain+modality first-class; see _CIS_COMMENSURATE_ARM_PAIRS / "
        "_CIS_ARM_STRUCTURE)"
    ),
    "_methylation_silencing_concordance_claim": (
        "cell-line `methylation_silencing_class` (DepMap model panel) × patient "
        "`patient_methylation_silencing_class` (TCGA cohort) — the SAME epigenetic-silencing property "
        "(promoter methylation → own LOW expression) measured at two DIFFERENT sample-context GRAINS (model "
        "vs patient, grain first-class); neither a subset/superset nor derived from the other. UNLIKE "
        "cis-dosage, the two silencing vocabularies DIFFER, so each token is routed through an EXPLICIT "
        "per-grain class→arm mapping (silencing_lineage_confounded / methylation_invariant_panel / patient "
        "insufficient_methylation_data route to NO rung — they DROP, never fabricating a disagreeing arm); "
        "commensurate by same-construct/same-granularity/independent-grain, see _SILENCING_COMMENSURATE_ARM_PAIRS"
    ),
    "_expression_dependency_concordance_claim": (
        "cell-line `correlation_class` (expression-dependency-correlation, bulk-RNA) × cell-line "
        "`abundance_dependency_class` (abundance-dependency, DepMap-Gygi MS-protein) — the SAME own-omics→"
        "dependency-coupling property (does the target's own expression/abundance predict its DepMap Chronos "
        "dependency?) measured by two independent ASSAY MODALITIES of the SAME cell-line sample-context grain "
        "(SK#1784, epic #1779 A4). Independence is by ASSAY MODALITY ONLY (bulk-RNA vs MS-protein) — WEAKER "
        "than cis-dosage's cross-GRAIN independence: BOTH arms share the cell_line_model grain, so grain is "
        "first-class and identical while dependence_group is the modality. A same-MODALITY restatement "
        "(re-reading the mRNA card) is NEVER a second arm; the two silencing/expression vocabularies DIFFER, "
        "so each token is routed through an EXPLICIT per-modality class→arm mapping (protein "
        "insufficient_paired_models / data_unavailable route to NO rung — they DROP, never fabricating a "
        "disagreeing arm). Neither a subset/superset nor derived from the other; commensurate by same-"
        "construct/same-granularity/independent-MODALITY, see _EXPRDEP_COMMENSURATE_ARM_PAIRS / _EXPRDEP_ARM_STRUCTURE"
    ),
}

# The (card_id, field) arms the fold reads. Three DISTINCT cis-coherence cards across two grains (cell-line
# RNA + cell-line protein share the model grain but differ in modality; patient is the cross-grain arm) —
# the set is what makes the arms commensurate-yet-independent. A re-pointed arm (reading another grain's or
# modality's card) changes this set and fails the assertion below.
_CIS_COMMENSURATE_ARM_PAIRS = frozenset(
    {
        ("cis-feature-expression-coherence", "cis_dosage_class"),  # cell-line grain, bulk-RNA modality
        ("patient-cis-coherence", "patient_cis_dosage_class"),  # patient grain, bulk-RNA modality (cross-grain)
        ("cis-feature-protein-coherence", "cis_protein_dosage_class"),  # cell-line grain, MS-protein modality (SK#1783)
    }
)

# SK#1783 — the independence STRUCTURE of the three arms: each (card, field) carries a sample-context
# GRAIN and an assay MODALITY. cell-line-RNA and protein SHARE the cell-line grain but differ in MODALITY
# (bulk-RNA vs MS-protein) → ONE dependence_group `cell_line_model` (independent by modality only, NEVER a
# second independent grain-replicate). The patient arm is the cross-GRAIN corroborator (its own group).
# This is what stops a same-grain modality restatement inflating corroborating_independent_arm_count.
_CIS_ARM_STRUCTURE = {
    ("cis-feature-expression-coherence", "cis_dosage_class"): {
        "grain": "cell_line_model",
        "modality": "bulk_rna",
        "dependence_group": "cell_line_model",
    },
    ("cis-feature-protein-coherence", "cis_protein_dosage_class"): {
        "grain": "cell_line_model",
        "modality": "ms_protein",
        "dependence_group": "cell_line_model",
    },
    ("patient-cis-coherence", "patient_cis_dosage_class"): {
        "grain": "patient_tumour",
        "modality": "bulk_rna",
        "dependence_group": "patient_tumour",
    },
}


def _cis_tree() -> ast.Module:
    return _parse(_CIS_COHERENCE_CLAIMS.read_text())


def assert_cis_arms_are_commensurate(tree: ast.Module) -> None:
    """Raise AssertionError unless `_cis_dosage_concordance_claim` folds EXACTLY the declared three
    cis-coherence card/field arms — no incommensurate card pulled in, none dropped, and the arms read three
    DISTINCT cards across two grains (the protein arm a distinct MODALITY of the cell-line grain, not a
    re-read of the RNA card). The predicate the cis-family mutations drive red. (Raw dosage metrics are read
    off a LOCAL card binding, not the inline `c.get(...) or {}).get(...)` idiom, so they are correctly NOT
    counted as arms.)"""
    funcs = _functions(tree)
    assert "_cis_dosage_concordance_claim" in funcs, (
        "_cis_dosage_concordance_claim vanished from cis_coherence_claims.py"
    )
    pairs = _card_field_get_pairs(funcs["_cis_dosage_concordance_claim"])
    declared = set(_CIS_COMMENSURATE_ARM_PAIRS)
    assert pairs == declared, (
        f"_cis_dosage_concordance_claim folds card/field arms {sorted(pairs)} — expected EXACTLY the "
        f"declared commensurate cis-dosage arms {sorted(declared)}. An arm reading a DIFFERENT card mixes an "
        f"incommensurate construct into the cis-dosage fold, and an arm reading the OTHER grain's card "
        f"collapses the two independent grains into one (a same-grain double-count, the #1667 shape). "
        f"undeclared = {sorted(pairs - declared)}; gone = {sorted(declared - pairs)}."
    )


# ── the cis-coherence-family tests ─────────────────────────────────────────────────────────────────
def test_cis_multi_arm_builders_are_declared():
    """ENUMERATION / anti-drift for the cis-coherence family: every function that folds arms via
    `corroboration_from_arms` in cis_coherence_claims.py must be declared. A NEW multi-arm builder fails
    here until its arm pairing is declared in `_DECLARED_CIS_CORROBORATION_BUILDERS`."""
    discovered = _corroboration_builders(_cis_tree())
    declared = set(_DECLARED_CIS_CORROBORATION_BUILDERS)
    assert discovered == declared, (
        f"cis-coherence multi-arm corroboration builders drifted from the declared oracle: "
        f"undeclared (add its arm pairing) = {sorted(discovered - declared)}; "
        f"declared-but-gone (remove it) = {sorted(declared - discovered)}"
    )


def test_cis_oracle_is_three_distinct_cards_across_two_grains():
    """The declared table encodes the commensurability + independence rule (SK#1783): the THREE arms read
    three DISTINCT cis-coherence cards spanning TWO sample-context grains. cell-line-RNA and protein SHARE
    the cell-line grain but differ in ASSAY MODALITY (bulk-RNA vs MS-protein) — the protein arm is a
    DISTINCT card, NOT a re-read of the RNA card — while the patient arm is the cross-GRAIN corroborator.
    Guards the oracle against (a) a typo collapsing an arm onto another card, and (b) the modality arm
    being mistaken for a third independent grain."""
    cards = {card for (card, _f) in _CIS_COMMENSURATE_ARM_PAIRS}
    assert len(cards) == 3, (
        f"the cis arms must read three DISTINCT cards (cell-line RNA, cell-line protein, patient), not one "
        f"card re-read (which would be a same-grain double-count); got cards {sorted(cards)}"
    )
    assert all("cis" in card for card in cards), (
        f"all cis arms must read a cis-coherence card (the SAME cis-dosage-coupling construct); got {sorted(cards)}"
    )
    # the arm-STRUCTURE table must cover exactly the declared arms, one grain+modality+group per arm.
    assert set(_CIS_ARM_STRUCTURE) == set(_CIS_COMMENSURATE_ARM_PAIRS), (
        "the arm-structure table must declare grain/modality/dependence_group for EXACTLY the folded arms"
    )
    grains = {v["grain"] for v in _CIS_ARM_STRUCTURE.values()}
    groups = {v["dependence_group"] for v in _CIS_ARM_STRUCTURE.values()}
    assert grains == {"cell_line_model", "patient_tumour"}, f"expected two grains, got {sorted(grains)}"
    # TWO independent dependence groups (not three) — the protein modality shares the cell-line group.
    assert len(groups) == 2, (
        f"three arms must fold into TWO dependence groups (cell-line RNA+protein share a grain), got {sorted(groups)}"
    )
    rna = _CIS_ARM_STRUCTURE[("cis-feature-expression-coherence", "cis_dosage_class")]
    prot = _CIS_ARM_STRUCTURE[("cis-feature-protein-coherence", "cis_protein_dosage_class")]
    # the crux: protein is a DISTINCT card + DISTINCT modality but the SAME grain / SAME dependence group.
    assert prot["grain"] == rna["grain"] == "cell_line_model", "protein must share the cell-line RNA grain"
    assert prot["dependence_group"] == rna["dependence_group"], "protein must share the cell-line RNA dependence group"
    assert prot["modality"] != rna["modality"], "protein must be a DISTINCT assay modality from the cell-line RNA arm"


def test_cis_folds_the_commensurate_cross_grain_arms():
    """GREEN on today's cis_coherence_claims.py: `_cis_dosage_concordance_claim` folds exactly the three
    commensurate arms (cell-line RNA + protein + patient). Also anti-vacuity — the declared arm set is non-empty."""
    assert _CIS_COMMENSURATE_ARM_PAIRS, "the declared cis arm set is empty — the test would pin nothing"
    assert_cis_arms_are_commensurate(_cis_tree())


# The mutation the cis detector exists to catch: the PATIENT arm re-pointed to read the SAME cell-line
# card — collapsing the two independent grains into one card (a same-grain double-count, the #1667 shape).
# Applied to a COPY of the source string.
def _mutant_cis_repoints_patient_arm_to_cellline_card(source: str) -> str:
    mutated = source.replace(
        '(c.get("patient-cis-coherence") or {}).get("patient_cis_dosage_class")',
        '(c.get("cis-feature-expression-coherence") or {}).get("patient_cis_dosage_class")',
    )
    assert mutated != source, "mutation was a no-op — the patient arm inline card read is no longer present to re-point"
    return mutated


def test_detector_bites_a_cis_arm_repointed_to_the_other_grain_card():
    """MUTATION TEST for the cis family — the corpus alone has no teeth here, so prove the detector bites.
    With the patient arm re-pointed to the cell-line card, the folded card set collapses to a single
    cis-coherence card (the two independent grains become one — a same-grain double-count) and
    `assert_cis_arms_are_commensurate` FAILS. Confirms both the RED (on the mutant) and — via
    `test_cis_folds_the_commensurate_cross_grain_arms` — the GREEN on real source."""
    mutant = _parse(_mutant_cis_repoints_patient_arm_to_cellline_card(_CIS_COHERENCE_CLAIMS.read_text()))
    # sanity: the mutant genuinely collapses the patient grain onto the cell-line RNA card (the protein
    # modality arm is untouched, so it survives — but the independent PATIENT grain is gone).
    pairs = _card_field_get_pairs(_functions(mutant)["_cis_dosage_concordance_claim"])
    cards = {card for (card, _f) in pairs}
    assert "patient-cis-coherence" not in cards, "the mutation did not collapse the patient grain as intended"
    assert "cis-feature-expression-coherence" in cards, "the RNA card should now carry the re-pointed patient field"
    # …and the detector rejects it
    with pytest.raises(AssertionError, match="_cis_dosage_concordance_claim"):
        assert_cis_arms_are_commensurate(mutant)


# The SECOND cis mutation (SK#1783): the PROTEIN arm re-pointed to read the cell-line-RNA card — which
# collapses the DISTINCT-modality distinction (protein masquerading as a re-read of the RNA card, a
# same-card double-count within one grain). The detector must bite this too.
def _mutant_cis_repoints_protein_arm_to_rna_card(source: str) -> str:
    mutated = source.replace(
        '(c.get("cis-feature-protein-coherence") or {}).get("cis_protein_dosage_class")',
        '(c.get("cis-feature-expression-coherence") or {}).get("cis_protein_dosage_class")',
    )
    assert mutated != source, "mutation was a no-op — the protein arm inline card read is no longer present to re-point"
    return mutated


def test_detector_bites_the_protein_arm_repointed_to_the_rna_card():
    """MUTATION TEST for the SK#1783 protein modality arm. Re-pointing the protein arm to read the
    cell-line-RNA card collapses the distinct-modality construct into a same-card double-count — the
    folded card set loses the protein card — and `assert_cis_arms_are_commensurate` FAILS. Confirms the
    detector defends the modality distinction, not merely the two-grain distinction."""
    mutant = _parse(_mutant_cis_repoints_protein_arm_to_rna_card(_CIS_COHERENCE_CLAIMS.read_text()))
    # sanity: the mutant genuinely drops the protein card off the fold
    pairs = _card_field_get_pairs(_functions(mutant)["_cis_dosage_concordance_claim"])
    cards = {card for (card, _f) in pairs}
    assert "cis-feature-protein-coherence" not in cards, "the mutation did not collapse the protein modality arm"
    # …and the detector rejects it
    with pytest.raises(AssertionError, match="_cis_dosage_concordance_claim"):
        assert_cis_arms_are_commensurate(mutant)


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# NINTH FAMILY — the CIS-COHERENCE (methylation-silencing cross-grain) builder in cis_coherence_claims.py
# (SK#1782)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# `_methylation_silencing_concordance_claim` (L2b #1782, epic #1779) folds
# `corroboration_from_arms([cellline_arm, patient_arm])`, where each arm is the resolved SILENCING direction
# of the SAME epigenetic-silencing property (promoter methylation → own LOW expression) at a DIFFERENT
# sample-context GRAIN:
#   * cell-line MODEL grain — cellline-methylation-expression-coherence.methylation_silencing_class (DepMap)
#   * patient TUMOUR grain  — patient-cis-coherence.patient_methylation_silencing_class            (TCGA)
#
# AUDIT VERDICT (SK#1782): COMMENSURATE by design, WITH an explicit vocabulary-mapping precondition.
#   * SAME CONSTRUCT: both resolve whether promoter methylation silences the target's own expression.
#   * SAME GRANULARITY, DIFFERENT GRAIN (first-class): per-target silencing class, one model / one patient.
#   * ★★ NON-IDENTICAL VOCABULARIES → EXPLICIT CLASS→ARM MAPPING (the crux distinguishing this family from
#     cis-dosage, which shares one vocabulary). Each grain enumerates EVERY token to silenced / not_silenced
#     / DROP. The cell-line `silencing_lineage_confounded` (measured but NOT interpretable as cis silencing)
#     + `methylation_invariant_panel` (untestable) and the patient `insufficient_methylation_data`
#     (uncovered cohort) route to NO rung — they DROP (None arm), they do NOT fabricate a disagreeing arm
#     (which would falsely drive corroboration to `low`). This mapping soundness is pinned at the CLAIM
#     level in test_cis_coherence_claims.py; here we pin the ARM-COMMENSURABILITY (two distinct grain cards).
#   * INDEPENDENT: DepMap cell-line panel vs TCGA patient cohort; neither a subset/superset nor derived.
#   * MEASURED (no vote flip): two agreeing grains → high; a discordance → low; one measured grain → single_
#     arm. Carries NO `signal` key, reads no verdict, feeds no rule (VERDICT-INERT, key omitted/byte-stable).
# The invariant this block pins: `_methylation_silencing_concordance_claim` folds EXACTLY the two declared
# cross-grain card/field arms (two DISTINCT cards — model vs patient). Re-pointing the patient arm to read
# the cell-line card (collapsing the two grains into one — the #1667 same-grain double-count shape) reds the
# assertion; the mutation test drives that red.

# The (card_id, field) arms the SILENCING fold reads. NOTE: unlike _CIS_COMMENSURATE_ARM_PAIRS these two
# cards do NOT both contain the "cis" substring (the cell-line card is `cellline-methylation-expression-
# coherence`), so the silencing family has its OWN distinct-grain assertion below rather than reusing the
# cis "cis"-substring check.
_SILENCING_COMMENSURATE_ARM_PAIRS = frozenset(
    {
        ("cellline-methylation-expression-coherence", "methylation_silencing_class"),
        ("patient-cis-coherence", "patient_methylation_silencing_class"),
    }
)


def assert_silencing_arms_are_commensurate(tree: ast.Module) -> None:
    """Raise AssertionError unless `_methylation_silencing_concordance_claim` folds EXACTLY the declared two
    silencing card/field arms — no incommensurate card pulled in, none dropped, two DISTINCT grain cards.
    (Raw silencing metrics are read off a LOCAL card binding, not the inline `(c.get(...) or {}).get(...)`
    idiom, so they are correctly NOT counted as arms.)"""
    funcs = _functions(tree)
    assert "_methylation_silencing_concordance_claim" in funcs, (
        "_methylation_silencing_concordance_claim vanished from cis_coherence_claims.py"
    )
    pairs = _card_field_get_pairs(funcs["_methylation_silencing_concordance_claim"])
    declared = set(_SILENCING_COMMENSURATE_ARM_PAIRS)
    assert pairs == declared, (
        f"_methylation_silencing_concordance_claim folds card/field arms {sorted(pairs)} — expected EXACTLY "
        f"the two commensurate cross-grain arms {sorted(declared)}. An arm reading a DIFFERENT card mixes an "
        f"incommensurate construct into the silencing fold, and an arm reading the OTHER grain's card "
        f"collapses the two independent grains into one (a same-grain double-count, the #1667 shape). "
        f"undeclared = {sorted(pairs - declared)}; gone = {sorted(declared - pairs)}."
    )


# ── the silencing-family tests ─────────────────────────────────────────────────────────────────────
def test_silencing_oracle_is_two_distinct_grain_cards():
    """The declared silencing table encodes the commensurability rule: two DISTINCT grain cards (cell-line
    MODEL methylation card vs patient TUMOUR cis card), same epigenetic-silencing construct. The cell-line
    card is NOT a `*cis*` card, so this pins the exact two expected cards rather than a substring."""
    cards = {card for (card, _f) in _SILENCING_COMMENSURATE_ARM_PAIRS}
    assert cards == {
        "cellline-methylation-expression-coherence",
        "patient-cis-coherence",
    }, (
        f"the two silencing arms must read the cell-line MODEL methylation card and the patient TUMOUR cis "
        f"card (two DISTINCT grains), not one card twice (a same-grain double-count); got {sorted(cards)}"
    )


def test_silencing_folds_the_commensurate_cross_grain_arms():
    """GREEN on today's cis_coherence_claims.py: `_methylation_silencing_concordance_claim` folds exactly
    the two commensurate cross-grain arms. Also anti-vacuity — the declared arm set is non-empty."""
    assert _SILENCING_COMMENSURATE_ARM_PAIRS, "the declared silencing arm set is empty — the test pins nothing"
    assert_silencing_arms_are_commensurate(_cis_tree())


# The mutation the silencing detector exists to catch: the PATIENT arm re-pointed to read the cell-line
# card — collapsing the two independent grains into one card (a same-grain double-count, #1667 shape).
def _mutant_silencing_repoints_patient_arm_to_cellline_card(source: str) -> str:
    mutated = source.replace(
        '(c.get("patient-cis-coherence") or {}).get("patient_methylation_silencing_class")',
        '(c.get("cellline-methylation-expression-coherence") or {}).get("patient_methylation_silencing_class")',
    )
    assert mutated != source, (
        "mutation was a no-op — the patient silencing arm inline card read is no longer present to re-point"
    )
    return mutated


def test_detector_bites_a_silencing_arm_repointed_to_the_other_grain_card():
    """MUTATION TEST for the silencing family — the corpus alone has no teeth here, so prove the detector
    bites. With the patient arm re-pointed to the cell-line card, the folded card set collapses to a single
    card (the two independent grains become one — a same-grain double-count) and
    `assert_silencing_arms_are_commensurate` FAILS. Confirms both the RED (on the mutant) and — via
    `test_silencing_folds_the_commensurate_cross_grain_arms` — the GREEN on real source."""
    mutant = _parse(_mutant_silencing_repoints_patient_arm_to_cellline_card(_CIS_COHERENCE_CLAIMS.read_text()))
    # sanity: the mutant genuinely collapses the two arms onto one card
    pairs = _card_field_get_pairs(_functions(mutant)["_methylation_silencing_concordance_claim"])
    cards = {card for (card, _f) in pairs}
    assert cards == {"cellline-methylation-expression-coherence"}, "the mutation did not collapse the arms as intended"
    # …and the detector rejects it
    with pytest.raises(AssertionError, match="_methylation_silencing_concordance_claim"):
        assert_silencing_arms_are_commensurate(mutant)


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# TENTH FAMILY — the CIS-COHERENCE (expression/abundance→dependency SAME-GRAIN CROSS-MODALITY) builder in
# cis_coherence_claims.py (SK#1784)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# `_expression_dependency_concordance_claim` (L2b #1784, epic #1779 A4) folds
# `corroboration_from_arms([rna_arm, protein_arm])`, where each arm is the resolved own-omics→dependency
# direction of the SAME expression/abundance→dependency-coupling property measured by a DIFFERENT ASSAY
# MODALITY of the SAME cell-line sample-context grain:
#   * mRNA modality    — expression-dependency-correlation.correlation_class    (DepMap bulk-RNA vs Chronos)
#   * protein modality — abundance-dependency.abundance_dependency_class        (DepMap-Gygi MS vs Chronos)
#
# AUDIT VERDICT (SK#1784): COMMENSURATE by design, WITH an explicit vocabulary-mapping precondition AND a
# MODALITY-only (not grain) independence axis — the crux distinguishing this family from #1781/#1782.
#   * SAME CONSTRUCT: both resolve whether the target's own-omics abundance predicts its DepMap dependency.
#   * SAME GRANULARITY, SAME GRAIN, DIFFERENT MODALITY (★★ the #1784 crux). BOTH arms are cell-line-panel
#     correlations against the SAME Chronos readout → they SHARE the cell_line_model grain (grain is
#     first-class and IDENTICAL). Independence is by ASSAY MODALITY ONLY (bulk-RNA vs MS-protein), recorded
#     as the per-arm dependence_group — WEAKER than #1781's cross-grain independence (shared culture/lineage/
#     panel confounds are NOT broken). corroborating_independent_arm_count counts INDEPENDENT MODALITIES (2
#     when both resolve); a same-MODALITY restatement never inflates it.
#   * ★★ NON-IDENTICAL VOCABULARIES → EXPLICIT CLASS→ARM MAPPING. Each modality enumerates EVERY token to
#     predictive / not_predictive / DROP. The protein `insufficient_paired_models` (underpowered) +
#     `data_unavailable` route to NO rung — they DROP (None arm), never fabricating a disagreeing arm (which
#     would falsely drive corroboration to `low`). This mapping soundness is pinned at the CLAIM level in
#     test_cis_coherence_claims.py; here we pin the ARM-COMMENSURABILITY (two distinct MODALITY cards).
#   * INDEPENDENT (by modality): distinct assay platforms; neither a subset/superset nor derived.
#   * MEASURED (no vote flip): two agreeing modalities → high; a discordance → low; one measured modality →
#     single_arm. Carries NO `signal` key, reads no verdict, feeds no rule (VERDICT-INERT, key omitted/byte-
#     stable). Declaration moves no decision.json — a pure detector extension.
# The invariant this block pins: `_expression_dependency_concordance_claim` folds EXACTLY the two declared
# cross-MODALITY card/field arms (two DISTINCT cards — bulk-RNA vs MS-protein). Re-pointing the protein arm
# to read the mRNA card (collapsing the two independent MODALITIES into one card — the #1667 same-source
# double-count shape) reds the assertion; the mutation test drives that red.

# The (card_id, field) arms the expression/abundance→dependency fold reads. Two DISTINCT cards, one per
# assay MODALITY, both at the SAME cell_line_model grain — the set is what makes the two arms commensurate-
# yet-independent-by-modality. A re-pointed arm (reading the OTHER modality's card) collapses this set and
# fails the assertion below.
_EXPRDEP_COMMENSURATE_ARM_PAIRS = frozenset(
    {
        ("expression-dependency-correlation", "correlation_class"),  # cell-line grain, bulk-RNA modality
        ("abundance-dependency", "abundance_dependency_class"),  # cell-line grain, MS-protein modality
    }
)

# SK#1784 — the independence STRUCTURE of the two arms: each (card, field) carries a sample-context GRAIN
# and an assay MODALITY. BOTH arms SHARE the cell_line_model grain but differ in MODALITY (bulk-RNA vs
# MS-protein) → TWO independent-by-MODALITY dependence_groups on ONE grain. This is what makes the
# independence axis MODALITY (not grain), and what stops a same-modality restatement counting twice.
_EXPRDEP_ARM_STRUCTURE = {
    ("expression-dependency-correlation", "correlation_class"): {
        "grain": "cell_line_model",
        "modality": "bulk_rna",
        "dependence_group": "cell_line_rna",
    },
    ("abundance-dependency", "abundance_dependency_class"): {
        "grain": "cell_line_model",
        "modality": "ms_protein",
        "dependence_group": "cell_line_protein",
    },
}


def assert_exprdep_arms_are_commensurate(tree: ast.Module) -> None:
    """Raise AssertionError unless `_expression_dependency_concordance_claim` folds EXACTLY the declared two
    expression/abundance→dependency card/field arms — no incommensurate card pulled in, none dropped, two
    DISTINCT MODALITY cards. (Raw correlation metrics are read off a LOCAL card binding, not the inline
    `(c.get(...) or {}).get(...)` idiom, so they are correctly NOT counted as arms.)"""
    funcs = _functions(tree)
    assert "_expression_dependency_concordance_claim" in funcs, (
        "_expression_dependency_concordance_claim vanished from cis_coherence_claims.py"
    )
    pairs = _card_field_get_pairs(funcs["_expression_dependency_concordance_claim"])
    declared = set(_EXPRDEP_COMMENSURATE_ARM_PAIRS)
    assert pairs == declared, (
        f"_expression_dependency_concordance_claim folds card/field arms {sorted(pairs)} — expected EXACTLY "
        f"the two commensurate cross-modality arms {sorted(declared)}. An arm reading a DIFFERENT card mixes "
        f"an incommensurate construct into the fold, and an arm reading the OTHER modality's card collapses "
        f"the two independent MODALITIES into one (a same-source double-count, the #1667 shape). "
        f"undeclared = {sorted(pairs - declared)}; gone = {sorted(declared - pairs)}."
    )


# ── the expression-dependency-family tests ──────────────────────────────────────────────────────────
def test_exprdep_oracle_is_two_distinct_modality_cards_one_grain():
    """The declared table encodes the commensurability + independence rule (SK#1784): the TWO arms read two
    DISTINCT cards — one bulk-RNA, one MS-protein — BOTH at the SAME cell_line_model grain. Guards the
    oracle against (a) a typo collapsing an arm onto the other card, and (b) the modality independence being
    mistaken for a second independent GRAIN."""
    cards = {card for (card, _f) in _EXPRDEP_COMMENSURATE_ARM_PAIRS}
    assert cards == {
        "expression-dependency-correlation",
        "abundance-dependency",
    }, (
        f"the two exprdep arms must read the bulk-RNA correlation card and the MS-protein abundance card "
        f"(two DISTINCT modalities), not one card twice (a same-modality double-count); got {sorted(cards)}"
    )
    # the arm-STRUCTURE table must cover exactly the declared arms, one grain+modality+group per arm.
    assert set(_EXPRDEP_ARM_STRUCTURE) == set(_EXPRDEP_COMMENSURATE_ARM_PAIRS), (
        "the arm-structure table must declare grain/modality/dependence_group for EXACTLY the folded arms"
    )
    grains = {v["grain"] for v in _EXPRDEP_ARM_STRUCTURE.values()}
    modalities = {v["modality"] for v in _EXPRDEP_ARM_STRUCTURE.values()}
    groups = {v["dependence_group"] for v in _EXPRDEP_ARM_STRUCTURE.values()}
    # ★★ the crux: ONE shared grain, TWO distinct modalities, TWO distinct dependence groups.
    assert grains == {"cell_line_model"}, (
        f"both exprdep arms must SHARE the cell_line_model grain (independence is by modality, not grain); "
        f"got grains {sorted(grains)}"
    )
    assert len(modalities) == 2 and len(groups) == 2, (
        f"the two arms must be two DISTINCT assay modalities / dependence groups on the one grain; got "
        f"modalities {sorted(modalities)}, groups {sorted(groups)}"
    )


def test_exprdep_folds_the_commensurate_cross_modality_arms():
    """GREEN on today's cis_coherence_claims.py: `_expression_dependency_concordance_claim` folds exactly
    the two commensurate cross-modality arms. Also anti-vacuity — the declared arm set is non-empty."""
    assert _EXPRDEP_COMMENSURATE_ARM_PAIRS, "the declared exprdep arm set is empty — the test pins nothing"
    assert_exprdep_arms_are_commensurate(_cis_tree())


# The mutation the exprdep detector exists to catch: the PROTEIN arm re-pointed to read the mRNA
# (expression-dependency-correlation) card — collapsing the two independent MODALITIES into one card (a
# same-modality double-count, #1667 shape; exactly the "same-modality restatement" the brief forbids).
def _mutant_exprdep_repoints_protein_arm_to_rna_card(source: str) -> str:
    mutated = source.replace(
        '(c.get("abundance-dependency") or {}).get("abundance_dependency_class")',
        '(c.get("expression-dependency-correlation") or {}).get("abundance_dependency_class")',
    )
    assert mutated != source, (
        "mutation was a no-op — the protein exprdep arm inline card read is no longer present to re-point"
    )
    return mutated


def test_detector_bites_an_exprdep_arm_repointed_to_the_other_modality_card():
    """MUTATION TEST for the expression-dependency family — the corpus alone has no teeth here, so prove the
    detector bites. With the protein arm re-pointed to the mRNA card, the folded card set collapses to a
    single card (the two independent MODALITIES become one — a same-modality double-count, the very "same-
    modality restatement counted as a second arm" the #1784 brief forbids) and
    `assert_exprdep_arms_are_commensurate` FAILS. Confirms both the RED (on the mutant) and — via
    `test_exprdep_folds_the_commensurate_cross_modality_arms` — the GREEN on real source."""
    mutant = _parse(_mutant_exprdep_repoints_protein_arm_to_rna_card(_CIS_COHERENCE_CLAIMS.read_text()))
    # sanity: the mutant genuinely collapses the two modality arms onto one card
    pairs = _card_field_get_pairs(_functions(mutant)["_expression_dependency_concordance_claim"])
    cards = {card for (card, _f) in pairs}
    assert cards == {"expression-dependency-correlation"}, "the mutation did not collapse the arms as intended"
    # …and the detector rejects it
    with pytest.raises(AssertionError, match="_expression_dependency_concordance_claim"):
        assert_exprdep_arms_are_commensurate(mutant)


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# FLEET-COMPLETENESS META-GUARD — every multi-arm fold-builder in _skills_common must belong to a
# declared commensurability family (SK#1704, tracking #1703, epic #1507)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# SK#1688/#1689/#1675 made the arm-commensurability audit a standing gate for THREE families
# (genomic / expression-proteomics / presence), but each family block is PER-FILE opt-in: it enumerates
# the `corroboration_from_arms` callers inside ONE named file against ONE oracle. Nothing asserted that
# *every* fold-builder across `_skills_common` belongs to a declared family — so a NEW builder landing in
# an un-audited claim file would ship silently un-audited, and the #1703 milestone ("zero un-declared
# multi-arm builders") stayed aspirational rather than enforced.
#
# This block is the enforcement artifact #1703 calls for. It STATIC-PARSES every `*claims*.py` in
# `_skills_common`, enumerates each file's `corroboration_from_arms` callers (RESOLVING the import alias
# per-file — presence imports it as `_corr_from_arms`; the resolution is generic, not hardcoded), and
# asserts each enclosing FILE is either in the DECLARED covered-families set (which have an oracle block
# above) OR in an explicit KNOWN-DEBT list. A caller in a file in NEITHER set fails loudly, naming the
# file + function + arms and pointing at #1703. This flips the audit's to-do list into the gate itself:
# the un-declared-builder population is closed by construction — a future multi-arm builder either lands
# in a declared family, or is baselined as debt, or fails this gate.
#
# As of SK#1709 ALL seven family files are declared covered families and `_KNOWN_DEBT_FILES` is EMPTY —
# the #1703 milestone "zero un-declared multi-arm builders in _skills_common" is reached. (literature moved
# from debt → a declared covered family in #1600; dependency/safety/combination moved in #1709, each
# audited COMMENSURATE with its oracle block above.) The guard reds the moment a NEW un-declared family/
# file appears, OR — while any debt entry exists — a debt family is removed from the debt list without a
# matching declared oracle block (the file still holds a caller, so it lands in NEITHER set → red). The `_cn_signal`-style signal/demotion
# MIRROR shape is already governed within its family block (genomic `_CN_DIRECTIONAL_BUILDERS`,
# selectivity `_PROTEIN_QUORUM`); at this FILE granularity it lives inside an already-covered file, so the
# fleet enumeration captures it by inclusion.
#
# This block edits ONLY the test file — no `*claims*.py` change — so it is verdict byte-stable by
# construction (no decision.json / field_read_health / golden move, no target-contracts pin).

_SKILLS_COMMON_DIR = pathlib.Path(__file__).resolve().parents[1]


# The DECLARED "covered families" set: files whose `corroboration_from_arms` callers are each pinned by a
# declared oracle block ABOVE in this file. Value = the family + the landed detector that covers it.
_COVERED_FAMILY_FILES = {
    "genomic_claims.py": (
        "genomic — detector SK#1688 (_DECLARED_CORROBORATION_BUILDERS + the _cn_signal demotion mirror); "
        "#1703 row: genomic [x]"
    ),
    "selectivity_claims.py": (
        "expression/proteomics — detector SK#1689 (_DECLARED_SELECTIVITY_CORROBORATION_BUILDERS + the "
        "_protein_window_quorum mirror); #1703 row: expression/proteomics [x]"
    ),
    "presence_claims.py": (
        "presence — detector SK#1675 (_DECLARED_PRESENCE_CORROBORATION_BUILDERS, corroboration_from_arms "
        "imported ALIASED as _corr_from_arms); #1703 row: presence [x]"
    ),
    "literature_context_claims.py": (
        "literature — detector SK#1600 (_DECLARED_LITERATURE_CORROBORATION_BUILDERS + the single-arm `_corr` "
        "fold: no non-independent n_diseases arm, capped at single_arm); #1703 row: literature [x]"
    ),
    "dependency_claims.py": (
        "dependency — detector SK#1709 (_DECLARED_DEPENDENCY_CORROBORATION_BUILDERS + "
        "_DEPENDENCY_COMMENSURATE_ARM_PAIRS: CRISPR×RNAi two independent orthogonal essentiality screens, "
        "same construct/granularity); #1703 row: dependency [x]"
    ),
    "safety_claims.py": (
        "safety — detector SK#1709 (_DECLARED_SAFETY_CORROBORATION_BUILDERS + _SAFETY_COMMENSURATE_SOURCE_ARMS: "
        "GTEx-bulk × scRNA-normal × HPA-IHC three independent organ-aware liability modalities, all mapped to "
        "the same organ-aware basis — the #1673 manufactured-agreement shape actively avoided); #1703 row: safety [x]"
    ),
    "combination_vulnerability_claims.py": (
        "combination — detector SK#1709 (_DECLARED_COMBINATION_CORROBORATION_BUILDERS + "
        "_COMBINATION_CONSORTIUM_ARM_FIELDS: one confirmed-positive DepMap primary arm + Dede/in4mer two "
        "independent consortia, no inflating sentinel, no double-count); #1703 row: combination [x]"
    ),
    "cis_coherence_claims.py": (
        "cis-coherence — detector SK#1781/#1782/#1784 (_DECLARED_CIS_CORROBORATION_BUILDERS covers THREE cis "
        "families: cis-dosage (_CIS_COMMENSURATE_ARM_PAIRS: cell-line `cis_dosage_class` × patient "
        "`patient_cis_dosage_class`) and methylation-silencing (_SILENCING_COMMENSURATE_ARM_PAIRS: cell-line "
        "`methylation_silencing_class` × patient `patient_methylation_silencing_class`, with an explicit "
        "per-grain class→arm mapping since the two silencing vocabularies differ) — each the SAME cis-domain "
        "construct at two DISTINCT sample-context grains, grain first-class, independent; PLUS expression/"
        "abundance→dependency (_EXPRDEP_COMMENSURATE_ARM_PAIRS: bulk-RNA `correlation_class` × MS-protein "
        "`abundance_dependency_class`) — the SAME expression/abundance→DepMap-dependency-coupling construct at "
        "the SAME cell_line_model grain but two DISTINCT assay MODALITIES, so independence is MODALITY-only "
        "(weaker than cross-grain; shared panel confounds NOT broken), with an explicit per-modality class→arm "
        "mapping since the two modality vocabularies differ; epic #1779)"
    ),
}

# The explicit KNOWN-DEBT list: files that DO contain a `corroboration_from_arms` caller but whose family
# is not yet declared with an oracle block. Baselined so the guard is GREEN when a family is still open;
# each entry cites its #1703 checklist row. Removing an entry here WITHOUT adding a declared oracle block
# for the file reds the guard (the file's caller then belongs to NEITHER set) — the intended forcing
# function. SK#1709 declared the last three families (dependency/safety/combination — each audited
# COMMENSURATE and moved to _COVERED_FAMILY_FILES above), so this list is now EMPTY: the #1703 milestone
# "zero un-declared multi-arm builders in _skills_common" is reached. A future un-audited builder must be
# declared (with an oracle block) or baselined here with a cited #1703-style reason, or it reds the guard.
_KNOWN_DEBT_FILES: dict[str, str] = {}


def _all_claims_files() -> list[pathlib.Path]:
    """Every `*claims*.py` module in `_skills_common` (the population the fleet guard sweeps). Sorted for
    deterministic reporting. `__file__` lives in tests/, so glob the parent skills_common dir directly."""
    return sorted(_SKILLS_COMMON_DIR.glob("*claims*.py"))


def corroboration_callers_by_file() -> dict[str, set[str]]:
    """file basename → {function names that fold arms via `corroboration_from_arms`}, across ALL
    `*claims*.py`. The import alias is resolved PER FILE (`_corr_from_arms_local_name`), so an aliased
    caller (presence) is enumerated identically to an unaliased one. Files with no caller are omitted."""
    out: dict[str, set[str]] = {}
    for path in _all_claims_files():
        tree = _parse(path.read_text())
        local = _corr_from_arms_local_name(tree)  # generic alias resolution (asname or plain name)
        callers = {name for name, fn in _functions(tree).items() if _calls_named(fn, local)}
        if callers:
            out[path.name] = callers
    return out


def assert_every_corroboration_file_is_declared_or_debt(
    callers_by_file: dict[str, set[str]],
    covered: set[str],
    debt: set[str],
) -> None:
    """Raise AssertionError unless every file that folds arms via `corroboration_from_arms` is in the
    DECLARED covered-families set OR the explicit known-debt list (and the two sets are disjoint). This is
    the predicate both fleet-completeness mutation tests drive red."""
    overlap = covered & debt
    assert not overlap, (
        f"a claim file is listed as BOTH a covered family and known-debt: {sorted(overlap)} — a family is "
        f"either declared (with an oracle block) or debt, never both (#1703)"
    )
    for fname in sorted(callers_by_file):
        funcs = callers_by_file[fname]
        assert fname in covered or fname in debt, (
            f"UN-DECLARED multi-arm fold-builder family: {fname} contains `corroboration_from_arms` "
            f"caller(s) {sorted(funcs)} but the file is in NEITHER the declared covered-families set NOR "
            f"the known-debt list. Every multi-arm fold-builder in _skills_common must belong to a "
            f"declared commensurability family (arm-commensurability invariant, tracking #1703, epic "
            f"#1507): fold arms are only commensurate if same construct/granularity/provenance-basis and "
            f"independent. Either ADD a declared oracle block for this family (like the genomic/"
            f"selectivity/presence blocks above) or BASELINE it in _KNOWN_DEBT_FILES citing its #1703 "
            f"checklist row."
        )


# ── the fleet-completeness tests ─────────────────────────────────────────────────────────────────────
def test_covered_and_debt_family_files_are_disjoint():
    """A claim file's family is either DECLARED (oracle block) or DEBT — never both. Guards against a
    stale debt entry lingering after a family is declared."""
    overlap = set(_COVERED_FAMILY_FILES) & set(_KNOWN_DEBT_FILES)
    assert not overlap, f"claim files listed as both covered and debt: {sorted(overlap)}"


def test_every_multi_arm_fold_builder_file_is_declared_or_debt():
    """FLEET COMPLETENESS (GREEN today): every `*claims*.py` that folds arms via `corroboration_from_arms`
    is in the declared covered-families set or the baselined known-debt list. A NEW un-declared family/
    file (or a NEW builder in an un-audited claim file) reds here until it is declared or baselined —
    turning the #1703 to-do list into the gate itself."""
    assert_every_corroboration_file_is_declared_or_debt(
        corroboration_callers_by_file(), set(_COVERED_FAMILY_FILES), set(_KNOWN_DEBT_FILES)
    )


def test_fleet_enumeration_finds_all_seven_known_family_files():
    """Anti-vacuity + coverage floor: the sweep must actually discover the seven family files known today
    (all seven now COVERED families; `_KNOWN_DEBT_FILES` is empty after SK#1709), each with ≥1 caller. If
    the enumeration silently found nothing (e.g. a broken alias resolution or glob), the completeness test
    above would pass VACUOUSLY. Pins that the enumeration has teeth and that every declared/debt file
    genuinely still carries a caller (so the covered/debt lists cannot go stale un-noticed)."""
    callers = corroboration_callers_by_file()
    expected_files = set(_COVERED_FAMILY_FILES) | set(_KNOWN_DEBT_FILES)
    # coverage floor: the seven known family files must all still be tracked (guards against the covered
    # set silently shrinking now that debt is empty and the debt-removal mutation test is vacuously skipped).
    assert len(expected_files) >= 7, (
        f"the arm-commensurability audit knows seven family files; the tracked set shrank to "
        f"{sorted(expected_files)} — a covered family was dropped without a replacement"
    )
    assert expected_files <= set(callers), (
        f"declared/debt family files with NO discovered corroboration_from_arms caller (stale entry, or "
        f"the enumeration failed to resolve them): {sorted(expected_files - set(callers))}"
    )
    # presence is the aliased case (`_corr_from_arms`); prove the alias resolution actually enumerated it.
    assert "presence_claims.py" in callers and callers["presence_claims.py"], (
        "the aliased presence family (_corr_from_arms) was not enumerated — alias resolution is broken"
    )


# MUTATION (a) — a synthetic `corroboration_from_arms` caller in a claim file that is in NEITHER the
# covered NOR the debt set must red the guard. Simulated by injecting a synthetic file→caller entry into
# the enumeration mapping (the guard is a pure predicate over that mapping), so no real module is touched.
def test_guard_bites_a_new_undeclared_family_file():
    """MUTATION TEST direction (a): a fold-builder in an un-audited claim file reds the guard. Confirms
    the guard bites the exact failure mode #1703 exists to prevent — a NEW multi-arm builder shipping in a
    file that no oracle block or debt entry covers."""
    mutant = dict(corroboration_callers_by_file())
    mutant["a_brand_new_undeclared_claims.py"] = {"_some_new_corroboration"}
    with pytest.raises(AssertionError, match="UN-DECLARED multi-arm fold-builder family"):
        assert_every_corroboration_file_is_declared_or_debt(mutant, set(_COVERED_FAMILY_FILES), set(_KNOWN_DEBT_FILES))


# MUTATION (b) — removing a family from the debt list WITHOUT adding its declared oracle block must red
# the guard: the file still holds a real caller, so it now belongs to NEITHER set.
@pytest.mark.parametrize("removed", sorted(_KNOWN_DEBT_FILES))
def test_guard_bites_a_debt_family_removed_without_a_declared_block(removed):
    """MUTATION TEST direction (b): silently dropping a debt entry (without promoting it to a declared
    oracle block) reds the guard, because the un-fixed file's real caller then belongs to neither set.
    This is what forces the debt list to shrink ONLY by declaring the family — never by quietly deleting
    the tracking row. Standing negative case over EVERY debt family."""
    debt_minus_one = set(_KNOWN_DEBT_FILES) - {removed}
    # sanity: the file we dropped genuinely still holds a live caller (else the test would pass vacuously)
    assert removed in corroboration_callers_by_file(), (
        f"{removed} no longer contains a corroboration_from_arms caller — this negative case is vacuous; "
        f"the debt entry should be removed and this parametrization updated"
    )
    with pytest.raises(AssertionError, match="UN-DECLARED multi-arm fold-builder family"):
        assert_every_corroboration_file_is_declared_or_debt(
            corroboration_callers_by_file(), set(_COVERED_FAMILY_FILES), debt_minus_one
        )
