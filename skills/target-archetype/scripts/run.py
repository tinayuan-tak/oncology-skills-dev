#!/usr/bin/env python3
"""target-archetype — the verdict-INERT cross-skill nearest-reference COMPANION (standalone entry).

Unlike the 14 dispatcher sub-skills, this is a META layer: it has NO cards of its own. It consumes the
OTHER sub-skills' composed claim-vectors (a full-package target-profile run) and positions the target
against a FROZEN reference atlas — nearest analogs + soft archetype membership + rule-fingerprint
precedent + a missingness map. See _skills_common/archetype_core.py for the primitive and the governance
contract (DESCRIPTIVE, verdict=None, never a gate).

In the COMPOSED target-profile this runs as a reduction-stage facet (target-profile run.py, alongside
fragility / heterogeneity). This script is the STANDALONE / gallery entry: point it at an existing
`--package-dir` (a `target-profile --full-package` output tree with subskills/*/package.json +
nomination.json) and it emits `companion.json`.

BESPOKE MAIN (not run_wired_skill): target-archetype is cardless + non-fan-out, so it does not go through
the dispatcher. The OPTIONAL, verdict-INERT --synthesize / --literature lanes are wired HERE surgically:
a decision-shaped dict is built from the companion + nomination_scorecard (a PHENOTYPE/ANALOG/PRECEDENT/
NOVELTY/READINESS claim_vector), the --literature lane (Europe-PMC-grounded + PMID-verified) attaches
`decision['literature_synthesis']` BEFORE the --synthesize narrator (mirroring the dispatcher seam), and
the narrator runs the generic engine over the TARGET_ARCHETYPE LensConfig. Both lanes are structurally
verdict-INERT (this layer has no verdict to move).

Usage:
  python3 run.py --package-dir <full-package-run-dir> [--k 8] [--atlas <atlas.json>] [--out companion.json]
                 [--synthesize] [--literature] [--synthesis-model <id>] [--literature-model <id>]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2]  # .../skills
sys.path.insert(0, str(SKILLS_DIR))
from _skills_common.archetype_core import (  # noqa: E402
    Atlas,
    claim_features,
    nomination_scorecard,
    _attach_archetype_caveats,
)

SKILL_NAME = "target-archetype"
SKILL_VERSION = "0.6.0"  # 0.6.0 (2026-09-05, literature-and-claims arc, FIRST non-fan-out skill): CREATE
# the TARGET_ARCHETYPE narrator lens (LENSES 14→15) + wire a BESPOKE --synthesize
# + --literature path (this skill uses a bespoke main(), not run_wired_skill) that
# builds a decision-shaped dict from companion+scorecard; BAKE the phenotype/analog
# literature lane; verdict-INERT confidence surface — archetype_confidence_caveat
# (3-tier: phenotype_mixture_low_stability_or_missingness_distorted /
# analog_or_label_circular / validated_canonical_anchor false-demote guard) +
# scorecard_confidence_caveat (illustrative-not-learned; cite RETIRED D2/D3) +
# archetype_provenance QUORUM. Cardless + verdict-INERT → verdict None byte-stable,
# NO atlas re-freeze, NO resolver. MUST equal SKILL.md metadata.version.

_DEFAULT_ATLAS = SKILLS_DIR / "target-archetype" / "atlas" / "atlas.json"


def _read_package_dir(pkg_dir: Path) -> tuple[dict, set, str, str]:
    """Read a full-package run dir -> (subskill_claim_vectors, fired_rule_ids, target, indication)."""
    nom_f = pkg_dir / "nomination.json"
    nom = json.loads(nom_f.read_text()) if nom_f.exists() else {}
    target, indication = nom.get("target"), nom.get("indication")
    cvs: dict = {}
    for pkg in glob.glob(str(pkg_dir / "subskills" / "*" / "package.json")):
        d = json.loads(Path(pkg).read_text())
        short = d.get("sub_skill") or os.path.basename(os.path.dirname(pkg))
        cv = d.get("claim_vector")
        if isinstance(cv, dict) and cv:
            cvs[short] = cv
    rules: set = set()
    for v in (nom.get("sub_verdicts") or {}).values():
        if isinstance(v, dict):
            rules.update(v.get("fired_rule_ids") or [])
    return cvs, rules, target, indication


# ── decision-shaped dict for the bespoke --synthesize / --literature lanes ──────────────────────────
def _tier(x, hi: float, mid: float, *, order="pos") -> str:
    """Ordinal tier from a scalar. order='pos' → strong/moderate/weak; 'corr' → high/moderate/low."""
    if x is None:
        return "unmeasured"
    if order == "corr":
        return "high" if x >= hi else "moderate" if x >= mid else "low"
    return "strong" if x >= hi else "moderate" if x >= mid else "weak"


def _short_detail(caveat, *, cap: int = 260) -> str:
    d = (caveat or {}).get("detail") or ""
    return (d[:cap].rsplit(" ", 1)[0] + "…") if len(d) > cap else d


def _archetype_claim_vector(companion: dict, scorecard: dict) -> dict:
    """Build the PHENOTYPE/ANALOG/PRECEDENT/NOVELTY/READINESS claim_vector the TARGET_ARCHETYPE lens narrates
    + the literature lane grounds — sourced entirely from the deterministic companion + scorecard (numbers the
    LLM can cite, no capsule/card data since this layer is cardless)."""
    mix = companion.get("soft_membership") or {}
    dom = max(mix, key=mix.get) if mix else None
    dom_mass = mix.get(dom) if dom else None
    top3 = ", ".join(f"{k} {v:.0%}" for k, v in list(mix.items())[:3])
    mu = companion.get("mixture_uncertainty") or {}
    stab = mu.get("stability")
    miss = companion.get("missingness") or {}
    n_meas, n_tot = miss.get("n_features_measured"), miss.get("n_features_total")
    unmeasured = miss.get("unmeasured_axes") or []
    analogs = companion.get("nearest_analogs") or []
    top = analogs[0] if analogs else {}
    nov = companion.get("novelty") or {}
    prec = companion.get("rule_precedent") or []
    cc = companion.get("archetype_confidence_caveat") or {}
    sc_caveat = (scorecard or {}).get("scorecard_confidence_caveat") or {}
    score = (scorecard or {}).get("score")
    coverage = (scorecard or {}).get("coverage")
    cf = (scorecard or {}).get("counterfactual_gap") or {}
    driving = ", ".join(a["axis"] for a in ((scorecard or {}).get("driving_axes") or [])[:3])

    cv: dict = {}
    cv["PHENOTYPE"] = {
        "signal": _tier(dom_mass, 0.5, 0.3),
        "corroboration": _tier(stab, 0.7, 0.4, order="corr"),
        "evidence": (
            f"dominant={dom} {dom_mass:.0%}; mixture[{top3}]; jackknife stability={stab}; "
            f"measured {n_meas}/{n_tot} atlas features; unmeasured axes={unmeasured or 'none'} "
            "(soft DISTRIBUTION, not a hard label)"
        ),
        "conflict": (
            _short_detail(cc)
            if cc.get("reason") == "phenotype_mixture_low_stability_or_missingness_distorted"
            else None
        ),
    }
    an = "; ".join(
        f"{a['target']}({a['archetype_label']}{'~DERIVED' if a.get('label_is_derived') else ''},d={a['distance']})"
        for a in analogs[:3]
    )
    cv["ANALOG"] = {
        "signal": "moderate",
        "corroboration": "low" if top.get("label_is_derived") else ("high" if top else "unmeasured"),
        "evidence": f"nearest analogs: {an or 'none'}",
        "conflict": _short_detail(cc) if cc.get("reason") == "analog_or_label_circular" else None,
    }
    if prec:
        p = prec[0]
        cv["PRECEDENT"] = {
            "signal": _tier(p.get("weighted_jaccard"), 0.4, 0.2),
            "corroboration": "moderate",
            "evidence": (
                f"top rule-fingerprint precedent: {p['target']}({p['archetype_label']}, "
                f"weighted_jaccard={p['weighted_jaccard']}); shared rungs={p.get('top_shared_rules')}"
            ),
        }
    else:
        cv["PRECEDENT"] = {
            "signal": "unmeasured",
            "corroboration": "unmeasured",
            "evidence": "no fired-rule fingerprint supplied (query_rules empty for this run)",
        }
    cv["NOVELTY"] = {
        "signal": ("strong" if nov.get("inconsistent_flag") else "moderate" if nov.get("multimodal") else "absent"),
        "corroboration": "moderate",
        "evidence": (
            f"inconsistent_flag={nov.get('inconsistent_flag')} "
            f"(scale-invariant rel_residual={nov.get('hull_residual_relative')}); "
            f"multimodal={nov.get('multimodal')}(n_dominant={nov.get('n_dominant_phenotypes')}); "
            f"mixture_entropy={nov.get('mixture_entropy')}; "
            f"local_density_flag={nov.get('local_density_flag')}"
        ),
    }
    cv["READINESS"] = {
        "signal": _tier(score, 0.6, 0.4),
        "corroboration": _tier(coverage, 0.7, 0.4, order="corr"),
        "evidence": (
            f"D1 nomination-readiness score={score} (coverage={coverage}); phenotype route="
            f"{(scorecard or {}).get('dominant_archetype_soft')}; driving axes={driving or 'n/a'}; "
            f"route-limiting axis={cf.get('limiting_axis')}. ILLUSTRATIVE weights (SHOWN, not learned)"
        ),
        # ALWAYS surface the illustrative-not-learned caveat as a CONFLICT flag on READINESS (the score
        # orients, never nominates — the RETIRED-D2/D3 lesson).
        "conflict": _short_detail(sc_caveat) if sc_caveat else None,
    }
    return cv


def _build_decision(companion: dict, scorecard: dict, target, indication) -> dict:
    """A minimal decision-shaped dict the generic narrator_engine + literature_synthesis consume. CARDLESS:
    the raw evidence_capsules package is empty (this META layer reads no cards) — the phenotype-landscape
    NUMBERS ride in the claim_vector evidence strings, which lead the narration (signals-first)."""
    cc = companion.get("archetype_confidence_caveat") or {}
    sc_caveat = (scorecard or {}).get("scorecard_confidence_caveat") or {}
    mix = companion.get("soft_membership") or {}
    dom = max(mix, key=mix.get) if mix else None
    analogs = companion.get("nearest_analogs") or []
    an = ", ".join(a["target"] for a in analogs[:2])
    stab = (companion.get("mixture_uncertainty") or {}).get("stability")
    miss = companion.get("missingness") or {}
    headline_phrase = (
        f"{target}/{indication}: phenotype mixture dominated by '{dom}' "
        f"({mix.get(dom, 0):.0%}); most like {an or 'n/a'}; jackknife stability {stab}, "
        f"{miss.get('n_features_measured')}/{miss.get('n_features_total')} atlas features measured; "
        f"D1 readiness {(scorecard or {}).get('score')}. DESCRIPTIVE signature LANDSCAPE — a soft mixture, "
        "NOT a classification or nomination."
    )
    # the PRIMARY caveat surfaced to the narrator + literature lane (read from key_signals.caveat): the
    # confidence caveat if it fired (over-call concern), else the always-present illustrative-weight note.
    caveat = _short_detail(cc, cap=400) if cc else (_short_detail(sc_caveat, cap=400) if sc_caveat else None)
    return {
        "target": target,
        "indication": indication,
        "headline": {
            "claim_vector": _archetype_claim_vector(companion, scorecard),
            "key_signals": {"headline": headline_phrase, "caveat": caveat},
            "evidence_capsules": {"capsules": {}, "manifest": []},  # cardless META layer — no card capsules
        },
        "cards": [],
    }


def _run_literature(decision: dict, model_id):
    from _skills_common.literature_synthesis import make_literature_fn
    from _skills_common.literature_retrieval import default_retrieve, verify_citations
    from _skills_common.narrator_lenses import TARGET_ARCHETYPE

    lit_fn = make_literature_fn(TARGET_ARCHETYPE, retrieve_fn=default_retrieve, verify_fn=verify_citations)
    return lit_fn(decision, model_id)


def _run_synthesize(decision: dict, model_id):
    from _skills_common.narrator_engine import make_synthesize_fn
    from _skills_common.narrator_lenses import TARGET_ARCHETYPE

    return make_synthesize_fn(TARGET_ARCHETYPE)(decision, model_id, None)


def main():
    ap = argparse.ArgumentParser(description="target-archetype nearest-reference companion (verdict-inert)")
    ap.add_argument("--package-dir", required=True, help="a target-profile --full-package output tree")
    ap.add_argument("--atlas", default=str(_DEFAULT_ATLAS))
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--out", default=None, help="default: <package-dir>/companion.json")
    ap.add_argument(
        "--synthesize",
        action="store_true",
        help="OPTIONAL verdict-INERT LLM phenotype-landscape narration (needs system python + "
        "BEDROCK_AWS_PROFILE). Attaches decision['llm_synthesis'] to the emitted doc.",
    )
    ap.add_argument(
        "--literature",
        action="store_true",
        help="OPTIONAL verdict-INERT LLM literature lane grounding the dominant phenotype + top "
        "analog (Europe PMC + PMID-verified). Attaches decision['literature_synthesis'] and "
        "feeds it to the --synthesize narrator.",
    )
    ap.add_argument("--synthesis-model", default=None, help="Bedrock model id for --synthesize (default: Opus).")
    ap.add_argument("--literature-model", default=None, help="Bedrock model id for --literature (default: Opus).")
    a = ap.parse_args()

    pkg_dir = Path(a.package_dir).expanduser()
    atlas = Atlas.load(a.atlas)
    cvs, rules, target, indication = _read_package_dir(pkg_dir)
    if not cvs:
        print(f"no sub-skill claim_vectors found under {pkg_dir}/subskills/*/package.json", file=sys.stderr)
        raise SystemExit(2)
    feat = claim_features(cvs)
    companion = atlas.companion(feat, k=a.k, query_rules=rules)
    scorecard = nomination_scorecard(feat, companion.get("soft_membership"), atlas)
    # VERDICT-INERT confidence surface (archetype_confidence_caveat + archetype_provenance), attached exactly
    # as the composed reduction hook does (companion_from_sub_results) so standalone == composed.
    _attach_archetype_caveats(companion, target=target, indication=indication)

    doc = {
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "target": target,
        "indication": indication,
        "verdict": None,  # governance: descriptive companion
        "companion": companion,
        "nomination_scorecard": scorecard,  # D1 glass-box readiness (verdict-inert)
    }

    # OPTIONAL verdict-INERT LLM lanes (bespoke seam mirroring the dispatcher: literature BEFORE synthesize so
    # the narrator can CITE it). Best-effort — a Bedrock/network fault degrades to a note, never breaks the
    # deterministic companion. This layer has NO verdict, so the lanes are structurally verdict-inert.
    if a.synthesize or a.literature:
        decision = _build_decision(companion, scorecard, target, indication)
        if a.literature:
            try:
                decision["literature_synthesis"] = _run_literature(decision, a.literature_model)
            except Exception as e:  # noqa: BLE001
                decision["literature_synthesis"] = {
                    "_literature_error": f"{type(e).__name__}: {e}",
                    "_note": "literature lane unavailable; companion unaffected.",
                }
            doc["literature_synthesis"] = decision["literature_synthesis"]
        if a.synthesize:
            try:
                doc["llm_synthesis"] = _run_synthesize(decision, a.synthesis_model)
            except Exception as e:  # noqa: BLE001
                doc["llm_synthesis"] = {
                    "_synthesis_error": f"{type(e).__name__}: {e}",
                    "_note": "narration unavailable; companion unaffected.",
                }

    out = Path(a.out) if a.out else pkg_dir / "companion.json"
    out.write_text(json.dumps(doc, indent=2))

    mem = " · ".join(f"{k}:{v:.0%}" for k, v in list(companion["soft_membership"].items())[:3])
    an = ", ".join(x["target"] for x in companion["nearest_analogs"][:4])
    print(f"{target}/{indication}")
    print(f"  soft membership : {mem}")
    print(f"  nearest analogs : {an}")
    nov = companion["novelty"]
    print(
        f"  novelty         : inconsistent={nov['inconsistent_flag']} "
        f"(rel_residual={nov['hull_residual_relative']}), multimodal={nov['multimodal']}"
        f"({nov['n_dominant_phenotypes']}), entropy={nov['mixture_entropy']}, "
        f"low_density={nov['local_density_flag']}"
    )
    print(f"  mixture stab.   : {companion['mixture_uncertainty'].get('stability')}")
    print(f"  unmeasured axes : {companion['missingness']['unmeasured_axes']}")
    cc = companion.get("archetype_confidence_caveat")
    print(f"  confidence      : {(cc or {}).get('reason')} [{(cc or {}).get('tier')}]")
    cf = (scorecard.get("counterfactual_gap") or {}).get("limiting_axis")
    voi = scorecard.get("value_of_information") or []
    top_voi = ", ".join(f"{v['axis']}(+{v['projected_score_gain']})" for v in voi[:3])
    print(
        f"  D1 readiness    : score={scorecard.get('score')} coverage={scorecard.get('coverage')} "
        f"route={scorecard.get('dominant_archetype_soft')} limiting_axis={cf}"
    )
    if top_voi:
        print(f"  value-of-info   : {top_voi}")
    if doc.get("literature_synthesis"):
        _v = (doc["literature_synthesis"] or {}).get("_verification") or {}
        print(
            f"  literature      : axes={len(((doc['literature_synthesis'] or {}).get('axes')) or [])} "
            f"verification={_v.get('status')} verified={_v.get('n_verified')}/{_v.get('n_pmid_checked')}"
        )
    if doc.get("llm_synthesis") and "context_read" in (doc["llm_synthesis"] or {}):
        print("  narration       : llm_synthesis attached (context_read)")
    print(f"  wrote {out}")


if __name__ == "__main__":
    main()
