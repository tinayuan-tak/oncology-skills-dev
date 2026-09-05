"""_normalize_modality — --modality token normalization (2026-08-24).

Regression: `--modality bite` silently no-op'd because the gate keys on the canonical
`bite_tce`; the raw token matched nothing and read as an APPLIED lens. Normalization aliases the
natural forms, passes canonical values through, and WARNS+drops an unrecognized token (never silent).
"""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parents[1], "tp_run_modality")


def test_canonical_passes_through():
    for m in ("small_molecule", "adc", "bite_tce", "antibody", "degrader", "cell_therapy"):
        assert tp._normalize_modality(m) == m


def test_natural_aliases_normalize():
    assert tp._normalize_modality("bite") == "bite_tce"          # the reported bug
    assert tp._normalize_modality("TCE") == "bite_tce"           # case-insensitive
    assert tp._normalize_modality("bispecific") == "bite_tce"
    assert tp._normalize_modality("PROTAC") == "degrader"
    assert tp._normalize_modality("car-t") == "cell_therapy"
    assert tp._normalize_modality(" SM ") == "small_molecule"    # strip + lower


def test_unknown_warns_and_drops(capsys):
    assert tp._normalize_modality("teleporter") is None
    err = capsys.readouterr().err
    assert "not a recognized modality" in err and "teleporter" in err


def test_aliases_resolve_into_the_canonical_set():
    # Every alias target must be a real canonical token (guards a typo in the alias map).
    for canonical in tp._MODALITY_ALIASES.values():
        assert canonical in tp._CANONICAL_MODALITIES
