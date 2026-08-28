"""archetype_core — the verdict-INERT cross-skill target-archetype COMPANION primitive.

WHAT THIS IS. A target's composed profile (the 13 sub-skills' claim-vectors) forms a per-target point
in a shared "target-archetype" space. Against a FROZEN reference atlas of labelled targets this module
computes, for a query target:
  - nearest reference ANALOGS   ("most like CDH17, TROP2, ...")
  - soft archetype MEMBERSHIP   (distance-weighted kNN vote — NOT a hard single label)
  - a rule-fingerprint PRECEDENT overlay (same fired-rule signature; lives on the auditable rule spine)
  - a MISSINGNESS map           (which axes are unmeasured — the acquisition backlog per target)
  - a CRUDE novelty score       (nearest-neighbour distance; flags EXTREME, see caveats)

WHAT THIS IS NOT (governance — non-negotiable). This is DESCRIPTIVE and strictly VERDICT-INERT: it never
mints a recommendation, never enters `fired`, the resolver, `_SHORT_TO_GATE`, or the nomination
sub_verdicts spine. It attaches like the other reduction-stage facets (fragility / heterogeneity /
biomarker) — computed AFTER the fan-out, emitted for the reader + LLM synthesis, one-directional. There
is NO atlas-freeze-FOR-CLASSIFICATION and NO hard archetype label: the honest validated result is that
archetype structure is real (~0.80 leave-one-TARGET-out with RF on the full claim-vector; kNN companion
is descriptive) but blind/external-label validation (P3) is the gate before any classification claim.

SUBSTRATE. The vector is built from each sub-skill's `synthesis_facet.claim_vector` — the SAME payload
`tp_manifest._subskill_package` serialises into `package.json`, so the OFFLINE atlas (built from harvested
package.json) and the RUNTIME query (built from in-process `sub_results`) share ONE vectoriser. Ordinal
map is ported verbatim from the validated harvest; absent(=0) is a real 'not present', unmeasured(=None)
is ignored per-pair by the nan-aware distance (the A2 mask) rather than imputed.

CAVEATS (carried in the emitted disclaimer): labels are PROVISIONAL + partly circular (clinical antigens;
cards designed from the same biology) — nothing is a classification claim until blind labels + a held-out
split clear baseline. `housekeeping` is not a distinct archetype (recovers at ~0% — correct). `amp_driver`
is fuzzy (small n). The corroboration ordinal preserves the validated harvest's quirk (only 'moderate'
maps to a value; low/high -> None) — a re-mapping is a separate re-validated change. Novelty is a crude
global-NN distance (flags EXTREME not INCONSISTENT); a class-relative / LOF metric is backlog (A3).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

# Ordinal encoding of the claim SIGNAL / CORROBORATION tiers — PORTED VERBATIM from the validated
# harvest (harvest_packages._SIG_ORD). Do NOT "fix" the corroboration quirk here without re-running the
# leave-one-TARGET-out validation and re-freezing the atlas: the reference matrix was built under this
# exact map, so query and atlas must encode identically.
CLAIM_SIG_ORD = {
    "strong": 3.0, "moderate": 2.0, "weak": 1.0,
    "absent": 0.0, "negative": 0.0,
    "unmeasured": None, "none": None,
}

DEFAULT_K = 8


def claim_features(subskill_claim_vectors: dict) -> dict:
    """{short: {CLAIM: {signal, corroboration, ...}}} -> {short::claim::CLAIM::signal|corrob: ordinal|None}.

    This is the single canonical vectoriser used for BOTH the offline atlas build and the runtime query,
    so the two coordinate systems are identical by construction."""
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
            out[f"{short}::claim::{claim}::corrob"] = CLAIM_SIG_ORD.get(cor)
    return out


def vector_from_sub_results(sub_results: dict) -> dict:
    """Build the query feature dict from the in-process fan-out `sub_results` (dict short -> r).

    Reads r['synthesis_facet']['claim_vector'] — the exact payload package.json carries — so a runtime
    query is byte-comparable to the offline-harvested atlas rows."""
    cvs = {}
    for short, r in (sub_results or {}).items():
        if not isinstance(r, dict):
            continue
        facet = r.get("synthesis_facet") or {}
        cv = facet.get("claim_vector")
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


def _nan_euclidean(q: list, rows: list) -> list:
    """NaN-aware Euclidean distance (the A2 mask): compare only co-measured dims, rescale by dimensionality
    so pairs with more missing overlap are not spuriously 'close'. q, rows entries are float or None."""
    d = len(q)
    out = []
    for row in rows:
        ssum = 0.0
        cnt = 0
        for a, b in zip(q, row):
            if a is None or b is None:
                continue
            diff = a - b
            ssum += diff * diff
            cnt += 1
        out.append(math.sqrt(ssum * (d / cnt)) if cnt > 0 else math.inf)
    return out


class Atlas:
    """A frozen reference atlas: reference vectors + labels + provenance. Loaded once, then queried.

    JSON shape (see build_atlas): feature_order, mu, sd (nan-aware, per feature), X (n x d, null=missing),
    targets, indications, labels, rule_fingerprints (list[list[str]]), all_rules, meta."""

    def __init__(self, doc: dict):
        self.feature_order: list = list(doc["feature_order"])
        self.mu: list = [float(x) for x in doc["mu"]]
        self.sd: list = [float(x) if x else 1.0 for x in doc["sd"]]
        self.X: list = doc["X"]                              # raw ordinal rows (null = unmeasured)
        self.targets: list = list(doc["targets"])
        self.indications: list = list(doc.get("indications", [""] * len(self.targets)))
        self.labels: list = list(doc["labels"])
        self.rule_fingerprints: list = doc.get("rule_fingerprints", [[] for _ in self.targets])
        self.axis_ref: dict = doc.get("axis_ref", {})        # {axis: {mean, std}} of axis_score (D1 z-ref)
        self.meta: dict = doc.get("meta", {})
        # pre-z-score the reference matrix once (same mu/sd applied to the query at call time)
        self._Z = [self._z(row) for row in self.X]
        # corpus novelty distribution (nearest-neighbour distance per reference point) for the flag
        self._nn_ref = self._corpus_nn_distances()

    @classmethod
    def load(cls, path) -> "Atlas":
        return cls(json.loads(Path(path).read_text()))

    def _z(self, row: list) -> list:
        return [None if (v is None) else (v - self.mu[i]) / self.sd[i] for i, v in enumerate(row)]

    def _align(self, feat: dict) -> list:
        """Project a query feature dict onto the atlas feature_order (unknown keys dropped, missing=None)."""
        return [feat.get(k) for k in self.feature_order]

    def _corpus_nn_distances(self) -> list:
        out = []
        for i, z in enumerate(self._Z):
            dists = _nan_euclidean(z, self._Z)
            dists[i] = math.inf                              # exclude self
            out.append(min(dists))
        return sorted(d for d in out if math.isfinite(d))

    def _novelty_pctl_threshold(self, pctl: float = 0.9) -> float:
        if not self._nn_ref:
            return math.inf
        idx = min(len(self._nn_ref) - 1, int(pctl * len(self._nn_ref)))
        return self._nn_ref[idx]

    def companion(self, feat: dict, k: int = DEFAULT_K,
                  query_rules: Optional[set] = None, exclude_self: bool = True) -> dict:
        """Compute the descriptive companion for a query feature dict. VERDICT-INERT payload."""
        z = self._z(self._align(feat))
        dists = _nan_euclidean(z, self._Z)
        order = sorted(range(len(dists)), key=lambda i: dists[i])
        # drop exact-self / zero-distance duplicates (a target present in its own atlas)
        if exclude_self:
            order = [i for i in order if dists[i] > 1e-9]
        nn = order[:k]

        analogs = [{
            "target": self.targets[i], "indication": self.indications[i],
            "archetype_label": self.labels[i], "distance": round(dists[i], 3),
        } for i in nn]

        # soft membership: inverse-distance-weighted vote over the k neighbours (NOT a hard label)
        votes: dict = {}
        for i in nn:
            w = 1.0 / (dists[i] + 1e-6)
            votes[self.labels[i]] = votes.get(self.labels[i], 0.0) + w
        tot = sum(votes.values()) or 1.0
        membership = {kk: round(vv / tot, 3) for kk, vv in
                      sorted(votes.items(), key=lambda x: -x[1])}

        # missingness map: which axes are entirely unmeasured for this target (acquisition backlog)
        by_axis_total: dict = {}
        by_axis_missing: dict = {}
        for kk in self.feature_order:
            ax = kk.split("::")[0]
            by_axis_total[ax] = by_axis_total.get(ax, 0) + 1
            if feat.get(kk) is None:
                by_axis_missing[ax] = by_axis_missing.get(ax, 0) + 1
        missing_axes = sorted(ax for ax in by_axis_total
                              if by_axis_missing.get(ax, 0) == by_axis_total[ax])

        # crude novelty (nearest-neighbour distance) + a percentile flag. NOT class-relative (A3 backlog).
        nn_dist = dists[nn[0]] if nn else math.inf
        novelty = {
            "nearest_neighbour_distance": None if not math.isfinite(nn_dist) else round(nn_dist, 3),
            "flag": bool(math.isfinite(nn_dist) and nn_dist > self._novelty_pctl_threshold()),
            "metric": "global_nn_distance_CRUDE_flags_extreme_not_inconsistent",
        }

        out = {
            "verdict": None,                                 # governance: descriptive companion, never a call
            "soft_membership": membership,
            "nearest_analogs": analogs,
            "missingness": {"unmeasured_axes": missing_axes,
                            "n_features_measured": sum(1 for v in feat.values() if v is not None),
                            "n_features_total": len(self.feature_order)},
            "novelty": novelty,
            "atlas_provenance": self.meta,
            "disclaimer": (
                "DESCRIPTIVE, verdict-inert nearest-reference companion. Soft membership is a "
                "distance-weighted kNN vote, NOT a classification claim. Reference labels are "
                "PROVISIONAL and partly circular (clinical antigens; cards designed from the same "
                "biology); 'housekeeping' is not a distinct archetype and 'amp_driver' is small-n/fuzzy. "
                "Not a nomination gate. Blind/external-label held-out validation is pending (P3)."
            ),
        }
        # rule-fingerprint PRECEDENT overlay (lives on the auditable rule spine): reference targets whose
        # fired-rule signature most overlaps the query's (Jaccard). Optional — only if query_rules given.
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
            out["rule_precedent"] = [{
                "target": self.targets[i], "indication": self.indications[i],
                "archetype_label": self.labels[i], "jaccard": round(j, 3),
            } for j, i in prec[:k] if j > 0]
        return out


def companion_from_sub_results(sub_results: dict, atlas: Atlas, k: int = DEFAULT_K) -> dict:
    """Convenience: in-process fan-out results -> companion payload. The target-profile reduction-stage hook."""
    feat = vector_from_sub_results(sub_results)
    rules = fired_rule_ids_from_sub_results(sub_results)
    return atlas.companion(feat, k=k, query_rules=rules)


# =============================================================================================
# D1 NOMINATION SCORECARD — the interpretable, glass-box, ARCHETYPE-CONDITIONED nomination-readiness
# companion. VERDICT-INERT (no verdict, never a gate). Weights are ILLUSTRATIVE + SHOWN, not learned:
# each axis's z-scored position (vs the frozen corpus axis_ref) is signed (+favorable / −liability) and
# weighted by a SOFT-MEMBERSHIP blend of per-archetype weight profiles, so a surface antigen is scored on
# its OWN route (expression/selectivity/surface/safety) instead of being penalised for "not being a
# driver". The per-axis contributions are emitted for audit; the route-conditioned limiting axis feeds a
# counterfactual ("closest to nominatable except axis X"). This is D1 only — NOT the outcome-trained
# predictive score (D2, which needs a frozen model + external-outcome calibration); D2/D3 stay in the
# validation harness until their productionization is separately approved.
# =============================================================================================
SCORECARD_AXES = ["expression", "selectivity", "surface_modality", "genomic_alteration", "dependency",
                  "tractability_sm", "differentiation", "mechanism", "cis_coherence", "immune_context",
                  "combination_vulnerability", "target_intrinsic", "safety"]
AX_SIGN = {a: 1 for a in SCORECARD_AXES}
AX_SIGN["safety"] = -1          # safety = LoF-constraint LIABILITY: more constraint is worse for full-KO
DEFAULT_AX_W = 0.2              # off-route axes contribute as low-weight context, never a penalty
# per-ARCHETYPE axis-weight profiles (ILLUSTRATIVE, expert-set, SHOWN in the emitted payload)
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
# fill each profile's missing axes with the low-weight default
ARCH_W = {k: {ax: v.get(ax, DEFAULT_AX_W) for ax in SCORECARD_AXES} for k, v in ARCH_W.items()}


def _axis_scores(feat: dict) -> dict:
    """Per-axis position = mean of that axis's measured ::signal claim tiers (None if the axis is unmeasured)."""
    acc: dict = {}
    for kk, v in feat.items():
        if v is None or not kk.endswith("::signal"):
            continue
        acc.setdefault(kk.split("::")[0], []).append(v)
    return {ax: (sum(vs) / len(vs)) for ax, vs in acc.items()}


def nomination_scorecard(feat: dict, membership: dict, atlas: Atlas) -> dict:
    """Glass-box, archetype-conditioned nomination-readiness score. VERDICT-INERT.

    membership = the companion's soft archetype membership (used to BLEND the per-archetype weight
    profiles — no hard label). Returns score(0-1) + coverage + per-axis contributions + driving/limiting
    axes + a route-conditioned counterfactual. Illustrative weights are echoed in the payload."""
    if not atlas.axis_ref:
        return {"verdict": None, "score": None, "note": "atlas has no axis_ref (rebuild atlas)"}
    ascore = _axis_scores(feat)
    # z-score each axis position vs the frozen corpus reference, apply favorable/liability sign
    z = {}
    for ax in SCORECARD_AXES:
        ref = atlas.axis_ref.get(ax)
        if ref and ax in ascore:
            z[ax] = ((ascore[ax] - ref["mean"]) / (ref["std"] or 1.0)) * AX_SIGN[ax]
    # effective per-axis weight = soft-membership-weighted blend of the archetype profiles (no hard label)
    m = membership or {}
    mtot = sum(m.values()) or 1.0
    eff_w = {}
    for ax in SCORECARD_AXES:
        eff_w[ax] = sum((m.get(k, 0.0) / mtot) * ARCH_W.get(k, {}).get(ax, DEFAULT_AX_W) for k in m) \
            if m else DEFAULT_AX_W
    contrib = {ax: z[ax] * eff_w[ax] for ax in z}                 # per-axis weighted contribution (measured)
    wsum = sum(eff_w[ax] for ax in z) or 1.0
    raw = sum(contrib.values()) / wsum                            # measured-weighted mean
    score01 = 1.0 / (1.0 + math.exp(-raw))                       # squashed to 0-1 for readability (logistic)
    coverage = len(z) / len(SCORECARD_AXES)

    ordered = sorted(contrib.items(), key=lambda x: -x[1])
    driving = [{"axis": ax, "contribution": round(c, 3)} for ax, c in ordered[:3] if c > 0]
    dom = max(m, key=m.get) if m else None
    route = {ax for ax, w in ARCH_W.get(dom, {}).items() if w >= 0.8} if dom else set(SCORECARD_AXES)
    # limiting axis = lowest contribution; route-conditioned limiting = lowest among the dominant route's axes
    limiting = ordered[-1] if ordered else (None, None)
    rel = [(ax, c) for ax, c in ordered if ax in route] or ordered
    cond_limiting = min(rel, key=lambda x: x[1]) if rel else (None, None)
    cl_ax, cl_c = cond_limiting
    counterfactual = None
    if cl_ax is not None:
        gap = atlas.axis_ref.get(cl_ax, {})
        measured = cl_ax in ascore
        counterfactual = {
            "limiting_axis": cl_ax,
            "limiting_contribution": round(cl_c, 3),
            "route_conditioned": True,
            "statement": (
                f"Route-limiting axis for the {dom} route is '{cl_ax}'"
                + (f" (below the corpus mean {gap.get('mean')})." if measured
                   else " — UNMEASURED; acquiring this axis's evidence would resolve the gap.")
            ),
            "axis_measured": measured,
        }
    return {
        "verdict": None,                                         # governance: companion score, never a call
        "score": round(score01, 3),
        "coverage": round(coverage, 3),
        "dominant_archetype_soft": dom,
        "axis_contributions": {ax: round(c, 3) for ax, c in ordered},
        "driving_axes": driving,
        "limiting_axis": {"axis": limiting[0], "contribution": round(limiting[1], 3)} if limiting[0] else None,
        "counterfactual_gap": counterfactual,
        "weights_note": ("ILLUSTRATIVE expert-set weights, soft-membership-blended per-archetype (SHOWN, "
                         "not learned). Interpretable D1 layer; safety is a liability axis (sign −1)."),
        "disclaimer": ("DESCRIPTIVE, verdict-inert nomination-READINESS score. Glass-box: score = "
                       "archetype-conditioned weighted mean of z-scored axis positions vs the frozen "
                       "corpus. NOT a gate, NOT the outcome-trained predictive score, never mints a "
                       "recommendation."),
    }


def scorecard_from_sub_results(sub_results: dict, atlas: Atlas, k: int = DEFAULT_K,
                               companion: Optional[dict] = None) -> dict:
    """Convenience: in-process fan-out results -> D1 scorecard. Reuses a precomputed companion's
    soft_membership if given (avoids recomputing), else derives it."""
    feat = vector_from_sub_results(sub_results)
    membership = (companion or {}).get("soft_membership")
    if membership is None:
        membership = atlas.companion(feat, k=k).get("soft_membership")
    return nomination_scorecard(feat, membership, atlas)
