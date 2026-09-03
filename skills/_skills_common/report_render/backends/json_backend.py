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


class JsonBackend:
    schema = "report_view.v1"

    def handled_kinds(self) -> set:
        # the JSON view emits any block as {kind, ...payload}; it covers the whole vocabulary.
        return set(vocab.BLOCK_KINDS)

    def to_obj(self, ir: ReportIR) -> dict:
        return {
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
            "header": {"kind": ir.header.kind, **ir.header.payload},
            "sections": [
                {
                    "short": sec.short,
                    "title": sec.title,
                    "role": sec.role,
                    "is_deciding": sec.is_deciding,
                    "blocks": [{"kind": b.kind, **b.payload} for b in sec.blocks],
                }
                for sec in ir.sections
            ],
            "about": ({"kind": ir.about.kind, **ir.about.payload} if ir.about is not None else None),
        }

    def render(self, ir: ReportIR) -> str:
        return json.dumps(self.to_obj(ir), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


__all__ = ["JsonBackend"]
