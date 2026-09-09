"""Hermetic test for the per-subskill discordance harness + router: a synthetic composed run with a
`contradicts` axis (cited) on one subskill + an all-`omics_unavailable` axis on another aggregates to a
classified contradiction + an unmeasurable, reading the RICH per-axis agreement (not the rollup)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subskill_discordance as D


def _run(tmp, target, skill_lit, target_call=None, llm=None):
    d = tmp / "examples" / target / "2026-09-09-full"
    d.mkdir(parents=True)
    tr = {"skill_reports": {s: {"evidence_graph": {"literature": lit}} for s, lit in skill_lit.items()}}
    if target_call is not None:
        tr["target_call"] = target_call
    nom = {"target_report": tr}
    if llm is not None:
        nom["llm_synthesis"] = {"overall_recommendation": llm}
    (d / "nomination.json").write_text(json.dumps(nom))
    return str(d)


def test_rich_contradiction_unmeasurable_and_routing(tmp_path):
    _run(
        tmp_path,
        "KIT-GIST",
        {
            "dependency": {
                "key_divergence": "KIT is the archetypal GIST addiction yet omics reads non_dependent.",
                "axes": [
                    {"agreement_vs_omics": "contradicts", "citation_ids": ["PMID1", "PMID2"]},
                    {"agreement_vs_omics": "agree", "citation_ids": []},
                ],
            },
            "selectivity": {"axes": [{"agreement_vs_omics": "extends"}]},  # not a contradiction
            "genomic_alteration": {
                "axes": [{"agreement_vs_omics": "omics_unavailable"}, {"agreement_vs_omics": "omics_blind"}]
            },
        },
        target_call={"gate": {"fired": False}},
        llm="veto",
    )
    prof = D.build_profile([str(tmp_path / "examples" / "*" / "2026-09-09-full")])
    per = prof["per_subskill"]
    assert prof["n_targets"] == 1
    assert per["dependency"]["contradicts"] == 1
    assert per["dependency"]["cases"][0]["n_citations"] == 2
    assert per["selectivity"]["contradicts"] == 0  # extends is not a contradiction
    assert per["genomic_alteration"]["unmeasurable"] == 1 and per["genomic_alteration"]["contradicts"] == 0
    # routing: the dependency contradiction is classified (B by default when no framework axis/inversion);
    # every case carries a class + home layer.
    assert per["dependency"]["cases"][0]["class"].startswith(("A-", "B-", "E-"))
    assert per["dependency"]["cases"][0]["layer"]
    assert prof["class_totals"]  # a routed backlog exists
    # C-synthesis is TARGET-level: gate.fired False + llm veto -> KIT-GIST flagged
    assert "KIT-GIST" in prof["c_synthesis_targets"]
    assert "class_totals" in D.render(prof) or "CLASS TOTALS" in D.render(prof)
