# Dashboard Rendering Contract

`schema_version: 2.0.0` · derived 2026-09-10 from the reader source of truth (major: the 2026-09-16
substrate-pivot ★/○ inversion — evidence is load-bearing, the verdict is optional; see the spine section)
`skills/_skills_common/report_render/ir.py` (verified line-by-line) + producers
`target-profile/scripts/{tp_facets,tp_fanout,tp_manifest}.py`, `_skills_common/{skill_report,evidence_graph}.py`.

## Why this file exists

`report_render` is the **sole** dashboard renderer. It reads the backend output structures
(`nomination.json` / `target_report`, per-subskill `evidence_graph`, and the composed
`evidence_graph` index) **directly** to build the composed target dashboard and every per-subskill
`dashboard.html`. This document is the **stable field interface** those readers depend on. Any
consolidation of the backend output shapes MUST preserve the fields listed here, or explicitly
migrate them (see [Migration rules](#migration-rules)). It is the guard every backend refactor
validates against.

The reader code is the source of truth — this doc is derived from it and must be re-derived if the
`ir.py` builders change.

## The requiredness model (read this first)

`ir.py` is **uniformly fail-soft**: every input read is `.get(...)`, `... or {}` / `or []`,
`isinstance`-guarded, or a truthy check gating the one indexed access. There are **no** unguarded
index/attribute reads on input dicts — a missing field never raises; it just drops the block or
field. (The five direct-index lines — `report["confidence"|"top_tension"|"question_table"|
"per_phase_metrics"|"provenance"]`, ir.py:344/346/384/393/411 — are each gated by an immediately
preceding `.get(...)` truthy check on the same key.)

Therefore requiredness here is about **content, not crashes**:

- **★ LOAD-BEARING** — its absence/renaming silently removes *decision-relevant* content (the
  recommendation, a skill's call/polarity, the deciding axis, a risk bin). These are the interface
  that must not break even though the code won't error. **Treat a rename/move of any ★ field as a
  breaking change.**
- **○ optional / degrade-gracefully** — absence drops a cosmetic or supplementary block only.

## The load-bearing spine (the ★ set at a glance)

**★/○ INVERSION, 2026-09-16 (substrate pivot).** The load-bearing spine is now the **evidence**, not the
verdict. A report must carry the measured evidence and, per its `lead` preset, a non-empty headline — the
verdict fields still compute and still render, but they are no longer the interface whose absence guts the
report. Relevance is the per-field salience role (`field_descriptor`), so the evidence carrier shows every
salient datum, ranked by nothing.

**★ LOAD-BEARING (the evidence):**
- the salient measured fields — `skill_reports[<short>].evidence_graph.cards[].key_evidence` projected by
  `_evidence_signals_block` into the `EVIDENCE_SIGNALS` block (rows + `rollup`); the block renders in every
  backend and, when present, as the composed dashboard's "Measured evidence" view.
- `target_report.skill_reports[<short>].{role, evidence_graph}` — the evidence graph itself (cards +
  questions) and the role that scopes it.
- per-subskill `evidence_graph.{questions[], cards[]}`.

**★ LEAD (per preset, so a demoted headline cannot silently empty):**
- `lead == "recommendation"` ⇒ `target_call.recommendation` present in the rendered report.
- `lead == "deciding_axis"` ⇒ `target_call.deciding_axis.deciding_axes[].short` present.
- `lead == "none"` ⇒ neither required.

**○ optional — still computed + rendered, no longer the guaranteed spine (the demotion):**
- `target_call.{recommendation, confidence, deciding_axis, gate, dissent}` — a legitimate summary, and the
  Decision-lens view still shows the verdict strip; but a report may lead with evidence instead.
- `skill_reports[<short>].{call, polarity}` — the per-skill verdict tokens.
- `risk_6dim[<dim>].bin` — the governance roll-up bin.
- composed index `evidence_graph.verdict.{recommendation, confidence.level, deciding_shorts}`.
- per-subskill `evidence_graph.verdict.{call, polarity}`.

## Renderer-green gate (run after every backend structural change)

From the home checkout, `TARGET_CONTRACTS_ROOT` pinned, `PYTHONPATH` including `skills/`:

```bash
export PATH="$HOME/.pixi/bin:$PATH"
export TARGET_CONTRACTS_ROOT=$HOME/rnd-computational-biology-oncology-target-contracts
cd $HOME/rnd-computational-biology-oncology-claude-oncology-skills
pixi run pytest skills/_skills_common/tests/ skills/target-profile/tests/ -q
# live render smoke — must not raise AND must still emit the sections:
PYTHONPATH="$PWD/skills" pixi run python -c "import json;from _skills_common.report_render import render_report;\
h=render_report(json.load(open('$HOME/dev/framework-runs/examples/KRAS-COADREAD/2026-09-09-review/nomination.json')),\
preset='full',backend='html');assert 'class=\"dim' in h and 'hgrid' in h and 'qtab' in h;print('render OK',len(h))"
```
Baseline on trunk (2026-09-10): `render OK 123838`.

---

## Artifact 1 — `target_report` (`target_report.v1`) + `skill_reports` spine
Producer: `tp_facets.build_target_report`; spine from `_skill_reports_by_short` ← `tp_fanout` carry ←
`skill_report.build_skill_report`.

| field path | reader fn(s) | ★/○ | notes (ir.py line) |
|---|---|---|---|
| `target_report` | `build_ir` | ★ | 2128 `nomination.get("target_report") or {}` — spine root |
| `.target_call` | `build_ir`, `_deciding_axis_block`, `_synthesis_banner_block` | ★ | 2130; top-level `nomination.target_call` fallback honored |
| `.target_call.recommendation` | `build_ir` header, `_synthesis_banner_block` | ★ | 2214, 1312 — authoritative call |
| `.target_call.confidence` | `build_ir` header | ★ | 2215 |
| `.target_call.deciding_axis` | `build_ir`, `_deciding_short`, `_deciding_axis_block` | ★ | 2135, 2216, 1054 |
| `.target_call.deciding_axis.deciding_axes[].{short,framework_can_evidence,gate,gate_name}` | `_deciding_short`, `_deciding_axis_rank`, `_deciding_axis_block` | ★ | 114/119/131-136/1058 — `short` picks headline axis |
| `.target_call.deciding_axis.{routing,basis}` | `_deciding_axis_block` | ○ | 1067-1068 |
| `.target_call.dissent[].{source,detail,resolved_to,blocking_axes}` | `build_ir` header | ○ | 2219 (producer tp_facets:1682-1705) |
| `.target_call.gate` | `build_ir` header | ★ | 2220 |
| `.target_call.gate.hard_gates[].{short,status}` | `build_ir` (reconciled_shorts) | ★ | 2141-2145 — `status=="reconciled"` de-escalates negatives |
| `.target_call.gate.suppressed_vetoes[].{short,verdict,suppressed_by.{safe_channels,kind}}` | `build_ir` (`_safety_escape`) | ★ | 2178-2189 — safety→modality hero escape |
| `.target_call.gate_scorecard` | carried, not destructured | ○ | opaque within `gate`/header |
| `.skill_reports` | `build_ir`, `_card_figure_owner_map`, `_risk_6dim_block`, `_route_synthesis_to_lenses`, `_literature_comention_summary`, `_clinical_precedent_card` | ★ | 2129 — `{short: skill_report}` |
| `.skill_reports[<short>].call` | `_build_section`, `_signals_overview_block`, `_signals_scatter_block` | ★ | 323/529 |
| `.skill_reports[<short>].polarity` | `_build_section`, signals blocks, `_sort_key` | ★ | 305-306/508/1388/2240 — diverging strip + ordering |
| `.skill_reports[<short>].role` | `_build_section`, `_card_figure_owner_map`, `_in_scope`, `build_ir` | ★ | 299/266/2235 — `"gating"` gates strip/scatter |
| `.skill_reports[<short>].honest_phrase` | `_build_section`, signals blocks, `_dim_member_reading` | ○ | 327/530/1411/598 |
| `.skill_reports[<short>].confidence(.level/.basis/.coverage)` | `_build_section`, `_signals_scatter_block`, `_skill_graph_header` | ○ | 331/343-344/1409-1410; `.basis` is the FALLBACK when the graph verdict omits basis (1586) |
| `.skill_reports[<short>].top_tension` | `_build_section` | ○ | 345-346 |
| `.skill_reports[<short>].evidence_graph` | `_build_section`, `build_composed_evidence_graph`, `_dim_member_reading`, `_clinical_precedent_card` | ★ | 310-311/364/388/399/406 — see Artifact 4 |
| `.skill_reports[<short>].subgroup_signals` | `_build_section`, `_subgroup_scatter_block`, `_subgroup_bands_block` | ○ | 363-374/1504/1540 |
| `.skill_reports[<short>].claim_chips[].evidence` | `_chips_block`, `_literature_comention_summary` | ○ | 152/2030-2039 |
| `.skill_reports[<short>].question_table[](.cross_lens/.informs_lens/.question)` | `_build_section`, `_cross_cutting_block` | ○ | 338/382-384/1997-2005 |
| `.skill_reports[<short>].per_phase_metrics` | `_build_section` | ○ | 392-393 |
| `.skill_reports[<short>].figures[].{caption,slot,kind,path}` | `_figure_blocks` | ○ | 167-179 |
| `.skill_reports[<short>].provenance.{cards_used,fired_rule_ids,driving_rule_id}` | `_signals_overview_block`, `_route_synthesis_to_lenses`, `_build_section` | ○ | 518/533-534/1337-1342/410 |
| `.risk_6dim` | `_risk_6dim_block`, `_literature_risk_block`, `build_composed_evidence_graph` | ★ | 601-745/1021/1858 — dict-of-dims or list |
| `.risk_6dim[<dim>].bin` | `_risk_6dim_block._emit`, `_literature_risk_block._omics_bin`, composed index | ★ | 699/1025/1861 — feeds rank/engine_blind |
| `.risk_6dim[<dim>].chain[]` `[source,read,level]` | `_risk_6dim_block._dim_members` | ○ | 654-685 — fallback members |
| `.risk_6dim[<dim>].blind_spots` | `_risk_6dim_block._emit` | ○ | 704 |
| `.risk_6dim[<dim>].grounded_findings[].{finding,kind,severity,cited_pmids/pmids}` | `_risk_6dim_block._emit` | ○ | 706-714 |
| `.risk_6dim[<dim>].mitigation` | `_risk_6dim_block._emit` | ○ | 705/728 |
| `.archetype.phenotype_mixture` | `_target_characterization` | ○ | 1228-1264 |
| `.archetype.nearest_analogs[].{target,indication,archetype_label,distance}` | `_target_characterization` | ○ | 1240-1252 |
| `.addressable_population` | `build_ir` header (opaque) | ○ | 2208 — no subfields read |
| `.modality_fit.by_channel[<ch>].{fit,limiting_axis,by_axis,masked_by_axis}` | `_modality_fit_channels`, `build_composed_evidence_graph` | ○ | 951-975/1846-1854 (producer tp_facets:584-620) |
| `.evidence_matrix`/`ordinal_matrix`.{rows,axes.columns,legend,_disclaimer} | `_modality_matrix_block`, `_row_has_on_scale` | ○ | 991-1007/922 |
| `.thesis.{thesis.primary,coherence.{class,caveats}}` | `_coherence_block`, `build_ir` | ○ | 900-916/2151-2197 |
| `.subtype_convergence.{verdict,n_subtypes_evaluated,per_subtype,axes_available,convergent_subtypes,associated_subtypes}` | `_subtype_block`, composed index | ○ | 1152-1171/1873 |
| `.biomarker.{verdict,preferred_assay,stratification_role,corroboration_role.alteration_role,biomarker_hypotheses[].{intended_use,basis,evidence_strength},intended_uses}` | `_biomarker_block` | ○ | 1175-1206 |
| `.evidence_graph` (composed index) | `_composed_fingerprint_block` | ○ | 1444 — see Artifact 6 |

## Artifact 2 — `llm_synthesis` (alias `llm_output`)
Advisory / verdict-inert. Read via `_llm_val` (unwraps `{value}`). Producer = upstream synthesis stage.

| field path | reader fn(s) | ★/○ | notes (ir.py line) |
|---|---|---|---|
| `llm_synthesis` \| `llm_output` | `_synthesis_block`, `_synthesis_banner_block`, `_route_synthesis_to_lenses`, `build_ir`, `_groundedness_summary` | ★ | 822/1304/1329/2159 |
| `.executive_summary(.value)` | `_synthesis_block`, `_synthesis_banner_block`, `build_ir` hero | ★ | 825/1307/2166 |
| `.tension_analysis(.value)` | `_synthesis_block`, `_route_synthesis_to_lenses` | ○ | 826/1361 |
| `.exec_bullets[].{text,polarity,cites}` | `_synthesis_block` | ○ | 830-835 (`cites` passed whole; `card_ids`/`citation_ids` not destructured in IR) |
| `.top_arguments`/`.arguments[].{claim,text,argument}` | `_synthesis_block` | ○ | 827/847 |
| `.top_arguments_for`/`.top_arguments_against[]` | `_route_synthesis_to_lenses` | ○ | 1355-1359 |
| `.rationale(.value)`/`.context_read(.value)` | `_synthesis_block`, `build_ir` | ○ | 836 |
| `.overall_statement`/`.headline` | `build_ir` hero | ○ | 2163 |
| `.overall_recommendation`/`.recommendation` | `_synthesis_banner_block` | ★ | 1311 — compared to `target_call.recommendation` (mismatch banner) |
| `._anchor_validation.{n_cited,n_invented,invented_anchors,invented_by_field}` | `_groundedness_summary` | ○ | 2066-2069 — invented tokens/fields forwarded to the trust badge (verdict-inert flag-only telemetry) |

## Artifact 3 — `hypothesis` (cross-evidence)
Read only by `_cross_evidence_summary`. `None` under `--no-hypothesis`.

| field path | reader fn | ★/○ | notes (ir.py line) |
|---|---|---|---|
| `hypothesis` | `_cross_evidence_summary` | ○ | 791 |
| `.edges[].{from_dimension,to_dimension,type}` | " | ○ | 797-799 |
| `.verdict.{computed,proposed_by_agent}` | " | ○ | 801 |
| `.uncertainty.{overall_certainty,limiting_dimension}` | " | ○ | 802/810-811 |
| `.defensibility.{n_fully_traceable,n_clauses,n_coherence_violations}` | " | ○ | 806/813 |

## Artifact 4 — per-subskill `evidence_graph` (`skill_reports[<short>].evidence_graph`)
Producer: `evidence_graph.build_evidence_graph` (+ `_build_key_evidence`/`_build_literature`/`_build_narrative`).

| field path | reader fn(s) | ★/○ | notes (ir.py line / producer) |
|---|---|---|---|
| `.target`/`.indication` | `_build_section` h1, `_card_chain_block` | ○ | 320-321/1805 (prod 624-625) |
| `.verdict.call` (else `.id`) | `_skill_graph_header` | ★ | 1581 (prod 609-610) |
| `.verdict.polarity` | `_skill_graph_header` | ★ | 1582 (prod 611) |
| `.verdict.driving_rule_id` | `_skill_graph_header` | ○ | 1584 (prod 612) |
| `.verdict.confidence.level` | `_skill_graph_header` | ○ | 1585 (prod 613) |
| `.verdict.confidence.coverage.{n_measured,n_axes,n_critical_measured}` | `_skill_graph_header` | ○ | 1587-1591 (prod 613) |
| `.verdict.confidence.basis` | `_skill_graph_header` | ○ | 1586 — **read but NOT produced on the graph verdict** (prod emits `{level,coverage}` only); reader falls back to `skill_report.confidence.basis` |
| `.verdict.top_tension.{text,severity}` | `_skill_graph_header` | ○ | 1592-1594 (prod 614-618) |
| `.questions[]` | `_evidence_fingerprint_block`, `_card_chain_block`, `_skill_graph_header` (count) | ★ | 1595/1611 (prod 549-564) |
| `.questions[].{id,seq,text}` | fingerprint, card_chain | ○ | 1611-1648/1849-1851 (`seq` not in prior known set) |
| `.questions[].signal.{polarity,tier}` | fingerprint, card_chain | ○ | 1637/1903 |
| `.questions[].confidence.{dots,level}` | fingerprint, card_chain | ○ | 1645/1906 |
| `.questions[].card_ids` | fingerprint, card_chain | ○ | 1613 |
| `.questions[].literature_axis_ids` | fingerprint, card_chain | ○ | 1626/1860 |
| `.questions[].evidence_refs[].label` / `.prose.primary` | `_card_chain_block` | ○ | 1897/1907 |
| `.cards[]` | fingerprint, card_chain, `_skill_graph_header` (count) | ★ | 1608/1800 (prod 506-523) |
| `.cards[].{id,measurement_type,role,question_ids}` | card_chain | ○ | 1814-1818/1844 |
| `.cards[].signal.{polarity,liability,label}` | fingerprint, card_chain | ○ | 1618-1623/1808 |
| `.cards[].confidence.{dots,n}` | fingerprint, card_chain | ○ | 1622/1825-1826 |
| `.cards[].class.value` | fingerprint, card_chain | ○ | 1623/1811 |
| `.cards[].chain.{dataset_ids,data,rule_id,is_driving,contributes_to_verdict}` | `_card_chain_block`, `_card_scope` | ○ | 1827-1831/1763 (prod 497-503) |
| `.cards[].key_evidence.effect.{metric,value,direction}` | `_format_key_evidence`, `_kegloss`, card_chain | ○ | 1674-1685/1719-1722 (prod 396) |
| `.cards[].key_evidence.significance.{stat,value}` | `_format_key_evidence`, `_kegloss` | ○ | 1687-1688/1724-1731 (prod 400) |
| `.cards[].key_evidence.omnibus.{stat,value}` | `_format_key_evidence` | ○ | 1696-1698 (prod 402) |
| `.cards[].key_evidence.top_strata[].{label,role,value,n,q}` | `_format_key_evidence`, card_chain, `_card_scope` | ○ | 1673-1695/1761/1836 (prod 404) |
| `.cards[].key_evidence.categorical[].value` | `_format_key_evidence` | ○ | 1699-1701 (prod 406) |
| `.cards[].key_evidence.n` | `_kegloss`, card_chain | ○ | 1729 (prod 398) |
| `.cards[].key_evidence.subtype_axis.{restriction_class,driving_axis,per_subtype/strata}` | `_format_key_evidence`, `_card_scope`, `_subtype_rollup` | ○ | 1702-1707/1753/1774-1789 (prod 412) |
| `.cards[].key_evidence.interpretation[]` | `_card_chain_block` (`gauge`/`gauges`) | ○ | 1812/1823-1824 (prod 394) |
| `.literature.axes[].{axis_id,read,agreement_vs_omics,confidence,assertion,question_ids,citation_ids}` | `_literature_axes_block`, fingerprint, card_chain | ○ | 1609/1629-1634/1959-1967/1873-1878 (prod 686-696) |
| `.literature.blind_spots[].{text,why_omics_blind,citation_ids}` | `_literature_axes_block` | ○ | 1971-1973 (prod 714-716) |
| `.literature.overall_consistency` | `_literature_axes_block`, composed index | ○ | 1980/1822 (prod 721) |
| `.literature.key_divergence` | `_literature_axes_block` | ○ | 1981 (prod 722) |
| `.citations[].{id,label,pmid,verified}` | `_literature_axes_block`, card_chain | ○ | 1949/1856/1869 (prod 672-680) |
| `.narrative.exec_bullets[].{text,polarity,cites}` | `_skill_synthesis_block` | ○ | 881 (prod 804) |
| `.narrative.{rationale,relevance}` | `_skill_synthesis_block`, `_dim_member_reading` | ○ | 882/594 (prod 798-799) |

## Artifact 5 — `subskills/<short>/package.json`  (NOT a renderer input)
Producer: `tp_manifest._subskill_package` / `write_full_package`.

**`ir.py` does not read `package.json` at all.** Per-subskill dashboards render from the in-memory
`skill_report` (`synthesis_facet.skill_report`) via `render_skill_report → build_ir_for_skill`
(tp_manifest.py:131-146). `package.json` is a sibling **review** artifact. Its fields
(`cards[].summary`, `fired_rules`, `llm_synthesis`, `claim_vector`, `key_signals`,
`cards[].{card_id,card_version,missing,data_source,figures}`) are producer-only and may be
reshaped without touching the renderer — but keep them stable for downstream review consumers.

## Artifact 6 — composed `evidence_graph` index (`target_report.evidence_graph`)
Reader: `_composed_fingerprint_block`. Producer: `tp_facets.build_composed_evidence_graph`.

| field path | ★/○ | notes (ir.py line / producer) |
|---|---|---|
| `.schema` (`== "composed_evidence_graph.v1"`) | ○ gate | 1445 — block returns None if schema mismatched/absent (byte-stable on pre-index runs) |
| `.skills[].{short,call,polarity,confidence,deciding,literature_consistency,lens}` | ○ | 1447/1458-1470 (prod 1812-1824) |
| `.verdict.{recommendation,confidence.level,deciding_shorts}` | ★ | 1482-1495 (prod 1797-1801) |
| `.edges[]` where `type=="dissent"` `.{from,note,resolved_to}` | ○ | 1484-1488 — other edge types produced but not read by this block (owned by other lenses) |

## Artifact 7 — other top-level `nomination` keys a reader touches

| field path | reader fn(s) | ★/○ | notes (ir.py line) |
|---|---|---|---|
| `nomination.sub_verdicts[<short>].cards_used[]` | `_card_figure_owner_map` | ○ | 258-261 — figure→section join |
| `nomination.card_figures{<card_id>:[{path,type,id,primary,dynamic}]}` | `_figures_by_owner`, `_card_figure_blocks` | ○ | 280/213-244 — run-dir figure join |
| `nomination.narrative_by_axis[<short>].flip_conditions[].{recommendation_flip,to_role,to_verdict,present,rule_id}` | `_flip_conditions_block` | ○ | 1106/1116-1126 — "what would change the call" |
| `nomination.risk_assessment.dimensions[<dim>].{interpretation,cited_pmids/pmids,risk_level,contradicts_deterministic}` | `_risk_6dim_block._literature`, `_literature_risk_block`, `_literature_comention_summary` | ○ | 689-696/1017-1049/2041-2047 |
| `nomination.target_coherence.{thesis.primary,coherence.class}` | `_coherence_block`, `build_ir` | ○ | 900/2152 — fallback for `target_report.thesis` |
| `nomination.ordinal_matrix` | `_modality_matrix_block` | ○ | 991 — fallback for `evidence_matrix` |
| `nomination.modality_fit_by_channel` | `_modality_fit_channels` | ○ | 951 — fallback for `target_report.modality_fit` |
| `nomination.deciding_axis` | `_deciding_axis_block` | ○ | 1054 — top-level fallback |
| `nomination.{target,indication}` | `build_ir` (`_first`) | ○ | 2132-2133 |

## Corrections vs. the originally-assumed field set

Fields assumed load-bearing that the reader does **not** read as stated:
- `skill_reports[<short>].synthesis_facet.{skill_report.evidence_graph, literature_synthesis}` —
  `synthesis_facet` is a `tp_fanout`-internal carrier (tp_fanout.py:1262). By the time data reaches
  `target_report.skill_reports[<short>]`, the facet's `skill_report` **is** that node and its graph is
  read at `.evidence_graph`; `literature_synthesis` is consumed at build time (tp_fanout.py:1244) and
  surfaces as the carried graph's `.literature`.
- `risk_6dim[<dim>].members` — the reader *emits* `members` (`_dim_members`, 643-686); it is not read
  off the input. Input side is `bin`/`chain`/`blind_spots`/`grounded_findings`/`mitigation`.
- `subskills/<short>/package.json.*` — not read by `ir.py` (Artifact 5).
- per-subskill `evidence_graph.verdict.confidence.basis` — read (1586) but not produced on the graph
  verdict (degrades to `skill_report.confidence.basis`).

Load-bearing reader fields that were **missing** from the assumed set (now captured above):
`target_call.gate.hard_gates[]`, `target_call.gate.suppressed_vetoes[]`, `risk_6dim[<dim>].mitigation`,
`llm_synthesis.{overall_recommendation, overall_statement, headline, rationale, arguments,
_anchor_validation}`, `hypothesis.verdict.{computed, proposed_by_agent}`, per-subskill
`evidence_graph.cards[].key_evidence.{omnibus, categorical, n}` + `.cards[].confidence` +
`.literature.key_divergence` + `.questions[].{seq, evidence_refs, prose}` + `.narrative.{rationale,
relevance}`, and the `nomination.{sub_verdicts, card_figures, narrative_by_axis}` figure/flip paths.

## Migration rules

When a backend refactor changes a field this contract lists:
1. **★ fields** — either keep a back-compat alias the reader reads, OR update the `ir.py` reader
   builder(s) in the **same change**, then re-run the renderer-green gate. Never land a ★ rename
   without one of these.
2. **○ fields** — update the reader in the same change where practical; if deferred, note it and
   confirm the block degrades (renders empty, not broken) via the gate.
3. Bump `schema_version` (minor for additive/optional, major for a ★ shape change) and re-derive the
   affected table rows from the reader.
4. Coordinate via `~/.claude/wip-registry.md` — a `report_render` dashboard arc lands PRs off these
   structures; the `ir.py` reader builders are the interface to protect.
