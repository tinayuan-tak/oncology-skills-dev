"""Card CONCEPT DISCIPLINE ratchet — a card's summary_fields should belong to its declared
measurement_type's concept. This guards the one genuinely FOREIGN concept the presence-coherence
review found: MOLECULAR-FORM (isoform dominance / splice dysregulation) fields riding on bulk-RNA
expression-abundance cards. They answer a "WHICH transcript / splice form" question — a target-
intrinsic / patient-splicing concept distinct from the "is it expressed, how much" presence-abundance
claim the card owns.

Scope + non-goals (deliberately narrow, to stay high-signal and honest to the decided model):
  * Only bulk_rna cards are scanned (isoform/splice are transcript concepts). This also avoids false
    positives on genomic "fusion event" / survival "n_events" fields elsewhere.
  * POPULATION-NORMAL comparison fields (GTEx / matched-normal) are NOT flagged — the presence model
    keeps tumor-vs-normal as INTRINSIC relative context, not a foreign concept (selectivity owns the
    VERDICT; presence shows the context). See the presence coherence plan.

Ratchet (mirrors analysis-methods' reader-absence discipline):
  * _BASELINE records the 2 known residual cards' molecular-form fields → CI is GREEN today.
  * A NEW molecular-form field on a non-molecular-form-typed bulk_rna card FAILS (no new debt).
  * A STALE baseline entry (the field was re-homed — e.g. after the Phase 3b isoform/splice card split)
    is reported so the ledger stays honest; delete it from _BASELINE when that happens.
"""
from __future__ import annotations

import glob
import re
from pathlib import Path

import yaml

CARDS = Path(__file__).resolve().parents[2] / "cards"

# measurement_types whose OWN concept is molecular-form (transcript identity). Empty until the Phase 3b
# isoform / splice cards land; a card of one of these types may legitimately carry these fields.
_MOLECULAR_FORM_TYPES: set = set()

# molecular-form field tokens — isoform dominance + splice dysregulation. Deliberately specific so it
# does NOT match survival "n_events" or genomic "fusion event" fields (which live on non-bulk_rna cards
# anyway, but belt-and-suspenders).
_MOLFORM_RE = re.compile(r"isoform|splic|(^|_)psi(_|$)|splice_type|variable_events|shifted_events", re.I)


def _summary_fields(spec: dict) -> list:
    raw = (spec.get("outputs") or {}).get("summary_fields") or []
    out = []
    for f in raw:
        if isinstance(f, str):
            out.append(f)
        elif isinstance(f, dict) and f.get("name"):
            out.append(f["name"])
    return out


def find_molform_violations() -> dict:
    """{f'{card_id}::{field}': measurement_type} for every molecular-form summary_field on a bulk_rna
    card whose measurement_type is not itself a molecular-form type."""
    viol = {}
    for path in sorted(glob.glob(str(CARDS / "*.card.yaml"))):
        try:
            spec = yaml.safe_load(Path(path).read_text())
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(spec, dict):
            continue
        if spec.get("measurement") != "bulk_rna":
            continue
        if spec.get("measurement_type") in _MOLECULAR_FORM_TYPES:
            continue
        cid = spec.get("card_id") or Path(path).stem
        for f in _summary_fields(spec):
            if f and _MOLFORM_RE.search(f):
                viol[f"{cid}::{f}"] = spec.get("measurement_type")
    return viol


# BASELINE — the 2 known residual cards' molecular-form fields. Burn down when Phase 3b re-homes them
# (isoform → a target-intrinsic card; splice → a tumor-splicing card); then delete the matching entries.
_ISOFORM_REASON = ("isoform-dominance rides on cellline-rna-distribution; re-home to a dedicated "
                   "target-intrinsic isoform card (Phase 3b) — verdict-inert.")
_SPLICE_REASON = ("splice-dysregulation rides on tumor-rna-distribution; re-home to a dedicated "
                  "tumor-splicing card (Phase 3b) — verdict-inert.")
_BASELINE: dict[str, str] = {
    "cellline-rna-distribution::isoform_expression_class": _ISOFORM_REASON,
    "cellline-rna-distribution::dominant_isoform_fraction": _ISOFORM_REASON,
    "cellline-rna-distribution::n_expressed_isoforms": _ISOFORM_REASON,
    "cellline-rna-distribution::dominant_isoform": _ISOFORM_REASON,
    "cellline-rna-distribution::isoform_n_models": _ISOFORM_REASON,
    "cellline-rna-distribution::isoform_context": _ISOFORM_REASON,
    "tumor-rna-distribution::splicing_dysregulation_class": _SPLICE_REASON,
    "tumor-rna-distribution::n_splice_events": _SPLICE_REASON,
    "tumor-rna-distribution::max_event_psi_std": _SPLICE_REASON,
    "tumor-rna-distribution::median_event_psi_std": _SPLICE_REASON,
    "tumor-rna-distribution::n_variable_events": _SPLICE_REASON,
    "tumor-rna-distribution::n_tumor_shifted_events": _SPLICE_REASON,
    "tumor-rna-distribution::dominant_event_splice_type": _SPLICE_REASON,
    "tumor-rna-distribution::splicing_context": _SPLICE_REASON,
}


def test_no_new_molecular_form_violations():
    """No NEW molecular-form field on a bulk-RNA expression-abundance card (beyond the baselined debt)."""
    current = set(find_molform_violations())
    new = sorted(current - set(_BASELINE))
    assert not new, (
        "New molecular-form summary_field(s) on a non-molecular-form-typed bulk_rna card — a card should "
        "own ONE concept. Move them to a dedicated molecular-form card (or, if the card IS molecular-form, "
        "register its measurement_type in _MOLECULAR_FORM_TYPES):\n  " + "\n  ".join(new))


def test_concept_baseline_not_stale():
    """A baseline entry whose field no longer exists = fixed debt (e.g. after the Phase 3b split);
    delete it from _BASELINE to keep the ledger honest."""
    current = set(find_molform_violations())
    stale = sorted(set(_BASELINE) - current)
    assert not stale, (
        "Stale molecular-form baseline entrie(s) — no longer detected (re-homed / renamed). Delete them "
        "from _BASELINE in this test:\n  " + "\n  ".join(stale))


def test_baseline_entries_have_reasons():
    missing = sorted(k for k, v in _BASELINE.items() if not v)
    assert not missing, f"Baseline entries missing a reason: {missing}"
