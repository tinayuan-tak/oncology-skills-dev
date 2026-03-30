# Drug Target Risk Assessment Prompt Template - Non-Small Cell Lung Cancer (NSCLC)

## System Prompt

You are a senior researcher in drug discovery and translational medicine. Produce a comprehensive, evidence-based assessment of the following drug target or mechanism for **Non-Small Cell Lung Cancer (NSCLC)**.

Your output should resemble a long-form internal research briefing or target evaluation document used in early-stage R&D. Organize the output logically, focus on critical synthesis, and—importantly—provide references (if available) or propose methods (computational, experimental, or literature-driven) that could be used to evaluate or validate each major claim.

---

## Data Sources for NSCLC Target Evaluation

### TCGA/GTEx (Raw Expression - On-Target Toxicity Assessment)
- **Source:** `s3://onc-compbio/omicsoft_oncoland_data`
- **Use:** Tumor vs Adjacent Normal comparison (primary safety metric)
- **Cohorts:** TCGA_LUAD, TCGA_LUSC, TCGA_Adjacent, GTEx_Lung, CCLE_NSCLC
- **Script:** `nsclc_comprehensive_analysis.py`

### Tempus (Real-World Evidence - iDAS Alignment)
- **Source:** Local Tempus NSCLC cohort
- **Use:** Line-of-therapy stratified expression, biomarker-defined populations
- **Sample Size:** ~1,867 patients, ~3,500 samples
- **Key Cohorts:**
  - `Tempus_2L_NonAGA` (n=518) - **iDAS Priority: 2L Non-AGA (IO-experienced)**
  - `Tempus_2L_EGFR` (n=38) - **iDAS Priority: 2L EGFR Mutant (post-TKI)**
  - `Tempus_1L2L_KRAS` (n=1,021) - **iDAS Priority: 1L/2L KRAS Mutant**
- **Script:** `nsclc_comprehensive_analysis.py`

### Running Integrated Analysis
```bash
# Full integrated analysis (TCGA + Tempus)
python nsclc_comprehensive_analysis.py --genes {GENE} --output-dir ./results

# TCGA-only analysis
python nsclc_comprehensive_analysis.py --genes {GENE} --skip-tempus

# Tempus-only analysis
python nsclc_comprehensive_analysis.py --genes {GENE} --skip-tcga
```

---

## NSCLC Strategic Context (iDAS Framework)

### Vision
Establish Takeda as a leader in NSCLC treatment through meaningful internal innovation and external partnerships.

### iDAS Status
**Endorsed: December 2025**

### Priority Whitespace Opportunities
Assess target alignment with these strategic priorities:

| Priority Whitespace | Patient Population | Strategic Rationale |
|---------------------|-------------------|---------------------|
| **2L Non-AGA (IO-experienced)** | ~35% of NSCLC | No actionable genomic alterations; progressed on IO ± chemo; high unmet need |
| **2L EGFR Mutant (post-TKI)** | ~15% of NSCLC | Post-osimertinib failure; resistance mechanisms emerging |
| **1L/2L KRAS Mutant** | ~25% of NSCLC | KRAS G12C (~13%) has approved drugs; non-G12C (~12%) remains unmet need |

### Key Biomarker Landscape in NSCLC
| Biomarker | Prevalence | Notes |
|-----------|------------|-------|
| **EGFR mutations** | ~15-20% | Standard TKI therapy (osimertinib); post-TKI resistance is key unmet need |
| **KRAS mutations** | ~25-30% | G12C (~13%) targetable; non-G12C (~12%) unmet need |
| **ALK fusions** | ~5% | Multiple approved TKIs (alectinib, lorlatinib) |
| **ROS1 fusions** | ~2% | TKI-responsive |
| **BRAF V600E** | ~2% | Dabrafenib + trametinib approved |
| **MET exon 14** | ~3% | Capmatinib, tepotinib approved |
| **RET fusions** | ~1-2% | Selpercatinib, pralsetinib approved |
| **STK11 mutations** | ~15-20% | Associated with IO resistance, poor prognosis |
| **KEAP1 mutations** | ~15-20% | Often co-occurs with STK11; poor prognosis |
| **PD-L1** | Variable | CPS/TPS used for IO patient selection |
| **AGA (Actionable Genomic Alterations)** | ~25-30% | EGFR, ALK, ROS1, RET, BRAF, MET, NTRK, KRAS G12C (treated), HER2 |

### NSCLC Patient Segmentation
| Segment | Prevalence | Current SOC | Unmet Need |
|---------|------------|-------------|------------|
| **Non-AGA (IO-eligible)** | ~70% | IO ± chemo (1L), docetaxel ± ramucirumab (2L) | 2L+ options limited |
| **EGFR mutant** | ~15% | Osimertinib (1L), chemo ± IO (2L+) | Post-TKI resistance |
| **KRAS G12C** | ~13% | Sotorasib/adagrasib (2L+) | Duration of response, resistance |
| **KRAS non-G12C** | ~12% | IO ± chemo | No targeted therapy |
| **ALK/ROS1/RET** | ~8% | TKIs | Later-line resistance |

### Competitive Landscape Considerations
| Target/Mechanism | Key Competitors | Status |
|------------------|-----------------|--------|
| **EGFR** | Osimertinib (AstraZeneca) | 1L SOC |
| **KRAS G12C** | Sotorasib (Amgen), Adagrasib (Mirati) | Approved 2L+ |
| **KRAS G12D** | MRTX1133 (Mirati), RMC-9805 (Revolution) | Phase 1/2 |
| **Pan-KRAS** | Daraxonrasib (Revolution Medicines) | Phase 3 |
| **PD-1/PD-L1** | Pembrolizumab, nivolumab, durvalumab, atezolizumab | Approved |
| **PD-1 + CTLA-4** | Nivolumab + ipilimumab | Approved 1L |
| **ALK** | Alectinib, lorlatinib, brigatinib | Approved |

----------------------------------------------------------------------------------------------------
## TARGET ID RISK ASSESSMENT PROMPT TEMPLATE

### Background Information
[target details]

### Strategic Alignment Assessment
**Whitespace Alignment:** [ ] 2L Non-AGA [ ] 2L EGFR mutant [ ] 1L/2L KRAS mutant
**Biomarker-Defined Population:** [Specify if target defines or overlaps with key NSCLC biomarker populations]

### Risk Assessment Instructions
Please assess the target across all six risk factor categories (Biological, Druggability, Translational, Clinical, Safety, and Commercial/Competitive). For each factor, determine if the risk level is Low, Medium, or High based on the provided criteria.

Important Note: Interpret criteria from left to right. If criteria for both Low and Medium risk levels are not met, the default risk classification should be High.

----------------------------------------------------------------------------------------------------
### 1. Biological Risk Assessment

#### Target Implication in NSCLC
Current Evidence: [Describe the evidence supporting target involvement in NSCLC]

NSCLC-Specific Considerations:
- [ ] Target relevant to LUAD (adenocarcinoma) - ~40% of NSCLC
- [ ] Target relevant to LUSC (squamous cell carcinoma) - ~30% of NSCLC
- [ ] Target relevant to Non-AGA population (IO-experienced)
- [ ] Target relevant to EGFR-mutant NSCLC
- [ ] Target relevant to KRAS-mutant NSCLC (G12C and/or non-G12C)
- [ ] Target relevant to STK11/KEAP1-mutant NSCLC (IO-resistant)
- [ ] Target expressed across NSCLC molecular subtypes

Validation Status:
- [ ] Clinically validated target in NSCLC
- [ ] Validated in NSCLC patient-derived xenograft (PDX) models
- [ ] Validated in NSCLC organoid models
- [ ] Validated in at least 1 in vivo NSCLC model
- [ ] Human genetic association of target with NSCLC (GWAS, somatic mutations)
- [ ] Novel target with limited external validation in NSCLC
- [ ] Low replication across labs

Risk Level: [ ] Low [ ] Medium [ ] High
Justification: [Provide reasoning for risk assessment—cite references, or propose validation approaches]

----------------------------------------------------------------------------------------------------
### 2. Druggability Risk Assessment

#### Target Tractability
Target Characteristics: [Describe the biophysical properties of the target]

Druggability Evidence:
- [ ] Target has approved/clinical PoC/in vivo PoC
- [ ] Target is homologous to target(s) with approved/clinical PoC/in vivo PoC
- [ ] Weak or no evidence of future tractability

#### Therapeutic Complexity/Manufacturability
CMC Considerations: [Describe any manufacturing complexities, supply chain, or IP issues]

CMC Resources:
- [ ] Established CMC expertise, GMP platforms & supply chain
- [ ] Limited CMC expertise, GMP platform or supply chain
- [ ] No CMC expertise, GMP platform or supply chain

#### Additional for Synthetic Molecules (if applicable)
Druggable Pocket Analysis:
- [ ] Druggable pocket identified, reasonably stable
- [ ] No druggable pocket identified
- [ ] Molecule highly flexible

Tool Molecules:
- [ ] Available with direct evidence of target binding
- [ ] Available with functional readout but no confirmed target engagement
- [ ] Not available

SAR and SBDD Status:
- [ ] SAR progression plan in place and feasible
- [ ] SBDD enabled with X-ray co-crystal structure
- [ ] SBDD ligand based
- [ ] No SBDD strategy

Assay Availability:
- [ ] Biochemical and biophysical assays available
- [ ] Cell-based assays available
- [ ] Only phenotypic cell screen available

Risk Level: [ ] Low [ ] Medium [ ] High
Justification: [Provide reasoning for risk assessment—cite references, or propose validation approaches]

----------------------------------------------------------------------------------------------------
### 3. Translational Risk Assessment

#### Disease Models
Available Models: [List animal models, human-cell-derived models, organoids, etc.]

**NSCLC-Relevant Model Systems:**
- [ ] NSCLC patient-derived xenografts (PDX) - gold standard for in vivo
- [ ] NSCLC patient-derived organoids (PDO) - ex vivo drug testing
- [ ] Genetically engineered mouse models (KRAS/TP53/STK11)
- [ ] Syngeneic NSCLC models (LL/2, LLC1, KLN-205) - immunotherapy studies
- [ ] NSCLC cell line panels with driver mutation representation

**Model Stratification Considerations:**
- EGFR mutation status representation (L858R, exon 19 del, T790M)
- KRAS mutation status representation (G12C, G12D, G12V)
- STK11/KEAP1 co-mutation status (IO resistance models)
- Histology representation (LUAD vs LUSC)
- Brain metastasis models (common site of NSCLC metastasis)

#### Biomarkers
Target Engagement Biomarkers: [Describe available TE biomarkers]
Pharmacodynamic Biomarkers: [Describe available PD biomarkers]

**NSCLC-Specific Biomarker Landscape:**
- ctDNA/cfDNA: Standard for EGFR/KRAS mutation monitoring, resistance detection
- PD-L1 IHC: 22C3/28-8 assays for IO patient selection
- NGS panels: Comprehensive genomic profiling standard of care
- ALK/ROS1 FISH/IHC: Standard for fusion detection

Validation Status:
- [ ] Validated NSCLC disease models AND target engagement AND PD biomarkers exist
- [ ] Disease models AND TE AND PD biomarkers available but not validated
- [ ] Disease models AND TE AND PD biomarkers not available
- [ ] Models include EGFR/KRAS mutant representation (strategic priority)
- [ ] Models include STK11/KEAP1 co-mutation phenotypes (IO resistance)

Risk Level: [ ] Low [ ] Medium [ ] High
Justification: [Provide reasoning for risk assessment—cite references, or propose validation approaches]

----------------------------------------------------------------------------------------------------
### 4. Clinical Risk Assessment

#### Definition of Patient Population
Patient Selection Strategy: [Describe how patients will be identified or stratified]

**NSCLC Population Stratification:**
- [ ] All-comer NSCLC population
- [ ] Non-AGA NSCLC (no actionable genomic alterations) - **High strategic priority (2L)**
- [ ] EGFR-mutant NSCLC - **High strategic priority (2L post-TKI)**
- [ ] KRAS-mutant NSCLC - **High strategic priority (1L/2L)**
  - [ ] KRAS G12C (~13%)
  - [ ] KRAS non-G12C (~12%)
- [ ] STK11/KEAP1-mutant NSCLC (IO-resistant population)
- [ ] PD-L1 high (TPS ≥50% or CPS ≥10)
- [ ] LUAD (adenocarcinoma) vs LUSC (squamous)

Biomarker Strategy: [Describe biomarker assay readiness, challenges]

**NSCLC Biomarker Testing Considerations:**
- EGFR/KRAS/ALK/ROS1/BRAF/MET/RET testing: Standard of care at diagnosis
- PD-L1 testing: Standard for IO selection, multiple assays available
- STK11/KEAP1 testing: Emerging for IO resistance prediction
- NGS panels: Increasingly standard, enables comprehensive profiling

#### Trial Feasibility
Recruitment Considerations: [Describe patient recruitment timeline, center availability]
Screen-to-Enrollment Ratio: [Estimated ratio or feasibility commentary]

**NSCLC-Specific Trial Considerations:**
- Large patient population globally (~2.2M new cases/year)
- Non-AGA 2L population: Large, high unmet need after IO failure
- EGFR 2L population: Smaller but well-defined post-osimertinib
- KRAS mutant population: ~25% of NSCLC, G12C has competing trials
- Competing trials: Extensive NSCLC trial landscape, particularly in 1L

Clinical Risk Factors:
- [ ] Clearly defined patient population and clinical-grade biomarker assay available
- [ ] Biomarker assay needs further development or has clinical interpretation challenges
- [ ] Difficult path for patient selection biomarker
- [ ] Feasible trial with acceptable recruitment timeline
- [ ] Trial has feasibility challenges
- [ ] Trial has significant feasibility challenges

Risk Level: [ ] Low [ ] Medium [ ] High
Justification: [Provide reasoning for risk assessment—cite references, or propose validation approaches]

----------------------------------------------------------------------------------------------------
### 5. Safety Risk Assessment

#### In Silico/Vitro/Vivo Safety Signals
Safety Data: [Summarize available safety data from literature or preclinical tests]

#### Target Biology
Known Safety Concerns: [Describe on-target or compound-class safety issues]
Safety Biomarkers: [Availability of premonitory safety biomarkers]

**NSCLC Patient Population Safety Considerations:**
- Often elderly population (median age ~70)
- Smoking history common (comorbidities: COPD, cardiovascular)
- Brain metastases frequent (~20-40%) - CNS penetration considerations
- Prior IO exposure: consider immune-related AE history
- Prior TKI exposure (EGFR mutant): consider cardiotoxicity history

Safety Assessment:
- [ ] Target safety is clinically validated, no anticipated compound class risks
- [ ] Safety risks are minimal, mitigated and acceptable for intended patient population
- [ ] Some evidence of target- or compound class-related risks
- [ ] Strong evidence of target- or compound class-related risks
- [ ] R/B likely manageable for intended patient population
- [ ] R/B questionable for intended patient population
- [ ] Premonitory safety biomarkers available
- [ ] No premonitory safety biomarkers available

Risk Level: [ ] Low [ ] Medium [ ] High
Justification: [Provide reasoning for risk assessment—cite references, or propose validation approaches]

----------------------------------------------------------------------------------------------------
### 6. Commercial/Competitive Risk Assessment

#### Patient Unmet Need
Current Treatment Landscape: [Describe standard-of-care, recognized gaps]

**NSCLC Current Standard of Care:**

| Setting | Population | Current SOC | Unmet Need |
|---------|------------|-------------|------------|
| **1L Non-AGA** | PD-L1 ≥50% | Pembrolizumab mono or + chemo | Moderate (durable responses in ~20%) |
| **1L Non-AGA** | PD-L1 <50% | Pembrolizumab + chemo | High (median PFS ~9 mo) |
| **2L Non-AGA** | IO-experienced | Docetaxel ± ramucirumab | **HIGH UNMET NEED** |
| **1L EGFR+** | - | Osimertinib | Moderate (eventual resistance) |
| **2L EGFR+** | Post-TKI | Chemo ± IO | **HIGH UNMET NEED** |
| **2L+ KRAS G12C** | - | Sotorasib, adagrasib | Moderate (response ~30-40%) |
| **KRAS non-G12C** | - | IO ± chemo | **HIGH UNMET NEED** |

**Key Gaps (iDAS Priority Areas):**
- 2L Non-AGA: ~35% of NSCLC, limited options after IO failure
- 2L EGFR mutant: Post-osimertinib, resistance mechanisms emerging
- 1L/2L KRAS mutant: G12C has options; non-G12C needs targeted therapy

#### Addressable Patient Population
Market Size: [Estimate or reference patient population]

**NSCLC Epidemiology:**
- Global incidence: ~2.2 million new cases annually
- Advanced/metastatic NSCLC: ~70% at diagnosis
- Non-AGA population: ~70% of NSCLC (~1.5M patients)
- EGFR-mutant: ~15% of NSCLC (~330K patients)
- KRAS-mutant: ~25% of NSCLC (~550K patients)

#### Competition
Competitive Landscape: [Discuss competing programs, patent coverage, generics, etc.]

**NSCLC Competitive Landscape (iDAS Intelligence):**

| Target/Mechanism | Key Competitors | Status | Notes |
|------------------|-----------------|--------|-------|
| EGFR (1L) | Osimertinib | Approved SOC | Generic 2032 |
| EGFR (resistance) | Multiple programs | Phase 1-2 | C797S, MET amp, etc. |
| KRAS G12C | Sotorasib, Adagrasib | Approved | Disar. Phase 3 |
| Pan-KRAS | Daraxonrasib (Revolution) | Phase 3 | Cross-GI potential |
| KRAS G12D | MRTX1133, RMC-9805 | Phase 1/2 | Early stage |
| PD-1/PD-L1 | Multiple | Approved | Crowded, generic pressure |
| PD-1 + LAG-3 | Multiple | Phase 3 | Next-gen IO |
| PD-1 + TIGIT | Tiragolumab, others | Phase 3 | Mixed results |
| ADCs | Multiple targets | Phase 1-3 | HER3, TROP2, B7-H3 |

**Strategic Differentiation Considerations:**
- First-in-class potential vs. best-in-class strategy
- Combination potential with IO (non-AGA) or TKIs (EGFR/KRAS)
- CNS penetration (brain metastases in ~20-40% of NSCLC)
- Oral vs. IV formulation considerations
- Cross-indication potential (SCLC, other solid tumors)

Commercial Potential:
- [ ] Potential peak sales > $3bn
- [ ] Potential peak sales $1-3bn
- [ ] Potential peak sales < $1bn

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
| 2L Non-AGA (IO-experienced) | [ ] Strong [ ] Moderate [ ] Weak [ ] None | [Explain] |
| 2L EGFR Mutant (post-TKI) | [ ] Strong [ ] Moderate [ ] Weak [ ] None | [Explain] |
| 1L/2L KRAS Mutant | [ ] Strong [ ] Moderate [ ] Weak [ ] None | [Explain] |

### Cross-Portfolio Synergy
- [ ] Target applicable to SCLC (potential shared development)
- [ ] Target applicable to other solid tumors (cross-indication potential)
- [ ] Target specific to NSCLC only

### Strategic Fit Assessment
**Alignment with iDAS Vision:** [ ] High [ ] Medium [ ] Low
**Innovation Priority Match:** [ ] ADC opportunity [ ] Bispecific opportunity [ ] Small molecule [ ] IO combination [ ] Other modality
**KRAS Strategy Synergy:** [ ] Complements KRAS strategy [ ] Alternative to KRAS [ ] Independent

---

## Tempus Real-World Evidence (RWE) Analysis

**Data Source:** Tempus NSCLC cohort (~1,867 patients, ~3,500 samples)
**Run integrated analysis:** `python nsclc_comprehensive_analysis.py --genes {GENE}`

### Line of Therapy Expression Profile

| LOT Cohort | N Samples | Mean Expression | log2FC vs 1L | Interpretation |
|------------|-----------|-----------------|--------------|----------------|
| 1L | ~2,611 | [mean] log2TPM | Reference | [Comment] |
| 2L | ~628 | [mean] log2TPM | [FC] | [Comment] |
| **3L+** | ~328 | [mean] log2TPM | [FC] | [Comment] |

**LOT Expression Assessment:**
- [ ] Expression maintained across LOT (log2FC > -0.5)
- [ ] Expression increased in later lines (log2FC > 0.5) - Favorable
- [ ] Expression decreased in later lines (log2FC < -0.5) - Unfavorable

### iDAS Priority Population Expression

| iDAS Cohort | N Samples | Mean Expression | Assessment |
|-------------|-----------|-----------------|------------|
| **2L Non-AGA** | 518 | [mean] log2TPM | [Strong/Moderate/Weak] |
| **2L EGFR Mutant** | 38 | [mean] log2TPM | [Strong/Moderate/Weak] |
| **1L/2L KRAS Mutant** | 1,021 | [mean] log2TPM | [Strong/Moderate/Weak] |

**iDAS Alignment Thresholds:**
- Strong: Mean expression >4 log2TPM
- Moderate: Mean expression 2-4 log2TPM
- Weak: Mean expression <2 log2TPM

### EGFR Mutation Status Expression

| EGFR Status | N Samples | Mean Expression | log2FC Mut vs WT |
|-------------|-----------|-----------------|------------------|
| EGFR Wild-Type | ~3,446 | [mean] log2TPM | Reference |
| EGFR Mutant | ~121 | [mean] log2TPM | [FC] |

**EGFR Context Assessment:**
- [ ] Expression similar in EGFR-mutant and WT - Broad applicability
- [ ] Expression enriched in EGFR-mutant - Favorable for EGFR+ focus
- [ ] Expression depleted in EGFR-mutant - Less favorable for EGFR+ population

### KRAS Mutation Status Expression

| KRAS Status | N Samples | Mean Expression | log2FC Mut vs WT |
|-------------|-----------|-----------------|------------------|
| KRAS Wild-Type | ~2,434 | [mean] log2TPM | Reference |
| KRAS Mutant | ~1,133 | [mean] log2TPM | [FC] |
| KRAS G12C | ~367 | [mean] log2TPM | [FC vs WT] |

**KRAS Context Assessment:**
- [ ] Expression similar across KRAS status - KRAS-agnostic potential
- [ ] Expression enriched in KRAS-mutant - Favorable for KRAS+ focus
- [ ] Expression depleted in KRAS-mutant - Less favorable for KRAS population

### STK11/KEAP1 Resistance Marker Expression

| Marker Status | N Samples | Mean Expression | log2FC Mut vs WT |
|---------------|-----------|-----------------|------------------|
| STK11 Wild-Type | ~3,016 | [mean] log2TPM | Reference |
| **STK11 Mutant** | ~551 | [mean] log2TPM | [FC] |
| KEAP1 Wild-Type | ~3,221 | [mean] log2TPM | Reference |
| **KEAP1 Mutant** | ~346 | [mean] log2TPM | [FC] |

**IO Resistance Context Assessment:**
- [ ] Expression maintained in STK11/KEAP1 mutant (potential IO-combo)
- [ ] Expression enriched in STK11/KEAP1 mutant - Favorable for IO-resistant population
- [ ] Expression depleted in STK11/KEAP1 mutant - Less favorable

### AGA Status Expression

| AGA Status | N Samples | Mean Expression | Interpretation |
|------------|-----------|-----------------|----------------|
| Non-AGA | ~3,115 | [mean] log2TPM | Key population for 2L |
| AGA | ~452 | [mean] log2TPM | EGFR/ALK/ROS1/etc. |

### Tempus RWE Summary

**Expression in iDAS Priority Populations:**
| iDAS Priority | Tempus Cohort | Expression Level | Alignment |
|---------------|---------------|------------------|-----------|
| 2L Non-AGA | Tempus_2L_NonAGA | [Low/Moderate/High] | [Strong/Moderate/Weak] |
| 2L EGFR Mutant | Tempus_2L_EGFR | [Low/Moderate/High] | [Strong/Moderate/Weak] |
| 1L/2L KRAS Mutant | Tempus_1L2L_KRAS | [Low/Moderate/High] | [Strong/Moderate/Weak] |

**Overall Tempus RWE Assessment:** [ ] Supportive [ ] Neutral [ ] Unfavorable

---

## Subgroup Suitability Analysis

**Data Source:** `{GENE}_subgroup_suitability.csv` from `nsclc_comprehensive_analysis.py`
**Visualization:** `figures/{GENE}_subgroup_suitability.png`

This analysis integrates histology, mutation status, and iDAS whitespace alignment to identify optimal patient populations and potential exclusion criteria.

### Subgroup Suitability Scores

| Subgroup | Category | Suitability Score | Key Metric | Recommendation |
|----------|----------|-------------------|------------|----------------|
| LUSC | Histology | [1-5]/5 | [X.Xx vs adjacent] | [GO/CONDITIONAL/CAUTION] |
| LUAD | Histology | [1-5]/5 | [X.Xx vs adjacent] | [GO/CONDITIONAL/CAUTION] |
| 2L Non-AGA | iDAS Whitespace | [1-5]/5 | [expr=X.XX, tox=Level] | [GO/CONDITIONAL/CAUTION] |
| 2L EGFR Mutant | iDAS Whitespace | [1-5]/5 | [expr=X.XX, tox=Level] | [GO/CONDITIONAL/CAUTION] |
| 1L/2L KRAS Mutant | iDAS Whitespace | [1-5]/5 | [expr=X.XX, tox=Level] | [GO/CONDITIONAL/CAUTION] |
| KRAS+ | Mutation Status | [1-5]/5 | [log2FC=X.XX vs WT] | [PRIORITY/GO/NEUTRAL/CAUTION/EXCLUDE] |
| EGFR+ | Mutation Status | [1-5]/5 | [log2FC=X.XX vs WT] | [PRIORITY/GO/NEUTRAL/CAUTION/EXCLUDE] |
| STK11+ | Mutation Status | [1-5]/5 | [log2FC=X.XX vs WT] | [PRIORITY/GO/NEUTRAL/CAUTION/EXCLUDE] |
| KEAP1+ | Mutation Status | [1-5]/5 | [log2FC=X.XX vs WT] | [PRIORITY/GO/NEUTRAL/CAUTION/EXCLUDE] |

### Suitability Score Interpretation

| Score | Recommendation | Criteria | Action |
|-------|----------------|----------|--------|
| **5/5** | PRIORITY | >2x tumor enrichment OR upregulated in mutant subgroup | Prioritize this population |
| **4/5** | GO | 1.5-2x enrichment OR high expression + manageable toxicity | Include in development |
| **3/5** | CONDITIONAL/NEUTRAL | Moderate enrichment OR no significant mutation effect | Requires additional validation |
| **2/5** | CAUTION | Low enrichment OR downregulated in mutant subgroup | Consider exclusion criteria |
| **1/5** | EXCLUDE | No enrichment OR significantly downregulated | Recommend exclusion |

### Priority Populations (Score ≥4)
[List subgroups with suitability score ≥4, ranked by score]
1.
2.
3.

### Potential Exclusion Criteria (Score ≤2)
[List subgroups with suitability score ≤2 that may warrant patient exclusion]
- [ ] Exclude [subgroup] patients: [Rationale - e.g., "target significantly downregulated in STK11-mutant tumors"]
- [ ] No exclusion criteria identified

### Subgroup-Stratified Development Strategy

**Recommended Patient Population:**
- [ ] All-comer NSCLC (no biomarker selection required)
- [ ] Histology-selected: [LUAD/LUSC preferred]
- [ ] Biomarker-selected: [Specify mutation/expression criteria]
- [ ] iDAS-aligned: [Specify priority whitespace]

**Recommended Exclusion Criteria:**
- [ ] None - target expressed broadly
- [ ] Exclude [mutation]+ patients
- [ ] Exclude [histology] patients

**Stratification Biomarker Feasibility:**
- [ ] Standard NGS panels can identify relevant populations
- [ ] Additional IHC/FISH assay development needed
- [ ] Target expression itself as biomarker (IHC)

---

### Key Strengths:
1. [List major strengths]
2. [Include subgroup-specific strengths if applicable, e.g., "Strong tumor enrichment in LUSC (2.0x)"]
3.

### Key Risks/Challenges:
1. [List major challenges or uncertainties]
2. [Include subgroup-specific concerns, e.g., "Target significantly downregulated in STK11-mutant tumors"]
3.

### Subgroup-Specific Considerations:
- **Best-suited populations:** [List populations with suitability score ≥4]
- **Populations requiring caution:** [List populations with suitability score ≤2]
- **Patient selection strategy implications:** [Describe how subgroup analysis informs trial design]

### Risk Mitigation Strategies:
1. [Propose methods to reduce or manage identified risks]
2. [Include subgroup-specific mitigations, e.g., "Exclude STK11-mutant patients from initial trial"]
3.

### Recommendation: [Overall go/no-go or priority level for further investment]

**iDAS Priority Recommendation:**
- [ ] High Priority - Strong alignment with NSCLC whitespace, recommend advancement
- [ ] Medium Priority - Partial alignment, requires additional validation
- [ ] Low Priority - Limited strategic fit, deprioritize unless compelling new data
- [ ] Not Recommended - Misaligned with iDAS strategy

**Subgroup-Stratified Recommendation:**
- [ ] All-comer development - Target suitable across all subgroups
- [ ] Biomarker-selected development - Recommend [specific population] based on suitability scores
- [ ] Conditional development - Requires exclusion of [specific subgroup] due to low suitability

## Additional Comments
[Any extra commentary, e.g., needed experiments, synergy with other agents, IP considerations, cross-indication applicability, etc.]

----------------------------------------------------------------------------------------------------

**Important:**
- For each major claim or statement, either cite references or propose how such a claim can be tested or replicated (e.g., "Evaluate in an orthotopic animal model," "Use CRISPR knockout in relevant cell lines," "Leverage a known co-crystal structure," "Conduct a targeted literature search via [database]").
- Aim for a decision-grade document appropriate for internal R&D review.
