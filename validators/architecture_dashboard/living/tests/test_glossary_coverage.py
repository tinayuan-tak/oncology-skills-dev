"""The baked-in legibility guarantee: every machine token the doc surfaces is glossed.

Fails the build (CI) on an unglossed token — so "easy to understand" cannot silently drift.
"""

from _util import builder, load_committed


def test_no_unglossed_tokens():
    graph = load_committed()
    errs = builder().glossary_coverage_errors(graph)
    assert not errs, "unglossed tokens (legibility drift):\n  " + "\n  ".join(errs[:40])


def test_glossary_entries_have_plain_english():
    gl = load_committed().get("glossary", {})
    assert gl, "no glossary present"
    missing = []
    for kind, entries in gl.items():
        for tok, rec in entries.items():
            if not rec.get("label"):
                missing.append(f"{kind}:{tok} has no label")
    assert not missing, "glossary entries missing labels:\n  " + "\n  ".join(missing[:30])
