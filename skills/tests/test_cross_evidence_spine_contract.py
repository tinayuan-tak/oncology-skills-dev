"""Cross-skill CONTRACT guard (roadmap §10): the fields the cross-evidence-hypothesis integrator
DECLARES it reads from the target-profile spine (`composition.reads_spine_fields` in its SKILL.md) MUST
actually be PRODUCIBLE by the target-profile evidence_package emitter.

This is the drift guard the alignment sweep (#744/#746/#747) was missing: it fails LOUD when either side
drifts — the emitter renames/drops a field the integrator reads (e.g. `decision_facets` → `facets`), OR
the integrator adds a `reads_spine_fields` entry the emitter never produces. It builds ONE MAXIMAL
evidence_package (safety short + subtypes + the decision_facets kwargs + registry-backed cards so
evidence_substrate stamps) via the real `_write_evidence_package`, then resolves every declared path.

Offline: `resolve_cards` (target-identity) is monkeypatched; no Bedrock, no S3.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import yaml

from _skills_common.compose_core import subskill_composition
from _test_support import load_run_py

SKILLS = Path(__file__).resolve().parents[1]          # .../skills
SKILL_MD = SKILLS / "cross-evidence-hypothesis" / "SKILL.md"


def _load_tp_run():
    return load_run_py(SKILLS / "target-profile", "tp_run_contract")


def _declared_reads_spine_fields() -> list:
    """Parse composition.reads_spine_fields out of the integrator's SKILL.md YAML frontmatter."""
    text = SKILL_MD.read_text()
    assert text.startswith("---"), "SKILL.md must open with YAML frontmatter"
    # split ONLY on lines that are exactly `---` (a `# --- ... ---` comment inside the block must not
    # truncate the frontmatter, as a naive text.split('---') would).
    parts = re.split(r"(?m)^---[ \t]*$", text)
    fm = parts[1]
    meta = yaml.safe_load(fm)
    reads = (meta.get("composition") or {}).get("reads_spine_fields")
    assert isinstance(reads, list) and reads, "composition.reads_spine_fields must be a non-empty list"
    return reads


_IDENTITY_CARD = {
    "card_id": "target-identity-summary",
    "summary": {"resolved_hgnc_symbol": "KRAS", "resolved_hgnc_id": 6407},
    "interpretation_call": "resolved",
    "provenance": {"method_calls": [], "input_manifest_ids": []},
}


def _card(card_id):
    return {"card_id": card_id, "summary": {"x": 1}, "interpretation_call": "informative",
            "provenance": {"method_calls": [], "input_manifest_ids": []}}


def _sub(card_id, fired_id, gate, verdict_pair, synthesis_facet=None):
    cards = [_card(card_id)]
    fired = [{"rule_id": fired_id}]
    out = {"skill_dir": f"dir-{gate or 'none'}", "cards": cards, "fired": fired,
           "verdict": verdict_pair,
           "composition": subskill_composition(card_outputs=cards, fired=fired, gate=gate,
                                               verdict_pair=verdict_pair)}
    if synthesis_facet is not None:
        out["synthesis_facet"] = synthesis_facet
    return out


_DEP_FACET = {
    "claim_vector": {"DEP": {"signal": "strong", "corroboration": "high",
                             "evidence_atom": {"read": "strongly_selective",
                                               "values": {"bimodality_coefficient": 0.7},
                                               "cite": {"card_id": "pan-cancer-crispr-dependency-distribution",
                                                        "fields": ["bimodality_coefficient"]}}},
                     "_disclaimer": "verdict-inert"},
    "key_signals": {"headline": "Strong genetic dependency."},
}


def _build_maximal_pkg(tmp_path, tp):
    """Build a MAXIMAL evidence_package that exercises every declared reads_spine_field: a safety short
    (→ safety_verdict_by_modality stamp), a claim-vector facet, registry-backed cards (→ evidence_substrate
    stamp), a populated recommendation_gate.hard_gates, all decision_facets kwargs, and --subtypes (→
    subtype_resolved.per_stratum)."""
    import tp_evidence_package
    tp_evidence_package.resolve_cards = lambda card_ids, target, indication, **kw: [dict(_IDENTITY_CARD)]

    sub_results = {
        # registry-backed card_ids so evidence_substrate stamps; a subtype-capable axis for per_stratum
        "expression": _sub("tumor-rna-distribution", "expr-01", None, ("tumor_broadly_expressed", "expr-01")),
        "dependency": _sub("pan-cancer-crispr-dependency-distribution", "dep-01", "dependency",
                           ("selective_dependency", "dep-01"), synthesis_facet=_DEP_FACET),
        "selectivity": _sub("tumor-vs-normal-selectivity", "sel-01", "selectivity",
                            ("tumor_selective", "sel-01")),
        "safety": _sub("gnomad-lof-constraint", "gnomad-lof-intolerant", "safety",
                       ("human_genetics_safety_concern", "gnomad-lof-intolerant")),
    }
    args = SimpleNamespace(target="KRAS", indication="COADREAD", release_pin=None, out=tmp_path)
    recommendation_gate = {
        "fired": False, "forced_recommendation": None,
        "hard_gates": [{"short": "dependency", "verdict": "non_dependent", "disposition": "gated",
                        "status": "latent", "live_verdict": "selective_dependency", "policy_source": "vocab"}],
    }
    ep_path = tp._write_evidence_package(
        args=args, sub_results=sub_results, gate_action=None,
        recommendation_gate=recommendation_gate, confidence_tier={"tier": "high"},
        deciding_axis={"basis": "gate_fired",
                       "deciding_axis": {"short": "dependency", "gate": "dependency"}, "routing": "x"},
        validation_summary={"n_cards_attempted": 4, "n_cards_passed": 4,
                            "n_cards_passed_with_warnings": 0, "n_cards_failed": 0,
                            "n_cards_excluded_by_applies_when": 0},
        subtypes=["MSS"], subtype_facet=None,
        certainty_by_axis={"dependency": {"strength": "strong_positive",
                                          "certainty": {"level": "high", "coverage": "high",
                                                        "corroboration": "high", "unknown_mass": 0.0}}},
        cross_gate_shared_evidence={"shared_input_cards": {}, "correlated_gate_pairs": []},
        fragility={"contested": False, "acquisition_backlog": []},
        competitor_crossref={"competition_density": "whitespace"},
        modality="small_molecule")
    return json.loads(Path(ep_path).read_text())


def _resolve(obj, path):
    """Resolve a dotted spine-field path against the package. Supports `*` (each dict value), `foo[]`
    (each list element), and `cards[]` (the top-level cards array). Returns True iff the leaf is
    PRODUCIBLE — a scalar leaf key is present, or (for a collection) at least one element resolves."""
    tokens = path.split(".")

    def _walk(cur, toks):
        if not toks:
            return True
        tok, rest = toks[0], toks[1:]
        if tok.endswith("[]"):
            key = tok[:-2]
            coll = cur.get(key) if isinstance(cur, dict) else None
            if not isinstance(coll, list) or not coll:
                return False
            return any(isinstance(e, dict) and _walk(e, rest) for e in coll)
        if tok == "*":
            if not isinstance(cur, dict) or not cur:
                return False
            return any(_walk(v, rest) for v in cur.values())
        if not isinstance(cur, dict) or tok not in cur:
            return False
        return _walk(cur[tok], rest) if rest else True

    return _walk(obj, tokens)


def test_declared_reads_spine_fields_are_all_producible(tmp_path):
    tp = _load_tp_run()
    ep = _build_maximal_pkg(tmp_path, tp)
    declared = _declared_reads_spine_fields()
    unresolved = [p for p in declared if not _resolve(ep, p)]
    assert unresolved == [], (
        "cross-evidence-hypothesis reads_spine_fields NOT producible by the target-profile "
        f"evidence_package emitter (contract drift): {unresolved}. Either the emitter renamed/dropped "
        "the field, or the SKILL.md declaration is stale.")


def test_contract_guard_would_catch_a_rename(tmp_path):
    """Meta: prove the resolver actually has teeth — a renamed spine field must NOT resolve."""
    tp = _load_tp_run()
    ep = _build_maximal_pkg(tmp_path, tp)
    assert _resolve(ep, "synthesis.decision_facets.certainty_by_axis") is True
    assert _resolve(ep, "synthesis.decision_facets.certainty_by_axis_RENAMED") is False
    assert _resolve(ep, "synthesis.sub_verdicts.safety.safety_verdict_by_modality") is True
