"""target_id_resolver — release-pinned identifier resolver for human gene/protein targets.

Public API:
    resolve(input_value, resolver_release=...) -> Target
    resolve_batch(inputs, resolver_release=...) -> list[Target | None]
    Target, ResolverError, AmbiguousInputError, NotFoundError
"""

from ._version import __version__
from .schema import (
    Target,
    HGNC,
    Ensembl,
    UniProt,
    NCBI,
    DeprecationWarning_,
    ReleasePins,
    InputDescriptor,
    ResolutionStatus,
)
from .core import resolve, resolve_batch
from .errors import ResolverError, AmbiguousInputError, NotFoundError

__all__ = [
    "resolve",
    "resolve_batch",
    "Target",
    "HGNC",
    "Ensembl",
    "UniProt",
    "NCBI",
    "DeprecationWarning_",
    "ReleasePins",
    "InputDescriptor",
    "ResolutionStatus",
    "ResolverError",
    "AmbiguousInputError",
    "NotFoundError",
]

