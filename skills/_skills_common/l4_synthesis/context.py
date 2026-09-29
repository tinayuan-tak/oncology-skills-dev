"""l4_synthesis.context — the read-over of an already-emitted decision / evidence package.

The L4 assembler reads L3d/L3f + selected L2 claims out of a subskill decision.json (content under
``headline.*``) OR an emitted evidence_package (top-level named sections). It resolves NOTHING itself and
NEVER mutates the object it reads — it is a pure projection. The ``L4Context`` gathers the handles a
facet builder needs and exposes ``resolve_ref`` (the claim-ID traceability resolver) so the assembler can
prove every emitted statement drills back into the envelope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

# Vector names — mirror ``presence_l3d_story._POOLED`` / ``_BY_SUBTYPE`` so an L3d story's
# ``provenance.claim_ids[*].vector`` indexes straight into the vectors gathered here.
POOLED = "pooled_claim_vector"
BY_SUBTYPE = "by_subtype_claim_vector"


@dataclass(frozen=True)
class L4Context:
    """A read-only view over an emitted decision / evidence package."""

    decision: Mapping
    l3d_domains: dict  # domain -> L3d story object (deterministic, claim-ID-traceable)
    l3f_frames: dict  # frame_id -> L3f frame object (none materialized in the flagship today)
    claim_vectors: dict  # vector_name -> claim-vector dict (L2b islands / L2a source properties)
    stage: Optional[str] = None
    target: Optional[str] = None
    indication: Optional[str] = None

    @property
    def assessed_domains(self) -> list:
        """Domains with a resolved L3d story, in a stable (sorted) order."""
        return sorted(self.l3d_domains)


def _headline(decision: Mapping) -> Mapping:
    h = decision.get("headline") if isinstance(decision, Mapping) else None
    return h if isinstance(h, Mapping) else {}


def _discover_l3d(decision: Mapping) -> dict:
    """Find every L3d domain story in the object.

    A decision.json rides its L3d story on the headline (e.g. ``headline.tumor_expression_biology_story``);
    an emitted envelope carries it under a top-level ``l3d`` section. We identify a story STRUCTURALLY — a
    dict tagged ``layer == "L3d"`` with a ``domain`` — so a new domain's story is picked up automatically.
    """
    found: dict = {}

    def _scan(container: Mapping):
        for v in container.values():
            if isinstance(v, Mapping) and v.get("layer") == "L3d":
                dom = v.get("domain")
                if isinstance(dom, str) and dom and dom not in found:
                    found[dom] = v

    _scan(_headline(decision))
    l3d_section = decision.get("l3d") if isinstance(decision, Mapping) else None
    if isinstance(l3d_section, Mapping):
        # envelope: the section is either the story itself or a {domain: story} map.
        if l3d_section.get("layer") == "L3d" and isinstance(l3d_section.get("domain"), str):
            found.setdefault(l3d_section["domain"], l3d_section)
        else:
            _scan(l3d_section)
    return found


def _discover_l3f(decision: Mapping) -> dict:
    """Find any materialized L3f decision-frame objects (structural: ``layer == "L3f"`` + ``frame_id``).

    No L3f frame is materialized as a stored object in the current flagship envelope (frames are evaluated
    inside the question-table), so this is typically empty — a forward hook for when frames are exported.
    """
    found: dict = {}
    for container in (_headline(decision), decision if isinstance(decision, Mapping) else {}):
        if not isinstance(container, Mapping):
            continue
        for v in container.values():
            if isinstance(v, Mapping) and v.get("layer") == "L3f":
                fid = v.get("frame_id")
                if isinstance(fid, str) and fid:
                    found.setdefault(fid, v)
    return found


def read_context(
    decision: Mapping,
    *,
    stage: Optional[str] = None,
    target: Optional[str] = None,
    indication: Optional[str] = None,
) -> L4Context:
    """Build an ``L4Context`` from an emitted decision / evidence package. Pure read; no mutation."""
    h = _headline(decision)
    claim_vectors = {
        POOLED: h.get("claim_vector") if isinstance(h.get("claim_vector"), Mapping) else {},
        BY_SUBTYPE: h.get("claim_vector_by_subtype") if isinstance(h.get("claim_vector_by_subtype"), Mapping) else {},
    }
    return L4Context(
        decision=decision,
        l3d_domains=_discover_l3d(decision),
        l3f_frames=_discover_l3f(decision),
        claim_vectors=claim_vectors,
        stage=stage,
        target=target if target is not None else (decision.get("target") if isinstance(decision, Mapping) else None),
        indication=(
            indication
            if indication is not None
            else (decision.get("indication") if isinstance(decision, Mapping) else None)
        ),
    )


def resolve_ref(ctx: L4Context, ref: Mapping) -> bool:
    """Does a claim ref drill back into the envelope?

    Resolution precedence (a ref carries at most one locator):
      * ``vector`` set   -> ``claim_id`` must be a key on that named claim vector (the L2b island / L2a
                            source-property claim).
      * ``domain`` set   -> that domain's L3d story must be present (the ref names the domain story).
      * ``frame`` set    -> that L3f frame must be present.
      * bare ``claim_id``-> resolvable if it is a key on ANY claim vector, or a present L3f frame id, or a
                            present L3d domain-story's ``title``/property (fallback search).
    """
    if not isinstance(ref, Mapping):
        return False
    cid = ref.get("claim_id")
    if not isinstance(cid, str) or not cid:
        return False

    vec = ref.get("vector")
    if vec is not None:
        v = ctx.claim_vectors.get(vec)
        return isinstance(v, Mapping) and cid in v

    dom = ref.get("domain")
    if dom is not None:
        return dom in ctx.l3d_domains

    frame = ref.get("frame")
    if frame is not None:
        return frame in ctx.l3f_frames

    # bare claim_id — search every locator surface.
    if cid in ctx.l3f_frames or cid in ctx.l3d_domains:
        return True
    for v in ctx.claim_vectors.values():
        if isinstance(v, Mapping) and cid in v:
            return True
    return False
