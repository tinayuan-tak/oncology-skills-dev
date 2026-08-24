"""Guard: every rule_id in wt_loss_safety_conditioning.yaml must exist in the
interpretation-rules, and the concern/protective buckets must be disjoint.
Prevents the sidecar going stale under a rule rename (Layer-1 of VERDICT_REPRESENTATION.md)."""
from pathlib import Path
import glob
import yaml

REPO = Path(__file__).resolve().parents[2]


def _all_rule_ids():
    ids = set()
    for p in glob.glob(str(REPO / "interpretation-rules" / "*.rules.yaml")):
        for r in (yaml.safe_load(open(p)).get("rules") or []):
            ids.add(r["rule_id"])
    return ids


def _sidecar():
    return yaml.safe_load(open(REPO / "vocabularies" / "wt_loss_safety_conditioning.yaml"))


def test_all_referenced_rule_ids_exist():
    known = _all_rule_ids()
    sc = _sidecar()
    referenced = list(sc.get("concern_rules") or []) + list(sc.get("protective_rules") or [])
    missing = [r for r in referenced if r not in known]
    assert not missing, f"wt_loss_safety_conditioning references non-existent rule_ids: {missing}"


def test_concern_and_protective_disjoint():
    sc = _sidecar()
    concern = set(sc.get("concern_rules") or [])
    protective = set(sc.get("protective_rules") or [])
    overlap = concern & protective
    assert not overlap, f"a rule cannot be both concern and protective: {overlap}"


def test_conditioning_property_declared():
    assert _sidecar().get("conditioning_property") == "wt_engagement"
