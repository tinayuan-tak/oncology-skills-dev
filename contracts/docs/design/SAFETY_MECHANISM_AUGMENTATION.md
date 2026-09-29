# Augmenting the Safety (F) and Mechanism (D) gates — dataset brainstorm

**Status:** backlog / design note (2026-07-21). No code. Names candidate datasets to move these two
thin gates from "one signal" toward decision-grade. Prioritization column = my recommendation.

## Why these two are the thinnest gates

- **Safety (F)** today = `gnomad-lof-constraint` (germline LoF intolerance) + `normal-tissue-liability`
  (HPA IHC breadth, and only partially wired). That is a *germline-genetics* proxy + one *normal-tissue*
  axis. It says almost nothing about the on-target toxicity that actually kills oncology programs:
  cardiac/hepatic/hematologic liability, tissue-specific essentiality, or clinical AE precedent.
- **Mechanism (D)** today = `signaling-network-mechanism` (SIGNOR-tagged OmniPath subset → MoA class).
  A single curated interactome. It's advisory-only (doesn't move the verdict), one-directional-prone,
  and blind to pathway context, complex membership, and functional MoA (kinase/enzyme class, PPI
  interface druggability, dependency-of-the-pathway).

Both are `partial` in gate_coverage — honest, but they need real second/third axes.

---

## Safety (F) — candidate augmenting datasets

| Dataset | What it adds | Access / license | Priority |
|---|---|---|---|
| **DepMap common-essential / normal-cell essentiality** (already in-house: Chronos) | The single most decision-relevant safety axis we DON'T yet use for F: is the target a pan-essential / broadly-required gene? A common-essential target = on-target toxicity in normal proliferating tissue. We compute this for Gate C — reuse the SAME Chronos scalar as a *safety* read (a pan-essential is a C-positive AND an F-liability). Zero new data. | in-house | **HIGH — do first** |
| **GTEx normal-tissue expression** (already in-house via recount3) | Which normal tissues express the target + at what level → on-target-off-tumor tissue map. We have GTEx for the selectivity gate (cell C); reuse it as the normal-tissue-breadth axis for F (esp. heart/CNS/liver/marrow). Complements HPA IHC with quantitative RNA. | in-house | **HIGH** |
| **HPA IHC (protein, normal tissues)** — finish wiring | normal-tissue-liability is only partially wired (3/5 surface cards data-blocked). Completing the HPA IHC read is the nearest-term win — pathologist-scored protein in essential tissues. | HPA (CC-BY-SA) | **HIGH** |
| **IMPC / MGI mouse knockout phenotypes** | Systemic in-vivo consequence of full KO — lethality, organ-specific phenotypes. The best *functional* germline-safety signal beyond gnomAD's statistical constraint. Maps target→mammalian phenotype terms. | IMPC (open), MGI (open) | **MEDIUM-HIGH** |
| **ClinVar / OMIM germline disease** | Is the target a known germline-disease gene (haploinsufficiency, dominant-negative)? Direct human safety precedent for modulating it. | ClinVar (public), OMIM (license) | **MEDIUM** |
| **FDA FAERS / clinical AE precedent for the target's DRUG CLASS** | If the target or its pathway has clinical agents, their AE profile IS the safety readout. Highest-value but license/curation-heavy (overlaps the G differentiation gate's Cortellis wall). | FAERS (open) / Cortellis (license) | **MEDIUM (data-heavy)** |
| **Single-cell normal atlases (HCA / Tabula Sapiens)** | Cell-type-resolved normal expression — catches the "bulk-normal looks clean but one essential cell-type expresses it" failure (e.g. cardiomyocyte, HSC). The sc_rna modality the taxonomy already names as unbuilt. | open | **MEDIUM (new modality)** |

**Safety recommendation:** the top 3 are effectively FREE (in-house Chronos + GTEx + finishing HPA)
and turn F from "germline proxy" into "germline + normal-tissue-RNA + normal-tissue-protein +
pan-essentiality" — a real multi-axis safety gate. IMPC is the best-value NEW ingest (functional
in-vivo). Sequence: reuse-in-house first, then IMPC, then sc atlases.

---

## Mechanism (D) — candidate augmenting datasets

| Dataset | What it adds | Access / license | Priority |
|---|---|---|---|
| **Reactome pathway membership** (partially referenced, not a first-class card) | Which pathways the target sits in + its role — the "pathway context" the single SIGNOR interactome lacks. Turns "has upstream/downstream partners" into "is the rate-limiting node in pathway X." | Reactome (CC0) | **HIGH** |
| **CORUM protein complexes** (already ingested! `corum-5.3`) | Complex membership → is the target an obligate subunit (paralog-buffered? complex-essential?)? Directly augments MoA AND cross-links to the paralog-buffering (C) evidence. We ALREADY have this in the catalog — just not wired to Mechanism. | in-house (CORUM 5.3) | **HIGH — near-free** |
| **UniProt functional annotation / EC + domain architecture** | Enzyme class, catalytic residues, domain families → the *molecular* MoA (kinase/protease/GPCR/TF) that determines druggability strategy. Complements the network position with molecular function. | UniProt (CC-BY) | **HIGH** |
| **OmniPath FULL (beyond the SIGNOR subset)** | We use only the SIGNOR-tagged, causally-directed subset for licensing cleanliness. The broader OmniPath (with provenance filtering) adds directionality + more partners — directly widens the current single-source signal. | OmniPath (mixed; filter by license) | **MEDIUM** |
| **Kinase–substrate (already have kinome-atlas!) + PhosphoSitePlus** | For kinase targets, substrate relationships = mechanistic PD markers. Kinome-atlas is in-house; PSP adds curated phospho-substrate edges (license-check). | in-house kinome + PSP (license) | **MEDIUM** |
| **Dependency-of-the-pathway (DepMap co-essentiality)** | Genes co-essential with the target = its functional module (often better than curated interactomes at finding the real mechanism). In-house Chronos co-essentiality matrix. The "data-driven mechanism" complement to curated networks. | in-house | **MEDIUM-HIGH** |
| **PROTAC/ternary feasibility features** (E3 ligase proximity, surface lysines) | For the degrader modality lens — mechanistic feasibility of induced degradation. Ties Mechanism (D) to modality-fit. | mixed | **LOW (modality-specific)** |

**Mechanism recommendation:** two near-free in-house wins first — **CORUM complexes** (already
ingested) + **DepMap co-essentiality** (data-driven mechanism module) — plus **Reactome pathway
membership** and **UniProt EC/domain** (both open, high-value). That moves D from "one curated
interactome, advisory-only" to "curated network + complex membership + data-driven co-essentiality +
molecular function" — and gives it enough substance to graduate from advisory to verdict-affecting.

---

## Cross-cutting note (ties to gate-model v2)

Several of these are the **same in-house measurement feeding a new gate** — the v2 `reports_into` /
many-to-many pattern:
- DepMap Chronos → already Gate C (Required); ALSO a Gate F (Safety) pan-essentiality liability.
- CORUM complexes → Mechanism (D) AND paralog-buffering (C, complex-essential paralogs).
- GTEx normal → Selectivity (B) comparator AND Safety (F) normal-tissue map.

So the cheapest augmentation isn't new ingestion — it's **wiring existing in-house data into these
gates via reports_into**. Recommend a first slice that does exactly that (Chronos→F, CORUM→D,
GTEx→F) before any new dataset ingest.
