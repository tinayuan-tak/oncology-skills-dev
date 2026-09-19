"""dataset_profiling_axes registry tests — the PRODUCT-GRAIN axis registry.

The product-grain sibling of target_profiling_axes.yaml: same grammar rotated 90 degrees from
(target x indication) onto product_id. See docs/design/DATASET_FITNESS_AXIS.md.

These pins:
  - the header is well-formed, versioned, keyed by product_id, and its `parallel_to` pointer
    resolves to a file that actually exists (a rename of the target registry reds here),
  - every signal declares `readable_directionally` AND `shape_confounded`, and every shape-confounded
    one carries the panel measurement that established it,
  - the MEASURED INVERSION is pinned: significant_fraction stays non-directional and keeps its
    supporting measurement block. Flipping it back to directional reds this test.
  - THE LOAD-BEARING INVARIANT (two forms): no non-directional signal, and — the stronger, panel-
    validated form that caught the missingness defect — no SHAPE-CONFOUNDED signal, may hold the
    `primary` role. A signal whose level is set by the product's comparator SHAPE (not its data
    quality) ranks collapsed products best, so only sampling is a value-level primary; the class is
    otherwise set by the SHAPE signals read deliberately.
  - declared-vs-referenced closure: every signal named in an axis role resolves to signal_vocab,
    every axis `emits` resolves to the real enum, and `default_class` is that enum's own default,
  - the PLACEMENT guarantee: the fitness resolution artifact is NOT under resolvers/, and no
    resolvers/dataset_fitness*.resolver.yaml exists. That absence is what makes never_gates
    structural (reachability) rather than conventional — validate_resolvers.py globs that
    directory, so a file landing there would wire a product-grain axis into the nomination chain.
"""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
REG_PATH = REPO / "vocabularies" / "dataset_profiling_axes.yaml"
REG = yaml.safe_load(REG_PATH.read_text())
FITNESS_ENUM = yaml.safe_load((REPO / "vocabularies" / "dataset_fitness_class.enum.yaml").read_text())

# The pinned signal set. Adding/removing a signal is a deliberate registry decision.
EXPECTED_SIGNALS = {
    "rows_measured",
    "sampling",
    "primary_value_missingness",
    "dynamic_range",
    "significant_fraction",
}
ROLE_VOCAB = {"primary", "floor_only", "context_only"}


def _signals():
    return {s["id"]: s for s in REG["signal_vocab"]}


def _axes():
    return {a["id"]: a for a in REG["axes"]}


# --------------------------------------------------------------------------
# Header + shape
# --------------------------------------------------------------------------
def test_registry_header_is_well_formed():
    assert REG["registry_id"] == "dataset_profiling_axes"
    assert REG["version"] == "1.0.0"
    assert REG["keyed_by"] == "product_id"
    assert REG["description"].strip()


def test_parallel_to_pointer_resolves():
    # a rename of the target-grain registry must not leave a dangling cross-reference here
    assert (REPO / REG["parallel_to"]).is_file(), REG["parallel_to"]


def test_standing_vocab_covers_the_abstention():
    assert set(REG["standing_vocab"]) == {"measured", "partial", "not_measured"}
    assert all(v.strip() for v in REG["standing_vocab"].values())


# --------------------------------------------------------------------------
# Signal vocabulary
# --------------------------------------------------------------------------
def test_signal_set_is_pinned():
    assert set(_signals()) == EXPECTED_SIGNALS


def test_every_signal_declares_direction_and_null_semantics():
    for sid, s in _signals().items():
        assert isinstance(s.get("readable_directionally"), bool), f"{sid}: direction undeclared"
        assert isinstance(s.get("shape_confounded"), bool), f"{sid}: shape_confounded undeclared"
        assert s.get("direction_note", "").strip(), f"{sid}: no direction_note"
        assert s.get("null_semantics", "").strip(), f"{sid}: no null_semantics"
        assert s.get("dtype"), f"{sid}: no dtype"


def test_only_sampling_is_not_shape_confounded():
    """Panel finding: every pooled value-level signal's LEVEL is set by comparator/arm SHAPE,
    not data quality. sampling (a read-completeness fact about the probe) is the sole exception."""
    signals = _signals()
    not_confounded = {sid for sid, s in signals.items() if s["shape_confounded"] is False}
    assert not_confounded == {"sampling"}, not_confounded
    # each shape_confounded signal must carry the measurement that established it
    for sid, s in signals.items():
        if s["shape_confounded"] and sid != "rows_measured":  # rows: a size, self-evidently structural
            m = s.get("measurement", {})
            assert m.get("consequence", "").strip(), f"{sid}: shape_confounded but no measurement.consequence"


def test_sampling_enumerates_the_skipped_too_large_abstention():
    # the honest abstention path: the object was never read, so nothing is known about it
    s = _signals()["sampling"]
    assert "skipped_too_large" in s["values"]
    assert "not_measured" in s["direction_note"]


def test_significant_fraction_stays_non_directional_with_its_measurement():
    """Regression pin on the inversion finding. Flipping this to directional reds here."""
    s = _signals()["significant_fraction"]
    assert s["readable_directionally"] is False
    assert s["inverted_on_first_roster"] is True
    m = s["measurement"]
    for key in ("roster", "structural_invariant", "paired_within_dataset", "between_group", "consequence"):
        assert m.get(key, "").strip(), f"measurement.{key} missing"
    # the bracketing invariant is the load-bearing evidence — it must stay stated, with its count
    assert "33/33" in m["structural_invariant"]
    assert "24/24" in m["paired_within_dataset"]


# --------------------------------------------------------------------------
# THE LOAD-BEARING INVARIANT
# --------------------------------------------------------------------------
def test_no_non_directional_signal_holds_the_primary_role():
    """A signal whose level is set by product SHAPE must never drive a class boundary.

    Ranking on significant_fraction rewards losing a comparator (7 of the top 8 on the first
    roster are single-comparator degraded products). A non-directional signal may act as a
    FLOOR (demote only) or as CONTEXT (reported, never ranked) — never as primary.
    """
    signals = _signals()
    offenders = []
    for aid, axis in _axes().items():
        for entry in axis.get("signal_roles", []):
            sid = entry["signal"]
            if entry["role"] == "primary" and signals[sid]["readable_directionally"] is False:
                offenders.append(f"{aid}:{sid}")
    assert not offenders, f"non-directional signal(s) given the primary role: {offenders}"


def test_no_shape_confounded_signal_holds_primary():
    """The stronger, panel-validated form of the invariant, and the one that caught the missingness
    defect. `readable_directionally` alone is too weak: primary_value_missingness is monotone WITHIN
    a shape (directional=True) yet its cross-product level is a serialization artifact — 6 of the
    best 8 by low missingness are collapsed-arm products, and the SAME degradation lands at 0.0 or
    0.67 depending only on whether the dead column was dropped or NaN-serialized. A signal whose
    level is set by SHAPE must never rank products, so only sampling may be primary among value
    signals; everything else that sets the class is a shape_signal read deliberately.
    """
    signals = _signals()
    offenders = []
    for aid, axis in _axes().items():
        for entry in axis.get("signal_roles", []):
            sid = entry["signal"]
            if entry["role"] == "primary" and signals[sid]["shape_confounded"] is True:
                offenders.append(f"{aid}:{sid}")
    assert not offenders, (
        f"shape-confounded signal(s) given the primary role (rank collapsed products best): {offenders}"
    )


def test_missingness_is_floor_only_not_primary():
    """Regression pin on the panel finding: missingness was demoted from primary to floor_only
    because low missingness is manufactured by comparator collapse. Restoring it to primary reds."""
    for aid, axis in _axes().items():
        for entry in axis.get("signal_roles", []):
            if entry["signal"] == "primary_value_missingness":
                assert entry["role"] == "floor_only", f"{aid}: {entry['role']}"


def test_significant_fraction_is_context_only_everywhere():
    for aid, axis in _axes().items():
        for entry in axis.get("signal_roles", []):
            if entry["signal"] == "significant_fraction":
                assert entry["role"] == "context_only", f"{aid}: {entry['role']}"


# --------------------------------------------------------------------------
# Declared-vs-referenced closure
# --------------------------------------------------------------------------
def test_every_referenced_signal_is_declared():
    known = set(_signals())
    for aid, axis in _axes().items():
        for entry in axis.get("signal_roles", []):
            assert entry["signal"] in known, f"{aid} reads undeclared signal {entry['signal']}"
            assert entry["role"] in ROLE_VOCAB, f"{aid}:{entry['signal']} bad role {entry['role']}"
            assert entry.get("use", "").strip(), f"{aid}:{entry['signal']} no use note"


def test_shape_signals_are_distinct_from_quality_measured_signals():
    """Shape signals come from DECLARED cohort metadata, not from quality.measured — keeping the
    namespaces disjoint is what stops a value-level signal being smuggled in as a shape read."""
    value_level = set(_signals())
    for aid, axis in _axes().items():
        for entry in axis.get("shape_signals", []):
            assert entry["signal"] not in value_level, f"{aid}: {entry['signal']} is a value-level signal"
            assert entry["role"] in ROLE_VOCAB
            assert entry.get("emitted_by", "").strip()
            assert entry.get("use", "").strip()


# --------------------------------------------------------------------------
# Axis wiring
# --------------------------------------------------------------------------
def test_dataset_fitness_axis_binds_to_the_real_enum():
    axis = _axes()["dataset_fitness"]
    assert axis["emits"] == FITNESS_ENUM["enum_id"]
    assert axis["keyed_by"] == "product_id"
    values = {v["value"] for v in FITNESS_ENUM["values"]}
    assert axis["default_class"] in values
    # the registry's default must BE the enum's declared default, not merely a legal value
    assert axis["default_class"] == FITNESS_ENUM["default"]
    assert axis["standing"] in REG["standing_vocab"]


def test_every_axis_is_a_dimension_that_reports_into_nothing():
    for aid, axis in _axes().items():
        assert axis["axis_role"] == "dimension", aid
        assert axis["never_gates"] is True, aid
        assert axis["reports_into"] == [], f"{aid} reports into {axis['reports_into']}"
        assert axis.get("reports_into_note", "").strip(), aid
        assert axis.get("question", "").strip(), aid


# --------------------------------------------------------------------------
# PLACEMENT — the reachability guarantee behind never_gates
# --------------------------------------------------------------------------
def test_resolution_artifact_is_not_under_resolvers():
    for aid, axis in _axes().items():
        target = axis["resolution_artifact"]
        assert not target.startswith("resolvers/"), (
            f"{aid}: a product-grain resolution under resolvers/ would be globbed by "
            f"validate_resolvers.py and wired into the nomination chain — got {target}"
        )


def test_no_product_grain_resolver_file_exists():
    """The absence that makes never_gates structural rather than conventional."""
    strays = sorted(p.name for p in (REPO / "resolvers").glob("dataset_*.resolver.yaml"))
    assert not strays, f"product-grain resolver(s) in resolvers/: {strays}"


def test_placement_rationale_is_recorded_in_the_registry():
    # the WHY must survive in the artifact, not just in a PR description
    head = REG_PATH.read_text()
    assert "validate_resolvers.py" in head
    assert "REACHABILITY" in head


# --------------------------------------------------------------------------
# Open question is recorded, not silently defaulted
# --------------------------------------------------------------------------
def test_open_question_is_declared_with_its_measurement():
    oq = {q["id"]: q for q in REG["open_questions"]}
    q = oq["discordance_feeds_partially_fit"]
    assert q["status"] == "awaiting_decision"
    assert q["measured_today"].strip()
    # the hnsc counterexample is the reason the question is not trivially answerable
    assert "hnsc" in q["measured_today"]
