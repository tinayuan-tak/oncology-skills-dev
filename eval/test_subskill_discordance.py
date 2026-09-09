"""Hermetic test for the per-subskill discordance harness: a synthetic composed run with a `contradicts`
axis (cited) on one subskill + an all-`omics_unavailable` axis on another must aggregate to a contradiction
(citation-anchored) and an unmeasurable, respectively — reading the RICH per-axis agreement, not the rollup."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subskill_discordance as D


def _run(tmp, target, skill_lit):
    d = tmp / "examples" / target / "2026-09-09-full"
    d.mkdir(parents=True)
    nom = {
        "target_report": {"skill_reports": {s: {"evidence_graph": {"literature": lit}} for s, lit in skill_lit.items()}}
    }
    (d / "nomination.json").write_text(json.dumps(nom))
    return str(d)


def test_rich_contradiction_and_unmeasurable(tmp_path):
    _run(
        tmp_path,
        "KIT-GIST",
        {
            "dependency": {
                "overall_consistency": "discordant",
                "key_divergence": "KIT is the archetypal GIST addiction yet omics reads non_dependent.",
                "axes": [
                    {"agreement_vs_omics": "contradicts", "citation_ids": ["PMID1", "PMID2"]},
                    {"agreement_vs_omics": "agree", "citation_ids": []},
                ],
            },
            # blunt rollup would say partially_concordant, but per-axis has NO contradicts → not discordant
            "selectivity": {"overall_consistency": "partially_concordant", "axes": [{"agreement_vs_omics": "extends"}]},
            # every axis omics_unavailable → unmeasurable (the axis-resolution gap health signal)
            "genomic_alteration": {
                "axes": [{"agreement_vs_omics": "omics_unavailable"}, {"agreement_vs_omics": "omics_blind"}]
            },
        },
    )
    prof = D.build_profile([str(tmp_path / "examples" / "*" / "2026-09-09-full")])
    per = prof["per_subskill"]
    assert prof["n_targets"] == 1
    assert per["dependency"]["contradicts"] == 1 and per["dependency"]["contra_cite_anchored"] == 1
    assert per["dependency"]["cases"][0]["n_citations"] == 2
    assert per["selectivity"]["contradicts"] == 0  # extends is not a contradiction
    assert per["genomic_alteration"]["unmeasurable"] == 1 and per["genomic_alteration"]["contradicts"] == 0
    # render must not crash and names the top subskill
    assert "dependency" in D.render(prof)
