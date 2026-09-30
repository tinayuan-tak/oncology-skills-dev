#!/usr/bin/env python
"""Regenerate `matrix.json` — the LIVE-PANEL two-arm counterfactual behind the #2221 adjudication
of the "highly expressed" absolute anchor (5.0 vs 5.6724 log2(TPM+1)).

WHAT IS UNDER TEST. One absolute bar on log2(TPM+1) exists at two values, and both are cut on the
SAME quantity — the fraction of samples at or above it:

    cell-line arm  depmap_expression_distribution/cli.py:242  highly_expressed_threshold = 5.0
                   -> summary["fraction_highly_expressed"] = mean(scores >= 5.0)
    tumour arm     tcga_gtex_expression_distribution/stats.py:24  HIGH_LOG2TPM = 5.6724
                   -> expression_fractions()["high_fraction"] = mean(values >= 5.6724)

Both fractions are then compared to the SAME 0.5 bar to mint the same `broadly_high` word, and both
feed the SAME bimodal/long_tail gap heuristic as its upper band edge. So this is a genuine
same-quantity divergence (unlike #2220, which compared a bar on `high_fraction` with a bar on
`detectable_fraction` and was closed as a non-divergence).

WHAT THIS SCRIPT STORES, AND WHY IT IS NOT A FIXTURE OF DERIVED VALUES. The irreproducible input is
the per-sample log2(TPM+1) vector. Storing the two fractions would be storing the answer: a fixture
of derived values can never fail. So the fixture stores, per unit, the RAW MEASURED per-sample values
inside a window that STRICTLY CONTAINS BOTH CANDIDATE BARS, plus integer counts outside it. From that
the fraction at ANY bar inside the window is recoverable EXACTLY:

    frac_ge(b) = (n_ge_win + #{v in win_values : v >= b}) / n      for win_lo <= b < win_hi

Everything the two arms disagree about is therefore RE-DERIVED in the test from measured inputs, and
`test_high_anchor_flip_matrix.py` pins the window to strictly contain both bars so the fixture cannot
go vacuous by a bar drifting out of it.

The bars NOT under test (detectable 1.0, moderate 3.4594) are stored as integer counts, and the
bar-independent order statistics (median, p95) are stored as measured values — a median is not a
function of the bar, so storing it imputes nothing.

Usage (live S3; ~10 min for the full panel):
    cd ~/rnd-computational-biology-oncology-claude-oncology-skills
    env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \
        pixi run python methods/tests/calibration/high_anchor_flip_matrix/regenerate.py
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
MATRIX = HERE / "matrix.json"

# The panel: the pinned reference flip panel from the #809 phase-3b artifact
# (skills/tumor-presence/tests/fixtures/subset_high_live_flip_matrix.json) — 61 (target, indication)
# pairs over 58 targets and 13 indications, already curated to contain presence movers. Reused rather
# than re-invented so the two flip matrices are comparable and neither panel is chosen to suit its
# own answer.
PANEL_SOURCE = "skills/tumor-presence/tests/fixtures/subset_high_live_flip_matrix.json"

# The window. MUST strictly contain both candidate bars with margin; pinned by a test.
WIN_LO = 4.5
WIN_HI = 6.25

DETECTABLE = 1.0
MODERATE = 3.4594
BAR_LOG_ROUND = 5.0  # log-space round number, TPM ~31  (cell-line / DepMap / presence-tier STRONG)
BAR_LINEAR_ROUND = 5.6724  # linear-space round number, log2(51) ~ TPM 50 (tumour / GTEx liability)

DEPMAP_PIN = "26q3"


def _repo_root() -> Path:
    out = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(out.stdout.strip())


def _sha(root: Path) -> str:
    out = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return out.stdout.strip() or "?"


def _panel(root: Path) -> list[tuple[str, str]]:
    doc = json.loads((root / PANEL_SOURCE).read_text())
    pairs = [(p["target"], p["code"]) for p in doc["pairs"]]
    pairs += [(e["target"], e["code"]) for e in (doc.get("_meta", {}).get("excluded") or [])]
    if len(pairs) < 50:
        raise SystemExit(f"panel is {len(pairs)} pairs — refusing to measure a panel too thin to contain movers")
    return pairs


def _cov_linear(a) -> float:
    """CoV on LINEAR TPM — a byte-for-byte restatement of
    tcga_gtex_expression_distribution.stats.coefficient_of_variation / the DepMap twin's
    _coefficient_of_variation. Restated (not imported) only because both arms are captured by this one
    script and the two live copies are identical; a test pins this to the live functions.
    """
    import numpy as np

    lin = np.clip(np.power(2.0, np.asarray(a, dtype=float)) - 1.0, 0.0, None)
    mean = float(np.mean(lin))
    if mean <= 1e-9:
        return 0.0
    return float(np.std(lin) / mean)


def _windowed(values: list[float]) -> dict:
    """Compress a measured per-sample vector to (counts outside the window + raw values inside it).

    LOSSLESS for `fraction >= b` at any b in [WIN_LO, WIN_HI), and for the two untested bars.
    Raises on an empty vector: a coverage gap must be recorded as an exclusion, never as a zero.
    """
    import numpy as np

    a = np.asarray(values, dtype=float)
    a = a[~np.isnan(a)]
    if a.size == 0:
        raise ValueError("empty vector")
    inside = np.sort(a[(a >= WIN_LO) & (a < WIN_HI)])
    row = {
        "n": int(a.size),
        "n_lt_detectable": int(np.sum(a < DETECTABLE)),
        "n_ge_moderate": int(np.sum(a >= MODERATE)),
        "median": float(np.median(a)),
        "p95": float(np.percentile(a, 95)),
        # BAR-INDEPENDENT measured statistics. Stored as values, not counts, because neither is a
        # function of the bar under test — so storing them imputes nothing. `cov` is the CoV on LINEAR
        # TPM (the log is undone first, exactly as coefficient_of_variation does); it is the second,
        # independent supply for `heterogeneity`, so without it a pattern flip cannot be turned into a
        # heterogeneity flip and the derivation would silently overstate the movers.
        "cov": _cov_linear(a),
        "win": [WIN_LO, WIN_HI],
        "n_lt_win": int(np.sum(a < WIN_LO)),
        "n_ge_win": int(np.sum(a >= WIN_HI)),
        "win_values": [float(v) for v in inside],
    }
    if row["n_lt_win"] + len(row["win_values"]) + row["n_ge_win"] != row["n"]:
        raise AssertionError("window partition does not sum to n — the compression is not lossless")
    return row


def measure(root: Path) -> dict:
    from onc_methods.depmap_expression_distribution.cli import load_expression_files
    from onc_methods.tcga_gtex_expression_distribution.read import read_tumor_samples

    pairs = _panel(root)
    tumour, cellline, excluded = [], [], []

    for target, code in pairs:
        try:
            vals = read_tumor_samples(target, code)
        except Exception as exc:  # one unreadable pair must not lose the other 60
            excluded.append({"arm": "tumor", "target": target, "indication": code, "reason": repr(exc)})
            continue
        if not vals:
            excluded.append({"arm": "tumor", "target": target, "indication": code, "reason": "no_samples"})
            continue
        tumour.append({"target": target, "indication": code, **_windowed(list(vals))})
        print(f"  tumor  {target:10s} {code:9s} n={len(vals)}", flush=True)

    for target in sorted({t for t, _ in pairs}):
        try:
            tpm, _meta, errs = load_expression_files(DEPMAP_PIN, target)
        except Exception as exc:
            excluded.append({"arm": "cellline", "target": target, "reason": repr(exc)})
            continue
        if errs or not tpm:
            excluded.append(
                {"arm": "cellline", "target": target, "reason": f"load_errors={errs[:1]} n={len(tpm or {})}"}
            )
            continue
        cellline.append({"target": target, "indication": None, **_windowed(list(tpm.values()))})
        print(f"  cell   {target:10s} {'-':9s} n={len(tpm)}", flush=True)

    return {"tumor": tumour, "cellline": cellline, "excluded": excluded}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    out = Path(args.out) if args.out else MATRIX
    root = _repo_root()

    measured = measure(root)
    doc = {
        "_meta": {
            "what": (
                "Two-arm threshold counterfactual for #2221: the absolute 'highly expressed' bar on "
                "log2(TPM+1) at 5.0 (log-space round, TPM~31) vs 5.6724 (linear-space round, log2(51), "
                "TPM~50). Both bars cut the SAME quantity — the fraction of samples at or above them — "
                "on both arms, so the two values are interchangeable by construction and the only "
                "question is which one the measurements support."
            ),
            "ground_truth": (
                "MEASURED: n, the counts outside the window, median/p95, and every per-sample value "
                "INSIDE the window. DERIVED (never stored): the fraction at either bar, the "
                "distribution pattern, the expression class, the resolved properties. The test "
                "re-derives all of those from the stored raw values through the real functions."
            ),
            "window_contract": (
                f"win = [{WIN_LO}, {WIN_HI}) strictly contains both candidate bars. frac_ge(b) = "
                "(n_ge_win + #{v in win_values : v >= b}) / n is EXACT for any b in the window. A test "
                "pins the window against both bars so this fixture cannot go vacuous if a bar moves."
            ),
            "panel": PANEL_SOURCE,
            "bars": {"log_round": BAR_LOG_ROUND, "linear_round": BAR_LINEAR_ROUND},
            "untested_bars": {"detectable": DETECTABLE, "moderate": MODERATE},
            "depmap_pin": DEPMAP_PIN,
            "repo_sha": _sha(root),
            "captured_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "regenerated_by": "methods/tests/calibration/high_anchor_flip_matrix/regenerate.py",
            "excluded": measured["excluded"],
            "measured": {
                "tumor_units": len(measured["tumor"]),
                "cellline_units": len(measured["cellline"]),
                "excluded_units": len(measured["excluded"]),
            },
        },
        "tumor": measured["tumor"],
        "cellline": measured["cellline"],
    }
    out.write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n")
    print(
        f"wrote {out}  tumor={len(measured['tumor'])} cellline={len(measured['cellline'])} excluded={len(measured['excluded'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
