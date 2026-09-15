#!/usr/bin/env python3
"""target-profile — composed target profile with Tier-3 LLM narrative synthesis.

Fans out to the 15 question-answering sub-skills in SUB_SKILLS (tumor-presence,
tumor-selectivity, functional-requirement, mechanism-and-pharmacology,
genomic-alteration-profile, differentiation-landscape, tractability-small-molecule,
surface-modality-fit, immune-context, on-target-safety-liability, target-intrinsic,
cis-feature-coherence, combination-and-vulnerability, translational-readiness,
literature-context)
+ a DEFAULT-ON subtype_fit tier (strata auto-resolved from the contracts
subtype_crosswalk; --no-subtypes opts out), collects their sub-verdicts + fired
rules, then invokes Bedrock (via _skills_common.llm) with a forced structured
tool_use to produce executive_summary + tension_analysis + recommendation. The
LLM's overall_recommendation is CLAMPED by the deterministic one-directional
nomination gate. Emits target_profile.md + nomination.json + provenance, and a
timestamped run.log (stdout+stderr tee) for development + provenance.

Each sub-skill is scoped to its OWN SUB_SKILL_CARDS entry (card_id_filter), so a
card must be in a sub-skill's entry to be seen by THAT sub-skill's verdict — a
card composed only under another sub-skill is invisible here (the resolver-
dependency completeness guard in tests/ enforces this).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

# scripts/ on sys.path so the sibling tp_* modules resolve regardless of how run.py
# is loaded (tests exec it via importlib.spec_from_file_location, which does NOT add
# scripts/ to sys.path). tp_common additionally puts the skills root on the path so
# `_skills_common` is importable.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

# The 5,138-LOC composer was split into cohesive sibling modules (2026-08-16). run.py
# stays the CLI entrypoint + orchestration (main); everything else lives in the tp_*
# modules and is re-exported here so the module's public surface — and every test that
# reaches into it (run._biomarker_facet, run.SUB_SKILL_CARDS, ...) — is byte-identical.
# _skills_common symbols invoked directly by main() (modality_lens preserved from the
# pre-split import surface).
from _skills_common import synthesize_structured
from _skills_common.envelope import build_governance

# tp_render_md + tp_render_html RETIRED 2026-09-03 (Wave-3): the default md/html render path is
# report_render (PR #963); run.py no longer calls either legacy renderer. `_risk_rows_from_rollup` (the
# category/level/driver row projection) was re-homed to _skills_common/risk_projection in #970 — re-exposed
# here so `tp._risk_rows_from_rollup` stays available to the risk-parity guards that read it off this module.
from _skills_common.risk_projection import _risk_rows_from_rollup  # noqa: F401
from tp_common import *  # noqa: F401,F403
from tp_common import SKILL_NAME, SKILL_VERSION, _framework_model_version, default_subtypes
from tp_emit import *  # noqa: F401,F403
from tp_emit import assert_write_set, write_artifact
from tp_evidence_package import *  # noqa: F401,F403
from tp_evidence_package import (
    _validation_summary_from_sub_results,
    _write_evidence_package,
)
from tp_facets import *  # noqa: F401,F403
from tp_facets import (
    _actionability_mode_facet,
    _addressable_population_facet,
    _backfill_subtype_spine,
    _biomarker_facet,
    _certainty_by_axis,
    _competitor_crossref_facet,
    _cross_gate_shared_evidence,
    _deciding_axis,
    _fragility_facet,
    _heterogeneity_facet,
    _magnitude_borderline,
    _modality_conjunction_facet,
    _modality_fit_by_channel,
    _narrative_by_axis,
    _ordinal_matrix,
    _presence_facet,
    _skill_reports_by_short,
    _subtype_facet,
    build_target_call,
    build_target_coherence,
    build_target_report,
    build_target_rollup,
)
from tp_fanout import *  # noqa: F401,F403
from tp_fanout import SUB_SKILLS, _run_sub_skills, _skipped_synthesis_output
from tp_figures import *  # noqa: F401,F403
from tp_figures import emit_figures, resolve_figures_root
from tp_gates import *  # noqa: F401,F403
from tp_gates import (  # names main() calls directly
    _CONFIDENCE_RANK,
    _TIER_TO_CONFIDENCE,
    _gate_recommendation,
    _gate_scorecard,
    _hard_gates_status,
    _positive_tier,
    _positive_tier_nominates,
    abstention_lower_bound_clamp,
    derive_thesis,
    reconcile_positive_nomination,
    thesis_nomination,
)
from tp_manifest import *  # noqa: F401,F403
from tp_manifest import write_full_package, write_subskill_package
from tp_synthesis_prompt import *  # noqa: F401,F403
from tp_synthesis_prompt import (
    _METRIC_LEGEND,
    _SYSTEM_PROMPT,
    _build_synthesis_tool,
    _build_user_prompt,
    validate_synthesis_anchors,
)

# Canonical modality tokens (target-contracts vocabularies/modality.enum.yaml) + natural-language
# aliases. The gate veto-suppression + positive-tier + modality_lens all key on the canonical set, so
# an un-normalized token silently matches nothing. Keep in sync with the enum if new modalities land.
_CANONICAL_MODALITIES = frozenset(
    {
        "small_molecule",
        "degrader",
        "adc",
        "bite_tce",
        "antibody",
        "bispecific_non_tce",
        "cell_therapy",
    }
)
_MODALITY_ALIASES = {
    "sm": "small_molecule",
    "small-molecule": "small_molecule",
    "inhibitor": "small_molecule",
    "protac": "degrader",
    "glue": "degrader",
    "molecular_glue": "degrader",
    "molecular-glue": "degrader",
    "bite": "bite_tce",
    "tce": "bite_tce",
    "t-cell-engager": "bite_tce",
    "tcell_engager": "bite_tce",
    "bispecific": "bite_tce",
    "bispecific_tce": "bite_tce",
    "mab": "antibody",
    "monoclonal": "antibody",
    "naked_antibody": "antibody",
    "car-t": "cell_therapy",
    "cart": "cell_therapy",
    "car_t": "cell_therapy",
    "cart_cell": "cell_therapy",
}


def _normalize_modality(raw: str) -> Optional[str]:
    """Map a user --modality token to a canonical modality.enum.yaml value.

    Lower/strip, accept a canonical value as-is, else resolve a known alias. An UNRECOGNIZED token
    warns to stderr and returns None (dropped) — so a typo/near-miss is never a silent no-op that
    reads as an applied lens. Verdict-inert: modality only reshapes the lens, never the spine.
    """
    key = (raw or "").strip().lower().replace(" ", "_")
    if key in _CANONICAL_MODALITIES:
        return key
    if key in _MODALITY_ALIASES:
        return _MODALITY_ALIASES[key]
    print(
        f"[target-profile] WARN: --modality {raw!r} is not a recognized modality "
        f"(canonical: {sorted(_CANONICAL_MODALITIES)}); ignoring the modality lens.",
        file=sys.stderr,
    )
    return None


# The AWS account that owns the onc-compbio derived-products bucket every sub-skill reads from
# (the cbg profile → 557690623046). Overridable (comma-list) for other authorized accounts via env.
_ONC_COMPBIO_ACCOUNT_IDS = frozenset(
    a.strip() for a in os.environ.get("ONC_COMPBIO_ACCOUNT_IDS", "557690623046").split(",") if a.strip()
)


def _preflight_data_access() -> "tuple[bool, str]":
    """Best-effort probe that the ambient AWS identity can read the onc-compbio derived-products
    bucket the fan-out depends on. Uses STS get_caller_identity (a permission-free call — no
    s3:ListBucket needed, so it can't false-fail on a read-only role) and checks the resolved
    ACCOUNT against the onc-compbio account set. This precisely catches the classic trap where
    AWS_PROFILE defaults to a non-onc account (e.g. cmp-dev → 888307857004), under which every live
    card read returns empty and the whole profile silently degrades to `insufficient` with exit 0.
    Returns (ok, detail); an unresolvable identity (missing/expired creds) is also a fail. Never
    raises."""
    try:
        import boto3
        from botocore.config import Config

        ident = boto3.client(
            "sts", config=Config(connect_timeout=5, read_timeout=5, retries={"max_attempts": 2})
        ).get_caller_identity()
        acct = ident.get("Account")
    except Exception as e:  # noqa: BLE001 — any resolution failure is a preflight fail, never a crash
        return False, f"could not resolve AWS identity ({type(e).__name__}: {e})"
    prof = os.environ.get("AWS_PROFILE", "<default-chain>")
    if acct not in _ONC_COMPBIO_ACCOUNT_IDS:
        return False, (
            f"AWS identity resolves to account {acct} (AWS_PROFILE={prof}), NOT an "
            f"onc-compbio account {sorted(_ONC_COMPBIO_ACCOUNT_IDS)}"
        )
    return True, f"account {acct} (AWS_PROFILE={prof})"


# Run log (development + provenance): tee stdout+stderr to <out>/run.log. The tee lives in
# _skills_common.run_log (shared with the focused skills' dispatcher); re-exported under the
# original private names so the composer + its tests reach it as run._install_run_log / _restore_run_log.
# A full run narrates its backend via ~33 `[target-profile] …` prints (fan-out, gate firing, Bedrock
# call, figure emission, WARNs); the tee mirrors that to a timestamped, greppable run.log that travels
# with the artifact tree (listed in provenance.yaml). Verdict-inert; best-effort.
from _skills_common.run_log import install_run_log as _install_run_log
from _skills_common.run_log import restore_run_log as _restore_run_log


def _synthesize_or_degrade(system_prompt: str, user_prompt: str, tool_schema: dict) -> dict:
    """FAIL-CLOSED wrapper around the ADVISORY Tier-3 Bedrock synthesis.

    The Tier-3 narration is advisory over the deterministic verdict spine (sub-verdicts,
    recommendation gate, positive tier, scorecard) computed independently in main(). A Bedrock
    outage — BedrockAuthError (SSO/IAM), ImportError (no anthropic[bedrock]), or RuntimeError
    (model didn't use the tool) — must therefore NOT abort the run and lose the auditable
    nomination/evidence-package main() writes downstream. On ANY such failure we degrade to the
    SAME stub the --no-synthesis path uses (known-good for the downstream gate-clamp + renderers),
    tagged `_synthesis_error` so main()'s guard skips anchor-validation and the renderers surface a
    "synthesis unavailable" note. Mirrors the per-skill dispatcher's fail-soft synthesis. NEVER
    raises. VERDICT-INERT: the emitted deterministic spine is byte-identical to the --no-synthesis path.
    """
    try:
        return synthesize_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            tool_name="target_profile_synthesis",
            tool_schema=tool_schema,
        )
    except Exception as e:  # noqa: BLE001 — advisory synthesis; never break the deterministic spine
        out = _skipped_synthesis_output()
        out["_synthesis_error"] = f"{type(e).__name__}: {e}"
        print(
            f"[target-profile] WARNING: Bedrock synthesis failed ({type(e).__name__}: {e}); "
            "emitting the deterministic verdict spine WITHOUT narration (fail-closed). "
            "The nomination/verdict is unaffected.",
            file=sys.stderr,
        )
        return out


def _build_arg_parser() -> argparse.ArgumentParser:
    """Construct the target-profile CLI parser (extracted from main() for readability — byte-identical
    to the inline construction). Covers --target/--indication/--out + the subtypes/emit/ground/
    synthesize/offline/fast/machine/report-render/verdict-only flag surface."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument(
        "--subtypes",
        default=None,
        help="Comma-separated molecular subgroup ids to scope the "
        "profile to (e.g. 'MSI_H,MSS'). The subtype tier is then "
        "evaluated: a MEASURED, floor-cleared subtype that is NOT "
        "a dependency holds the nomination. DEFAULT (2026-09-11): "
        "omitting this resolves the indication's full registered "
        "stratum set from the contracts subtype_crosswalk; pass "
        "--no-subtypes for a whole-cohort-only profile.",
    )
    ap.add_argument(
        "--no-subtypes",
        action="store_true",
        help="Skip the subtype tier entirely (whole-cohort only). Overrides --subtypes. The pre-2026-09-11 default.",
    )
    ap.add_argument(
        "--modality",
        default=None,
        help="OPTIONAL post-hoc modality lens. Canonical values (modality.enum.yaml): "
        "small_molecule, degrader, adc, bite_tce, antibody, bispecific_non_tce, "
        "cell_therapy. Common aliases are normalized (e.g. bite/tce/bispecific -> "
        "bite_tce, protac/glue -> degrader, car-t -> cell_therapy); an UNKNOWN token "
        "warns and is ignored (never a silent no-op).",
    )
    ap.add_argument(
        "--release-pin",
        default=None,
        help="OPTIONAL data release_pin to STAMP into governance/provenance for "
        "reproducibility (parity with compose-dashboard). Pass-through only: "
        "target-profile reads live and does NOT auto-resolve the release — absent "
        "this flag the pin is recorded as 'unpinned' (honest, never fabricated). "
        "Auto-resolution is a deferred data-catalog follow-on.",
    )
    ap.add_argument(
        "--therapeutic-hypothesis",
        default=None,
        help="OPTIONAL therapeutic hypothesis (line-of-therapy, "
        "patient state, clinical goal). Reshapes LLM "
        "narrative; sub-verdicts unchanged.",
    )
    ap.add_argument(
        "--no-figures",
        action="store_true",
        help="VERDICT-ONLY mode: skip per-card figure emission + the interactive HTML "
        "(the 4.6MB inlined plotly.js + the figure double-read). Emits "
        "nomination.json + target_profile.md + provenance + a STATIC (no-JS) HTML. "
        "The deterministic verdict spine is byte-identical to a full run — figures "
        "never feed the verdict. Use for fast iteration / re-runs; render later via "
        "the deferred-render path. (Perf Stage 1, 2026-07-23.)",
    )
    ap.add_argument(
        "--full-package",
        action="store_true",
        help="Self-contained REVIEW bundle: a normal run PLUS the deterministic "
        "evidence_package.json + a per-sub-skill package under subskills/<short>/"
        "package.json + a MANIFEST (.json/.md) index tying every artifact together. "
        "Additive + verdict-inert; for team review where all outputs must persist in "
        "one portable tree. Pairs well with --self-contained.",
    )
    ap.add_argument(
        "--reports",
        default=None,
        metavar="PRESETS",
        help="Also emit report_render bundles from the nomination: a comma-separated list "
        "of presets (exec-brief,reviewer-dossier,deck,full), written to "
        "<out>/reports/report_<preset>.<ext>. Additive + verdict-inert + best-effort "
        "(a render failure never aborts the run). e.g. --reports exec-brief,deck",
    )
    ap.add_argument(
        "--report-backends",
        default=None,
        metavar="BACKENDS",
        help="Comma-separated backends for --reports (default: markdown,html,json; add "
        "'pptx' for a pandoc deck, 'text' for plain text).",
    )
    ap.add_argument(
        "--self-contained",
        action="store_true",
        help="Render target_profile.html as a fully OFFLINE, portable artifact: per-card "
        "figures embed as inline base64 SVG data-URIs (no interactive Plotly, no CDN "
        "fetch), so it renders in any webview / can be shared or served from S3 with "
        "no network. Default (omit) keeps the interactive Plotly+CDN embed. "
        "Verdict-inert; the .md/nomination spine is unchanged.",
    )
    # Per-sub-skill LLM narration rides the SAME default-on substrate umbrella as ground/risk/hypothesis:
    # ON by default, OFF under --no-substrate / --no-synthesis / --verdict-only / --emit. Each
    # narrator-bearing sub-skill's single-lens narration is persisted under subskills/<short>/package.json
    # (llm_synthesis). Best-effort + VERDICT-INERT (a Bedrock failure degrades to a note; the deterministic
    # spine is unaffected). No dedicated flag — the substrate umbrella governs it.
    ap.add_argument(
        "--no-synthesis",
        action="store_true",
        help="Skip the Tier-3 Bedrock LLM synthesis (executive-summary / tension / "
        "recommendation narrative). The deterministic verdict spine — sub-verdicts, "
        "recommendation gate, positive tier, deciding axis, scorecard, facets — is "
        "computed independently of the LLM and stays byte-identical to a full run. "
        "nomination.json marks llm_synthesis._synthesis_skipped; the report shows a "
        "note in place of the narrative. Removes the serial, non-cacheable network tail.",
    )
    ap.add_argument(
        "--verdict-only",
        action="store_true",
        help="Umbrella fast/CI/iteration mode: implies --no-synthesis AND --no-figures. "
        "Emits the deterministic nomination (nomination.json + a narrative-free "
        "target_profile.md + provenance) with no Bedrock call and no figure/panel "
        "render. The verdict spine is byte-identical to a full run.",
    )
    # --- rich embedded views: per-subskill narrative + literature carried into each embedded evidence_graph ---
    ap.add_argument(
        "--rich-embedded",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run each sub-skill's LLM narrative AND literature lane in the fan-out and carry "
        "them into that sub-skill's embedded evidence_graph, so the composed dashboard's "
        "embedded sub-skill views match a standalone `--synthesize --literature` run "
        "(narrative + literature axes + verified citations). DEFAULT ON. Cost: up to 14x "
        "Bedrock narration + 14x (EuropePMC/PubTator retrieval + Bedrock literature-"
        "synthesis) — use --no-rich-embedded (or --verdict-only) for a fast, Bedrock-lean "
        "run (omics-rich embedded + one top-level narrative). AUTO-OFF whenever top-level "
        "synthesis is suppressed (--no-synthesis / --verdict-only / --emit). "
        "VERDICT-INERT + display-only: the deterministic spine stays byte-identical.",
    )
    ap.add_argument(
        "--synthesize-subskills",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Override --rich-embedded for the per-subskill NARRATIVE only (embedded "
        "narrative). Default follows --rich-embedded.",
    )
    ap.add_argument(
        "--subskill-literature",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Override --rich-embedded for the per-subskill LITERATURE lane only (embedded "
        "literature axes + citations). Default follows --rich-embedded.",
    )
    ap.add_argument(
        "--subskill-literature-scope",
        choices=["all", "gating"],
        default="all",
        help="Which sub-skills run the per-subskill literature lane when enabled: 'all' "
        "(default) or 'gating' (the 8 gating axes only — cheaper).",
    )
    ap.add_argument(
        "--profile-timers",
        action="store_true",
        help="Emit per-sub-skill READ vs FIGURE-EMIT wall-clock timings to stderr "
        "(instrumentation only; zero effect on artifacts). (Perf Stage 0.)",
    )
    ap.add_argument(
        "--emit",
        choices=["nomination", "evidence-package"],
        default="nomination",
        help="Output shape. 'nomination' (default) → nomination.json + target_profile.md "
        "+ provenance (the biologist-facing narrated profile). 'evidence-package' → "
        "a deterministic, LLM-free evidence_package.json envelope (the same machine-"
        "facing shape compose-dashboard emits), assembled from the SAME per-sub-skill "
        "verdict spine. evidence-package implies --no-synthesis + --no-figures and "
        "emits no nomination.json / md / html.",
    )
    ap.add_argument(
        "--risk-assessment",
        default=None,
        type=Path,
        help="OPTIONAL: path to a literature-risk-assessment risk_assessment.json. When "
        "given, its 6-dimension literature RISK read is rendered on the HTML dashboard "
        "as a visually-separate, explicitly-labeled CONTEXT-TIER panel (non-reproducible; "
        "never a verdict input — RISK_ASSESSMENT_INTEGRATION.md §4). Display-only.",
    )
    ap.add_argument(
        "--grounded-dir",
        default=None,
        type=Path,
        help="OPTIONAL: directory of per-axis grounded_<axis>.json records "
        "(literature-risk-assessment/ground_axis). Each subskill section whose axis has "
        "a record shows its escalate-only, PMID-cited literature findings inline. "
        "Display-only; never a verdict input.",
    )
    ap.add_argument(
        "--ground",
        nargs="?",
        const="engine",
        default=None,
        metavar="AXES",
        help="AUTO-GROUND (fanout-integration): after the fan-out, run "
        "literature-risk-assessment/ground_axis over the assembled evidence_package to "
        "PRODUCE per-axis grounded_<axis>.json (escalate-only, PMID-cited literature "
        "findings) in --out — feeding BOTH the inline HTML render AND downstream "
        "--substrate (risk_rollup [3A] + cross-evidence-hypothesis [3B]). Value: "
        "'engine' (default: the 5 engine axes), 'all' (+ clinical/commercial "
        "pseudo-cards), or a comma-list (e.g. safety,dependency). Requires Bedrock + "
        "network (BEDROCK_AWS_PROFILE); VERDICT-INERT + best-effort. Off by default "
        "(a run without --ground is byte-identical + makes no network call).",
    )
    ap.add_argument(
        "--ground-indication",
        default=None,
        metavar="TERM",
        help="OPTIONAL natural-language disease term for --ground's PubMed retrieval (e.g. "
        "'colorectal cancer'). ground_axis searches PubMed by term, so an OncoTree code "
        "(--indication COADREAD) retrieves almost nothing; pass the disease name here. "
        "Defaults to --indication when omitted. Affects ONLY grounding retrieval — the "
        "fan-out / verdict spine still key on --indication.",
    )
    ap.add_argument(
        "--risk-rollup",
        default=None,
        type=Path,
        help="OPTIONAL: path to a risk_rollup.json (literature-risk-assessment/risk_rollup [3A]). "
        "Renders the DETERMINISTIC, reproducible 'Risk by category' 5R lead table (the "
        "committee glance) — modality-conditioned bins that are a pure function of the "
        "sub-verdicts; the LLM/literature never sets a bin. Display-only.",
    )
    ap.add_argument(
        "--hypothesis",
        default=None,
        type=Path,
        help="OPTIONAL: path to a cross-evidence-hypothesis hypothesis.json. When given, the "
        "gate-clamped, cited 6-part hypothesis REPLACES the original Tier-3 LLM "
        "executive-summary + tension synthesis on the HTML dashboard (the cross-evidence "
        "integrator is a meta-layer above target-profile). Display-only; the deterministic "
        "recommendation stays the header top-line.",
    )
    ap.add_argument(
        "--ab-suppress-fragility-prompt",
        action="store_true",
        help="A/B CONTROL ARM (Phase-0 certainty-layer gate): suppress the per-axis "
        "how-solid (certainty) block in the synthesis prompt only. Verdict-INERT — "
        "the fragility facet is still computed and written to nomination.json, and "
        "the deterministic recommendation/confidence spine is byte-identical; this "
        "flag changes ONLY what the LLM narration sees, so an A/B run can measure "
        "the block's effect on the prose. Not for production use.",
    )
    ap.add_argument(
        "--allow-degraded-data",
        action="store_true",
        help="Escape hatch: SKIP the data-access preflight (STS account check for the "
        "onc-compbio derived-products account). By DEFAULT a run whose AWS identity "
        "is NOT the onc-compbio account aborts non-zero — because every live card "
        "read would silently come back empty (all-`insufficient` verdicts, exit 0), "
        "which would quietly invalidate an at-scale batch. Pass this ONLY for an "
        "intentional cache-only / offline run. (env TARGET_PROFILE_SKIP_PREFLIGHT=1 "
        "has the same effect.)",
    )
    # DEFAULT-ON grounded-substrate chain (2026-08-26). After the fan-out, a full nomination run now
    # AUTO-RUNS the two-projection chain over the assembled evidence_package: ground_axis → risk_rollup
    # [3A] + the 6-dim literature risk_assessment + cross-evidence-hypothesis [3B]. All three are
    # DISPLAY-ONLY / verdict-INERT (they read the finished spine; the recommendation stays byte-stable),
    # but they require Bedrock + PubMed network and are NON-reproducible — so a default run is no longer
    # byte-identical / offline. Opt out with --no-substrate (restores the offline, network-free run), or
    # suppress one leg with --no-ground / --no-risk / --no-hypothesis. The chain is ALSO auto-skipped in
    # the offline/fast/machine modes (--no-synthesis / --verdict-only / --emit evidence-package), which
    # stay byte-identical. An explicit --ground / --risk-assessment / --risk-rollup / --hypothesis / a
    # --grounded-dir file always takes precedence over the auto-produced artifact.
    ap.add_argument(
        "--no-substrate",
        action="store_true",
        help="Opt OUT of the DEFAULT-ON grounded-substrate chain (ground_axis → risk_rollup "
        "[3A] + 6-dim literature risk_assessment + cross-evidence-hypothesis [3B]). "
        "Restores the offline, network-free, byte-identical run. The chain is "
        "display-only / verdict-INERT either way.",
    )
    ap.add_argument(
        "--no-ground",
        action="store_true",
        help="Granular opt-out: skip only the auto-grounding leg (no ground_axis PubMed "
        "retrieval). risk_rollup/hypothesis then run without grounded findings.",
    )
    ap.add_argument(
        "--no-risk",
        action="store_true",
        help="Granular opt-out: skip the risk_rollup [3A] + 6-dim literature risk_assessment "
        "legs (the hypothesis, if on, then has no --risk input).",
    )
    ap.add_argument(
        "--no-hypothesis", action="store_true", help="Granular opt-out: skip the cross-evidence-hypothesis [3B] leg."
    )
    return ap


def main() -> int:
    ap = _build_arg_parser()
    args = ap.parse_args()

    # Normalize --modality to a canonical modality.enum.yaml token. The gate's veto-suppression +
    # positive-tier keys on the canonical set {adc, bite_tce, antibody, ...}; a natural token like
    # "bite" previously flowed through raw and silently matched nothing (a NO-OP that looked applied).
    # Alias the common natural forms; an UNRECOGNIZED token WARNS and is dropped (never silent).
    if args.modality:
        args.modality = _normalize_modality(args.modality)

    # --verdict-only is the umbrella fast mode: skip BOTH the LLM synthesis tail and figure/panel
    # rendering. Both are verdict-inert, so the deterministic spine is unaffected.
    if args.verdict_only:
        args.no_synthesis = True
        args.no_figures = True

    # --emit evidence-package is a MACHINE artifact: deterministic + LLM-free by construction, and
    # never renders the nomination-oriented md/html/figures. The deterministic verdict spine it reads
    # (sub-verdicts, recommendation gate, deciding axis) is byte-identical to a nomination run.
    if args.emit == "evidence-package":
        args.no_synthesis = True
        args.no_figures = True

    args.out.mkdir(parents=True, exist_ok=True)

    # Persist a timestamped run log alongside the artifacts (dev + provenance). Installed here — as
    # soon as --out exists — so every subsequent print (WARNs, fan-out, gate, synthesis, figures) is
    # captured. Torn down before each return via _restore_run_log (and atexit as a backstop).
    _install_run_log(args.out, header={"skill": SKILL_NAME, "skill_version": SKILL_VERSION})
    print(f"[target-profile] run log → {args.out}/run.log", file=sys.stderr)

    # DATA-ACCESS PREFLIGHT (2026-08-25): every sub-skill reads its evidence from the onc-compbio
    # derived-products bucket. If the ambient AWS identity is the wrong account (the classic trap:
    # AWS_PROFILE defaults to cmp-dev, not cbg), every live read returns empty and the profile
    # silently degrades to all-`insufficient` verdicts — exit 0, no error. That would silently
    # invalidate an at-scale pressure-test batch. Fail LOUD + non-zero here so a batch driver's
    # per-row exit-code capture flags the row. Escape hatch: --allow-degraded-data or env
    # TARGET_PROFILE_SKIP_PREFLIGHT=1 (intentional cache-only / offline run). Verdict-inert — on
    # success it only logs; it never touches the fan-out or the spine.
    if not (args.allow_degraded_data or os.environ.get("TARGET_PROFILE_SKIP_PREFLIGHT")):
        _pf_ok, _pf_detail = _preflight_data_access()
        if not _pf_ok:
            print(
                "\n" + "=" * 78 + "\n[target-profile] DATA-ACCESS PREFLIGHT FAILED — aborting (exit 3).\n"
                f"  {_pf_detail}\n"
                "  Every sub-skill reads derived products from the onc-compbio bucket; without\n"
                "  access, ALL verdicts silently degrade to `insufficient` (a hollow profile).\n"
                "  FIX:   ensure the ambient AWS creds resolve to an onc-compbio account\n"
                f"         {sorted(_ONC_COMPBIO_ACCOUNT_IDS)} — e.g. a SageMaker execution role in\n"
                "         that account (no profile needed), or on a local box `export AWS_PROFILE=cbg`.\n"
                "  Offline/cache-only run? pass --allow-degraded-data to skip this check.\n" + "=" * 78,
                file=sys.stderr,
            )
            _restore_run_log()
            return 3
        print(f"[target-profile] data-access preflight OK — {_pf_detail}", file=sys.stderr)

    # OPTIONAL literature context (display-only, never verdict-affecting): the target-level 6-dim
    # risk_assessment.json + per-axis grounded_<axis>.json records from literature-risk-assessment.
    # Loaded here and passed to the HTML renderer; failures degrade to "not shown", never block a run.
    risk_assessment = None
    if args.risk_assessment:
        try:
            risk_assessment = json.loads(Path(args.risk_assessment).read_text())
        except Exception as e:  # noqa: BLE001
            print(f"[target-profile] WARN: could not read --risk-assessment: {e}", file=sys.stderr)
    risk_rollup = None
    if args.risk_rollup:
        try:
            risk_rollup = json.loads(Path(args.risk_rollup).read_text())
        except Exception as e:  # noqa: BLE001
            print(f"[target-profile] WARN: could not read --risk-rollup: {e}", file=sys.stderr)
    grounded_by_axis: dict = {}
    if args.grounded_dir and Path(args.grounded_dir).is_dir():
        for gp in sorted(Path(args.grounded_dir).glob("grounded_*.json")):
            try:
                rec = json.loads(gp.read_text())
                ax = rec.get("axis")
                if ax:
                    grounded_by_axis[ax] = rec
            except Exception as e:  # noqa: BLE001
                print(f"[target-profile] WARN: could not read {gp.name}: {e}", file=sys.stderr)
    hypothesis = None
    if args.hypothesis:
        try:
            hypothesis = json.loads(Path(args.hypothesis).read_text())
        except Exception as e:  # noqa: BLE001
            print(f"[target-profile] WARN: could not read --hypothesis: {e}", file=sys.stderr)

    # DEFAULT-ON grounded-substrate chain gating (display-only / verdict-INERT). The chain runs for a
    # full nomination run unless opted out. It is auto-SKIPPED in the offline/fast/machine modes so those
    # stay byte-identical + network-free: --no-substrate (explicit), --no-synthesis / --verdict-only
    # (which set args.no_synthesis above), and --emit evidence-package (the deterministic envelope).
    # The gating is a PURE function (tp_grounding.plan_substrate) so it is unit-testable without
    # executing main(): grounding honors an explicit --ground else defaults to the engine axes; the
    # projections [3A]/[3B] auto-produce unless suppressed OR an explicit file input already supplied the
    # artifact (file always wins, handled below). The grounded substrate feeds BOTH the inline render and
    # the two projections.
    from tp_grounding import plan_substrate

    _plan = plan_substrate(
        no_substrate=args.no_substrate,
        no_synthesis=args.no_synthesis,
        emit=args.emit,
        ground=args.ground,
        no_ground=args.no_ground,
        no_risk=args.no_risk,
        no_hypothesis=args.no_hypothesis,
    )
    substrate_chain_on = _plan["chain_on"]
    # Record on args so the artifact write-set guard (tp_emit.expected_artifacts) reads the IDENTICAL
    # substrate-chain decision that gates the evidence_package write below (run.py:764) — a default-on
    # chain emits evidence_package.json, and the guard must expect it without re-deriving the predicate.
    args.substrate_chain_on = substrate_chain_on
    run_ground, ground_spec = _plan["run_ground"], _plan["ground_spec"]
    run_risk, run_hypothesis = _plan["run_risk"], _plan["run_hypothesis"]
    if substrate_chain_on:
        print(
            f"[target-profile] grounded-substrate chain ON (ground={run_ground}, risk={run_risk}, "
            f"hypothesis={run_hypothesis}); display-only/verdict-inert, needs Bedrock+PubMed. "
            "Pass --no-substrate for an offline byte-identical run.",
            file=sys.stderr,
        )

    invoked_lenses: dict = {}
    if args.modality:
        invoked_lenses["modality"] = args.modality
    if args.therapeutic_hypothesis:
        invoked_lenses["therapeutic_hypothesis"] = args.therapeutic_hypothesis

    # 1. Fan out to sub-skills.
    print(
        f"[target-profile] Running {len(SUB_SKILLS)} sub-skills for {args.target} in {args.indication}...",
        file=sys.stderr,
    )
    # Subtype scope. DEFAULT-ON since 2026-09-11: an omitted --subtypes no longer means
    # "whole-cohort only" — it resolves the indication's registered strata from the contracts
    # crosswalk, so the subtype tier (subtype_specific_non_dependence / subtype_restricted_*)
    # gets a chance to fire on EVERY run. WHY: the tier is verdict-bearing in both directions,
    # and while it was opt-in, no published panel run ever evaluated it — a subtype-restricted
    # dependency and a subtype-specific NON-dependence both read as whole-cohort silence.
    # --no-subtypes restores the old behavior; an unregistered indication (MPN/AML) degrades to
    # whole-cohort on its own, so this is a no-op there rather than a failure.
    if args.no_subtypes:
        subtypes, subtypes_source = None, "disabled:--no-subtypes"
    elif args.subtypes:
        subtypes = [s.strip() for s in args.subtypes.split(",") if s.strip()] or None
        subtypes_source = "explicit:--subtypes"
    else:
        _auto, subtypes_source = default_subtypes(args.indication)
        subtypes = _auto or None
    print(
        f"[target-profile] subtype tier: {len(subtypes or [])} strata ({subtypes_source})"
        + (f" — {','.join(subtypes)}" if subtypes else " — whole-cohort only"),
        file=sys.stderr,
    )
    # Figure Stage 3 (offline seam activation): on a figures-emitting run, persist each card's plot_data
    # DURING resolution into figures/cards/<card_id>/ so the figure emitters render OFFLINE from it
    # instead of re-executing a SECOND live method read (the pre-2026-08-21 behavior: target-profile
    # never passed plot_data_root, so every distribution emitter fell to its live-re-execution fallback).
    # Gated on figures being emitted — under --no-figures / --verdict-only / --emit evidence-package
    # (all set args.no_figures) plot_data_root stays None and the run is byte-identical. VERDICT-INERT:
    # persistence is a side artifact of resolution; card summaries + the verdict spine are unchanged.
    plot_data_root = None
    if not args.no_figures:
        plot_data_root = resolve_figures_root(args.out)
        plot_data_root.mkdir(parents=True, exist_ok=True)
    _fanout_t0 = time.perf_counter() if args.profile_timers else 0.0
    # RICH EMBEDDED VIEWS (default on): per-subskill narrative + literature carried into each embedded
    # evidence_graph so the composed dashboard's embedded views == a standalone --synthesize --literature
    # run. Auto-OFF whenever top-level synthesis is suppressed (offline/fast modes stay Bedrock-free +
    # byte-stable). The granular --synthesize-subskills / --subskill-literature flags override the master.
    _rich = bool(args.rich_embedded) and not args.no_synthesis
    _narr = args.synthesize_subskills if args.synthesize_subskills is not None else _rich
    _subskill_narrative = (bool(_narr) or run_hypothesis) and not args.no_synthesis
    _lit = args.subskill_literature if args.subskill_literature is not None else _rich
    _subskill_literature = bool(_lit) and not args.no_synthesis
    if _subskill_literature or _subskill_narrative:
        print(
            f"[target-profile] rich embedded views: narrative={_subskill_narrative} "
            f"literature={_subskill_literature} (scope={args.subskill_literature_scope}); "
            f"needs Bedrock+network, VERDICT-INERT. Use --no-rich-embedded for a fast run.",
            file=sys.stderr,
        )
    sub_results = _run_sub_skills(
        args.target,
        args.indication,
        subtypes=subtypes,
        profile_timers=args.profile_timers,
        plot_data_root=plot_data_root,
        synthesize_subskills=_subskill_narrative,
        subskill_literature=_subskill_literature,
        subskill_literature_scope=args.subskill_literature_scope,
        synthesis_model=getattr(args, "synthesis_model", None),
    )
    if args.profile_timers:
        print(f"[perf] === fan-out total {time.perf_counter() - _fanout_t0:6.1f}s ===", file=sys.stderr)
    for short, r in sub_results.items():
        v = r["verdict"]
        verdict_str = v[0] if v else "(no verdict)"
        print(f"  - {short:15s} -> {verdict_str}", file=sys.stderr)

    # Ordinal matrix VIEW: gate × modality signals projected onto the ordinal
    # scale. Labeled, additive, NOT a verdict input (ordinal_view contract). Computed BEFORE the
    # prompt so synthesis can reason over the matrix-SLICE, not only the flat verdict
    # list; also emitted in nomination.json for downstream consumers.
    ordinal_matrix = _ordinal_matrix(sub_results)

    # Biomarker convergence facet (Q12): a deterministic, additive, verdict-inert assembly of
    # the scattered biomarker byproducts (corroboration + stratification + preferred_assay). Like the
    # ordinal matrix, computed BEFORE the prompt so synthesis can reason over it, and emitted in
    # nomination.json. One-directional: informs confidence, never mints a nominate.
    biomarker_facet = _biomarker_facet(sub_results)

    # Subtype convergence facet (integration layer): converge the three
    # subtype-grain panoramas (expression / dependency / mutation-frequency) BY molecular subtype
    # to surface cross-axis patient-selection strata. Like the biomarker facet: deterministic,
    # additive, verdict-inert; computed before the prompt so synthesis can reason over it, and
    # emitted in nomination.json. One-directional — informs confidence, never mints a nominate.
    # First back-fill each owning skill's skill_report.claim_chips_by_subtype from the resolved subtype
    # rows (fast-follow to the #953 spine re-point): the dependency + mutation-frequency subtype cards
    # resolve CENTRALLY under `subtype_fit`, so those per-skill reports would otherwise leave the slot
    # None in the composed profile. VERDICT-INERT + byte-identical — the written rows equal what
    # `_subtype_facet` reads anyway (see `_backfill_subtype_spine`); this only makes `_subtype_rows`'
    # spine-first branch fire in production and lets target_report.skill_reports carry the sub-vector.
    _backfill_subtype_spine(sub_results)
    subtype_facet = _subtype_facet(sub_results, indication=args.indication)

    # Presence cross-modal reconciliation facet (2026-08-17): tumor-presence's own deterministic
    # per-(measurement, sample_context) presence matrix + RNA→protein proxy-quality + normal-tissue
    # comparators, carried through the fan-out via its _synthesis_facet hook. Previously the fan-out
    # captured only tumor-presence's collapsed one-word verdict, so the synthesis had to re-derive the
    # cross-modal tension (RNA-high/protein-absent; tumor-high/normal-high) from raw card numbers. This
    # hands the reasoner the skill's computed reconciliation. VERDICT-INERT (presence ∉ _SHORT_TO_GATE).
    presence_facet = _presence_facet(sub_results)

    # (Wave-3 legacy-facet retirement 2026-09-03) `_selectivity_facet` (a verbatim passthrough of
    # sub_results['selectivity']['synthesis_facet']) was RETIRED: once the legacy md/html renderers were
    # gone its only reader was its own nomination key, and render_review reads the selectivity question_table
    # off the skill_report[] spine (target_report.skill_reports.selectivity). The synthesis_facet itself is
    # still carried by the fan-out + on the spine. presence_facet is KEPT here — it is still an in-memory
    # input to the synthesis prompt (a capped reconciliation facet); only its redundant nomination key drops.

    # (The former `dependency_facet` nomination key — a verbatim passthrough of
    # sub_results['dependency']['synthesis_facet'] — was RETIRED 2026-09-03 (Wave-3 legacy-facet
    # retirement): it had no consumer beyond render_review's question-table, which now reads the
    # question_table off the skill_report[] spine (target_report.skill_reports.dependency). The same
    # synthesis_facet is still carried through the fan-out at sub_results['dependency']['synthesis_facet'].)

    # Modality-conjunction facet (2026-08-18): completes the modality nomination presence can't mint —
    # the presence claim vector conjoined with the cross-lens surface / window / safety gates. Like the
    # other facets: deterministic, additive, VERDICT-INERT (never touches overall_recommendation).
    modality_conjunction = _modality_conjunction_facet(sub_results)

    # Competitor cross-reference facet (2026-08-24): the competitor-landscape VALUE-ADD. Cross-references
    # the Open Targets competitor field (carried on the differentiation facet) against the framework's own
    # surface-modality-fit verdict → competition density (crowded/white-space) + whether the framework's
    # preferred modality is VALIDATED by clinical precedent or CONTRARIAN to it + differentiation hooks.
    # DETERMINISTIC + strictly VERDICT-INERT: never touches the gate / recommendation / confidence — the
    # framework surfaces positioning hooks, the TPP author writes the claim. None when no competitor signal.
    competitor_crossref = _competitor_crossref_facet(sub_results)

    # Fragility facet (2026-08-12): verdict-inert flip-stability — the quantitative "how solid is this
    # call?" scalar. Worst-case single-rule flip-fragility over the decision-relevant axes (+ a
    # coverage floor for blind axes), computed by re-running the deterministic resolver over perturbed
    # fired-rule sets. Like the other facets: computed BEFORE the prompt, emitted in nomination.json,
    # and STRICTLY verdict-inert — it never calls the gate and never writes overall_recommendation /
    # confidence. May set a categorical `contested` flag (declarative threshold) for the reader/banner.
    fragility = _fragility_facet(sub_results, subtypes=subtypes, modality=args.modality)
    # Heterogeneity facet (2026-08-12): verdict-inert cross-context DISPERSION — does a pooled
    # verdict hide a split across comparators / assays / molecular subtypes? Companion to fragility;
    # never touches the recommendation.
    heterogeneity = _heterogeneity_facet(sub_results, subtypes=subtypes)
    # Cross-gate shared-evidence facet (verdict-inert): input cards driving >1 gate → those gate calls
    # are correlated, not independent corroboration (the measured cross-gate redundancy). Surfaced so the
    # roll-up/synthesis doesn't over-count co-firing correlated gates. Never moves the recommendation.
    cross_gate_shared_evidence = _cross_gate_shared_evidence(sub_results)
    addressable_population = _addressable_population_facet(sub_results)
    # Actionability-mode facet (2026-08-19): VERDICT-INERT selection-basis profile — cis_feature vs
    # abundance vs dependency_relational (+ mixed / insufficient), the HANDLE by which the target is
    # actioned, orthogonal to biology_axis. Post-hoc over sub_results. Graduated past the annotation-only phase: it now
    # routes render emphasis (tp_render_md) AND injects a synthesis EMPHASIS governance block
    # (tp_synthesis_prompt.format_mode_governance_block), so the prompt + prompt_hash DO change when a
    # mode is present. The DETERMINISTIC verdict spine (recommendation/confidence/gate) stays
    # byte-identical — emphasis-only, never a verdict; prompt_hash is NOT byte-stable (see design doc).
    actionability_mode = _actionability_mode_facet(sub_results, target=args.target)

    # Per-axis (strength, certainty) sidecar (CERTAINTY_MODEL): the verdict-DISJOINT reliability
    # object each opting-in sub-skill emits beside its verdict (coverage + Broad↔Sanger corroboration +
    # measured coverage-gap unknown_mass), assembled by short. VERDICT-INERT — a reliability projection
    # for the reader/panel, NEVER in sub_verdicts or the recommendation spine. {} until an axis opts in
    # (functional-requirement `dependency` is the reference axis).
    certainty_by_axis = _certainty_by_axis(sub_results)
    # The per-skill skill_report[] SPINE ({short: report}) — assembled from each sub-skill's synthesis_facet
    # so target_report can ROLL IT UP (docs/UNIFIED_OUTPUT_CONTRACT.md). Verdict-inert; the consumer that
    # closes the emitted-but-not-read gap.
    skill_reports = _skill_reports_by_short(sub_results)

    # (target_report consolidation, Wave 0) The aggregated `claim_record_shadow` nomination KEY was an
    # M1 render-equivalence-proof substrate that nothing ever consumed (empty until an axis opts in,
    # never read by any renderer / prompt / gate). Removed. The per-axis `_claim_record` hooks +
    # `_claim_record_shadow_by_axis()` STAY — they still feed `_modality_fit_by_channel` +
    # `_magnitude_borderline` (via tp_facets), which is where the shadow is actually used.

    # Per-axis NARRATIVE (interpretability layer): for every decision-relevant sub-verdict, the
    # movers / dissenters / flip_conditions / gaps / rule_sentences that re-materialise the traversal
    # the resolver distils into one token. A cheap re-projection of the fragility facet + each
    # sub_result's fired-set (no second flip scan). VERDICT-INERT — consumed by the dashboard
    # 'why this verdict' panel + the Tier-3 synthesis, never the spine.
    narrative_by_axis = _narrative_by_axis(sub_results, fragility, modality=args.modality)

    # Target-archetype COMPANION (2026-08-28): a verdict-INERT reduction-stage facet — the cross-skill
    # target-signature LANDSCAPE companion. Distils this target's composed claim-vectors into a point in the
    # frozen low-dim embedding and emits a soft PHENOTYPE MIXTURE (convex membership to curated canonical
    # anchors — never a hard label) + nearest analogs + rule-fingerprint precedent + a missingness map +
    # novelty (hull-residual = inconsistent with any canonical phenotype). DESCRIPTIVE only — never a gate,
    # never in _SHORT_TO_GATE / sub_verdicts / the resolver; emitted for the reader + Tier-3 synthesis.
    # Best-effort: a missing/unreadable atlas degrades to None so the deterministic spine is NEVER affected.
    # See skills/target-archetype/SKILL.md + _skills_common/archetype_core.py for the governance contract.
    archetype_companion = None
    # D1 NOMINATION SCORECARD: interpretable, glass-box, PHENOTYPE-CONDITIONED nomination-readiness companion
    # — per-axis z-scored position (vs the frozen corpus) × phenotype-mixture-blended per-archetype weights
    # → score + driving/limiting axes + a route-conditioned counterfactual gap. Reuses the companion's
    # phenotype mixture. DESCRIPTIVE / verdict-inert (never a gate), same governance as the companion.
    nomination_scorecard_facet = None
    # Canonical skill_report spine for the archetype facet — built from the SAME companion + scorecard via the
    # SHARED archetype_core builder, so the composed spine is byte-identical to the standalone
    # target-archetype companion.json. role=descriptive / call=None (verdict-inert). None when no companion.
    archetype_skill_report = None
    # NOTE: the former outcome-trained approval-propensity score (D2/D3) was RETIRED — an ablation showed its
    # signal was carried by advancement/study-depth features, not disease biology (the pure-biology residual
    # did not beat a genetics baseline), so the honest product is the descriptive phenotype landscape above.
    nomination_predictive_score = None
    try:
        from _skills_common import archetype_core

        _atlas_path = Path(__file__).resolve().parents[2] / "target-archetype" / "atlas" / "atlas.json"
        if _atlas_path.exists():
            _atlas = archetype_core.Atlas.load(_atlas_path)
            archetype_companion = archetype_core.companion_from_sub_results(sub_results, _atlas)
            nomination_scorecard_facet = archetype_core.scorecard_from_sub_results(
                sub_results, _atlas, companion=archetype_companion
            )
            archetype_skill_report = archetype_core.companion_skill_report(
                archetype_companion, nomination_scorecard_facet, args.target, args.indication
            )
    except Exception:
        archetype_companion = None  # verdict-inert facets — never fail the flagship on an error
        nomination_scorecard_facet = None
        archetype_skill_report = None

    # Biology-axis (resolved early so it can also MASK the per-modality view below). Curated axis +
    # plausible modalities; uncurated → axis=unknown. NEVER raises. SLOT-2 emphasis only; the
    # deterministic verdict + gate recommendation are untouched.
    from _skills_common.biology_axis import resolve_biology_axis

    axis_info = resolve_biology_axis(args.target)

    # THESIS TYPING (Step 2a). Derive the target's thesis from archetype_core's verdict-inert
    # soft_membership under the governed hard-margin rule (target_thesis.yaml), falling back to the
    # curated biology_axis lookup when ambiguous. VERDICT-INERT: emitted onto nomination.json and
    # consumed by NO gate block until Step 2b — recommendation + confidence are byte-identical.
    # `unresolved` reproduces today's gate exactly.
    thesis = derive_thesis(archetype_companion, axis_info.get("biology_axis"), sub_results=sub_results)
    print(f"[target-profile] thesis [{thesis['basis']}]: {thesis['thesis']}", file=sys.stderr)

    # M4 modality-fit-by-channel: roll up the records' modality_scope into a PER-CHANNEL favorability
    # (worst-case conjunction) so the nomination can express per-modality calls — nominable as an
    # allele-selective SM, hold as a degrader — instead of one scalar. VERDICT-INERT. The biology-axis
    # applicability MASK marks category-error channels (SM for a pure surface antigen; ADC/TCE for a
    # pure intracellular target) not_applicable_by_axis — skipped for multi_axis duals (EGFR/ERBB2/MET).
    modality_fit_by_channel = _modality_fit_by_channel(sub_results, axis_info=axis_info)

    # target_rollup.v1 + target_coherence.v1 — the VERDICT-INERT distillation layer (7-axis roll-up +
    # negative block; thesis/coherence lens). Additive keys in nomination.json; never touch the spine.
    # subtype_facet is threaded in so the roll-up can surface subtype signals prominently.
    target_rollup = build_target_rollup(sub_results, modality_fit_by_channel, subtype_facet=subtype_facet)
    target_coherence = build_target_coherence(sub_results, target_rollup)

    # M4 coarsen-magnitude: flag axes whose categorical call HARD-CUTS a continuous value that barely
    # cleared its cutpoint (knife-edge / over-precision). Read from the record's magnitude value +
    # distance_to_cut. VERDICT-INERT — a fragility signal for the reader, never the spine.
    magnitude_borderline = _magnitude_borderline(sub_results)

    # (biology_axis resolved above — it also drives the modality-fit applicability mask.)

    # 2. LLM synthesis via Bedrock (structured tool_use) — SKIPPED under --no-synthesis/--verdict-only.
    # The deterministic spine (sub-verdicts, recommendation gate, positive tier, deciding axis,
    # scorecard, facets) is computed independently below and is byte-identical whether or not
    # synthesis runs, so the skipped path emits a stub the gate clamps into + the renderers degrade
    # to a "synthesis skipped" note.
    if args.no_synthesis:
        llm_output = _skipped_synthesis_output()
        print(
            "[target-profile] --verdict-only/--no-synthesis: skipped Bedrock synthesis "
            "(deterministic verdict spine is authoritative)",
            file=sys.stderr,
        )
    else:
        print(
            f"[target-profile] Invoking Bedrock synthesis (biology_axis={axis_info['biology_axis']})...",
            file=sys.stderr,
        )
        # ABSORB (feed-only): the advisory synthesis NARRATES the deterministic 6-dim governance risk
        # roll-up. #992/#1279: FEED the GROUNDED risk_6dim so exec_summary / tension_analysis cannot omit an
        # indication-scoped HIGH-severity literature finding that CONTRADICTS a deterministic bin (the
        # KRAS-CRC non-translation crux). Grounding NEVER moves a bin (locked #937) — it only attaches
        # escalate-only findings + engine_literature_discordance, so the BINS are byte-identical to the
        # pre-grounding view; only the surfaced findings are added. Best-effort (any failure → the prompt
        # omits the findings). VERDICT-INERT.
        from tp_grounding import build_risk_6dim

        # Ground EARLY (synthesis path only) off the LEAN package (assemble_risk_package = the same
        # sub_verdicts+cards ground_axis reads), so the recommendation-gate / evidence_package-write /
        # build_target_call ordering is UNCHANGED downstream (evidence_package.json byte-stable). Skip when
        # grounding was pre-supplied (--grounded-dir already populated grounded_by_axis) or is off; the
        # post-gate auto_ground below is guarded to not re-ground. Uses a throwaway temp pkg file (not an
        # emitted artifact) so the write-set is unchanged; the real grounded_<axis>.json still land in --out.
        if run_ground and not grounded_by_axis and args.out:
            try:
                from _skills_common.risk_projection import assemble_risk_package
                from tp_grounding import auto_ground, resolve_axes

                _ground_ind = args.ground_indication or args.indication
                Path(args.out).mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as _tf:
                    json.dump(assemble_risk_package(sub_results), _tf, default=str)
                    _lean_pkg = _tf.name
                try:
                    grounded_by_axis.update(
                        auto_ground(args.target, _ground_ind, _lean_pkg, args.out, resolve_axes(ground_spec))
                    )
                finally:
                    os.unlink(_lean_pkg)
                print(
                    f"[target-profile] pre-synthesis grounding {sorted(grounded_by_axis)} → fed into the "
                    "synthesis 6-dim risk block (verdict-inert; bins unchanged)",
                    file=sys.stderr,
                )
            except Exception as e:  # noqa: BLE001 — grounding is advisory context, never blocks synthesis
                print(
                    f"[target-profile] WARN: pre-synthesis grounding failed ({type(e).__name__}: {e}); "
                    "synthesis proceeds without grounded findings",
                    file=sys.stderr,
                )

        risk_6dim_for_synthesis = build_risk_6dim(sub_results, args.modality, grounded_by_axis, out_dir=None)
        tool_schema = _build_synthesis_tool()
        user_prompt = _build_user_prompt(
            args.target,
            args.indication,
            sub_results,
            modality=args.modality,
            therapeutic_hypothesis=args.therapeutic_hypothesis,
            ordinal_matrix=ordinal_matrix,
            biomarker_facet=biomarker_facet,
            subtype_facet=subtype_facet,
            presence_facet=presence_facet,
            fragility=(None if args.ab_suppress_fragility_prompt else fragility),
            axis_info=axis_info,
            actionability_mode=actionability_mode,
            competitor_crossref=competitor_crossref,
            narrative_by_axis=narrative_by_axis,
            risk_6dim=risk_6dim_for_synthesis,
        )
        # FAIL-CLOSED: synthesis is ADVISORY narration over the deterministic spine, so a Bedrock
        # outage must NOT abort the run and lose the auditable nomination written below. Degrades to
        # the same stub the --no-synthesis path uses (see _synthesize_or_degrade).
        llm_output = _synthesize_or_degrade(_SYSTEM_PROMPT, user_prompt, tool_schema)
        # Attach the deterministic cross-cutting metric legend (sibling key) so a non-computational
        # reader has an accurate reference for the quantities cited across lenses — independent of the
        # LLM's inline glosses. On a successful narration only (a degraded/error dict stays minimal).
        if isinstance(llm_output, dict) and "_synthesis_error" not in llm_output:
            llm_output.setdefault("metric_legend", _METRIC_LEGEND)
            # Verdict-INERT audit: flag any bracketed [rule_id]/[card_id] anchors the model cited that
            # are NOT in the deterministic narrative/fired/card anchor set (possible hallucinated
            # citations). Fail-visible (records, never strips); does not touch the verdict/recommendation.
            llm_output["_anchor_validation"] = validate_synthesis_anchors(llm_output, narrative_by_axis, sub_results)
            _inv = llm_output["_anchor_validation"]["n_invented"]
            if _inv:
                print(
                    f"[target-profile] NOTE: {_inv} synthesis citation anchor(s) not in the "
                    f"narrative block (possible hallucination): "
                    f"{llm_output['_anchor_validation']['invented_anchors']}",
                    file=sys.stderr,
                )

    # 2b. Deterministic recommendation gate. A killer sub-verdict FORCES the
    # recommendation regardless of what the LLM chose — the auditable rule wins.
    # We clamp the wrapped {value, _source, ...} in place and record the override
    # in nomination.json + provenance so the gate is never silent.
    gate_action, gate_hits, gate_suppressions = _gate_recommendation(
        sub_results, modality=args.modality, biology_axis=axis_info.get("biology_axis"), thesis=thesis.get("thesis")
    )
    recommendation_gate = {"fired": bool(gate_action), "suppressed_vetoes": gate_suppressions}
    # Step 3: set only in the abstention branch below (the thesis decider is unreachable when a kill
    # fired). Initialized here so the deciding-axis router can read it unconditionally.
    thesis_record: dict | None = None
    if gate_suppressions:
        print(
            f"[target-profile] recommendation gate SUPPRESSED "
            f"{[s['short'] + ':' + s['verdict'] + ' via ' + s['suppressed_by']['kind'] for s in gate_suppressions]}",
            file=sys.stderr,
        )
    # confidence_tier is computed the SAME WAY in BOTH gate branches (2026-09-11, CDH3 review): the
    # positive tier + its supporting hits are resolved unconditionally, so the object carries an
    # identical {tier, hits} shape and meaning whether or not a kill gate fired. Previously the gated
    # branch left {"tier": None} with no `hits` key, so a vetoed run's confidence object meant something
    # different from an abstaining run's (CDH3 was the first target to publish that branch). The
    # confidence FLOOR (raising the LLM's confidence to the tier's floor) is applied ONLY on abstention
    # below — a kill gate owns the recommendation and never has its confidence RAISED — but the tier
    # itself is now reported on gated runs too (confidence and recommendation are orthogonal: one can be
    # highly confident that a target should be vetoed).
    tier, pos_hits = _positive_tier(sub_results, modality=args.modality)
    confidence_tier = {"tier": tier, "hits": pos_hits}
    if gate_action:
        rec = llm_output.get("overall_recommendation")
        llm_value = rec.get("value") if isinstance(rec, dict) else rec
        recommendation_gate = {
            "fired": True,
            "forced_recommendation": gate_action,
            "llm_recommendation": llm_value,
            "overridden": llm_value != gate_action,
            "triggered_by": gate_hits,
            "suppressed_vetoes": gate_suppressions,
        }
        if isinstance(rec, dict):
            rec["value"] = gate_action
            rec["_gated"] = True  # mark the value as rule-forced, not LLM-chosen
        else:
            llm_output["overall_recommendation"] = {"value": gate_action, "_source": "recommendation_gate"}
        print(
            f"[target-profile] recommendation GATE fired: forced '{gate_action}' "
            f"(LLM said '{llm_value}') via {[h['short'] + ':' + h['verdict'] for h in gate_hits]}",
            file=sys.stderr,
        )
        if any(h.get("_fail_closed") for h in gate_hits):
            print(
                "[target-profile] NOTE: recommendation was FAIL-CLOSED (an unrecognized/malformed "
                "verdict on a veto-capable axis routed to least-permissive — never a silent pass).",
                file=sys.stderr,
            )
    else:
        # NO kill fired (the gate ABSTAINED). Two clamps live here:
        #
        # (a) LOWER-BOUND guard — the missing pessimism half of the one-directional clamp. With no
        #     veto/hold rule fired, an LLM-authored NEGATIVE (veto/hold) has no rule behind it and
        #     nothing in the audit spine to attribute it to, so it collapses to insufficient_evidence
        #     (symmetric to "a nominate requires a positive tier"). The LLM narrative is preserved and
        #     still explains the concern; only the composed recommendation VALUE is clamped. A
        #     `nominate`/`insufficient_evidence` is not a negative and stands (nominate stays bounded
        #     above by the kill gate).
        rec = llm_output.get("overall_recommendation")
        llm_value = rec.get("value") if isinstance(rec, dict) else rec
        clamped_to, clamp_record = abstention_lower_bound_clamp(llm_value)
        if clamped_to is not None:
            recommendation_gate["lower_bound_clamp"] = clamp_record
            if isinstance(rec, dict):
                rec["value"] = clamped_to
                rec["_gated"] = True  # rule-bounded, not free LLM choice
                rec["_lower_bound_clamped"] = True
            else:
                llm_output["overall_recommendation"] = {"value": clamped_to, "_source": "abstention_lower_bound"}
            print(
                f"[target-profile] recommendation LOWER-BOUND clamp: LLM '{llm_value}' → "
                f"'{clamped_to}' (gate abstained — no veto/hold rule fired)",
                file=sys.stderr,
            )
        # (a2) THESIS DECIDER (Step 3) — evaluate the thesis's necessity conjunction. This only
        #     COMPUTES and RECORDS; the single writer at (c) decides what, if anything, is forced.
        #     F1-SAFE BY CONTROL FLOW, not by policy: this is the else-branch of the kill gate, so it
        #     is unreachable while any veto/hold (or fail-closed clamp) survives — the same argument
        #     the positive tier rests on. `thesis_nomination` re-asserts that guard on its own `hits`
        #     argument anyway. It is satisfiable only by a FAVORABLE MEASURED verdict on the thesis's
        #     deciding axis, corroborated on independent axes AND by a measured value of the thesis's
        #     ground-truth deciding-axis card field — so routing alone can never invent a GO. An
        #     unregistered thesis (incl. `unresolved` and oncogene_addiction) is a no-op.
        thesis_action, thesis_record = thesis_nomination(sub_results, thesis.get("thesis"), gate_hits)
        if thesis_record is not None:
            recommendation_gate["thesis_decider"] = thesis_record
        if thesis_record is not None and not thesis_action:
            print(
                f"[target-profile] thesis decider DECLINED for thesis "
                f"'{thesis_record['thesis']}': unsatisfied {thesis_record['unsatisfied']}",
                file=sys.stderr,
            )

        # (b) the positive tier (computed above, before the branch) raises a deterministic confidence
        #     FLOOR and, at the tier the vocab names, FORCES `nominate` (see (c)). F1-safe: this branch
        #     is unreachable when a kill fired. The tier/hits are already on confidence_tier; only the
        #     floor is abstention-scoped (a killed target is never confidence-RAISED).
        if tier:
            floor = _TIER_TO_CONFIDENCE[tier]  # strong→high, moderate→medium
            conf = llm_output.get("confidence")
            llm_conf = conf.get("value") if isinstance(conf, dict) else conf
            # Apply as a floor: never lower the LLM's confidence, only raise it.
            if _CONFIDENCE_RANK.get(floor, 0) > _CONFIDENCE_RANK.get(llm_conf, 0):
                if isinstance(conf, dict):
                    conf["value"] = floor
                    conf["_floored_by_positive_tier"] = True
                else:
                    llm_output["confidence"] = {"value": floor, "_source": "positive_tier"}
                confidence_tier["floored_from"] = llm_conf
                confidence_tier["floored_to"] = floor
            print(
                f"[target-profile] positive tier: {tier} "
                f"(dims={sorted({h['short'] for h in pos_hits})}); "
                f"confidence floor {floor}",
                file=sys.stderr,
            )
        # (c) POSITIVE NOMINATION — the SINGLE writer for both deterministic nominate paths (the
        #     positive tier from A1/vocab 1.18.0 and the thesis decider from Step 3/vocab 1.21.0).
        #     All policy — precedence, the LLM-authored-negative interlock, and the refusal to touch
        #     `recommendation_gate["fired"]` — lives in `reconcile_positive_nomination`, which is pure
        #     and unit-tested. Landing the two paths as independent writers produced a write collision,
        #     an attribution relabel, and a `fired` value that INVERTS a nomination into a kill in two
        #     downstream consumers; one writer is what prevents all three.
        #
        #     Structurally F1-safe for the same reason the floor above is: unreachable when a kill
        #     fired, so a nomination can never mask or outrank a veto/hold. Fail-closed on the vocab
        #     (a missing/broken key yields no nomination; a broken vocab cannot mint a GO).
        prior_value = rec.get("value") if isinstance(rec, dict) else rec
        forced_positive, positive_patch = reconcile_positive_nomination(
            thesis_action=thesis_action,
            thesis_record=thesis_record,
            tier=tier,
            tier_nominates=_positive_tier_nominates(tier, modality=args.modality),
            pos_hits=pos_hits,
            clamped=clamped_to is not None,
            llm_value=llm_value,
        )
        recommendation_gate.update(positive_patch)
        if forced_positive:
            if isinstance(rec, dict):
                rec["value"] = forced_positive
                rec["_gated"] = True  # rule-forced, not LLM-chosen
                if positive_patch.get("forced_by") == "thesis_decider":
                    rec["_thesis_decided"] = True
            else:
                llm_output["overall_recommendation"] = {
                    "value": forced_positive,
                    "_source": positive_patch.get("forced_by"),
                }
            print(
                f"[target-profile] POSITIVE gate FIRED [{positive_patch.get('forced_by')}]: "
                f"'{prior_value}' → '{forced_positive}' (LLM said '{llm_value}') via "
                f"{[h['short'] + ':' + h['verdict'] for h in positive_patch.get('triggered_by') or []]}",
                file=sys.stderr,
            )
            if positive_patch.get("also_reached_by"):
                print(
                    f"[target-profile] both nominate paths agree: "
                    f"{positive_patch['also_reached_by']['paths']} also reached it "
                    f"(attribution stays {positive_patch.get('forced_by')})",
                    file=sys.stderr,
                )
        elif positive_patch.get("nominate_withheld"):
            w = positive_patch["nominate_withheld"]
            print(
                f"[target-profile] nominate WITHHELD [{w['path']}]: LLM authored a rule-less negative ('{llm_value}')",
                file=sys.stderr,
            )

    # Gate-complete ceiling: attach the COMPLETE declared hard-gate set with per-gate
    # fired/suppressed/excluded/blind status. Additive — reads the resolved gate state, forces
    # nothing; flows into nomination.json + evidence_package via recommendation_gate.
    recommendation_gate["hard_gates"] = _hard_gates_status(sub_results, gate_hits, gate_suppressions)

    # Deciding-axis router: name the load-bearing gate + whether the framework can
    # evidence it. Reports (never predicts): a fired gate is the deciding axis; on abstention,
    # the unevidenced necessity gates are the routing instruction. Purely additive — reads the
    # already-resolved gate/positive state, touches no verdict.
    deciding_axis = _deciding_axis(
        sub_results,
        gate_action,
        gate_hits,
        positive_hits=confidence_tier.get("hits", []) or [],
        thesis_record=thesis_record,
    )
    print(
        f"[target-profile] deciding axis [{deciding_axis['basis']}]: {deciding_axis.get('routing', '')}",
        file=sys.stderr,
    )

    # Gate scorecard (deterministic, top-of-report): 8-gate rows from the gate registry, 4-state
    # status reusing the nomination-gate policy. Also emitted in nomination.json.
    # `thesis` is threaded for the same reason `modality` is: without it the scorecard labelled an
    # axis this run's thesis declares IRRELEVANT as `opposing`, while `hard_gates` (line ~1214, same
    # dict, same artifact) reported the very same veto as `suppressed`. Same expression as the two
    # sibling consumers above (:1040, :1125) so the three views cannot be given different theses.
    scorecard = _gate_scorecard(sub_results, deciding_axis, modality=args.modality, thesis=thesis.get("thesis"))
    # target_call.v1 (target_report consolidation, Wave 1 — ADDITIVE): a unified DECISION view composed
    # over the spine objects just built (recommendation_gate/confidence_tier/deciding_axis/scorecard) +
    # target_rollup.block, adding the authoritative recommendation value + a dissent block. Verdict-inert;
    # recommendation_gate stays the sole owner. The spine keys remain top-level until renderers migrate.
    target_call = build_target_call(
        recommendation_gate,
        confidence_tier,
        deciding_axis,
        scorecard,
        overall_recommendation=llm_output.get("overall_recommendation"),
        target_rollup=target_rollup,
    )

    # 5-field validation_summary — the shared evidence-package writer's contract, composed from
    # target-profile's card-read model (passed = card returned usable data; failed = absent/not-wired
    # OR data_unavailable; passed_with_warnings + excluded_by_applies_when = 0: no method validation,
    # no target-level applies_when gating). Computed HERE (before the emit branch) so the
    # evidence-package emitter and the nomination path below share ONE construction.
    validation_summary = _validation_summary_from_sub_results(sub_results)

    # Write the deterministic evidence_package if EITHER the emit mode OR auto-grounding needs it
    # (once, shared). ground_axis reads this envelope (synthesis.sub_verdicts + cards); the emit-mode
    # return path reuses the same file. When neither is requested, ep_path stays None → nothing written
    # → a default nomination run is byte-identical.
    # Track the artifact kinds WRITTEN THIS RUN (not files on disk) so assert_write_set is robust to a
    # reused --out with stale artifacts from a prior mode.
    _written: set = set()
    ep_path = None
    if args.emit == "evidence-package" or args.ground or args.full_package or substrate_chain_on:
        ep_path = _write_evidence_package(
            args=args,
            sub_results=sub_results,
            gate_action=gate_action,
            recommendation_gate=recommendation_gate,
            confidence_tier=confidence_tier,
            deciding_axis=deciding_axis,
            validation_summary=validation_summary,
            # subtype-first-class-evidence (Option A): populate context.subgroup_spec + the
            # subtype_resolved block ONLY when the run is subtype-scoped (byte-stable default).
            subtypes=subtypes,
            subtype_facet=subtype_facet,
            # verdict-INERT decision facets (previously nomination.json-only) into synthesis.decision_facets
            # + the composed modality into context, so the cross-evidence integrator can consume them.
            certainty_by_axis=certainty_by_axis,
            cross_gate_shared_evidence=cross_gate_shared_evidence,
            fragility=fragility,
            competitor_crossref=competitor_crossref,
            # factored-record consumers (M4): per-modality favorability + over-precision audit, so the
            # cross-evidence integrator sees per-MODALITY calls + magnitude fragility, not just the scalar.
            modality_fit_by_channel=modality_fit_by_channel,
            magnitude_borderline=magnitude_borderline,
            modality=args.modality,
        )
        _written.add("evidence_package")

    # AUTO-GROUND (fanout-integration): PRODUCE the per-axis grounded substrate in one pass over the
    # just-written evidence package. VERDICT-INERT (reads the finished spine) + best-effort (any failure
    # degrades to 'not grounded'). Populates grounded_by_axis so the inline HTML render shows the
    # findings, and persists grounded_<axis>.json in --out for downstream --substrate consumers.
    # ground_axis retrieves PubMed BY TERM → use the natural-language --ground-indication when given
    # (an OncoTree code retrieves ~nothing); default to --indication otherwise. Shared by grounding +
    # the 6-dim literature risk read below.
    ground_ind = args.ground_indication or args.indication
    # #1279: skip when grounding already ran (pre-synthesis early-grounding on the --synthesis path, or a
    # pre-supplied --grounded-dir) — grounded_by_axis already populated. On --no-synthesis this is empty,
    # so this block runs exactly as before (byte-identical). Prevents a double PubMed/Bedrock grounding pass.
    if run_ground and ep_path is not None and not grounded_by_axis:
        try:
            from tp_grounding import auto_ground, resolve_axes

            axes = resolve_axes(ground_spec)
            print(
                f"[target-profile] auto-grounding axes {axes} over {ep_path.name} "
                f"(indication term {ground_ind!r}; verdict-inert)...",
                file=sys.stderr,
            )
            produced = auto_ground(args.target, ground_ind, ep_path, args.out, axes)
            grounded_by_axis.update(produced)
            print(
                f"[target-profile] auto-grounded {sorted(produced)} → grounded_<axis>.json in {args.out}",
                file=sys.stderr,
            )
        except Exception as e:  # noqa: BLE001 — grounding is substrate/display context, never blocks a run
            print(
                f"[target-profile] WARN: auto-grounding failed ({type(e).__name__}: {e}); "
                "continuing without grounded substrate",
                file=sys.stderr,
            )

    # The LLM literature risk read (display-only / verdict-INERT; NON-reproducible). Best-effort + gated
    # by run_risk (needs Bedrock/network). The DETERMINISTIC risk_6dim moved OUT of this network gate — it
    # is now computed UNCONDITIONALLY in-memory below (build_risk_6dim), so md/html/json/target_report all
    # read one deterministic source even offline. An explicit --risk-assessment file wins.
    if run_risk and ep_path is not None:
        from tp_grounding import auto_risk_assessment

        if risk_assessment is None:
            risk_assessment = auto_risk_assessment(args.target, ground_ind, ep_path, args.out)
        # NOTE: the verdict-INERT cited gene×indication literature card is no longer written here as a
        # side-channel (cited_literature_evidence.json) — it is now the first-class literature-context
        # fan-out member composing the cited-literature-evidence card (2026-09-02).

    # [3B] the cross-evidence hypothesis (display-only / verdict-INERT; when present it REPLACES the
    # Tier-3 exec-summary/tension in the HTML render). Consumes the shared substrate + the 6-dim risk read
    # produced just above. Best-effort; an explicit --hypothesis file wins.
    if run_hypothesis and ep_path is not None and hypothesis is None:
        from tp_grounding import auto_hypothesis

        risk_path = Path(args.out) / "risk_assessment.json"
        # the indication-INDEPENDENT target-biology dossier: this run composed target_intrinsic as a
        # fan-out member, so the dossier is a projection of a carrier already in memory. Not passing it
        # left the integrator reporting `degraded inputs: ['dossier']` on EVERY default-on chain run,
        # which caps its certainty `low` unconditionally — a panel-wide constant that cannot rank
        # targets. The integrator accepts this composed shape (no `headline`) as well as a standalone
        # decision.json.
        # ORDERING: subskills/ is written by write_full_package at the very END of the run, so simply
        # pointing at the path was NOT enough — `.exists()` was False here on every run and the caveat
        # persisted. Materialize the one projection [3B] needs now; the full-package write later
        # rewrites the same file (with figure joins) and wins.
        dossier_path = Path(args.out) / "subskills" / "target_intrinsic" / "package.json"
        if not dossier_path.exists() and isinstance(sub_results.get("target_intrinsic"), dict):
            write_subskill_package(Path(args.out), "target_intrinsic", sub_results["target_intrinsic"])
        hypothesis = auto_hypothesis(
            ep_path,
            args.out,
            modality=args.modality,
            risk_path=(str(risk_path) if risk_assessment is not None else None),
            dossier_path=(str(dossier_path) if dossier_path.exists() else None),
            grounded_by_axis=grounded_by_axis,
        )

    # --emit evidence-package: RETURN after emitting the deterministic machine envelope (written above),
    # skipping every nomination-oriented render (composite panel / md / html / nomination.json /
    # provenance). The spine it reads is byte-identical to a nomination run.
    if args.emit == "evidence-package":
        assert_write_set(args, _written)  # envelope-only write-set (evidence_package recorded above)
        print(f"[target-profile] wrote {ep_path} (evidence-package; deterministic, LLM-free)")
        # gate_action carries only the KILL actions; a strong-tier forced `nominate` lives on
        # recommendation_gate.forced_recommendation (A1) — read both or the console under-reports it.
        print(f"Recommendation: {gate_action or recommendation_gate.get('forced_recommendation') or '(no gate fired)'}")
        _restore_run_log()
        return 0

    # [3A] DETERMINISTIC risk_6dim (target_report.risk_6dim) — computed UNCONDITIONALLY from the in-memory
    # sub_results (an offline-safe pure spine projection), so md / html / risk_rollup.json / target_report
    # all read ONE source (the former md↔html divergence is gone). grounded_by_axis (populated above when
    # --ground ran) layers escalate-only literature findings; empty offline → pure deterministic bins. An
    # explicit --risk-rollup file (loaded near the top) wins. Verdict-INERT; target_call stays sole gate.
    if risk_rollup is None:
        from tp_grounding import build_risk_6dim

        risk_rollup = build_risk_6dim(sub_results, args.modality, grounded_by_axis, args.out)

    # 3a. Emit figures via the single orchestrator (tp_figures): composite panel (skipped under
    # --verdict-only) + per-card registry figures + per-sub-skill heros (skipped under --no-figures).
    # Returns a FigureManifest — the ONE source of figure paths the renderers read. Verdict-inert.
    fig = emit_figures(args, sub_results, llm_output, profile_timers=args.profile_timers)
    card_figures = fig.card_figures

    # 3b/3c. target_profile.md + target_profile.html render via the UNIFIED report_render engine
    # (spine-sourced), emitted just AFTER the nomination is assembled below (report_render reads the
    # nomination's target_report.skill_reports spine) — the SOLE md/html producer. The legacy
    # tp_render_md / tp_render_html modules have been RETIRED (removed; render_review is self-contained).
    # Figures above (emit_figures) still feed card_figures / --reports / the report_render figure-join.
    # See `_emit_default_reports` just after the nomination write.

    # Governance / reproducibility. Build the governance block via the SHARED
    # _skills_common.build_governance so it can no longer drift from compose-dashboard's — same keys,
    # same construction, one source. Uses the 5-field validation_summary composed above (shared with
    # the --emit evidence-package path). release_pin is a pass-through (target-profile reads live and
    # does not auto-resolve the release); honest default 'unpinned'.
    governance = build_governance("live_latest", args.release_pin or "unpinned", validation_summary)
    # Additive target-profile annotation (does NOT alter the shared 3-key core → no schema drift):
    governance["_note"] = (
        "target-profile reads live data; release auto-resolution is a deferred data-catalog "
        "follow-on, so release_pin is 'unpinned' unless supplied via --release-pin."
    )

    # target_report.v1 (docs/UNIFIED_OUTPUT_CONTRACT.md) — ADDITIVE unified per-target object composed by
    # REFERENCE over the target-level facets built above (target_call + the rollups). Verdict-inert;
    # target_call owns the recommendation. The originals stay top-level until consumers migrate to read
    # target_report; this is the scaffold the later consolidation collapses into.
    target_report = build_target_report(
        target_call=target_call,
        target_rollup=target_rollup,
        target_coherence=target_coherence,
        ordinal_matrix=ordinal_matrix,
        modality_fit_by_channel=modality_fit_by_channel,
        modality_conjunction=modality_conjunction,
        risk_rollup=risk_rollup,
        subtype_facet=subtype_facet,
        biomarker_facet=biomarker_facet,
        fragility=fragility,
        heterogeneity=heterogeneity,
        cross_gate_shared_evidence=cross_gate_shared_evidence,
        magnitude_borderline=magnitude_borderline,
        certainty_by_axis=certainty_by_axis,
        addressable_population=addressable_population,
        actionability_mode=actionability_mode,
        competitor_crossref=competitor_crossref,
        archetype_companion=archetype_companion,
        nomination_scorecard=nomination_scorecard_facet,
        nomination_predictive_score=nomination_predictive_score,
        skill_reports=skill_reports,
    )

    nomination = {
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "target": args.target,
        "indication": args.indication,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "governance": governance,
        "invoked_lenses": invoked_lenses,
        # Mirrors provenance (below): the subtype tier is default-on, so nomination.json must say
        # which strata were in scope — `subtype_fit` appearing in sub_verdicts is otherwise the only
        # hint, and it is absent for an unregistered indication.
        "scope_subtypes": list(subtypes or []),
        "scope_subtypes_source": subtypes_source,
        "sub_verdicts": {
            short: {
                "skill_dir": r["skill_dir"],
                "verdict": r["verdict"][0] if r["verdict"] else None,
                "driving_rule_id": r["verdict"][1] if r["verdict"] else None,
                "fired_rule_ids": [f["rule_id"] for f in r["fired"]],
                # cards_used: the ACTUAL card set this sub-skill resolved this run (2026-08-12
                # reproducibility fix). Previously only cards_MISSING was recorded, leaving the positive
                # pulled set implicit in the static SUB_SKILL_CARDS map — insufficient to reproduce a run
                # or key an eval ledger. Now the full set + the missing subset are both on the record.
                "cards_used": [c["card_id"] for c in r["cards"]],
                "cards_missing": [c["card_id"] for c in r["cards"] if c.get("_missing")],
            }
            for short, r in sub_results.items()
        },
        # target_report.v1 — the unified per-target object (additive; references the facets below).
        # See docs/UNIFIED_OUTPUT_CONTRACT.md.
        "target_report": target_report,
        # target_call — the unified DECISION view and the CANONICAL OWNER of the four decision-spine
        # objects: recommendation_gate→target_call.gate, confidence_tier→target_call.confidence,
        # deciding_axis→target_call.deciding_axis, gate_scorecard→target_call.gate_scorecard. The FULL-NEST
        # (2026-09-03): those four are NO LONGER emitted as top-level nomination keys — they live only
        # under target_call, retiring the #932 dual-exposure scaffold. recommendation_gate is still the
        # sole owner of the recommendation VALUE (build_target_call recomputes nothing). See
        # docs/UNIFIED_OUTPUT_CONTRACT.md. (provenance.json + the evidence_package synthesis block carry
        # their own copies for reproducibility / the cross-evidence contract — unchanged.)
        "target_call": target_call,
        "ordinal_matrix_view": ordinal_matrix,
        # (Wave-3 legacy-facet retirement 2026-09-03) The top-level "biomarker_facet" + "subtype_facet"
        # nomination keys were DUPLICATES of target_report.biomarker + target_report.subtype_convergence
        # (the SAME objects) and had no reader — dropped. They remain nested under target_report, and are
        # still passed in-memory to the synthesis prompt / evidence package / target_rollup.
        # target_rollup.v1 + target_coherence.v1 — the VERDICT-INERT distillation layer: a 7-axis
        # roll-up + a NEGATIVE cross-axis block (no positive scalar) + a PROMINENT subtype block, and a
        # thesis/coherence lens on top. Additive; never touch the spine above.
        "target_rollup": target_rollup,
        "target_coherence": target_coherence,
        # Literature-derived risk-by-dimension (the --risk-assessment / grounded lit lane). Serialized so
        # the report_render literature_risk block can render it (it reads nomination.risk_assessment);
        # None on a default run without the lit-risk lane. VERDICT-INERT — literature is context, never a
        # gate. (Was previously passed only to the now-deprecated legacy html renderer, never persisted.)
        "risk_assessment": risk_assessment,
        # ("presence_facet" + "selectivity_facet" RETIRED 2026-09-03, Wave-3: the legacy md/html renderers
        # that consumed them are gone. presence_facet stays an IN-MEMORY input to the synthesis prompt
        # (see _build_user_prompt below) — only its redundant top-level nomination key drops; the selectivity
        # question_table is on the skill_report[] spine (target_report.skill_reports.selectivity). Both
        # skills' synthesis_facets remain carried by the fan-out under sub_results[<short>].)
        # ("dependency_facet" RETIRED 2026-09-03 — see the facet-build block; functional-requirement's
        # synthesis_facet is still carried at sub_results['dependency']['synthesis_facet'] + on the
        # skill_report[] spine under target_report.skill_reports.dependency.)
        # ("modality_conjunction" RETIRED 2026-09-03 — duplicated target_report.modality_fit.conjunction,
        # no reader; still nested there + passed in-memory to build_target_report.)
        # (Wave-3 legacy-facet retirement 2026-09-03) The top-level "competitor_crossref", "fragility",
        # "cross_gate_shared_evidence", "actionability_mode", and "certainty_by_axis" nomination keys were
        # DUPLICATES of their target_report nests (competitive_positioning / robustness.fragility /
        # robustness.correlated_evidence / actionability_mode / robustness.certainty_by_axis — the SAME
        # objects) and had NO top-level-key reader: the synthesis prompt + MD renderer take them in-memory,
        # and cross-evidence reads certainty/cross_gate/competitor/fragility via the EVIDENCE-PACKAGE
        # decision_facets (tp_evidence_package, unchanged), not the nomination. Dropped. `fragility`'s only
        # cross-repo reader (target-contracts eval ledger) now reads target_report.robustness.fragility as a
        # forward-compat fallback (target-contracts #618). All still nested under target_report + passed
        # in-memory to build_target_report / the prompt / the evidence package.
        # ("addressable_population" top-level key RETIRED 2026-09-03 — its last non-render reader
        # (tools/rerender.py) retired with the legacy html renderer; still nested at
        # target_report.addressable_population + passed in-memory to build_target_report.)
        # Per-axis NARRATIVE (interpretability), keyed by sub-skill short: movers / dissenters /
        # flip_conditions / gaps / rule_sentences per decision-relevant verdict. ADDITIVE / verdict-inert
        # — the citeable substrate for the dashboard 'why this verdict' panel + Tier-3 synthesis.
        "narrative_by_axis": narrative_by_axis,
        # Target-archetype COMPANION (2026-08-28): the verdict-INERT cross-skill nearest-reference facet
        # — soft archetype membership (kNN, not a label) + nearest reference analogs + rule-fingerprint
        # precedent + a missingness map, against the frozen reference atlas. DESCRIPTIVE; archetype ∉
        # _SHORT_TO_GATE and this never touches the recommendation/gate/confidence. None when the atlas is
        # absent or the companion could not be computed (best-effort — see the computation site above).
        "archetype_companion": archetype_companion,
        # Canonical UNIFIED_OUTPUT_CONTRACT spine for the archetype facet (role=descriptive, call=None) —
        # the same skill_report shape the fan-out sub-skills carry + the standalone target-archetype
        # companion.json emits, built from the SAME companion + scorecard via the shared archetype_core
        # builder (offline==composed). VERDICT-INERT. None when the atlas/companion is absent.
        "archetype_skill_report": archetype_skill_report,
        # THESIS (Step 2a, 2026-09-11): the governed thesis-routing key derived from archetype_companion's
        # verdict-inert soft_membership (target_thesis.yaml hard-margin rule + biology_axis fallback).
        # VERDICT-INERT — consumed by NO gate block until Step 2b; emitted for review + as the input the
        # per-thesis gate will read. `unresolved` reproduces today's gate.
        "thesis": thesis,
        # D1 nomination-readiness SCORECARD (2026-08-28): glass-box, archetype-conditioned per-axis score +
        # driving/limiting axes + route-conditioned counterfactual gap. DESCRIPTIVE / verdict-inert — never
        # touches the recommendation/gate/confidence. None when the atlas is absent or it could not be
        # computed (best-effort — see the computation site above).
        "nomination_scorecard": nomination_scorecard_facet,
        # D2 predictive score + D3 attribution (2026-08-28): outcome-trained (frozen de-FAMEd logistic)
        # clinical-advancement PROPENSITY + exact per-axis attribution. DESCRIPTIVE / verdict-inert — NOT
        # P(success), NOT a gate; never touches the recommendation/confidence. None when no d2_model.
        "nomination_predictive_score": nomination_predictive_score,
        # M4 per-channel modality favorability rolled up from the records' modality_scope (worst-case
        # conjunction). ADDITIVE / verdict-inert — the per-modality view the scalar verdict couldn't hold.
        "modality_fit_by_channel": modality_fit_by_channel,
        # M4 over-precision audit: axes whose call is knife-edge on its continuous cutpoint. ADDITIVE /
        # verdict-inert. Empty until an axis populates magnitude.value + distance_to_cut (selectivity first).
        "magnitude_borderline": magnitude_borderline,
        # Per-card figures produced this run (SVG + interactive .plotly.json siblings), keyed by
        # card_id, paths relative to figures/. The dynamic HTML renderer embeds the
        # `dynamic: True` Plotly specs; falls back to the SVG otherwise.
        "card_figures": card_figures,
        "llm_synthesis": llm_output,
        # CARRY the cross-evidence-hypothesis (3B) into the nomination so the ONE renderer
        # (report_render) can surface its causal chain + defensibility/uncertainty WITHOUT re-reading
        # the sibling hypothesis.json (dashboard consolidation). DISPLAY-ONLY / VERDICT-INERT (never
        # feeds the gate); None when --no-hypothesis / offline. (risk_assessment is already carried
        # above for the lit×omics coherence view.) Also written as sibling hypothesis.json as before.
        "hypothesis": hypothesis,
    }
    write_artifact(args.out, "nomination", json.dumps(nomination, indent=2, default=str), _written)

    # Default target_profile.md + target_profile.html render via the UNIFIED report_render engine
    # (preset "full"), reading the nomination's skill_report[] spine. md is required by the write-set;
    # html is BEST-EFFORT (mirrors the legacy try/except — a render failure must never abort the run).
    from _skills_common.report_render import render_report as _render_report

    write_artifact(
        args.out,
        "markdown",
        _render_report(nomination, preset="full", backend="markdown", target=args.target, indication=args.indication),
        _written,
    )
    try:
        write_artifact(
            args.out,
            "html",
            _render_report(
                nomination,
                preset="full",
                backend="html",
                target=args.target,
                indication=args.indication,
                # asset_root = the run dir → the html backend INLINES figure SVGs
                # (data-URIs) so target_profile.html is self-contained and renders
                # in any viewer, not only a browser opened from the run dir.
                asset_root=args.out,
            ),
            _written,
        )
        print(f"[target-profile] wrote {args.out}/target_profile.html (report_render)", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[target-profile] WARN: report_render HTML failed: {e}", file=sys.stderr)

    provenance = {
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "target": args.target,
        "indication": args.indication,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "governance": governance,
        "invoked_lenses": invoked_lenses,
        # Subtype scope PROVENANCE (2026-09-11, tier default-on). A reader must be able to tell an
        # auto-resolved scope from an operator-chosen one, and "whole-cohort because the indication
        # is unregistered" from "whole-cohort because --no-subtypes". See tp_common.default_subtypes.
        "scope_subtypes": list(subtypes or []),
        "scope_subtypes_source": subtypes_source,
        "sub_skills_ran": [s for s, _ in SUB_SKILLS],
        "recommendation_gate": recommendation_gate,
        "confidence_tier": confidence_tier,
        "deciding_axis": deciding_axis,
        "llm_prompt_hash": llm_output.get("executive_summary", {}).get("_prompt_hash"),
        "llm_model_id": llm_output.get("executive_summary", {}).get("_model_id"),
        # Governance item B (2026-07-20): the DECLARED framework model pin. Distinct
        # from llm_model_id (the model that actually ran) — when the two diverge, an
        # env override was used. Auditors compare them to detect per-run drift.
        "framework_model_version": _framework_model_version(),
        "artefacts": [
            "target_profile.md",
            "target_profile.html",
            "nomination.json",
            "run.log",
        ]
        + (
            []
            if args.no_figures
            else [
                "figures/target_profile_at_a_glance.png",
                "figures/target_profile_at_a_glance.svg",
            ]
        )
        + [f"grounded_{ax}.json" for ax in sorted(grounded_by_axis)],
        # fanout-integration: the per-axis grounded substrate ACTUALLY produced this run. Keyed on
        # grounded_by_axis (non-empty), NOT args.ground: the grounded-substrate chain is DEFAULT-ON
        # (SKILL_VERSION 1.2.0), so a normal run auto-produces grounded_<axis>.json via run_ground
        # WITHOUT the --ground flag being set. Gating provenance on args.ground under-reported those
        # files (grounded_axes: [] + artifacts omitted) even though they exist in --out and feed the
        # inline render + risk_rollup/hypothesis. Report what was produced. Verdict-inert.
        "grounded_axes": sorted(grounded_by_axis),
    }
    write_artifact(args.out, "provenance", yaml.safe_dump(provenance, sort_keys=False), _written)

    # --reports: OPTIONAL report_render bundle(s) from the assembled nomination (spine). Additive +
    # verdict-inert + BEST-EFFORT — wrapped so a render failure can never abort a run that already wrote
    # its md/nomination/provenance (the 'reports' kind is BEST_EFFORT in tp_emit). Recorded into
    # _written so assert_write_set (below) accounts for it.
    if getattr(args, "reports", None):
        try:
            import tp_reports

            presets = [p.strip() for p in args.reports.split(",") if p.strip()]
            backends = (
                [b.strip() for b in args.report_backends.split(",") if b.strip()] if args.report_backends else None
            )
            _written |= tp_reports.write_reports(args.out, nomination, presets, backends)
        except Exception:
            pass  # best-effort: never let report rendering abort the run
    # Guard: the artifacts WRITTEN THIS RUN match this mode's declared MODE_WRITE_SET (html is
    # best-effort; evidence_package was recorded above when --ground/--full-package).
    assert_write_set(args, _written)

    # --full-package: additive REVIEW bundle — the evidence_package.json was already written above
    # (ep_path); here we add the per-sub-skill packages + a MANIFEST index tying every artifact together.
    # Verdict-inert projection over the same sub_results; best-effort, never blocks a run.
    if args.full_package:
        try:
            mpath = write_full_package(
                args.out,
                target=args.target,
                indication=args.indication,
                sub_results=sub_results,
                skill_name=SKILL_NAME,
                skill_version=SKILL_VERSION,
                generated_at=provenance["generated_at"],
                subtypes=subtypes,
                modality=args.modality,
                has_figures=not args.no_figures,
                has_evidence_package=ep_path is not None,
                has_narrative=True,
            )
            print(
                f"[target-profile] --full-package: wrote per-sub-skill packages + {mpath.name} "
                f"(+ MANIFEST.md); evidence_package.json {'present' if ep_path else 'ABSENT'}"
            )
        except Exception as e:  # noqa: BLE001 — persistence side-artifact must never break the run
            print(
                f"[target-profile] WARN: --full-package manifest failed "
                f"({type(e).__name__}: {e}); core artifacts already written",
                file=sys.stderr,
            )

    print(f"[target-profile] wrote {args.out}/target_profile.md")
    print(f"[target-profile] wrote {args.out}/nomination.json")
    print(f"[target-profile] wrote {args.out}/provenance.yaml")
    print()

    def _unwrap(raw):
        return raw.get("value") if isinstance(raw, dict) else raw

    print(f"Recommendation: {_unwrap(llm_output.get('overall_recommendation'))}")
    print(f"Confidence:     {_unwrap(llm_output.get('confidence'))}")
    _restore_run_log()
    return 0


if __name__ == "__main__":
    sys.exit(main())
