"""OFFLINE replay of a frozen CD19/COADREAD dossier — the committed NEGATIVE/DISCORDANT spine-
validation fixture the tumor-presence L1->L4 spine lacked (#2020).

Mirror of test_tumor_presence_replay.py (the EPCAM/COADREAD flagship), but EPCAM and KRAS (#1986's
two acceptance flagships) are both intrinsic-PRESENT — neither exercises the measured-ABSENT /
discordant climb. CD19/COADREAD is a real, live-frozen dossier (freeze_fixture.py --target CD19
--indication COADREAD, 2026-09-28) where the antigen is measured-absent across three INDEPENDENT
modalities in this indication (bulk RNA, single-cell malignant RNA, antibody-IHC), while the
target-wide breadth card shows CD19 IS elevated elsewhere (it is a well-known lymphoid-lineage
marker) — a genuine DISCORDANT read on claim D, not a bug. That combination is exactly what a future
regression could silently break in either direction:
  (a) collapse a well-powered measured-absence into a false `underpowered` (the #1743 power-gate
      regressing — claim C here rests on 231 single-cell donors / 398412 malignant cells, both far
      above the MIN_RELIABLE_DONORS(5) / MIN_MALIGNANT_CELLS_TOTAL(100) floor: a well-powered
      absence, not a coverage gap dressed as one);
  (b) fabricate a presence-positive narrative on a measured absence (a reader-field-drift class the
      EPCAM replay cannot catch, because EPCAM never resolves an absence path).

Fixture: fixtures/cd19_coadread.yaml (17 cards, all real summaries, frozen live 2026-09-28; the 18th card,
the TPHP tumor arm added by SK#1825, is deliberately NOT in this freeze — it replays as an honest GAP,
which is exactly the still-no-coverage fall-through the new arm must preserve).

H1/#2019 interaction note: at the time this fixture was frozen, `main` has NO abundance-island /
ADC-payload caveat field on the headline (that gate is issue #2019's separate, parallel, unmerged
scope in `_skills_common` composition/gating code). This fixture is written against CURRENT main
behavior and does NOT depend on #2019's branch; `test_replay_no_abundance_island_caveat_yet` pins
that absence explicitly so #2019's landing is a visible, reviewable diff against this fixture rather
than a silent one.
"""

from __future__ import annotations

import copy
import json
import runpy
import sys
from pathlib import Path

import pytest
import yaml
from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"
FIXTURE = SKILL_DIR / "tests" / "fixtures" / "cd19_coadread.yaml"


def _load_fixture() -> dict:
    if not FIXTURE.exists():
        pytest.skip(f"no frozen fixture at {FIXTURE} — run freeze_fixture.py --target CD19 --indication COADREAD")
    return yaml.safe_load(FIXTURE.read_text()) or {}


def _real_summary(s) -> bool:
    return isinstance(s, dict) and bool(s) and not s.get("_freeze_error") and not s.get("_dispatcher_returned_none")


@pytest.fixture(scope="module")
def cd19_decision(tmp_path_factory):
    """Run the ACTUAL run.py end-to-end on CD19/COADREAD with the live dispatcher replaced by the
    frozen fixture; return the parsed decision.json."""
    frozen = _load_fixture()

    import _skills_common as skc

    def _fake_dispatcher_factory():
        def _read_live(card_id, target, indication, *args, **kwargs):
            s = frozen.get(card_id)
            if not _real_summary(s):
                return None
            return copy.deepcopy(s)

        return _read_live

    out_dir = tmp_path_factory.mktemp("tp-cd19-replay")
    mp = pytest.MonkeyPatch()
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    mp.setattr(skc, "_import_dispatcher", _fake_dispatcher_factory)
    mp.setattr(sys, "argv", ["run.py", "--target", "CD19", "--indication", "COADREAD", "--out", str(out_dir)])
    try:
        runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit as e:
        assert e.code in (0, None), f"run.py exited non-zero ({e.code}) on the frozen CD19 replay"
    finally:
        mp.undo()

    decision_path = out_dir / "decision.json"
    assert decision_path.exists(), "run.py wrote no decision.json on the frozen CD19 replay"
    return json.loads(decision_path.read_text())


def test_fixture_is_nonvacuous():
    """Guard against a stale/broken freeze reading green: CD19/COADREAD resolves 17 of the 18 cards from this freeze; require
    the bulk (>=15) to carry a real summary."""
    frozen = _load_fixture()
    real = [cid for cid, s in frozen.items() if _real_summary(s)]
    assert len(real) >= 15, (
        f"only {len(real)}/{len(frozen)} frozen cards carry a real summary — refreeze against live S3 "
        f"(freeze_fixture.py --target CD19 --indication COADREAD). Real cards: {sorted(real)}"
    )


def test_replay_conforms_to_data_product_schema(cd19_decision):
    """LOAD-BEARING output-drift guard on the ABSENCE path (the EPCAM replay never exercises this
    branch of the schema): the fresh emit from a measured-absent target must still validate."""
    import os

    from _skills_common.data_product_contract import conformance_errors, load_schema, schema_path

    schema = load_schema("tumor-presence")
    if schema is None:
        reason = f"data-product schema not found at {schema_path('tumor-presence')}"
        pytest.fail(reason + " [CI]") if os.environ.get("CI") else pytest.skip(reason)
    errors = conformance_errors(schema, cd19_decision)
    assert not errors, "FRESH replay emit violates the data-product schema:\n  " + "\n  ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:15]
    )


def test_replay_verdict_resolves_honest_measured_absence(cd19_decision):
    """THE ABSENCE-PATH DRIFT GUARD (the half no EPCAM/KRAS flagship test can cover, since both are
    intrinsic-present): CD19 is measured-absent in COADREAD across bulk RNA, single-cell malignant RNA
    and antibody-IHC. A reader-field drift that broke a rule keying this shape would either collapse
    the verdict to a false `insufficient`/`data_unavailable` (masking a real, honest negative as a
    coverage gap) or — worse — fabricate a presence-positive read. Pin the honest degrade: a real,
    non-empty driving rule and a verdict that is NOT the data-starved sentinel."""
    assert cd19_decision["skill"] == "tumor-presence"
    headline = cd19_decision.get("headline") or {}
    verdict = headline.get("presence_verdict")
    assert verdict not in (None, "", "insufficient", "data_unavailable"), (
        f"presence_verdict={verdict!r} on the frozen CD19/COADREAD replay — a well-measured, honestly "
        f"absent antigen must not collapse to the coverage-gap sentinel (gap != absent)."
    )
    assert headline.get("driving_rule_id"), (
        "presence_verdict resolved but driving_rule_id is empty — inconsistent verdict spine."
    )


def test_replay_claims_a_b_c_measured_negative(cd19_decision):
    """Claims A (abundance), B (tumor-elevation) and C (malignant-intrinsic) must all read a measured
    NEGATIVE on this fixture — pinning the multi-axis honest-negative shape the CD19/COADREAD run
    exists to cover (#2020's 'claim A/B/C ... all correctly negative' finding)."""
    cv = (cd19_decision.get("headline") or {}).get("claim_vector") or {}
    for axis in ("A", "B", "C"):
        signal = (cv.get(axis) or {}).get("signal")
        assert signal in ("absent", "negative"), (
            f"claim {axis} signal={signal!r} on frozen CD19/COADREAD — expected a measured negative "
            f"(absent/negative), not a positive or a coverage-gap token."
        )


def test_replay_claim_c_well_powered_absent_not_underpowered(cd19_decision):
    """THE #1743 POWER-GATE ON REAL DATA: claim C's measured-absence here rests on a single-cell study
    with 231 malignant donors / 398412 malignant cells — both far above the MIN_RELIABLE_DONORS(5) /
    MIN_MALIGNANT_CELLS_TOTAL(100) floor. A regression that dropped/weakened the #1743 gate's floor
    check would let a THIN study assert absence; a regression that INVERTED the gate direction would
    misclassify this well-powered absence as `underpowered`. Both directions are pinned here on the
    real numbers, not a synthetic n."""
    cv = (cd19_decision.get("headline") or {}).get("claim_vector") or {}
    c = cv.get("C") or {}
    assert c.get("signal") == "absent", f"claim C signal={c.get('signal')!r} — expected the well-powered absent"
    assert c.get("corroboration") == "high", (
        f"claim C corroboration={c.get('corroboration')!r} — 231 donors is >= POWER_HIGH_N(100), "
        f"expected 'high', not an off-scale/underpowered tier."
    )
    atom = c.get("evidence_atom") or {}
    n_donors = (atom.get("values") or {}).get("malignant_detection_fraction")  # sanity: fraction present
    assert n_donors is not None, "claim C evidence_atom lost the malignant_detection_fraction field"


def test_claim_c_power_gate_teeth_underpowered_variant_of_the_same_antigen():
    """THE TEETH (#2020 acceptance: 'prove at least one assertion goes RED under a deliberate
    regression'): re-derive claim C directly through presence_claim_vector (the #1743 gate's own
    entrypoint) from the SAME real CD19/COADREAD sc-card shape (sc_expression_class=broadly_low,
    malignant_detection_fraction=0.00315 — copied verbatim from the frozen fixture), but with the
    donor count dropped below the MIN_RELIABLE_DONORS(5) floor. If a future regression removed or
    inverted the #1743 power gate, THIS assertion goes RED (the crippled variant would wrongly read
    `absent` instead of `underpowered`) — proving the fixture has teeth on the exact real-data shape
    this issue is about, not just on a synthetic n. The powered branch (231 donors, matching the
    frozen fixture) is re-asserted here too, as a negative-direction (over-gating) guard."""
    from _skills_common.presence_claims import presence_claim_vector

    real_sc = yaml.safe_load(FIXTURE.read_text())["tumor-scrna-celltype-expression"]
    base_hl = {
        "sc_expression_class": real_sc["sc_expression_class"],
        "sc_malignant_detection_fraction": real_sc["malignant_detection_fraction"],
    }

    powered = dict(
        base_hl, sc_malignant_n_donors=real_sc["malignant_n_donors"], sc_malignant_n_cells=real_sc["malignant_n_cells"]
    )
    assert presence_claim_vector(powered, [])["C"]["signal"] == "absent", (
        "well-powered CD19 shape (231 donors / 398412 cells) must stay 'absent' — over-gating regression guard"
    )

    crippled = dict(base_hl, sc_malignant_n_donors=4, sc_malignant_n_cells=real_sc["malignant_n_cells"])
    assert presence_claim_vector(crippled, [])["C"]["signal"] == "underpowered", (
        "a thin (4-donor) study of the SAME antigen/shape must read 'underpowered', never a confident "
        "'absent' — this is the exact regression #1743 exists to prevent (gap != absent)."
    )


def test_replay_claim_d_discordant_breadth_is_not_forced_negative(cd19_decision):
    """The DISCORDANT half of this fixture's name: CD19 is a well-known lymphoid-lineage marker, so
    claim D (generality/breadth, TARGET-wide, not indication-scoped) legitimately reads a non-absent
    breadth signal even though this indication (COADREAD) is locally measured-absent on A/B/C. This is
    an honest discordance, not a bug — claims are explicitly NOT additive (a weak/positive D does not
    override a negative A/B/C), and the claim_vector is verdict-INERT (never feeds presence_verdict).
    Pin the current real shape so a future change to breadth-selection logic is a visible diff here."""
    cv = (cd19_decision.get("headline") or {}).get("claim_vector") or {}
    d = cv.get("D") or {}
    assert d.get("signal") in ("weak", "moderate", "strong"), (
        f"claim D signal={d.get('signal')!r} — expected a non-absent breadth read for CD19 (lymphoid "
        f"marker, target-wide elevation elsewhere), documenting the discordance with A/B/C's local absence."
    )
    assert d.get("corroboration") in ("moderate", "high"), (
        f"claim D corroboration={d.get('corroboration')!r} — the breadth roster tested is not thin here."
    )


def test_replay_l2b_concordance_agreed_direction_measured_not_present(cd19_decision):
    """L2b cross-source integration node (`tumor_presence_concordance`, #1867): three genuinely
    independent measurement groups (bulk RNA, single-cell malignant RNA, antibody-IHC) must AGREE on
    `measured_not_present` — the cross-source corroboration the #2020 finding names directly."""
    cv = (cd19_decision.get("headline") or {}).get("claim_vector") or {}
    tpi = cv.get("tumor_presence_concordance") or {}
    assert tpi.get("concordance_class") == "tumor_presence_concordant"
    support = tpi.get("concordance_support") or {}
    assert support.get("agreed_direction") == "measured_not_present", (
        f"agreed_direction={support.get('agreed_direction')!r} — expected the cross-source measured "
        f"non-detection direction pinned by #2020."
    )
    assert tpi.get("corroborating_independent_arm_count") == 3
    assert set(support.get("agreeing_arms") or []) == {"bulk_rna", "sc_malignant", "antibody_ihc"}


def test_replay_l3d_biology_story_measured_non_detection_headline(cd19_decision):
    """L3d within-domain biology story headline must state the cross-source-corroborated measured
    non-detection in plain language — the '3 INDEPENDENT measurement groups AGREE on a MEASURED tumor
    non-detection' framing the #2020 finding quotes verbatim."""
    story = (cd19_decision.get("headline") or {}).get("tumor_expression_biology_story") or {}
    assert story.get("coherence") == "cross_source_corroborated"
    headline_text = story.get("headline") or ""
    assert "AGREE" in headline_text and "MEASURED tumor non-detection" in headline_text, (
        f"L3d headline does not carry the expected corroborated-non-detection framing: {headline_text!r}"
    )


def test_replay_no_abundance_island_caveat_yet(cd19_decision):
    """H1/#2019 interaction note: as of this fixture's freeze, `main` has no abundance-island / ADC-
    payload caveat wired into the headline (#2019's separate, parallel, unmerged scope). This pins
    that absence EXPLICITLY so #2019 landing such a caveat produces a visible, reviewable diff against
    this fixture (the caveat should end up suppressed-or-demoted on this measured-absence shape, per
    #2020's acceptance criteria) rather than an invisible one. Not a statement that #2019 is wrong —
    only that this fixture does not depend on its unmerged branch."""
    headline = cd19_decision.get("headline") or {}
    assert "abundance_island_caveat" not in headline
    assert "adc_payload_caveat" not in headline


def _rna_presence_positive() -> frozenset:
    return load_run_py(SKILL_DIR, "_tp_run_const_cd19")._RNA_PRESENCE_POSITIVE


def test_replay_verdict_is_not_a_measured_positive(cd19_decision):
    """Cross-check against the EPCAM flagship's own positive vocabulary (imported from run.py, single
    source of truth): CD19/COADREAD's collapsed verdict must NOT be a member of the measured-positive
    RNA set — the false-positive-fabrication failure mode this fixture guards against (H1)."""
    headline = cd19_decision.get("headline") or {}
    verdict = headline.get("presence_verdict")
    assert verdict not in _rna_presence_positive(), (
        f"presence_verdict={verdict!r} for CD19/COADREAD is a measured-POSITIVE RNA call — a measured, "
        f"cross-source-corroborated absence must never resolve positive."
    )
