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
