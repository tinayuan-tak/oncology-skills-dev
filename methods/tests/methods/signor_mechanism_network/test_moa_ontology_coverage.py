"""SIGNOR MoA-ontology COVERAGE drift-guard — the credential-less CI test moa_ontology.py's docstring
has claimed exists since v1.0.0 but never did.

`moa_ontology.py` (Ontology discipline #2) asserts: "a `test_signor_moa_ontology_coverage` verification
test fails CI when >5% of edges are unmapped." No such test existed — grep across the tree found only
`tests/methods/mechanism_composed/test_coessentiality_lane.py`. The `<5% unmapped` invariant (the manifest
freezes it at "~4.2% unmapped") had no runtime or CI guard: an ontology-table edit that dropped a
high-frequency mechanism string, or an upstream re-freeze adding un-curated vocabulary, would silently
push `moa_ontology_unmapped_fraction` past the documented ceiling with nothing red.

This test closes that gap OFFLINE and credential-less by replaying a FROZEN tally of the distinct
(SIGNOR MECHANISM string, direction) pairs over the human protein-protein edge population of the
SIGNOR_Jul2026_release.txt — built exactly as methods/signor_mechanism_network/read.py builds edges (each
SIGNOR A->B row contributes one `downstream` edge for A and one `upstream` edge for B; MECHANISM is
lower/quote-stripped, empty MECHANISM falls back to inhibition/stimulation/binding from EFFECT). It
classifies each pair through the LIVE ontology and asserts the edge-weighted unmapped fraction stays
under 5%. It goes red the moment the ontology table regresses coverage below the documented ceiling.

The frozen tally is `signor_mechanism_tally_jul2026.json` (84 distinct pairs, 45,004 edges). It pins the
Jul2026 SOURCE vocabulary — it does NOT itself detect NEW upstream vocabulary (that needs a re-freeze
against the next release). To refresh against a new SIGNOR release, re-run (with AWS_PROFILE=cbg):

    import json, collections
    from onc_methods.signor_mechanism_network.read import _load_signor_rows_indexed
    rows, _ = _load_signor_rows_indexed()
    t = collections.Counter()
    for row in rows:
        if "protein" not in row.get("TYPEA","").strip().lower(): continue
        if "protein" not in row.get("TYPEB","").strip().lower(): continue
        eff = row.get("EFFECT","").strip().strip('"'); el = eff.lower()
        mech = row.get("MECHANISM","").strip().strip('"')
        if mech: ms = mech.lower()
        elif "down-regulates" in el or "down regulates" in el: ms = "inhibition"
        elif "up-regulates" in el or "up regulates" in el: ms = "stimulation"
        else: ms = "binding"
        t[(ms,"downstream")] += 1; t[(ms,"upstream")] += 1
    # dump {n_edges_total, tally:[[mech,direction,count],...]} sorted by (mech,direction)
"""

from __future__ import annotations

import json
from pathlib import Path

from onc_methods.signor_mechanism_network.moa_ontology import classify_edge

_FIXTURE = Path(__file__).resolve().parent / "signor_mechanism_tally_jul2026.json"
_MAX_UNMAPPED_FRACTION = 0.05  # the documented ontology-coverage ceiling (moa_ontology.py discipline #2)


def _load_tally() -> dict:
    return json.loads(_FIXTURE.read_text())


def test_moa_ontology_edge_weighted_unmapped_fraction_under_ceiling():
    """The edge-weighted unmapped fraction over the frozen Jul2026 (mechanism, direction) tally stays
    under the documented 5% ceiling. Red = an ontology-table edit dropped coverage below 95%."""
    tally = _load_tally()["tally"]
    total = sum(c for _m, _d, c in tally)
    unmapped = sum(c for m, d, c in tally if classify_edge(m, d) is None)
    frac = unmapped / total
    assert frac < _MAX_UNMAPPED_FRACTION, (
        f"MoA-ontology unmapped fraction {frac:.4f} exceeds the documented {_MAX_UNMAPPED_FRACTION:.0%} "
        f"ceiling ({unmapped}/{total} edges). The ontology table regressed coverage — add the newly-unmapped "
        f"mechanism strings to methods/signor_mechanism_network/moa_ontology.py."
    )


def test_fixture_edge_total_matches_declared():
    """Guard the fixture's own integrity — the tally sums to the declared n_edges_total (a truncated or
    hand-edited fixture cannot silently weaken the coverage assertion above)."""
    data = _load_tally()
    assert sum(c for _m, _d, c in data["tally"]) == data["n_edges_total"]
