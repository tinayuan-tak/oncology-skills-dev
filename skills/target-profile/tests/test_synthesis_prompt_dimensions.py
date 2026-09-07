"""Guard: the synthesis _SYSTEM_PROMPT dimension list must match the live fan-out (arch-review R14).

_SYSTEM_PROMPT hardcodes the evidence dimensions it tells the LLM to expect. It had drifted — it named
DROPPED dimensions (mutation [reframed to genomic_alteration], population + cohort_rank [deleted from the
fan-out]) and OMITTED live ones (surface_modality, synthetic_lethal_partners, combinatorial_dependency,
target_intrinsic, cis_coherence). A stale prompt mis-primes the reasoner (asks for dimensions that don't
exist; never mentions ones that do). This pins it to the current fan-out so it can't re-drift silently.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SKILLS = Path(__file__).resolve().parent.parent.parent  # for _skills_common
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SKILLS))

from tp_synthesis_prompt import _SYSTEM_PROMPT  # noqa: E402


def test_dropped_dimensions_absent_from_prompt():
    """Deleted/renamed fan-out dimensions must not be advertised to the LLM as expected inputs."""
    low = _SYSTEM_PROMPT.lower()
    for dropped in ("population,", "cohort_rank", "cohort rank"):
        assert dropped not in low, f"stale dropped dimension {dropped!r} still in _SYSTEM_PROMPT"


def test_live_dimensions_mentioned_in_prompt():
    """The prompt must name the current fan-out dimensions (at least the ones added/renamed since the
    original 10-dimension list)."""
    low = _SYSTEM_PROMPT.lower()
    for live in (
        "genomic alteration",
        "surface/modality",
        "synthetic-lethal",
        "combinatorial dependency",
        "cis-coherence",
        "target-intrinsic",
    ):
        assert live in low, f"live fan-out dimension {live!r} missing from _SYSTEM_PROMPT"
