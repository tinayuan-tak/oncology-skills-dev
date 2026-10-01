"""Hermetic tests for eval/loop/batch_constructor.py (skills#2348).

No network, no pixi, no live skill run — coverage is a plain fixture dict, exactly as production
usage will be once a future WI-A/run_batch.py scan supplies the real one. Every selection /
determinism claim is paired with a mutation that must change the result, so a check that cannot
fail (SKIP != PASS) is never mistaken for a guard.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_LOOP = Path(__file__).resolve().parents[1] / "loop"
if str(_LOOP) not in sys.path:
    sys.path.insert(0, str(_LOOP))

import batch_constructor as bc  # noqa: E402

# --------------------------------------------------------------------------------------------- #
# Fixture candidate set — small, hand-built, mirrors the pilot's shape (positives / negatives /
# panel archetypes) without depending on any real corpus file.
# --------------------------------------------------------------------------------------------- #


def _candidates():
    return [
        bc.Candidate("CEACAM5", "COADREAD", stratum="control_positive"),
        bc.Candidate("EPCAM", "COADREAD", stratum="control_positive"),
        bc.Candidate("ACTB", "COADREAD", stratum="control_negative"),
        bc.Candidate("PRM1", "COADREAD", stratum="control_negative"),
        bc.Candidate("CD274", "LUAD", stratum="panel_archetype"),
        bc.Candidate("CCNE1", "OV", stratum="panel_archetype"),
        bc.Candidate("GFAP", "COADREAD", stratum="panel_archetype"),
    ]


_REQUIRED = frozenset(
    {
        ("tumor_presence_concordance", "tumor_presence_concordant"),
        ("tumor_presence_concordance", "tumor_presence_discordant"),
        ("protein_presence_concordance", "protein_presence_concordant"),
        ("subtype_restriction_concordance", "single_source_only"),
        ("abundance_concordance", "abundance_concordant"),
        ("cellline_heterogeneity_lineage_qualifier", "cellline_heterogeneity_is_cross_lineage"),
    }
)


def _coverage():
    return {
        "CEACAM5|COADREAD|": frozenset(
            {
                ("tumor_presence_concordance", "tumor_presence_concordant"),
                ("protein_presence_concordance", "protein_presence_concordant"),
                ("abundance_concordance", "abundance_concordant"),
            }
        ),
        "EPCAM|COADREAD|": frozenset(
            {
                ("tumor_presence_concordance", "tumor_presence_concordant"),
                ("subtype_restriction_concordance", "single_source_only"),
            }
        ),
        "ACTB|COADREAD|": frozenset(
            {
                ("protein_presence_concordance", "protein_presence_concordant"),
            }
        ),
        "PRM1|COADREAD|": frozenset(
            {
                ("tumor_presence_concordance", "tumor_presence_discordant"),
            }
        ),
        "CD274|LUAD|": frozenset(
            {
                ("cellline_heterogeneity_lineage_qualifier", "cellline_heterogeneity_is_cross_lineage"),
            }
        ),
        # CCNE1 and GFAP deliberately carry NO coverage entry — coverage-unknown, quota-fill only.
    }


# --------------------------------------------------------------------------------------------- #
# load_candidates_tsv / dedupe
# --------------------------------------------------------------------------------------------- #


def test_load_candidates_tsv_round_trips_3_and_4_column(tmp_path):
    p = tmp_path / "c.tsv"
    p.write_text("CEACAM5\tCOADREAD\tpos_tumor_antigen\nERBB2\tBRCA\tpos_tumor_antigen_subset_high\tHER2E\n")
    rows = bc.load_candidates_tsv(p)
    assert rows[0] == bc.Candidate("CEACAM5", "COADREAD", stratum="pos_tumor_antigen")
    assert rows[1] == bc.Candidate("ERBB2", "BRCA", subtype="HER2E", stratum="pos_tumor_antigen_subset_high")


def test_load_candidates_tsv_skips_blank_and_comment_lines(tmp_path):
    p = tmp_path / "c.tsv"
    p.write_text("# header\n\nACTB\tCOADREAD\tcontrol\n")
    rows = bc.load_candidates_tsv(p)
    assert len(rows) == 1
    assert rows[0].target == "ACTB"


def test_dedupe_candidates_first_source_wins():
    a = bc.Candidate("ACTB", "COADREAD", stratum="pilot_hand_picked", source="pilot")
    b = bc.Candidate("ACTB", "COADREAD", stratum="panel_504", source="corpus")
    out = bc.dedupe_candidates([a, b])
    assert len(out) == 1
    assert out[0].stratum == "pilot_hand_picked"


# --------------------------------------------------------------------------------------------- #
# select_roster — coverage report
# --------------------------------------------------------------------------------------------- #


def test_select_roster_covers_every_required_pair():
    roster = bc.select_roster(_candidates(), _coverage(), _REQUIRED, target_min=1, target_max=10)
    assert roster.covered_pairs == _REQUIRED
    assert roster.uncovered_pairs == frozenset()
    assert roster.coverage_fraction == 1.0


def test_select_roster_coverage_report_has_denominators_and_resolves_each_pair():
    roster = bc.select_roster(_candidates(), _coverage(), _REQUIRED, target_min=1, target_max=10)
    report = roster.coverage_report()
    assert report["required_pairs_total"] == len(_REQUIRED)
    assert report["covered_pairs_total"] == len(_REQUIRED)
    assert report["uncovered_pairs"] == []
    # every required pair must trace to >=1 covering candidate key
    for fam, tok in _REQUIRED:
        coverers = report["covering_candidate_by_pair"][f"{fam}::{tok}"]
        assert coverers, f"{fam}::{tok} has no covering candidate recorded"


def test_select_roster_is_a_true_cover_not_vacuous():
    """ANTI-VACUITY: strip one candidate's coverage of the ONLY pair it provides and the roster
    must report that pair uncovered — a report that always reads 'fully covered' is worthless."""
    cov = dict(_coverage())
    cov["CD274|LUAD|"] = frozenset()  # was the sole source of the qualifier pair
    roster = bc.select_roster(_candidates(), cov, _REQUIRED, target_min=1, target_max=10)
    assert ("cellline_heterogeneity_lineage_qualifier", "cellline_heterogeneity_is_cross_lineage") in (
        roster.uncovered_pairs
    )
    assert roster.coverage_fraction < 1.0


def test_select_roster_seed_keys_admitted_first():
    cands = _candidates()
    seed = ["PRM1|COADREAD|"]
    roster = bc.select_roster(cands, _coverage(), _REQUIRED, target_min=1, target_max=10, seed_keys=seed)
    assert roster.entries[0].candidate.key == "PRM1|COADREAD|"
    assert roster.entries[0].reason == "seed"


def test_select_roster_quota_fills_uncovering_candidates_up_to_target_min():
    roster = bc.select_roster(_candidates(), _coverage(), _REQUIRED, target_min=7, target_max=10)
    keys = {e.candidate.key for e in roster.entries}
    # CCNE1 and GFAP carry no coverage at all but must still be admitted to reach target_min=7
    # (all 7 fixture candidates), via the quota-fill path.
    assert "CCNE1|OV|" in keys
    assert "GFAP|COADREAD|" in keys
    reasons = {e.candidate.key: e.reason for e in roster.entries}
    assert reasons["CCNE1|OV|"] == "quota"


def test_select_roster_respects_target_max():
    roster = bc.select_roster(_candidates(), _coverage(), _REQUIRED, target_min=1, target_max=3)
    assert len(roster.entries) <= 3


def test_select_roster_strata_min_floors_a_stratum():
    roster = bc.select_roster(
        _candidates(),
        _coverage(),
        _REQUIRED,
        target_min=1,
        target_max=10,
        strata_min={"control_negative": 2},
    )
    strata = [e.candidate.stratum for e in roster.entries]
    assert strata.count("control_negative") >= 2


def test_select_roster_deterministic_regardless_of_input_order():
    cands = _candidates()
    reversed_cands = list(reversed(cands))
    r1 = bc.select_roster(cands, _coverage(), _REQUIRED, target_min=5, target_max=10)
    r2 = bc.select_roster(reversed_cands, _coverage(), _REQUIRED, target_min=5, target_max=10)
    keys1 = sorted(e.candidate.key for e in r1.entries)
    keys2 = sorted(e.candidate.key for e in r2.entries)
    assert keys1 == keys2


# --------------------------------------------------------------------------------------------- #
# assign_split — determinism + stability
# --------------------------------------------------------------------------------------------- #


def _entries():
    roster = bc.select_roster(_candidates(), _coverage(), _REQUIRED, target_min=7, target_max=10)
    return roster.entries


def test_assign_split_deterministic_across_repeated_calls():
    entries = _entries()
    s1 = bc.assign_split(entries, salt="batch-v1")
    s2 = bc.assign_split(entries, salt="batch-v1")
    assert s1.split == s2.split


def test_assign_split_stable_regardless_of_entry_order():
    entries = _entries()
    s1 = bc.assign_split(entries, salt="batch-v1")
    s2 = bc.assign_split(list(reversed(entries)), salt="batch-v1")
    assert s1.split == s2.split


def test_assign_split_changes_with_a_different_salt():
    """ANTI-VACUITY: a split that never changes with its own salt input is not reading the salt.
    `min_per_stratum=0` so the stratified floor (which can promote enough dev->held_out to mask
    the raw per-key hash) doesn't swamp the comparison on this small fixture."""
    entries = _entries()
    s1 = bc.assign_split(entries, salt="batch-v1", min_per_stratum=0)
    s2 = bc.assign_split(entries, salt="batch-v2", min_per_stratum=0)
    assert s1.split != s2.split


def test_assign_split_honors_min_per_stratum_floor():
    entries = _entries()
    split = bc.assign_split(entries, salt="batch-v1", min_per_stratum=2)
    by_stratum: dict[str, list[str]] = {}
    for e in entries:
        by_stratum.setdefault(e.candidate.stratum, []).append(e.candidate.key)
    for stratum, keys in by_stratum.items():
        if len(keys) < 2:
            continue
        held = [k for k in keys if split.split[k] == "held_out"]
        assert len(held) >= 2, f"stratum {stratum} has only {len(held)} held-out of {keys}"


def test_assign_split_counts_reconcile_to_total():
    entries = _entries()
    split = bc.assign_split(entries, salt="batch-v1")
    counts = split.counts()
    assert counts["dev"] + counts["held_out"] == counts["total"] == len(entries)


# --------------------------------------------------------------------------------------------- #
# build_batch_spec / write_roster_tsv / write_batch_spec — output shape
# --------------------------------------------------------------------------------------------- #


def test_build_batch_spec_round_trips_split_rule_and_counts():
    roster = bc.select_roster(_candidates(), _coverage(), _REQUIRED, target_min=7, target_max=10)
    split = bc.assign_split(roster.entries, salt="batch-v1")
    spec = bc.build_batch_spec(roster, split, skill="tumor-presence", batch_id="test-v1")
    assert spec["skill"] == "tumor-presence"
    assert spec["batch_id"] == "test-v1"
    assert "held_out" in spec["split_rule"]
    assert spec["split_counts"]["total"] == len(roster.entries)
    assert len(spec["roster"]) == len(roster.entries)
    for row in spec["roster"]:
        assert row["split"] in ("dev", "held_out")


def test_write_roster_tsv_and_batch_spec_are_readable(tmp_path):
    roster = bc.select_roster(_candidates(), _coverage(), _REQUIRED, target_min=7, target_max=10)
    split = bc.assign_split(roster.entries, salt="batch-v1")
    roster_path = tmp_path / "batch.tsv"
    spec_path = tmp_path / "batch.v1.json"
    bc.write_roster_tsv(roster, split, roster_path)
    spec = bc.build_batch_spec(roster, split, skill="tumor-presence", batch_id="test-v1")
    bc.write_batch_spec(spec, spec_path)

    lines = roster_path.read_text().strip("\n").split("\n")
    assert len(lines) == len(roster.entries)
    for line in lines:
        cols = line.split("\t")
        assert len(cols) == 5  # target, indication, subtype, stratum, split
        assert cols[-1] in ("dev", "held_out")

    reloaded = json.loads(spec_path.read_text())
    assert reloaded["skill"] == "tumor-presence"
    assert reloaded["coverage"]["required_pairs_total"] == len(_REQUIRED)


# --------------------------------------------------------------------------------------------- #
# load_coverage_json / load_required_pairs_json
# --------------------------------------------------------------------------------------------- #


def test_load_coverage_json_and_required_pairs_json(tmp_path):
    cov_path = tmp_path / "coverage.json"
    cov_path.write_text(json.dumps({"ACTB|COADREAD|": [["abundance_concordance", "abundance_concordant"]]}))
    req_path = tmp_path / "required.json"
    req_path.write_text(json.dumps([["abundance_concordance", "abundance_concordant"]]))

    coverage = bc.load_coverage_json(cov_path)
    required = bc.load_required_pairs_json(req_path)

    assert coverage["ACTB|COADREAD|"] == frozenset({("abundance_concordance", "abundance_concordant")})
    assert required == frozenset({("abundance_concordance", "abundance_concordant")})


# --------------------------------------------------------------------------------------------- #
# CLI end-to-end (no network, all paths under tmp_path)
# --------------------------------------------------------------------------------------------- #


def test_cli_main_end_to_end(tmp_path):
    cand_path = tmp_path / "candidates.tsv"
    cand_path.write_text("\n".join(f"{c.target}\t{c.indication}\t{c.stratum}" for c in _candidates()) + "\n")
    cov_path = tmp_path / "coverage.json"
    cov_path.write_text(json.dumps({k: [list(p) for p in v] for k, v in _coverage().items()}))
    req_path = tmp_path / "required.json"
    req_path.write_text(json.dumps([list(p) for p in _REQUIRED]))
    out_roster = tmp_path / "out.tsv"
    out_spec = tmp_path / "out.json"

    rc = bc.main(
        [
            "--candidates-tsv",
            str(cand_path),
            "--coverage-json",
            str(cov_path),
            "--required-pairs-json",
            str(req_path),
            "--batch-id",
            "cli-test",
            "--salt",
            "cli-salt",
            "--target-min",
            "7",
            "--target-max",
            "7",
            "--out-roster",
            str(out_roster),
            "--out-spec",
            str(out_spec),
        ]
    )
    assert rc == 0
    assert out_roster.exists()
    spec = json.loads(out_spec.read_text())
    assert spec["batch_id"] == "cli-test"
    assert spec["coverage"]["coverage_fraction"] == 1.0
