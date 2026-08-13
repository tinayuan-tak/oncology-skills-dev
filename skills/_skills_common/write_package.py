"""write_package — standard data-package output tree writer.

Skills declaring `output_shape: data_package` emit this fixed layout:

    <out>/
    ├── decision.json                # rule verdict + fired rules
    ├── summary.yaml                 # per-card summary dicts (human-readable)
    ├── figures/                     # slide-droppable figures per card
    │   ├── {card_id}_primary.svg
    │   └── {card_id}_primary.png    # 300-DPI raster
    ├── tables/                      # slide-droppable tables per card
    │   ├── {card_id}_summary_stats.csv
    │   └── {card_id}_top_hits.csv   (optional; only if card exposes top-N)
    └── provenance.yaml              # target, indication, S3 URIs, invoked_lenses

This module writes the tree given (a) the decision dict, (b) the resolved
card_outputs, (c) provenance metadata. Figure emission is delegated to each
card's method-side emitter (dge_deseq2.emit et al.) — this module does NOT
reimplement plotting logic.

Design invariants:
  - Non-fatal on partial coverage: if a card's method module has no emitter,
    the corresponding figure/table is skipped and noted in provenance.yaml.
  - `provenance.yaml.invoked_lenses` records which optional lenses (modality,
    therapeutic_hypothesis, subgroup) the user supplied at runtime. Empty
    list when no lenses were invoked.
  - Every file in the tree is deterministic given the same (target,
    indication, decision, cards) — no timestamps embedded in file bodies
    other than generated_at in provenance.yaml.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml


def write_package(
    out_dir: Path,
    decision: dict,
    card_outputs: list[dict],
    target: str,
    indication: str,
    skill_name: str,
    skill_version: str = "1.0.0",
    invoked_lenses: Optional[dict] = None,
) -> dict:
    """Materialize the data-package tree at `out_dir`.

    Args:
        out_dir: destination directory (created if missing)
        decision: the decision dict from `make_decision_json` (also written
            standalone as decision.json)
        card_outputs: list of {card_id, summary, ...} from `resolve_cards`
        target: gene symbol
        indication: OncoTree code
        skill_name: name of the invoking skill (recorded in provenance)
        skill_version: skill version (default "1.0.0")
        invoked_lenses: dict of {lens_name: lens_value} for post-hoc lenses
            the caller applied (e.g. {"modality": "small_molecule"}).
            Empty dict / None means no lenses invoked. Recorded in
            provenance.yaml.invoked_lenses.

    Returns:
        Dict with paths to every written file, keyed by role. Useful for
        smoke tests + downstream consumers that want to know where things
        landed.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = out_dir / "figures"
    tables_dir = out_dir / "tables"
    figures_dir.mkdir(exist_ok=True)
    tables_dir.mkdir(exist_ok=True)

    written: dict[str, list[Path] | Path] = {"figures": [], "tables": []}

    # decision.json — the rule verdict + fired rules
    decision_path = out_dir / "decision.json"
    decision_path.write_text(json.dumps(decision, indent=2, default=str))
    written["decision"] = decision_path

    # summary.yaml — per-card summary dicts, human-readable
    summary_doc = {
        "target": target,
        "indication": indication,
        "skill": skill_name,
        "cards": {
            c["card_id"]: c.get("summary", {}) or {}
            for c in card_outputs
        },
    }
    summary_path = out_dir / "summary.yaml"
    summary_path.write_text(yaml.safe_dump(summary_doc, sort_keys=False))
    written["summary"] = summary_path

    # tables/{card_id}_summary_stats.csv — scalar fields as k,v CSV
    for card in card_outputs:
        cid = card["card_id"]
        s = card.get("summary") or {}
        scalars = {k: v for k, v in s.items()
                   if not k.startswith("_")
                   and isinstance(v, (int, float, str, bool, type(None)))}
        if not scalars:
            continue
        csv_path = tables_dir / f"{cid}_summary_stats.csv"
        with csv_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["field", "value"])
            for k, v in scalars.items():
                w.writerow([k, "" if v is None else v])
        written["tables"].append(csv_path)

    # tables/{card_id}_top_hits.csv — list-of-dict fields (e.g. per_hotspot_stats)
    for card in card_outputs:
        cid = card["card_id"]
        s = card.get("summary") or {}
        for field_name, val in s.items():
            if field_name.startswith("_"):
                continue
            if isinstance(val, list) and val and isinstance(val[0], dict):
                csv_path = tables_dir / f"{cid}_{field_name}.csv"
                keys = list(dict.fromkeys(k for row in val for k in row))
                with csv_path.open("w", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
                    w.writeheader()
                    for row in val:
                        w.writerow({k: row.get(k) for k in keys})
                written["tables"].append(csv_path)

    # figures/ — populated per-card by the caller before calling write_package,
    # OR left empty. write_package does NOT invoke method-side emitters
    # itself; the calling skill decides which cards get figures. This module
    # just notes which files exist in provenance.
    existing_figures = sorted(figures_dir.glob("*"))
    written["figures"] = existing_figures

    # data_provenance — per-card derived-manifest / source pins. Card readers
    # already stamp their summary with `_data_source` (the derived-manifest id,
    # e.g. `pancohort-cooccurrence-fisher-v1`); harvest it here so the audit
    # anchor records WHICH data product each card resolved against, not just
    # that the card ran. Closes the "reproducible & traceable" gap where
    # provenance.yaml previously named no manifest IDs / release pins.
    data_provenance = []
    for c in card_outputs:
        s = c.get("summary") or {}
        entry = {
            "card_id": c["card_id"],
            "data_source": s.get("_data_source"),
            # DECLARED input manifest ids (card_spec.required_inputs), stamped by resolve_cards.
            # Populated even for the many readers that never stamp `_data_source` themselves, so the
            # audit anchor names real manifest ids for every card — not just the ~40% that stamp.
            "input_manifest_ids": (c.get("provenance") or {}).get("input_manifest_ids", []),
            "_missing": bool(c.get("_missing")),   # match card_output + cards_missing key
        }
        if c.get("_missing_reason"):
            entry["_missing_reason"] = c["_missing_reason"]
        data_provenance.append(entry)

    # provenance.yaml — the audit anchor
    provenance = {
        "skill": skill_name,
        "skill_version": skill_version,
        "target": target,
        "indication": indication,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "invoked_lenses": invoked_lenses or {},
        # run-level reproducibility block (skills sha, data_mode/release_pin, resolved digests +
        # per-family drift) — mirrors decision.json['provenance'], single-sourced upstream.
        "governance": (decision or {}).get("provenance", {}),
        "cards_resolved": [c["card_id"] for c in card_outputs],
        "cards_missing": [c["card_id"] for c in card_outputs
                          if c.get("_missing")],
        "data_provenance": data_provenance,
        "artefacts": {
            "decision_json": str(decision_path.name),
            "summary_yaml": str(summary_path.name),
            "figures": sorted(p.name for p in existing_figures),
            "tables": sorted(p.name for p in tables_dir.glob("*.csv")),
        },
    }
    provenance_path = out_dir / "provenance.yaml"
    provenance_path.write_text(yaml.safe_dump(provenance, sort_keys=False))
    written["provenance"] = provenance_path

    return written
