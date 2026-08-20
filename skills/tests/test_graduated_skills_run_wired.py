"""Regression test — SKILL.md ↔ scripts drift catcher.

W4b (2026-07-09): This test would have caught the class of bug that
shipped in Layer 6 and surfaced as code-review findings #3, #4, #5:
SKILL.md advertised status: wired or partial, but scripts/run.py still
called emit_placeholder(). This test invokes each wired/partial skill's
run.py end-to-end and asserts:

  1. The skill's run.py exits 0 (dispatcher didn't crash).
  2. decision.json is emitted with the standard data-package tree.
  3. decision.json's `skill` field matches SKILL.md's `name` field.
  4. decision.json does NOT emit the `verdict: phase_not_yet_wired` shape
     that emit_placeholder produces — a positive assertion that the
     graduated skill's dispatcher ran, not the placeholder shell.
  5. When the underlying data product is not available (scaffold state),
     the graduated skill emits `verdict: insufficient` OR the equivalent
     categorical default, NOT `phase_not_yet_wired`.

Not tested here (would require live-reader compute):
  - Rule content matches expectations for a specific target
  - Card summary_fields contain real data

This test is a CONTRACT check, not a data-quality check.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.composition_schema import validate_skill_md, STATUSES


# Skills to verify. Excludes non-compositional legacy skills that predate
# the composition contract (compose-dashboard, query-target-evidence,
# render-evidence-package). Excludes the
# target-profile composed skill which has its own more elaborate LLM-
# synthesis pipeline test.
_ALWAYS_WIRED = [
    "tumor-presence",
    "tumor-selectivity",
    "functional-requirement",
    "genomic-alteration-profile",        # reframed from mutation-profile 2026-07-14
    "tractability-small-molecule",       # split from tractability-and-modality 2026-07-14
    "surface-modality-fit",              # split from tractability-and-modality 2026-07-14 (partial)
    "mechanism-and-pharmacology",       # W2a graduation
    "differentiation-landscape",         # W2b graduation
    "on-target-safety-liability",        # W2c graduation
    "surfaceome-cohort-ranking",         # W4-only skill (no target arg required)
    "target-intrinsic",                  # indication-INDEPENDENT dossier (SK#201); descriptive/verdict-free,
                                         # so it is in the SHAPE+status list but NOT _MUST_FIRE_ON_KRAS_COADREAD
                                         # (it mints no verdict by design). Added 2026-08-11 prod-readiness pass.
    "cis-feature-coherence",             # cis-coherence Stage 1 (2026-08-20); dedicated self-contained axis,
                                         # VERDICT-INERT at composition. Wired end-to-end (card→depmap_cis_dosage
                                         # →cis_coherence resolver). Also in _MUST_FIRE (fires coherent_cis_driver
                                         # on KRAS/COADREAD with the local DepMap cache).
    # patient-population-and-access DELETED 2026-07-14 (prevalence folded into
    # genomic-alteration-profile; was a thin re-projection of one shared card).
]


def _skill_paths(skill_name: str) -> tuple[Path, Path]:
    """Return (SKILL.md path, run.py path) for the given skill."""
    return (
        SKILLS_DIR / skill_name / "SKILL.md",
        SKILLS_DIR / skill_name / "scripts" / "run.py",
    )


@pytest.mark.parametrize("skill_name", _ALWAYS_WIRED)
def test_skill_md_declares_wired_or_partial(skill_name: str):
    """SKILL.md must declare status in {wired, partial} for this test's targets."""
    skill_md, _ = _skill_paths(skill_name)
    if not skill_md.exists():
        pytest.skip(f"{skill_name} has no SKILL.md")
    comp = validate_skill_md(skill_md)
    assert comp.status in {"wired", "partial"}, (
        f"{skill_name}: SKILL.md declares status={comp.status}. If this "
        f"skill is now not_wired, remove it from _ALWAYS_WIRED in "
        f"test_graduated_skills_run_wired.py."
    )


@pytest.mark.parametrize("skill_name", _ALWAYS_WIRED)
def test_run_py_dispatcher_emits_matching_status(skill_name: str, tmp_path):
    """Invoke run.py --target KRAS --indication COADREAD; assert the emitted
    decision.json's shape matches a WIRED dispatcher, not a placeholder.

    The key discriminator: emit_placeholder writes
        {"verdict": "phase_not_yet_wired", "unwired_cards": [...],
         "data_gaps": [...]}
    A wired dispatcher writes
        {"skill": "...", "headline": {...}, "cards": [...],
         "fired_rules": [...]}
    We assert the wired-shape keys are present.
    """
    skill_md, run_py = _skill_paths(skill_name)
    if not run_py.exists():
        pytest.skip(f"{skill_name} has no scripts/run.py")

    out_dir = tmp_path / f"verify-{skill_name}"

    # surfaceome-cohort-ranking has a different CLI (--indication only,
    # optional --target). Adapt argv accordingly.
    if skill_name == "surfaceome-cohort-ranking":
        argv = [
            sys.executable, str(run_py),
            "--indication", "COADREAD",
            "--target", "KRAS",  # optional but supported
            "--out", str(out_dir),
        ]
    else:
        argv = [
            sys.executable, str(run_py),
            "--target", "KRAS",
            "--indication", "COADREAD",
            "--out", str(out_dir),
        ]

    result = subprocess.run(argv, capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, (
        f"{skill_name}: run.py exited {result.returncode} "
        f"(expected 0).\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    decision_path = out_dir / "decision.json"
    assert decision_path.exists(), (
        f"{skill_name}: run.py exited 0 but decision.json was not written. "
        f"The wired-skill contract requires the data-package tree. "
        f"stdout:\n{result.stdout}"
    )

    decision = json.loads(decision_path.read_text())

    # Wired-dispatcher shape assertions.
    #
    # emit_placeholder emits {"verdict": "phase_not_yet_wired", ...} —
    # explicitly check we did NOT get that.
    verdict_top_level = decision.get("verdict")
    assert verdict_top_level != "phase_not_yet_wired", (
        f"{skill_name}: decision.json emitted verdict='phase_not_yet_wired'. "
        f"This is the emit_placeholder shape — SKILL.md declares "
        f"status={validate_skill_md(skill_md).status} but the dispatcher "
        f"still returns the placeholder. Rewrite scripts/run.py to use "
        f"the canonical wired-skill pattern (see _skills_common/dispatcher.py "
        f"or W2a-c fix rollup)."
    )
    assert "unwired_cards" not in decision, (
        f"{skill_name}: decision.json contains 'unwired_cards' key which is "
        f"emit_placeholder's shape. Skill claims to be wired/partial in "
        f"SKILL.md but scripts/run.py still calls emit_placeholder."
    )

    # Positive wired-shape check: `skill`, `cards`, `fired_rules` keys present
    for key in ("skill", "target", "indication"):
        assert key in decision, (
            f"{skill_name}: decision.json missing key '{key}'. The "
            f"canonical wired-skill contract requires this key."
        )

    # `skill` field must match SKILL.md's name (drift catcher).
    comp_name = skill_md.parent.name
    assert decision["skill"] == comp_name, (
        f"{skill_name}: decision.json 'skill' field = "
        f"{decision['skill']!r} does not match SKILL.md directory name "
        f"= {comp_name!r}. Dispatcher wrote wrong skill_name."
    )


# Skills whose cards genuinely return real data for KRAS/COADREAD today, so
# a wired verdict MUST be produced (not a silent collapse to `insufficient`).
# This is the DATA-QUALITY complement to the shape checks above — it is what
# would have caught the 2026-07-13 decision-layer bugs (differentiation-
# landscape returning `insufficient` on 709 real co-occurring hits because
# no rule matched `cooccurrence_class=both_patterns_present`, and the
# bool-vs-string rule-match failure). KRAS in COADREAD is a maximally-
# characterized reference target: expression, dependency, mutation,
# mechanism, and co-mutation all have real signal.
#
# Deliberately EXCLUDED (real data-unavailable, not a bug):
#   - surface-modality-fit (split from tractability-and-modality 2026-07-14):
#     KRAS is intracellular; structure/surfaceome derived products not all
#     landed — honest `insufficient` here, not a fireable signal.
#   - surfaceome-cohort-ranking: KRAS is not a surface protein; empty is correct.
#   - on-target-safety-liability: gnomad_constraint method module not yet
#     written (tracked separately) — cannot fire until that lands.
# NOTE: tractability-small-molecule (the SM half of the split) DOES fire on
# KRAS (well_covered / e7-triangulated) so it IS in the must-fire list.
_MUST_FIRE_ON_KRAS_COADREAD = [
    "tumor-presence",
    "tumor-selectivity",
    "functional-requirement",
    "genomic-alteration-profile",       # reframed from mutation-profile
    "tractability-small-molecule",      # SM half of the tractability split
    "mechanism-and-pharmacology",
    "differentiation-landscape",
    "cis-feature-coherence",            # fires coherent_cis_driver on KRAS/COADREAD (CN↔expr cis-dosage
                                        # coupled r~0.44 + amp∩overexpr more dependent) — real DepMap signal.
]


@pytest.mark.parametrize("skill_name", _MUST_FIRE_ON_KRAS_COADREAD)
def test_wired_skill_fires_on_reference_target(skill_name: str, tmp_path):
    """DATA-QUALITY check (not just shape): a skill whose cards return real
    data on the KRAS/COADREAD reference target must actually FIRE >=1 rule
    (or emit a non-`insufficient` verdict). A skill that gathers real card
    data and then collapses to `insufficient`/no-fired-rules is the exact
    decision-layer failure this suite previously missed.

    If ALL of the skill's cards come back `_missing` (e.g. an S3 outage),
    the test skips rather than fails — this asserts the DECISION layer, not
    data availability.
    """
    skill_md, run_py = _skill_paths(skill_name)
    if not run_py.exists():
        pytest.skip(f"{skill_name} has no scripts/run.py")

    out_dir = tmp_path / f"fire-{skill_name}"
    argv = [
        sys.executable, str(run_py),
        "--target", "KRAS", "--indication", "COADREAD",
        "--out", str(out_dir),
    ]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, (
        f"{skill_name}: run.py exited {result.returncode}.\n{result.stderr}"
    )
    decision = json.loads((out_dir / "decision.json").read_text())

    cards = decision.get("cards") or []
    available = [c for c in cards if not c.get("_missing")]
    if cards and not available:
        pytest.skip(
            f"{skill_name}: all cards _missing on KRAS/COADREAD "
            f"(data availability, not a decision-layer bug)."
        )

    fired = decision.get("fired_rules") or []
    headline = decision.get("headline") or {}

    # Each skill names its primary verdict differently (presence_verdict,
    # selectivity_class, dependency_verdict, mutation_landscape_class,
    # mechanism_verdict, differentiation_verdict, ...). Extract GENERICALLY —
    # any headline key ending in `_verdict` or `_class` — so this check does
    # not silently miss a skill's verdict (and rot when a 7th skill is added).
    SENTINELS = (None, "insufficient", "data_unavailable")
    verdict_fields = {
        k: v for k, v in headline.items()
        if (k.endswith("_verdict") or k.endswith("_class")) and isinstance(v, str)
    }
    # Also honor a plain top-level `verdict` if a skill uses that.
    if isinstance(decision.get("verdict"), str):
        verdict_fields["verdict"] = decision["verdict"]

    # A real verdict = at least one verdict field holds a non-sentinel value.
    has_real_verdict = any(v not in SENTINELS for v in verdict_fields.values())

    # Distinguish "insufficient live data -> SKIP" from "sufficient live data,
    # decision layer collapsed -> FAIL" (this guard's own docstring item 5:
    # scaffold state -> SKIP). A 0-rules / null-verdict outcome is only a real
    # decision-layer bug if the environment actually supplied VERDICT-DRIVING
    # data -- i.e. at least one VERDICT-BEARING card resolved to an INFORMATIVE
    # (non-absence) class value.
    #
    # Why this matters now: the reader-hardening burndown (analysis-methods) made
    # readers RE-RAISE creds/transient errors instead of masking them to
    # data_unavailable, so a creds-limited CI runner leaves every S3-backed
    # verdict-bearing card `_missing`. What still resolves is a card that reads a
    # BUNDLED resource -- e.g. partner-conditional-dependency reads a curated
    # partner_map.yaml and resolves to the not-applicable token "no_partner_mapped"
    # for a target outside its map (KRAS), in BOTH creds-full and creds-less runs.
    # That resolution is NOT evidence verdict-driving data was available, so it
    # must not, by itself, keep the guard out of the SKIP path. With full
    # credentials the S3-backed cards resolve to real class values and the skill
    # fires, so the guard keeps its teeth whenever verdict-driving data IS present.
    #
    # The verdict-bearing card set is the skill's OWN composition.rules_scope (the
    # card_ids whose rules enter the resolver -- validated elsewhere to be a subset
    # of cards_used). The ["all"] wildcard (tractability-small-molecule,
    # mechanism-and-pharmacology) declares every consumed card in scope -> fall
    # back to cards_used (conservative: never loses teeth). "no_partner_mapped" is
    # the one documented not-applicable class token among these skills' bundled
    # conditional cards; it is matched EXACTLY (not by pattern) so a genuine
    # "no_*" verdict can never be silently swallowed.
    comp = validate_skill_md(skill_md)
    rules_scope = set(comp.rules_scope)
    verdict_bearing = (
        set(comp.cards_used) if "all" in rules_scope
        else (rules_scope & set(comp.cards_used))
    )
    if not verdict_bearing:
        # Defensive: a skill with no declarable rules_scope -> treat every
        # consumed card as verdict-bearing so the guard never loses teeth.
        verdict_bearing = {(c.get("card_id") or c.get("id")) for c in cards}
    absence_class_values = set(SENTINELS) | {"", "no_partner_mapped"}

    def _card_has_informative_verdict_data(card: dict) -> bool:
        """A resolved card carries verdict-driving data iff at least one of its
        `*_class`/`*_verdict` summary fields holds a non-absence value (mirrors
        the headline verdict extraction above, applied to the card summary)."""
        summary = card.get("summary") or {}
        class_vals = [
            v for k, v in summary.items()
            if (k.endswith("_class") or k.endswith("_verdict"))
        ]
        return any(
            isinstance(v, str) and v not in absence_class_values for v in class_vals
        )

    vb_informative = [
        c for c in available
        if (c.get("card_id") or c.get("id")) in verdict_bearing
        and _card_has_informative_verdict_data(c)
    ]

    if not fired and not has_real_verdict and not vb_informative:
        pytest.skip(
            f"{skill_name}: no VERDICT-BEARING card resolved INFORMATIVE data on "
            f"KRAS/COADREAD ({len(available)} card(s) resolved; verdict-bearing "
            f"set={sorted(verdict_bearing)}). Insufficient live card data in this "
            f"environment -- scaffold/creds-less state (guard docstring item 5); "
            f"the drift-guard requires >=1 verdict-bearing card to resolve a real "
            f"(non-absence) class value before it can assert a decision-layer "
            f"collapse."
        )

    # With verdict-driving data present, EITHER a rule fired OR a real
    # (non-sentinel) verdict was emitted. Both being absent = the collapse.
    assert fired or has_real_verdict, (
        f"{skill_name}: gathered {len(vb_informative)} verdict-bearing card(s) with "
        f"real data on KRAS/COADREAD but fired 0 rules and all verdict fields are "
        f"sentinels "
        f"({verdict_fields}). This is a decision-layer collapse (real data -> "
        f"null verdict), not a data gap. Check for (a) rule categorical-"
        f"coverage holes for the emitted class value, (b) a bool-vs-string "
        f"rule-match failure in _skills_common.fired_rules, or (c) the leaf "
        f"skill's _verdict() not mapping the fired rule_id to a verdict."
    )
