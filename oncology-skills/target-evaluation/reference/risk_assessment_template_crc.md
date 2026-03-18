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
Please assess the target across all six risk factor categories (Biological, Druggability, Translational, Clinical, Safety, and Commercial/Competitive). For each factor, determine if the risk level is Low, Medium, or High based on the provided criteria.

Important Note: Interpret criteria from left to right. If criteria for both Low and Medium risk levels are not met, the default risk classification should be High.

----------------------------------------------------------------------------------------------------
### 1. Biological Risk Assessment

#### Target Implication in CRC
Current Evidence: [Describe the evidence supporting target involvement in CRC]

CRC-Specific Considerations:
• [ ] Target relevant to RAS mutant CRC (~45% of patients)
• [ ] Target relevant to RAS wild-type CRC
• [ ] Target relevant to MSI-H/dMMR CRC (~5% of mCRC)
• [ ] Target relevant to MSS/pMMR CRC (majority of mCRC)
• [ ] Target expressed/active across CRC molecular subtypes (CMS1-4)

Validation Status:
• [ ] Clinically validated target in CRC
• [ ] Validated in CRC patient-derived xenograft (PDX) models
• [ ] Validated in CRC organoid models
• [ ] Validated in at least 1 in vivo CRC model
• [ ] Human genetic association of target with CRC (GWAS, somatic mutations)
• [ ] Novel target with limited external validation in CRC
• [ ] Low replication across labs

Risk Level: [ ] Low [ ] Medium [ ] High
Justification: [Provide reasoning for risk assessment—cite references, or propose validation approaches]

----------------------------------------------------------------------------------------------------
### 2. Druggability Risk Assessment

#### Target Tractability
Target Characteristics: [Describe the biophysical properties of the target]

Druggability Evidence:
• [ ] Target has approved/clinical PoC/in vivo PoC
• [ ] Target is homologous to target(s) with approved/clinical PoC/in vivo PoC
• [ ] Weak or no evidence of future tractability

#### Therapeutic Complexity/Manufacturability
CMC Considerations: [Describe any manufacturing complexities, supply chain, or IP issues]

CMC Resources:
• [ ] Established CMC expertise, GMP platforms & supply chain
• [ ] Limited CMC expertise, GMP platform or supply chain
• [ ] No CMC expertise, GMP platform or supply chain

#### Additional for Synthetic Molecules (if applicable)
Druggable Pocket Analysis:
• [ ] Druggable pocket identified, reasonably stable
• [ ] No druggable pocket identified
• [ ] Molecule highly flexible

Tool Molecules:
• [ ] Available with direct evidence of target binding
• [ ] Available with functional readout but no confirmed target engagement
• [ ] Not available

SAR and SBDD Status:
• [ ] SAR progression plan in place and feasible
• [ ] SBDD enabled with X-ray co-crystal structure
• [ ] SBDD ligand based
• [ ] No SBDD strategy

Assay Availability:
• [ ] Biochemical and biophysical assays available
• [ ] Cell-based assays available
• [ ] Only phenotypic cell screen available

Risk Level: [ ] Low [ ] Medium [ ] High
Justification: [Provide reasoning for risk assessment—cite references, or propose validation approaches]

----------------------------------------------------------------------------------------------------
### 3. Translational Risk Assessment

#### Disease Models
Available Models: [List animal models, human-cell-derived models, organoids, etc.]

**CRC-Relevant Model Systems:**
• [ ] CRC patient-derived xenografts (PDX) - gold standard for in vivo
• [ ] CRC patient-derived organoids (PDO) - ex vivo drug testing
• [ ] Genetically engineered mouse models (APC/KRAS/TP53)
• [ ] Syngeneic CRC models (CT26, MC38) - immunotherapy studies
• [ ] CRC cell line panels (RAS mutant vs. wild-type representation)

**Model Stratification Considerations:**
- RAS mutation status representation
- MSI/MSS status representation
- CMS subtype representation (CMS1-4)
- Liver metastasis models (primary site of CRC metastasis)

#### Biomarkers
Target Engagement Biomarkers: [Describe available TE biomarkers]
Pharmacodynamic Biomarkers: [Describe available PD biomarkers]

**CRC-Specific Biomarker Landscape:**
- ctDNA/cfDNA: Emerging for response monitoring, RAS mutation tracking
- CEA: Traditional tumor marker, limited specificity
- CTC enumeration: Prognostic value
- Tissue-based IHC/FISH: Standard for HER2, MMR status

Validation Status:
• [ ] Validated CRC disease models AND target engagement AND PD biomarkers exist
• [ ] Disease models AND TE AND PD biomarkers available but not validated
• [ ] Disease models AND TE AND PD biomarkers not available
• [ ] Models include RAS mutant representation (strategic priority)
• [ ] Models include chemorefractory/resistant phenotypes

Risk Level: [ ] Low [ ] Medium [ ] High
Justification: [Provide reasoning for risk assessment—cite references, or propose validation approaches]

----------------------------------------------------------------------------------------------------
### 4. Clinical Risk Assessment

#### Definition of Patient Population
Patient Selection Strategy: [Describe how patients will be identified or stratified]

**CRC Population Stratification:**
• [ ] All-comer mCRC population
• [ ] RAS mutant mCRC (~45% prevalence) - High strategic priority
• [ ] RAS wild-type mCRC (~55% prevalence)
• [ ] MSI-H/dMMR mCRC (~5% prevalence)
• [ ] MSS/pMMR mCRC (~95% prevalence)
• [ ] Chemorefractory 3L+ mCRC - High strategic priority
• [ ] Resectable CRC (neoadjuvant/adjuvant setting)

Biomarker Strategy: [Describe biomarker assay readiness, challenges]

**CRC Biomarker Testing Considerations:**
- RAS/BRAF testing: Standard of care, high availability
- MSI/MMR testing: Standard of care for IO eligibility
- HER2 testing: Emerging, not yet routine in CRC
- PD-L1 testing: Variable clinical utility in CRC

#### Trial Feasibility
Recruitment Considerations: [Describe patient recruitment timeline, center availability]
Screen-to-Enrollment Ratio: [Estimated ratio or feasibility commentary]

**CRC-Specific Trial Considerations:**
- Large patient population globally (~1.9M new cases/year)
- RAS mutant population: ~45% of mCRC, large addressable cohort
- Chemorefractory 3L+: Limited treatment options, high enrollment motivation
- Competing trials: Multiple KRAS-targeted agents in development

Clinical Risk Factors:
• [ ] Clearly defined patient population and clinical-grade biomarker assay available
• [ ] Biomarker assay needs further development or has clinical interpretation challenges
• [ ] Difficult path for patient selection biomarker
• [ ] Feasible trial with acceptable recruitment timeline
• [ ] Trial has feasibility challenges
• [ ] Trial has significant feasibility challenges

Risk Level: [ ] Low [ ] Medium [ ] High
Justification: [Provide reasoning for risk assessment—cite references, or propose validation approaches]

----------------------------------------------------------------------------------------------------
### 5. Safety Risk Assessment

#### In Silico/Vitro/Vivo Safety Signals
Safety Data: [Summarize available safety data from literature or preclinical tests]

#### Target Biology
Known Safety Concerns: [Describe on-target or compound-class safety issues]
Safety Biomarkers: [Availability of premonitory safety biomarkers]

Safety Assessment:
• [ ] Target safety is clinically validated, no anticipated compound class risks
• [ ] Safety risks are minimal, mitigated and acceptable for intended patient population
• [ ] Some evidence of target- or compound class-related risks
• [ ] Strong evidence of target- or compound class-related risks
• [ ] R/B likely manageable for intended patient population
• [ ] R/B questionable for intended patient population
• [ ] Premonitory safety biomarkers available
• [ ] No premonitory safety biomarkers available

Risk Level: [ ] Low [ ] Medium [ ] High
Justification: [Provide reasoning for risk assessment—cite references, or propose validation approaches]

----------------------------------------------------------------------------------------------------
### 6. Commercial/Competitive Risk Assessment

#### Patient Unmet Need
Current Treatment Landscape: [Describe standard-of-care, recognized gaps]

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

#### Addressable Patient Population
Market Size: [Estimate or reference patient population]

**CRC Epidemiology:**
- Global incidence: ~1.9 million new cases annually
- mCRC patients: ~700,000 globally
- RAS mutant mCRC: ~315,000 patients (45%)
- 3L+ chemorefractory: Large population with high unmet need

#### Competition
Competitive Landscape: [Discuss competing programs, patent coverage, generics, etc.]

**CRC Competitive Landscape (iDAS Intelligence):**
| Target/Mechanism | Key Competitors | Status |
|-----------------|-----------------|--------|
| KRAS G12C | Sotorasib (Amgen), Adagrasib (Mirati) | Approved |
| Pan-KRAS | Daraxonrasib (Revolution Medicines) | Phase 3 |
| KRAS G12D | Multiple early-stage programs | Phase 1/2 |
| HER2 | Trastuzumab deruxtecan, tucatinib combinations | Approved/Phase 3 |
| EGFR (RAS WT) | Cetuximab, panitumumab | Approved (generic pressure) |

**Strategic Differentiation Considerations:**
- First-in-class potential vs. best-in-class strategy
- Combination potential with existing therapies
- Applicability across RAS mutation subtypes (G12D, G12V, G12C)
- Potential for earlier-line advancement

Commercial Potential:
• [ ] Potential peak sales > $3bn
• [ ] Potential peak sales $1–3bn
• [ ] Potential peak sales < $1bn

Risk Level: [ ] Low [ ] Medium [ ] High
Justification: [Provide reasoning for risk assessment—cite references, or propose validation approaches]

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
