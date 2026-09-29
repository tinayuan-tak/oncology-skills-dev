# `method_development/` — auditable home for method-development work

Method modules under `methods/<pkg>/` ship **deterministic, tested** production code. But the
*development* of a method — the exploratory QC, the calibration studies, the "why did we choose
this correction" evidence — has nowhere to live in that layer. This directory is that home.

## Convention

```
methods/<pkg>/method_development/<YYYY-MM>_<slug>/
    README.md            # dev log: the question, decisions, the robustness argument, links
    scripts/             # exploratory / calibration scripts (run ON DEMAND, not in CI)
    outputs/             # small committed artifacts (reports, summary JSON); heavy files gitignored
```

- **One dated slug per investigation.** `<YYYY-MM>_<slug>` keeps investigations self-describing and
  ordered. Cross-link the arc README to the relevant `DESIGN_*.md` and any external spec.
- **Nothing here is a unit test.** These scripts invoke R and read live S3; they are not
  credential-less-deterministic. The repo-root `conftest.py` carries
  `collect_ignore_glob = ["*/method_development/*"]` so pytest never collects anything here.
  Cheap invariants that *are* worth gating (e.g. "the calibration summary has a row per indication")
  belong in the package's real `tests/` dir, reading a committed `outputs/` artifact.
- **Commit the argument, gitignore the bulk.** Reports and small summary JSON are committed so the
  robustness case is reviewable in-repo; plots and regenerated parquet are gitignored (each arc's
  `.gitignore`).

## Active / past arcs

- [`2026-09_cross_cohort_reimplementation/`](2026-09_cross_cohort_reimplementation/) — full
  reimplementation of the TCGA DGE "sensitivity" family: within-TCGA paired contrast as the primary
  verdict, count-based RUVg correction (+ RIN evaluation) for the cross-cohort GTEx contrast, and
  cross-substrate validation (recount3 vs Xena/Toil). See its README for the design and the QC that
  motivated it.
