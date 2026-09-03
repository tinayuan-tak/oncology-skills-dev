"""Backend registry + dispatch. A backend is a dumb {block-kind → syntax} renderer with two methods:
`handled_kinds() -> set` and `render(ir) -> str`. Adding a format = registering one factory here;
no content/selection logic lives in a backend (that is the IR builder's job).
"""
from __future__ import annotations

from ..ir import ReportIR
from .html import HtmlBackend
from .json_backend import JsonBackend
from .pptx import PptxBackend
from .text import TextBackend

# name → zero-arg factory. `markdown`/`md` and `text` share TextBackend (syntax toggle only).
BACKENDS: dict = {
    "text": lambda: TextBackend(markdown=False),
    "markdown": lambda: TextBackend(markdown=True),
    "md": lambda: TextBackend(markdown=True),
    "html": lambda: HtmlBackend(),
    "json": lambda: JsonBackend(),
    "pptx": lambda: PptxBackend(),
}

# backends whose render() returns BYTES (must be written to a file, never printed to stdout).
BINARY_BACKENDS: frozenset = frozenset({"pptx"})

# canonical file extension per backend name (for CLI artifact naming).
EXTENSIONS: dict = {"text": "txt", "markdown": "md", "md": "md", "html": "html",
                    "json": "json", "pptx": "pptx"}


def backend_names() -> list:
    return sorted(BACKENDS)


def string_backend_names() -> list:
    """Backends whose render() returns str (excludes the binary pptx backend)."""
    return sorted(set(BACKENDS) - BINARY_BACKENDS)


def get_backend(name: str):
    try:
        return BACKENDS[name]()
    except KeyError:
        raise ValueError(f"unknown backend {name!r}; choose one of {backend_names()}")


def render(ir: ReportIR, backend: str) -> str:
    return get_backend(backend).render(ir)


def coverage() -> dict:
    """{backend_name: set(block kinds it handles)} — the backend-coverage test surface."""
    return {name: set(factory().handled_kinds()) for name, factory in BACKENDS.items()}


__all__ = ["BACKENDS", "BINARY_BACKENDS", "EXTENSIONS", "backend_names", "string_backend_names",
           "get_backend", "render", "coverage"]
