"""depmap_partner_conditional_dependency.read — library entry for partner-conditional dependency.

Mirrors depmap_cn_dependency/read.py's shape + error handling. For the target, looks up its
curated partner(s) in partner_map.yaml, builds each partner's DEFICIENCY boolean vector
(MSI-signature or LoF-mutation), runs the shared Mann-Whitney contrast on the target's Chronos,
and returns the STRONGEST-signal partner's summary_fields (all partners retained under
`_all_partner_results` for transparency). Target-only (indication accepted for dispatcher
signature, not consumed).

Returns the partner-conditional-dependency card's summary_fields, or a dict with
_live_read_error / no_partner_mapped when the underlying data is unreachable or unmapped.
"""

from __future__ import annotations

from typing import Optional

from . import cli as _cli

METHOD_VERSION = _cli.METHOD_VERSION
DEFAULT_AWS_PROFILE = "cbg"

# Precedence for "strongest" partner result when a target has multiple mapped partners.
_CLASS_RANK = {
    "partner_conditional_strongly_dependent": 0,
    "partner_conditional_moderately_dependent": 1,
    "partner_neutral_strongly_dependent": 2,
    "not_partner_stratified": 3,
    "insufficient_partner_deficient_rate": 4,
    "no_partner_mapped": 5,
    "data_unavailable": 6,
}


from onc_methods.target_id_sidecar import ensure_aws_profile


def read_partner_conditional_dependency(
    target: str, indication: Optional[str] = None, release_pin: str = "26q3"
) -> dict:
    """Compute partner-conditional dependency for target across the DepMap panel.

    `indication` is accepted for dispatcher-signature back-compat but NOT consumed (target-only,
    like the CN/mutation-stratified siblings). Returns the card's summary_fields (strongest partner),
    or a dict with _live_read_error / no_partner_mapped when data is unreachable / unmapped.
    """
    ensure_aws_profile()

    partner_map = _cli.load_partner_map()
    entries = partner_map.get(target, [])
    if not entries:
        return {
            "partner_stratification_class": "no_partner_mapped",
            "target": target,
            "_note": "target has no curated partner in partner_map.yaml; "
            "extend the map (SynLethDB is the candidate-generation source).",
        }

    # 1. Chronos for the TARGET (reuse the shared loader).
    from onc_methods.depmap_chronos_distribution import cli as c1cli

    chronos_by_model, model_metadata, chronos_errs = c1cli.load_depmap_files(
        release_pin=release_pin, target_symbol=target
    )
    if chronos_errs:
        return {
            "_live_read_error": chronos_errs[0].get("_live_read_error", "s3_or_local_read_failed"),
            "errors": chronos_errs,
            "_remediation": "Method cannot reach DepMap Chronos; verify local cache or AWS credentials.",
            "partner_stratification_class": "data_unavailable",
        }
    if not chronos_by_model:
        return {
            "_live_read_error": "no_chronos_for_target",
            "target": target,
            "partner_stratification_class": "data_unavailable",
        }

    # 2. For each mapped partner, build its deficiency vector + run the contrast.
    all_results = []
    for entry in entries:
        partner = entry["partner"]
        dtype = entry["deficiency_type"]
        try:
            deficient_by_model = _cli.build_partner_deficiency_vector(release_pin, partner, dtype)
        except Exception as e:  # absence-discipline: exempt -- per-partner best-effort INSIDE a multi-partner loop: this records partner_stratification_class=data_unavailable AND sets _live_read_error for the SINGLE failing partner then continues, so the failure is OBSERVABLE (not the silent dead axis this ratchet targets) and the blast radius is one partner, never the whole verdict -- per-partner isolation is a deliberate resilience choice so one flaky partner cannot abort the whole panel
            all_results.append(
                {
                    "partner": partner,
                    "deficiency_type": dtype,
                    "partner_stratification_class": "data_unavailable",
                    "_live_read_error": f"partner_deficiency_load_failed: {type(e).__name__}: {e}",
                }
            )
            continue
        if not deficient_by_model:
            all_results.append(
                {
                    "partner": partner,
                    "deficiency_type": dtype,
                    "partner_stratification_class": "insufficient_partner_deficient_rate",
                    "_note": "no partner-deficiency calls loaded (partner absent from source or all-null).",
                }
            )
            continue
        summary = _cli.compute_partner_stratification(chronos_by_model, deficient_by_model)
        summary["partner"] = partner
        summary["deficiency_type"] = dtype
        all_results.append(summary)

    # 3. Pick the strongest-signal partner as the headline; retain all.
    all_results.sort(key=lambda r: _CLASS_RANK.get(r.get("partner_stratification_class"), 99))
    headline = dict(all_results[0])
    headline["target"] = target
    headline["_all_partner_results"] = all_results
    headline["_method_version"] = METHOD_VERSION
    return headline
