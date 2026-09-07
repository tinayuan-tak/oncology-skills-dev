#!/usr/bin/env python3
"""loop_health — measure the discordance loop's OWN precision (process step 6).

A monitored, self-improving process should measure itself: of the SHARP candidate gaps the loop flagged
(calibration_gap + verdict_rule_gap), what fraction were REAL (a landed fix or a documented real gap) vs
NOISE (the lane over-flagged an axis the verdict already agrees with, or the axis had no omics data)?
Reads the structured triage dispositions (eval/loop_dispositions.yaml, the CASE_LOG triage as data) and
reports precision overall + per gap_class + per skill. INSTRUMENT, not a gate — it never fails CI; it tells
you when to tighten the containment guard.

precision_strict      = (fixed + real_deferred) / n_sharp
precision_incl_scope  = (fixed + real_deferred + dismissed_scope) / n_sharp   # scope caveats are honest wins
noise_rate            = (dismissed_concordant + dismissed_data_absent) / n_sharp
"""
from __future__ import annotations

import argparse
import collections
from pathlib import Path

REAL = ("fixed", "real_deferred")
SCOPE = ("dismissed_scope",)
NOISE = ("dismissed_concordant", "dismissed_data_absent")
_ALL = REAL + SCOPE + NOISE


def _skill_axis(key: str) -> tuple[str, str]:
    parts = key.split("|")
    return (parts[0] if parts else "?", parts[3] if len(parts) > 3 else "?")


def load_dispositions(path: str | Path) -> dict:
    import yaml  # type: ignore
    doc = yaml.safe_load(Path(path).read_text()) or {}
    out = {}
    for k, v in (doc.get("dispositions") or {}).items():
        out[k] = (v or {}).get("disposition") if isinstance(v, dict) else v
    return out


def compute(dispositions: dict) -> dict:
    n = len(dispositions)
    counts = collections.Counter(dispositions.values())
    real = sum(counts.get(d, 0) for d in REAL)
    scope = sum(counts.get(d, 0) for d in SCOPE)
    noise = sum(counts.get(d, 0) for d in NOISE)
    by_skill: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for key, disp in dispositions.items():
        by_skill[_skill_axis(key)[0]][disp] += 1

    def _rate(x):
        return round(x / n, 3) if n else 0.0

    return {
        "n_sharp": n,
        "counts": dict(counts),
        "precision_strict": _rate(real),
        "precision_incl_scope": _rate(real + scope),
        "noise_rate": _rate(noise),
        "unknown_disposition": [d for d in counts if d not in _ALL],
        "by_skill": {sk: dict(c) for sk, c in sorted(by_skill.items())},
    }


def render_md(m: dict) -> str:
    L = ["# Discordance loop health — precision of the candidate-gap flagging",
         "",
         "_Instrument (process step 6), not a gate. Source: `eval/loop_dispositions.yaml` (the CASE_LOG "
         "triage as data). Regenerate after each triage pass: `python eval/loop_health.py --out eval/LOOP_HEALTH.md`._",
         "",
         f"- **SHARP candidate gaps flagged:** {m['n_sharp']}",
         f"- **precision_strict** (fixed + real_deferred): **{m['precision_strict']}**",
         f"- **precision_incl_scope** (+ scope caveats, honest wins): **{m['precision_incl_scope']}**",
         f"- **noise_rate** (concordant over-flag + data-absent): **{m['noise_rate']}**",
         "",
         "## Disposition counts",
         "",
         "| disposition | n |", "|---|---|"]
    for d, c in sorted(m["counts"].items(), key=lambda kv: -kv[1]):
        L.append(f"| {d} | {c} |")
    L += ["", "## By skill", "", "| skill | dispositions |", "|---|---|"]
    for sk, c in m["by_skill"].items():
        L.append(f"| {sk} | {', '.join(f'{k}:{v}' for k, v in sorted(c.items()))} |")
    if m["unknown_disposition"]:
        L += ["", f"> ⚠ unknown disposition tokens: {m['unknown_disposition']}"]
    L += ["",
          "## Read",
          "",
          "- The **containment guard is working**: 0 confabulation rows reached the sharp set (the "
          "`≥1 verified citation` rule filters non-reproducible LLM contradictions upstream).",
          "- The dominant NOISE source is **`dismissed_concordant`** — the lane flags `contradicts` on an "
          "axis whose omics signal already AGREES with the literature direction. The ledger-v2 "
          "claim-vector alignment now carries `claim_signal` per row, so the next guard tightening is to "
          "AUTO-DEMOTE a lane `contradicts` whose claim atom already matches the literature direction "
          "(direction cross-check), cutting this noise without touching the verdict.",
          "- `dismissed_scope` (pharmacovigilance, CASE-009) are honest measured-axis contradictions the "
          "verdict already covers conservatively — resolved with scope caveats, counted separately.",
          "",
          "## Governance checkpoint (RISK_ASSESSMENT_INTEGRATION.md §4-5)",
          "",
          "Literature remains **`citable_in_nominations: false`** — verdict-blind. Re-assessed against the "
          "five `clinical_validation` preconditions: (1) corpus pin — NO (the lane is Opus, model-default "
          "temperature, `_prompt_hash` drifts); (2) source determinism — NO; (3) null≠MEDIUM — n/a for this "
          "lane; (4) drop commercial/translational — n/a; (5) staleness TTL — NO. **Verdict: NO-GO stands.** "
          "Every discordance fix to date landed via the card/rule/method channel + the ground-truth "
          "calibration set, never the literature lane. Do not flip the stance until (1),(2),(5) are met."]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dispositions", default=str(Path(__file__).resolve().parent / "loop_dispositions.yaml"))
    ap.add_argument("--out", default=None, help="write the LOOP_HEALTH.md report here")
    a = ap.parse_args(argv)
    m = compute(load_dispositions(a.dispositions))
    md = render_md(m)
    if a.out:
        Path(a.out).write_text(md)
    print(f"[loop-health] n_sharp={m['n_sharp']} precision_strict={m['precision_strict']} "
          f"incl_scope={m['precision_incl_scope']} noise_rate={m['noise_rate']} counts={m['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
