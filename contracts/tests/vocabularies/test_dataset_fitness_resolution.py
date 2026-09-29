"""dataset_fitness_resolution tests — the threshold layer of the product-grain fitness axis.

Two jobs, and the second is the reason this file is long.

STRUCTURAL: the declared-vs-referenced closure a resolution needs — every signal a rule reads
is declared in `reads`, every `threshold:` reference resolves, every emitted class is a real
enum value, `default` is the enum's own default, priorities are unique, and the artifact stays
OUT of resolvers/ (the reachability guarantee behind never_gates).

BEHAVIOURAL: an INDEPENDENT interpreter of the ladder, run against the 36 measured first-roster
inputs committed in the artifact, checked against the hand-derived `expected` block. The
interpreter is written here from the rule grammar; the expectation was derived by hand from the
measurements. Neither is generated from the other, so a disagreement reds instead of confirming
itself — a fixture of DERIVED values can never fail, so what is stored is the irreproducible
measured INPUT and the class is re-derived on every run.

The load-bearing invariants, each the machine form of something that was measured:
  - `fit` is reachable only by an explicit `when_all`, never by fall-through, and `default` is
    the abstention. A fall-through to the best class is how an absence becomes a compliment.
  - the `fit` conjunction MUST pin comparator_status == both_comparators. A collapsed product
    reports NULL discordance (a lone arm cannot disagree with itself) and a genuine 0.0
    missingness; the null now fails the <=0.15 bound, but the pin is what makes both_comparators
    an EXPLICIT precondition for the best class rather than an emergent side effect of how
    absence happens to serialize — a producer that back-filled a collapsed arm's discordance as
    0.0 (as the old one did, before data-catalog #642) would re-admit exactly the broken products
    (#830 measured 7 of the top 8 / 6 of the best 8). Deleting the pin reds here.
  - every roster_relative threshold records the distribution it was cut from, so a relative cut
    can never be mistaken for an absolute standard.
  - the rung-attribution counts are pinned, so a rung that fires zero times is DECLARED as a
    forward guard rather than silently assumed to be doing work.
"""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
RES_PATH = REPO / "vocabularies" / "dataset_fitness_resolution.yaml"
RES = yaml.safe_load(RES_PATH.read_text())
FITNESS_ENUM = yaml.safe_load((REPO / "vocabularies" / "dataset_fitness_class.enum.yaml").read_text())
AXES = yaml.safe_load((REPO / "vocabularies" / "dataset_profiling_axes.yaml").read_text())

ENUM_VALUES = {v["value"] for v in FITNESS_ENUM["values"]}
THRESHOLD_BASES = {"absolute", "roster_relative"}
# Every field a roster product row must carry. A missing one would silently read as None and
# quietly change a class, so the set is pinned rather than tolerated.
ROSTER_FIELDS = {
    "product_id",
    "quality_measured_present",
    "sampling",
    "primary_value_missingness",
    "dynamic_range",
    "rows_measured",
    "comparator_status",
    "arm_below_floor",
    "discordant_fraction",
}


def _thresholds():
    return {t["id"]: t for t in RES["thresholds"]}


def _reads():
    return {r["signal"]: r for r in RES["reads"]}


def _rules():
    return sorted(RES["resolve"], key=lambda r: r["priority"])


def _clauses(rule):
    return rule.get("when_any", []) + rule.get("when_all", [])


# ==========================================================================
# An INDEPENDENT interpreter of the rule grammar.
# ==========================================================================
def _op(name, actual, expected):
    if name == "is_true":
        return actual is True
    if name == "is_false":
        return actual is False
    if name == "eq":
        return actual == expected
    if name == "in":
        return actual in expected
    # Numeric comparisons: an ABSENT value never satisfies a bound. This matters in both
    # directions — a None must not trip a floor (that would be unfit-by-silence) and must not
    # clear the `fit` conjunction's upper bounds (that would be fit-by-silence).
    if actual is None:
        return False
    return {
        "gt": lambda: actual > expected,
        "gte": lambda: actual >= expected,
        "lt": lambda: actual < expected,
        "lte": lambda: actual <= expected,
    }[name]()


def _clause_holds(clause, product):
    if "threshold" in clause:
        t = _thresholds()[clause["threshold"]]
        return _op(t["op"], product.get(t["signal"]), t.get("value"))
    return _op(clause["op"], product.get(clause["signal"]), clause.get("value"))


def _resolve(product):
    """Return (class, priority_of_deciding_rule) — None priority means the default fired."""
    for rule in _rules():
        if "when_any" in rule and any(_clause_holds(c, product) for c in rule["when_any"]):
            return rule["class"], rule["priority"]
        if "when_all" in rule and all(_clause_holds(c, product) for c in rule["when_all"]):
            return rule["class"], rule["priority"]
    return RES["default"]["class"], None


def _derived():
    return {p["product_id"]: _resolve(p) for p in RES["roster_validation"]["products"]}


# ==========================================================================
# Header + binding
# ==========================================================================
def test_header_is_well_formed():
    assert RES["resolution_id"] == "dataset_fitness_resolution"
    assert RES["version"] == "1.0.0"
    assert RES["keyed_by"] == "product_id"
    assert RES["evaluation"] == "first_match_wins"
    assert RES["description"].strip()


def test_binds_to_the_axis_and_the_enum():
    axis = {a["id"]: a for a in AXES["axes"]}["dataset_fitness"]
    assert RES["axis"] == axis["id"]
    assert RES["emits"] == FITNESS_ENUM["enum_id"]
    assert RES["keyed_by"] == axis["keyed_by"]
    # the axis must point AT this file — a rename that breaks the pointer reds here
    assert axis["resolution_artifact"] == "vocabularies/dataset_fitness_resolution.yaml"


def test_is_a_dimension_that_never_gates():
    assert RES["axis_role"] == "dimension"
    assert RES["never_gates"] is True


def test_artifact_stays_out_of_resolvers():
    """The reachability guarantee, re-pinned at the resolution's own level.

    validate_resolvers.py globs resolvers/*.resolver.yaml; a product-grain resolution landing
    there would be wired into the rule -> resolver -> nomination_verdict_gate chain.
    """
    assert RES_PATH.parent.name == "vocabularies"
    strays = sorted(p.name for p in (REPO / "resolvers").glob("dataset_*.resolver.yaml"))
    assert not strays, f"product-grain resolver(s) in resolvers/: {strays}"


# ==========================================================================
# Declared-vs-referenced closure
# ==========================================================================
def test_every_signal_a_rule_reads_is_declared_in_reads():
    known = set(_reads())
    for rule in _rules():
        for clause in _clauses(rule):
            if "signal" in clause:
                assert clause["signal"] in known, f"{rule['class']} reads undeclared {clause['signal']}"
    for t in RES["thresholds"]:
        assert t["signal"] in known, f"threshold {t['id']} reads undeclared {t['signal']}"


def test_every_threshold_reference_resolves():
    known = set(_thresholds())
    for rule in _rules():
        for clause in _clauses(rule):
            if "threshold" in clause:
                assert clause["threshold"] in known, f"{rule['class']}: unknown threshold {clause['threshold']}"


def test_every_declared_threshold_is_actually_referenced():
    """A threshold nothing reads is a number with no consumer — it reads as governance that is
    not actually in force."""
    referenced = {c["threshold"] for r in _rules() for c in _clauses(r) if "threshold" in c}
    orphans = sorted(set(_thresholds()) - referenced)
    assert not orphans, f"declared but never referenced: {orphans}"


def test_comparator_status_declares_all_six_producer_tokens():
    """#830's registry declares only four; the producer emits six. A token the resolution has
    never seen falls through to the abstention and reads as 'unprofiled' when the truth is
    'measured, and nothing compared'."""
    declared = set(_reads()["comparator_status"]["values"])
    assert declared == {
        "both_comparators",
        "degraded_to_gtex_only",
        "degraded_to_adjacent_only",
        "single_comparator",
        "no_comparator_ran",
        "cohort_not_declared",
    }, sorted(declared)
    # every token must be handled by SOME rule, or it silently defaults
    handled = set()
    for rule in _rules():
        for clause in _clauses(rule):
            if clause.get("signal") == "comparator_status":
                v = clause.get("value")
                handled |= set(v) if isinstance(v, list) else {v}
    unhandled = declared - handled - {"cohort_not_declared"}  # this one defaults BY DESIGN
    assert not unhandled, f"comparator_status token(s) no rule handles: {sorted(unhandled)}"


def test_arm_below_floor_is_a_reason_not_a_predicate():
    """It is subsumed by comparator_status by construction (same min_normals test), so a rung
    keyed on it could never fire. It must appear only as reason enrichment."""
    assert _reads()["arm_below_floor"]["use"] == "reason_detail"
    for rule in _rules():
        for clause in _clauses(rule):
            assert clause.get("signal") != "arm_below_floor", f"{rule['class']} predicates on arm_below_floor"
    consumers = [r for r in _rules() if r.get("reason_detail_from") == "arm_below_floor"]
    assert consumers, "arm_below_floor declared as reason_detail but no rule consumes it"


# ==========================================================================
# Ladder shape
# ==========================================================================
def test_priorities_are_unique_and_classes_are_real():
    prios = [r["priority"] for r in RES["resolve"]]
    assert len(prios) == len(set(prios)), prios
    for rule in _rules():
        assert rule["class"] in ENUM_VALUES, rule["class"]
        assert rule["reason_code"].strip()
        assert rule["rationale"].strip()
        assert ("when_any" in rule) != ("when_all" in rule), f"{rule['class']}: need exactly one of when_any/when_all"


def test_absence_is_evaluated_first():
    """The absence rungs must come FIRST — absence outranks measurement, so a product is never
    scored on evidence that was not collected. There are TWO kinds of absence here and both
    precede every scoring rung: the value probe never ran (priority 10), and the shape signal is
    undecidable (priority 15). The second is what conditions the discordance read further down,
    so its position is load-bearing rather than cosmetic."""
    rules = _rules()
    assert rules[0]["class"] == "not_measured"
    assert rules[1]["class"] == "not_measured"
    assert [r["reason_code"] for r in rules[:2]] == ["not_value_profiled", "shape_undecidable"]
    # every scoring rung sits strictly below both absence rungs
    scoring = [r["priority"] for r in rules if r["class"] != "not_measured"]
    assert min(scoring) > rules[1]["priority"]


def test_fit_is_never_a_fall_through():
    """A fall-through to the BEST class is how an absence becomes a compliment."""
    assert RES["default"]["class"] != "fit"
    assert RES["default"]["class"] == FITNESS_ENUM["default"]
    fit = [r for r in _rules() if r["class"] == "fit"][0]
    assert "when_all" in fit, "fit must be an explicit conjunction, not an any-match"
    assert "when_any" not in fit
    assert fit["priority"] == max(r["priority"] for r in RES["resolve"]), "fit must be evaluated last"


def test_fit_conjunction_pins_the_comparator_shape():
    """THE load-bearing invariant of this file.

    The `fit` conjunction bounds two shape-confounded signals (discordant_fraction <= 0.15,
    primary_value_missingness <= 0.25). A COLLAPSED product reports NULL discordance (a single
    live comparator has nothing to disagree with, so the producer emits null — data-catalog
    #642) and a genuine 0.0 missingness: the null now fails the discordance bound, so the pin is
    not the ONLY thing blocking promotion on this roster. But the pin is what makes
    `comparator_status == both_comparators` an EXPLICIT precondition rather than an emergent
    property of how absence serializes — the old producer back-filled that discordance as 0.0,
    which SATISFIED the bound, and without the pin the best class was reachable by exactly the
    products #830 measured as ranking best-by-breakage. Removing the pin reds here.
    """
    fit = [r for r in _rules() if r["class"] == "fit"][0]
    pins = [
        c
        for c in fit["when_all"]
        if c.get("signal") == "comparator_status" and c.get("op") == "eq" and c.get("value") == "both_comparators"
    ]
    assert pins, "fit does not pin comparator_status == both_comparators"


def test_shape_confounded_signals_are_never_read_as_promoters():
    """A shape-confounded signal may only appear as a demoting bound or as an upper bound inside
    the shape-pinned `fit` conjunction. It may never be independently sufficient to land a
    product in a class better than a demotion."""
    reads = _reads()
    confounded = {s for s, r in reads.items() if r.get("shape_confounded") is True}
    assert confounded, "no shape_confounded signals declared — did the reads block lose the field?"
    for rule in _rules():
        # in an ANY rule every clause is independently sufficient. That is safe only where the
        # class is a DEMOTION (unfit, fit_with_caveats, not_measured); it is not safe for a class
        # that describes the product as better-scoped than a demotion.
        if rule["class"] not in ("partially_fit", "fit") or "when_any" not in rule:
            continue
        for clause in rule["when_any"]:
            sig = clause.get("signal") or _thresholds()[clause["threshold"]]["signal"]
            assert sig not in confounded, f"{rule['class']} promotable from confounded signal {sig}"


def test_every_threshold_declares_its_basis_and_relative_ones_show_the_distribution():
    for t in RES["thresholds"]:
        assert t["basis"] in THRESHOLD_BASES, f"{t['id']}: basis {t.get('basis')}"
        assert t["rationale"].strip(), f"{t['id']}: no rationale"
        if t["basis"] == "roster_relative":
            assert t.get("distribution", "").strip(), (
                f"{t['id']}: a roster-relative cut must record the distribution it came from, "
                "or it reads as an absolute standard"
            )


def test_discordance_is_conditioned_on_resolved_shape():
    """discordant_fraction is shape-confounded in the same direction as the pooled signals (7 of
    8 collapsed products report NULL — a lone arm cannot disagree with itself). It is only
    readable within the both_comparators partition, which the ladder buys by ORDERING: its rung
    must sit strictly below the rung that resolves shape."""
    reads = _reads()
    assert reads["discordant_fraction"]["use"] == "within_shape_only"
    assert reads["discordant_fraction"].get("conditioned_on", "").strip()
    shape_rung = [r for r in _rules() if r["class"] == "partially_fit"][0]["priority"]
    users = [
        r["priority"]
        for r in _rules()
        for c in _clauses(r)
        if c.get("signal") == "discordant_fraction"
        or (c.get("threshold") and _thresholds()[c["threshold"]]["signal"] == "discordant_fraction")
    ]
    assert users, "discordant_fraction declared but unused"
    assert min(users) > shape_rung, (
        f"discordance read at priority {min(users)} <= the shape rung {shape_rung}: it would be "
        "evaluated before shape is resolved, where its zero is manufactured by arm loss"
    )


# ==========================================================================
# Roster re-derivation
# ==========================================================================
def test_roster_is_complete_and_well_formed():
    """Anti-vacuity: the behavioural tests below iterate the roster, so an empty or truncated
    roster would make every one of them pass while checking nothing."""
    products = RES["roster_validation"]["products"]
    assert len(products) == RES["roster_validation"]["n_products"] == 36
    ids = [p["product_id"] for p in products]
    assert len(set(ids)) == 36, "duplicate product_id in the roster"
    for p in products:
        assert set(p) == ROSTER_FIELDS, f"{p['product_id']}: fields {sorted(set(p) ^ ROSTER_FIELDS)}"


def test_every_product_resolves_to_a_declared_class():
    for pid, (cls, _) in _derived().items():
        assert cls in ENUM_VALUES, f"{pid} -> {cls}"


def test_the_ladder_is_not_degenerate():
    """If every product landed in one class the counts could still match a typo'd expectation."""
    classes = {cls for cls, _ in _derived().values()}
    assert len(classes) >= 4, f"ladder discriminates only {sorted(classes)}"


def test_derived_class_counts_match_the_hand_derived_expectation():
    from collections import Counter

    got = Counter(cls for cls, _ in _derived().values())
    expected = RES["roster_validation"]["expected"]["class_counts"]
    assert dict(got) == {k: v for k, v in expected.items() if v}, f"got {dict(got)} expected {expected}"
    assert sum(expected.values()) == 36


def test_named_membership_matches_for_every_non_fit_class():
    """A count alone cannot catch a swap between two products of the same class size."""
    derived = _derived()
    expected = RES["roster_validation"]["expected"]
    for cls in ("partially_fit", "fit_with_caveats", "unfit", "not_measured"):
        got = sorted(pid for pid, (c, _) in derived.items() if c == cls)
        assert got == sorted(expected[cls]), f"{cls}: got {got} expected {sorted(expected[cls])}"


def test_rung_attribution_matches_the_declared_firing_counts():
    """Pins WHICH rung decided each product, so a rung that fires zero times is declared as a
    forward guard instead of being assumed to be doing work. A refactor that moved a product
    between two rungs emitting the same class would pass the count test and red here."""
    from collections import Counter

    by_rung = Counter()
    for cls, prio in _derived().values():
        by_rung[prio if prio is not None else "default"] += 1
    declared = RES["roster_validation"]["rungs_fired_on_first_roster"]
    got = {
        "priority_10_not_measured": by_rung[10],
        "priority_15_not_measured": by_rung[15],
        "priority_20_unfit": by_rung[20],
        "priority_30_partially_fit": by_rung[30],
        "priority_40_fit_with_caveats": by_rung[40],
        "priority_50_fit": by_rung[50],
        "default_not_measured": by_rung["default"],
    }
    assert got == declared, f"got {got} declared {declared}"
    assert sum(got.values()) == 36


def test_the_unfired_value_floors_are_declared_as_forward_guards():
    """Three absolute floors fire zero times on the first roster. That is fine and intended, but
    it must be STATED — an unfired rung whose rationale claims validation would be a threshold
    asserting evidence it does not have."""
    for tid in ("missingness_unusable", "dynamic_range_flat", "rows_too_thin"):
        t = _thresholds()[tid]
        assert t["basis"] == "absolute", tid
        assert "UNFIRED" in t["rationale"], f"{tid}: unfired on this roster but not declared so"
    # and confirm they really are unfired, rather than trusting the comment
    for p in RES["roster_validation"]["products"]:
        for tid in ("missingness_unusable", "dynamic_range_flat", "rows_too_thin"):
            assert not _clause_holds({"threshold": tid}, p), f"{p['product_id']} trips {tid}"


def test_collapsed_products_are_not_promoted_by_their_clean_value_signals():
    """The measured inversion, checked end to end rather than by declaration.

    The 8 collapsed products report the BEST values on the pooled signals: 6 of them exactly 0.0
    missingness, and discordance is NULL for 7 of them (undefined — a lone arm cannot disagree
    with itself, so the producer emits null rather than the fabricated 0.0 it used to; data-
    catalog #642). Every one of them must still land in partially_fit, never fit or
    fit_with_caveats.
    """
    derived = _derived()
    collapsed = [
        p
        for p in RES["roster_validation"]["products"]
        if p["comparator_status"] in ("degraded_to_gtex_only", "degraded_to_adjacent_only", "single_comparator")
    ]
    assert len(collapsed) == 8, len(collapsed)
    for p in collapsed:
        cls, prio = derived[p["product_id"]]
        assert cls == "partially_fit", (
            f"{p['product_id']} -> {cls} (missingness {p['primary_value_missingness']}, "
            f"discordance {p['discordant_fraction']})"
        )
        assert prio == 30
    # the premise, anti-vacuous in both halves: 6 collapsed products report a genuine 0.0
    # missingness (they really do look cleanest on that pooled signal, and are still not
    # promoted), and discordance is NULL for 7 of the 8 -- undefined, not a fabricated 0.0
    # (data-catalog #642) -- so a discordance <= 0.15 bound cannot be what would promote them.
    assert sum(1 for p in collapsed if p["primary_value_missingness"] == 0.0) == 6
    assert sum(1 for p in collapsed if p["discordant_fraction"] is None) == 7
    # and no collapsed product carries a spurious 0.0 discordance any more (regression guard)
    assert sum(1 for p in collapsed if p["discordant_fraction"] == 0.0) == 0


def test_cohort_not_declared_abstains_rather_than_scoring():
    """#830 is explicit that cohort_not_declared is an abstention, never a failure. These
    products ARE value-profiled, so the risk is the opposite of unfit — it is that they get
    promoted to `fit` on value signals while the silent-degradation check was never possible."""
    derived = _derived()
    undeclared = [p for p in RES["roster_validation"]["products"] if p["comparator_status"] == "cohort_not_declared"]
    assert len(undeclared) == 7, len(undeclared)
    for p in undeclared:
        cls, _ = derived[p["product_id"]]
        assert cls == "not_measured", f"{p['product_id']} -> {cls}"
