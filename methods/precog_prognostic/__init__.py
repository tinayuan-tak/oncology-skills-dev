"""precog_prognostic — per-(gene x indication) PRECOG prognostic meta-Z facet (Gentles 2015 + 2026 NAR).

Verdict-INERT prognostic-association facet: for a target in an indication, is high expression
associated (across 166 datasets / ~18k patients) with WORSE or BETTER overall survival? PRECOG's
meta-Z is the pan-cancer META-ANALYTIC prognostic prior (POSITIVE = high-expr-worse-OS), so it
CORROBORATES the single-cohort expression-clinical-association card.

Emits prognostic_class ∈ {expression_high_worse_survival, expression_high_better_survival,
no_prognostic_association, data_unavailable}, mirroring expression-clinical-association's vocabulary.
The crosswalk from PRECOG's 39 idiosyncratic cancer-type columns to framework indications is in
cli.INDICATION_TO_PRECOG (approximations flagged via precog_indication_approx). VERDICT-INERT.
"""

from .read import read_precog_prognostic, METHOD_VERSION  # noqa: F401
