"""Teeth for eval/loop/critic/probes.py (SK#2303 WI-G, issue #2357).

C1 (pair-identity) and CALIB (direction) are REGRESSION probes: on a mature, well-formed skill they
are silent (true zero), so the only thing that keeps them trustworthy is that each planted defect
below FIRES and the clean case stays SILENT (anti-vacuity, per repo convention — see
eval/loop/tests/test_substrate.py's own teeth for the same discipline).

The 5 teeth (ported from ``~/subskill-loop-pilot/probe.py``'s ``teeth()``, each now its own
pytest so a single regression never hides behind an aggregate boolean):
  1. clean-case silence         — both probes emit nothing over the real, unmutated packages.
  2. rogue-pair tooth           — a token valid for family B written into family A's island.
  3. phantom-pair tooth         — the per-family token-key catch (strip the token key from the one
                                   qualifier family; the clean case must ALSO stay silent on it).
  4. NULL tooth (C1 & CALIB)    — a stripped section is not_evaluable, NEVER a silent pass.
  5. control-inversion tooth    — a curated positive control forced to read low.

Plus one scope-correctness check (not one of the 5, but a named requirement in #2357): a
``negative_except_lineage`` control read INSIDE its own lineage must stay silent, never a false
positive — exercised against a synthetic minimal package (no real lung-indication fixture exists
yet in eval/loop/tests/fixtures/).

Fixtures: the two real ``run.py --emit-envelope`` captures already landed for WI-B
(``{ceacam5,epcam}_coadread_emitted.json``, #2347) — both CEACAM5 and EPCAM are curated positive
("tumor_antigen") controls in ``tumor_presence_controls.yaml``, both COADREAD.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_CRITIC = Path(__file__).resolve().parents[1] / "critic"
if str(_CRITIC) not in sys.path:
    sys.path.insert(0, str(_CRITIC))

import probes as PR  # noqa: E402

_FIX = Path(__file__).resolve().parent / "fixtures"
_QUALIFIER = "cellline_heterogeneity_lineage_qualifier"


def _load(name: str) -> dict:
    return json.loads((_FIX / f"{name}_coadread_emitted.json").read_text())["evidence_package"]


def _clean() -> dict:
    return _load("ceacam5")


def _fails(findings: list[tuple]) -> list[tuple]:
    return [f for f in findings if f[2] == "fail"]


def _not_evaluable(findings: list[tuple]) -> list[tuple]:
    return [f for f in findings if f[2] == "not_evaluable"]


# ── Tooth 1: clean-case silence ─────────────────────────────────────────────────────────────────
def test_tooth_1_clean_case_is_silent():
    pkg = _clean()
    c1 = PR.probe_c1(pkg)
    calib = PR.probe_calib(pkg, "CEACAM5", "COADREAD")
    assert _fails(c1) == [], f"C1 should be silent on a clean package, got {c1}"
    assert _not_evaluable(c1) == [], f"C1 should find every section present, got {c1}"
    assert calib == [], f"CALIB should be silent on a clean positive control, got {calib}"


def test_tooth_1b_second_real_package_is_also_silent():
    """A second, independent real package (EPCAM) must be silent too — one clean package proving
    silence could be a fixture accident, not a property of the probe."""
    pkg = _load("epcam")
    assert _fails(PR.probe_c1(pkg)) == []
    assert PR.probe_calib(pkg, "EPCAM", "COADREAD") == []


# ── Tooth 2: rogue-pair ──────────────────────────────────────────────────────────────────────────
def test_tooth_2_rogue_pair_fires():
    """A token that is VALID for protein_presence_concordance, written onto
    tumor_presence_concordance's island, must be flagged as a rogue pair — never silently accepted
    because the token exists SOMEWHERE in the enum."""
    pkg = _clean()
    pkg["integrated_properties"]["tumor_presence_concordance"]["concordance_class"] = "antibody_detects_ms_absent"
    findings = _fails(PR.probe_c1(pkg))
    assert any("ROGUE PAIR" in f[3] and "tumor_presence_concordance" in f[3] for f in findings), findings


def test_tooth_2_sibling_direction_also_fires():
    """The mirror direction (a tumor_presence-only token written onto protein_presence_concordance)
    must also fire — the guard is symmetric, not special-cased to one family."""
    pkg = _clean()
    pkg["integrated_properties"]["protein_presence_concordance"]["concordance_class"] = "tumor_presence_discordant"
    findings = _fails(PR.probe_c1(pkg))
    assert any("ROGUE PAIR" in f[3] and "protein_presence_concordance" in f[3] for f in findings), findings


# ── Tooth 3: phantom-pair (the per-family token-key catch) ─────────────────────────────────────
def test_tooth_3_phantom_pair_fires_when_token_key_stripped():
    pkg = _clean()
    pkg["integrated_properties"][_QUALIFIER].pop("qualifier_class", None)
    findings = _fails(PR.probe_c1(pkg))
    assert any("NO token key" in f[3] and _QUALIFIER in f[3] for f in findings), findings


def test_tooth_3_clean_qualifier_family_stays_silent():
    """The clean case must NOT flag the qualifier family at all — proving the per-family token-key
    resolution (not a hard-coded `concordance_class` read) is what makes tooth 3 trustworthy."""
    pkg = _clean()
    findings = PR.probe_c1(pkg)
    assert not any(_QUALIFIER in f[3] for f in findings), findings


def test_tooth_3_hardcoded_token_key_would_fabricate_a_phantom_pair():
    """Direct regression guard on the pilot bug: the qualifier island carries NO
    `concordance_class` key at all, so a hard-coded ``island.get("concordance_class")`` read (the
    pilot's original bug) silently yields ``None`` — exactly the phantom-pair input (a `None` token
    that would index as ``(family, None)`` without ever surfacing an error). The real per-family
    resolver used by :func:`probes.probe_c1` instead finds the island's actual ``qualifier_class``
    key and returns its real token — never falling back to ``None``."""
    pkg = _clean()
    island = pkg["integrated_properties"][_QUALIFIER]
    assert "concordance_class" not in island  # the qualifier island never carries this key
    naive_token = island.get("concordance_class")
    assert naive_token is None  # the naive hard-coded read silently fabricates a None token

    import _predicates as P  # noqa: PLC0415

    real_key, real_token = P.resolve_token(island)
    assert real_key == "qualifier_class"
    assert real_token is not None
    assert real_token != P.MISSING_TOKEN


# ── Tooth 4: NULL tooth (C1 & CALIB) — not_evaluable, never a pass ──────────────────────────────
def test_tooth_4_c1_null_on_missing_integrated_properties():
    pkg = _clean()
    pkg.pop("integrated_properties", None)
    findings = PR.probe_c1(pkg)
    assert _not_evaluable(findings) and not _fails(findings), findings


def test_tooth_4_calib_null_on_missing_patient_tumor_abundance():
    pkg = _clean()
    pkg["source_properties"].pop("patient_tumor_abundance", None)
    findings = PR.probe_calib(pkg, "CEACAM5", "COADREAD")
    assert _not_evaluable(findings) and not _fails(findings), findings


def test_tooth_4_calib_null_on_missing_source_properties_section():
    pkg = _clean()
    pkg.pop("source_properties", None)
    findings = PR.probe_calib(pkg, "CEACAM5", "COADREAD")
    assert _not_evaluable(findings) and not _fails(findings), findings


# ── Tooth 5: control-inversion ───────────────────────────────────────────────────────────────────
def test_tooth_5_control_inversion_fires():
    """CEACAM5 is a curated POSITIVE (tumor_antigen) control that reads broadly_high in the real
    package. Force it to read low — CALIB must flag the inversion, never accept it."""
    pkg = _clean()
    pta = pkg["source_properties"]["patient_tumor_abundance"]
    pta["property"] = "absent"
    for a in pta.get("anchors", []):
        if a.get("field") == "median_log2tpm":
            a["value"] = 0.1
    findings = _fails(PR.probe_calib(pkg, "CEACAM5", "COADREAD"))
    assert findings and "POSITIVE reads low" in findings[0][3], findings


def test_tooth_5_control_inversion_silent_on_the_unmutated_control():
    """Paired negative check: the SAME control, unmutated, is silent (so tooth 5 is proven to react
    to the mutation, not to CEACAM5 generally)."""
    pkg = _clean()
    assert PR.probe_calib(pkg, "CEACAM5", "COADREAD") == []


# ── Named requirement (not one of the 5 teeth): lineage-scope honoured ──────────────────────────
def test_lineage_scope_guard_silences_a_marker_inside_its_own_lineage():
    """SFTPC (negative_except_lineage: Lung) reading broadly_high in NSCLC/SCLC (gtex_normal_tissue
    == Lung) must NOT be flagged — it is the lineage marker there, not a negative. Built from a
    synthetic minimal package: no real lung-indication fixture exists yet in this test's fixtures/."""
    pkg = {
        "source_properties": {
            "patient_tumor_abundance": {
                "property": "broadly_high",
                "anchors": [{"field": "median_log2tpm", "value": 9.0}],
            }
        }
    }
    findings = PR.probe_calib(pkg, "SFTPC", "NSCLC")
    assert findings and findings[0][2] == "not_evaluable" and "scope-skipped" in findings[0][3], findings
    assert _fails(findings) == []


def test_lineage_scope_guard_still_fires_outside_the_lineage():
    """The SAME SFTPC-high reading, in a non-lung indication (COADREAD), is a real inversion of its
    floor role and must fire — the scope guard narrows WHERE it applies, it does not disable it."""
    pkg = {
        "source_properties": {
            "patient_tumor_abundance": {
                "property": "broadly_high",
                "anchors": [{"field": "median_log2tpm", "value": 9.0}],
            }
        }
    }
    findings = _fails(PR.probe_calib(pkg, "SFTPC", "COADREAD"))
    assert findings and "FLOOR reads high" in findings[0][3], findings
