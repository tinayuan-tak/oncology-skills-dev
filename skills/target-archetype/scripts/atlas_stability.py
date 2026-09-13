#!/usr/bin/env python3
"""FREEZE STABILITY for the reference atlas — the property nothing asserted (skills #1243).

`atlas.json` is a 1.2MB FROZEN artifact that every target-archetype read is measured against: mu/sd are the
z-reference, `X` is the cohort-percentile population, `embedding.components` is the projection, `anchors` are
the phenotype corners. Two failure modes had no guard:

  1. SILENT MUTATION of the shipped artifact — a hand-edit, a half-applied amend script (see
     amend_atlas_feature_corr.py, which rewrites the file IN PLACE), a bad merge resolution on a 1.2MB
     single-line JSON, a partial regen that updated `X` but not `mu`. `test_shipped_atlas_passes_health`
     does NOT cover this: it checks INTERNAL consistency (offline embedding == runtime transform) plus
     provenance presence, both of which a self-consistent mutation satisfies — recompute the embedding from
     a mutated `X` and the integrity check is green while every percentile in the fleet has moved.
  2. NON-REPRODUCIBLE RE-FREEZE — nothing established that rebuilding from the same corpus yields the same
     numbers, so a future re-freeze diff mixed the intended change with unquantified build noise.

The two claims are pinned differently ON PURPOSE:

  PIN (`--check`, the CI gate): the shipped artifact vs `atlas/atlas_freeze.json`. NOTHING is volatile here
  — a frozen artifact's provenance stamp is part of what is frozen. Digests are per top-level field and per
  `meta` key so a failure NAMES what moved instead of saying "the file changed".

  REBUILD (`--verify-rebuild`, run by hand at a re-freeze): a fresh build over the same corpus vs the
  shipped artifact. Here a small, DECLARED set of fields legitimately differs (VOLATILE_ON_REBUILD) — the
  build stamps the current git sha and date. MEASURED 2026-09-13 over
  target-archetype-corpus-20260911 + panel_297.tsv: all 16 substantive top-level fields reproduced
  BYTE-IDENTICALLY (feature_order, mu, sd, X, targets, indications, labels, rule_fingerprints, axis_ref,
  embedding, anchors, soft_labels, reference_mask_fraction, feature_corr*, and meta minus the volatile
  keys). So a re-freeze diff is attributable: anything else that moves is the change under review.

  ⚠️ `--verify-rebuild` CANNOT run in CI, and is deliberately NOT wrapped in a test that skips when it
  can't: (a) build_atlas.py imports `sklearn.decomposition.PCA` and scikit-learn is NOT in the pixi env, so
  the freeze is not reproducible in the repo environment at all (see the PR that added this file); (b) the
  corpus is ~200 multi-MB run directories that live outside the repo. A conditional test would report GREEN
  in CI while never executing — the exact fail-open this module exists to close. It is a re-freeze checklist
  step with a hard exit code, not a suite member.

Usage:
  python3 atlas_stability.py --check                       # CI gate: shipped atlas vs pinned manifest
  python3 atlas_stability.py --write                       # re-pin after an INTENDED re-freeze
  python3 atlas_stability.py --verify-rebuild /tmp/new.json # rebuild vs shipped, modulo volatile fields
"""

import argparse
import hashlib
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DEFAULT_ATLAS = _HERE.parent / "atlas" / "atlas.json"
_DEFAULT_MANIFEST = _HERE.parent / "atlas" / "atlas_freeze.json"

SCHEMA = "atlas_freeze/1.0.0"

# Canonical form for hashing: key-sorted, whitespace-free JSON. Sorting keys means a dict field's digest is
# insensitive to Python insertion order (which build_atlas does not guarantee across refactors) while
# remaining exact on VALUES; floats round-trip through repr, so this is lossless for the numeric blocks.
_CANON = dict(sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=True)

# Fields a REBUILD is allowed to change, each with the reason it is not evidence of drift. Only consulted by
# --verify-rebuild; the --check pin gates on everything. Keys are dotted paths into the doc.
VOLATILE_ON_REBUILD = {
    "meta.build_date": ("the --build-date CLI argument, i.e. the day the rebuild ran — not a property of the corpus"),
    "meta.build_git_sha": ("HEAD at build time; it changes with every commit, including the one that adds this file"),
    "meta.feature_corr_provenance": (
        "stamped POST-freeze by amend_atlas_feature_corr.py (derived_post_freeze=true + the basis sha it "
        "was derived against). A native rebuild computes feature_corr inside build_atlas and so does not "
        "carry the amend stamp — the CORR NUMBERS themselves are NOT volatile and are compared"
    ),
}

# Identity fields echoed into the manifest so a re-pin is a LEGIBLE diff: reviewing `--write` output shows
# which corpus/sha/shape the new digests belong to, instead of an opaque wall of changed hashes. Gated on
# equality with the atlas (a manifest describing a different build is not a pin).
_IDENTITY_FIELDS = (
    "corpus",
    "build_date",
    "build_git_sha",
    "feature_schema_version",
    "n_targets",
    "n_features",
    "emb_dim",
)


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, **_CANON).encode()).hexdigest()


def field_digests(doc: dict) -> dict:
    """One digest per TOP-LEVEL field. Population derived from the document itself, so a re-freeze that adds
    a field cannot slip past unpinned — compare_manifest() reports it as UNPINNED."""
    return {k: _digest(v) for k, v in doc.items()}


def meta_digests(doc: dict) -> dict:
    """One digest per `meta` key. `meta` is also covered by field_digests['meta']; this exists purely so a
    failure names the key that moved (a single meta digest would say only 'meta changed')."""
    return {k: _digest(v) for k, v in (doc.get("meta") or {}).items()}


def freeze_manifest(doc: dict) -> dict:
    return {
        "schema": SCHEMA,
        "note": (
            "Per-field digests of the FROZEN atlas.json. Regenerate ONLY as part of an intended re-freeze "
            "(scripts/atlas_stability.py --write), in the same commit as the new atlas.json — a manifest "
            "updated on its own converts this guard into a rubber stamp."
        ),
        "digest": "sha256 of json.dumps(value, sort_keys=True, separators=(',',':'), ensure_ascii=False)",
        "identity": {k: (doc.get("meta") or {}).get(k) for k in _IDENTITY_FIELDS},
        "fields": field_digests(doc),
        "meta_fields": meta_digests(doc),
    }


def compare_manifest(pinned: dict, doc: dict) -> list:
    """Returns a list of problem strings (empty == stable). Reports, separately: fields whose digest MOVED,
    fields present in the artifact but UNPINNED (a new field must be pinned deliberately), fields pinned but
    now MISSING, and identity drift."""
    problems = []
    if pinned.get("schema") != SCHEMA:
        problems.append(f"manifest schema {pinned.get('schema')!r} != {SCHEMA!r}")

    identity = pinned.get("identity") or {}
    meta = doc.get("meta") or {}
    for k in _IDENTITY_FIELDS:
        if identity.get(k) != meta.get(k):
            problems.append(f"identity.{k}: manifest {identity.get(k)!r} != atlas {meta.get(k)!r}")

    for scope, pinned_d, live_d in (
        ("field", pinned.get("fields") or {}, field_digests(doc)),
        ("meta", pinned.get("meta_fields") or {}, meta_digests(doc)),
    ):
        if not pinned_d:
            problems.append(f"manifest pins NO {scope} digests — the guard would pass vacuously")
            continue
        for k in sorted(set(pinned_d) | set(live_d)):
            if k not in live_d:
                problems.append(f"{scope} {k!r} is pinned but MISSING from the atlas")
            elif k not in pinned_d:
                problems.append(
                    f"{scope} {k!r} is in the atlas but UNPINNED — pin it (--write) as part of the "
                    f"re-freeze that introduced it, so it is covered from day one"
                )
            elif pinned_d[k] != live_d[k]:
                problems.append(f"{scope} {k!r} CHANGED: pinned {pinned_d[k][:12]} != atlas {live_d[k][:12]}")
    return problems


def diff_docs(shipped: dict, rebuilt: dict, volatile=VOLATILE_ON_REBUILD) -> tuple:
    """Field-by-field comparison of two atlas documents for --verify-rebuild.
    Returns (substantive, waived): both are lists of dotted paths that differ; `waived` are the ones the
    VOLATILE_ON_REBUILD declaration accounts for. Volatile paths are subtracted at the META-KEY grain, so a
    build_git_sha change does not excuse the rest of meta."""
    substantive, waived = [], []

    def _note(path):
        (waived if path in volatile else substantive).append(path)

    for k in sorted(set(shipped) | set(rebuilt)):
        if k not in shipped or k not in rebuilt:
            substantive.append(f"{k} (present in only one document)")
        elif k == "meta":
            for mk in sorted(set(shipped["meta"]) | set(rebuilt["meta"])):
                if _digest(shipped["meta"].get(mk, "\x00absent")) != _digest(rebuilt["meta"].get(mk, "\x00absent")):
                    _note(f"meta.{mk}")
        elif _digest(shipped[k]) != _digest(rebuilt[k]):
            _note(k)
    return substantive, waived


def main():
    ap = argparse.ArgumentParser(description="atlas freeze-stability pin / rebuild verifier")
    ap.add_argument("--atlas", default=str(_DEFAULT_ATLAS))
    ap.add_argument("--manifest", default=str(_DEFAULT_MANIFEST))
    ap.add_argument("--check", action="store_true", help="compare the atlas against the pinned manifest (default)")
    ap.add_argument(
        "--write", action="store_true", help="(re-)pin the manifest from the atlas — INTENDED re-freezes only"
    )
    ap.add_argument(
        "--verify-rebuild", default=None, metavar="ATLAS_JSON", help="compare a fresh build against the shipped atlas"
    )
    a = ap.parse_args()

    doc = json.loads(Path(a.atlas).read_text())

    if a.write:
        Path(a.manifest).write_text(json.dumps(freeze_manifest(doc), indent=2, ensure_ascii=False) + "\n")
        print(f"pinned {len(doc)} fields + {len(doc.get('meta') or {})} meta keys -> {a.manifest}")
        return

    if a.verify_rebuild:
        rebuilt = json.loads(Path(a.verify_rebuild).read_text())
        substantive, waived = diff_docs(doc, rebuilt)
        for p in waived:
            print(f"  [WAIVED] {p}: {VOLATILE_ON_REBUILD[p]}")
        for p in substantive:
            print(f"  [DIFF]   {p}")
        ok = not substantive
        print(
            f"atlas_stability --verify-rebuild: {'REPRODUCED' if ok else 'DIVERGED'} "
            f"({len(substantive)} substantive, {len(waived)} waived)"
        )
        raise SystemExit(0 if ok else 1)

    problems = compare_manifest(json.loads(Path(a.manifest).read_text()), doc)
    for p in problems:
        print(f"  [FAIL] {p}")
    print("atlas_stability: " + ("PASS" if not problems else f"FAIL ({len(problems)} problems)"))
    raise SystemExit(0 if not problems else 1)


if __name__ == "__main__":
    main()
