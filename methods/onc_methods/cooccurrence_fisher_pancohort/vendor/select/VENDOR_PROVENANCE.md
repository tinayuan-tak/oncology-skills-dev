# SELECT vendoring — SUPERSEDED (SELECT installed as R package instead)

**STATUS**: SELECT is now installed as a proper R package via
`devtools::install_github("CSOgroup/select", ref = "v1.6.3")` from
`setup.R`. **No vendoring needed**.

This directory is retained as a placeholder for the SELECT dependency
lineage — if the CSOgroup upstream ever becomes unavailable, this is
where a locally-vendored fallback would live.

## SELECT upstream (2026-07-10 resolution)

- **Repo**: https://github.com/CSOgroup/select
- **Owner**: Computational Systems Oncology (CSO) lab, UNIL Lausanne
  (Ciriello lab)
- **Current stable tag**: v1.6.3 (commit `a7463c6484e398a0eb3138c2da9dd99c51dceafd`)
- **License**: LGPL (>= 3) + file LICENSE (permissive; commercial use OK)
- **R package structure**: proper package with DESCRIPTION, NAMESPACE, R/,
  man/, vignettes/ — not a script bundle.
- **Exported functions**: `new.AL`, `select`, `select.on.AL`, `filter.al`,
  `get_vetos`
- **Bioconductor dependencies**: BiRewire (bipartite network null model)
- **CRAN dependencies**: foreach, doParallel, igraph, Matrix, matrixStats,
  parallel

## Prior URL-hunt (2026-07-10 morning)

Several plausible URLs failed before finding CSOgroup/select. Documented
here so future URL hunts can skip these dead-ends:

- github.com/CBIIT/SELECT — Repository not found
- github.com/RobertoVi/SELECT — Repository not found
- github.com/mattiaboschi/SELECT — Repository not found
- github.com/CiriellLab/SELECT — Repository not found (wrong org name)
- github.com/mmina/SELECT — Repository not found
- github.com/tavernaridavide/SELECT — Repository not found

The correct URL was suggested by the user (2026-07-10). The correct
org name is **CSOgroup** (Computational Systems Oncology), NOT
CiriellLab / CBIIT / Mina Lab.

## Citations (required for downstream use of SELECT results)

Per the CSOgroup/select README:

  Mina M, Iyer A, Tavernari D, Raynaud F, Ciriello G. Discovering
  functional evolutionary dependencies in human cancers. **Nature
  Genetics 52(11):1198-1207 (2020).**
  doi:10.1038/s41588-020-0703-5

  Mina M, Raynaud F, Tavernari D, Battistello E, Sungalee S, Saghafinia S,
  et al. Conditional selection of genomic alterations dictates cancer
  evolution and oncogenic dependencies. **Cancer Cell 32(2):155-168 (2017).**

## When to consider actual vendoring (deferred)

If CSOgroup/select becomes unavailable OR pins to a version that changes
API semantics unexpectedly, a follow-up commit could:
1. `git clone https://github.com/CSOgroup/select.git`
2. Copy R/*.R + DESCRIPTION + NAMESPACE + man/ into `vendor/select/`
3. Update `setup.R` to install from `vendor/select/` local dir
4. Note the vendored commit SHA here + copy date

Not needed today. Package installation is the cleaner path.
