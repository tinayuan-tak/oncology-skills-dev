"""opentargets_drug_warning — per-target pharmacovigilance safety CONTEXT (OT 26.06).

Joins drug_warning (chembl black-box/withdrawn warnings) to drug_mechanism_of_action (chembl->target)
so a target inherits the warning history of the drugs that engage it. VERDICT-INERT context (a drug
warning is a confounded on-target signal). Closes the P5 drug_warning placeholder axis.

METHOD_VERSION 0.1.0.
"""
from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .read import read_drug_warning, classify_drug_warning  # noqa: E402,F401
