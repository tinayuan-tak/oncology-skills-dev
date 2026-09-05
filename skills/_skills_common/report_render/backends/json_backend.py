"""Machine JSON backend — a stable, spec-applied serialization of the IR.

This is the "report view" a programmatic consumer reads (and the golden-snapshot surface): the SAME
tiered/scoped selection the human backends see, as data. It handles every block kind by construction
(each block serializes to `{kind, ...payload}`), so it can never silently drop a new kind — the
coverage test still asserts this. Output is deterministic (sort_keys) so snapshots are byte-stable.
"""
from __future__ import annotations

import json

from .. import vocab
from ..ir import ReportIR


def _block_obj(b) -> dict:
    """Serialize one block as {kind, ...payload}, carrying its faceted-view `lens` only when set — so an
    un-lensed IR (the standalone build_ir_for_skill path) stays byte-identical to the pre-lens golden."""
    o = {"kind": b.kind, **b.payload}
    if getattr(b, "lens", None):
        o["lens"] = b.lens
    return o


def _section_obj(sec) -> dict:
    o = {
        "short": sec.short,
        "title": sec.title,
        "role": sec.role,
        "is_deciding": sec.is_deciding,
        "blocks": [_block_obj(b) for b in sec.blocks],
    }
    if getattr(sec, "lens", None):
        o["lens"] = sec.lens
    return o


class JsonBackend:
    schema = "report_view.v1"

    def handled_kinds(self) -> set:
        # the JSON view emits any block as {kind, ...payload}; it covers the whole vocabulary.
        return set(vocab.BLOCK_KINDS)

    def to_obj(self, ir: ReportIR) -> dict:
        obj = {
            "schema": self.schema,
            "target": ir.target,
            "indication": ir.indication,
            "spec": {
                "level": ir.spec.level,
                "medium": ir.spec.medium,
                "scope": list(ir.spec.scope) if isinstance(ir.spec.scope, tuple) else ir.spec.scope,
                "lead": ir.spec.lead,
                "bump_deciding": ir.spec.bump_deciding,
            },
            "deciding_short": ir.deciding_short,
            "header": _block_obj(ir.header),
            "banner": (_block_obj(ir.banner) if getattr(ir, "banner", None) is not None else None),
            "overview": [_block_obj(b) for b in ir.overview],
            "sections": [_section_obj(sec) for sec in ir.sections],
            "about": (_block_obj(ir.about) if ir.about is not None else None),
        }
        # the faceted-view grouping as data (composed reports only; absent for the standalone path so its
        # golden is unchanged). Each item references a block by kind or a section by short.
        lenses = ir.lenses()
        if lenses:
            obj["lenses"] = [
                {"id": lid, "title": title,
                 "items": [({"section": it.short} if kind == "section" else {"block": it.kind})
                           for kind, it in items]}
                for lid, title, items in lenses
            ]
        return obj

    def render(self, ir: ReportIR) -> str:
        return json.dumps(self.to_obj(ir), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


__all__ = ["JsonBackend"]
