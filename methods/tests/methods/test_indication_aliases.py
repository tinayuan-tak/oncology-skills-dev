"""indication_aliases: the two directional vocabulary maps.

to_cohort_canonical UP-pools a finer OncoTree code to its patient-cohort canonical (LUAD→NSCLC);
indication_leaf_codes DOWN-expands an umbrella to its member LEAF codes for leaf-keyed products
(NSCLC→(LUAD,LUSC)) — the CPTAC per-sample readers, which have no pooled NSCLC cohort.
"""

from __future__ import annotations

import importlib

IA = importlib.import_module("onc_methods.indication_aliases")


def test_up_pooling_unchanged():
    assert IA.to_cohort_canonical("LUAD") == "NSCLC"
    assert IA.to_cohort_canonical("LUSC") == "NSCLC"
    assert IA.to_cohort_canonical("COADREAD") == "COADREAD"  # identity for a canonical code


def test_leaf_expansion_of_umbrella():
    assert IA.indication_leaf_codes("NSCLC") == ("LUAD", "LUSC")
    assert IA.indication_leaf_codes("nsclc") == ("LUAD", "LUSC")  # case-normalized


def test_leaf_expansion_identity_for_leaf_code():
    # a non-umbrella code expands to itself (single-element) so callers can iterate uniformly
    assert IA.indication_leaf_codes("LUAD") == ("LUAD",)
    assert IA.indication_leaf_codes("COADREAD") == ("COADREAD",)


def test_leaf_expansion_empty_for_falsy():
    assert IA.indication_leaf_codes("") == ()
    assert IA.indication_leaf_codes(None) == ()
