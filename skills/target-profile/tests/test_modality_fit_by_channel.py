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

from tp_facets import _modality_fit_by_channel  # noqa: E402


def _rec(axis, modality_scope):
    return {"claim_record_shadow": {"axis": axis, "finding": {}, "modality_scope": modality_scope}}


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
