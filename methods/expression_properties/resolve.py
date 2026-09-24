"""Deterministic resolver: Card-1 (cellline-rna-distribution) measurements → the shared L2
expression-property vocabulary.

This is P2 of the evidence-property architecture (epic claude-oncology-skills#1507; audit #1506;
vocabulary P1 = target-contracts vocabularies/expression_property.enum.yaml, merged #865). The
thesis: the SAME objective measurements resolve a small set of ORTHOGONAL, cross-skill biological
PROPERTIES — not an ever-richer per-card `expression_class`. This module resolves them for the
cell-line arm; the tumor arm (tcga_gtex_expression_distribution) resolves the same properties from
its own measurements, and P4 carries them on the claim atom.

WHY THIS EXISTS (the buried-signal rescue). Card 1 already computes `distribution_pattern=bimodal`
for EPCAM, but `_classify_expression` (depmap_expression_distribution/cli.py) never reads it, so
EPCAM collapses to `broadly_moderate` and the shape signal is silently dropped — while its tumor
twin, which DOES consume shape, reads `subset_high`. This resolver makes the same measurements
resolve `heterogeneity=high` + `prevalence=subset` for EPCAM, recovering the dropped signal WITHOUT
touching `expression_class` (which stays byte-identical — the pilot's verdict-inert invariant).

ARM AGREEMENT. The prevalence/heterogeneity "distinct high subset" call reuses the tumor twin's
`subset_high` shape thresholds so the two arms agree on the same distribution:
  - tumor: `_classify_tumor_expression` @ tcga_gtex_expression_distribution/read.py:862 —
    `pattern ∈ {bimodal, long_tail} ∧ high_fraction >= 0.1` → `subset_high`
    (and `high_fraction >= 0.5` → `broadly_high`, `detectable >= 0.7` → broadly detected).
  - the shape itself: `_distribution_pattern` @ depmap_expression_distribution/cli.py:208.
The thresholds below mirror those literals; a comment cites each source. Keeping them named + local
(not imported) avoids a runtime cell-line→tumor coupling, but they must move together — the pinned
tests document the correspondence.

PURITY / TESTABILITY. `resolve_expression_properties` is a pure function of the summary dict — no
I/O, no numpy. Every value is a token from the P1 vocabulary; a property an arm cannot resolve emits
the literal ``"unmeasured"`` (signal_ord null — a GAP, never a zero tier: unmeasured ≠ absent).
"""

from __future__ import annotations

from typing import Optional

# --- Vocabulary tokens (mirror target-contracts vocabularies/expression_property.enum.yaml v1.0.0).
# Documented here so this module is self-describing; a test cross-checks them against the enum when
# the target-contracts checkout is reachable. A token change is a BREAKING contract change (see the
# enum's governance block) — coordinate via the wip-registry.
VALID_VALUES: dict[str, tuple[str, ...]] = {
    "presence": ("supported", "weak", "absent", "unmeasured"),
    "magnitude": ("high", "moderate", "low", "unmeasured"),
    "prevalence": ("broad", "subset", "rare", "unmeasured"),
    "heterogeneity": ("high", "moderate", "uniform", "unmeasured"),
    "lineage_restriction": ("restricted", "intermediate", "diffuse", "unmeasured"),
    # fleet-deferred (declared to reserve the shared name; value set governed in the fleet phase).
    "selectivity": ("unmeasured",),
    "localization": ("unmeasured",),
    "subtype_restriction": ("unmeasured",),
}

# Properties that Card-1 cannot resolve from a single cell-line RNA panel — always `unmeasured`
# (NULL, not zero). They need a normal-tissue / subtype / protein-localization comparator.
_FLEET_DEFERRED = ("selectivity", "localization", "subtype_restriction")

# --- Thresholds. The shape-related ones MIRROR the tumor twin (arm agreement); the rest mirror the
# cell-line `_classify_expression` knobs and the DepMap log2(TPM+1) detection floors.
_BIMODAL_PATTERNS = frozenset({"bimodal", "long_tail"})

# DepMap detection floors (log2(TPM+1)); mirror depmap_expression_distribution _EXPRESSED/_HIGHLY.
_EXPRESSED_LOG2TPM = 1.0
_HIGHLY_EXPRESSED_LOG2TPM = 5.0

# subset_high anchor: a distinct target-high subpopulation on a shaped distribution.
# Mirrors tcga_gtex_expression_distribution/read.py:862 (`high_fraction >= 0.1`).
_SUBSET_HIGH_FRACTION_MIN = 0.1
# broadly_high anchor: a MAJORITY highly-express → prevalence=broad.
# Mirrors tcga_gtex_expression_distribution/read.py:860 (`high_fraction >= 0.5`).
_BROADLY_HIGH_FRACTION_MIN = 0.5
# broadly-detected / broadly-expressed: expressed across most of the panel.
# Mirrors cli._classify_expression broadly_expressed_fraction (0.70) and the twin's `>= 0.7`.
_BROAD_EXPRESSED_FRACTION = 0.70
# A substantial highly-expressing subpopulation even without a called bimodal/long_tail shape.
_SUBSTANTIAL_SUBSET_HIGH_FRACTION = 0.20

# presence tiers on the expressed fraction (+ a corroborating panel median).
_PRESENCE_SUPPORTED_FRACTION = 0.50  # expressed in a majority → clearly present
_PRESENCE_SUPPORTED_MEDIAN_FRACTION = 0.30  # a solid median rescues a subset-level fraction to supported
_PRESENCE_FLOOR_FRACTION = 0.10  # below this AND no expressing median → a measured `absent`
# prevalence: expressed in only a small fraction → rare.
_RARE_FRACTION = 0.10

# heterogeneity from the coefficient of variation (linear-TPM CoV; see cli._coefficient_of_variation).
# Bimodal panels sit well above _CV_HIGH (cf. tests/.../test_shape_metrics: bimodal CoV > 0.5); the
# tiers give heterogeneity a SECOND, independent supply besides distribution_pattern.
_CV_HIGH = 0.75
_CV_MODERATE = 0.35

# magnitude from the all-gene percentile position (0-100) with a median fallback.
_MAGNITUDE_HIGH_PERCENTILE = 75.0
_MAGNITUDE_MODERATE_PERCENTILE = 25.0

# lineage_restriction: share of evaluated lineages that are restricted-drivers (enriched ≥0.4 above
# the panel). A minority of lineages carrying expression → restricted; a majority → intermediate.
_LINEAGE_RESTRICTED_MAX_SHARE = 0.5


def _presence(summary: dict) -> str:
    """Is the target expressed at a detectable level in the panel? (monotone presence-polarity)

    Supplies: fraction_expressed (primary breadth-above-floor) corroborated by median_log2tpm_panel.
    """
    fe = summary.get("fraction_expressed")
    med = summary.get("median_log2tpm_panel")
    if fe is None and med is None:
        return "unmeasured"
    fe0 = fe if fe is not None else 0.0
    median_expressing = med is not None and med >= _EXPRESSED_LOG2TPM
    # supported: expressed across a majority, OR a solidly-expressing median with a real fraction.
    if fe0 >= _PRESENCE_SUPPORTED_FRACTION or (median_expressing and fe0 >= _PRESENCE_SUPPORTED_MEDIAN_FRACTION):
        return "supported"
    # absent: essentially nothing above the detection floor — a MEASURED negative, not a gap.
    if fe0 < _PRESENCE_FLOOR_FRACTION and not median_expressing:
        return "absent"
    # weak: detected, but near the floor / in a thin fraction.
    return "weak"


def _magnitude(summary: dict, presence_value: str) -> str:
    """How high is expression WHERE present? (monotone; conditional on presence)

    Supplies: control_target_percentile / allgene_percentile (all-gene position), median_log2tpm_panel,
    fraction_highly_expressed. Conditional on presence: presence=absent → `unmeasured` (no level to grade).
    """
    if presence_value == "absent":
        return "unmeasured"
    med = summary.get("median_log2tpm_panel")
    pct = summary.get("control_target_percentile")
    if pct is None:
        pct = summary.get("allgene_percentile")
    fh = summary.get("fraction_highly_expressed")
    if med is None and pct is None:
        return "unmeasured"
    if (
        (pct is not None and pct >= _MAGNITUDE_HIGH_PERCENTILE)
        or (med is not None and med >= _HIGHLY_EXPRESSED_LOG2TPM)
        or (fh is not None and fh >= _BROADLY_HIGH_FRACTION_MIN)
    ):
        return "high"
    if (pct is not None and pct >= _MAGNITUDE_MODERATE_PERCENTILE) or (med is not None and med >= _EXPRESSED_LOG2TPM):
        return "moderate"
    return "low"


def _prevalence(summary: dict) -> str:
    """In how much of the panel is it expressed? (monotone presence-polarity)

    Supplies: fraction_expressed, fraction_highly_expressed, distribution_pattern. The subset/broad
    decision ORDER mirrors the tumor twin's `_classify_tumor_expression` so the arms agree (broadly_high
    before subset_high before broadly_detected).
    """
    fe = summary.get("fraction_expressed")
    fh = summary.get("fraction_highly_expressed")
    pattern = summary.get("distribution_pattern")
    if fe is None and fh is None:
        return "unmeasured"
    fe0 = fe if fe is not None else 0.0
    fh0 = fh if fh is not None else 0.0
    # 1. twin broadly_high: a MAJORITY highly-express → broad (read.py:860).
    if fh is not None and fh0 >= _BROADLY_HIGH_FRACTION_MIN:
        return "broad"
    # 2. twin subset_high: a distinct high subset on a shaped distribution → subset (read.py:862).
    #    This is the buried signal — a bimodal EPCAM lands here, co-occurring with heterogeneity=high.
    if pattern in _BIMODAL_PATTERNS and fh0 >= _SUBSET_HIGH_FRACTION_MIN:
        return "subset"
    # 3. broadly detected across the panel → broad.
    if fe is not None and fe0 >= _BROAD_EXPRESSED_FRACTION:
        return "broad"
    # 4. only a small fraction expresses → rare.
    if fe is not None and fe0 < _RARE_FRACTION:
        return "rare"
    # 5. a substantial highly-expressing subpopulation without a called shape → subset.
    if fh is not None and fh0 >= _SUBSTANTIAL_SUBSET_HIGH_FRACTION:
        return "subset"
    # 6. detected in a substantial-but-not-whole-panel fraction → subset.
    return "subset"


def _heterogeneity(summary: dict) -> str:
    """How variable is expression across the panel? (DESCRIPTIVE — tier = amount of heterogeneity)

    Supplies: distribution_pattern (bimodal/long_tail → high) AND coefficient_of_variation (an
    independent second supply). No `absent` value — `uniform` is the measured low end.
    """
    pattern = summary.get("distribution_pattern")
    cv = summary.get("coefficient_of_variation")
    if pattern is None and cv is None:
        return "unmeasured"
    if pattern in _BIMODAL_PATTERNS or (cv is not None and cv >= _CV_HIGH):
        return "high"
    if cv is not None and cv >= _CV_MODERATE:
        return "moderate"
    return "uniform"


def _lineage_restriction(summary: dict) -> str:
    """Is expression confined to few lineages? (DESCRIPTIVE — tier = degree of restriction)

    Supplies: n_lineage_restricted_lineages, per_lineage_stats / n_lineages_evaluated. Mirrors the
    cell-line `_classify_expression` lineage-restricted driver (a lineage enriched ≥0.4 above panel).
    """
    nlr = summary.get("n_lineage_restricted_lineages")
    n_eval = summary.get("n_lineages_evaluated")
    if n_eval is None:
        per = summary.get("per_lineage_stats")
        n_eval = len(per) if per else 0
    if nlr is None or not n_eval:
        return "unmeasured"
    if nlr <= 0:
        return "diffuse"
    if (nlr / n_eval) <= _LINEAGE_RESTRICTED_MAX_SHARE:
        return "restricted"
    return "intermediate"


def resolve_expression_properties(summary: Optional[dict]) -> dict:
    """Resolve the shared L2 expression properties from a Card-1 summary dict.

    Maps EXISTING cellline-rna-distribution measurements into the P1 vocabulary
    (expression_property.enum.yaml). Pure + deterministic; verdict-inert (never touches
    expression_class). Every value is a vocabulary token; an unresolvable property → ``"unmeasured"``
    (a NULL, never a zero tier). A ``None`` / empty / data_unavailable summary → all `unmeasured`.

    Returns a dict keyed by property id (presence, magnitude, prevalence, heterogeneity,
    lineage_restriction, selectivity, localization, subtype_restriction).
    """
    if not summary or summary.get("_no_data") or summary.get("expression_class") == "data_unavailable":
        props = {p: "unmeasured" for p in VALID_VALUES}
        return props

    presence = _presence(summary)
    props = {
        "presence": presence,
        "magnitude": _magnitude(summary, presence),
        "prevalence": _prevalence(summary),
        "heterogeneity": _heterogeneity(summary),
        "lineage_restriction": _lineage_restriction(summary),
    }
    for name in _FLEET_DEFERRED:
        props[name] = "unmeasured"
    return props
