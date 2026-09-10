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
CLAIM_SIG_ORD = {
    "strong": 3.0,
    "moderate": 2.0,
    "weak": 1.0,
    "absent": 0.0,
    "negative": 0.0,
    "unmeasured": None,
    "none": None,
}
CLAIM_CORR_ORD = {
    "high": 3.0,
    "moderate": 2.0,
    "low": 1.0,
    "absent": 0.0,
    "negative": 0.0,
    "unmeasured": None,
    "none": None,
}

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


def _claim_vector_from_report(skill_report: dict) -> dict:
    """Reconstruct the {CLAIM: {signal, corroboration}} shape `claim_features` expects from a
    skill_report's `claim_chips` (the SPINE). A chip is a projection of a claim_vector atom, so the two
    coordinate systems are identical: chip.key -> CLAIM, chip.signal/corroboration -> the atom's. This
    lets the archetype vectoriser read the wired skill_report[] spine rather than the raw claim_vector
    reach-in (contract §100-128)."""
    out: dict = {}
    for chip in skill_report.get("claim_chips") or []:
        if isinstance(chip, dict) and chip.get("key") is not None:
            out[chip["key"]] = {"signal": chip.get("signal"), "corroboration": chip.get("corroboration")}
    return out


def vector_from_sub_results(sub_results: dict) -> dict:
    """Build the query feature dict from the in-process fan-out `sub_results` (dict short -> r).

    Reads each sub-skill's claim vector FROM THE skill_report[] spine (`synthesis_facet.skill_report.
    claim_chips`), falling back to the legacy `synthesis_facet.claim_vector` for a result that carries no
    report (e.g. the composed subtype tier). Byte-identical to the former claim_vector read — chips are a
    lossless projection of the claim_vector atoms — but sourced from the wired spine (contract §100-128)."""
    cvs = {}
    for short, r in (sub_results or {}).items():
        if not isinstance(r, dict):
            continue
        facet = r.get("synthesis_facet") or {}
        sr = facet.get("skill_report")
        cv = _claim_vector_from_report(sr) if isinstance(sr, dict) else None
        if not cv:  # no report / no chips → legacy fallback
            cv = facet.get("claim_vector")
        if isinstance(cv, dict) and cv:
            cvs[short] = cv
    # NUMERIC substrate (Phase 1d): merge polarity-signed numeric features + missingness masks harvested from
    # the SAME sub_results (each sub-skill's cards[].summary + synthesis_facet.claim_vector atom.values), so
    # the runtime query vector matches what build_atlas freezes (offline==runtime). Additive + byte-stable
    # against the current frozen atlas: feature_order has no numeric keys yet, so _align_z_impute drops them
    # until a re-freeze admits them. Local import avoids a module-load cycle (feature_vectoriser imports
    # claim_features from this module).
    from _skills_common.feature_vectoriser import build_feature_vector, numeric_values_from_sub_results

    return build_feature_vector(cvs, numeric_values_from_sub_results(sub_results))


def fired_rule_ids_from_sub_results(sub_results: dict) -> set:
    """The union of fired rule_ids across sub-skills — the auditable rule-fingerprint of a target.

    Reads each sub-skill's fired set FROM THE skill_report[] spine (`skill_report.provenance.
    fired_rule_ids`), falling back to the raw `fired` list for a result without a report (the subtype
    tier). Byte-identical union — the report's fired_rule_ids are the rule_ids of the same `fired`."""
    hits: set = set()
    for r in (sub_results or {}).values():
        if not isinstance(r, dict):
            continue
        sr = (r.get("synthesis_facet") or {}).get("skill_report")
        rule_ids = ((sr or {}).get("provenance") or {}).get("fired_rule_ids") if isinstance(sr, dict) else None
        if rule_ids:
            hits.update(rid for rid in rule_ids if rid)
        else:  # no report → legacy fired fallback
            for f in r.get("fired") or []:
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
        # data-derived dominant phenotype per corpus target (anchored-mixture argmax at build) — used to
        # DISPLAY a meaningful analog label where the curated panel label is "?" (marked with a trailing ~).
        self.soft_labels: list = list(doc.get("soft_labels", ["?"] * len(self.targets)))
        self.rule_fingerprints: list = doc.get("rule_fingerprints", [[] for _ in self.targets])
        self.axis_ref: dict = doc.get("axis_ref", {})
        emb = doc.get("embedding") or {}
        self.components: list = emb.get("components", [])  # m x d PCA loadings
        self.corpus_emb: list = emb.get("corpus", [])  # n x m reference coords
        self.anchors: list = doc.get("anchors", [])  # [{label,target,indication,coord}]
        self.meta: dict = doc.get("meta", {})
        # corpus nearest-neighbour distance distribution (in embedding) for the local-density novelty flag
        self._nn_ref = self._corpus_nn_distances()
        # corpus hull-residual distributions for the novelty threshold — computed ONCE at load (not per
        # companion() call): each residual is an anchored-membership solve, so recomputing it every call
        # made companion O(n) and a portfolio scan O(n^2). Cached here → companion() is O(1) in the corpus.
        # Build BOTH the absolute hull residual (legacy) and the scale-invariant RELATIVE residual in one
        # pass; the relative one drives inconsistent_flag (fixes extreme-but-canonical false novelty).
        _hulls, _rels = [], []
        for c in self.corpus_emb:
            h = self._membership_hull(c)
            _hulls.append(h)
            _rels.append(self._relative_residual(c, h))
        self._hull_ref = sorted(_hulls)
        self._rel_ref = sorted(_rels)
        self._hull_thr = (
            self._hull_ref[min(len(self._hull_ref) - 1, int(0.9 * len(self._hull_ref)))] if self._hull_ref else math.inf
        )
        self._rel_thr = (
            self._rel_ref[min(len(self._rel_ref) - 1, int(0.9 * len(self._rel_ref)))] if self._rel_ref else math.inf
        )
        # rule-fingerprint IDF (rarity weighting for the precedent overlay): a common rung (fires for
        # nearly every target) is near-uninformative; a rare rung is a strong precedent signal. Weighted
        # Jaccard with these weights stops precedent being dominated by ubiquitous rungs.
        n_corp = max(len(self.rule_fingerprints), 1)
        df: dict = {}
        for rf in self.rule_fingerprints:
            for r in set(rf):
                df[r] = df.get(r, 0) + 1
        self._rule_idf = {r: math.log((n_corp + 1.0) / (d + 1.0)) + 1.0 for r, d in df.items()}

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

        Returns (weights_by_label: dict, hull_residual: float, recon: list). Labels reuse the archetype
        vocabulary. `recon` = the anchor-hull reconstruction of e (used for the scale-invariant novelty
        metric — an EXTREME-but-consistent target reconstructs in the same DIRECTION, only larger)."""
        Z = [a["coord"] for a in self.anchors]
        k = len(Z)
        if not k:
            return {}, math.inf, [0.0] * len(e)
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
            votes[a["label"]] = votes.get(a["label"], 0.0) + w[j]  # collapse duplicate-label anchors
        return {kk: round(vv, 3) for kk, vv in sorted(votes.items(), key=lambda x: -x[1])}, hull, recon

    @staticmethod
    def _relative_residual(e: list, hull: float) -> float:
        """Scale-invariant novelty: hull residual / ||e||. An extreme-but-canonical target (large ||e||)
        has a SMALL relative residual because its reconstruction points the same way, only larger — so it
        is no longer false-flagged 'novel' merely for being far from the origin (the EGFR failure mode)."""
        norm = math.sqrt(sum(x * x for x in e))
        return hull / norm if norm > 1e-9 else 0.0

    @staticmethod
    def _mixture_entropy(weights: dict) -> float:
        """Shannon entropy (nats) of the phenotype mixture — high = a genuine multi-phenotype BLEND,
        low = a single dominant phenotype. Distinguishes 'off-hull because multi-modal' from 'truly weird'."""
        ws = [w for w in weights.values() if w > 0]
        return -sum(w * math.log(w) for w in ws) if ws else 0.0

    def companion(
        self,
        feat: dict,
        k: int = DEFAULT_K,
        query_rules: Optional[set] = None,
        exclude_self: bool = True,
        with_uncertainty: bool = True,
    ) -> dict:
        """Descriptive phenotype-landscape companion for a query feature dict. VERDICT-INERT payload.

        with_uncertainty runs the axis-jackknife mixture-stability band (default on); pass False on hot
        paths that only need soft_membership (e.g. the scorecard's internal companion call)."""
        e = self._embed(feat)
        # nearest analogs in the embedding — DEDUPED BY TARGET (keep the nearest occurrence) so a target
        # present in several indications no longer floods the list (the "KRAS, KRAS, KRAS" artifact).
        dists = [math.sqrt(sum((x - y) ** 2 for x, y in zip(e, c))) for c in self.corpus_emb]
        order = sorted(range(len(dists)), key=lambda i: dists[i])
        if exclude_self:
            # SELF_EPS tolerates the atlas's 6-dp coord rounding (a self-query lands at ~1e-5, not exactly 0);
            # far below the real inter-target spacing (>~5 in this embedding), so only self / exact
            # duplicates are dropped, never a genuine neighbour.
            order = [i for i in order if dists[i] > 1e-3]
        nn, _seen_targets = [], set()
        for i in order:
            if self.targets[i] in _seen_targets:
                continue
            _seen_targets.add(self.targets[i])
            nn.append(i)
            if len(nn) >= k:
                break

        # analog label: curated panel label when present; else the data-derived soft label (trailing "~")
        def _analog_label(i):
            return self.labels[i] if self.labels[i] not in ("?", "", None) else f"{self.soft_labels[i]}~"

        analogs = [
            {
                "target": self.targets[i],
                "indication": self.indications[i],
                "archetype_label": _analog_label(i),
                "label_is_derived": self.labels[i] in ("?", "", None),
                "distance": round(dists[i], 3),
            }
            for i in nn
        ]

        membership, hull, _recon = self._membership(e)

        # missingness map (acquisition backlog): axes entirely unmeasured for this target
        by_tot: dict = {}
        by_missing: dict = {}
        for kk in self.feature_order:
            ax = kk.split("::")[0]
            by_tot[ax] = by_tot.get(ax, 0) + 1
            if feat.get(kk) is None:
                by_missing[ax] = by_missing.get(ax, 0) + 1
        missing_axes = sorted(ax for ax in by_tot if by_missing.get(ax, 0) == by_tot[ax])

        # novelty: SCALE-INVARIANT relative hull-residual (INCONSISTENT with any canonical mix) + a
        # multi-modal descriptor + local-density flag. The inconsistent_flag now keys off the RELATIVE
        # residual (hull/||e||) vs the corpus, so an extreme-but-canonical blend (EGFR = amp+SNV RTK) is
        # NOT flagged merely for being far from the origin — only a signature whose SHAPE fits no anchor
        # mix trips it. mixture_entropy separates 'off-hull because a genuine multi-phenotype blend' from
        # 'off-hull because truly weird'.
        nn_dist = dists[nn[0]] if nn else math.inf
        rel = self._relative_residual(e, hull) if math.isfinite(hull) else math.inf
        entropy = self._mixture_entropy(membership)
        n_modes = sum(1 for w in membership.values() if w >= 0.2)
        novelty = {
            "hull_residual": None if not math.isfinite(hull) else round(hull, 3),
            "hull_residual_relative": None if not math.isfinite(rel) else round(rel, 3),
            "inconsistent_flag": bool(math.isfinite(rel) and rel > self._rel_thr),
            "hull_residual_absolute_flag": bool(math.isfinite(hull) and hull > self._hull_thr),
            "mixture_entropy": round(entropy, 3),
            "multimodal": bool(n_modes >= 2),
            "n_dominant_phenotypes": n_modes,
            "nearest_neighbour_distance": None if not math.isfinite(nn_dist) else round(nn_dist, 3),
            "local_density_flag": bool(math.isfinite(nn_dist) and nn_dist > self._novelty_threshold()),
            "metric": (
                "inconsistent_flag=relative_hull_residual(hull/||e||)_vs_corpus_p90 "
                "(scale-invariant, extreme!=novel); multimodal=>=2 anchors at >=0.2; "
                "nn_distance=local_density"
            ),
        }

        out = {
            "verdict": None,  # governance: descriptive companion, never a call
            "phenotype_mixture": membership,  # convex membership to canonical anchors
            "soft_membership": membership,  # alias (D1 scorecard consumes this key)
            "nearest_analogs": analogs,
            "missingness": {
                "unmeasured_axes": missing_axes,
                "n_features_measured": sum(1 for v in feat.values() if v is not None),
                "n_features_total": len(self.feature_order),
            },
            "mixture_uncertainty": (
                self._mixture_uncertainty(feat, membership)
                if with_uncertainty
                else {"stability": None, "note": "not computed (with_uncertainty=False)"}
            ),
            "novelty": novelty,
            "anchors": [
                {"label": a["label"], "target": a["target"], "indication": a["indication"]} for a in self.anchors
            ],
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
            # IDF-WEIGHTED Jaccard: rare rungs (high IDF) dominate the precedent match, so a shared
            # ubiquitous rung no longer inflates overlap. Falls back to unit weights for rules unseen in
            # the corpus. Plain jaccard retained alongside for continuity/auditability.
            def _idf(r):
                return self._rule_idf.get(r, 1.0)

            prec = []
            for i, rf in enumerate(self.rule_fingerprints):
                rs = set(rf)
                if not rs:
                    continue
                inter_set = query_rules & rs
                union_set = query_rules | rs
                wj = sum(_idf(r) for r in inter_set) / (sum(_idf(r) for r in union_set) or 1.0)
                j = len(inter_set) / (len(union_set) or 1)
                if wj > 0:
                    prec.append((wj, j, i, sorted(inter_set, key=_idf, reverse=True)[:3]))
            prec.sort(key=lambda x: -x[0])
            out["rule_precedent"] = [
                {
                    "target": self.targets[i],
                    "indication": self.indications[i],
                    "archetype_label": self.labels[i],
                    "weighted_jaccard": round(wj, 3),
                    "jaccard": round(j, 3),
                    "top_shared_rules": shared,
                }
                for wj, j, i, shared in prec[:k]
            ]
        return out

    def _membership_hull(self, e: list) -> float:
        """Hull residual for a corpus point (used to build the novelty reference distribution)."""
        return self._membership(e, iters=200)[1]

    def _mixture_uncertainty(self, feat: dict, full_weights: dict) -> dict:
        """Axis-jackknife stability of the phenotype mixture. Re-solves the mixture with each MEASURED
        axis dropped in turn; the spread quantifies how much the mixture leans on any single axis and how
        much the mean-imputation of missing axes could be masking. This is what turns an over-confident
        point mixture (the pre-fix EGFR failure: amp-dominant only because the SNV axis was silently 0)
        into an honestly-caveated one. Emits per-anchor [min,max] envelope + a scalar stability in [0,1]
        (1 = mixture invariant to dropping any one axis)."""
        axes = sorted({k.split("::")[0] for k, v in feat.items() if v is not None})
        labels = list(full_weights.keys())
        if len(axes) < 2 or not labels:
            return {
                "stability": 1.0,
                "per_anchor_envelope": {},
                "n_axes_jackknifed": len(axes),
                "note": "too few measured axes to jackknife",
            }
        env = {lb: [full_weights[lb], full_weights[lb]] for lb in labels}
        tvs = []
        for drop in axes:
            sub = {k: v for k, v in feat.items() if k.split("::")[0] != drop}
            w, _h, _r = self._membership(self._embed(sub))
            tvs.append(0.5 * sum(abs(w.get(lb, 0.0) - full_weights.get(lb, 0.0)) for lb in labels))
            for lb in labels:
                wl = w.get(lb, 0.0)
                env[lb][0] = min(env[lb][0], wl)
                env[lb][1] = max(env[lb][1], wl)
        stability = 1.0 - (sum(tvs) / len(tvs))  # mean total-variation distance across folds
        return {
            "stability": round(max(0.0, min(1.0, stability)), 3),
            "per_anchor_envelope": {lb: [round(env[lb][0], 3), round(env[lb][1], 3)] for lb in labels},
            "n_axes_jackknifed": len(axes),
            "note": "leave-one-axis-out jackknife; stability=1-mean(total-variation vs full mixture)",
        }


def vocabulary_drift(atlas: "Atlas", subskill_claim_vectors: dict) -> dict:
    """STALENESS guard. A live claim key absent from the FROZEN feature_order is silently mean-imputed
    (z=0) and never reaches the embedding — so a substrate change that adds/renames a claim (e.g. a new
    genomic splice class) degrades the atlas invisibly. This surfaces that: given a live set of claim
    vectors, report the feature keys present LIVE but MISSING from the atlas (→ 're-freeze the atlas').

    Returns {missing_keys, missing_axes, covered, note}. missing_keys empty ⇒ atlas vocabulary is current."""
    live = set(claim_features(subskill_claim_vectors).keys())
    frozen = set(atlas.feature_order)
    missing = sorted(live - frozen)
    return {
        "missing_keys": missing,
        "missing_axes": sorted({k.split("::")[0] for k in missing}),
        "covered": not missing,
        "n_live": len(live),
        "n_frozen": len(frozen),
        "note": (
            "live claim keys absent from the frozen feature_order are dropped from the embedding; "
            "a non-empty missing_keys means the substrate drifted → re-freeze via build_atlas.py"
        ),
    }


def companion_from_sub_results(sub_results: dict, atlas: Atlas, k: int = DEFAULT_K) -> dict:
    """In-process fan-out results -> phenotype-landscape companion. The target-profile reduction hook.

    Attaches the VERDICT-INERT archetype confidence surface (archetype_confidence_caveat +
    archetype_provenance) onto the companion, so the COMPOSED target-profile facet carries them exactly as the
    standalone doc does (target-profile stores this whole dict into nomination.json.archetype_companion). Gates
    only on the already-computed companion fields → the mixture/analog/novelty NUMBERS are unchanged (only new
    caveat keys added). Best-effort: a fault degrades a caveat to None, never breaks the reduction facet."""
    feat = vector_from_sub_results(sub_results)
    rules = fired_rule_ids_from_sub_results(sub_results)
    companion = atlas.companion(feat, k=k, query_rules=rules)
    _attach_archetype_caveats(companion)
    return companion


def _attach_archetype_caveats(companion: dict, target=None, indication=None) -> dict:
    """Attach the VERDICT-INERT confidence caveat + provenance quorum onto a companion (in place). Shared by
    the composed reduction hook and the standalone run.py so both carry an identical surface. Best-effort."""
    for _fld, _fn in (
        ("archetype_confidence_caveat", archetype_confidence_caveat),
        ("archetype_provenance", archetype_provenance),
    ):
        try:
            companion[_fld] = _fn(companion, target=target, indication=indication)
        except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never break the reduction facet
            companion.setdefault("_enrichment_errors", {})[_fld] = f"{type(exc).__name__}: {exc}"
            companion[_fld] = None
    return companion


# =============================================================================================
# D1 NOMINATION SCORECARD — interpretable, glass-box, ARCHETYPE-CONDITIONED nomination-readiness companion.
# VERDICT-INERT. Consumes the phenotype MIXTURE (`soft_membership`, keyed by the archetype vocabulary) to
# blend per-archetype weight profiles, so a target is scored on its OWN phenotype route. Unchanged by the
# landscape refactor except that membership now comes from the anchored mixture.
# =============================================================================================
SCORECARD_AXES = [
    "expression",
    "selectivity",
    "surface_modality",
    "genomic_alteration",
    "dependency",
    "tractability_sm",
    "differentiation",
    "mechanism",
    "cis_coherence",
    "immune_context",
    "combination_vulnerability",
    "target_intrinsic",
    "safety",
]
AX_SIGN = {a: 1 for a in SCORECARD_AXES}
AX_SIGN["safety"] = -1
DEFAULT_AX_W = 0.2
ARCH_W = {
    "expression_surface": {
        "expression": 1.2,
        "selectivity": 1.3,
        "surface_modality": 1.4,
        "safety": 1.0,
        "immune_context": 0.6,
        "differentiation": 0.4,
        "genomic_alteration": 0.2,
        "dependency": 0.2,
        "tractability_sm": 0.2,
        "mechanism": 0.3,
    },
    "snv_driver": {
        "genomic_alteration": 1.3,
        "tractability_sm": 1.2,
        "dependency": 1.0,
        "mechanism": 0.9,
        "safety": 0.9,
        "differentiation": 0.6,
        "expression": 0.3,
        "selectivity": 0.3,
        "surface_modality": 0.2,
    },
    # fusion/rearrangement driver — genomic-driven like snv, but the actionability leans on the
    # rearrangement (a mutation-defined patient subgroup) + tractability of the fusion partner kinase.
    # Route vocabulary is forward-ready; the matching atlas anchor activates on the next re-freeze once
    # ALK/ROS1/NTRK-fusion exemplar runs exist (see build_atlas.ANCHOR_SETS).
    "fusion_driver": {
        "genomic_alteration": 1.3,
        "tractability_sm": 1.2,
        "dependency": 1.0,
        "mechanism": 0.9,
        "differentiation": 0.7,
        "safety": 0.8,
        "selectivity": 0.4,
        "expression": 0.3,
        "surface_modality": 0.2,
    },
    "amp_driver": {
        "genomic_alteration": 1.3,
        "dependency": 1.0,
        "tractability_sm": 1.0,
        "expression": 0.9,
        "surface_modality": 0.5,
        "safety": 0.8,
        "mechanism": 0.7,
        "selectivity": 0.4,
    },
    "tsg_loss": {
        "genomic_alteration": 1.1,
        "combination_vulnerability": 1.2,
        "differentiation": 0.7,
        "mechanism": 0.6,
        "dependency": 0.5,
        "tractability_sm": 0.4,
        "safety": 0.6,
        "expression": 0.2,
        "surface_modality": 0.2,
    },
    "dependency_essential": {
        "dependency": 1.4,
        "tractability_sm": 1.1,
        "mechanism": 0.9,
        "safety": 1.0,
        "differentiation": 0.5,
        "combination_vulnerability": 0.6,
        "expression": 0.3,
        "genomic_alteration": 0.4,
    },
    "control_absent": {a: 0.3 for a in SCORECARD_AXES},
    "control_housekeeping": {**{a: 0.3 for a in SCORECARD_AXES}, "safety": 1.2, "dependency": 0.5},
    "immune_checkpoint": {
        "immune_context": 1.4,
        "surface_modality": 1.0,
        "expression": 0.8,
        "selectivity": 0.8,
        "safety": 1.0,
        "differentiation": 0.6,
        "mechanism": 0.4,
        "genomic_alteration": 0.2,
        "dependency": 0.2,
        "tractability_sm": 0.2,
    },
}
ARCH_W = {k: {ax: v.get(ax, DEFAULT_AX_W) for ax in SCORECARD_AXES} for k, v in ARCH_W.items()}


def _axis_scores(feat: dict) -> dict:
    acc: dict = {}
    for kk, v in feat.items():
        if v is None or not kk.endswith("::signal"):
            continue
        acc.setdefault(kk.split("::")[0], []).append(v)
    return {ax: (sum(vs) / len(vs)) for ax, vs in acc.items()}


def _scorecard_confidence_caveat(score) -> Optional[dict]:
    """The (c) sub-inflation (VERDICT-INERT): the D1 nomination_scorecard per-archetype weights are
    ILLUSTRATIVE + SHOWN, NOT learned — so the score ORIENTS, it is NEVER a nomination-readiness verdict. Cite
    the RETIRED outcome-trained D2/D3 approval-propensity score as the cautionary tale (a LEARNED score was
    maturity/study-depth-confounded, not disease biology — corroborated by the study-attention-bias +
    outcome-label-leakage literature). Fires whenever a real score exists; None when the atlas lacks axis_ref
    (score None → byte-stable)."""
    if score is None:
        return None
    return {
        "reason": "illustrative_not_learned_orients_not_nominates",
        "tier": "context",
        "detail": (
            "The D1 readiness score is a GLASS-BOX orientation layer: a phenotype-mixture-blended "
            "weighted mean of z-scored axis positions using ILLUSTRATIVE, expert-set, SHOWN "
            "per-archetype weights (NOT learned). The NUMBER ORIENTS ('closest to nominatable except "
            "axis X'); it is NEVER a nomination-readiness verdict and never mints a recommendation. "
            "The cautionary tale is the RETIRED outcome-trained D2/D3 approval-propensity score: an "
            "ablation showed its signal was carried by advancement / study-depth (maturity-"
            "confounded — target attention is self-reinforcing and forecastable from study history, "
            "Stoeger 2018 PMID 30226837 / Edwards 2011 PMID 21307913; and outcome-trained target "
            "scores leak the 'already-known-target' label, Ferrero 2017 PMID 28851378), not disease "
            "biology, so it was removed. Do NOT read the score as a learned probability of success."
        ),
    }


def nomination_scorecard(feat: dict, membership: dict, atlas: Atlas) -> dict:
    """Glass-box, archetype-conditioned nomination-readiness score. VERDICT-INERT."""
    if not atlas.axis_ref:
        return {
            "verdict": None,
            "score": None,
            "note": "atlas has no axis_ref (rebuild atlas)",
            "scorecard_confidence_caveat": None,
        }
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
        eff_w[ax] = (
            sum((m.get(k, 0.0) / mtot) * ARCH_W.get(k, {}).get(ax, DEFAULT_AX_W) for k in m) if m else DEFAULT_AX_W
        )
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
            "limiting_axis": cl_ax,
            "limiting_contribution": round(cl_c, 3),
            "route_conditioned": True,
            "statement": (
                f"Route-limiting axis for the {dom} route is '{cl_ax}'"
                + (
                    f" (below the corpus mean {gap.get('mean')})."
                    if measured
                    else " — UNMEASURED; acquiring this axis's evidence would resolve the gap."
                )
            ),
            "axis_measured": measured,
        }
    # VALUE OF INFORMATION: for each UNMEASURED axis, how much would the readiness score rise if that
    # axis came back FAVOURABLE (a +1σ signed position)? A route-conditioned acquisition backlog, ranked —
    # the general form of counterfactual_gap (which reports only the single limiting axis). Weighted by the
    # phenotype route, so a surface antigen ranks 'acquire surface_modality' above 'acquire genomic'.
    voi = []
    for ax in SCORECARD_AXES:
        if ax in ascore:
            continue  # already measured — nothing to acquire
        w_ax = eff_w[ax]
        raw_if = (sum(contrib.values()) + w_ax * 1.0) / ((wsum + w_ax) or 1.0)
        gain = 1.0 / (1.0 + math.exp(-raw_if)) - score01
        voi.append({"axis": ax, "projected_score_gain": round(gain, 3), "route_weight": round(w_ax, 3)})
    voi.sort(key=lambda x: -x["projected_score_gain"])

    return {
        "verdict": None,
        "score": round(score01, 3),
        "coverage": round(coverage, 3),
        "dominant_archetype_soft": dom,
        "axis_contributions": {ax: round(c, 3) for ax, c in ordered},
        "driving_axes": driving,
        "limiting_axis": {"axis": limiting[0], "contribution": round(limiting[1], 3)} if limiting[0] else None,
        "counterfactual_gap": counterfactual,
        "value_of_information": voi,
        "weights_note": (
            "ILLUSTRATIVE expert-set weights, phenotype-mixture-blended per-archetype (SHOWN, "
            "not learned). Interpretable D1 layer; safety is a liability axis (sign −1)."
        ),
        # VERDICT-INERT: the score ORIENTS, it is never a nomination-readiness verdict (illustrative-not-learned
        # weights; cite the RETIRED maturity-confounded outcome-trained D2/D3 score). Nested here so BOTH the
        # standalone doc + the composed target-profile facet (scorecard_from_sub_results → this) carry it.
        "scorecard_confidence_caveat": _scorecard_confidence_caveat(round(score01, 3)),
        "disclaimer": (
            "DESCRIPTIVE, verdict-inert nomination-READINESS score. Glass-box: score = "
            "phenotype-conditioned weighted mean of z-scored axis positions vs the frozen "
            "corpus. NOT a gate, never mints a recommendation."
        ),
    }


def scorecard_from_sub_results(
    sub_results: dict, atlas: Atlas, k: int = DEFAULT_K, companion: Optional[dict] = None
) -> dict:
    """In-process fan-out results -> D1 scorecard. Reuses a precomputed companion's soft_membership."""
    feat = vector_from_sub_results(sub_results)
    membership = (companion or {}).get("soft_membership")
    if membership is None:
        membership = atlas.companion(feat, k=k, with_uncertainty=False).get("soft_membership")
    return nomination_scorecard(feat, membership, atlas)


# =============================================================================================
# ARCHETYPE CONFIDENCE SURFACE (VERDICT-INERT) — the phenotype-landscape analog of the fan-out skills'
# *_confirmation_caveat surface (surface_confirmation_caveat / partner_confirmation_caveat /
# translational_readiness_confidence_caveat). THE TRAP: the phenotype_mixture / nearest_analogs /
# rule_precedent / nomination_scorecard OVER-CALLS a REAL, literature-supported phenotype assignment /
# analogy / nomination-readiness. Five sub-inflations, all documented in SKILL.md + this arc's verified
# literature review:
#   (a) LABEL CIRCULARITY — the anchors + reference panel labels are curated + PARTLY CIRCULAR (clinical
#       antigens; cards designed from the same biology), so a nearest_analogs "most like TROP2/CDH17" can be
#       a shared-card-design artifact, not an independent biological analogy (the documented guilt-by-
#       association multifunctionality / annotation-propagation / analog-bias failure — Gillis & Pavlidis
#       2012 PMID 22479173; Schnoes 2013 PMID 23737737; Wallach & Heifets 2018 PMID 29698607). Signalled by
#       an analog whose SHOWN label is DATA-DERIVED (label_is_derived — the curated panel label was "?"), so
#       the analogy rests on a label produced by the SAME embedding.
#   (b) MISSINGNESS-DISTORTED MIXTURE — an unmeasured axis mean-imputes to 0 and silently distorts the
#       mixture (the documented EGFR amp-dominant-because-SNV-silently-0 failure); the axis-jackknife
#       mixture_uncertainty.stability band + the missingness map are the honest discriminators.
#   (c) ILLUSTRATIVE-NOT-LEARNED scorecard weights — see _scorecard_confidence_caveat.
#   (d) NOVELTY MIS-CALL — the hull-residual inconsistent_flag is a heuristic; a CONVEX-HULL residual is NOT
#       scale-invariant on its own (an extreme-but-canonical point beyond the anchor hull would false-flag),
#       which is why inconsistent_flag keys off the SCALE-INVARIANT relative residual + multimodal/entropy
#       (the standard OOD two-statistic resolution — Jackson & Mudholkar 1979; Qin 2003).
#   (e) ANCHOR PROVISIONALITY / DEFERRED FUSION — anchors curated + partly circular; fusion_driver DEFERRED
#       (a trial re-freeze bled RTK-ness into non-fusion RTKs). Surfaced in archetype_provenance.
# target-archetype is CARDLESS + verdict-INERT, so these gate ONLY on the EXISTING companion + scorecard
# fields (mixture_uncertainty.stability / missingness / soft_membership / novelty) — NO atlas re-freeze, NO
# resolver, NEVER a verdict change (there is none). SET literals (reference-drift guard), not 2-string tuples.
# =============================================================================================

# The anchor labels whose drug-target phenotype is INDEPENDENTLY biologically established (a high-stability,
# low-missingness mixture dominated by one of these is NOT an over-call — the MILDER false-demote guard):
# snv_driver (KRAS=GoF-driver), tsg_loss (VHL=TSG), amp_driver (ERBB2=amp), expression_surface (EPCAM=surface),
# dependency_essential (AURKA=dependency). The controls (control_absent / control_housekeeping),
# immune_checkpoint, and the DEFERRED fusion_driver are deliberately NOT canonical drug-target guards here.
_CANONICAL_ESTABLISHED_ANCHORS = {"snv_driver", "tsg_loss", "amp_driver", "expression_surface", "dependency_essential"}

# Calibrated (2026-09-05) against the standalone panel live reads — see the workstream concordance doc. The
# guard requires a mixture that is BOTH robust (jackknife stability) AND adequately measured AND decisively
# dominant; the sharp low-stability/missingness tier fires below the stability floor OR when too little of
# the atlas signature is measured.
_ARCH_STABILITY_FLOOR = 0.6  # mixture_uncertainty.stability in [0,1]; below = leans on a single axis
_ARCH_MEASURED_FRAC_FLOOR = 0.5  # fraction of the atlas feature_order actually measured
_ARCH_DOMINANT_MASS_FLOOR = 0.4  # dominant anchor membership mass for a "decisive" phenotype call


def _archetype_positive_substrate(companion: dict) -> bool:
    """Is there a phenotype mixture to confidence-qualify at all? True when a soft_membership exists (every
    real companion has one). An empty / malformed companion → False → caveat None (byte-stable honest degrade)."""
    return bool(
        isinstance(companion, dict) and (companion.get("soft_membership") or companion.get("phenotype_mixture"))
    )


def _archetype_mixture_facts(companion: dict) -> dict:
    """Pull the fields the caveats + provenance gate on out of a companion, once."""
    mix = companion.get("soft_membership") or companion.get("phenotype_mixture") or {}
    dom = max(mix, key=mix.get) if mix else None
    dom_mass = mix.get(dom) if dom else None
    mu = companion.get("mixture_uncertainty") or {}
    stability = mu.get("stability")
    miss = companion.get("missingness") or {}
    n_meas, n_tot = miss.get("n_features_measured"), miss.get("n_features_total")
    frac_meas = (n_meas / n_tot) if (isinstance(n_meas, (int, float)) and n_tot) else None
    unmeasured_axes = miss.get("unmeasured_axes") or []
    analogs = companion.get("nearest_analogs") or []
    top_analog = analogs[0] if analogs else None
    return {
        "mix": mix,
        "dominant_anchor": dom,
        "dominant_mass": dom_mass,
        "stability": stability,
        "frac_measured": frac_meas,
        "n_measured": n_meas,
        "n_total": n_tot,
        "unmeasured_axes": unmeasured_axes,
        "top_analog": top_analog,
    }


def archetype_confidence_caveat(companion: dict, target=None, indication=None) -> Optional[dict]:
    """CONSOLIDATED phenotype/analog-over-call vs validated-anchor confidence call (VERDICT-INERT). Precedence:
    the MILDER canonical-anchor false-demote guard (iii) FIRST (a HIGH-stability, LOW-missingness, decisively
    canonical-anchor-dominated mixture must NOT be flagged) > the SHARP low-stability / missingness-distorted
    mixture tier (i) > the SHARP analog/label-circular tier (ii) > None (a robust, adequately-measured,
    non-circular, non-canonical signature — no over-call concern). Gates on already-computed companion fields
    (mixture_uncertainty.stability / missingness / soft_membership / nearest_analogs.label_is_derived); NEVER
    moves a spine (there is none — cardless + verdict-INERT). target/indication are OPTIONAL echo (None in the
    composed path); the guard is target-agnostic so composed == standalone."""
    if not _archetype_positive_substrate(companion):
        return None
    f = _archetype_mixture_facts(companion)
    dom, dom_mass, stab, frac = f["dominant_anchor"], f["dominant_mass"], f["stability"], f["frac_measured"]

    # TIER (iii) MILDER — validated_canonical_anchor false-demote guard.
    if (
        dom in _CANONICAL_ESTABLISHED_ANCHORS
        and isinstance(stab, (int, float))
        and stab >= _ARCH_STABILITY_FLOOR
        and isinstance(frac, (int, float))
        and frac >= _ARCH_MEASURED_FRAC_FLOOR
        and isinstance(dom_mass, (int, float))
        and dom_mass >= _ARCH_DOMINANT_MASS_FLOOR
    ):
        return {
            "reason": "validated_canonical_anchor",
            "tier": "milder",
            "false_demote_guarded": True,
            "dominant_anchor": dom,
            "dominant_mass": round(dom_mass, 3),
            "stability": stab,
            "detail": (
                f"The mixture is dominated ({dom_mass:.0%}) by the canonical '{dom}' anchor with HIGH "
                f"axis-jackknife stability ({stab}) and adequate coverage ({frac:.0%} of atlas features "
                "measured). This is a ROBUST, adequately-measured read on a phenotype that is "
                "INDEPENDENTLY biologically established (KRAS=GoF-driver / VHL=TSG / ERBB2=amp / "
                "EPCAM=surface / AURKA=dependency) — NOT an over-call, do NOT demote it. The mixture "
                "remains a soft distribution, not a hard label."
            ),
        }

    # TIER (i) SHARP — low mixture stability OR missingness-distorted (the EGFR amp-dominant-because-SNV-0 mode).
    low_stability = isinstance(stab, (int, float)) and stab < _ARCH_STABILITY_FLOOR
    high_missingness = isinstance(frac, (int, float)) and frac < _ARCH_MEASURED_FRAC_FLOOR
    if low_stability or high_missingness:
        bits = []
        if low_stability:
            bits.append(
                f"the mixture is UNSTABLE (axis-jackknife stability {stab} < {_ARCH_STABILITY_FLOOR}) — "
                "dropping a single measured axis materially moves the phenotype call, so the dominant "
                f"'{dom}' phenotype leans on one axis rather than a corroborated signature"
            )
        if high_missingness:
            bits.append(
                f"only {f['frac_measured']:.0%} of the atlas signature is measured "
                f"(unmeasured axes: {', '.join(f['unmeasured_axes']) or 'n/a'}) — an unmeasured axis "
                "MEAN-IMPUTES to 0 and can silently distort the mixture (the documented EGFR "
                "amp-dominant-because-the-SNV-axis-was-silently-0 failure mode)"
            )
        return {
            "reason": "phenotype_mixture_low_stability_or_missingness_distorted",
            "tier": "sharp",
            "false_demote_guarded": False,
            "dominant_anchor": dom,
            "dominant_mass": round(dom_mass, 3) if isinstance(dom_mass, (int, float)) else None,
            "stability": stab,
            "frac_measured": round(frac, 3) if isinstance(frac, (int, float)) else None,
            "detail": (
                "The phenotype mixture is an OVER-CONFIDENT read its OWN stability/missingness does "
                "not support: " + "; ".join(bits) + ". Read the mixture_uncertainty per-anchor "
                "envelope + the missingness map, not the point mixture; acquiring the unmeasured "
                "axes is the honest resolution."
            ),
        }

    # TIER (ii) SHARP — the nearest-analog / precedent rests on a CIRCULAR (data-derived) reference label.
    top = f["top_analog"]
    if isinstance(top, dict) and top.get("label_is_derived"):
        return {
            "reason": "analog_or_label_circular",
            "tier": "sharp",
            "false_demote_guarded": False,
            "top_analog": top.get("target"),
            "top_analog_label": top.get("archetype_label"),
            "detail": (
                f"The nearest analog ('{top.get('target')}', shown as "
                f"'{top.get('archetype_label')}') carries a DATA-DERIVED label (its curated panel "
                "label was '?', so the shown label is the anchored-mixture argmax from the SAME "
                "embedding). A 'most like X' analogy resting on a label produced by the same features "
                "used to compute similarity is at risk of LABEL CIRCULARITY (guilt-by-association "
                "multifunctionality / annotation-propagation / analog bias — Gillis & Pavlidis 2012 "
                "PMID 22479173; Schnoes 2013 PMID 23737737; Wallach & Heifets 2018 PMID 29698607), "
                "not an independent biological analogy. Treat the analog as a hypothesis; confirm "
                "the similarity from evidence INDEPENDENT of the embedding."
            ),
        }

    return None  # robust, adequately-measured, curated-label, non-canonical signature → no over-call concern


def archetype_provenance(companion: dict, target=None, indication=None) -> Optional[dict]:
    """QUORUM / PROVENANCE summary for the phenotype-landscape read (VERDICT-INERT): the measured/unmeasured
    axis counts, the mixture stability scalar, the dominant anchor + its membership mass, the novelty flags,
    and the anchor-set provenance (+ the fusion_driver-DEFERRED note) — so a sharp point mixture is never
    mistaken for a robust, well-measured, non-circular signature. Companion-only (no scorecard dependency), so
    the composed facet and the standalone doc carry an identical quorum. None only on an empty/malformed
    companion (byte-stable)."""
    if not _archetype_positive_substrate(companion):
        return None
    f = _archetype_mixture_facts(companion)
    nov = companion.get("novelty") or {}
    anchors = companion.get("anchors") or []
    anchor_labels = sorted({a.get("label") for a in anchors if isinstance(a, dict) and a.get("label")})
    top = f["top_analog"] if isinstance(f["top_analog"], dict) else {}
    return {
        "n_measured_axes": f["n_measured"],
        "n_total_axes": f["n_total"],
        "frac_measured": round(f["frac_measured"], 3) if isinstance(f["frac_measured"], (int, float)) else None,
        "n_unmeasured_subskill_axes": len(f["unmeasured_axes"]),
        "unmeasured_axes": list(f["unmeasured_axes"]),
        "mixture_stability": f["stability"],
        "dominant_anchor": f["dominant_anchor"],
        "dominant_mass": round(f["dominant_mass"], 3) if isinstance(f["dominant_mass"], (int, float)) else None,
        "top_analog": top.get("target"),
        "top_analog_label_is_derived": bool(top.get("label_is_derived")),
        "novelty_inconsistent_flag": nov.get("inconsistent_flag"),
        "novelty_multimodal": nov.get("multimodal"),
        "novelty_mixture_entropy": nov.get("mixture_entropy"),
        "anchor_labels": anchor_labels,
        "n_anchors": len(anchors),
        "anchor_provenance_note": (
            "Anchors are CURATED canonical exemplars + reference panel labels are "
            "provisional and PARTLY CIRCULAR (clinical antigens; cards designed from the "
            "same biology). The fusion_driver anchor is DEFERRED — a trial re-freeze bled "
            "RTK-ness into non-fusion RTKs (SKILL.md), so a fusion-driven target has no "
            "dedicated anchor and blends into snv_driver / amp_driver."
        ),
    }
