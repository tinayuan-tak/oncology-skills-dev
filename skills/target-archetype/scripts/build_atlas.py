#!/usr/bin/env python3
"""Build the FROZEN reference atlas for the target-signature LANDSCAPE companion.

OFFLINE, one-time (re-run only to re-freeze after a validated substrate change). Iterates a corpus of
composed target-profile --full-package runs, vectorises each via archetype_core.claim_features (the SAME
vectoriser the runtime query uses — single source of truth), and freezes:
  feature_order · mu · sd (nan-aware) · X · targets · indications · labels · rule_fingerprints · axis_ref
  · embedding{components (m x d PCA loadings), corpus (n x m coords)} · anchors[{label,target,indication,
  coord}] · meta.

The embedding is a LINEAR PCA projection fit on the z-scored, mean-imputed (missing->0) corpus — the
EXACT transform archetype_core applies to a single query at runtime, so offline == runtime, pure-numpy,
deterministic. Phenotype ANCHORS are curated canonical exemplars (one per drug-target phenotype); a query
is expressed as a convex mixture of the anchors' frozen embedding coords.

Usage:
  python3 build_atlas.py \
      --runs  ~/dev/tumor-presence-audit-2026-08-26/tp_runs_xl \
              ~/dev/tumor-presence-audit-2026-08-26/tp_runs_expansion \
              ~/dev/tumor-presence-audit-2026-08-26/tp_runs_prospective \
      --panel ~/dev/tumor-presence-audit-2026-08-26/tp_panel_xl.tsv \
      --out   ../atlas/atlas.json --emb-dim 16

Governance: labels are PROVISIONAL (panel-derived, partly circular) and back a DESCRIPTIVE, verdict-inert
companion only — NOT a classifier freeze. Anchor labels reuse the archetype vocabulary so the D1 scorecard
consumes the mixture unchanged. Ship n as-is (no silent drop of hard pairs)."""

import argparse
import functools
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

SKILLS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling corpus_io
from _skills_common.archetype_core import claim_features  # noqa: E402,F401  (kept for back-compat imports)
from _skills_common.feature_vectoriser import build_feature_vector, numeric_values_from_package  # noqa: E402
from corpus_io import claim_vectors_for_run  # noqa: E402

# curated canonical phenotype anchors (label reuses the archetype vocabulary; exemplar = (target, indication)).
# One well-covered exemplar per drug-target phenotype; the query is a convex mixture of these.
# Curated phenotype anchors — each is the CENTROID of a small exemplar SET (not a single point), so a
# corner no longer pivots on one target's noisy/partial signature. First member is the canonical
# representative (shown in the payload); the anchor coord is the mean of all present members' embeddings.
ANCHOR_SETS = {
    "snv_driver": [("KRAS", "LUAD"), ("BRAF", "COADREAD"), ("NRAS", "COADREAD")],
    "tsg_loss": [("VHL", "KIRC"), ("STK11", "LUAD"), ("PTEN", "COADREAD"), ("RB1", "LUSC")],
    "amp_driver": [("ERBB2", "BRCA"), ("CCND1", "BRCA"), ("MYC", "COADREAD"), ("MET", "LUAD")],
    "expression_surface": [("EPCAM", "COADREAD"), ("CEACAM6", "COADREAD"), ("MSLN", "PAAD"), ("FOLR1", "OV")],
    "dependency_essential": [("AURKA", "BRCA"), ("PLK1", "LUAD"), ("BIRC5", "LUAD"), ("WEE1", "OV")],
    # immune-synapse set — grown 2026-09-13 with 5 canonical checkpoints (CTLA4/PD-L1/LAG3/TIGIT/TIM3) so
    # the corner no longer rests on 3 points. immune_context signal is indication-level (non-discriminative),
    # so this anchor separates on the surface-receptor-with-immune-role profile, not the immune signal.
    "immune_checkpoint": [
        ("PDCD1", "LUAD"),
        ("CD28", "BRCA"),
        ("ICOSLG", "BRCA"),
        ("CTLA4", "LUAD"),
        ("CD274", "LUAD"),
        ("LAG3", "BRCA"),
        ("TIGIT", "COADREAD"),
        ("HAVCR2", "STAD"),
    ],
    # synthetic-lethal / partner-conditional phenotype — ⚠️ DEFERRED 2026-09-13 (evidenced, like fusion_driver
    # below), declared in UNDECLARED_ANCHORS: there is deliberately NO entry here, and re-adding one fails the
    # build. A separation test was run: 10 canonical SL/checkpoint exemplars (WRN/PARP1/ATR/POLQ/MAT2A/RAD51)
    # were regenerated + a synthetic_lethal anchor built. It DID NOT separate: the SL centroid sat WITHIN the
    # p90 NN scale (~6.30) of BOTH dependency_essential (5.94) and tsg_loss (5.37); only 3/6 exemplars
    # recovered (WRN→tsg_loss 37%, PARP1→amp_driver 36% mislanded), and DDR dependencies bled in (CHEK1 FLIPPED
    # to synthetic_lethal 54%, WEE1 38%). ROOT CAUSE: the SL claim signal is ubiquitous (129/213) and
    # dependency::COND is 2-3/213, so the feature space does not encode SL as a distinct phenotype — an SL
    # target's placement is driven by its dependency/genome-instability reads, not the SL window. Activating
    # cleanly needs the partner-conditional signal made SEPARABLE first (a curated SL-window feature, not more
    # exemplars) — the same lesson as fusion_driver. The 10 exemplar runs remain in the corpus as unlabeled
    # cloud points. See project_atlas_rebuild_strategy_2026_09_06 + the separation-test log.
    "control_housekeeping": [("GAPDH", "LUAD"), ("ACTB", "COADREAD"), ("RPL13A", "OV")],
    # fusion/rearrangement-driver phenotype. Members were LIVE-verified to read `fusion:
    # recurrent_fusion_driver` (strong FUS) in their canonical fusion indication (RET/NSCLC + NTRK1/LUAD
    # were REJECTED — sporadic/absent there). ⚠️ NOT ACTIVATED (kept aspirational; exemplar runs live under
    # a separate tp_runs_fusion corpus, NOT the shipped --runs, so build SKIPS it). WHY DEFERRED: a
    # 2026-09-02 re-freeze that DID activate it regressed the panel — the exemplars correctly land on the
    # anchor (ALK 97%, NTRK1 88%, RET 83%, ROS1 67%), BUT because FUS is ONE sparse feature of 108 and every
    # recurrent-fusion driver is an RTK, the anchor centroid encodes RTK-ness not rearrangement, bleeding
    # spurious fusion mass into non-fusion RTK/surface targets (MET flipped fusion-DOMINANT; ERBB2 35%; EGFR
    # 20%; CLDN18 — not even a kinase — 31%). Activating this cleanly needs the fusion signal made SEPARABLE
    # (e.g. FUS-feature up-weighting in the embedding) first, not just adding exemplars. See
    # project_target_archetype_augment memory.
    "fusion_driver": [("ALK", "LUAD"), ("ROS1", "LUAD"), ("RET", "THCA"), ("FGFR2", "CHOL"), ("NTRK1", "THCA")],
    # NULL/floor corner (added at the 2026-09-11 re-freeze). The panel has carried 8 curated
    # `control_absent` targets since the first build, but with no anchor to absorb them every
    # not-really-a-target profile had to distribute its mass over the SEVEN POSITIVE corners —
    # which is why `immune_checkpoint` accumulated 29 soft-labels while holding ZERO curated
    # members. A floor corner is what makes "this target is absent/undruggable-looking" sayable.
    "control_absent": [
        ("RHO", "LUAD"),
        ("CNGB3", "OV"),
        ("GFAP", "COADREAD"),
        ("MYF5", "COADREAD"),
        ("MYH2", "PAAD"),
        ("MYH6", "BRCA"),
        ("NPHS2", "STAD"),
        ("OTX2", "LUSC"),
    ],
}

# Anchors that must NOT activate even when their exemplars are present in the corpus — DEFERRED by an
# EVIDENCED separation failure (they bleed into a neighbouring corner), distinct from the "absent exemplars"
# skip. fusion_driver: the 2026-09-02 activation bled RTK-ness into non-fusion RTKs; its members (RET/THCA,
# NTRK1/THCA) re-entered the corpus with the 2026-09-13 diverse expansion, so it now needs this explicit
# guard rather than relying on absence. synthetic_lethal is deferred by the OTHER mechanism (no ANCHOR_SETS
# entry at all) and is declared in UNDECLARED_ANCHORS below. Re-activate only after a separation test PASSES.
DEFERRED_ANCHORS = frozenset({"fusion_driver"})

# Anchors deferred by the WEAKER mechanism: they carry NO `ANCHOR_SETS` entry at all, so the build skips
# them by never iterating them. That is deferral-by-ABSENCE, and absence is invisible — nothing in the code
# or the artifact says "this label was considered and rejected on evidence", so pasting an exemplar list back
# into ANCHOR_SETS silently ACTIVATES a known-bleeding corner (DEFERRED_ANCHORS above would not catch it: it
# guards labels that HAVE an entry). Declaring them here turns that absence into a checkable statement, with
# the evidence that must be overturned to activate. Keys must NOT appear in ANCHOR_SETS —
# _assert_deferral_declarations_consistent() fails the BUILD if one does, which is the whole point: the
# accident this guards against is an edit to ANCHOR_SETS, so it must be caught at the producer boundary and
# not only by the test suite (a caller that runs build_atlas.py directly skips the tests entirely).
# `exemplars` is the curated set that WOULD be the ANCHOR_SETS value — kept so the curation survives the
# deferral (it was otherwise only in prose), and so a test can assert the exemplars are still IN the corpus,
# i.e. that the deferral is still load-bearing rather than a comment about a hypothetical. It is read by
# nothing in the build; the ONLY way to activate is to move it into ANCHOR_SETS and delete the key here.
UNDECLARED_ANCHORS = {
    "synthetic_lethal": {
        "exemplars": [
            ("WRN", "COADREAD"),
            ("PARP1", "BRCA"),
            ("ATR", "OV"),
            ("POLQ", "BRCA"),
            ("MAT2A", "PAAD"),
            ("RAD51", "OV"),
        ],
        "reason": (
            "2026-09-13 separation test FAILED: the SL centroid sat WITHIN the p90 NN scale (~6.30) of BOTH "
            "dependency_essential (5.94) and tsg_loss (5.37); only 3/6 exemplars recovered (WRN→tsg_loss 37%, "
            "PARP1→amp_driver 36%) and DDR dependencies bled in (CHEK1 FLIPPED to synthetic_lethal 54%, WEE1 "
            "38%). ROOT CAUSE is structural, not exemplar count: the SL claim signal is ubiquitous (129/213 "
            "corpus rows) while dependency::COND is 2-3/213, so the frozen feature space does not encode "
            "partner-conditionality as a distinct phenotype — an SL target's placement is driven by its "
            "dependency/genome-instability reads, not the SL window. The exemplars ARE in the shipped corpus, "
            "so restoring an ANCHOR_SETS entry activates this IMMEDIATELY. Activate only after a curated "
            "SL-window feature makes the signal SEPARABLE and a re-run separation test PASSES."
        ),
    },
}


def _assert_deferral_declarations_consistent() -> None:
    """Producer-boundary check on the two deferral mechanisms. Raises rather than warning: a violated
    invariant here means the build is about to ship an anchor that a deferral was supposed to withhold,
    and a WARN on stderr is exactly what a CI log swallows."""
    both = sorted(set(UNDECLARED_ANCHORS) & set(ANCHOR_SETS))
    if both:
        raise SystemExit(
            f"BUILD REFUSED: {both} are declared in UNDECLARED_ANCHORS (deferred with NO exemplar set) but "
            f"now carry an ANCHOR_SETS entry, which would ACTIVATE them. Reasons that must be overturned "
            f"first: " + " | ".join(f"{k}: {UNDECLARED_ANCHORS[k]['reason']}" for k in both) + " — if the separation "
            "test now PASSES, delete the UNDECLARED_ANCHORS key in the SAME commit as the exemplar set."
        )
    dangling = sorted(set(DEFERRED_ANCHORS) - set(ANCHOR_SETS))
    if dangling:
        raise SystemExit(
            f"BUILD REFUSED: DEFERRED_ANCHORS names {dangling}, which have no ANCHOR_SETS entry. The skip "
            f"loop iterates ANCHOR_SETS, so those guards are DECORATIVE — the label is really deferred by "
            f"absence. Move them to UNDECLARED_ANCHORS (with their evidence) or restore the exemplar set."
        )


# Claim namespaces/keys EXCLUDED from the frozen feature space BY DECISION (atlas data-package lockdown):
# maturity/study-depth-confounded axes (literature_context, translational_readiness, safety
# PHARMACOVIGILANCE) and a single-gene constant (genomic SPL = METex14). These keys are still EMITTED by
# every run — the vector is a shared artifact, so dropping them at the source would blind other consumers
# and the drift guard alike (see atlas_health._DEFAULT_EXCLUDED_NAMESPACES, which is the SAME list). The
# filter belongs HERE, at the freeze: admitting them would let study-depth ride into the phenotype geometry
# as if it were biology. Stamped into meta.atlas_excluded_namespaces so the guard reads the built model's
# own list rather than its default.
EXCLUDED_NAMESPACES = (
    "literature_context::",
    "translational_readiness::",
    "safety::claim::PHARMACOVIGILANCE::",
    "genomic_alteration::claim::SPL::",
)


FEATURE_CORR_MIN_PAIRWISE_N = 10


# ★ The PCA solver is PINNED, not left to sklearn's `auto`, because `auto` is a function of CORPUS SIZE.
# sklearn's heuristic picks the exact `full` solver while `max(n_samples, n_features) <= 500` and switches to
# the STOCHASTIC `randomized` approximation above it. The corpus is n=297 today, so `auto` resolves to `full`
# and this pin is a byte-level no-op — but the authorised panel expansion adds 207 targets (ESCA 40, CML 38,
# SCLC 37, STAD 24, HNSC 23, AML 23, PAAD 22), landing n at 504 and crossing that boundary. Measured on the
# shipped X: refitting with `randomized` moves the loadings by 1.23e-02, versus a 2.24e-05 floor that is just
# the 6-dp rounding of the frozen floats — a 550x, plainly visible change. A re-freeze that crossed 500 would
# therefore show a moved embedding and every moved coord, and a reviewer would attribute that to the new
# targets rather than to a solver swap nobody chose. Pinning also decouples the freeze from sklearn's own
# heuristic, which last changed in 1.5 (the `covariance_eigh` branch). See tests/test_atlas_embedding.py.
PCA_SVD_SOLVER = "full"


def native_feature_corr_provenance(build_date: str, git_sha: str) -> dict:
    """The provenance stamp for a feature_corr block emitted BY THIS BUILD, in the same pass that froze X.

    `amend_atlas_feature_corr.py` is the other producer and stamps `derived_post_freeze: True`; the two
    states are mutually exclusive and both legitimate, so the block has to say which one made it. Kept as a
    named function, not an inline literal inside `build()`, so the native contract is assertable without a
    full build (which needs scikit-learn plus the ~200-run corpus) — an inline dict would leave this branch
    exercised only by a re-freeze, i.e. never in CI.
    """
    return {
        "derived_post_freeze": False,
        "derived_from": "the same X + feature_order this build froze (single pass)",
        "method": "pairwise_complete_pearson over ::num:: non-mask columns",
        "basis_build_git_sha": git_sha,
        "reason": (
            "emitted natively by build_atlas.feature_correlation during the freeze, so the block and the "
            "basis it describes are the same build. The post-freeze path (amend_atlas_feature_corr.py) "
            "exists only to backfill artifacts frozen before build_atlas computed feature_corr at all."
        ),
        "added_date": build_date,
    }


def feature_correlation(feature_order, X):
    """PAIRWISE-COMPLETE correlation over the metered numeric (non-`::mask`) columns.

    Returns `(order, corr, n)`: the column keys the matrix is aligned to, the matrix itself, and the
    number of rows actually behind each cell. Three keys rather than one, for two reasons that have each
    already cost this repo a bug:

    - **Alignment is DECLARED, not assumed.** `reference_mask_fraction` is aligned to `feature_order` and
      a reader must know that out of band. This block is aligned to a SUBSET, so shipping the matrix
      without its own order invites a consumer to index it with `feature_order` and silently read the
      wrong column pair.
    - **A correlation is a derived number, so it needs its basis** — the same reason `bits` is schema-
      required to carry `cohort_n >= 1`. Two columns measured together in 11 targets and two measured
      together in 250 both yield a float in [-1, 1], and only `n` distinguishes a structure from a
      coincidence. Cells below `FEATURE_CORR_MIN_PAIRWISE_N` are `None`, not 0.0: "we could not look"
      and "we looked and found independence" are different claims.

    Why PAIRWISE-COMPLETE and not the mean-imputed `Z` that feeds the PCA: that transform sets every
    missing cell to exactly the column mean, which drags the covariance toward zero in proportion to
    missingness — so the columns most in need of a redundancy discount get the smallest one. Measured on
    the 2026-09-13 freeze, imputation understates |r| on real pairs by up to 0.080 (median 0.012 over the
    190 usable pairs); `cn_stratified_dependency::num::delta_chronos_amplified_vs_neutral` vs
    `dependency_predictability::num::pearson_r_squared_rf` reads 0.549 pairwise-complete against 0.469
    imputed, off 132 co-measured targets. The PCA wants the imputed basis (it needs a dense matrix and
    z=0 is the least-committal fill); a redundancy measure wants the observed one.

    Scope is the `::num::` non-mask columns because they are the population that gets RANKED. The
    `::mask` columns are excluded from rank consumers already (every one carries
    `reference_mask_fraction` 1.000 by construction, so the usable-reference gate is vacuous against
    them), and a full `feature_order` block would ship ~31k cells for 176 columns with no consumer.

    ★ Verdict-INERT and DESCRIPTIVE. This is an instrument, not a ranker — see the salience tests for the
    measured reason no cross-frame aggregator is built on it yet.
    """
    order = [k for k in feature_order if "::num::" in k and not k.endswith("::mask")]
    cols = [feature_order.index(k) for k in order]
    A = np.array([[np.nan if row[j] is None else row[j] for j in cols] for row in X], dtype=float)
    d = len(order)
    corr = [[None] * d for _ in range(d)]
    counts = [[0] * d for _ in range(d)]
    for a in range(d):
        for b in range(a, d):
            both = ~np.isnan(A[:, a]) & ~np.isnan(A[:, b])
            k = int(np.count_nonzero(both))
            counts[a][b] = counts[b][a] = k
            if a == b:
                # the diagonal is 1.0 whenever the column exists at all — a column is perfectly
                # redundant with itself even when only one target measured it.
                corr[a][b] = 1.0 if k else None
                continue
            if k < FEATURE_CORR_MIN_PAIRWISE_N:
                continue
            va, vb = A[both, a], A[both, b]
            if np.std(va) == 0 or np.std(vb) == 0:
                # a constant column has no correlation with anything (0/0); leave it unknown rather than
                # reporting the 0.0 that np.corrcoef emits with a RuntimeWarning.
                continue
            r = float(np.corrcoef(va, vb)[0, 1])
            if not np.isfinite(r):
                continue
            corr[a][b] = corr[b][a] = round(r, 4)
    return order, corr, counts


@functools.lru_cache(maxsize=1)
def _live_rule_ids() -> frozenset:
    """Every rule_id currently defined in target-contracts' rule files — the set a FRESH run can still emit.
    Used to drop DEAD fingerprint ids (renamed/retired rungs) from the frozen precedent overlay: a rename
    like #1326 (`phospho-not-phosphoprotein-neutral` retired) otherwise leaves a token in ~112 CACHED corpus
    packages that no live query can match, quietly deflating those targets' rule-fingerprint jaccard. A
    re-freeze from cache would preserve it; a string remap is invalid (the retired rung SPLIT 3 ways). So the
    freeze filters fingerprints to what's still emittable. Fail-OPEN: contracts unreachable/unparseable →
    empty set → NO filtering (never silently blank the fingerprints)."""
    try:
        import yaml
        from _skills_common.paths import target_contracts_root

        root = target_contracts_root()
    except Exception:  # noqa: BLE001
        return frozenset()
    ids: set = set()

    def _walk(o):
        if isinstance(o, dict):
            v = o.get("rule_id")
            if isinstance(v, str):
                ids.add(v)
            for x in o.values():
                _walk(x)
        elif isinstance(o, list):
            for x in o:
                _walk(x)

    try:
        for f in Path(root).rglob("*.yaml"):
            try:
                _walk(yaml.safe_load(f.read_text()))
            except Exception:  # noqa: BLE001 — skip an unparseable file, never abort the build
                continue
    except Exception:  # noqa: BLE001
        return frozenset()
    return frozenset(ids)


def _load_panel(path: Path) -> dict:
    panel = {}
    for line in Path(path).read_text().splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 3:
            panel[(parts[0], parts[1])] = parts[2]
    return panel


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], cwd=str(SKILLS_DIR), stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def build(runs_dirs, panel_path: Path, build_date: str, emb_dim: int = 16) -> dict:
    _assert_deferral_declarations_consistent()  # before any work: a violated deferral invalidates the output
    panel = _load_panel(panel_path)
    feats, targets, indications, labels, fingerprints = [], [], [], [], []
    seen = set()
    for runs in runs_dirs:
        for run in sorted(glob.glob(f"{runs}/*")):
            if not os.path.isdir(run):
                continue
            # claim vectors — layout-tolerant (current evidence_package.json OR legacy subskills/*/package.json)
            cvs = claim_vectors_for_run(run)
            if not cvs:
                continue
            ep_f = os.path.join(run, "evidence_package.json")
            pkg = json.load(open(ep_f)) if os.path.exists(ep_f) else None
            nom_f = os.path.join(run, "nomination.json")
            nom = json.load(open(nom_f)) if os.path.exists(nom_f) else {}
            # target / indication + fired rules: current evidence_package context, else legacy nomination
            if pkg:
                ctx = pkg.get("context") or {}
                t, i = ctx.get("target") or {}, ctx.get("indication") or {}
                tgt = (t.get("symbol") if isinstance(t, dict) else t) or nom.get("target")
                ind = (i.get("oncotree_code") if isinstance(i, dict) else i) or nom.get("indication")
                sub_verdicts = (pkg.get("synthesis") or {}).get("sub_verdicts") or {}
            else:
                tgt, ind = nom.get("target"), nom.get("indication")
                sub_verdicts = nom.get("sub_verdicts") or {}
            if not tgt or (tgt, ind) in seen:
                continue
            # NUMERIC substrate: harvest the metered value_fields (+ masks) from the composed package.
            # build_feature_vector merges ordinal claims (claim_features) with the polarity-signed numerics.
            numeric_values = numeric_values_from_package(pkg) if pkg else {}
            feat = build_feature_vector(cvs, numeric_values)
            feat = {k: v for k, v in feat.items() if not k.startswith(EXCLUDED_NAMESPACES)}
            if not feat:
                continue
            rules = set()
            for v in sub_verdicts.values():
                if isinstance(v, dict):
                    rules.update(v.get("fired_rule_ids") or [])
            # drop DEAD rungs (renamed/retired since these — possibly cached — packages were generated) so the
            # frozen precedent overlay carries only ids a live query can still match. Fail-open (empty live
            # set ⇒ keep all).
            live = _live_rule_ids()
            fp = sorted(r for r in rules if r in live) if live else sorted(rules)
            seen.add((tgt, ind))
            feats.append(feat)
            targets.append(tgt)
            indications.append(ind)
            labels.append(panel.get((tgt, ind), "?"))
            fingerprints.append(fp)

    # feature_order = union of claim keys measured in >=2 targets (drop all-NaN/singleton columns)
    cand = sorted({k for f in feats for k in f})
    feature_order = [k for k in cand if sum(1 for f in feats if f.get(k) is not None) >= 2]
    # A `::mask` column is ALWAYS 0/1 (never None), so the sparsity rule above can never drop it — even when
    # the value column it describes IS dropped. That left an ORPHAN mask in the 2026-09-12 freeze
    # (tumor_protein_abundance::num::protein_effect_size::mask, whose value column was clobbered at harvest):
    # a constant-0 column that spends a feature slot, adds no signal, and reads as a live axis to any consumer
    # walking feature_order. Drop a mask with its value column.
    kept = set(feature_order)
    feature_order = [k for k in feature_order if not (k.endswith("::mask") and k[: -len("::mask")] not in kept)]
    dropped = len(cand) - len(feature_order)
    X = [[f.get(k) for k in feature_order] for f in feats]
    Xn = np.array([[np.nan if v is None else v for v in row] for row in X], dtype=float)
    mu = np.nanmean(Xn, axis=0)
    sd = np.nanstd(Xn, axis=0)
    sd = np.where(sd == 0, 1.0, sd)
    # per-column MEASURED fraction (non-null over all corpus targets), aligned to feature_order. A column
    # that is mostly unmeasured is not a trustworthy REFERENCE distribution — a rank/percentile/surprisal
    # read against it over-claims. Frozen so any label-free consumer (cohort meters, a salience surprisal
    # probe) can gate on reference quality (e.g. require >= 0.6) FROM the artifact, auditably, instead of
    # recomputing it per read. Descriptive / verdict-INERT.
    n_rows = Xn.shape[0] if Xn.size else 0
    reference_mask_fraction = [
        round(float(np.count_nonzero(~np.isnan(Xn[:, j])) / n_rows), 4) if n_rows else 0.0
        for j in range(len(feature_order))
    ]

    # per-column-PAIR redundancy, over the metered numerics only, on the OBSERVED rows (not the imputed
    # ones the PCA uses). Lets a label-free consumer discount a reference column that duplicates another
    # instead of hand-tuning a per-axis weight. See feature_correlation() for why the basis differs.
    feature_corr_order, feature_corr, feature_corr_n = feature_correlation(feature_order, X)

    # LINEAR embedding: z-score vs mu/sd, mean-impute missing -> 0 (EXACT runtime transform), then PCA.
    from sklearn.decomposition import PCA

    Z = (np.where(np.isnan(Xn), mu, Xn) - mu) / sd  # missing -> mean -> z=0
    m = min(emb_dim, Z.shape[1], Z.shape[0])
    pca = PCA(n_components=m, random_state=0, svd_solver=PCA_SVD_SOLVER).fit(Z)
    components = pca.components_  # m x d
    corpus_emb = pca.transform(Z)  # n x m

    # anchors: each label's coord = CENTROID (mean embedding) of its present exemplar-set members
    idx_of = {(t, i): r for r, (t, i) in enumerate(zip(targets, indications))}
    anchors = []
    skipped_anchors = []
    for label, members in ANCHOR_SETS.items():
        if label in DEFERRED_ANCHORS:
            # DEFERRED by an evidenced separation failure (not mere absence): its exemplars may now be in the
            # corpus (e.g. the 2026-09-13 expansion added RET/THCA + NTRK1/THCA, which are fusion_driver
            # members), but activating it would ship a known-BLEEDING anchor without a passing separation
            # test. Skip regardless of member presence until a re-freeze re-runs + PASSES its separation test.
            skipped_anchors.append(label)
            print(
                f"WARN: anchor '{label}' DEFERRED (evidenced non-separation) — skipped despite members", file=sys.stderr
            )
            continue
        present = [(t, i) for (t, i) in members if (t, i) in idx_of]
        if not present:
            # An ASPIRATIONAL anchor (its exemplars are not yet in the corpus, e.g. fusion_driver awaiting
            # ALK/ROS1/NTRK-fusion runs) is SKIPPED with a warning rather than aborting the whole build —
            # so the exemplar spec can carry the target panel forward and the anchor activates once its
            # runs land. A wrongly-typo'd exemplar surfaces the same way (empty → skipped + warned).
            skipped_anchors.append(label)
            print(f"WARN: anchor '{label}' skipped — no exemplar members present in corpus: {members}", file=sys.stderr)
            continue
        rows = [idx_of[(t, i)] for (t, i) in present]
        centroid = corpus_emb[rows].mean(axis=0)
        rep_t, rep_i = present[0]  # canonical representative (shown in payload)
        anchors.append(
            {
                "label": label,
                "target": rep_t,
                "indication": rep_i,
                "coord": [round(float(x), 6) for x in centroid],
                "members": [[t, i] for (t, i) in present],
                "n_members": len(present),
            }
        )

    # axis_ref (D1 scorecard z-ref): per-axis corpus mean/std of axis_score (nan-mean of ::signal tiers)
    sig_idx = [j for j, k in enumerate(feature_order) if k.endswith("::signal")]
    axis_of = {j: feature_order[j].split("::")[0] for j in sig_idx}
    axes = sorted(set(axis_of.values()))
    axis_scores = np.full((len(feats), len(axes)), np.nan)
    for r in range(len(feats)):
        for a_i, ax in enumerate(axes):
            vals = [Xn[r, j] for j in sig_idx if axis_of[j] == ax and not np.isnan(Xn[r, j])]
            if vals:
                axis_scores[r, a_i] = float(np.mean(vals))
    ax_mean = np.nanmean(axis_scores, axis=0)
    ax_std = np.nanstd(axis_scores, axis=0)
    ax_std = np.where((ax_std == 0) | np.isnan(ax_std), 1.0, ax_std)
    axis_ref = {
        axes[j]: {"mean": round(float(ax_mean[j]), 6), "std": round(float(ax_std[j]), 6)} for j in range(len(axes))
    }

    doc = {
        "feature_order": feature_order,
        # per-column measured fraction (aligned to feature_order) — reference-distribution quality for
        # label-free rank/percentile/surprisal consumers to gate on (verdict-INERT).
        "reference_mask_fraction": reference_mask_fraction,
        # per-PAIR redundancy over the metered numerics, pairwise-complete. Three keys, always together:
        # the matrix, the column keys it is aligned to (a SUBSET of feature_order — never index it with
        # feature_order), and the co-measured row count behind each cell (None cell = never looked).
        "feature_corr_order": feature_corr_order,
        "feature_corr": feature_corr,
        "feature_corr_n": feature_corr_n,
        "mu": [round(float(x), 6) for x in mu],
        "sd": [round(float(x), 6) for x in sd],
        "X": X,
        "targets": targets,
        "indications": indications,
        "labels": labels,
        "rule_fingerprints": fingerprints,
        "axis_ref": axis_ref,
        "embedding": {
            "kind": "pca_linear_on_zscored_mean_imputed",
            "dim": int(m),
            "components": [[round(float(x), 6) for x in row] for row in components],
            "explained_variance_ratio": [round(float(x), 5) for x in pca.explained_variance_ratio_],
            "corpus": [[round(float(x), 6) for x in row] for row in corpus_emb],
        },
        "anchors": anchors,
        "meta": {
            "n_targets": len(targets),
            "n_features": len(feature_order),
            "n_features_dropped_sparse": dropped,
            "emb_dim": int(m),
            # WHICH PCA solver produced the loadings. `full` and `randomized` are different algorithms, not
            # the same one at different precisions, so an embedding is only reproducible against the solver
            # that fit it. Stamped rather than assumed because the value used to be sklearn's size-dependent
            # `auto` — see PCA_SVD_SOLVER. Absent from atlases frozen before 2026-09-13; those were all built
            # under a corpus small enough that `auto` resolved to `full`.
            "embedding_pca_svd_solver": PCA_SVD_SOLVER,
            "classes": sorted(set(labels)),
            "anchor_phenotypes": [a["label"] for a in anchors],
            "anchor_phenotypes_skipped": skipped_anchors,  # aspirational anchors awaiting exemplar runs
            "corpus": "+".join(os.path.basename(str(r)) for r in runs_dirs),
            "build_date": build_date,
            "build_git_sha": _git_sha(),
            # feature_schema_version distinguishes the ORDINAL-ONLY freeze (v1, 108 features, claim tiers
            # only) from the richer substrate (v2 = ordinal claims + polarity-signed metered numerics +
            # measured-vs-unmeasured masks). A consumer that must know whether numerics are in the frozen
            # space reads this instead of counting columns.
            "feature_schema_version": "2.0.0",
            # feature_corr is computed ABOVE, in this same build, from the same X being frozen. Stamping
            # that here is not decoration: `amend_atlas_feature_corr.py` is the OTHER producer of this
            # block and it hardcodes derived_post_freeze=True, so before this stamp existed a native
            # rebuild emitted feature_corr with NO provenance at all and
            # test_the_derived_block_declares_its_own_provenance failed on the next re-freeze. The tempting
            # repair — re-run the amend script over the fresh artifact — would assert a post-freeze
            # derivation that did not happen. The two states are mutually exclusive and both legitimate;
            # `derived_post_freeze` is which one produced the block, so a reader can tell a block frozen
            # WITH the basis from one re-derived against it.
            "feature_corr_provenance": native_feature_corr_provenance(build_date, _git_sha()),
            "atlas_excluded_namespaces": list(EXCLUDED_NAMESPACES),
            "n_numeric_features": sum(1 for k in feature_order if "::num::" in k and not k.endswith("::mask")),
            "n_mask_features": sum(1 for k in feature_order if k.endswith("::mask")),
            "vectoriser": "feature_vectoriser.build_feature_vector (ordinal claims + metered numerics + masks)",
            "note": (
                "DESCRIPTIVE phenotype-landscape atlas; provisional partly-circular panel labels; NOT "
                "a classifier freeze. Anchored convex mixture over curated canonical exemplars. The "
                "former outcome/approval-propensity (D2/D3) score was RETIRED."
            ),
        },
    }
    # soft_labels: the anchored-mixture DOMINANT phenotype for EVERY corpus target — a data-derived
    # display label so nearest-analogs read meaningfully even where the curated panel label is "?"
    # (106/213 unlabeled). Descriptive only; the curated `labels` field is left untouched.
    from _skills_common.archetype_core import Atlas  # noqa: E402  (reuse the runtime membership solver)

    _a = Atlas(doc)
    soft = []
    for e in _a.corpus_emb:
        votes, _hull, _recon = _a._membership(e)
        soft.append(max(votes, key=votes.get) if votes else "?")
    doc["soft_labels"] = soft
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True, nargs="+", help="one or more target-profile run dirs")
    ap.add_argument("--panel", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--emb-dim", type=int, default=16)
    ap.add_argument("--build-date", default=os.environ.get("ATLAS_BUILD_DATE", "unknown"))
    a = ap.parse_args()
    doc = build([Path(r).expanduser() for r in a.runs], Path(a.panel).expanduser(), a.build_date, a.emb_dim)
    out = Path(a.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, separators=(",", ":"), sort_keys=False))
    m = doc["meta"]
    print(
        f"wrote {out}  n_targets={m['n_targets']} n_features={m['n_features']} emb_dim={m['emb_dim']} "
        f"anchors={m['anchor_phenotypes']}"
    )


if __name__ == "__main__":
    main()
