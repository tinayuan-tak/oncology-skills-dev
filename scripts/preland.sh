#!/usr/bin/env bash
# preland.sh — run the contracts-validate gates locally before landing. Mirrors .github/workflows/contracts-validate.yml.
# NOTE: plain `pytest` does NOT invoke validators/validate_*.py, and contracts-validate is not a branch-protection-required
# check — so a schema violation can pass pytest yet turn trunk RED. Run THIS before landing any cards/ | interpretation-rules/
# | resolvers/ | vocabularies/ change. Bare python (no pixi in this repo).
set -uo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)" || exit 2
fail=0
run() { local label="$1"; shift; local out
  if out=$("$@" 2>&1); then echo "PASS  $label"
  else echo "FAIL  $label"; echo "$out" | tail -n 30 | sed 's/^/      /'; fail=1; fi; }
# --- gates (transcribed in order from contracts-validate.yml) ---
run "validate_cards"                     python validators/validate_cards.py cards/
run "validate_measurement_types"         python validators/validate_measurement_types.py
run "validate_interpretation_rules"      python validators/validate_interpretation_rules.py --rules interpretation-rules/ --cards cards/
run "validate_resolvers"                 python validators/validate_resolvers.py --resolvers resolvers/ --rules interpretation-rules/
run "validate_verdict_tokens"            python validators/validate_verdict_tokens.py --gate vocabularies/nomination_verdict_gate.yaml --resolvers resolvers/
run "validate_certainty_disjointness"    python validators/validate_certainty_disjointness.py
run "validate_card_resolver_consumption" python validators/validate_card_resolver_consumption.py
run "pytest tests/schemas"               python -m pytest tests/schemas/ -q
run "pytest test_eval_ledger"            python -m pytest tests/validators/test_eval_ledger.py -q
run "build_eval_ledger --self-check"     python validators/build_eval_ledger.py --self-check
run "pytest subgroup+coverage"           python -m pytest tests/validators/test_subgroup_assignments_and_coverage.py -q
run "pytest framework_discrimination"    python -m pytest tests/calibration/test_framework_discrimination.py -q
run "pytest card_concept_discipline"     python -m pytest tests/validators/test_card_concept_discipline.py -q
run "pytest nomination-gate+subtype-tier" python -m pytest tests/vocabularies/test_nomination_verdict_gate.py tests/validators/test_subtype_tier_rules.py -q
[ $fail -eq 0 ] && echo "ALL GATES PASS" || echo "GATES FAILED"
exit $fail
