"""archetype_core — the verdict-INERT cross-skill target-signature LANDSCAPE companion.

WHAT THIS IS. A target's composed profile (the 13 sub-skills' claim-vectors) is distilled into a point in
a FROZEN low-dimensional embedding of the target-signature space. Against a frozen set of CANONICAL
phenotype ANCHORS (curated exemplars, one per drug-target phenotype) this module computes, for a query:
  - a soft PHENOTYPE MIXTURE  (convex membership to the anchors — "60% surface + 25% GoF-driver + ...";
                               a distribution, NEVER a hard single label)
  - nearest reference ANALOGS ("most like CDH17, TROP2, ...", by embedding distance)
  - a MISSINGNESS map          (which axes are unmeasured — the acquisition backlog per target)
  - NOVELTY                    (hull-residual = fits no canonical phenotype mix = INCONSISTENT, plus a
                               local-density flag — the fix for the old global-NN metric flagging EXTREME
                               targets like EGFR as "novel")
  - a rule-fingerprint PRECEDENT overlay (same fired-rule signature; on the auditable rule spine)

WHY ANCHORED (design). Unsupervised phenotype DISCOVERY (kNN over raw features, KMeans, archetypal
analysis) is seed/n-unstable at this corpus size and mis-names corners. Anchoring the phenotype space on
curated canonical exemplars (KRAS=GoF-driver, VHL=TSG, ERBB2=amp, EPCAM=surface, AURKA=dependency,
GAPDH=control) makes the mixture stable, correctly-named, and biologically faithful (validated:
KRAS→90% GoF, ERBB2→100% amp, VHL→100% TSG, EGFR→amp+GoF). Anchor labels reuse the archetype-label
vocabulary so the D1 scorecard's per-archetype weight profiles keep consuming `soft_membership` unchanged.

WHAT THIS IS NOT (governance — non-negotiable). DESCRIPTIVE and strictly VERDICT-INERT: it never mints a
recommendation, never enters `fired` / the resolver / `_SHORT_TO_GATE` / the sub_verdicts spine. It
attaches like the other reduction-stage facets (fragility / heterogeneity), computed AFTER the fan-out.
NOTE: the outcome-trained approval-propensity score (former D2/D3) was RETIRED here — an ablation showed
its signal was carried by advancement/study-depth features, not disease biology, and the pure-biology
residual did not beat a genetics baseline; the honest product is this descriptive phenotype landscape.

DEPLOYMENT. Pure-stdlib + deterministic. The embedding is a FROZEN linear projection (PCA loadings shipped
as data in the atlas), applied to a z-scored, mean-imputed query vector — no torch, no pickle. Missing
tiers are mean-imputed (z=0) for the projection; per-axis missingness is surfaced honestly alongside.

SUBSTRATE. The vector is built from each sub-skill's `synthesis_facet.claim_vector` — the same payload
`package.json` carries — so the OFFLINE atlas and the RUNTIME query share ONE vectoriser. Corroboration
uses its own low/moderate/high vocabulary (the prior "only-moderate" encoding bug is fixed here).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

# Ordinal encoding of the claim tiers. SIGNAL uses strong/moderate/weak/absent; CORROBORATION uses its
# OWN low/moderate/high vocabulary — the prior single-map silently nulled low+high (the "only-moderate"
# bug). Both encodings must match the offline atlas build (single source of truth).
CLAIM_SIG_ORD = {"strong": 3.0, "moderate": 2.0, "weak": 1.0,
                 "absent": 0.0, "negative": 0.0, "unmeasured": None, "none": None}
CLAIM_CORR_ORD = {"high": 3.0, "moderate": 2.0, "low": 1.0,
                  "absent": 0.0, "negative": 0.0, "unmeasured": None, "none": None}

DEFAULT_K = 8


def claim_features(subskill_claim_vectors: dict) -> dict:
    """{short: {CLAIM: {signal, corroboration, ...}}} -> {short::claim::CLAIM::signal|corrob: ordinal|None}.

    The single canonical vectoriser used for BOTH the offline atlas build and the runtime query, so the
    two coordinate systems are identical by construction."""
    out: dict = {}
    for short, cv in (subskill_claim_vectors or {}).items():
        if not isinstance(cv, dict):
            continue
        for claim, val in cv.items():
            if not isinstance(val, dict):
                continue
            sig = str(val.get("signal", "")).lower()
            cor = str(val.get("corroboration", "")).lower()
            out[f"{short}::claim::{claim}::signal"] = CLAIM_SIG_ORD.get(sig)
            out[f"{short}::claim::{claim}::corrob"] = CLAIM_CORR_ORD.get(cor)
    return out


def vector_from_sub_results(sub_results: dict) -> dict:
    """Build the query feature dict from the in-process fan-out `sub_results` (dict short -> r)."""
    cvs = {}
    for short, r in (sub_results or {}).items():
        if not isinstance(r, dict):
            continue
        cv = (r.get("synthesis_facet") or {}).get("claim_vector")
        if isinstance(cv, dict) and cv:
            cvs[short] = cv
    return claim_features(cvs)


def fired_rule_ids_from_sub_results(sub_results: dict) -> set:
    """The union of fired rule_ids across sub-skills — the auditable rule-fingerprint of a target."""
    hits: set = set()
    for r in (sub_results or {}).values():
        if not isinstance(r, dict):
            continue
        for f in (r.get("fired") or []):
            if isinstance(f, dict) and f.get("rule_id"):
                hits.add(f["rule_id"])
    return hits


def _proj_simplex(v: list) -> list:
    """Project a vector onto the probability simplex (Duchi 2008), pure-python."""
    if not v:
        return v
    u = sorted(v, reverse=True)
    css = 0.0
    rho, theta = 0, 0.0
    for i, uu in enumerate(u):
        css += uu
        if uu - (css - 1.0) / (i + 1) > 0:
            rho = i + 1
            theta = (css - 1.0) / (i + 1)
    # recompute theta at rho (css over first rho entries)
    theta = (sum(u[:rho]) - 1.0) / rho if rho else 0.0
    return [max(x - theta, 0.0) for x in v]


class Atlas:
    """A frozen reference atlas backing the descriptive phenotype-landscape companion.

    JSON shape (see build_atlas): feature_order · mu · sd (nan-aware) · X (raw ordinal rows, null=missing) ·
    targets · indications · labels · rule_fingerprints · axis_ref (D1 z-ref) · embedding{components (m x d),
    corpus (n x m)} · anchors[{label, target, indication, coord (m)}] · meta."""

    def __init__(self, doc: dict):
        self.feature_order: list = list(doc["feature_order"])
        self.mu: list = [float(x) for x in doc["mu"]]
        self.sd: list = [float(x) if x else 1.0 for x in doc["sd"]]
        self.X: list = doc.get("X", [])
        self.targets: list = list(doc["targets"])
        self.indications: list = list(doc.get("indications", [""] * len(self.targets)))
        self.labels: list = list(doc["labels"])
        self.rule_fingerprints: list = doc.get("rule_fingerprints", [[] for _ in self.targets])
        self.axis_ref: dict = doc.get("axis_ref", {})
        emb = doc.get("embedding") or {}
        self.components: list = emb.get("components", [])          # m x d PCA loadings
        self.corpus_emb: list = emb.get("corpus", [])              # n x m reference coords
        self.anchors: list = doc.get("anchors", [])                # [{label,target,indication,coord}]
        self.meta: dict = doc.get("meta", {})
        # corpus nearest-neighbour distance distribution (in embedding) for the local-density novelty flag
        self._nn_ref = self._corpus_nn_distances()

    @classmethod
    def load(cls, path) -> "Atlas":
        return cls(json.loads(Path(path).read_text()))

    # ---- embedding ----
    def _align_z_impute(self, feat: dict) -> list:
        """Align a query onto feature_order, z-score vs frozen mu/sd, mean-impute missing -> 0 (=corpus mean)."""
        out = []
        for i, k in enumerate(self.feature_order):
            v = feat.get(k)
            out.append(0.0 if v is None else (v - self.mu[i]) / self.sd[i])
        return out

    def _embed(self, feat: dict) -> list:
        """Project a query into the frozen embedding: e[j] = sum_i components[j][i] * z_imputed[i]."""
        z = self._align_z_impute(feat)
        return [sum(comp[i] * z[i] for i in range(len(z))) for comp in self.components]

    def _corpus_nn_distances(self) -> list:
        out = []
        for i, a in enumerate(self.corpus_emb):
            best = math.inf
            for j, b in enumerate(self.corpus_emb):
                if i == j:
                    continue
                d = math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))
                if d < best:
                    best = d
            if math.isfinite(best):
                out.append(best)
        return sorted(out)

    def _novelty_threshold(self, pctl: float = 0.9) -> float:
        if not self._nn_ref:
            return math.inf
        return self._nn_ref[min(len(self._nn_ref) - 1, int(pctl * len(self._nn_ref)))]

    # ---- anchored convex membership ----
    def _membership(self, e: list, iters: int = 400) -> tuple:
        """Convex mixture of the anchors nearest e: min ||e - w·Z||^2 s.t. w>=0, sum w=1 (projected grad).

        Returns (weights_by_label: dict, hull_residual: float). Labels reuse the archetype vocabulary."""
        Z = [a["coord"] for a in self.anchors]
        k = len(Z)
        if not k:
            return {}, math.inf
        m = len(e)
        w = [1.0 / k] * k
        step = 1.0
        prev = math.inf
        for _ in range(iters):
            recon = [sum(w[j] * Z[j][t] for j in range(k)) for t in range(m)]
            resid = [e[t] - recon[t] for t in range(m)]
            # grad_j = -2 * <resid, Z_j>
            grad = [-2.0 * sum(resid[t] * Z[j][t] for t in range(m)) for j in range(k)]
            gmax = max((abs(g) for g in grad), default=1.0) or 1.0
            w = _proj_simplex([w[j] - step * grad[j] / gmax for j in range(k)])
            loss = sum(r * r for r in resid)
            step = step * 1.05 if loss < prev else step * 0.6
            prev = loss
        recon = [sum(w[j] * Z[j][t] for j in range(k)) for t in range(m)]
        hull = math.sqrt(sum((e[t] - recon[t]) ** 2 for t in range(m)))
        votes: dict = {}
        for j, a in enumerate(self.anchors):
            votes[a["label"]] = votes.get(a["label"], 0.0) + w[j]      # collapse duplicate-label anchors
        return {kk: round(vv, 3) for kk, vv in sorted(votes.items(), key=lambda x: -x[1])}, hull

    def companion(self, feat: dict, k: int = DEFAULT_K,
                  query_rules: Optional[set] = None, exclude_self: bool = True) -> dict:
        """Descriptive phenotype-landscape companion for a query feature dict. VERDICT-INERT payload."""
        e = self._embed(feat)
        # nearest analogs in the embedding
        dists = [math.sqrt(sum((x - y) ** 2 for x, y in zip(e, c))) for c in self.corpus_emb]
        order = sorted(range(len(dists)), key=lambda i: dists[i])
        if exclude_self:
            # SELF_EPS tolerates the atlas's 6-dp coord rounding (a self-query lands at ~1e-5, not exactly 0);
            # far below the real inter-target spacing (>~5 in this embedding), so only self / exact
            # duplicates are dropped, never a genuine neighbour.
            order = [i for i in order if dists[i] > 1e-3]
        nn = order[:k]
        analogs = [{"target": self.targets[i], "indication": self.indications[i],
                    "archetype_label": self.labels[i], "distance": round(dists[i], 3)} for i in nn]

        membership, hull = self._membership(e)

        # missingness map (acquisition backlog): axes entirely unmeasured for this target
        by_tot: dict = {}
        by_missing: dict = {}
        for kk in self.feature_order:
            ax = kk.split("::")[0]
            by_tot[ax] = by_tot.get(ax, 0) + 1
            if feat.get(kk) is None:
                by_missing[ax] = by_missing.get(ax, 0) + 1
        missing_axes = sorted(ax for ax in by_tot if by_missing.get(ax, 0) == by_tot[ax])

        # novelty: hull-residual (INCONSISTENT with any canonical mix) + local-density flag (embedding NN)
        nn_dist = dists[nn[0]] if nn else math.inf
        hull_ref = sorted(
            self._membership_hull(c) for c in self.corpus_emb) if self.corpus_emb else []
        hull_thr = hull_ref[min(len(hull_ref) - 1, int(0.9 * len(hull_ref)))] if hull_ref else math.inf
        novelty = {
            "hull_residual": None if not math.isfinite(hull) else round(hull, 3),
            "inconsistent_flag": bool(math.isfinite(hull) and hull > hull_thr),
            "nearest_neighbour_distance": None if not math.isfinite(nn_dist) else round(nn_dist, 3),
            "local_density_flag": bool(math.isfinite(nn_dist) and nn_dist > self._novelty_threshold()),
            "metric": "hull_residual=inconsistent_with_canonical_phenotypes; nn_distance=local_density",
        }

        out = {
            "verdict": None,                                 # governance: descriptive companion, never a call
            "phenotype_mixture": membership,                 # convex membership to canonical anchors
            "soft_membership": membership,                   # alias (D1 scorecard consumes this key)
            "nearest_analogs": analogs,
            "missingness": {"unmeasured_axes": missing_axes,
                            "n_features_measured": sum(1 for v in feat.values() if v is not None),
                            "n_features_total": len(self.feature_order)},
            "novelty": novelty,
            "anchors": [{"label": a["label"], "target": a["target"], "indication": a["indication"]}
                        for a in self.anchors],
            "atlas_provenance": self.meta,
            "disclaimer": (
                "DESCRIPTIVE, verdict-inert target-signature LANDSCAPE companion. Phenotype mixture is a "
                "convex membership to CURATED canonical anchors (soft, never a hard label); it describes "
                "the collected evidence, it is NOT a classification or nomination claim and NOT a gate. "
                "Novelty=hull-residual flags a signature inconsistent with any canonical phenotype mix. "
                "The outcome/approval-propensity score was retired (signal was study-depth, not biology)."
            ),
        }
        if query_rules:
            prec = []
            for i, rf in enumerate(self.rule_fingerprints):
                rs = set(rf)
                if not rs:
                    continue
                inter = len(query_rules & rs)
                union = len(query_rules | rs) or 1
                prec.append((inter / union, i))
            prec.sort(key=lambda x: -x[0])
            out["rule_precedent"] = [{"target": self.targets[i], "indication": self.indications[i],
                                      "archetype_label": self.labels[i], "jaccard": round(j, 3)}
                                     for j, i in prec[:k] if j > 0]
        return out

    def _membership_hull(self, e: list) -> float:
        """Hull residual for a corpus point (used to build the novelty reference distribution)."""
        return self._membership(e, iters=200)[1]


def companion_from_sub_results(sub_results: dict, atlas: Atlas, k: int = DEFAULT_K) -> dict:
    """In-process fan-out results -> phenotype-landscape companion. The target-profile reduction hook."""
    feat = vector_from_sub_results(sub_results)
    rules = fired_rule_ids_from_sub_results(sub_results)
    return atlas.companion(feat, k=k, query_rules=rules)


# =============================================================================================
# D1 NOMINATION SCORECARD — interpretable, glass-box, ARCHETYPE-CONDITIONED nomination-readiness companion.
# VERDICT-INERT. Consumes the phenotype MIXTURE (`soft_membership`, keyed by the archetype vocabulary) to
# blend per-archetype weight profiles, so a target is scored on its OWN phenotype route. Unchanged by the
# landscape refactor except that membership now comes from the anchored mixture.
# =============================================================================================
SCORECARD_AXES = ["expression", "selectivity", "surface_modality", "genomic_alteration", "dependency",
                  "tractability_sm", "differentiation", "mechanism", "cis_coherence", "immune_context",
                  "combination_vulnerability", "target_intrinsic", "safety"]
AX_SIGN = {a: 1 for a in SCORECARD_AXES}
AX_SIGN["safety"] = -1
DEFAULT_AX_W = 0.2
ARCH_W = {
    "expression_surface": {"expression": 1.2, "selectivity": 1.3, "surface_modality": 1.4, "safety": 1.0,
                           "immune_context": 0.6, "differentiation": 0.4, "genomic_alteration": 0.2,
                           "dependency": 0.2, "tractability_sm": 0.2, "mechanism": 0.3},
    "snv_driver": {"genomic_alteration": 1.3, "tractability_sm": 1.2, "dependency": 1.0, "mechanism": 0.9,
                   "safety": 0.9, "differentiation": 0.6, "expression": 0.3, "selectivity": 0.3,
                   "surface_modality": 0.2},
    "amp_driver": {"genomic_alteration": 1.3, "dependency": 1.0, "tractability_sm": 1.0, "expression": 0.9,
                   "surface_modality": 0.5, "safety": 0.8, "mechanism": 0.7, "selectivity": 0.4},
    "tsg_loss": {"genomic_alteration": 1.1, "combination_vulnerability": 1.2, "differentiation": 0.7,
                 "mechanism": 0.6, "dependency": 0.5, "tractability_sm": 0.4, "safety": 0.6,
                 "expression": 0.2, "surface_modality": 0.2},
    "dependency_essential": {"dependency": 1.4, "tractability_sm": 1.1, "mechanism": 0.9, "safety": 1.0,
                             "differentiation": 0.5, "combination_vulnerability": 0.6, "expression": 0.3,
                             "genomic_alteration": 0.4},
    "control_absent": {a: 0.3 for a in SCORECARD_AXES},
    "control_housekeeping": {**{a: 0.3 for a in SCORECARD_AXES}, "safety": 1.2, "dependency": 0.5},
}
ARCH_W = {k: {ax: v.get(ax, DEFAULT_AX_W) for ax in SCORECARD_AXES} for k, v in ARCH_W.items()}


def _axis_scores(feat: dict) -> dict:
    acc: dict = {}
    for kk, v in feat.items():
        if v is None or not kk.endswith("::signal"):
            continue
        acc.setdefault(kk.split("::")[0], []).append(v)
    return {ax: (sum(vs) / len(vs)) for ax, vs in acc.items()}


def nomination_scorecard(feat: dict, membership: dict, atlas: Atlas) -> dict:
    """Glass-box, archetype-conditioned nomination-readiness score. VERDICT-INERT."""
    if not atlas.axis_ref:
        return {"verdict": None, "score": None, "note": "atlas has no axis_ref (rebuild atlas)"}
    ascore = _axis_scores(feat)
    z = {}
    for ax in SCORECARD_AXES:
        ref = atlas.axis_ref.get(ax)
        if ref and ax in ascore:
            z[ax] = ((ascore[ax] - ref["mean"]) / (ref["std"] or 1.0)) * AX_SIGN[ax]
    m = membership or {}
    mtot = sum(m.values()) or 1.0
    eff_w = {}
    for ax in SCORECARD_AXES:
        eff_w[ax] = sum((m.get(k, 0.0) / mtot) * ARCH_W.get(k, {}).get(ax, DEFAULT_AX_W) for k in m) \
            if m else DEFAULT_AX_W
    contrib = {ax: z[ax] * eff_w[ax] for ax in z}
    wsum = sum(eff_w[ax] for ax in z) or 1.0
    raw = sum(contrib.values()) / wsum
    score01 = 1.0 / (1.0 + math.exp(-raw))
    coverage = len(z) / len(SCORECARD_AXES)
    ordered = sorted(contrib.items(), key=lambda x: -x[1])
    driving = [{"axis": ax, "contribution": round(c, 3)} for ax, c in ordered[:3] if c > 0]
    dom = max(m, key=m.get) if m else None
    route = {ax for ax, w in ARCH_W.get(dom, {}).items() if w >= 0.8} if dom else set(SCORECARD_AXES)
    limiting = ordered[-1] if ordered else (None, None)
    rel = [(ax, c) for ax, c in ordered if ax in route] or ordered
    cond_limiting = min(rel, key=lambda x: x[1]) if rel else (None, None)
    cl_ax, cl_c = cond_limiting
    counterfactual = None
    if cl_ax is not None:
        gap = atlas.axis_ref.get(cl_ax, {})
        measured = cl_ax in ascore
        counterfactual = {
            "limiting_axis": cl_ax, "limiting_contribution": round(cl_c, 3), "route_conditioned": True,
            "statement": (f"Route-limiting axis for the {dom} route is '{cl_ax}'"
                          + (f" (below the corpus mean {gap.get('mean')})." if measured
                             else " — UNMEASURED; acquiring this axis's evidence would resolve the gap.")),
            "axis_measured": measured,
        }
    return {
        "verdict": None,
        "score": round(score01, 3),
        "coverage": round(coverage, 3),
        "dominant_archetype_soft": dom,
        "axis_contributions": {ax: round(c, 3) for ax, c in ordered},
        "driving_axes": driving,
        "limiting_axis": {"axis": limiting[0], "contribution": round(limiting[1], 3)} if limiting[0] else None,
        "counterfactual_gap": counterfactual,
        "weights_note": ("ILLUSTRATIVE expert-set weights, phenotype-mixture-blended per-archetype (SHOWN, "
                         "not learned). Interpretable D1 layer; safety is a liability axis (sign −1)."),
        "disclaimer": ("DESCRIPTIVE, verdict-inert nomination-READINESS score. Glass-box: score = "
                       "phenotype-conditioned weighted mean of z-scored axis positions vs the frozen "
                       "corpus. NOT a gate, never mints a recommendation."),
    }


def scorecard_from_sub_results(sub_results: dict, atlas: Atlas, k: int = DEFAULT_K,
                               companion: Optional[dict] = None) -> dict:
    """In-process fan-out results -> D1 scorecard. Reuses a precomputed companion's soft_membership."""
    feat = vector_from_sub_results(sub_results)
    membership = (companion or {}).get("soft_membership")
    if membership is None:
        membership = atlas.companion(feat, k=k).get("soft_membership")
    return nomination_scorecard(feat, membership, atlas)
