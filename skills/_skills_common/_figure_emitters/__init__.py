"""_skills_common figure-emission registry (package form).

Stage-4 split of the former `_figure_emitters.py` monolith into a package. The public surface is
unchanged: `import _figure_emitters` / `from _figure_emitters import emit_figures_for_card` keep
working. Emitters live in tier modules; the registry + dispatch live in `_registry`; shared
helpers in `_common`.
"""

from ._common import _dge_cell_contrasts, _plotly_from  # test-surface + shared helpers
from ._registry import CARD_FIGURE_EMITTERS, emit_figures_for_card

__all__ = ["CARD_FIGURE_EMITTERS", "emit_figures_for_card", "_plotly_from", "_dge_cell_contrasts"]
