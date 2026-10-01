"""_skills_common — shared harness for compositional skills.

Skills answer a question by fetching a card set, running the axis
interpretation-rules over the summaries, optionally projecting fired rules
onto a modality lens, and emitting a decision artefact. This harness lets
each skill assemble a projection of the framework's machinery in ~30 lines.

Public API:
  1. `resolve_cards`     — pull live summaries for a card_id list, via
                            the already-wired dispatchers (rehomed into
                            _skills_common off the retired compose-dashboard).
  2. `fired_rules`       — apply the axis interpretation-rules to those
                            summaries, returning a flat biology-first list
                            of matched rules.
  3. `modality_lens`     — OPTIONAL projector from fired rules to a
                            modality (small_molecule / degrader / adc /
                            bite / antibody).
  4. `make_decision_json` — build the decision.json payload.

Zero new dispatcher code, zero new rule content — skills are PROJECTIONS
over the same layers Macro (the retired compose-dashboard, now in
_skills_common) used.

Design principles:
- Biology-first output. Modality is a post-hoc lens, not a native output
  attribute. Skills answering (target, indication) questions must produce
  valid output whether or not modality is specified.
- Rules are loaded via the canonical `rules_loader.load_interpretation_rules`
  function (this package). Skills do NOT reach into compose-dashboard's
  private `_synthesis._load_interpretation_rules` — decoupled since 2026-07-07.
- The live-reader dispatcher (`_live_readers`) lives HERE in _skills_common — one
  canonical dispatch table across the framework (rehomed 2026-08-21 off the retiring
  compose-dashboard skill; consumed via `_import_dispatcher()` / `from ._live_readers import`).

Layout (2026-10-01, #2380): the harness proper is split into three cohesive
submodules — `cards` (card resolution + per-card provenance), `rule_engine`
(the axis rule-firing engine + modality lens), and `decision` (decision.json
assembly + card accessors). This `__init__` is a thin re-export shim so the
public import surface — `from _skills_common import resolve_cards`,
`fired_rules`, `make_decision_json`, and the private helpers skills/tests reach
for — is unchanged.
"""

from __future__ import annotations

from pathlib import Path

from .cards import (  # noqa: F401 — public re-export
    _data_unavailable_field,
    _import_dispatcher,
    _is_data_unavailable,
    _primary_class_value,
    _read_cards_process,
    _read_cards_threaded,
    _resolve_one_card,
    _resolve_one_card_star,
    _summary_is_unavailable,
    _trace_event_to_dataset,
    card_declared_method_calls,
    card_input_manifest_ids,
    resolve_cards,
)
from .composite_panel import render_composite_panel  # noqa: F401 — public re-export
from .composition_schema import Composition, CompositionError, validate_skill_md  # noqa: F401 — public re-export
from .composition_schema import validate as validate_composition  # noqa: F401 — public re-export
from .decision import card_summary, get_card_field, make_decision_json  # noqa: F401 — public re-export
from .llm import EVIDENCE_ONLY_DIRECTIVE, synthesize_structured  # noqa: F401 — public re-export
from .placeholder import emit_placeholder  # noqa: F401 — public re-export
from .resolver import load_resolver, resolve_or_raise, resolve_verdict, resolve_verdict_for_gate  # noqa: F401
from .rule_engine import (  # noqa: F401 — public re-export
    _record_matches,
    _rule_values_equal,
    fired_rules,
    modality_lens,
)
from .rules_loader import (  # noqa: F401 — public re-export
    TARGET_CONTRACTS,
    filter_rules_by_card_ids,
    load_interpretation_rules,
)
from .write_package import write_package  # noqa: F401 — public re-export

# --- environment discovery -------------------------------------------------

SKILLS_DIR = Path(__file__).resolve().parent.parent

# Framework version stamp (rehomed 2026-08-21 from the retired compose-dashboard compose_phase1).
# Emitted into evidence-package / decision.json governance blocks by every engine.
FRAMEWORK_VERSION = "2.0.0"
