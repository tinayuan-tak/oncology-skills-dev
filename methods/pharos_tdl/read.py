"""pharos_tdl.read — library entry (thin re-export; the logic is a single-module O(1) lookup in cli)."""
from .cli import read_pharos_tdl, METHOD_VERSION  # noqa: F401
