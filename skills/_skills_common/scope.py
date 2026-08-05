"""_skills_common.scope — typed Scope contract (Phase 5).

Ships the Scope dataclass + resolve_bucket() helper that the target-profile
skill (and future scope-aware skills) uses to route between the 5 invocation
modes: target_only, indication, multi_indication, indication_subtype,
multi_indication_subtype.

Design lives in target-contracts docs/design/IDAS_SUBTYPE_PIPELINE.md.
Locked decisions (Phase-0d + subsequent user checkpoints):
- Every iDAS = one indication. Multi-indication queries use
  `indications=[list]`, not a `panel` field. Strategic buckets (Thoracic,
  GI-upper, GI-lower, Heme) resolve to indication-lists at construction time
  via resolve_bucket(), NOT stored as a first-class Scope field.
- Enumerated iDAS ids validated against
  target-contracts/vocabularies/indication_crosswalk.yaml.
- Enumerated strategic-bucket ids validated against
  target-contracts/vocabularies/idas_strategic_buckets.yaml.
- Backward compat: existing target-profile invocations (--target + --indication)
  continue to work; they resolve to Scope(indication=x).
"""

from __future__ import annotations
import os

import functools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml


# Canonical vocabulary paths (loaded once per session). Fallback allows tests
# to override by monkeypatching these module-level constants.
DEFAULT_CONTRACTS_REPO = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)


ScopeMode = Literal[
    "target_only",
    "indication",
    "multi_indication",
    "indication_subtype",
    "multi_indication_subtype",
]


class ScopeError(ValueError):
    """Raised on invalid Scope construction (invalid iDAS id, mutually-
    exclusive fields, etc.)."""


@functools.lru_cache(maxsize=None)
def _load_idas_indications(contracts_repo: Path | None = None) -> set[str]:
    """Load the enumerated iDAS indication ids from indication_crosswalk.yaml."""
    if contracts_repo is None:
        contracts_repo = DEFAULT_CONTRACTS_REPO
    path = contracts_repo / "vocabularies" / "indication_crosswalk.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"indication_crosswalk.yaml not found at {path}. "
            f"Ensure target-contracts is checked out and merged with Phase 1a."
        )
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ValueError(f"indication_crosswalk.yaml is malformed: {exc}") from exc
    return {entry["canonical_code"] for entry in data["indications"]}


@functools.lru_cache(maxsize=None)
def _load_strategic_buckets(contracts_repo: Path | None = None) -> dict[str, list[str]]:
    """Load the strategic-bucket → indication-list map from idas_strategic_buckets.yaml."""
    if contracts_repo is None:
        contracts_repo = DEFAULT_CONTRACTS_REPO
    path = contracts_repo / "vocabularies" / "idas_strategic_buckets.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"idas_strategic_buckets.yaml not found at {path}."
        )
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ValueError(f"idas_strategic_buckets.yaml is malformed: {exc}") from exc
    return {entry["bucket_id"]: list(entry["indications"]) for entry in data["buckets"]}


@dataclass(frozen=True)
class Scope:
    """Typed scope contract for target-evaluation skill invocations.

    Fields:
      indication: single iDAS canonical code (e.g. "COADREAD"). Mutually
        exclusive with `indications`.
      indications: list of iDAS canonical codes for multi-indication
        queries. Mutually exclusive with `indication`.
      subtypes: list of subgroup stratum ids (e.g. ["MSI_H", "MSS"]).
        Requires `indication` OR `indications` set.

    Computed:
      .mode: one of the 5 ScopeMode literals; derived at __post_init__.

    Validation (raises ScopeError):
      - `indication` and `indications` both set → error
      - `subtypes` set with neither `indication` nor `indications` → error
      - Any iDAS code not in the crosswalk vocabulary → error
    """

    indication: str | None = None
    indications: list[str] | None = None
    subtypes: list[str] | None = None
    _contracts_repo: Path | None = field(default=None, repr=False)

    def __post_init__(self):
        if self.indication and self.indications:
            raise ScopeError(
                "indication (singular) and indications (list) are mutually exclusive. "
                "Use one or the other."
            )
        if self.subtypes and not (self.indication or self.indications):
            raise ScopeError(
                "subtypes require either indication or indications to be set. "
                "target-only mode cannot carry subtypes."
            )
        # Validate iDAS codes against the crosswalk
        allowed = _load_idas_indications(self._contracts_repo)
        codes_to_check = []
        if self.indication:
            codes_to_check.append(self.indication)
        if self.indications:
            codes_to_check.extend(self.indications)
        invalid = [c for c in codes_to_check if c not in allowed]
        if invalid:
            raise ScopeError(
                f"Unknown iDAS canonical code(s): {invalid}. "
                f"Valid codes (from indication_crosswalk.yaml): {sorted(allowed)}"
            )

    @property
    def mode(self) -> ScopeMode:
        """Compute mode from populated fields (Phase 4/5 locked decision)."""
        if self.subtypes:
            return "multi_indication_subtype" if self.indications else "indication_subtype"
        if self.indications:
            return "multi_indication"
        if self.indication:
            return "indication"
        return "target_only"

    def resolved_indications(self) -> list[str]:
        """Return the indication list this Scope resolves to at query time.

        - target_only mode → []
        - indication mode → [indication]
        - multi_indication modes → indications list as-is
        """
        if self.indication:
            return [self.indication]
        if self.indications:
            return list(self.indications)
        return []


def resolve_bucket(bucket_id: str, contracts_repo: Path | None = None) -> Scope:
    """Resolve a strategic-bucket id (e.g. "Thoracic") to a Scope.

    Buckets are display-facing labels that map to indication lists at query
    time. Reviewers see "Thoracic-bucket query over NSCLC+SCLC+HNSC" — the
    resolution is transparent.

    Args:
      bucket_id: canonical bucket id (e.g. "Thoracic", "GI-upper", "GI-lower", "Heme")

    Returns:
      Scope(indications=[<resolved iDAS codes>])
    """
    buckets = _load_strategic_buckets(contracts_repo)
    if bucket_id not in buckets:
        raise ScopeError(
            f"Unknown strategic bucket id: {bucket_id!r}. "
            f"Valid buckets: {sorted(buckets)}"
        )
    return Scope(
        indications=buckets[bucket_id],
        _contracts_repo=contracts_repo,
    )


def parse_cli_scope(
    indication: str | None = None,
    indications: str | None = None,
    subgroups: str | None = None,
    strategic_bucket: str | None = None,
    contracts_repo: Path | None = None,
) -> Scope:
    """Parse CLI-shaped inputs into a Scope.

    Called by target-profile run.py after argparse. Handles all 5 modes:

    Backward-compat single-indication (target-profile PR #22 legacy):
      --indication COADREAD
      → Scope(indication="COADREAD")

    Explicit multi-indication (Phase 5):
      --indications COADREAD,NSCLC,HNSC
      → Scope(indications=["COADREAD","NSCLC","HNSC"])

    Strategic bucket → resolves to multi-indication:
      --strategic-bucket Thoracic
      → resolve_bucket("Thoracic")
      → Scope(indications=["NSCLC","SCLC","HNSC"])

    Subtype-stratified:
      --indication COADREAD --subgroups MSI_H,MSS
      → Scope(indication="COADREAD", subtypes=["MSI_H","MSS"])

    Target-only:
      (no scope args)
      → Scope()
    """
    # Strategic bucket + explicit indications → conflict
    if strategic_bucket and (indication or indications):
        raise ScopeError(
            "--strategic-bucket is mutually exclusive with --indication and --indications. "
            "Buckets resolve to indication lists internally; do not combine."
        )
    if strategic_bucket:
        base = resolve_bucket(strategic_bucket, contracts_repo=contracts_repo)
        # Merge subgroups if provided
        if subgroups:
            subtype_list = [s.strip() for s in subgroups.split(",") if s.strip()]
            return Scope(
                indications=base.indications,
                subtypes=subtype_list,
                _contracts_repo=contracts_repo,
            )
        return base

    ind_list = None
    if indications:
        ind_list = [i.strip() for i in indications.split(",") if i.strip()]

    subtype_list = None
    if subgroups:
        subtype_list = [s.strip() for s in subgroups.split(",") if s.strip()]

    return Scope(
        indication=indication,
        indications=ind_list,
        subtypes=subtype_list,
        _contracts_repo=contracts_repo,
    )
