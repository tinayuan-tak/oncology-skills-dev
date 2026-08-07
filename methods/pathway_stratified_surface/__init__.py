"""pathway_stratified_surface — per-target pathway/stress-stratified surface window (E4-A3).

Reads pathway-stratified-surface-window-v1: is surface antigen {target} elevated in a tumor-STATE
subset (e.g. hypoxia-HIGH tertile) — a biologics handle on that compartment? Emits
pathway_stratified_surface_class {pathway_high_up_surface / pathway_high_down_surface /
not_stratified / underpowered / not_in_product}. v1 = HALLMARK_HYPOXIA x NSCLC. METHOD_VERSION 0.1.0.
"""
from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .read import read_pathway_stratified_surface  # noqa: E402,F401
