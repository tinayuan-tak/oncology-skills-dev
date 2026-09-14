#!/usr/bin/env python3
"""build_discordance_ledger — READ-ONLY aggregator over the verdict-INERT --literature lane.

PURPOSE. Every fan-out skill can attach a `decision['literature_synthesis']` block (the
opt-in `--literature` lane): per-axis `literature_read` + `agreement_vs_omics`
(agree/extends/contradicts/omics_blind/omics_unavailable) + `overall_consistency` +
`key_divergence` + `blind_spots[]`, each with citations. Nothing deterministic consumes it —
it only decorates the narrator / evidence-graph / report. This module HARVESTS that latent
signal into a ranked CANDIDATE-GAP ledger for review, joining each lane read against the
skill's deterministic sub-verdict.

GOVERNANCE / SAFETY CONTRACT (mirrors literature-risk-assessment/risk_rollup.py):
  * ESCALATE-ONLY + ANNOTATION-ONLY. The ledger is a REVIEW QUEUE. It NEVER lowers a concern,
    NEVER moves a verdict, NEVER writes into any decision/package. Literature stays
    `citable_in_nominations: false` (target-contracts RISK_ASSESSMENT_INTEGRATION.md, 2026-07-17).
  * CONTAINMENT GUARD. A `contradicts`/`discordant` read is only treated as a candidate REAL
    gap if it carries >=1 VERIFIED citation; otherwise it is classed confabulation/unverified
    (cheap to dismiss) — because the lane is an LLM read of abstracts and NOT bit-reproducible.

INPUT is a NORMALIZED HARVEST RECORD (decoupled from how the harvest is produced — a standalone
`--literature` run or an extraction from a target-profile package):
  {"target","indication","skill",
   "sub_verdict": {"gate","verdict","driving_rule_id","fired_rule_ids":[...]},
   "claim_vector": {AXIS: {"signal","corroboration",...}, ...}   # optional
   "literature_synthesis": {<lane output>},
   "_provenance": {"model_id","prompt_hash",...}}                # optional
A corpus is a JSON list of records, or a directory of per-record JSON files, or a single
record. See `load_corpus`.

OUTPUT `eval/discordance_ledger.json`: ranked rows + a per-class / per-skill summary + `covered`,
the (skill, target, indication) triples the lane ACTUALLY compared.

WHY `covered` (2026-09-12). A concordant pair yields ZERO rows, so the rows alone cannot tell
"this pair was examined and is clean" from "this pair was never in the corpus". The monitored-
cadence diff needs exactly that distinction: a baseline gap key may only be called RESOLVED if
this run actually re-examined its pair. Without `covered`, a SCOPED ledger (one skill, one panel)
diffed against a full-fleet baseline reported every other skill's key as resolved. `covered`
deliberately EXCLUDES records whose lane was skipped or errored — a failed lane examined nothing.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
from pathlib import Path
from typing import Iterable

# --- Gap taxonomy (see the plan §Component 1). Higher weight = higher review priority. -------
GAP_CALIBRATION = "calibration_gap"  # contradicts on a ground-truth target -> false-negative candidate
GAP_VERDICT_RULE = "verdict_rule_gap"  # verified contradicts -> resolver/card/method fix candidate
GAP_BLIND_SPOT = "blind_spot_gap"  # omics cannot measure the signal -> data/axis need
GAP_STALENESS = "staleness_gap"  # axis the atlas has no anchor for -> atlas session
GAP_CONFABULATION = "confabulation_or_unverified"  # unverified/non-reproducible -> discard
GAP_CONCORDANT_OVERFLAG = "concordant_over_flag"  # lane's own overall_consistency==concordant but a lone
# axis says contradicts -> internal over-flag -> demote

_SEVERITY = {
    GAP_CALIBRATION: 5,
    GAP_VERDICT_RULE: 4,
    GAP_BLIND_SPOT: 3,
    GAP_STALENESS: 2,
    GAP_CONFABULATION: 1,
    GAP_CONCORDANT_OVERFLAG: 1,  # discard tier alongside confabulation; NON-actionable, NON-sharp
}

# Axes the frozen target-archetype atlas has no anchor for (sourced from the atlas-rebuild
# exclusion allowlist: literature_context / translational_readiness / genomic SPL /
# safety PHARMACOVIGILANCE). A blind-spot on one of these routes to the atlas session, not a
# card/rule fix here.
#
# ★★CASE-033: this was a SUBSTRING MATCH ON PROSE — `_ATLAS_EXCLUDED_HINTS = ("pharmacovig",
# "splice", "exon skip", "exon-skip")` tested against `f"{assertion} {axis_key}"`. For a
# `blind_spots[]` row the assertion is `f"{signal}: {why_omics_blind}"`, and `why_omics_blind`
# routinely ENUMERATES WHAT THE PACKAGE DOES MEASURE ("the genomic-alteration omics measure
# DNA-level SNV/CN/fusion/splice…", "outside the SNV/CN/fusion/splice omics"). So the hint fired on
# the NEGATED mention of the axis. Measured on the genomic-20 re-run: all 17 `staleness_gap` rows
# matched on 'splice' and NOT ONE was about splicing (protein-IHC, 2-HG oncometabolite, non-coding
# RNA, antigen loss, drug-resistance states) — precision 0/17. And it was simultaneously VACUOUS for
# its purpose: a genuine SPL row carries `axis_key == "SPL"`, which contains none of the hints, so
# the true positive was unreachable. Cost: 17 rows demoted a severity tier AND routed to the wrong
# owner.
#
# Route on the DECLARED axis key instead. A `blind_spots[]` entry declares no axis, so it can no
# longer be atlas-excluded by wording — which is correct: prose cannot establish which axis a
# literature-only signal belongs to. Same rule as everywhere else in this repo: derive the
# population from a declaration, never from a name or a free-text match.
_ATLAS_EXCLUDED_SKILLS = {"literature-context", "translational-readiness"}
_ATLAS_EXCLUDED_AXES = {"SPL"}

_BLIND_AGREEMENTS = {"omics_blind", "omics_unavailable"}
_DISCORDANT_CONSISTENCY = {"discordant", "partially_concordant"}


def load_corpus(path: str | Path) -> list[dict]:
    """A corpus is a JSON list, a directory of per-record .json files, or a single record."""
    p = Path(path)
    if p.is_dir():
        out: list[dict] = []
        for f in sorted(p.glob("*.json")):
            doc = json.loads(f.read_text())
            out.extend(doc if isinstance(doc, list) else [doc])
        return out
    doc = json.loads(p.read_text())
    return doc if isinstance(doc, list) else [doc]


def _citation_support(citations: Iterable[dict]) -> tuple[int, int]:
    """(n_verified, n_total). A citation counts as support only when verified is truthy — the
    containment guard: an LLM may emit an unverified/fabricated PMID."""
    cits = list(citations or [])
    n_ver = sum(1 for c in cits if isinstance(c, dict) and c.get("verified"))
    return n_ver, len(cits)


def _is_atlas_excluded(skill: str, axis_key) -> bool:
    """True iff this row belongs to the atlas session rather than to a card/rule fix here.

    Keyed on the DECLARED `axis_key` (a closed vocabulary the record already carries), never on the
    assertion prose — see the CASE-033 note above `_ATLAS_EXCLUDED_AXES`."""
    if skill in _ATLAS_EXCLUDED_SKILLS:
        return True
    return isinstance(axis_key, str) and axis_key in _ATLAS_EXCLUDED_AXES


# claim-vector axis signal tiers that count as MEASURED. Per the fleet SIGNAL_ORD convention a measured
# floor (`absent`) or a wrong-direction result (`negative`) is STILL measured; only `unmeasured` / missing
# / `data_unavailable` is a genuine gap.
_UNMEASURED_SIGNALS = {None, "", "unmeasured", "data_unavailable", "not_measured"}


def _claim_atom(claim_vector, axis_key):
    """The claim-vector atom {signal, corroboration, ...} for a lane axis_key, or None. The lane's
    axis_key IS the claim-axis key (DEP/SEL/COMUT/SURVIVAL/DRUG/…). Tolerant of the two shapes seen
    across skills: a flat {AXIS: {...}} dict OR a nested {"claim_vector": {AXIS: {...}}} wrapper."""
    cv = claim_vector
    if isinstance(cv, dict) and isinstance(cv.get("claim_vector"), dict):
        cv = cv["claim_vector"]
    if not isinstance(cv, dict) or axis_key is None:
        return None
    atom = cv.get(axis_key)
    return atom if isinstance(atom, dict) else None


# ★CASE-031/032 DIRECTION: `calibration_gap`'s prose said "candidate false-negative" unconditionally, but
# a literature `contradicts` against a claim the omics ASSERTS POSITIVELY is a candidate false-POSITIVE — the
# opposite fix, and the opposite calibration assertion. All 3 sharp rows of the genomic-20 re-run are that
# direction (a cell-line `recurrently_deleted` call literature denies), so the reviewer was being pointed at a
# missing signal that does not exist. Direction is DERIVED from the claim atom, not restated: a measured
# POSITIVE tier vs a measured floor/wrong-direction (`absent`/`negative` are measured, per SIGNAL_ORD).
_POSITIVE_SIGNALS = {"weak", "moderate", "strong"}
# The producer's OWN internal-disagreement flag. `genomic_claims._cn_corroboration` returns `low` for
# "cell-line recurrent but patient tumour focal-neutral — disagreement" while `_cn_signal` still publishes
# `moderate` (CASE-031: corroboration is bidirectional, signal is one-way). When the framework has already
# flagged the disagreement, the literature contradiction is evidence about the CLAIM LAYER, not the
# calibration set — say so in the row so the reviewer routes it to the right fix.
#
# DELIBERATELY EXCLUDES `single_arm`. That rung means "measured by exactly ONE arm, so there was nothing
# to compare" — a coverage gap, not an internal disagreement. It was split out of `moderate` precisely
# because `moderate` served as the fleet-wide one-armed default (22 of 61 ClaimSpecs), and the reason it
# is not folded into `low` instead is THIS set: routing one-armed claims to `low` would mark every
# uncovered axis as a framework-internal disagreement and fabricate a sharp row per coverage gap. Only
# `low` means arms were compared and disagreed. `test_single_arm_is_not_a_disagreement` pins this.
_DISAGREEMENT_CORROBORATION = {"low"}


def _axis_measured(atom) -> "bool | None":
    """True if the claim axis carries a MEASURED signal, False if positively unmeasured, None if there
    is no matching claim atom (then we cannot check → trust the lane, preserving prior behavior)."""
    if not isinstance(atom, dict):
        return None
    return atom.get("signal") not in _UNMEASURED_SIGNALS


def _classify(
    agreement: str,
    n_verified: int,
    is_blind: bool,
    atlas_excluded: bool,
    in_calibration: bool,
    claim_measured: "bool | None",
    overall_concordant: bool = False,
    claim_signal: "str | None" = None,
    claim_corroboration: "str | None" = None,
) -> tuple[str, str]:
    """Deterministic gap-class assignment. Returns (gap_class, why).

    CLAIM-VECTOR ALIGNMENT: the literature lane compares against a per-AXIS claim signal, not the
    reduced verdict — so a `contradicts` is a real per-axis gap only when that claim axis was MEASURED.
    When the claim atom is positively UNMEASURED (claim_measured is False) the literature cannot
    contradict an absent signal → it is a blind-spot / coverage gap, not a verdict contradiction. When
    there is no matching claim atom (claim_measured is None) we cannot check and preserve prior behavior.

    CONCORDANT-OVER-FLAG CROSS-CHECK (guard-tightening, LOOP_HEALTH 'next tightening'): the lane emits its
    OWN holistic `overall_consistency` for the (target,indication,skill). When that summary is `concordant`
    — the lane itself judged literature and omics to AGREE in aggregate — an isolated axis marked
    `contradicts` is an INTERNAL over-flag (the aggregate direction already matches), not a real gap. Demote
    it below the sharp/actionable set (still emitted as a review-queue row, just non-sharp) so it stops
    inflating the dominant `dismissed_concordant` noise. We key off the lane's own summary rather than a
    claim_signal-direction heuristic BECAUSE direction alone is not separable on this corpus — `absent`+
    supporting-lit and `strong`+supporting-lit each appear in BOTH real gaps (MET/COMUT, PARP1/COND) and
    concordant noise; only the lane's `overall_consistency==concordant` isolates the noise with 0 real-gap
    collisions. Placed AFTER the UNMEASURED check so a genuine coverage gap still routes to blind-spot."""
    if is_blind:
        if atlas_excluded:
            return (
                GAP_STALENESS,
                "literature signal on an axis the frozen atlas has no anchor for (route to atlas session)",
            )
        return GAP_BLIND_SPOT, "literature reports a signal the omics in this package cannot measure (data/axis need)"
    if agreement == "contradicts":
        if n_verified < 1:
            return (
                GAP_CONFABULATION,
                "contradicts with no VERIFIED citation — non-reproducible LLM read; discard unless a source is confirmed",
            )
        if claim_measured is False:
            if atlas_excluded:
                return (
                    GAP_STALENESS,
                    "literature 'contradicts' an UNMEASURED claim axis the atlas has no anchor for (coverage/atlas)",
                )
            return (
                GAP_BLIND_SPOT,
                "literature 'contradicts' a claim axis whose omics signal is UNMEASURED — a coverage gap, not a verdict contradiction",
            )
        if overall_concordant:
            return GAP_CONCORDANT_OVERFLAG, (
                "lane's own overall_consistency is 'concordant' — an isolated axis "
                "'contradicts' against a concordant summary is an internal over-flag "
                "(literature and omics agree in aggregate); demoted below the "
                "sharp/actionable set"
            )
        direction = (
            "candidate false-POSITIVE (the omics ASSERTS this axis; literature denies it)"
            if claim_signal in _POSITIVE_SIGNALS
            else "candidate false-negative (the omics reports a measured floor; literature reports a signal)"
        )
        flagged = (
            " — and the producer ALREADY flagged this claim's corroboration `low` (internal "
            "cell-line-vs-patient disagreement), so fix the CLAIM LAYER, not the calibration set"
            if claim_corroboration in _DISAGREEMENT_CORROBORATION
            else ""
        )
        if in_calibration:
            return (
                GAP_CALIBRATION,
                f"verified literature contradicts a MEASURED claim axis on a GROUND-TRUTH target — {direction}; "
                f"anchor a calibration assertion{flagged}",
            )
        return (
            GAP_VERDICT_RULE,
            f"verified literature contradicts a MEASURED claim axis — {direction}; candidate rule/card/method gap{flagged}",
        )
    # agree / extends and not blind -> not a gap (concordant); surfaced only in summary counts.
    return "", ""


def lane_produced_a_comparison(record: dict) -> bool:
    """True iff the --literature lane actually ran and returned a synthesis for this record.

    The single source of truth for "was this pair examined": `build_rows` uses it to decide
    whether to project any rows, and `covered_scope` uses it to decide whether the pair counts as
    covered. Keeping ONE predicate is the point — if they drifted, a pair whose lane errored could
    be reported as examined-and-clean, and the diff would call its open gaps resolved.

    The RAW field is tested, not `field or {}`: a missing / None / EMPTY synthesis means the lane
    returned nothing for this pair — the same "not examined" state as an explicit `_literature_error`,
    just failing silently instead of loudly. (build_rows yielded no rows in that state anyway, having
    no axes to project, so routing it through this predicate is behaviour-preserving there and only
    makes the reason explicit.)"""
    lit = record.get("literature_synthesis")
    return (
        bool(lit) and isinstance(lit, dict) and not lit.get("_literature_skipped") and not lit.get("_literature_error")
    )


def covered_scope(records: Iterable[dict]) -> list[list[str]]:
    """The sorted (skill, target, indication) triples the lane actually compared.

    Includes CONCORDANT pairs (zero rows but genuinely examined — the whole reason this exists) and
    excludes skipped/errored pairs (no comparison happened, so nothing about them can be resolved)."""
    triples = {
        (str(r.get("skill") or r.get("skill_dir") or "?"), str(r.get("target")), str(r.get("indication")))
        for r in records
        if lane_produced_a_comparison(r)
    }
    return [list(t) for t in sorted(triples)]


def build_rows(record: dict, calibration_targets: set[str] | None = None) -> list[dict]:
    """Project one harvest record into zero-or-more candidate-gap rows. Concordant axes yield
    no row. Never mutates `record`."""
    calibration_targets = calibration_targets or set()
    lit = record.get("literature_synthesis") or {}
    if not lane_produced_a_comparison(record):
        return []
    target = record.get("target")
    indication = record.get("indication")
    skill = record.get("skill") or record.get("skill_dir") or "?"
    sv = record.get("sub_verdict") or {}
    verdict = sv.get("verdict")
    driving = sv.get("driving_rule_id")
    overall = lit.get("overall_consistency")
    key_div = lit.get("key_divergence")
    prov = record.get("_provenance") or {}
    claim_vector = record.get("claim_vector")
    in_calibration = (target or "").upper() in {t.upper() for t in calibration_targets}

    rows: list[dict] = []

    def _emit(axis_key, agreement, lit_read, assertion, confidence, citations, is_blind):
        n_ver, n_tot = _citation_support(citations)
        atlas_excluded = _is_atlas_excluded(skill, axis_key)
        # CLAIM-VECTOR ALIGNMENT: join the lane axis to its claim-vector atom (the omics signal the lane
        # actually compared against), and classify on measured-ness — not on the reduced verdict.
        atom = _claim_atom(claim_vector, axis_key) if not is_blind else None
        claim_measured = _axis_measured(atom)
        claim_signal = (atom or {}).get("signal") if isinstance(atom, dict) else None
        claim_corrob = (atom or {}).get("corroboration") if isinstance(atom, dict) else None
        gap_class, why = _classify(
            agreement,
            n_ver,
            is_blind,
            atlas_excluded,
            in_calibration,
            claim_measured,
            overall_concordant=(overall == "concordant"),
            claim_signal=claim_signal,
            claim_corroboration=claim_corrob,
        )
        if not gap_class:
            return
        rows.append(
            {
                "target": target,
                "indication": indication,
                "skill": skill,
                "axis_key": axis_key,
                "gap_class": gap_class,
                "severity": _SEVERITY[gap_class],
                "why": why,
                "agreement_vs_omics": agreement,
                "literature_read": lit_read,
                "assertion": assertion,
                "confidence": confidence,
                "overall_consistency": overall,
                "key_divergence": key_div,
                # per-AXIS claim match (the correct resolution) — the omics signal/corroboration the lane
                # compared against; `sub_verdict` is retained as CONTEXT/priority only, not the match target.
                "claim_signal": claim_signal,
                "claim_corroboration": claim_corrob,
                "claim_measured": claim_measured,
                "sub_verdict": verdict,
                "driving_rule_id": driving,
                "n_verified_citations": n_ver,
                "n_citations": n_tot,
                "confabulation_risk": (agreement == "contradicts" and n_ver < 1),
                "citations": list(citations or []),
                "in_calibration_set": in_calibration,
                "provenance": {
                    "model_id": prov.get("model_id") or lit.get("_model_id"),
                    "prompt_hash": prov.get("prompt_hash") or lit.get("_prompt_hash"),
                },
            }
        )

    for ax in lit.get("axes") or []:
        if not isinstance(ax, dict):
            continue
        agreement = ax.get("agreement_vs_omics")
        _emit(
            ax.get("axis_key"),
            agreement,
            ax.get("literature_read"),
            ax.get("assertion"),
            ax.get("confidence"),
            ax.get("citations"),
            is_blind=agreement in _BLIND_AGREEMENTS,
        )

    # blind_spots[] are literature-only signals the omics CANNOT measure by construction.
    for bs in lit.get("blind_spots") or []:
        if not isinstance(bs, dict):
            continue
        _emit(
            "blind_spot",
            "omics_blind",
            "not_addressed",
            f"{bs.get('signal', '')}: {bs.get('why_omics_blind', '')}".strip(": "),
            None,
            bs.get("citations"),
            is_blind=True,
        )

    return rows


def _corpus_fingerprint(path: str | Path) -> str:
    p = Path(path)
    h = hashlib.sha256()
    files = sorted(p.glob("*.json")) if p.is_dir() else [p]
    for f in files:
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def build_ledger(corpus_path: str | Path, calibration_targets: set[str] | None = None) -> dict:
    records = load_corpus(corpus_path)
    rows: list[dict] = []
    for rec in records:
        rows.extend(build_rows(rec, calibration_targets))
    # Rank: severity desc, then verified-citation count desc, then (skill, target) for stability.
    rows.sort(
        key=lambda r: (
            -r["severity"],
            -r["n_verified_citations"],
            str(r["skill"]),
            str(r["target"]),
            str(r["axis_key"]),
        )
    )
    by_class: dict[str, int] = {}
    by_skill: dict[str, int] = {}
    for r in rows:
        by_class[r["gap_class"]] = by_class.get(r["gap_class"], 0) + 1
        by_skill[r["skill"]] = by_skill.get(r["skill"], 0) + 1
    actionable = [r for r in rows if r["gap_class"] in (GAP_CALIBRATION, GAP_VERDICT_RULE, GAP_BLIND_SPOT)]
    covered = covered_scope(records)
    return {
        # v2.1: + `covered` (the examined (skill,target,indication) triples). v2 consumers keep working;
        # the diff degrades to a conservative rows-derived scope when the field is absent.
        "schema": "discordance_ledger/v2.1",  # claim-vector-axis aligned (per-axis claim match, not verdict)
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "corpus": str(corpus_path),
        "corpus_fingerprint": _corpus_fingerprint(corpus_path),
        "n_records": len(records),
        "n_rows": len(rows),
        "n_actionable": len(actionable),
        # SCOPE of this run: what a diff is entitled to call RESOLVED. n_covered < n_records when a
        # record's lane was skipped/errored.
        "covered": covered,
        "n_covered": len(covered),
        "summary": {"by_gap_class": by_class, "by_skill": by_skill},
        "governance": "escalate-only; annotation-only; literature not citable in nominations "
        "(RISK_ASSESSMENT_INTEGRATION.md). This ledger is a review queue.",
        "rows": rows,
    }


# The ground-truth sections whose entries are KEYED BY TARGET SYMBOL. A `contradicts` on any of
# these is a candidate against a curated outcome → calibration_gap. `known_gap_watchlist` is the
# most valuable source: documented false-negatives the framework is expected to miss today.
_CALIBRATION_SECTIONS = (
    "reference_profiles",
    "known_gap_watchlist",
    "positive_controls",
    "abstention_cases",
    "selectivity_cases",
)


def _load_calibration_targets(path: str | Path | None) -> set[str]:
    """Pull target symbols from the ground-truth sections of known_target_calibration_set.yaml.
    Those sections are DICTS keyed by target symbol (not lists of {target: ...}), so the symbol is
    the KEY. Best-effort; never raises."""
    if not path:
        return set()
    p = Path(path)
    if not p.exists():
        return set()
    try:
        import yaml  # type: ignore

        doc = yaml.safe_load(p.read_text()) or {}
    except Exception:  # noqa: BLE001 — never let ground-truth loading break the ledger
        return set()
    out: set[str] = set()
    for section in _CALIBRATION_SECTIONS:
        sec = doc.get(section)
        if isinstance(sec, dict):
            out.update(str(k) for k in sec)  # keyed-by-target (the real schema)
        elif isinstance(sec, list):  # tolerate a list-of-dicts variant
            for entry in sec:
                if isinstance(entry, dict):
                    t = entry.get("target") or entry.get("gene") or entry.get("symbol")
                    if t:
                        out.add(str(t))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", required=True, help="JSON list, directory of records, or single record")
    ap.add_argument(
        "--calibration-set", default=None, help="optional known_target_calibration_set.yaml to tag calibration_gap rows"
    )
    ap.add_argument("--out", default=None, help="write ledger JSON here (default: stdout only)")
    a = ap.parse_args(argv)
    ledger = build_ledger(a.corpus, _load_calibration_targets(a.calibration_set))
    text = json.dumps(ledger, indent=2)
    if a.out:
        Path(a.out).write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
