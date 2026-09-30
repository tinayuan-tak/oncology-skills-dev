"""reliability_calibration — the per-property-KIND `powered` floors for the #2306 reliability facet.

Epic claude-oncology-skills#1507; structure arc #2210; the #2306 rollout follow-on that CALIBRATES the
`powered` tri-state so `_derive_reliability` (skills/_skills_common/reliability.py) computes `true`/`false`
instead of the uniform `unmeasured` PR#2326 emitted. Issue #2327.

This is the SINGLE SOURCE of the floors. The deriver reads them through `powered_floor_for`; the property
catalog's `determinants` blocks (dependency.yaml) DOCUMENT them and cite the flip matrix; neither restates
a value. Each calibrated floor is the property's OWN method's admissibility guard — imported, never
re-declared, so a second copy cannot drift (the CONFOUND_R single-source pattern PR#2326 used).
"""
