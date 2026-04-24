---
name: analysis-sc-rna-nsclc
description: |
  Use when analyzing single-cell RNA-seq data in non-small cell lung cancer. Triggers include
  scRNA-seq analysis for NSCLC, tumor microenvironment characterization, cell type annotation,
  or single-cell gene expression in NSCLC context. (COMING SOON - use analysis-bulk-rna-nsclc instead)
metadata:
  version: 0.1.0
  owner: ming-ju.tsai@takeda.com
  requires_preflight: false
  environment: none
---

# NSCLC Single-Cell RNA-seq Analysis

## Status: COMING SOON

This skill is under development. For now, use the bulk RNA analysis skill:

**Available alternative:** `analysis-bulk-rna-nsclc`

## Planned Capabilities

- Single-cell gene expression analysis in NSCLC
- Cell type annotation and clustering (AT1, AT2, immune, stromal)
- Tumor microenvironment characterization
- Differential expression by cell type
- Cell-cell communication analysis
- Integration with TCGA/Tempus bulk data

## Data Sources (Planned)

- CELLxGENE Census NSCLC datasets
- Published NSCLC scRNA-seq studies
- Internal datasets
