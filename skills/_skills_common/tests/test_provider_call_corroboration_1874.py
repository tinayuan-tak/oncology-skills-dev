"""SK#1874 (epic #1507 Arm B): unit teeth for the provider-DE-call corroboration wiring.

tumor-presence historically DISCARDED the DE provider's OWN significance/direction call on the
tumor-vs-adjacent contrast in favour of the effect-size-aware re-derived `expression_call_class`.
SK#1874 surfaces it as an INDEPENDENT corroboration arm and — the verdict-moving part — CAPS the
corroboration one step and raises a conflict when a re-derived "up" elevation is NOT corroborated by
the provider (fails its significance test, opposite direction, or rests on near-floor absolute
expression). The committed EPCAM/COADREAD golden exercises only the byte-stable `provider_only_significant`
path (uncorroborated_up=False), so these synthetic-context tests are the ONLY teeth on the cap+conflict
branch. Pure; no S3; touches no committed golden."""

from __future__ import annotations

from _skills_common.presence_claims import (  # noqa: E402
    _BASE_MEAN_FLOOR,
    _claim_B,
    _provider_call_corroboration,
)

_UP = ("up", 2)  # _dir("modest_upregulation")


# --- 1. Direct _provider_call_corroboration: each uncorroborated_up=True sub-case + negatives ---


def test_uncorroborated_up_when_rederived_only_significant():
    """re-derived "up", provider NOT significant -> rederived_only_significant -> uncorroborated_up."""
    r = _provider_call_corroboration(_UP, prov_sig=False, prov_up=False, base_mean=100.0)
    assert r["concordance"] == "rederived_only_significant"
    assert r["low_absolute_expression"] is False
    assert r["uncorroborated_up"] is True


def test_uncorroborated_up_when_direction_discordant():
    """re-derived "up", provider significant but calls DOWN -> direction_discordant -> uncorroborated_up."""
    r = _provider_call_corroboration(_UP, prov_sig=True, prov_up=False, base_mean=100.0)
    assert r["concordance"] == "direction_discordant"
    assert r["provider_direction"] == "down"
    assert r["uncorroborated_up"] is True


def test_uncorroborated_up_when_near_floor_low_abs():
    """re-derived "up", provider concordant, but base_mean < floor -> low_abs -> uncorroborated_up."""
    r = _provider_call_corroboration(_UP, prov_sig=True, prov_up=True, base_mean=_BASE_MEAN_FLOOR - 1.0)
    assert r["concordance"] == "concordant"
    assert r["low_absolute_expression"] is True
    assert r["uncorroborated_up"] is True


def test_corroborated_concordant_up_is_not_uncorroborated():
    """NEGATIVE: re-derived "up", provider concordant, well above floor -> uncorroborated_up=False."""
    r = _provider_call_corroboration(_UP, prov_sig=True, prov_up=True, base_mean=100.0)
    assert r["concordance"] == "concordant"
    assert r["low_absolute_expression"] is False
    assert r["uncorroborated_up"] is False


def test_absent_provider_call_returns_none():
    """NEGATIVE: no provider call (non-bool significance) -> None, so the claim stays byte-stable."""
    assert _provider_call_corroboration(_UP, prov_sig=None, prov_up=None, base_mean=100.0) is None


# --- 2. _claim_B-level synthetic context: cap one step + conflict string, and the corroborated mirror ---

_CONFLICT_SUBSTR = "not corroborated by provider DE call"


def _ctx(prov_sig, prov_up, base_mean, *, cptac_up):
    """Synthetic cards-by-id summary dict feeding _claim_B with a re-derived "up" RNA-DGE arm and,
    optionally, a second (CPTAC) up arm so len(ups)>=2 -> rel would otherwise be "high"."""
    c = {
        "tumor-rna-vs-adjacent": {
            "expression_call_class": "modest_upregulation",  # _dir -> ("up", 2)
            "log2_fc": 2.0,
            "q_value": 1e-8,
            "n_tumor": 50,
            "is_significant_provider_call": prov_sig,
            "is_upregulated_provider_call": prov_up,
            "base_mean": base_mean,
        }
    }
    if cptac_up:
        c["tumor-protein-abundance-cptac"] = {
            "protein_expression_class": "modest_upregulation",  # _dir -> ("up", 2)
            "protein_effect_size": 1.0,
            "protein_bh_q_value": 1e-5,
        }
    return c


def test_claim_b_uncorroborated_up_caps_moderate_to_low_and_conflicts():
    """Single up arm (rel would be "moderate") + uncorroborated provider call -> capped to "low" + conflict."""
    out = _claim_B({}, _ctx(prov_sig=False, prov_up=False, base_mean=100.0, cptac_up=False))
    assert out["corroboration"] == "low"
    assert _CONFLICT_SUBSTR in out["conflict"]
    assert out["provider_call"]["uncorroborated_up"] is True


def test_claim_b_uncorroborated_up_caps_high_to_moderate():
    """Two up arms (rel would be "high") + uncorroborated provider call -> capped to "moderate" + conflict."""
    out = _claim_B({}, _ctx(prov_sig=False, prov_up=False, base_mean=100.0, cptac_up=True))
    assert out["corroboration"] == "moderate"
    assert _CONFLICT_SUBSTR in out["conflict"]


def test_claim_b_corroborated_up_leaves_rel_and_conflict_unchanged():
    """MIRROR: same two-up context but provider CONCORDANT -> rel stays "high", no conflict raised."""
    out = _claim_B({}, _ctx(prov_sig=True, prov_up=True, base_mean=100.0, cptac_up=True))
    assert out["corroboration"] == "high"
    assert out["conflict"] is None
    assert out["provider_call"]["uncorroborated_up"] is False
