"""oncology_target_contracts.plot_styles — shared figure palette + matplotlib style.

Makes the Takeda oncology figure palette importable from the installed package:

    from oncology_target_contracts.plot_styles import takeda_palette
    from oncology_target_contracts.plot_styles import mplstyle_path

The palette module (`takeda_palette.py`) physically lives at the contracts-repo root
`plot_styles/` dir (it predates the installable package). Rather than duplicate 178
lines, this subpackage loads that canonical file by location and re-exports its public
names — one source of truth, one import path. skills#2237 removed the last
`sys.path.insert(contracts_root/"plot_styles")` + bare `from takeda_palette import ...`
call site, so THIS is now the only supported way in.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from ..loader import contracts_root


def mplstyle_path() -> Path:
    """Absolute path to takeda_oncology.mplstyle (for plt.style.use)."""
    return contracts_root() / "plot_styles" / "takeda_oncology.mplstyle"


def _load_canonical_palette():
    """Import the canonical plot_styles/takeda_palette.py by file location."""
    palette_file = contracts_root() / "plot_styles" / "takeda_palette.py"
    spec = importlib.util.spec_from_file_location("oncology_target_contracts.plot_styles.takeda_palette", palette_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load takeda_palette from {palette_file}")
    mod = importlib.util.module_from_spec(spec)
    # register so `from ...plot_styles import takeda_palette` resolves to this module
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


takeda_palette = _load_canonical_palette()

__all__ = ["takeda_palette", "mplstyle_path"]
