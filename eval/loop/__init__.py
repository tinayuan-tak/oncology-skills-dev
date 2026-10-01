"""eval/loop — the subskill iteration loop (SK#2303).

Phase 0, Work Item A (#2345): `run_batch.py`, the batch runner that invokes a focused subskill's
`scripts/run.py --emit-envelope` over a roster of target×indication triples and lays the emitted
packages out for the downstream substrate assembler + triangulation judge (Work Items B/C).
"""
