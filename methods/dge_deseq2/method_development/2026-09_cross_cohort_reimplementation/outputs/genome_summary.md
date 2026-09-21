# Genome-wide summary stats — Stage-1 calibration cells

Effect gate = |log2FC| ≥ log2(1.5) = 0.585; padj/s-value cutoffs padj<0.05, svalue<0.005. Cell A = within-TCGA anchor; C = naive cross-cohort; Cr = RUVg-corrected.

| substrate | ind | cell | n tested | n sig (padj) | frac sig | n sig (padj+lfc) | n sig (svalue+lfc) | up | down | median\|lfc\| | median baseMean |
|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| recount3 | brca | A | 30,747 | 22,798 | 0.742 | 14,246 | 11,441 | 10,039 | 4,207 | 0.582 | 19944.1 |
| recount3 | brca | C | 30,847 | 27,816 | 0.902 | 19,593 | 18,567 | 11,937 | 7,656 | 0.872 | 19418.24 |
| recount3 | brca | Cr | 30,847 | 27,725 | 0.899 | 19,235 | 17,787 | 11,399 | 7,836 | 0.831 | 20387.29 |
| recount3 | paad | A | 29,710 | 694 | 0.023 | 392 | 343 | 241 | 151 | 0.032 | 17053.87 |
| recount3 | paad | C | 29,880 | 26,220 | 0.877 | 18,356 | 16,932 | 9,306 | 9,050 | 0.869 | 12853.67 |
| recount3 | paad | Cr | 29,879 | 23,854 | 0.798 | 16,595 | 13,952 | 8,332 | 8,263 | 0.754 | 13090.21 |
| xena-toil | brca | A | 21,850 | 17,875 | 0.818 | 10,140 | 8,358 | 6,617 | 3,523 | 0.540 | 704.24 |
| xena-toil | brca | C | 21,759 | 19,659 | 0.903 | 13,444 | 12,460 | 8,010 | 5,434 | 0.801 | 667.09 |
| xena-toil | brca | Cr | 21,759 | 19,668 | 0.904 | 13,851 | 12,831 | 8,194 | 5,657 | 0.839 | 678.26 |
| xena-toil | paad | A | 21,387 | 563 | 0.026 | 497 | 211 | 268 | 229 | 0.061 | 557.63 |
| xena-toil | paad | C | 20,970 | 18,605 | 0.887 | 12,402 | 11,458 | 7,320 | 5,082 | 0.773 | 385.36 |
| xena-toil | paad | Cr | 20,970 | 17,870 | 0.852 | 12,561 | 10,377 | 4,664 | 7,897 | 0.767 | 387.48 |
