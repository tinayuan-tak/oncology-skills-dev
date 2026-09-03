#!/usr/bin/env python3
"""target-profile — composed target profile with Tier-3 LLM narrative synthesis.

Fans out to the 14 question-answering sub-skills in SUB_SKILLS (tumor-presence,
tumor-selectivity, functional-requirement, mechanism-and-pharmacology,
genomic-alteration-profile, differentiation-landscape, tractability-small-molecule,
surface-modality-fit, immune-context, on-target-safety-liability, target-intrinsic,
cis-feature-coherence, combination-and-vulnerability, translational-readiness)
+ an opt-in subtype_fit tier (--subtypes), collects their sub-verdicts + fired
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
import concurrent.futures
import importlib.util
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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
from tp_common import *              # noqa: F401,F403
from tp_common import SKILL_NAME, SKILL_VERSION, SKILLS_DIR, _framework_model_version
from tp_fanout import *              # noqa: F401,F403
from tp_fanout import SUB_SKILLS, _run_sub_skills, _skipped_synthesis_output
from tp_gates import *               # noqa: F401,F403
from tp_gates import (               # names main() calls directly
    _CONFIDENCE_RANK, _TIER_TO_CONFIDENCE, _gate_recommendation, _gate_scorecard,
    _hard_gates_status, _positive_tier,
)
from tp_facets import *              # noqa: F401,F403
from tp_facets import (
    _actionability_mode_facet,
    _addressable_population_facet, _biomarker_facet, _certainty_by_axis, _competitor_crossref_facet,
    _skill_reports_by_short,
    _modality_fit_by_channel, _magnitude_borderline,
    _deciding_axis, _dependency_facet,
    _cross_gate_shared_evidence,
    _fragility_facet, _narrative_by_axis, _heterogeneity_facet, _modality_conjunction_facet, _ordinal_matrix, _presence_facet,
    _selectivity_facet, _subtype_facet,
    build_target_rollup, build_target_coherence, build_target_call, build_target_report,
)
from tp_synthesis_prompt import *    # noqa: F401,F403
from tp_synthesis_prompt import (_SYSTEM_PROMPT, _METRIC_LEGEND, _build_synthesis_tool,
                                  _build_user_prompt, validate_synthesis_anchors)
from tp_render_md import *           # noqa: F401,F403
from tp_render_md import _render_target_profile_md
from tp_render_html import *         # noqa: F401,F403
from tp_render_html import _render_target_profile_html
from tp_evidence_package import *    # noqa: F401,F403
from tp_evidence_package import (
    _catalogue_rows_from_sub_results, _emit_card_figures, _validation_summary_from_sub_results,
    _write_evidence_package,
)
from tp_figures import *             # noqa: F401,F403
from tp_figures import emit_figures, resolve_figures_root, FigureManifest
from tp_emit import *                # noqa: F401,F403
from tp_emit import write_artifact, assert_write_set, expected_artifacts, run_mode
from tp_manifest import *            # noqa: F401,F403
from tp_manifest import write_full_package

# _skills_common symbols invoked directly by main() (modality_lens preserved from the
# pre-split import surface).
from _skills_common import modality_lens, synthesize_structured, render_composite_panel
from _skills_common import ordinal_view
from _skills_common.envelope import build_governance




# Canonical modality tokens (target-contracts vocabularies/modality.enum.yaml) + natural-language
# aliases. The gate veto-suppression + positive-tier + modality_lens all key on the canonical set, so
# an un-normalized token silently matches nothing. Keep in sync with the enum if new modalities land.
_CANONICAL_MODALITIES = frozenset({
    "small_molecule", "degrader", "adc", "bite_tce", "antibody", "bispecific_non_tce", "cell_therapy",
})
_MODALITY_ALIASES = {
    "sm": "small_molecule", "small-molecule": "small_molecule", "inhibitor": "small_molecule",
    "protac": "degrader", "glue": "degrader", "molecular_glue": "degrader", "molecular-glue": "degrader",
    "bite": "bite_tce", "tce": "bite_tce", "t-cell-engager": "bite_tce", "tcell_engager": "bite_tce",
    "bispecific": "bite_tce", "bispecific_tce": "bite_tce",
    "mab": "antibody", "monoclonal": "antibody", "naked_antibody": "antibody",
    "car-t": "cell_therapy", "cart": "cell_therapy", "car_t": "cell_therapy", "cart_cell": "cell_therapy",
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
    print(f"[target-profile] WARN: --modality {raw!r} is not a recognized modality "
          f"(canonical: {sorted(_CANONICAL_MODALITIES)}); ignoring the modality lens.",
          file=sys.stderr)
    return None


# The AWS account that owns the onc-compbio derived-products bucket every sub-skill reads from
# (the cbg profile → 557690623046). Overridable (comma-list) for other authorized accounts via env.
_ONC_COMPBIO_ACCOUNT_IDS = frozenset(
    a.strip() for a in os.environ.get("ONC_COMPBIO_ACCOUNT_IDS", "557690623046").split(",") if a.strip())


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
        ident = boto3.client("sts", config=Config(connect_timeout=5, read_timeout=5,
                                                   retries={"max_attempts": 2})).get_caller_identity()
        acct = ident.get("Account")
    except Exception as e:  # noqa: BLE001 — any resolution failure is a preflight fail, never a crash
        return False, f"could not resolve AWS identity ({type(e).__name__}: {e})"
    prof = os.environ.get("AWS_PROFILE", "<default-chain>")
    if acct not in _ONC_COMPBIO_ACCOUNT_IDS:
        return False, (f"AWS identity resolves to account {acct} (AWS_PROFILE={prof}), NOT an "
                       f"onc-compbio account {sorted(_ONC_COMPBIO_ACCOUNT_IDS)}")
    return True, f"account {acct} (AWS_PROFILE={prof})"


# Run log (development + provenance): tee stdout+stderr to <out>/run.log. The tee lives in
# _skills_common.run_log (shared with the focused skills' dispatcher); re-exported under the
# original private names so the composer + its tests reach it as run._install_run_log / _restore_run_log.
# A full run narrates its backend via ~33 `[target-profile] …` prints (fan-out, gate firing, Bedrock
# call, figure emission, WARNs); the tee mirrors that to a timestamped, greppable run.log that travels
# with the artifact tree (listed in provenance.yaml). Verdict-inert; best-effort.
from _skills_common.run_log import install_run_log as _install_run_log, restore_run_log as _restore_run_log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--subtypes", default=None,
                    help="Comma-separated molecular subgroup ids to scope the "
                         "profile to (e.g. 'MSI_H,MSS'). When set, the subtype "
                         "tier is evaluated: a MEASURED, floor-cleared subtype "
                         "that is NOT a dependency holds the nomination. Omit for "
                         "a whole-cohort profile (backward-compatible default).")
    ap.add_argument("--modality", default=None,
                    help="OPTIONAL post-hoc modality lens. Canonical values (modality.enum.yaml): "
                         "small_molecule, degrader, adc, bite_tce, antibody, bispecific_non_tce, "
                         "cell_therapy. Common aliases are normalized (e.g. bite/tce/bispecific -> "
                         "bite_tce, protac/glue -> degrader, car-t -> cell_therapy); an UNKNOWN token "
                         "warns and is ignored (never a silent no-op).")
    ap.add_argument("--release-pin", default=None,
                    help="OPTIONAL data release_pin to STAMP into governance/provenance for "
                         "reproducibility (parity with compose-dashboard). Pass-through only: "
                         "target-profile reads live and does NOT auto-resolve the release — absent "
                         "this flag the pin is recorded as 'unpinned' (honest, never fabricated). "
                         "Auto-resolution is a deferred data-catalog follow-on.")
    ap.add_argument("--therapeutic-hypothesis", default=None,
                    help="OPTIONAL therapeutic hypothesis (line-of-therapy, "
                         "patient state, clinical goal). Reshapes LLM "
                         "narrative; sub-verdicts unchanged.")
    ap.add_argument("--no-figures", action="store_true",
                    help="VERDICT-ONLY mode: skip per-card figure emission + the interactive HTML "
                         "(the 4.6MB inlined plotly.js + the figure double-read). Emits "
                         "nomination.json + target_profile.md + provenance + a STATIC (no-JS) HTML. "
                         "The deterministic verdict spine is byte-identical to a full run — figures "
                         "never feed the verdict. Use for fast iteration / re-runs; render later via "
                         "the deferred-render path. (Perf Stage 1, 2026-07-23.)")
    ap.add_argument("--full-package", action="store_true",
                    help="Self-contained REVIEW bundle: a normal run PLUS the deterministic "
                         "evidence_package.json + a per-sub-skill package under subskills/<short>/"
                         "package.json + a MANIFEST (.json/.md) index tying every artifact together. "
                         "Additive + verdict-inert; for team review where all outputs must persist in "
                         "one portable tree. Pairs well with --self-contained.")
    ap.add_argument("--reports", default=None, metavar="PRESETS",
                    help="Also emit report_render bundles from the nomination: a comma-separated list "
                         "of presets (exec-brief,reviewer-dossier,deck,full), written to "
                         "<out>/reports/report_<preset>.<ext>. Additive + verdict-inert + best-effort "
                         "(a render failure never aborts the run). e.g. --reports exec-brief,deck")
    ap.add_argument("--report-backends", default=None, metavar="BACKENDS",
                    help="Comma-separated backends for --reports (default: markdown,html,json; add "
                         "'pptx' for a pandoc deck, 'text' for plain text).")
    ap.add_argument("--self-contained", action="store_true",
                    help="Render target_profile.html as a fully OFFLINE, portable artifact: per-card "
                         "figures embed as inline base64 SVG data-URIs (no interactive Plotly, no CDN "
                         "fetch), so it renders in any webview / can be shared or served from S3 with "
                         "no network. Default (omit) keeps the interactive Plotly+CDN embed. "
                         "Verdict-inert; the .md/nomination spine is unchanged.")
    # Per-sub-skill LLM narration rides the SAME default-on substrate umbrella as ground/risk/hypothesis:
    # ON by default, OFF under --no-substrate / --no-synthesis / --verdict-only / --emit. Each
    # narrator-bearing sub-skill's single-lens narration is persisted under subskills/<short>/package.json
    # (llm_synthesis). Best-effort + VERDICT-INERT (a Bedrock failure degrades to a note; the deterministic
    # spine is unaffected). No dedicated flag — the substrate umbrella governs it.
    ap.add_argument("--no-synthesis", action="store_true",
                    help="Skip the Tier-3 Bedrock LLM synthesis (executive-summary / tension / "
                         "recommendation narrative). The deterministic verdict spine — sub-verdicts, "
                         "recommendation gate, positive tier, deciding axis, scorecard, facets — is "
                         "computed independently of the LLM and stays byte-identical to a full run. "
                         "nomination.json marks llm_synthesis._synthesis_skipped; the report shows a "
                         "note in place of the narrative. Removes the serial, non-cacheable network tail.")
    ap.add_argument("--verdict-only", action="store_true",
                    help="Umbrella fast/CI/iteration mode: implies --no-synthesis AND --no-figures. "
                         "Emits the deterministic nomination (nomination.json + a narrative-free "
                         "target_profile.md + provenance) with no Bedrock call and no figure/panel "
                         "render. The verdict spine is byte-identical to a full run.")
    ap.add_argument("--profile-timers", action="store_true",
                    help="Emit per-sub-skill READ vs FIGURE-EMIT wall-clock timings to stderr "
                         "(instrumentation only; zero effect on artifacts). (Perf Stage 0.)")
    ap.add_argument("--emit", choices=["nomination", "evidence-package"], default="nomination",
                    help="Output shape. 'nomination' (default) → nomination.json + target_profile.md "
                         "+ provenance (the biologist-facing narrated profile). 'evidence-package' → "
                         "a deterministic, LLM-free evidence_package.json envelope (the same machine-"
                         "facing shape compose-dashboard emits), assembled from the SAME per-sub-skill "
                         "verdict spine. evidence-package implies --no-synthesis + --no-figures and "
                         "emits no nomination.json / md / html.")
    ap.add_argument("--risk-assessment", default=None, type=Path,
                    help="OPTIONAL: path to a literature-risk-assessment risk_assessment.json. When "
                         "given, its 6-dimension literature RISK read is rendered on the HTML dashboard "
                         "as a visually-separate, explicitly-labeled CONTEXT-TIER panel (non-reproducible; "
                         "never a verdict input — RISK_ASSESSMENT_INTEGRATION.md §4). Display-only.")
    ap.add_argument("--grounded-dir", default=None, type=Path,
                    help="OPTIONAL: directory of per-axis grounded_<axis>.json records "
                         "(literature-risk-assessment/ground_axis). Each subskill section whose axis has "
                         "a record shows its escalate-only, PMID-cited literature findings inline. "
                         "Display-only; never a verdict input.")
    ap.add_argument("--ground", nargs="?", const="engine", default=None, metavar="AXES",
                    help="AUTO-GROUND (fanout-integration): after the fan-out, run "
                         "literature-risk-assessment/ground_axis over the assembled evidence_package to "
                         "PRODUCE per-axis grounded_<axis>.json (escalate-only, PMID-cited literature "
                         "findings) in --out — feeding BOTH the inline HTML render AND downstream "
                         "--substrate (risk_rollup [3A] + cross-evidence-hypothesis [3B]). Value: "
                         "'engine' (default: the 5 engine axes), 'all' (+ clinical/commercial "
                         "pseudo-cards), or a comma-list (e.g. safety,dependency). Requires Bedrock + "
                         "network (BEDROCK_AWS_PROFILE); VERDICT-INERT + best-effort. Off by default "
                         "(a run without --ground is byte-identical + makes no network call).")
    ap.add_argument("--ground-indication", default=None, metavar="TERM",
                    help="OPTIONAL natural-language disease term for --ground's PubMed retrieval (e.g. "
                         "'colorectal cancer'). ground_axis searches PubMed by term, so an OncoTree code "
                         "(--indication COADREAD) retrieves almost nothing; pass the disease name here. "
                         "Defaults to --indication when omitted. Affects ONLY grounding retrieval — the "
                         "fan-out / verdict spine still key on --indication.")
    ap.add_argument("--risk-rollup", default=None, type=Path,
                    help="OPTIONAL: path to a risk_rollup.json (literature-risk-assessment/risk_rollup [3A]). "
                         "Renders the DETERMINISTIC, reproducible 'Risk by category' 5R lead table (the "
                         "committee glance) — modality-conditioned bins that are a pure function of the "
                         "sub-verdicts; the LLM/literature never sets a bin. Display-only.")
    ap.add_argument("--hypothesis", default=None, type=Path,
                    help="OPTIONAL: path to a cross-evidence-hypothesis hypothesis.json. When given, the "
                         "gate-clamped, cited 6-part hypothesis REPLACES the original Tier-3 LLM "
                         "executive-summary + tension synthesis on the HTML dashboard (the cross-evidence "
                         "integrator is a meta-layer above target-profile). Display-only; the deterministic "
                         "recommendation stays the header top-line.")
    ap.add_argument("--ab-suppress-fragility-prompt", action="store_true",
                    help="A/B CONTROL ARM (Phase-0 certainty-layer gate): suppress the per-axis "
                         "how-solid (certainty) block in the synthesis prompt only. Verdict-INERT — "
                         "the fragility facet is still computed and written to nomination.json, and "
                         "the deterministic recommendation/confidence spine is byte-identical; this "
                         "flag changes ONLY what the LLM narration sees, so an A/B run can measure "
                         "the block's effect on the prose. Not for production use.")
    ap.add_argument("--allow-degraded-data", action="store_true",
                    help="Escape hatch: SKIP the data-access preflight (STS account check for the "
                         "onc-compbio derived-products account). By DEFAULT a run whose AWS identity "
                         "is NOT the onc-compbio account aborts non-zero — because every live card "
                         "read would silently come back empty (all-`insufficient` verdicts, exit 0), "
                         "which would quietly invalidate an at-scale batch. Pass this ONLY for an "
                         "intentional cache-only / offline run. (env TARGET_PROFILE_SKIP_PREFLIGHT=1 "
                         "has the same effect.)")
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
    ap.add_argument("--no-substrate", action="store_true",
                    help="Opt OUT of the DEFAULT-ON grounded-substrate chain (ground_axis → risk_rollup "
                         "[3A] + 6-dim literature risk_assessment + cross-evidence-hypothesis [3B]). "
                         "Restores the offline, network-free, byte-identical run. The chain is "
                         "display-only / verdict-INERT either way.")
    ap.add_argument("--no-ground", action="store_true",
                    help="Granular opt-out: skip only the auto-grounding leg (no ground_axis PubMed "
                         "retrieval). risk_rollup/hypothesis then run without grounded findings.")
    ap.add_argument("--no-risk", action="store_true",
                    help="Granular opt-out: skip the risk_rollup [3A] + 6-dim literature risk_assessment "
                         "legs (the hypothesis, if on, then has no --risk input).")
    ap.add_argument("--no-hypothesis", action="store_true",
                    help="Granular opt-out: skip the cross-evidence-hypothesis [3B] leg.")
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
            print("\n" + "=" * 78 +
                  "\n[target-profile] DATA-ACCESS PREFLIGHT FAILED — aborting (exit 3).\n"
                  f"  {_pf_detail}\n"
                  "  Every sub-skill reads derived products from the onc-compbio bucket; without\n"
                  "  access, ALL verdicts silently degrade to `insufficient` (a hollow profile).\n"
                  "  FIX:   ensure the ambient AWS creds resolve to an onc-compbio account\n"
                  f"         {sorted(_ONC_COMPBIO_ACCOUNT_IDS)} — e.g. a SageMaker execution role in\n"
                  "         that account (no profile needed), or on a local box `export AWS_PROFILE=cbg`.\n"
                  "  Offline/cache-only run? pass --allow-degraded-data to skip this check.\n"
                  + "=" * 78, file=sys.stderr)
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
        no_substrate=args.no_substrate, no_synthesis=args.no_synthesis, emit=args.emit,
        ground=args.ground, no_ground=args.no_ground, no_risk=args.no_risk,
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
        print(f"[target-profile] grounded-substrate chain ON (ground={run_ground}, risk={run_risk}, "
              f"hypothesis={run_hypothesis}); display-only/verdict-inert, needs Bedrock+PubMed. "
              "Pass --no-substrate for an offline byte-identical run.", file=sys.stderr)

    invoked_lenses: dict = {}
    if args.modality:
        invoked_lenses["modality"] = args.modality
    if args.therapeutic_hypothesis:
        invoked_lenses["therapeutic_hypothesis"] = args.therapeutic_hypothesis

    # 1. Fan out to sub-skills.
    print(f"[target-profile] Running {len(SUB_SKILLS)} sub-skills for "
          f"{args.target} in {args.indication}...", file=sys.stderr)
    subtypes = [s.strip() for s in args.subtypes.split(",") if s.strip()] if args.subtypes else None
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
    # Per-sub-skill LLM narration rides the SAME default-on substrate umbrella (run_hypothesis is the
    # LLM tail gate — off under --no-substrate / --no-synthesis / --verdict-only / --emit), so a default
    # run narrates each narrator sub-skill and an offline run stays byte-identical.
    sub_results = _run_sub_skills(args.target, args.indication, subtypes=subtypes,
                                  profile_timers=args.profile_timers,
                                  plot_data_root=plot_data_root,
                                  synthesize_subskills=run_hypothesis,
                                  synthesis_model=getattr(args, "synthesis_model", None))
    if args.profile_timers:
        print(f"[perf] === fan-out total {time.perf_counter() - _fanout_t0:6.1f}s ===",
              file=sys.stderr)
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
    subtype_facet = _subtype_facet(sub_results, indication=args.indication)

    # Presence cross-modal reconciliation facet (2026-08-17): tumor-presence's own deterministic
    # per-(measurement, sample_context) presence matrix + RNA→protein proxy-quality + normal-tissue
    # comparators, carried through the fan-out via its _synthesis_facet hook. Previously the fan-out
    # captured only tumor-presence's collapsed one-word verdict, so the synthesis had to re-derive the
    # cross-modal tension (RNA-high/protein-absent; tumor-high/normal-high) from raw card numbers. This
    # hands the reasoner the skill's computed reconciliation. VERDICT-INERT (presence ∉ _SHORT_TO_GATE).
    presence_facet = _presence_facet(sub_results)

    # Selectivity facet: tumor-selectivity's 8-question leading table (WIN/DIST/INT/SAFE) +
    # the tumor-vs-normal WINDOW gate. Parallel to presence_facet; rendered as the leading table in the
    # composed dashboard. VERDICT-INERT — selectivity's verdict is owned by its resolver + veto clamp.
    selectivity_facet = _selectivity_facet(sub_results)

    # Dependency claim-vector facet (2026-08-18): functional-requirement's SIGNAL
    # decomposition (claim_vector DEP/SEL/COND/CHEM + key_signals + confidence annotations), parallel to
    # presence_facet. The SIGNAL half of the reconciliation; the certainty roll-up is certainty_by_axis.
    # VERDICT-INERT — dependency's verdict is owned by its resolver; this projection never moves it.
    dependency_facet = _dependency_facet(sub_results)

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
                sub_results, _atlas, companion=archetype_companion)
    except Exception:
        archetype_companion = None            # verdict-inert facets — never fail the flagship on an error
        nomination_scorecard_facet = None

    # Biology-axis (resolved early so it can also MASK the per-modality view below). Curated axis +
    # plausible modalities; uncurated → axis=unknown. NEVER raises. SLOT-2 emphasis only; the
    # deterministic verdict + gate recommendation are untouched.
    from _skills_common.biology_axis import resolve_biology_axis
    axis_info = resolve_biology_axis(args.target)

    # M4 modality-fit-by-channel: roll up the records' modality_scope into a PER-CHANNEL favorability
    # (worst-case conjunction) so the nomination can express per-modality calls — nominable as an
    # allele-selective SM, hold as a degrader — instead of one scalar. VERDICT-INERT. The biology-axis
    # applicability MASK marks category-error channels (SM for a pure surface antigen; ADC/TCE for a
    # pure intracellular target) not_applicable_by_axis — skipped for multi_axis duals (EGFR/ERBB2/MET).
    modality_fit_by_channel = _modality_fit_by_channel(sub_results, axis_info=axis_info)

    # target_rollup.v1 + target_coherence.v1 — the VERDICT-INERT distillation layer (7-axis roll-up +
    # negative block; thesis/coherence lens). Additive keys in nomination.json; never touch the spine.
    # subtype_facet is threaded in so the roll-up can surface subtype signals prominently.
    target_rollup = build_target_rollup(sub_results, modality_fit_by_channel,
                                        subtype_facet=subtype_facet)
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
        print("[target-profile] --verdict-only/--no-synthesis: skipped Bedrock synthesis "
              "(deterministic verdict spine is authoritative)", file=sys.stderr)
    else:
        print(f"[target-profile] Invoking Bedrock synthesis (biology_axis={axis_info['biology_axis']})...",
              file=sys.stderr)
        # ABSORB (feed-only): the advisory synthesis NARRATES the deterministic 6-dim governance risk
        # roll-up. Computed here as a DETERMINISTIC-only view (grounded_by_axis=None, no file write) — it
        # is grounding-INVARIANT (grounding never moves a bin since the 2026-09-03 demotion), so this
        # pre-synthesis view has bins identical to the artifact risk_rollup computed post-grounding below.
        # Best-effort (None on failure → the prompt simply omits the block). VERDICT-INERT.
        from tp_grounding import build_risk_6dim
        risk_6dim_for_synthesis = build_risk_6dim(sub_results, args.modality, None, out_dir=None)
        tool_schema = _build_synthesis_tool()
        user_prompt = _build_user_prompt(
            args.target, args.indication, sub_results,
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
        llm_output = synthesize_structured(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            tool_name="target_profile_synthesis",
            tool_schema=tool_schema,
        )
        # Attach the deterministic cross-cutting metric legend (sibling key) so a non-computational
        # reader has an accurate reference for the quantities cited across lenses — independent of the
        # LLM's inline glosses. On a successful narration only (a degraded/error dict stays minimal).
        if isinstance(llm_output, dict) and "_synthesis_error" not in llm_output:
            llm_output.setdefault("metric_legend", _METRIC_LEGEND)
            # Verdict-INERT audit: flag any bracketed [rule_id]/[card_id] anchors the model cited that
            # are NOT in the deterministic narrative/fired/card anchor set (possible hallucinated
            # citations). Fail-visible (records, never strips); does not touch the verdict/recommendation.
            llm_output["_anchor_validation"] = validate_synthesis_anchors(
                llm_output, narrative_by_axis, sub_results)
            _inv = llm_output["_anchor_validation"]["n_invented"]
            if _inv:
                print(f"[target-profile] NOTE: {_inv} synthesis citation anchor(s) not in the "
                      f"narrative block (possible hallucination): "
                      f"{llm_output['_anchor_validation']['invented_anchors']}", file=sys.stderr)

    # 2b. Deterministic recommendation gate. A killer sub-verdict FORCES the
    # recommendation regardless of what the LLM chose — the auditable rule wins.
    # We clamp the wrapped {value, _source, ...} in place and record the override
    # in nomination.json + provenance so the gate is never silent.
    gate_action, gate_hits, gate_suppressions = _gate_recommendation(
        sub_results, modality=args.modality, biology_axis=axis_info.get("biology_axis"))
    recommendation_gate = {"fired": bool(gate_action),
                           "suppressed_vetoes": gate_suppressions}
    if gate_suppressions:
        print(f"[target-profile] recommendation gate SUPPRESSED "
              f"{[s['short']+':'+s['verdict']+' via '+s['suppressed_by']['kind'] for s in gate_suppressions]}",
              file=sys.stderr)
    confidence_tier = {"tier": None}
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
            llm_output["overall_recommendation"] = {
                "value": gate_action, "_source": "recommendation_gate"}
        print(f"[target-profile] recommendation GATE fired: forced '{gate_action}' "
              f"(LLM said '{llm_value}') via {[h['short']+':'+h['verdict'] for h in gate_hits]}",
              file=sys.stderr)
        if any(h.get("_fail_closed") for h in gate_hits):
            print("[target-profile] NOTE: recommendation was FAIL-CLOSED (an unrecognized/malformed "
                  "verdict on a veto-capable axis routed to least-permissive — never a silent pass).",
                  file=sys.stderr)
    else:
        # NO kill fired → the positive tier may raise a deterministic confidence
        # FLOOR. F1-safe: this branch is unreachable when a kill fired; it touches
        # ONLY `confidence`, never `overall_recommendation` (never forces nominate).
        tier, pos_hits = _positive_tier(sub_results, modality=args.modality)
        confidence_tier = {"tier": tier, "hits": pos_hits}
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
                    llm_output["confidence"] = {
                        "value": floor, "_source": "positive_tier"}
                confidence_tier["floored_from"] = llm_conf
                confidence_tier["floored_to"] = floor
            print(f"[target-profile] positive tier: {tier} "
                  f"(dims={sorted({h['short'] for h in pos_hits})}); "
                  f"confidence floor {floor}", file=sys.stderr)

    # Gate-complete ceiling: attach the COMPLETE declared hard-gate set with per-gate
    # fired/suppressed/excluded/blind status. Additive — reads the resolved gate state, forces
    # nothing; flows into nomination.json + evidence_package via recommendation_gate.
    recommendation_gate["hard_gates"] = _hard_gates_status(
        sub_results, gate_hits, gate_suppressions)

    # Deciding-axis router: name the load-bearing gate + whether the framework can
    # evidence it. Reports (never predicts): a fired gate is the deciding axis; on abstention,
    # the unevidenced necessity gates are the routing instruction. Purely additive — reads the
    # already-resolved gate/positive state, touches no verdict.
    deciding_axis = _deciding_axis(
        sub_results, gate_action, gate_hits,
        positive_hits=confidence_tier.get("hits", []) or [],
    )
    print(f"[target-profile] deciding axis [{deciding_axis['basis']}]: "
          f"{deciding_axis.get('routing', '')}", file=sys.stderr)

    # Gate scorecard (deterministic, top-of-report): 8-gate rows from the gate registry, 4-state
    # status reusing the nomination-gate policy. Also emitted in nomination.json.
    scorecard = _gate_scorecard(sub_results, deciding_axis, modality=args.modality)
    # target_call.v1 (target_report consolidation, Wave 1 — ADDITIVE): a unified DECISION view composed
    # over the spine objects just built (recommendation_gate/confidence_tier/deciding_axis/scorecard) +
    # target_rollup.block, adding the authoritative recommendation value + a dissent block. Verdict-inert;
    # recommendation_gate stays the sole owner. The spine keys remain top-level until renderers migrate.
    target_call = build_target_call(recommendation_gate, confidence_tier, deciding_axis, scorecard,
                                    overall_recommendation=llm_output.get("overall_recommendation"),
                                    target_rollup=target_rollup)
    catalogue_rows = _catalogue_rows_from_sub_results(sub_results)

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
            args=args, sub_results=sub_results, gate_action=gate_action,
            recommendation_gate=recommendation_gate, confidence_tier=confidence_tier,
            deciding_axis=deciding_axis, validation_summary=validation_summary,
            # subtype-first-class-evidence (Option A): populate context.subgroup_spec + the
            # subtype_resolved block ONLY when the run is subtype-scoped (byte-stable default).
            subtypes=subtypes, subtype_facet=subtype_facet,
            # verdict-INERT decision facets (previously nomination.json-only) into synthesis.decision_facets
            # + the composed modality into context, so the cross-evidence integrator can consume them.
            certainty_by_axis=certainty_by_axis,
            cross_gate_shared_evidence=cross_gate_shared_evidence,
            fragility=fragility, competitor_crossref=competitor_crossref,
            # factored-record consumers (M4): per-modality favorability + over-precision audit, so the
            # cross-evidence integrator sees per-MODALITY calls + magnitude fragility, not just the scalar.
            modality_fit_by_channel=modality_fit_by_channel, magnitude_borderline=magnitude_borderline,
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
    if run_ground and ep_path is not None:
        try:
            from tp_grounding import resolve_axes, auto_ground
            axes = resolve_axes(ground_spec)
            print(f"[target-profile] auto-grounding axes {axes} over {ep_path.name} "
                  f"(indication term {ground_ind!r}; verdict-inert)...", file=sys.stderr)
            produced = auto_ground(args.target, ground_ind, ep_path, args.out, axes)
            grounded_by_axis.update(produced)
            print(f"[target-profile] auto-grounded {sorted(produced)} → grounded_<axis>.json in {args.out}",
                  file=sys.stderr)
        except Exception as e:  # noqa: BLE001 — grounding is substrate/display context, never blocks a run
            print(f"[target-profile] WARN: auto-grounding failed ({type(e).__name__}: {e}); "
                  "continuing without grounded substrate", file=sys.stderr)

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
        hypothesis = auto_hypothesis(
            ep_path, args.out, modality=args.modality,
            risk_path=(str(risk_path) if risk_assessment is not None else None),
            grounded_by_axis=grounded_by_axis,
        )

    # --emit evidence-package: RETURN after emitting the deterministic machine envelope (written above),
    # skipping every nomination-oriented render (composite panel / md / html / nomination.json /
    # provenance). The spine it reads is byte-identical to a nomination run.
    if args.emit == "evidence-package":
        assert_write_set(args, _written)   # envelope-only write-set (evidence_package recorded above)
        print(f"[target-profile] wrote {ep_path} (evidence-package; deterministic, LLM-free)")
        print(f"Recommendation: {gate_action or '(no gate fired)'}")
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
    figures_dir = fig.figures_dir
    composite_rel = fig.composite_rel
    card_figures = fig.card_figures

    # 3b. Render + emit markdown artefact (Shape A — enriched).
    md = _render_target_profile_md(
        args.target, args.indication, sub_results, llm_output, invoked_lenses,
        composite_figure_relpath=composite_rel,
        deciding_axis=deciding_axis,
        ordinal_matrix=ordinal_matrix,
        presence_facet=presence_facet,
        actionability_mode=actionability_mode,
        archetype_companion=archetype_companion,
        nomination_scorecard=nomination_scorecard_facet,
        risk_rollup=risk_rollup,   # canonical deterministic risk_6dim (the ONE source md/html/json share)
        recommendation_gate=recommendation_gate,   # so the recommendation renders as advisory + surfaces
                                                    # any LLM↔deterministic-gate disagreement as a tension
    )
    write_artifact(args.out, "markdown", md, _written)

    # 3c. Render + emit the static HTML governance artifact (self-contained; inlines the
    # composite SVG). Pure projection — never blocks emission on failure.
    try:
        composite_svg = fig.composite_svg
        htmldoc = _render_target_profile_html(
            args.target, args.indication, sub_results, llm_output, invoked_lenses,
            deciding_axis=deciding_axis, ordinal_matrix=ordinal_matrix,
            scorecard=scorecard, composite_svg_path=composite_svg,
            catalogue_rows=catalogue_rows, recommendation_gate=recommendation_gate,
            card_figures=card_figures, figures_dir=figures_dir,
            presence_facet=presence_facet,
            selectivity_facet=selectivity_facet,
            risk_assessment=risk_assessment, grounded_by_axis=grounded_by_axis,
            hypothesis=hypothesis, confidence_tier=confidence_tier,
            risk_rollup=risk_rollup, addressable_population=addressable_population,
            embed="self_contained" if getattr(args, "self_contained", False) else "interactive",
            target_rollup=target_rollup, target_coherence=target_coherence,
            full_package=getattr(args, "full_package", False),
        )
        write_artifact(args.out, "html", htmldoc, _written)
        print(f"[target-profile] wrote {args.out}/target_profile.html", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[target-profile] WARN: HTML render failed: {e}", file=sys.stderr)

    # Governance / reproducibility. Build the governance block via the SHARED
    # _skills_common.build_governance so it can no longer drift from compose-dashboard's — same keys,
    # same construction, one source. Uses the 5-field validation_summary composed above (shared with
    # the --emit evidence-package path). release_pin is a pass-through (target-profile reads live and
    # does not auto-resolve the release); honest default 'unpinned'.
    governance = build_governance("live_latest", args.release_pin or "unpinned", validation_summary)
    # Additive target-profile annotation (does NOT alter the shared 3-key core → no schema drift):
    governance["_note"] = (
        "target-profile reads live data; release auto-resolution is a deferred data-catalog "
        "follow-on, so release_pin is 'unpinned' unless supplied via --release-pin.")

    # target_report.v1 (docs/UNIFIED_OUTPUT_CONTRACT.md) — ADDITIVE unified per-target object composed by
    # REFERENCE over the target-level facets built above (target_call + the rollups). Verdict-inert;
    # target_call owns the recommendation. The originals stay top-level until consumers migrate to read
    # target_report; this is the scaffold the later consolidation collapses into.
    target_report = build_target_report(
        target_call=target_call, target_rollup=target_rollup, target_coherence=target_coherence,
        ordinal_matrix=ordinal_matrix, modality_fit_by_channel=modality_fit_by_channel,
        modality_conjunction=modality_conjunction, risk_rollup=risk_rollup, subtype_facet=subtype_facet,
        biomarker_facet=biomarker_facet, fragility=fragility, heterogeneity=heterogeneity,
        cross_gate_shared_evidence=cross_gate_shared_evidence, magnitude_borderline=magnitude_borderline,
        certainty_by_axis=certainty_by_axis, addressable_population=addressable_population,
        actionability_mode=actionability_mode, competitor_crossref=competitor_crossref,
        archetype_companion=archetype_companion, nomination_scorecard=nomination_scorecard_facet,
        nomination_predictive_score=nomination_predictive_score, skill_reports=skill_reports)

    nomination = {
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "target": args.target,
        "indication": args.indication,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "governance": governance,
        "invoked_lenses": invoked_lenses,
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
        # Biomarker convergence facet (Q12, Part 3c): corroboration + stratification + preferred_assay.
        # A FACET (not a gate) — informs confidence + patient-selection; never mints a nominate.
        "biomarker_facet": biomarker_facet,
        # Subtype convergence facet (Part 3c integration layer): the per-molecular-subtype cross-axis
        # convergence (expression / dependency / mutation-frequency). A FACET (not a gate) — defines
        # patient-selection strata + informs confidence; never mints a nominate.
        "subtype_facet": subtype_facet,
        # target_rollup.v1 + target_coherence.v1 — the VERDICT-INERT distillation layer: a 7-axis
        # roll-up + a NEGATIVE cross-axis block (no positive scalar) + a PROMINENT subtype block, and a
        # thesis/coherence lens on top. Additive; never touch the spine above.
        "target_rollup": target_rollup,
        "target_coherence": target_coherence,
        # Presence cross-modal reconciliation facet (2026-08-17): tumor-presence's per-modality
        # presence matrix + RNA→protein proxy-quality + normal-tissue comparators. A FACET (not a
        # gate) — surfaces cross-modal tension the one-word presence verdict hides + frames tumor
        # presence against the normal-tissue window. Presence ∉ _SHORT_TO_GATE, so it never moves
        # the recommendation. None when tumor-presence supplied no facet.
        "presence_facet": presence_facet,
        # Selectivity facet: tumor-selectivity's 8-question leading table + WIN/DIST/INT/SAFE +
        # the tumor-vs-normal WINDOW gate. A FACET (not a gate) — selectivity's verdict is owned by its
        # resolver + veto clamp; never moves the recommendation. None when tumor-selectivity supplied none.
        "selectivity_facet": selectivity_facet,
        # Dependency claim-vector facet (P2 phase 3-claim): functional-requirement's SIGNAL decomposition
        # (claim_vector + key_signals + confidence annotations). A FACET (not a gate) — the SIGNAL half;
        # the per-axis certainty roll-up is certainty_by_axis. None when FR supplied no facet.
        "dependency_facet": dependency_facet,
        "modality_conjunction": modality_conjunction,
        # Competitor cross-reference facet (2026-08-24): OT competitor field vs the framework's own
        # surface-modality-fit verdict — competition density + modality validated/contrarian +
        # differentiation hooks. A FACET (not a gate); never moves the recommendation. None when
        # differentiation supplied no competitor signal.
        "competitor_crossref": competitor_crossref,
        # Fragility facet (verdict-inert flip-stability): worst-case single-rule flip-fragility over the
        # decision-relevant axes + a `contested` flag (declarative threshold). A structural sensitivity
        # measure ("how solid is this call?"), NOT a probability — informs the reader, never mints or
        # moves a recommendation (target_index/contested touch neither the gate nor confidence).
        "fragility": fragility,
        # Heterogeneity facet (verdict-inert): cross-context dispersion (comparator / modality /
        # subtype). A stratified-opportunity signal the pooled verdict hides; never moves the call.
        "heterogeneity": heterogeneity,
        # Cross-gate shared-evidence (verdict-inert): which gate verdicts share an input card (correlated,
        # not independent corroboration) — the measured cross-gate redundancy made visible for the roll-up.
        "cross_gate_shared_evidence": cross_gate_shared_evidence,
        "addressable_population": addressable_population,
        "actionability_mode": actionability_mode,
        # Per-axis (strength, certainty) sidecar (CERTAINTY_MODEL), keyed by sub-skill short. A
        # verdict-INERT reliability projection (coverage + verdict-disjoint corroboration +
        # coverage-gap unknown_mass) for the reader/panel; NOT in sub_verdicts, never moves the gate.
        "certainty_by_axis": certainty_by_axis,
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
    }
    write_artifact(args.out, "nomination", json.dumps(nomination, indent=2, default=str), _written)

    provenance = {
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "target": args.target,
        "indication": args.indication,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "governance": governance,
        "invoked_lenses": invoked_lenses,
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
        ] + ([] if args.no_figures else [
            "figures/target_profile_at_a_glance.png",
            "figures/target_profile_at_a_glance.svg",
        ]) + [f"grounded_{ax}.json" for ax in sorted(grounded_by_axis)],
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
            backends = ([b.strip() for b in args.report_backends.split(",") if b.strip()]
                        if args.report_backends else None)
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
                args.out, target=args.target, indication=args.indication, sub_results=sub_results,
                skill_name=SKILL_NAME, skill_version=SKILL_VERSION,
                generated_at=provenance["generated_at"], subtypes=subtypes, modality=args.modality,
                has_figures=not args.no_figures, has_evidence_package=ep_path is not None,
                has_narrative=True)
            print(f"[target-profile] --full-package: wrote per-sub-skill packages + {mpath.name} "
                  f"(+ MANIFEST.md); evidence_package.json {'present' if ep_path else 'ABSENT'}")
        except Exception as e:  # noqa: BLE001 — persistence side-artifact must never break the run
            print(f"[target-profile] WARN: --full-package manifest failed "
                  f"({type(e).__name__}: {e}); core artifacts already written", file=sys.stderr)

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
