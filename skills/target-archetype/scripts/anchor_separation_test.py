#!/usr/bin/env python3
"""SEPARATION TEST for a candidate atlas anchor — the criterion that decides activation (skills #1243).

Adding an anchor is not free: every corpus target's phenotype mixture is re-solved against the new corner, so
a corner that does not describe a DISTINCT phenotype does not merely add nothing, it RELABELS neighbours. Two
anchors have been refused on this basis (`synthetic_lethal` 2026-09-13, `fusion_driver` 2026-09-14) and both
refusals were argued from numbers produced by hand, in a scratch script, thrown away afterwards. That is why
this file exists: the 2026-09-02 `fusion_driver` deferral cited four named witnesses (MET flipped
fusion-dominant, ERBB2 35%, EGFR 20%, CLDN18 31%) and by n=504 EVERY ONE had stopped reproducing, while the
conclusion had actually grown stronger. Evidence that cannot be re-run is evidence that quietly rots, and the
next reader overturns a correct deferral on the strength of the refuted half.

THE CRITERION — three legs, all of which must PASS. Set by the `synthetic_lethal` precedent, which failed
legs 2 and 3 (3/6 exemplars recovered; CHEK1 and WEE1 flipped in):

  LEG 1  CENTROID ISOLATION  the candidate centroid sits further from EVERY incumbent anchor than the p90
                             nearest-neighbour distance of the corpus itself. "Further apart than typical
                             neighbours are" is the weakest defensible reading of "a distinct corner".
  LEG 2  EXEMPLAR RECOVERY   the anchor's OWN members resolve to it as their dominant phenotype. A curated
                             exemplar that lands elsewhere means the label does not describe its own members
                             — membership is not conferred by declaration, coordinates decide.
  LEG 3  NO BLEED            no NON-member target FLIPS its dominant phenotype to the new anchor. This is
                             the leg that fails, and it is a statement about the FEATURE SPACE: a corner
                             defined by a sparse signal is positioned by whatever DENSE features co-occur
                             with its exemplars, so it captures the co-occurring phenotype instead.

⚠️ THE p90 SCALE MOVES WITH n AND MUST BE RECOMPUTED, never carried over: 5.929 at n=297, 4.968 at n=504
(the corpus got DENSER, so the bar got STRICTER). The `synthetic_lethal` log quotes "~6.30" against a corpus
that no longer exists. This script always recomputes it from the baseline you pass.

TWO MODES, and the difference is not cosmetic:

  --candidate  (PRIMARY, exact) two real atlas builds, one with the anchor activated and one without. Every
               dominant label is read from each doc's own `soft_labels`, i.e. the production path
               (build_atlas computes them via Atlas._membership), so nothing here reimplements the producer.
               Requires a build, which needs sklearn + the corpus. Preceded by a LEG 0 method-validity gate.

  --members    (CONVENIENCE, approximate) one atlas plus a hypothetical member list. The centroid is averaged
               offline and the mixtures are re-solved here. Use it to SCREEN member sets; do not cite its
               numbers as the verdict. Two reasons, printed at runtime: (a) `embedding.corpus` is stored
               rounded to 6dp while build_atlas averages the UNROUNDED in-memory array, so an offline
               centroid differs from the real one by up to ~1e-6 on some coordinates — immaterial to a
               verdict, fatal to a byte comparison; (b) baseline dominants come from `soft_labels` while
               candidate dominants are re-solved here, so leg 3 mixes two derivations.
               MEASURED 2026-09-14, fusion_driver over corpus-20260914 (n=504): on the SAME member set the
               two modes agreed on all three legs and on every reported count (42 flips, 40 unsupported,
               TP=3/FP=41/FN=3, p90 4.968) in 8.5s vs a full rebuild. So the caveat is about byte-level
               reproducibility, not about the verdict — but that is a measurement on ONE anchor whose
               centroid sits far from the decision boundary, and a marginal candidate is exactly where
               ~1e-6 could tip a leg. Screen here; confirm with --candidate before recording.

  --evidence-column KEY   OPTIONAL DIAGNOSTIC, not part of the criterion. Scores the resulting dominant-label
               set against a feature column that is supposed to BE the phenotype (e.g.
               `genomic_alteration::claim::FUS::signal` at the `strong` tier). This is what turned "42 flips"
               into the real finding for fusion_driver: precision 6-8%, i.e. the corner named after fusion
               was answering a different question. A leg-3 failure tells you the corner moved neighbours; the
               diagnostic tells you whether it means what its NAME says.

Exit code: 0 = every leg PASSED (the anchor may be activated), 1 = at least one leg FAILED (deferral stands),
2 = the comparison itself was invalid (LEG 0), which is NOT a verdict about the anchor.

Usage:
  # primary: build both atlases first, one with the label in DEFERRED_ANCHORS and one without
  python3 anchor_separation_test.py --baseline /tmp/atlas_base.json --candidate /tmp/atlas_fus.json \
      --label fusion_driver --evidence-column genomic_alteration::claim::FUS::signal
  # convenience: screen a member set against the shipped atlas
  python3 anchor_separation_test.py --baseline ../atlas/atlas.json --label fusion_driver \
      --members RET/THCA NTRK1/THCA ALK/NSCLC
"""

import argparse
import json
import math
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS_DIR))
from _skills_common.archetype_core import Atlas  # noqa: E402

# Fields that MUST be identical between baseline and candidate for the comparison to mean anything. The
# embedding is fitted on Z, which is built from X/mu/sd — none of which sees `anchors` — so activating an
# anchor is LABEL-ONLY and the two worlds are directly comparable. That is a property of build_atlas, not a
# law, so it is CHECKED (leg 0) rather than assumed: an embedding that moved would make every leg meaningless
# while still printing plausible numbers.
_LEG0_FIELDS = ("feature_order", "mu", "sd", "X", "targets", "indications", "reference_mask_fraction")

_CANON = dict(sort_keys=True, separators=(",", ":"))


def _S(o) -> str:
    return json.dumps(o, **_CANON)


def _bare_solver(anchors: list, corpus_emb: list) -> Atlas:
    """An Atlas that can only do geometry. `Atlas.__init__` eagerly runs an O(n^2) NN sweep plus one hull
    solve per corpus row to build its novelty reference; `_membership` reads ONLY `self.anchors`, so bypassing
    __init__ uses the REAL solver without paying for machinery this script re-derives itself."""
    s = Atlas.__new__(Atlas)
    s.anchors = anchors
    s.corpus_emb = corpus_emb
    return s


def _dist(a: list, b: list) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def p90_nn_scale(corpus_emb: list, pctl: float = 0.9) -> float:
    """The yardstick, recomputed from the corpus every time. Uses archetype_core's own primitives so the bar
    is the SAME number the runtime novelty gate uses, not a lookalike."""
    s = _bare_solver([], corpus_emb)
    s._nn_ref = s._corpus_nn_distances()
    return s._novelty_threshold(pctl)


def leg0_comparable(base: dict, cand: dict, label: str) -> list:
    """Method validity. Returns a list of problems; empty means the two builds differ ONLY in the label."""
    problems = []
    for f in _LEG0_FIELDS:
        if _S(base.get(f)) != _S(cand.get(f)):
            problems.append(f"{f} DIFFERS between baseline and candidate")
    for f in ("corpus", "components"):
        if _S((base.get("embedding") or {}).get(f)) != _S((cand.get("embedding") or {}).get(f)):
            problems.append(f"embedding.{f} DIFFERS — the geometry moved, so no leg is interpretable")
    b_lab = {a["label"] for a in base.get("anchors") or []}
    c_lab = {a["label"] for a in cand.get("anchors") or []}
    if label in b_lab:
        problems.append(f"'{label}' is ALREADY an anchor in the baseline — pass a baseline with it deferred")
    if label not in c_lab:
        problems.append(
            f"'{label}' is NOT an anchor in the candidate. If build_atlas skipped it, check DEFERRED_ANCHORS "
            f"and whether its exemplars resolve (see _assert_anchor_exemplars_resolve)"
        )
    if c_lab - b_lab != {label} and label in c_lab:
        problems.append(f"candidate adds more than one anchor: {sorted(c_lab - b_lab)}")
    if b_lab - c_lab:
        problems.append(f"candidate LOST anchors: {sorted(b_lab - c_lab)}")
    # incumbent centroids must be byte-identical, which is the sharpest form of "label-only"
    b_by = {a["label"]: a for a in base.get("anchors") or []}
    moved = [
        lb
        for lb, a in ((x["label"], x) for x in cand.get("anchors") or [])
        if lb in b_by and _S(a["coord"]) != _S(b_by[lb]["coord"])
    ]
    if moved:
        problems.append(f"incumbent anchor centroids MOVED: {moved}")
    return problems


def calibrate(anchors: list, scale: float) -> tuple:
    """Do the INCUMBENT anchors clear the bar leg 1 applies? Not part of the criterion — asked because a bar
    the shipped anchors fail is a statement about the bar, not about the candidate."""
    pairs = sorted(
        (_dist(p["coord"], q["coord"]), p["label"], q["label"]) for i, p in enumerate(anchors) for q in anchors[i + 1 :]
    )
    return pairs, [x for x in pairs if x[0] < scale]


def run_legs(
    base: dict,
    label: str,
    coord: list,
    members: list,
    dom_base: list,
    dom_cand: list,
    scale: float,
    incumbents: list,
    strong_rows: set | None,
) -> dict:
    emb = base["embedding"]["corpus"]
    T, I = base["targets"], base["indications"]
    idx = {(t, i): r for r, (t, i) in enumerate(zip(T, I))}
    solver = _bare_solver(incumbents + [{"label": label, "coord": coord}], emb)
    mem = {tuple(m) for m in members}
    out = {}

    # ---- LEG 1 ----
    ds = sorted((_dist(coord, a["coord"]), a["label"]) for a in incumbents)
    within = [(d, lb) for d, lb in ds if d < scale]
    out["leg1"] = not within
    print(f"\nLEG 1  CENTROID ISOLATION   bar = p90 NN scale {scale:.3f} (recomputed at n={len(emb)})")
    for d, lb in ds:
        print(f"       {d:>8.3f}  {'WITHIN — not distinct' if d < scale else 'outside':<22} {label} <-> {lb}")
    print(f"  => {'PASS' if out['leg1'] else 'FAIL'} — {len(within)} of {len(ds)} incumbents sit within the scale")

    # ---- LEG 2 ----
    rec = [m for m in sorted(mem) if m in idx and dom_cand[idx[m]] == label]
    absent = [m for m in sorted(mem) if m not in idx]
    resolvable = [m for m in sorted(mem) if m in idx]
    out["leg2"] = bool(resolvable) and len(rec) == len(resolvable)
    print("\nLEG 2  EXEMPLAR RECOVERY    do the anchor's own members resolve to it?")
    for m in resolvable:
        r = idx[m]
        w, resid, _ = solver._membership(emb[r])
        ok = dom_cand[r] == label
        print(
            f"       {m[0]:>9}/{m[1]:<10} {label}={w.get(label, 0.0):>4.0%}  dominant={dom_cand[r]:<21}"
            f"hull_resid={resid:>6.3f}{'' if ok else '   <-- MISLANDED'}"
        )
    if absent:
        print(
            f"       NOT IN CORPUS (excluded from the leg, but the anchor is then built from a SUBSET — see "
            f"build_atlas._assert_anchor_exemplars_resolve): {', '.join(f'{t}/{i}' for t, i in absent)}"
        )
    print(f"  => {'PASS' if out['leg2'] else 'FAIL'} — {len(rec)}/{len(resolvable)} resolvable members dominant")

    # ---- LEG 3 ----
    flips = [
        r for r in range(len(emb)) if dom_base[r] != dom_cand[r] and dom_cand[r] == label and (T[r], I[r]) not in mem
    ]
    collateral = [r for r in range(len(emb)) if dom_base[r] != dom_cand[r] and dom_cand[r] != label]
    out["leg3"] = not flips
    print(f"\nLEG 3  NO BLEED             non-member targets whose DOMINANT phenotype flips to '{label}'")
    ranked = sorted(((solver._membership(emb[r])[0].get(label, 0.0), r) for r in flips), reverse=True)
    for w, r in ranked[:25]:
        ev = "" if strong_rows is None else ("  evidence=yes" if r in strong_rows else "  evidence=NO")
        print(f"       {T[r]:>9}/{I[r]:<10} was {dom_base[r]:<21} {label}={w:>4.0%}{ev}")
    if len(ranked) > 25:
        print(f"       ... and {len(ranked) - 25} more")
    if strong_rows is not None and flips:
        noev = [r for r in flips if r not in strong_rows]
        print(f"       {len(noev)} of {len(flips)} flips carry NO supporting evidence in the named column")
    print(f"       collateral flips NOT to '{label}' (mixtures re-solved against a new corner): {len(collateral)}")
    print(
        f"  => {'PASS' if out['leg3'] else 'FAIL'} — {len(flips)} non-member flips (synthetic_lethal was refused at 2)"
    )
    out["flips"] = len(flips)
    return out


def diagnostic_vs_column(base: dict, label: str, dom_cand: list, strong_rows: set, key: str, tier: float) -> None:
    claimed = {r for r in range(len(dom_cand)) if dom_cand[r] == label}
    tp, fp, fn = len(claimed & strong_rows), len(claimed - strong_rows), len(strong_rows - claimed)
    prec = tp / (tp + fp) if (tp + fp) else float("nan")
    print(f"\nDIAGNOSTIC (not part of the criterion) — '{label}' vs {key} >= {tier}")
    print(
        f"       rows reading the column at/above tier: {len(strong_rows)} of {len(dom_cand)} "
        f"({len(strong_rows) / max(1, len(dom_cand)):.1%})"
    )
    print(
        f"       dominant-'{label}' rows={len(claimed)}   TP={tp} FP={fp} FN={fn}   "
        f"precision={prec:.0%}  recall={tp}/{len(strong_rows)}"
    )
    print(
        "       Low precision here with leg 1 PASSING is the structural signature: the corner is real "
        "geometry that does NOT mean what its name says."
    )
    if fn:
        print(
            f"       {fn} row(s) carry the evidence and REFUSE the corner — a row cannot be placed by fiat, "
            f"its coordinates come from its dense features."
        )


def main():
    ap = argparse.ArgumentParser(description="three-leg separation test for a candidate atlas anchor")
    ap.add_argument("--baseline", required=True, help="atlas WITHOUT the candidate anchor")
    ap.add_argument("--label", required=True, help="candidate anchor label")
    ap.add_argument("--candidate", default=None, help="atlas WITH the candidate anchor activated (PRIMARY mode)")
    ap.add_argument(
        "--members",
        nargs="*",
        default=None,
        metavar="TARGET/INDICATION",
        help="hypothetical member set (CONVENIENCE mode; approximate, see module docstring)",
    )
    ap.add_argument("--pctl", type=float, default=0.9, help="NN percentile for the leg-1 bar (default 0.9)")
    ap.add_argument(
        "--evidence-column", default=None, help="optional diagnostic: feature key that should BE the phenotype"
    )
    ap.add_argument("--evidence-min", type=float, default=3.0, help="tier counted as evidence (default 3.0 = `strong`)")
    a = ap.parse_args()

    if (a.candidate is None) == (a.members is None):
        raise SystemExit("pass exactly one of --candidate (primary, exact) or --members (convenience, approximate)")

    base = json.loads(Path(a.baseline).read_text())
    emb = base["embedding"]["corpus"]
    incumbents = [x for x in (base.get("anchors") or [])]
    # PROVENANCE FIRST, and LOUD when it is missing. The whole point of this script is to produce evidence
    # that can be re-run, and evidence is only re-runnable if it names what it was measured on — the deferral
    # this replaced rotted precisely because its numbers were unattributed. So an unstamped baseline gets a
    # WARN, not a `?` placeholder that would be copied into a declaration as if it were a corpus id.
    meta = base.get("meta") or {}
    corpus = meta.get("corpus")
    print(
        f"baseline {a.baseline}\n  n={len(emb)} rows, {len(incumbents)} incumbent anchors, "
        f"{len(base['feature_order'])} features"
    )
    print(
        f"  corpus={corpus or 'UNSTAMPED'}  build_date={meta.get('build_date', '?')}  "
        f"git_sha={meta.get('build_git_sha', '?')}  schema={meta.get('feature_schema_version', '?')}"
    )
    if not corpus:
        print(
            "  ⚠️ WARN: baseline carries no meta.corpus — do NOT record these numbers as evidence; they "
            "cannot be reproduced without knowing which corpus they came from.",
            file=sys.stderr,
        )

    strong_rows = None
    if a.evidence_column:
        if a.evidence_column not in base["feature_order"]:
            raise SystemExit(
                f"--evidence-column {a.evidence_column!r} is not in feature_order. Note the "
                f"claim vector is NESTED per axis; the FLAT key is what the atlas stores."
            )
        j = base["feature_order"].index(a.evidence_column)
        strong_rows = {r for r, row in enumerate(base["X"]) if row[j] is not None and row[j] >= a.evidence_min}

    if a.candidate:
        cand = json.loads(Path(a.candidate).read_text())
        print(f"candidate {a.candidate}   (PRIMARY mode: both dominant-label sets read from `soft_labels`)")
        problems = leg0_comparable(base, cand, a.label)
        print("\nLEG 0  METHOD VALIDITY      activation must be LABEL-ONLY, or no leg below is interpretable")
        if problems:
            for p in problems:
                print(f"       [INVALID] {p}")
            print(
                "  => INVALID — not a verdict about the anchor. Rebuild both atlases from the SAME corpus, "
                "changing ONLY whether the label is deferred."
            )
            raise SystemExit(2)
        print(
            f"       every one of {len(_LEG0_FIELDS) + 2} substrate fields identical; all {len(incumbents)} "
            f"incumbent centroids byte-identical; candidate adds exactly ['{a.label}']"
        )
        print("  => VALID — the embedding does not depend on anchors, so the two worlds are comparable")
        anc = [x for x in cand["anchors"] if x["label"] == a.label][0]
        coord, members = anc["coord"], [tuple(m) for m in anc["members"]]
        dom_base, dom_cand = base["soft_labels"], cand["soft_labels"]
        print(f"\n'{a.label}' as BUILT: {anc['n_members']} members -> {[f'{t}/{i}' for t, i in members]}")
    else:
        members = [tuple(m.split("/", 1)) for m in a.members]
        idx = {(t, i): r for r, (t, i) in enumerate(zip(base["targets"], base["indications"]))}
        rows = [idx[m] for m in members if m in idx]
        if not rows:
            raise SystemExit(f"none of {a.members} are in the corpus — nothing to average")
        print("CONVENIENCE mode — APPROXIMATE, do not cite as a verdict:")
        print("  * the centroid is averaged from `embedding.corpus`, which is stored ROUNDED TO 6dp, while")
        print("    build_atlas averages the UNROUNDED in-memory array (differs by ~1e-6 on some coordinates)")
        print("  * baseline dominants come from `soft_labels` but candidate dominants are RE-SOLVED here, so")
        print("    leg 3 mixes two derivations. Confirm any FAIL with --candidate before recording it.")
        coord = [round(sum(emb[r][t] for r in rows) / len(rows), 6) for t in range(len(emb[0]))]
        solver = _bare_solver(incumbents + [{"label": a.label, "coord": coord}], emb)
        dom_base = base["soft_labels"]
        print(f"\nre-solving {len(emb)} corpus mixtures against {len(incumbents) + 1} anchors (pure python, slow)...")
        dom_cand = []
        for r in range(len(emb)):
            w, _, _ = solver._membership(emb[r])
            dom_cand.append(max(w, key=w.get) if w else "?")
        print(f"'{a.label}' hypothetical: {len(rows)}/{len(members)} members resolve")

    scale = p90_nn_scale(emb, a.pctl)
    pairs, tight = calibrate(incumbents, scale)
    print("\nCALIBRATION (not part of the criterion) — do the INCUMBENTS clear the bar leg 1 applies?")
    print(
        f"       {len(pairs)} incumbent pairs; closest {pairs[0][0]:.3f} ({pairs[0][1]} <-> {pairs[0][2]}), "
        f"widest {pairs[-1][0]:.3f}"
    )
    print(
        f"       incumbent pairs BELOW the p{int(a.pctl * 100)} NN scale {scale:.3f}: {len(tight)} of {len(pairs)}"
        f"{'  <-- the BAR is suspect, not the candidate' if tight else ''}"
    )

    res = run_legs(base, a.label, coord, members, dom_base, dom_cand, scale, incumbents, strong_rows)
    if a.evidence_column:
        diagnostic_vs_column(base, a.label, dom_cand, strong_rows, a.evidence_column, a.evidence_min)

    ok = res["leg1"] and res["leg2"] and res["leg3"]
    print(f"\n{'=' * 100}\nSEPARATION TEST VERDICT — '{a.label}' @ n={len(emb)}")
    for k, nm in (("leg1", "centroid isolation"), ("leg2", "exemplar recovery"), ("leg3", "no bleed")):
        print(f"  {'PASS' if res[k] else 'FAIL'}  {nm}")
    print(f"  OVERALL: {'PASS — the anchor may be ACTIVATED' if ok else 'FAIL — the DEFERRAL STANDS'}")
    if not ok:
        print("  Record this in build_atlas.DEFERRED_ANCHORS (or UNDECLARED_ANCHORS if the label has no")
        print("  exemplar set) — a prose reason cannot be re-run, so it decays without anything noticing:")
        print(f'      "measured_on": "{corpus or "UNSTAMPED"} (n={len(emb)})",')
        print('      "measured_by": "scripts/anchor_separation_test.py",')
        print(f'      "p90_nn_scale": {scale:.3f},   # RECOMPUTED at this n; it MOVES, never carry it over')
    print("=" * 100)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
