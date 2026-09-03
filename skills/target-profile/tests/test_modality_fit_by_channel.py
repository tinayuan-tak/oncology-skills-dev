"""M4 modality-fit-by-channel rollup (VERDICT_REPRESENTATION §8 / migration §3) — the SECOND factored
-record consumer. Pins the per-channel worst-case conjunction of the records' modality_scope: the
answer to the KRAS case (nominable as an allele-selective SM, hold as a degrader), from the record.
S3-free: pure over synthetic claim_record_shadow sub_results."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SKILLS = SCRIPTS.parent.parent                       # skills/ — tp_facets imports _skills_common
for _p in (str(SKILLS), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tp_facets import _modality_fit_by_channel, _modality_scope_by_axis  # noqa: E402


def _rec(axis, modality_scope):
    return {"claim_record_shadow": {"axis": axis, "finding": {}, "modality_scope": modality_scope}}


def _spine(axis, modality_scope):
    """A sub_result carrying modality_scope on the skill_report[] SPINE (no shadow)."""
    return {"synthesis_facet": {"skill_report": {"role": "gating", "modality_scope": modality_scope}}}


def test_kras_like_per_modality_split():
    # safety: WT-loss concern — SM conditional (allele-selective spares WT), degrader unfavorable.
    # tractability: SM favorable (ligandable). => SM = worst(conditional, favorable) = conditional;
    # degrader = unfavorable (only safety speaks) — the per-modality call the scalar could not hold.
    sr = {
        "safety": _rec("safety", {"small_molecule": "conditional", "biologics": "unfavorable",
                                  "_refinements": {"degrader": "unfavorable"}}),
        "tractability_sm": _rec("tractability_small_molecule",
                                {"small_molecule": "favorable", "biologics": "na"}),
    }
    out = _modality_fit_by_channel(sr)
    assert out["small_molecule"]["fit"] == "conditional"
    assert out["small_molecule"]["limiting_axis"] == "safety"       # the WT-loss concern limits SM
    assert out["degrader"]["fit"] == "unfavorable"
    assert out["small_molecule"]["by_axis"] == {"safety": "conditional", "tractability_sm": "favorable"}


def test_surface_refinements_drive_adc_tce():
    # surface: adc favorable, bite_tce unfavorable (adc_preferred_tce_unsafe-like).
    sr = {"surface_modality": _rec("surface_modality",
                                   {"small_molecule": "na", "biologics": "favorable",
                                    "_refinements": {"adc": "favorable", "bite_tce": "unfavorable"}})}
    out = _modality_fit_by_channel(sr)
    assert out["adc"]["fit"] == "favorable"
    assert out["bite_tce"]["fit"] == "unfavorable"
    assert out["small_molecule"]["fit"] == "na"                     # surface is silent on SM


def test_worst_case_conjunction_across_axes():
    # two axes both speak to biologics: favorable & unfavorable -> worst (unfavorable) wins.
    sr = {
        "surface_modality": _rec("surface_modality", {"small_molecule": "na", "biologics": "favorable"}),
        "safety": _rec("safety", {"small_molecule": "conditional", "biologics": "unfavorable"}),
    }
    out = _modality_fit_by_channel(sr)
    assert out["biologics"]["fit"] == "unfavorable"
    assert out["biologics"]["limiting_axis"] == "safety"


def test_na_when_no_axis_constrains():
    sr = {"dependency": _rec("dependency", None)}   # dependency carries no modality_scope
    out = _modality_fit_by_channel(sr)
    assert all(out[ch]["fit"] == "na" for ch in out)


def test_empty_shadow_is_all_na():
    out = _modality_fit_by_channel({})
    assert set(out) == {"small_molecule", "biologics", "degrader", "adc", "bite_tce", "antibody"}
    assert all(v["fit"] == "na" for v in out.values())


# ── biology-axis applicability MASK (the coherence fix) ──────────────────────────────────────────
_SURFACE_AXIS = {"biology_axis": "surface_intrinsic", "curated": True, "multi_axis": False,
                 "plausible_modalities": ["adc", "bite_tce", "antibody"]}
_INTRA_AXIS = {"biology_axis": "intracellular_intrinsic", "curated": True, "multi_axis": False,
               "plausible_modalities": ["small_molecule", "degrader"]}


def test_surface_antigen_masks_small_molecule_as_category_error():
    # tractability says SM favorable, but for a pure surface antigen SM is a CATEGORY ERROR, not a call.
    sr = {"tractability_sm": _rec("tractability_small_molecule",
                                  {"small_molecule": "favorable", "biologics": "na"}),
          "surface_modality": _rec("surface_modality",
                                   {"small_molecule": "na", "biologics": "favorable",
                                    "_refinements": {"adc": "favorable"}})}
    out = _modality_fit_by_channel(sr, axis_info=_SURFACE_AXIS)
    assert out["small_molecule"]["fit"] == "not_applicable_by_axis"     # masked, not "favorable"
    assert out["degrader"]["fit"] == "not_applicable_by_axis"
    assert out["adc"]["fit"] == "favorable"                            # biologic channels stay live


def test_intracellular_masks_surface_biologics():
    sr = {"safety": _rec("safety", {"small_molecule": "conditional", "biologics": "unfavorable"})}
    out = _modality_fit_by_channel(sr, axis_info=_INTRA_AXIS)
    assert out["small_molecule"]["fit"] == "conditional"              # SM stays live for intracellular
    assert out["adc"]["fit"] == "not_applicable_by_axis"
    assert out["bite_tce"]["fit"] == "not_applicable_by_axis"
    assert out["biologics"]["fit"] == "not_applicable_by_axis"        # base umbrella masked too


def test_multi_axis_dual_keeps_all_channels_live():
    # EGFR-like: intracellular kinase AND surface antigen → NEVER mask (the de-emphasis-not-erase rule).
    dual = {**_SURFACE_AXIS, "multi_axis": True}
    sr = {"tractability_sm": _rec("tractability_small_molecule",
                                  {"small_molecule": "favorable", "biologics": "na"})}
    out = _modality_fit_by_channel(sr, axis_info=dual)
    assert out["small_molecule"]["fit"] == "favorable"               # NOT masked for a dual target


def test_uncurated_axis_does_not_mask():
    unknown = {"biology_axis": "unknown", "curated": False, "multi_axis": False, "plausible_modalities": []}
    sr = {"tractability_sm": _rec("tractability_small_molecule",
                                  {"small_molecule": "favorable", "biologics": "na"})}
    out = _modality_fit_by_channel(sr, axis_info=unknown)
    assert out["small_molecule"]["fit"] == "favorable"               # no curated axis → no mask


# ── SPINE re-point (contract §100-128): modality_scope is now read from the skill_report[] spine ──────
def test_modality_scope_read_from_spine():
    # modality_scope lives ONLY on the skill_report (no claim_record_shadow) → the rollup still sees it.
    sr = {"tractability_sm": _spine("tractability_small_molecule",
                                    {"small_molecule": "favorable", "biologics": "na"})}
    assert _modality_scope_by_axis(sr) == {"tractability_sm": {"small_molecule": "favorable", "biologics": "na"}}
    out = _modality_fit_by_channel(sr)
    assert out["small_molecule"]["fit"] == "favorable"
    assert out["small_molecule"]["limiting_axis"] == "tractability_sm"


def test_spine_wins_over_shadow_when_both_present():
    # spine-first precedence: a report carrying modality_scope shadows the legacy claim_record_shadow.
    both = {"synthesis_facet": {"skill_report": {"modality_scope": {"small_molecule": "favorable",
                                                                    "biologics": "na"}}},
            "claim_record_shadow": {"axis": "tractability_small_molecule",
                                    "modality_scope": {"small_molecule": "unfavorable", "biologics": "na"}}}
    assert _modality_scope_by_axis({"tractability_sm": both})["tractability_sm"]["small_molecule"] == "favorable"


def test_shadow_fallback_when_report_lacks_scope():
    # a report present but WITHOUT a modality_scope slot (predates the migration) → legacy shadow fills in.
    mixed = {"synthesis_facet": {"skill_report": {"role": "gating"}},   # no modality_scope
             "claim_record_shadow": {"axis": "safety",
                                     "modality_scope": {"small_molecule": "conditional", "biologics": "unfavorable"}}}
    got = _modality_scope_by_axis({"safety": mixed})
    assert got == {"safety": {"small_molecule": "conditional", "biologics": "unfavorable"}}
