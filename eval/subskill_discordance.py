#!/usr/bin/env python3
"""subskill_discordance — the standing per-subskill omics↔literature DISCORDANCE harness + ROUTER.

The composed target-profile emits, per subskill, a corpus-grounded literature read vs the deterministic
omics signal (evidence_graph.literature.axes[].agreement_vs_omics + assertion + citation_ids + a
key_divergence). This tool aggregates the SHARP per-axis `contradicts` across a panel, then ROUTES each
discordance to its failure class (RFC eval/RFC_discordance_failure_taxonomy.md) so the output is a CLASSIFIED
backlog, not a flat list — detection generalizes, but each class needs a different layer to fix:

  A precedence      — resolver picked a winner but a co-fired rung was discarded (Engine1/2)
  B measurement     — omics measured the wrong scope/mechanism; resolver correct given the data (data layer)
  C synthesis       — gate did NOT veto but the Tier-3 LLM did (synthesis prompt)
  E framing         — a measured negative orthogonal to the target's engagement mode (Engine2 downgrade)
  (D coverage       — axis unmeasurable; reported as the `unmeasurable` column, not a `contradicts` case)

Class A uses resolve_verdict_provenance re-run on the persisted fired set (no run-output change needed).
Routing is a TRIAGE proposal; a human confirms (esp. Class B, which can be a real biological negative).

Usage: python subskill_discordance.py <run_glob_or_dir>...  [--json OUT.json]
"""

from __future__ import annotations

import glob
import json
import os
import sys
from collections import defaultdict

# lazy/guarded framework imports (harness still runs for B/C/D + raw counts if these are unavailable)
try:
    from _skills_common.biology_axis import resolve_biology_axis
    from _skills_common.resolver import load_resolver, resolve_verdict_provenance

    _FW = True
except Exception:  # noqa: BLE001
    _FW = False

_CONTRA = "contradicts"
_UNAVAIL = ("omics_unavailable", "omics_blind")
_SHORT_TO_GATE = {  # subskill short -> resolver gate name (resolver-backed axes only)
    "dependency": "dependency",
    "safety": "safety",
    "selectivity": "selectivity",
    "genomic_alteration": "genomic_alteration",
    "surface_modality": "surface_modality",
    "tractability_sm": "tractability_small_molecule",
    "mechanism": "mechanism",
    "differentiation": "differentiation",
    "cis_coherence": "cis_coherence",
}
_EXTRINSIC_AXES = ("surface_intrinsic", "extrinsic", "mixed")  # engagement modes where dep/sel is orthogonal
_axis_cache: dict = {}
_spec_cache: dict = {}


def _lit_of(rep: dict) -> dict:
    eg = rep.get("evidence_graph") if isinstance(rep, dict) else None
    return (eg or {}).get("literature") or {} if isinstance(eg, dict) else {}


def _biology_axis(target: str) -> str | None:
    if not _FW:
        return None
    sym = target.split("-")[0]
    if sym not in _axis_cache:
        try:
            r = resolve_biology_axis(sym)
            _axis_cache[sym] = r.get("biology_axis") if isinstance(r, dict) else None
        except Exception:  # noqa: BLE001
            _axis_cache[sym] = None
    return _axis_cache[sym]


# A precedence INVERSION is a real bug only when a MORE-AUTHORITATIVE signal was DISCARDED under a weaker
# winner — not merely "some rung lost" (that is normal multi-match). Seeded with the modality-authoritative
# downgrade (biologic-only annotation) losing to a weaker SM-positive — the tractability_sm case. Extend as
# the evidence-strength order (RFC P3) is formalized. Keeps Class A precise so B (measurement) is the residual.
_AUTHORITATIVE_DOWNGRADES = {"annotation_only_indirect"}
_WEAKER_POSITIVES = {"structurally_ligandable", "chemically_active", "druggable_genome", "clinical_precedent_only"}


def _precedence_inversion(short: str, fired_ids: list[str]) -> bool:
    """Class-A probe: re-run resolve_verdict_provenance (D1) on the persisted fired set; True iff an
    AUTHORITATIVE-downgrade rung was DISCARDED while a WEAKER positive won. Guarded → False if unavailable."""
    gate = _SHORT_TO_GATE.get(short)
    if not (_FW and gate and fired_ids):
        return False
    if gate not in _spec_cache:
        try:
            _spec_cache[gate] = load_resolver(gate)
        except Exception:  # noqa: BLE001
            _spec_cache[gate] = None
    spec = _spec_cache[gate]
    if not spec:
        return False
    try:
        winner, _d, discarded = resolve_verdict_provenance([{"rule_id": r} for r in fired_ids], spec)
        if winner not in _WEAKER_POSITIVES:
            return False
        return any(v in _AUTHORITATIVE_DOWNGRADES for _pr, v, _dr in discarded)
    except Exception:  # noqa: BLE001
        return False


def _classify(short, biology_axis, fired_ids) -> tuple[str, str]:
    """Route a contradicted subskill to its failure class + home layer (first match)."""
    if short in ("dependency", "selectivity") and biology_axis in _EXTRINSIC_AXES:
        return "E-framing", "Engine2 biology_axis/modality downgrade"
    if _precedence_inversion(short, fired_ids):
        return "A-precedence", "resolver provenance + gate reconciler"
    return "B-measurement", "data/rules layer (stratified reads / applicability caveat)"


def build_profile(patterns: list[str]) -> dict:
    per = defaultdict(lambda: {"targets": 0, "contradicts": 0, "unmeasurable": 0, "cases": []})
    classes: dict = defaultdict(int)
    c_synthesis_targets: list = []
    seen: set[str] = set()
    n = 0
    for pat in patterns:
        for d in sorted(glob.glob(pat)):
            if not os.path.isdir(d):
                continue
            t = os.path.basename(os.path.dirname(d))
            f = os.path.join(d, "nomination.json")
            if t in seen or not os.path.exists(f):
                continue
            try:
                nom = json.load(open(f))
            except (OSError, ValueError):
                continue
            seen.add(t)
            n += 1
            tr = nom.get("target_report") or {}
            tc = tr.get("target_call") or nom.get("target_call") or {}
            gate_fired = (tc.get("gate") or {}).get("fired")
            llm = nom.get("llm_synthesis", {}).get("overall_recommendation")
            llm = llm.get("value") if isinstance(llm, dict) else llm
            if llm == "veto" and gate_fired is False:  # C-synthesis is a TARGET property (LLM-authored veto)
                c_synthesis_targets.append(t)
            bax = _biology_axis(t)
            for short, rep in (tr.get("skill_reports") or {}).items():
                lit = _lit_of(rep)
                axes = lit.get("axes") or []
                if not axes and not lit:
                    continue
                ags = [(a.get("agreement_vs_omics") or "") for a in axes]
                if not ags:
                    continue
                p = per[short]
                p["targets"] += 1
                if all(x in _UNAVAIL or x == "" for x in ags):
                    p["unmeasurable"] += 1
                    continue
                if _CONTRA in ags:
                    p["contradicts"] += 1
                    fired_ids = ((rep.get("provenance") or {}).get("fired_rule_ids")) or []
                    cls, layer = _classify(short, bax, fired_ids)
                    classes[cls] += 1
                    p["cases"].append(
                        {
                            "target": t,
                            "class": cls,
                            "layer": layer,
                            "biology_axis": bax,
                            "key_divergence": lit.get("key_divergence") or "",
                            "n_citations": sum(
                                len(a.get("citation_ids") or []) for a in axes if a.get("agreement_vs_omics") == _CONTRA
                            ),
                        }
                    )
    return {
        "n_targets": n,
        "framework_imports": _FW,
        "class_totals": dict(classes),
        "c_synthesis_targets": c_synthesis_targets,
        "per_subskill": dict(per),
    }


def render(profile: dict) -> str:
    per = profile["per_subskill"]
    order = sorted(per, key=lambda k: (-per[k]["contradicts"], per[k]["unmeasurable"]))
    out = [f"# Per-subskill omics↔literature discordance + routing ({profile['n_targets']} targets)"]
    if not profile.get("framework_imports"):
        out.append("_(framework imports unavailable — Class A/E routing degraded; run with skills/ on PYTHONPATH)_")
    ct = profile.get("class_totals") or {}
    out.append(
        "\nCLASS TOTALS (the routed backlog): " + (", ".join(f"{k}={v}" for k, v in sorted(ct.items())) or "none")
    )
    out.append("  A=precedence(resolver/gate) B=measurement(data) E=framing(Engine2)")
    cst = profile.get("c_synthesis_targets") or []
    out.append(
        f"C-synthesis (TARGET-level: gate≠veto but LLM vetoed → Tier-3 reconciled-block): {sorted(set(cst)) or 'none'}\n"
    )
    out.append(f"{'subskill':26} {'N':>3} {'CONTRA':>6} {'unmeasurable':>12}")
    for k in order:
        p = per[k]
        out.append(f"{k:26} {p['targets']:3} {p['contradicts']:6} {p['unmeasurable']:12}")
    out.append("\n## Classified discordant cases (the routed backlog)\n")
    for k in order:
        for c in sorted(per[k]["cases"], key=lambda c: (c["class"], -c["n_citations"])):
            out.append(f"[{c['class']}] {k} · {c['target']} → fix in: {c['layer']} ({c['n_citations']} cites)")
            out.append(f"      {c['key_divergence'][:220]}")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    json_out = next((argv[i + 1] for i, a in enumerate(argv) if a == "--json" and i + 1 < len(argv)), None)
    if not args:
        print(__doc__)
        return 2
    profile = build_profile(args)
    print(render(profile))
    if json_out:
        json.dump(profile, open(json_out, "w"), indent=2)
        print(f"\n[wrote {json_out}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
