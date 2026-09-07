"""mutation_stratified_surface — per-target mutation-stratified surface-antigen window (E4-A2).

Reads mutation-stratified-surface-window-v1: is surface antigen {target} elevated in a driver's
MUTANT tumor subset (a biologics handle on the driver-mutant patient subset)? Emits
mutant_stratified_surface_class {mutant_up_surface / mutant_down_surface / not_stratified /
underpowered / not_in_product}. v1 covers the KRAS x NSCLC archetype. METHOD_VERSION 0.1.0.
"""

from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .read import read_mutation_stratified_surface  # noqa: E402,F401
