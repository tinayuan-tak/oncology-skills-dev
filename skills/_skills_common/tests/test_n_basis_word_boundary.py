"""#2015 mutation-teeth for `_n_basis` word-boundary matching.

Pre-#2015 `_n_basis` admitted any numeric field whose name merely CONTAINED a hint substring, so the
2-char `_N_HINTS` tokens `"n_"` / `"_n"` matched inside unrelated field names and laundered a
measurement / p-value / correlation into the sample-size basis. These tests assert the substring
false-positives the issue enumerated are refused while genuine `n_*` sample-size fields survive, and
that the fix is strictly subtractive (never admits a field the old substring test did not).
"""

from _skills_common.evidence_capsule import _matches_n_hint, _n_basis

# The exact false-positive field names the #2015 brief enumerated from the golden.
_LAUNDERED = [
    "fraction_detected",  # "fractio·n_·detected"
    "median_log2_abundance_panel",  # "media·n_·log2..."
    "rna_protein_r",  # "rna_protei·n_·r"  (the sharpest sub-case)
    "rna_protein_r_ci95_high",
    "expression_purity_pearson_p",  # a Pearson p-value ("expressio·n_·purity...")
    "expression_purity_pearson_r",
    "protein_bh_q_value",  # a BH q-value ("protei·n_·bh_q_value")
    "distribution_overlap_tumor_normal",  # trailing "_normal" contains "_n"
]

# Genuine sample-size bases that MUST still be admitted.
_GENUINE_N = [
    "n_paired_tumors",
    "n_samples",
    "n_cell_lines_evaluated",
    "n_high",
    "n_tumor_samples",
    "n_adjacent",
    "samples_n",  # trailing whole-token "_n"
]


def test_laundered_measurements_are_not_n_fields():
    for f in _LAUNDERED:
        assert not _matches_n_hint(f), f"{f!r} is a measurement, not a sample-size basis"


def test_genuine_n_fields_are_admitted():
    for f in _GENUINE_N:
        assert _matches_n_hint(f), f"{f!r} is a genuine n_* sample-size field"


def test_n_basis_end_to_end_refuses_laundered_and_keeps_real_n():
    """The sharpest sub-case shape: a summary carrying the headline correlation + its CI + a p/q value
    alongside the real n. Only the real n_* count survives; the statistics are refused."""
    summary = {
        "rna_protein_r": 0.4564,
        "rna_protein_r_ci95_high": 0.5771,
        "expression_purity_pearson_p": 0.0029,
        "protein_bh_q_value": 0.3032,
        "fraction_detected": 1.0,
        "n_paired_tumors": 96,
    }
    nb = _n_basis(summary)
    assert nb == {"n_paired_tumors": 96}, nb


def test_fix_is_strictly_subtractive_vs_old_substring():
    """Every word-boundary match must also be an old-substring match — the correction can only REMOVE
    laundered entries, never admit a new one (the corpus-invariant behind the #2015 spot-check)."""
    from _skills_common.evidence_capsule import _N_HINTS

    def _old_substring_match(k):
        kl = k.lower()
        return any(h in kl for h in _N_HINTS)

    probes = (
        _LAUNDERED
        + _GENUINE_N
        + [
            "cells_supporting",  # leading "cells" — must NOT newly match
            "cells_ran",
            "median_purity",
            "log2_fc",
            "n_subgroups_measured",
            "min_subgroup_expression",
        ]
    )
    for f in probes:
        if _matches_n_hint(f):
            assert _old_substring_match(f), f"{f!r} newly matched — fix is not subtractive"
    # And a spot-check that leading count-word fields (a fraction, not a count) are not swept in by
    # a bare token: "cells_supporting" starts with "cells" but has no non-initial n-token.
    assert not _matches_n_hint("cells_supporting")
    assert not _matches_n_hint("cells_ran")
