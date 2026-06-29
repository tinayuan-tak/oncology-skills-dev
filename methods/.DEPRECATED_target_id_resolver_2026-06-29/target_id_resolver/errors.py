"""Exception hierarchy for target_id_resolver.

Resolver design is fail-closed on ambiguity: rather than picking one
interpretation when multiple are plausible, raise a structured error so the
caller can disambiguate explicitly. NotFoundError is distinct so callers can
differentiate 'never existed' from 'multiple matches'.
"""


class ResolverError(Exception):
    """Base class for all resolver errors."""


class AmbiguousInputError(ResolverError):
    """Raised when the input maps to more than one HGNC entity and the
    resolver cannot pick a canonical one. Caller should disambiguate by
    passing a more specific identifier (HGNC ID or Ensembl gene ID)."""

    def __init__(self, input_value: str, candidates: list[dict]):
        self.input_value = input_value
        self.candidates = candidates
        msg = (
            f"Ambiguous input {input_value!r}: matches {len(candidates)} HGNC entries. "
            f"Disambiguate by passing HGNC:NNNN or ENSGNNNNN. "
            f"Candidates: {[c.get('hgnc_id') or c.get('symbol') for c in candidates]}"
        )
        super().__init__(msg)


class NotFoundError(ResolverError):
    """Raised when no matching gene is found for the input value."""

    def __init__(self, input_value: str):
        self.input_value = input_value
        super().__init__(f"No gene found for input: {input_value!r}")


class ResolverPinError(ResolverError):
    """Raised when a resolver-release pin cannot be loaded or is malformed."""
