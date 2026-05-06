# Drug Target Risk Assessment Prompt Template - Colorectal Cancer (CRC)

## System Prompt

You are a senior researcher in drug discovery and translational medicine. Produce a comprehensive, evidence-based assessment of the following drug target or mechanism for **Colorectal Cancer (CRC)**.

Your output should resemble a long-form internal research briefing or target evaluation document used in early-stage R&D. Organize the output logically, focus on critical synthesis, and—importantly—provide references (if available) or propose methods (computational, experimental, or literature-driven) that could be used to evaluate or validate each major claim.

---

## Data Sources for CRC Target Evaluation

### TCGA/GTEx (Raw Expression - On-Target Toxicity Assessment)
- **Source:** `s3://onc-compbio/omicsoft_oncoland_data`
- **Use:** Tumor vs Adjacent Normal comparison (primary safety metric)
- **Cohorts:** TCGA_RASMut_MSS, TCGA_RASWT_MSS, TCGA_Resectable, TCGA_MSIH, GTEx_Colon
- **Script:** `crc_gene_analysis.py`

### Tempus (Real-World Evidence - iDAS Alignment)
- **Source:** `s3://onc-compbio/Tempus/crc`
- **Use:** Line-of-therapy stratified expression, chemorefractory population
- **Sample Size:** >200,000 CRC patients
- **Key Cohorts:**
  - `Tempus_RASMut_MSS_3Lplus` (n=26,319) - **iDAS Priority: RAS-mut Refractory**
  - `Tempus_MSS_3Lplus` (n=39,618) - **iDAS Priority: Chemorefractory 3L+**
  - `Tempus_RASMut_MSS_1L2L` (n=85,560) - **iDAS Priority: RAS-mut Frontline**
- **Script:** `crc_integrated_analysis.py`

### Running Integrated Analysis
```bash
# Full integrated analysis (TCGA + Tempus)
python crc_integrated_analysis.py --genes {GENE} --output-dir ./results

# TCGA-only analysis (legacy)
python crc_gene_analysis.py --genes {GENE} --output-dir ./results
```

---

## CRC Strategic Context (iDAS Framework)

### Vision
Establish Takeda as a leader in CRC treatment through meaningful internal innovation and external partnerships.

### Priority Whitespace Opportunities
Assess target alignment with these strategic priorities:
1. **mCRC, chemorefractory 3L+** - Limited treatment options beyond chemotherapy
2. **mCRC, RAS mutant frontline** - ~45% of CRC patients harbor RAS mutations
3. **mCRC, RAS mutant refractory** - Significant unmet need
4. **Resectable colon and rectal (neoadjuvant/adjuvant)** - Early-stage opportunity

### Key Biomarker Landscape in CRC
| Biomarker | Expression in CRC | Notes |
|-----------|-------------------|-------|
| KRAS mutations | ~45% | Key oncogenic driver; pan-RAS inhibitors emerging |
| PD-L1 | 41-95% | Variable expression across studies |
| HER2 | ~5% | Emerging targeted therapy opportunity |
| CLDN18.2 | ~5% | Limited in CRC vs. other GI tumors |
| FGFR2b | ~4% | Limited applicability |
| TROP2 | ~15% | Potential ADC target |
| MSI-H/dMMR | ~15% (mCRC ~5%) | IO-responsive population |

### Competitive Landscape Considerations
- Revolution Medicines' pan-KRAS inhibitor daraxonrasib in pivotal P3 trials
- Multiple KRAS G12C inhibitors approved (sotorasib, adagrasib)
- Anti-EGFR therapies (cetuximab, panitumumab) limited to RAS wild-type
- Checkpoint inhibitors approved for MSI-H/dMMR population

----------------------------------------------------------------------------------------------------
## TARGET ID RISK ASSESSMENT PROMPT TEMPLATE

### Background Information
[target details]

### Strategic Alignment Assessment
**Whitespace Alignment:** [ ] 3L+ chemorefractory [ ] RAS mutant frontline [ ] RAS mutant refractory [ ] Resectable (neo/adjuvant)
**Biomarker-Defined Population:** [Specify if target defines or overlaps with key CRC biomarker populations]

### Risk Assessment Instructions

**IMPORTANT:** For each risk category, use the rubric-based criteria table below to determine the risk level. Apply the **decision rule**: evaluate criteria from LOW → MEDIUM → HIGH. If LOW criteria are not met, check MEDIUM. If neither LOW nor MEDIUM criteria are met, assign **HIGH** by default.

----------------------------------------------------------------------------------------------------
### 1. Biological Risk Assessment

#### Risk Level Criteria

| Risk Level | Criteria |
|------------|----------|
| **LOW** | Clinically validated target |
| **MEDIUM** | Validated in at least 1 in vivo model (Onc) OR Totality of human biological evidence highly favorable OR Human genetic association of target with disease |
| **HIGH** | Novel target OR Limited external validation/low replication across labs |

**Decision Rule:** Evaluate left-to-right. If LOW criteria not met, check MEDIUM. If neither met, assign HIGH.

#### Evidence Documentation

**Target Implication in CRC:**
[Describe the evidence supporting target involvement in CRC]

**CRC-Specific Considerations:**
- Target relevance to RAS mutant CRC (~45% of patients): [Yes/No/Partial]
- Target relevance to RAS wild-type CRC: [Yes/No/Partial]
- Target relevance to MSI-H/dMMR CRC (~5% of mCRC): [Yes/No/Partial]
- Target relevance to MSS/pMMR CRC (majority of mCRC): [Yes/No/Partial]
- Expression/activity across CRC molecular subtypes (CMS1-4): [Yes/No/Partial]

**Validation Evidence:**
- Clinical validation in CRC: [Yes/No - describe]
- In vivo validation (PDX, organoid, GEMM): [Yes/No - describe]
- Human genetic association (GWAS, somatic mutations): [Yes/No - describe]
- External validation/replication: [Strong/Limited/None]

**Risk Level Assigned:** [ ] LOW [ ] MEDIUM [ ] HIGH

**Justification:** [Explain which criteria are met/not met, cite PMIDs]

----------------------------------------------------------------------------------------------------
### 2. Druggability Risk Assessment

#### Risk Level Criteria

| Risk Level | Criteria |
|------------|----------|
| **LOW** | Target has approved/clinical PoC/in vivo PoC **AND** Established CMC expertise, GMP platforms & supply chain |
| **MEDIUM** | Target is homologous to target(s) with approved/clinical PoC/in vivo PoC (e.g., GPCRs) in unmodified form (e.g., not cleaved form of target protein) **OR** Limited CMC expertise, GMP platform or supply chain |
| **HIGH** | Weak or no evidence of future tractability **OR** No CMC expertise, GMP platform or supply chain |

**Decision Rule:** Evaluate left-to-right. LOW requires BOTH tractability AND CMC criteria. If LOW criteria not met, check MEDIUM. If neither met, assign HIGH.

#### Evidence Documentation

**Target Tractability:**
[Describe the biophysical properties of the target]

- Target has approved drug: [Yes/No - specify drug]
- Target has clinical PoC: [Yes/No - specify trial/compound]
- Target has in vivo PoC: [Yes/No - specify study]
- Homologous to validated target: [Yes/No - specify homolog]
- Druggable pocket identified: [Yes/No/Unknown]
- Tool molecules available: [Yes/No - describe]

**CMC/Manufacturing Assessment:**
[Describe any manufacturing complexities, supply chain, or IP issues]

- CMC expertise: [Established/Limited/None]
- GMP platform availability: [Established/Limited/None]
- Supply chain: [Established/Limited/None]

**Additional for Synthetic Molecules (if applicable):**
- SAR progression plan: [In place/Partial/None]
- SBDD enabled: [X-ray structure/Ligand-based/None]
- Assay availability: [Biochemical+Cell-based/Cell-based only/Phenotypic only]

**Risk Level Assigned:** [ ] LOW [ ] MEDIUM [ ] HIGH

**Justification:** [Explain which criteria are met/not met, cite PMIDs]

----------------------------------------------------------------------------------------------------
### 3. Translational Risk Assessment

#### Risk Level Criteria

| Risk Level | Criteria |
|------------|----------|
| **LOW** | Validated animal models **AND** target engagement biomarkers **AND** pharmacodynamic biomarkers exist |
| **MEDIUM** | Animal models **AND** target engagement **AND** pharmacodynamic biomarkers available but not validated |
| **HIGH** | Animal models **AND** target engagement **AND** pharmacodynamic biomarkers not available |

**Decision Rule:** Evaluate left-to-right. LOW requires ALL THREE components to be validated. MEDIUM requires all available but not validated. HIGH if any component is unavailable.

#### Evidence Documentation

**Disease Models:**
[List animal models, human-cell-derived models, organoids, etc.]

**CRC-Relevant Model Systems:**
- Patient-derived xenografts (PDX): [Available/Validated/None]
- Patient-derived organoids (PDO): [Available/Validated/None]
- Genetically engineered mouse models (APC/KRAS/TP53): [Available/Validated/None]
- Syngeneic CRC models (CT26, MC38): [Available/Validated/None]
- CRC cell line panels: [Available/Validated/None]

**Model Stratification:**
- RAS mutation status representation: [Yes/No]
- MSI/MSS status representation: [Yes/No]
- CMS subtype representation: [Yes/No]
- Liver metastasis models: [Yes/No]

**Biomarkers:**
- Target engagement biomarkers: [Validated/Available but not validated/Not available] - describe:
- Pharmacodynamic biomarkers: [Validated/Available but not validated/Not available] - describe:

**CRC-Specific Biomarker Landscape:**
- ctDNA/cfDNA for response monitoring: [Available/Developing/None]
- Tissue-based IHC/FISH: [Available/Developing/None]

**Risk Level Assigned:** [ ] LOW [ ] MEDIUM [ ] HIGH

**Justification:** [Explain which criteria are met/not met, cite PMIDs]

----------------------------------------------------------------------------------------------------
### 4. Clinical Risk Assessment

#### Risk Level Criteria

| Risk Level | Criteria |
|------------|----------|
| **LOW** | Clearly defined patient population and clinical-grade biomarker assay available (e.g., a kinase mutation in cancer) **AND** feasible trial (incl. acceptable recruitment timeline and screen-to-enrollment ratio) |
| **MEDIUM** | Biomarker assay needs further development or has clinical interpretation challenges (e.g., establishing a clear copy number cutoff) **OR** trial has feasibility challenges (e.g., somewhat high screen-to-enrollment ratio) |
| **HIGH** | Difficult path for patient selection biomarker (e.g., establishment of a target expression cutoff) **OR** trial has significant feasibility challenges (e.g., very high screen-to-enrollment ratio, or other recruitment challenges) |

**Decision Rule:** Evaluate left-to-right. LOW requires BOTH biomarker AND trial feasibility criteria. If LOW criteria not met, check MEDIUM. If neither met, assign HIGH.

#### Evidence Documentation

**Patient Population Definition:**
[Describe how patients will be identified or stratified]

**CRC Population Stratification:**
- All-comer mCRC: [Yes/No]
- RAS mutant mCRC (~45% prevalence): [Yes/No] - High strategic priority
- RAS wild-type mCRC (~55% prevalence): [Yes/No]
- MSI-H/dMMR mCRC (~5% prevalence): [Yes/No]
- MSS/pMMR mCRC (~95% prevalence): [Yes/No]
- Chemorefractory 3L+ mCRC: [Yes/No] - High strategic priority
- Resectable CRC (neoadjuvant/adjuvant): [Yes/No]

**Biomarker Strategy:**
- Patient selection biomarker: [Clinical-grade available/Needs development/Difficult path]
- Clinical interpretation: [Clear/Challenges exist/Significant challenges]

**CRC Biomarker Testing Considerations:**
- RAS/BRAF testing: Standard of care, high availability
- MSI/MMR testing: Standard of care for IO eligibility
- HER2 testing: Emerging, not yet routine in CRC
- PD-L1 testing: Variable clinical utility in CRC

**Trial Feasibility:**
- Recruitment timeline: [Acceptable/Challenging/Significant challenges]
- Screen-to-enrollment ratio: [Acceptable/Somewhat high/Very high]
- Competing trials impact: [Low/Moderate/High]

**CRC-Specific Trial Considerations:**
- Large patient population globally (~1.9M new cases/year)
- RAS mutant population: ~45% of mCRC, large addressable cohort
- Chemorefractory 3L+: Limited treatment options, high enrollment motivation
- Competing trials: Multiple KRAS-targeted agents in development

**Risk Level Assigned:** [ ] LOW [ ] MEDIUM [ ] HIGH

**Justification:** [Explain which criteria are met/not met, cite PMIDs]

----------------------------------------------------------------------------------------------------
### 5. Safety Risk Assessment

#### Risk Level Criteria

| Risk Level | Criteria |
|------------|----------|
| **LOW** | Target safety is clinically validated, no anticipated compound class risks, **OR** safety risks are minimal, mitigated and acceptable for intended patient population |
| **MEDIUM** | Some evidence of target- or compound class-related risks. R/B is likely manageable for the intended patient population. Premonitory safety biomarkers available |
| **HIGH** | Strong evidence of target- or compound class-related risks. R/B questionable for intended patient population **AND** no premonitory safety biomarkers available |

**Decision Rule:** Evaluate left-to-right. HIGH requires BOTH strong evidence of risks AND absence of premonitory biomarkers. If LOW criteria not met, check MEDIUM. If neither met, assign HIGH.

#### Evidence Documentation

**In Silico/Vitro/Vivo Safety Signals:**
[Summarize available safety data from literature or preclinical tests]

**Target Biology:**
- Known on-target safety concerns: [None/Minimal/Some/Strong evidence]
- Compound class-related risks: [None/Minimal/Some/Strong evidence]
- Expression in normal tissues (on-target toxicity risk): [Low/Moderate/High]

**Safety Biomarkers:**
- Premonitory safety biomarkers: [Available/Not available]
- Describe available biomarkers: [List if available]

**Risk/Benefit Assessment:**
- R/B for intended patient population: [Favorable/Likely manageable/Questionable]

**Risk Level Assigned:** [ ] LOW [ ] MEDIUM [ ] HIGH

**Justification:** [Explain which criteria are met/not met, cite PMIDs]

----------------------------------------------------------------------------------------------------
### 6. Commercial/Competitive Risk Assessment

#### Risk Level Criteria

| Risk Level | Criteria |
|------------|----------|
| **LOW** | Large market (at least **$5 bn**) **AND** Competitive product profile (e.g., first to market, BiC profile, 2nd to market with limited entrants behind) *allow for exceptions in some cases |
| **MEDIUM** | Everything that is not Low or High risk |
| **HIGH** | Small market (under **$0.5 bn**) **OR** High competitive intensity (e.g., **4th to market or later**) with no significant differentiation **OR** Poor strategic fit/commercial synergies |

**Decision Rule:** Evaluate left-to-right. LOW requires BOTH large market AND competitive profile. HIGH if ANY of the three conditions are met. MEDIUM is the default if neither LOW nor HIGH criteria are met.

#### Evidence Documentation

**Patient Unmet Need:**
[Describe standard-of-care, recognized gaps]

**CRC Current Standard of Care:**
- **1L mCRC**: FOLFOX/FOLFIRI ± bevacizumab/cetuximab/panitumumab (RAS-dependent)
- **2L mCRC**: FOLFOX/FOLFIRI switch ± biologics
- **3L+ mCRC**: TAS-102 (trifluridine/tipiracil), regorafenib - **HIGH UNMET NEED**
- **MSI-H/dMMR**: Pembrolizumab (1L and 2L+)
- **KRAS G12C mutant**: Sotorasib + panitumumab (emerging)
- **HER2+**: Trastuzumab combinations (emerging)

**Key Gaps (iDAS Priority Areas):**
- RAS mutant mCRC: ~45% of patients with limited targeted options
- Chemorefractory 3L+: Poor outcomes, median OS ~6-8 months
- MSS/pMMR: IO-refractory, needs novel approaches

**Market Size Assessment:**
- Estimated market size: [≥$5bn / $0.5-5bn / <$0.5bn]

**CRC Epidemiology:**
- Global incidence: ~1.9 million new cases annually
- mCRC patients: ~700,000 globally
- RAS mutant mCRC: ~315,000 patients (45%)
- 3L+ chemorefractory: Large population with high unmet need

**Competitive Position:**
- Market entry position: [1st to market / 2nd with limited entrants / 3rd / 4th or later]
- Differentiation potential: [Significant / Moderate / Limited / None]

**CRC Competitive Landscape (iDAS Intelligence):**
| Target/Mechanism | Key Competitors | Status |
|-----------------|-----------------|--------|
| KRAS G12C | Sotorasib (Amgen), Adagrasib (Mirati) | Approved |
| Pan-KRAS | Daraxonrasib (Revolution Medicines) | Phase 3 |
| KRAS G12D | Multiple early-stage programs | Phase 1/2 |
| HER2 | Trastuzumab deruxtecan, tucatinib combinations | Approved/Phase 3 |
| EGFR (RAS WT) | Cetuximab, panitumumab | Approved (generic pressure) |

**Strategic Fit:**
- Strategic fit/commercial synergies: [Strong / Moderate / Poor]
- Differentiation considerations: [Describe]

**Risk Level Assigned:** [ ] LOW [ ] MEDIUM [ ] HIGH

**Justification:** [Explain which criteria are met/not met, cite sources]

----------------------------------------------------------------------------------------------------
## Overall Risk Assessment Summary

| Risk Factor           | Risk Level          | Key Considerations                       |
|-----------------------|---------------------|------------------------------------------|
| Biological            | [Low/Med/High]     | [Brief summary]                          |
| Druggability          | [Low/Med/High]     | [Brief summary]                          |
| Translational         | [Low/Med/High]     | [Brief summary]                          |
| Clinical              | [Low/Med/High]     | [Brief summary]                          |
| Safety                | [Low/Med/High]     | [Brief summary]                          |
| Commercial/Competitive| [Low/Med/High]     | [Brief summary]                          |

### Overall Target Risk Profile: [Low/Medium/High]

---

## iDAS Strategic Alignment Assessment

### Whitespace Alignment Score
| Priority Whitespace | Alignment | Rationale |
|--------------------|-----------|-----------|
| mCRC chemorefractory 3L+ | [ ] Strong [ ] Moderate [ ] Weak [ ] None | [Explain] |
| mCRC RAS mutant frontline | [ ] Strong [ ] Moderate [ ] Weak [ ] None | [Explain] |
| mCRC RAS mutant refractory | [ ] Strong [ ] Moderate [ ] Weak [ ] None | [Explain] |
| Resectable (neo/adjuvant) | [ ] Strong [ ] Moderate [ ] Weak [ ] None | [Explain] |

### Cross-GI Portfolio Synergy
• [ ] Target applicable to PDAC (potential shared development)
• [ ] Target applicable to Gastric Cancer (potential shared development)
• [ ] Target specific to CRC only

### Strategic Fit Assessment
**Alignment with iDAS Vision:** [ ] High [ ] Medium [ ] Low
**Innovation Priority Match:** [ ] ADC opportunity [ ] Bispecific opportunity [ ] Small molecule [ ] Other modality
**KRAS Strategy Synergy:** [ ] Complements KRAS strategy [ ] Alternative to KRAS [ ] Independent

---

## Tempus Real-World Evidence (RWE) Analysis

**Data Source:** Tempus CRC cohort (n>200,000 patients)
**Run integrated analysis:** `python crc_integrated_analysis.py --genes {GENE}`

### Line of Therapy Expression Profile

| LOT Cohort | N Samples | Mean Expression | log2FC vs Frontline | Interpretation |
|------------|-----------|-----------------|---------------------|----------------|
| Frontline (1L-2L) MSS | [n] | [mean] log2TPM | Reference | [Comment] |
| **3L+ Chemorefractory MSS** | [n] | [mean] log2TPM | [FC] | [Comment] |

**3L+ vs Frontline Assessment:**
• [ ] Expression maintained in 3L+ (log2FC > -0.5)
• [ ] Expression increased in 3L+ (log2FC > 0.5) - Favorable
• [ ] Expression decreased in 3L+ (log2FC < -0.5) - Unfavorable

### RAS Status Expression Profile (MSS Population)

| RAS Cohort | N Samples | Mean Expression | log2FC RAS-mut vs WT |
|------------|-----------|-----------------|----------------------|
| RAS Mutant MSS (1L-2L) | [n] | [mean] log2TPM | [FC] |
| **RAS Mutant MSS (3L+)** | [n] | [mean] log2TPM | [FC] |
| RAS Wild-Type MSS (1L-2L) | [n] | [mean] log2TPM | Reference |
| RAS Wild-Type MSS (3L+) | [n] | [mean] log2TPM | [FC] |

**RAS Mutation Context Assessment:**
• [ ] Target expressed in RAS-mutant population (mean > 3 log2TPM)
• [ ] Expression higher in RAS-mutant vs RAS-WT - Favorable for RAS-mut targeting
• [ ] Expression similar across RAS status - RAS-agnostic potential
• [ ] Expression lower in RAS-mutant - Less favorable for RAS-mut focus

### Key iDAS Target Population: MSS RAS-Mutant 3L+ Chemorefractory

**Population Size:** [n] samples (Tempus RWD)
**Mean Expression:** [mean] log2TPM
**% Detected:** [pct]%
**log2FC vs All MSS:** [FC]

**Assessment:**
• [ ] Strong expression in key iDAS population (mean > 4 log2TPM, >80% detected)
• [ ] Moderate expression (mean 2-4 log2TPM, >50% detected)
• [ ] Weak expression (mean < 2 log2TPM or <50% detected)

### CMS Subtype Expression (Tempus)

| CMS Subtype | Characteristics | N Samples | Mean Expression |
|-------------|-----------------|-----------|-----------------|
| CMS1 | MSI Immune, hypermutated | [n] | [mean] |
| CMS2 | Canonical, WNT/MYC | [n] | [mean] |
| CMS3 | Metabolic, KRAS | [n] | [mean] |
| CMS4 | Mesenchymal, EMT | [n] | [mean] |

**CMS Expression Pattern:**
• [ ] Uniformly expressed across CMS subtypes
• [ ] Enriched in CMS1 (MSI-H) - IO combination potential
• [ ] Enriched in CMS2/3 (Canonical/Metabolic) - Mainstream CRC
• [ ] Enriched in CMS4 (Mesenchymal) - Poor prognosis, high unmet need

### Checkpoint Inhibitor Treatment Context

| CPI Status | N Samples | Mean Expression | log2FC Treated vs Naive |
|------------|-----------|-----------------|-------------------------|
| CPI Naive | [n] | [mean] log2TPM | Reference |
| CPI Treated | [n] | [mean] log2TPM | [FC] |

**IO Context Assessment:**
• [ ] Expression maintained post-CPI treatment
• [ ] Expression changes post-CPI - Consider sequencing implications

### Tempus RWE Summary

**Expression in iDAS Priority Populations:**
| iDAS Priority | Tempus Cohort | Expression Level | Alignment |
|---------------|---------------|------------------|-----------|
| Chemorefractory 3L+ | Tempus_MSS_3Lplus | [Low/Moderate/High] | [Strong/Moderate/Weak] |
| RAS Mutant Frontline | Tempus_RASMut_MSS_1L2L | [Low/Moderate/High] | [Strong/Moderate/Weak] |
| RAS Mutant Refractory | Tempus_RASMut_MSS_3Lplus | [Low/Moderate/High] | [Strong/Moderate/Weak] |

**Overall Tempus RWE Assessment:** [ ] Supportive [ ] Neutral [ ] Unfavorable

---

### Key Strengths:
1. [List major strengths]
2.
3.

### Key Risks/Challenges:
1. [List major challenges or uncertainties]
2.
3.

### Risk Mitigation Strategies:
1. [Propose methods to reduce or manage identified risks]
2.
3.

### Recommendation: [Overall go/no-go or priority level for further investment]

**iDAS Priority Recommendation:**
• [ ] High Priority - Strong alignment with CRC whitespace, recommend advancement
• [ ] Medium Priority - Partial alignment, requires additional validation
• [ ] Low Priority - Limited strategic fit, deprioritize unless compelling new data
• [ ] Not Recommended - Misaligned with iDAS strategy

## Additional Comments
[Any extra commentary, e.g., needed experiments, synergy with other agents, IP considerations, cross-GI applicability, etc.]

----------------------------------------------------------------------------------------------------

**Important:** 
- For each major claim or statement, either cite references or propose how such a claim can be tested or replicated (e.g., "Evaluate in an orthotopic animal model," "Use CRISPR knockout in relevant cell lines," "Leverage a known co-crystal structure," "Conduct a targeted literature search via [database]"). 
- Aim for a decision-grade document appropriate for internal R&D review.
