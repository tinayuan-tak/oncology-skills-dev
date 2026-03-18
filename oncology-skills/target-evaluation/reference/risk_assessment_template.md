# Drug Target Risk Assessment Prompt Template

## System Prompt

You are a senior researcher in drug discovery and translational medicine. Produce a comprehensive, evidence-based assessment of the following drug target or mechanism.

Your output should resemble a long-form internal research briefing or target evaluation document used in early-stage R&D. Organize the output logically, focus on critical synthesis, and—importantly—provide references (if available) or propose methods (computational, experimental, or literature-driven) that could be used to evaluate or validate each major claim.

----------------------------------------------------------------------------------------------------
## TARGET ID RISK ASSESSMENT PROMPT TEMPLATE

### Background Information
[target details]

### Risk Assessment Instructions
Please assess the target across all six risk factor categories (Biological, Druggability, Translational, Clinical, Safety, and Commercial/Competitive). For each factor, determine if the risk level is Low, Medium, or High based on the provided criteria.

Important Note: Interpret criteria from left to right. If criteria for both Low and Medium risk levels are not met, the default risk classification should be High.

----------------------------------------------------------------------------------------------------
### 1. Biological Risk Assessment

#### Target Implication in Disease
Current Evidence: [Describe the evidence supporting target involvement in the disease]

Validation Status:
• [ ] Clinically validated target
• [ ] Validated in at least 1 in vivo model (Oncology only)
• [ ] Totality of human biological evidence highly favorable (Other TAs)
• [ ] Human genetic association of target with disease
• [ ] Novel target with limited external validation
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

#### Biomarkers
Target Engagement Biomarkers: [Describe available TE biomarkers]
Pharmacodynamic Biomarkers: [Describe available PD biomarkers]

Validation Status:
• [ ] Validated disease models AND target engagement AND PD biomarkers exist
• [ ] Disease models AND TE AND PD biomarkers available but not validated
• [ ] Disease models AND TE AND PD biomarkers not available

Risk Level: [ ] Low [ ] Medium [ ] High
Justification: [Provide reasoning for risk assessment—cite references, or propose validation approaches]

----------------------------------------------------------------------------------------------------
### 4. Clinical Risk Assessment

#### Definition of Patient Population
Patient Selection Strategy: [Describe how patients will be identified or stratified]

Biomarker Strategy: [Describe biomarker assay readiness, challenges]

#### Trial Feasibility
Recruitment Considerations: [Describe patient recruitment timeline, center availability]
Screen-to-Enrollment Ratio: [Estimated ratio or feasibility commentary]

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

#### Addressable Patient Population
Market Size: [Estimate or reference patient population]

#### Competition
Competitive Landscape: [Discuss competing programs, patent coverage, generics, etc.]

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

## Additional Comments
[Any extra commentary, e.g., needed experiments, synergy with other agents, IP considerations, etc.]

----------------------------------------------------------------------------------------------------

**Important:** 
- For each major claim or statement, either cite references or propose how such a claim can be tested or replicated (e.g., "Evaluate in an orthotopic animal model," "Use CRISPR knockout in relevant cell lines," "Leverage a known co-crystal structure," "Conduct a targeted literature search via [database]"). 
- Aim for a decision-grade document appropriate for internal R&D review.
