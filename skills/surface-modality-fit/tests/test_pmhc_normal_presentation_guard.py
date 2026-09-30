"""#2113 — the pMHC-TCE normal-presentation MEASUREDNESS guard has TEETH and is FALSIFIABLE.

THE BUG THIS PINS (fail-OPEN over-credit). Before #2113 the surface_modality resolver minted the
verdict-moving positive `pmhc_tce_supported` from the conjunction [neither-viable-killer, pmhc-iedb-
{tcell-validated|presented}-tce-supportive] — i.e. from TUMOR-CONTEXT-AGNOSTIC IEDB epitope evidence
ALONE, with NO normal-tissue-presentation conjunct. The only corrective (the broadly-presented VETO)
fired off a SEPARATE, frequently-absent benign-atlas card, so on n=504 it fired 0× and the guard was
structurally absent for 160/195 promotions. A clean `pmhc_tce_supported` earns the nomination
veto→hold rescue (nomination_verdict_gate biology_axis_scoped_veto_downgrade.when_surface_verdict_in),
so this over-credited 160/504 intracellular non_dependent targets on weak, tumor-agnostic evidence.

THE FIX + WHAT THESE TESTS DEFEND:
  1. FALSIFIABILITY (teeth): the CLEAN pmhc_tce_supported is now unreachable WITHOUT a MEASURED
     tumor-restricted normal-presentation conjunct (pmhc-restricted-presentation-tce-supportive). If a
     future edit dropped that conjunct, `test_clean_promotion_requires_the_restricted_presentation_
     conjunct` goes RED — the property the golden coverage-debt lift made observable to the oracle.
  2. NEGATIVE FIXTURE (the over-credit is gone): IEDB-positive + neither_viable WITHOUT a benign-atlas
     read now resolves to the NON-NOMINATING caveat pmhc_tce_supported_presentation_unconfirmed, NOT
     the clean positive — and that caveat is absent from the nomination positive / veto-downgrade
     vocab, so it earns NO rescue.

Pure (resolver YAML + vocab YAML reads; no S3)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from _skills_common.paths import TARGET_CONTRACTS_ROOT_DEFAULT
from _skills_common.resolver import load_resolver, resolve_verdict

CONTRACTS = Path(os.environ.get("TARGET_CONTRACTS_ROOT", TARGET_CONTRACTS_ROOT_DEFAULT))

_KILL = "neither-viable-killer"
_TV = "pmhc-iedb-tcell-validated-tce-supportive"
_PR = "pmhc-iedb-presented-tce-supportive"
_RESTRICTED = "pmhc-restricted-presentation-tce-supportive"
_BROAD = "pmhc-broadly-presented-normal-tce-opposing"
_CAVEAT = "pmhc_tce_supported_presentation_unconfirmed"

_SPEC = load_resolver("surface_modality", contracts_repo=CONTRACTS)
pytestmark = pytest.mark.skipif(_SPEC is None, reason="surface_modality.resolver.yaml unavailable")


def _resolve(*rule_ids):
    return resolve_verdict([{"rule_id": r} for r in rule_ids], _SPEC)


# ── (2) NEGATIVE FIXTURE — the over-credit is gone: IEDB alone no longer mints the clean positive ──
@pytest.mark.parametrize("iedb", [_TV, _PR])
def test_iedb_alone_demotes_to_the_nonnominating_caveat_not_the_clean_positive(iedb):
    """The exact 160/195 corpus population: neither_viable + an IEDB epitope positive with NO benign-atlas
    presentation read. It must resolve to the caveat, NOT clean pmhc_tce_supported."""
    verdict, _ = _resolve(_KILL, iedb)
    assert verdict == _CAVEAT, (
        f"IEDB-positive ({iedb}) + neither_viable with an UNMEASURED normal-presentation window must "
        f"demote to {_CAVEAT}, not mint a clean positive (fail-open over-credit) — got {verdict}"
    )


# ── (1) CLEAN positive requires the MEASURED restricted-presentation conjunct (falsifiability teeth) ──
@pytest.mark.parametrize("iedb", [_TV, _PR])
def test_restricted_presentation_conjunct_earns_the_clean_positive(iedb):
    verdict, _ = _resolve(_KILL, iedb, _RESTRICTED)
    assert verdict == "pmhc_tce_supported", (
        f"neither_viable + {iedb} + MEASURED restricted normal-presentation must earn the CLEAN "
        f"pmhc_tce_supported — got {verdict}"
    )


@pytest.mark.parametrize("iedb", [_TV, _PR])
def test_broadly_presented_normal_still_vetoes(iedb):
    verdict, drv = _resolve(_KILL, iedb, _BROAD)
    assert verdict == "tce_unsafe_normal_liability" and drv == _BROAD, (
        f"a MEASURED broadly-presented-normal read must veto the promotion → tce_unsafe_normal_liability "
        f"(got {verdict}/{drv})"
    )


def test_clean_promotion_requires_the_restricted_presentation_conjunct():
    """TEETH: every resolver rung that emits the CLEAN pmhc_tce_supported must carry the measured
    restricted-presentation conjunct. This goes RED the instant a future edit reverts to minting the
    clean positive from IEDB evidence alone — the fail-open regression #2113 fixed."""
    clean_rungs = [
        r for r in _SPEC.get("resolve", []) if isinstance(r, dict) and r.get("verdict") == "pmhc_tce_supported"
    ]
    assert clean_rungs, "no rung emits pmhc_tce_supported — resolver shape changed unexpectedly"
    for r in clean_rungs:
        conj = set(r.get("when_all_fired") or ([r["when_fired"]] if "when_fired" in r else []))
        assert _RESTRICTED in conj, (
            f"a pmhc_tce_supported rung {r} mints the CLEAN positive WITHOUT the measured "
            f"{_RESTRICTED} conjunct — the #2113 fail-open guard has been removed."
        )
        assert _KILL in conj, f"pmhc_tce_supported rung {r} lost its neither-viable-killer conjunct"


# ── (2) the caveat earns NO nomination rescue (absent from the gate vocab, unlike the clean positive) ──
def _gate_vocab():
    p = CONTRACTS / "vocabularies" / "nomination_verdict_gate.yaml"
    if not p.exists():
        pytest.skip("nomination_verdict_gate.yaml unavailable")
    return yaml.safe_load(p.read_text())


def _all_when_surface_verdict_in(vocab) -> set:
    out: set = set()
    for arm in vocab.get("biology_axis_scoped_veto_downgrade") or []:
        out |= set(arm.get("when_surface_verdict_in") or [])
    return out


def test_caveat_is_not_in_the_veto_downgrade_admit_set_but_clean_positive_is():
    """The over-credit vector: `pmhc_tce_supported` turns a dependency:non_dependent veto→hold. The caveat
    must NOT (it is unconfirmed, non-nominating); the clean positive must still get the rescue."""
    admit = _all_when_surface_verdict_in(_gate_vocab())
    assert "pmhc_tce_supported" in admit, "clean pmhc_tce_supported unexpectedly lost its veto→hold admit"
    assert _CAVEAT not in admit, (
        f"{_CAVEAT} must NOT be in biology_axis_scoped_veto_downgrade.when_surface_verdict_in — a caveated, "
        f"normal-presentation-UNMEASURED route must not rescue an intracellular non_dependent target "
        f"(that IS the #2113 over-credit)."
    )


def test_caveat_is_not_a_nomination_positive_signal():
    vocab = _gate_vocab()
    pos = vocab.get("positive_signals_modality_scoped") or {}
    flat: set = set()

    def _collect(node):
        if isinstance(node, str):
            flat.add(node)
        elif isinstance(node, dict):
            for v in node.values():
                _collect(v)
        elif isinstance(node, list):
            for v in node:
                _collect(v)

    _collect(pos)
    assert _CAVEAT not in flat, f"{_CAVEAT} must be NON-NOMINATING (absent from positive_signals_modality_scoped)"
