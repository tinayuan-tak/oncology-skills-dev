"""pharos_tdl — per-gene Target Development Level (Pharos/IDG TCRD; verdict-inert target-intrinsic facet).

The integrated druggability/novelty tier: Tclin (drugged) / Tchem (probed) / Tbio (studied) / Tdark.
Reads the frozen per-gene TDL snapshot (18,400 genes), O(1) HGNC lookup. Fills the novelty/druggability
gap via a CC0 route. FACET-ONLY (bibliometric novelty → verdict-inert, never a killer).
Live: EGFR/KRAS=Tclin, TP53/MARK3=Tchem, WRN=Tbio.
"""

from .read import read_pharos_tdl, METHOD_VERSION  # noqa: F401
