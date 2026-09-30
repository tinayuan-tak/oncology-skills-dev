"""property_catalog validator tests — population conformance PLUS mutation teeth.

Two halves, and the second is the load-bearing one:

  * POPULATION — the committed vocabularies/property_catalog/ passes every clause. This is also the
    CI gate: contracts/tests/ is collected wholesale by the `contracts-pytest` job with no path
    filter, so a validator regression reds trunk here without needing a workflow edit.

  * TEETH — each clause is exercised against a PLANTED defect and asserted RED. A validator nobody
    has watched fail is not a validator; a green population result means nothing unless the checker
    can bite. Every teeth test names the real-world failure it defends against.

The teeth tests call the SAME functions the population test calls (`validate_file`,
`check_additivity`), never a re-implementation — otherwise a green population could coexist with an
inert checker.
"""

from __future__ import annotations

import copy
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
CONTRACTS = Path(__file__).resolve().parents[2]
CATALOG = CONTRACTS / "vocabularies" / "property_catalog"
CARDS = CONTRACTS / "cards"
SKILLS = REPO / "skills"


def _load_validator():
    path = CONTRACTS / "validators" / "validate_property_catalog.py"
    spec = importlib.util.spec_from_file_location("validate_property_catalog", path)
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec: @dataclass resolves its annotations through sys.modules[cls.__module__].
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


V = _load_validator()
CATALOG_FILES = sorted(CATALOG.glob("*.yaml"))
CARD_INDEX = V.card_field_index(CARDS)
ALL_IDS = V.collect_entry_ids(CATALOG)


# --------------------------------------------------------------------------- population


def test_catalog_is_not_empty():
    """Anti-vacuity floor. Without this, an empty glob would make every parametrized test below
    collect zero cases and the whole module would pass while checking nothing."""
    assert len(CATALOG_FILES) >= 3, f"expected >= 3 catalog files, found {[p.name for p in CATALOG_FILES]}"
    assert len(ALL_IDS) >= 25, f"expected >= 25 catalog entries, found {len(ALL_IDS)}"
    assert CARD_INDEX and len(CARD_INDEX) >= 100, "card index did not load — referential clauses would be inert"


@pytest.mark.parametrize("path", CATALOG_FILES, ids=[p.name for p in CATALOG_FILES])
def test_committed_catalog_validates(path):
    r = V.validate_file(path, CARD_INDEX, ALL_IDS, SKILLS)
    assert r.ok, f"{path.name}:\n  " + "\n  ".join(r.errors)


def test_every_l2a_property_has_an_estimator():
    """The identifiability test's positive form, asserted over the population rather than only
    enforced by the validator — a property resolvable only through `coupled` observables is a
    placeholder masquerading as a resolved property."""
    checked = 0
    for path in CATALOG_FILES:
        doc = yaml.safe_load(path.read_text())
        if doc.get("kind") != "l2a_property":
            continue
        for pid, entry in (doc.get("properties") or {}).items():
            if entry.get("status") != "resolvable":
                continue
            roles = [o.get("role") for o in (entry.get("observables") or [])]
            assert "estimator" in roles, f"{path.name}::{pid} has no estimator observable"
            checked += 1
    assert checked >= 10, f"only {checked} resolvable l2a properties examined — population too small to trust"


def test_family_count_matches_the_pinned_population():
    """integrated_families.yaml registers the LANDED families, and the landed count is pinned at 13
    by skills/_skills_common/tests/test_rung5_envelope_enforcement.py::_EXPECTED_FAMILY_COUNT.

    Arc #2210 must not add a family (peer epics #1730/#1755/#1779/#1812 own those), so this is a
    real constraint on this file, not a restatement of its own content: a catalog that grows past
    the landed population is claiming coverage that does not exist in code.
    """
    doc = yaml.safe_load((CATALOG / "integrated_families.yaml").read_text())
    families = doc["families"]
    assert len(families) == 13, f"expected the 13 landed families, got {len(families)}: {sorted(families)}"


def test_no_family_asserts_undeclared_independence():
    """#1667's lesson over the whole population: every family either spans >= 2 dependence_groups or
    says out loud why it does not."""
    doc = yaml.safe_load((CATALOG / "integrated_families.yaml").read_text())
    for fid, fam in doc["families"].items():
        groups = {a["dependence_group"] for a in fam["arms"]}
        if len(groups) < 2:
            assert fam["integration"].get("independence_waiver"), (
                f"{fid}: single dependence_group {groups} and no independence_waiver"
            )


def test_cptac_and_tphp_share_a_dependence_group():
    """The concrete #1667 case, pinned. Both cards are mass-spectrometry tumour proteomics; if a
    future edit gives them different dependence_groups, the selectivity family would start counting
    one modality measured twice as two independent arms — silently, with no other test noticing."""
    doc = yaml.safe_load((CATALOG / "integrated_families.yaml").read_text())
    arms = doc["families"]["selectivity"]["arms"]
    groups = {a["card_id"]: a["dependence_group"] for a in arms}
    assert groups["tumor-protein-abundance-cptac"] == groups["tumor-vs-normal-protein-abundance-tphp"], (
        f"CPTAC and TPHP must share a dependence_group; got {groups}"
    )


def test_every_unknown_rationale_is_tracked():
    """An honest UNKNOWN is allowed; an UNTRACKED one becomes permanent. Asserted over the
    population so a new determinant cannot quietly add an orphan hole."""
    unknowns = 0
    for path in CATALOG_FILES:
        doc = yaml.safe_load(path.read_text())
        entries = doc.get("properties") or doc.get("families") or {}
        for eid, entry in entries.items():
            for det in entry.get("determinants") or []:
                if "UNKNOWN" in (det.get("rationale") or ""):
                    unknowns += 1
                    assert det["calibration"].get("adjudication"), (
                        f"{path.name}::{eid}::{det['name']}: UNKNOWN rationale with no adjudication ref"
                    )
    assert unknowns > 0, (
        "no UNKNOWN rationales found — either the catalog became fully justified (great, then relax "
        "this floor deliberately) or the scan stopped reading determinants"
    )


# --------------------------------------------------------------------------- teeth


def _l2a_doc() -> dict:
    return copy.deepcopy(yaml.safe_load((CATALOG / "tumor_presence.yaml").read_text()))


def _l2b_doc() -> dict:
    return copy.deepcopy(yaml.safe_load((CATALOG / "integrated_families.yaml").read_text()))


def _run(tmp_path: Path, name: str, doc: dict) -> "list[str]":
    path = tmp_path / name
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return V.validate_file(path, CARD_INDEX, ALL_IDS, SKILLS).errors


def test_teeth_clean_roundtrip_is_green(tmp_path):
    """The control. Every teeth case below plants ONE defect into this same doc, so if the untouched
    round-trip were already RED the teeth would prove nothing about the defect they planted."""
    assert _run(tmp_path, "tumor_presence.yaml", _l2a_doc()) == []
    assert _run(tmp_path, "integrated_families.yaml", _l2b_doc()) == []


def test_teeth_nonexistent_card_id(tmp_path):
    """Defends: a card renamed or deleted leaving the catalog pointing at nothing — the entry would
    still READ as traceable to a measurement."""
    doc = _l2a_doc()
    doc["properties"]["patient_tumor_abundance"]["observables"][0]["card_id"] = "no-such-card"
    errs = _run(tmp_path, "tumor_presence.yaml", doc)
    assert any("dangling reference" in e for e in errs), errs


def test_teeth_nonexistent_field(tmp_path):
    """Defends the reconstructability contract: the exact defect found live in
    expression_property.enum.yaml, whose `magnitude.resolves_from` names `control_target_percentile`,
    a field that does not exist on its card. Documentation-only there; RED here."""
    doc = _l2a_doc()
    doc["properties"]["patient_tumor_abundance"]["observables"][1]["field"] = "control_target_percentile"
    errs = _run(tmp_path, "tumor_presence.yaml", doc)
    assert any("does not declare summary field" in e for e in errs), errs


def test_teeth_coupled_without_estimates_property(tmp_path):
    """Defends the identifiability test: an observable marked as measuring a different property must
    say WHICH, or `coupled` degenerates into a way to silence the estimator requirement."""
    doc = _l2a_doc()
    obs = doc["properties"]["patient_tumor_abundance"]["observables"][4]
    assert obs["role"] == "coupled"
    del obs["estimates_property"]
    errs = _run(tmp_path, "tumor_presence.yaml", doc)
    assert any("MUST name `estimates_property`" in e for e in errs), errs


def test_teeth_estimates_property_dangling(tmp_path):
    doc = _l2a_doc()
    doc["properties"]["patient_tumor_abundance"]["observables"][4]["estimates_property"] = "not_a_property"
    errs = _run(tmp_path, "tumor_presence.yaml", doc)
    assert any("does not resolve to any catalog entry" in e for e in errs), errs


def test_teeth_property_with_no_estimator(tmp_path):
    """Defends against a property that looks resolved but has admitted no measurement of itself."""
    doc = _l2a_doc()
    for o in doc["properties"]["tumor_elevation_breadth"]["observables"]:
        o["role"] = "coupled"
        o["estimates_property"] = "patient_tumor_abundance"
    errs = _run(tmp_path, "tumor_presence.yaml", doc)
    assert any("has not admitted the measurement" in e for e in errs), errs


def test_teeth_missing_dependence_group(tmp_path):
    doc = _l2a_doc()
    del doc["properties"]["patient_tumor_abundance"]["observables"][0]["dependence_group"]
    errs = _run(tmp_path, "tumor_presence.yaml", doc)
    assert any("dependence_group" in e for e in errs), errs


def test_teeth_misspelled_entry_key_is_not_ignored(tmp_path):
    """THE fail-open this validator's strict allowlist exists for: `determinats:` would otherwise be
    silently ignored AND the real `determinants` reported missing-or-empty, so a file could lose its
    whole threshold record while reading as conformant."""
    doc = _l2a_doc()
    entry = doc["properties"]["patient_tumor_abundance"]
    entry["determinats"] = entry.pop("determinants")
    errs = _run(tmp_path, "tumor_presence.yaml", doc)
    assert any("unknown key `determinats`" in e for e in errs), errs


def test_teeth_untracked_unknown_rationale(tmp_path):
    doc = _l2a_doc()
    det = doc["properties"]["patient_tumor_abundance"]["determinants"][3]
    det["rationale"] = "UNKNOWN — nobody recorded why."
    det["calibration"]["adjudication"] = None
    errs = _run(tmp_path, "tumor_presence.yaml", doc)
    assert any("must be TRACKED" in e for e in errs), errs


def test_teeth_determinant_missing_unit(tmp_path):
    """Defends against the units trap: two thresholds sharing a numeral in different units reconcile
    to a confident wrong answer. A determinant without a unit cannot be reconciled at all."""
    doc = _l2a_doc()
    del doc["properties"]["patient_tumor_abundance"]["determinants"][0]["unit"]
    errs = _run(tmp_path, "tumor_presence.yaml", doc)
    assert any("missing `unit`" in e for e in errs), errs


def test_teeth_determinant_source_path_moved(tmp_path):
    """Defends against a moved/renamed resolver module leaving every rationale pointing at nothing."""
    doc = _l2a_doc()
    doc["properties"]["patient_tumor_abundance"]["determinants"][0]["source"] = "methods/onc_methods/gone/stats.py:24"
    errs = _run(tmp_path, "tumor_presence.yaml", doc)
    assert any("does not exist" in e for e in errs), errs


def test_teeth_determinant_line_drift_is_tolerated(tmp_path):
    """The deliberate NON-failure: line numbers drift on every unrelated edit. If this went RED the
    validator would be unmaintainable and would get disabled, which is worse than line rot."""
    doc = _l2a_doc()
    doc["properties"]["patient_tumor_abundance"]["determinants"][0]["source"] = (
        "methods/onc_methods/tcga_gtex_expression_distribution/stats.py:999999"
    )
    assert _run(tmp_path, "tumor_presence.yaml", doc) == []


def test_teeth_calibration_flip_matrix_path_moved(tmp_path):
    """Defends against the citation that resolves to nothing. `calibration.flip_matrix` and
    `calibration.controls` are how a determinant claims "this number was MEASURED, here is where" —
    a claim that reads identically whether the artifact exists or was deleted three refactors ago.
    Null is legal (nothing recorded yet); a non-empty value pointing nowhere is the defect."""
    doc = _l2a_doc()
    det = doc["properties"]["patient_tumor_abundance"]["determinants"][0]
    det["calibration"]["flip_matrix"] = "methods/tests/calibration/gone/matrix.json"
    errs = _run(tmp_path, "tumor_presence.yaml", doc)
    assert any("flip_matrix" in e and "does not exist" in e for e in errs), errs


def test_teeth_calibration_controls_path_moved(tmp_path):
    """Same clause, the other key — pinned separately so dropping one key from the loop cannot stay
    green on the strength of the other."""
    doc = _l2a_doc()
    det = doc["properties"]["patient_tumor_abundance"]["determinants"][0]
    det["calibration"]["controls"] = "methods/onc_methods/gone_controls/read.py"
    errs = _run(tmp_path, "tumor_presence.yaml", doc)
    assert any("controls" in e and "does not exist" in e for e in errs), errs


def test_teeth_null_calibration_stays_legal(tmp_path):
    """Deliberate NON-failure #1: most determinants have no calibration artifact yet, and saying so
    honestly with `null` must not be punished — otherwise the pressure is to invent a citation."""
    doc = _l2a_doc()
    det = doc["properties"]["patient_tumor_abundance"]["determinants"][0]
    det["calibration"]["flip_matrix"] = None
    det["calibration"]["controls"] = None
    assert _run(tmp_path, "tumor_presence.yaml", doc) == []


def test_teeth_calibration_line_suffix_is_tolerated(tmp_path):
    """Deliberate NON-failure #2: a calibration reference may carry a `:line` suffix like `source`
    does, and line numbers drift on every unrelated edit."""
    doc = _l2a_doc()
    det = doc["properties"]["patient_tumor_abundance"]["determinants"][0]
    det["calibration"]["controls"] = "methods/onc_methods/tumor_presence_controls/read.py:999999"
    assert _run(tmp_path, "tumor_presence.yaml", doc) == []


def test_teeth_fleet_deferred_with_observables(tmp_path):
    """Defends against a property claiming to be unresolvable while quietly resolving something."""
    doc = copy.deepcopy(yaml.safe_load((CATALOG / "expression.yaml").read_text()))
    doc["properties"]["localization"]["observables"] = [
        {
            "card_id": "cellline-rna-distribution",
            "field": "expression_class",
            "role": "estimator",
            "dependence_group": "depmap_rna",
        }
    ]
    errs = _run(tmp_path, "expression.yaml", doc)
    assert any("must carry ZERO observables" in e for e in errs), errs


def test_teeth_fleet_deferred_without_reason(tmp_path):
    doc = copy.deepcopy(yaml.safe_load((CATALOG / "expression.yaml").read_text()))
    del doc["properties"]["localization"]["deferred_pending"]
    errs = _run(tmp_path, "expression.yaml", doc)
    assert any("deferred_pending" in e for e in errs), errs


def test_teeth_family_arms_all_one_dependence_group(tmp_path):
    """THE #1667 tooth. Collapse the selectivity family's groups to one and the family is folding
    CPTAC with TPHP with RNA as three independent arms — the validator must refuse without a waiver."""
    doc = _l2b_doc()
    for arm in doc["families"]["selectivity"]["arms"]:
        arm["dependence_group"] = "protein_ms_tumor"
    errs = _run(tmp_path, "integrated_families.yaml", doc)
    assert any("independence_waiver" in e for e in errs), errs


def test_teeth_family_single_arm(tmp_path):
    doc = _l2b_doc()
    doc["families"]["essentiality"]["arms"] = doc["families"]["essentiality"]["arms"][:1]
    errs = _run(tmp_path, "integrated_families.yaml", doc)
    assert any("integrates >= 2 arms" in e for e in errs), errs


def test_teeth_relation_outside_closed_vocabulary(tmp_path):
    """Defends against a builder inventing a relation the consumer has never seen. The closed set is
    mirrored from dependence_edges.py; drift there and here is the thing to catch."""
    doc = _l2b_doc()
    doc["families"]["essentiality"]["integration"]["relations"] = ["corroborates", "mostly_agrees"]
    errs = _run(tmp_path, "integrated_families.yaml", doc)
    assert any("outside the closed vocabulary" in e for e in errs), errs


def test_teeth_family_missing_integration(tmp_path):
    doc = _l2b_doc()
    del doc["families"]["essentiality"]["integration"]
    errs = _run(tmp_path, "integrated_families.yaml", doc)
    assert any("REQUIRES an `integration`" in e for e in errs), errs


def test_teeth_builder_path_moved(tmp_path):
    doc = _l2b_doc()
    doc["families"]["essentiality"]["integration"]["builder"] = "skills/_skills_common/gone.py"
    errs = _run(tmp_path, "integrated_families.yaml", doc)
    assert any("`builder` path" in e for e in errs), errs


def test_teeth_l2a_carrying_integration(tmp_path):
    """Kind disjointness: an L2a property is per-source by definition, so an `integration` block on
    one means either the kind or the block is wrong."""
    doc = _l2a_doc()
    doc["properties"]["patient_tumor_abundance"]["integration"] = {
        "island_key": "x",
        "builder": "skills/_skills_common/presence_claims.py",
        "builder_function": "_x",
        "comparability": "y",
        "relations": ["corroborates"],
    }
    errs = _run(tmp_path, "tumor_presence.yaml", doc)
    assert any("must NOT carry `arms` or `integration`" in e for e in errs), errs


def test_teeth_catalog_id_must_match_filename(tmp_path):
    doc = _l2a_doc()
    errs = _run(tmp_path, "renamed.yaml", doc)
    assert any("must equal the filename stem" in e for e in errs), errs


def test_teeth_bad_semver(tmp_path):
    doc = _l2a_doc()
    doc["version"] = "1.0"
    errs = _run(tmp_path, "tumor_presence.yaml", doc)
    assert any("semver" in e for e in errs), errs


def test_teeth_empty_governance_clause(tmp_path):
    doc = _l2a_doc()
    doc["governance"]["ownership"] = "   "
    errs = _run(tmp_path, "tumor_presence.yaml", doc)
    assert any("`ownership` must be a non-empty string" in e for e in errs), errs


def test_teeth_nonexistent_consumer_skill(tmp_path):
    doc = _l2a_doc()
    doc["properties"]["patient_tumor_abundance"]["consumers"][0]["skill"] = "no-such-skill"
    errs = _run(tmp_path, "tumor_presence.yaml", doc)
    assert any("has no skills/no-such-skill/" in e for e in errs), errs


def test_teeth_consumer_without_a_read_site(tmp_path):
    doc = _l2a_doc()
    c = doc["properties"]["patient_tumor_abundance"]["consumers"][0]
    c.pop("axis_key", None)
    c.pop("surface", None)
    errs = _run(tmp_path, "tumor_presence.yaml", doc)
    assert any("must say WHERE it reads" in e for e in errs), errs


# --------------------------------------------------------------------------- gate-argv parity
#
# 0a shipped WITHOUT a test that invokes the validator exactly as preland.sh does (literal relative
# argv, cwd contracts/, nothing patched) — 0c later built that habit
# (test_gate_invocation_matches_preland_argv + test_the_two_gate_argv_tests_match_what_preland_sh_
# ACTUALLY_RUNS in test_comparability_state_enum.py) and #2244 backfills it here. Two tests, mirroring
# 0c: the first hardcodes the literal argv the gate is believed to run; the second reads preland.sh
# and pins the wired flags to what the first hardcodes, so an edit to preland.sh that drops or
# reflags this validator's invocation reds HERE instead of leaving the first test green against an
# invocation that no longer exists.


def test_gate_invocation_matches_preland_argv():
    """Invoke the validator EXACTLY as preland.sh's pool step does — cwd contracts/, the literal
    relative argv, nothing patched."""
    proc = subprocess.run(
        [
            sys.executable,
            "validators/validate_property_catalog.py",
            "--catalog",
            "vocabularies/property_catalog",
            "--cards",
            "cards/",
        ],
        cwd=CONTRACTS,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"gate argv failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"


def test_gate_invocation_with_additive_against_matches_preland_argv():
    """Invoke the validator EXACTLY as preland.sh's additivity step does."""
    proc = subprocess.run(
        [
            sys.executable,
            "validators/validate_property_catalog.py",
            "--catalog",
            "vocabularies/property_catalog",
            "--cards",
            "cards/",
            "--additive-against",
            "HEAD",
        ],
        cwd=CONTRACTS,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"gate argv failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"


def test_the_two_gate_argv_tests_match_what_preland_sh_ACTUALLY_RUNS():
    """Copied verbatim (mechanism) from test_comparability_state_enum.py. The two tests above hardcode
    the argv they believe the gate uses — so if someone edits preland.sh they keep passing while
    testing an invocation that no longer exists. This reads the script and pins BOTH wired lines to
    the flags those tests pass. Deliberately a SUBSTRING check on flags, not whole-line equality — the
    label column and line continuations are formatting, and pinning those would red on a reindent.
    """
    # Join backslash continuations FIRST, or this reds on formatting, not on a real drift.
    script = (CONTRACTS / "scripts" / "preland.sh").read_text().replace("\\\n", " ")
    wired = [
        " ".join(ln.split())
        for ln in script.splitlines()
        if "validate_property_catalog.py" in ln and not ln.lstrip().startswith("#")
    ]
    assert len(wired) == 2, (
        f"expected the validator wired TWICE in preland.sh (pool shape clause + additivity), found "
        f"{len(wired)}: {wired}"
    )
    shape, additivity = wired[0], wired[1]
    for flag in (
        "--catalog vocabularies/property_catalog",
        "--cards cards/",
    ):
        assert flag in shape, (
            f"preland.sh shape line is missing {flag!r}; test_gate_invocation_matches_preland_argv is now fiction"
        )
    assert "--additive-against" in additivity, (
        "the second wiring must pass --additive-against, otherwise the token-additivity clause never "
        "runs in the gate and this catalog is governed in name only"
    )


# --------------------------------------------------------------------------- additivity teeth


def test_teeth_additivity_unresolvable_ref_is_red():
    """The anti-fail-open clause. The caller explicitly asked for the additivity check; if the ref
    cannot be resolved, returning green would report a clause as satisfied that never ran."""
    r = V.check_additivity(CATALOG, "definitely-not-a-ref-2210")
    assert not r.ok
    assert any("does not resolve" in e for e in r.errors), r.errors


def test_additivity_runs_on_a_RELATIVE_catalog_path(monkeypatch):
    """Regression: the clause must survive the invocation form preland.sh and CI actually use.

    Every other additivity test passes the absolute `CATALOG` constant and monkeypatches `_git_show`,
    so none of them ever executed the path arithmetic — and the first real run crashed with
    `ValueError: 'vocabularies/property_catalog/expression.yaml' is not in the subpath of <root>`,
    because `git show` needs a REPO-root-relative path while the argument arrives relative to cwd.
    A validator that raises is not a validator that fails: preland.sh reports FAIL either way, but
    the clause is unrun. This test invokes it the way the gate does — cwd contracts/, relative
    --catalog — and asserts the clause ran rather than blew up or self-excused.
    """
    monkeypatch.chdir(CATALOG.parents[1])
    r = V.check_additivity(Path("vocabularies/property_catalog"), "HEAD")
    assert not any("resolves outside the repo root" in e for e in r.errors), r.errors
    # And it must not have taken the anti-fail-open exit either: HEAD resolves in any git checkout,
    # so a "does not resolve" error here would mean the clause silently declined to compare.
    assert not any("does not resolve" in e for e in r.errors), r.errors


def _additivity_against_synthetic(monkeypatch, mutate_prior) -> "list[str]":
    """Run check_additivity with a SYNTHETIC prior built from the live files, so the clause is
    exercised on real content without depending on what happens to be on a git ref."""
    monkeypatch.setattr(
        V,
        "subprocess",
        type(
            "S",
            (),
            {"run": staticmethod(lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})())},
        ),
    )

    def fake_show(ref, rel_path):
        path = V.REPO_ROOT / rel_path
        doc = yaml.safe_load(path.read_text())
        mutate_prior(doc)
        return yaml.safe_dump(doc, sort_keys=False)

    monkeypatch.setattr(V, "_git_show", fake_show)
    return V.check_additivity(CATALOG, "synthetic-prior").errors


def test_teeth_additivity_removal_is_red(monkeypatch):
    """Property ids are published names (#2228's registry references them by id). A removal must be
    a MAJOR bump, never a quiet delete."""

    def mutate(doc):
        section = "families" if doc.get("kind") == "l2b_family" else "properties"
        doc[section]["ghost_property_that_was_removed"] = {"grain": {}}

    errs = _additivity_against_synthetic(monkeypatch, mutate)
    assert any("entries removed" in e for e in errs), errs


def test_teeth_additivity_grain_change_is_red(monkeypatch):
    """Identity is property x grain. Editing an existing entry's grain in place silently redefines
    what every downstream reference means."""

    def mutate(doc):
        section = "families" if doc.get("kind") == "l2b_family" else "properties"
        first = next(iter(doc[section]))
        doc[section][first]["grain"]["sample_context"] = "something_else_entirely"

    errs = _additivity_against_synthetic(monkeypatch, mutate)
    assert any("`grain` changed" in e for e in errs), errs


def test_teeth_additivity_addition_without_version_bump_is_red(monkeypatch):
    def mutate(doc):
        section = "families" if doc.get("kind") == "l2b_family" else "properties"
        doc[section].pop(next(iter(doc[section])))

    errs = _additivity_against_synthetic(monkeypatch, mutate)
    assert any("without bumping `version`" in e for e in errs), errs


def test_teeth_additivity_identical_prior_is_green(monkeypatch):
    """Control for the three cases above: an unchanged prior must be silent, or their REDs would not
    be attributable to the defect each one planted."""
    assert _additivity_against_synthetic(monkeypatch, lambda doc: None) == []
