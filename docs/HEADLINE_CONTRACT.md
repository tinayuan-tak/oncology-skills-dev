# Headline contract — the canonical per-skill headline block

**Status:** design note + reference implementation (2026-08-21). Exemplar: `tumor-presence`.
**Scope:** the tail-end *headline message* every target-profiling question-skill emits — a concise
**verdict + confidence + top-tension** triple, as deterministic text **and** a renderer-agnostic hero
figure — and how the four downstream consumers (plots, cross-reasoning agents, persistent store,
dashboards) read it.

---

## 1. Why

The skills already compute a verdict and a rich distilled corpus (`claim_vector`, `key_signals`,
`question_table`, per-card summaries). Turning that into ONE concise headline was the weak, inconsistent
part:

- **No single headline object.** Verdict, confidence, and the top tension lived in three unrelated
  places; the verdict was spelled four different ways across consumers.
- **Hero figures for only 2 of 13 skills**, in two incompatible formats, with no naming convention.
- **The distilled fields were second-class downstream** — carried as unvalidated additions, ignored by
  the dashboard renderer.

This contract gives all four consumers a single object to read: `decision.headline.headline_block`.

## 2. The block

Built by `_skills_common/headline_core.build_headline(...)` — a **verdict-INERT** projection over the
already-computed `claim_vector` + `key_signals` (never feeds a rule/resolver/gate; the verdict spine
stays byte-stable, frozen by each skill's golden/replay test).

```
headline_block = {
  "verdict":      {call, phrase, gate, driving_rule_id},   # the ONE canonical verdict spelling
  "confidence":   {level ∈ strong|moderate|weak|insufficient, basis, coverage:{n_measured,n_axes,n_critical_measured}},
  "top_tension":  {text, source, severity} | null,          # the single sharpest tension
  "headline_text": "<call> — <confidence> confidence[; tension: <...>].",   # deterministic, NOT the LLM
  "hero":         { kind, verdict, confidence, tension, axes[] },   # renderer-agnostic plot_data
  "provenance":   [ {axis, card_id, fields}, ... ],         # lifted from claim_vector atoms
}
```

### Derivation rules (the discipline)
- **confidence** = weakest-link over the **measured** axes' `corroboration` tiers, then:
  capped one step by any active `conflict`; capped at `weak` when fewer than half the decision-critical
  axes are measured; `insufficient` when no critical axis is measured. A skill that emits the
  authoritative CERTAINTY_MODEL sidecar (`strength_certainty`/`certainty_by_axis`) passes it in and it
  **wins** over the derived value. Confidence is SEPARATE from signal (never averaged into it).
- **top_tension** = the single highest-severity item among claim-vector `conflict`s (severity = the
  conflicting claim's signal tier — a conflict on a *strong* claim matters most), the `key_signals`
  caveat (severity 1), and an optional skill-specific source (e.g. presence's cross-modal
  `presence_headline_conflict`). `null` when clean.
- **gap ≠ absent.** An `unmeasured` axis lowers coverage; it is never a measured floor.

## 3. Per-skill declaration

A skill declares a `HeadlineSpec` (the `claim_vector`-axes analogue): the verdict `gate`, a
`verdict_label` (token → phrase), the `axis_keys` + `axis_labels` to surface, the decision-`critical_axes`
whose coverage floors confidence, and an optional `tension_extra(headline)` skill-specific tension
source. See `tumor-presence/scripts/run.py::_PRESENCE_HEADLINE_SPEC`.

## 4. The hero figure

`_skills_common/headline_hero.py` is the ONE reference renderer. `emit_headline_hero(decision,
figures_root)` reads only the decision (offline, no live read — matching
`FIGURE_EMITTER_ARCHITECTURE_2026-08-19.md` §3.1) and writes the single canonical convention:

```
figures/figure_headline_hero.svg    # hand-rolled SVG (house style)
figures/figure_headline_hero.png    # matplotlib twin (best-effort; SVG+JSON are primary)
figures/figure_headline_hero.json   # the headline_block payload
```

Honesty discipline (mirrors `presence_claims_figure`): bar length = ordinal signal tier only;
corroboration is a separate dot channel; an unmeasured axis is a **hatched gap**, never a zero bar;
conflicting axes carry a ⚠ marker.

## 5. Consumer contract

| Consumer | Reads | How |
|---|---|---|
| **Plots** | `headline_block.hero` | `emit_headline_hero` (offline); or any renderer over the `hero` payload |
| **Cross-reasoning agents** | `synthesis.claim_vectors[short].headline_block` | canonical verdict + confidence + provenance, alongside the claim_vector atoms |
| **Persistent store** | `verdict.call` / `confidence.level` | one canonical verdict field (ends the 4-way spelling drift) |
| **Dashboards** | `headline_block` | `render-evidence-package` renders a leading "Skill Headlines" table |

Carried through each skill's `_synthesis_facet` (key `headline_block`) → the target-profile fan-out →
`synthesis.claim_vectors[short].headline_block`, declared first-class in the target-contracts
`evidence_package.schema.json` (`$defs.headline_block`). The `synthesis` block intentionally does **not**
set `additionalProperties:false` (consumer-owned `sub_verdicts` / `recommendation_gate` still ride).

## 6. Rollout

Exemplar = `tumor-presence` (A/B/C/D axes). Fan-out to the other 12 skills is mechanical: import
`build_headline`/`HeadlineSpec`, declare a `HeadlineSpec`, set `hl["headline_block"]`, add
`emit_headline_hero` to the skill's figure hook, and add `"headline_block"` to its `_SYNTHESIS_FACET_KEYS`.
No verdict-spine change; each skill's replay/golden fixture is regenerated to include the new key.
