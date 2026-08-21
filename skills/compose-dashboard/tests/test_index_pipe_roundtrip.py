r"""_parse_existing_index must survive a pipe in a headline / class-call
cell. The writer escapes a literal '|' as '\|' to keep the markdown table valid; the reader must
split on UNESCAPED pipes (then unescape), else the row splits into >6 cells and is silently dropped
— and lost on the next full re-render (which re-reads + re-writes the whole table)."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import compose_dashboard as C  # noqa: E402


def test_parse_index_preserves_escaped_pipe_in_headline(tmp_path):
    idx = tmp_path / "INDEX.md"
    # exactly the shape _upsert_target_index writes: 6 cells, headline carries an escaped pipe.
    idx.write_text(
        "# KRAS evidence packages\n\n"
        "| Generated | Indication | Package | Path | Class calls | Headline |\n"
        "|---|---|---|---|---|---|\n"
        "| 2026-08-11 | COADREAD | `kras-coad-v1` | [`KRAS/kras-coad-v1`](KRAS/kras-coad-v1/) | "
        "dependency-depmap: dependent | fit is strong \\| dominant signal |\n"
    )
    rows = C._parse_existing_index(idx)
    assert len(rows) == 1, "the piped row must not be dropped"
    assert rows[0]["headline"] == "fit is strong | dominant signal"
    assert rows[0]["package_id"] == "kras-coad-v1"
    assert rows[0]["class_calls"] == {"dependency-depmap": "dependent"}
