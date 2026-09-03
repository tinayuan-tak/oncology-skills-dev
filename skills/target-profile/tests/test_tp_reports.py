"""target-profile --reports wiring: tp_reports.write_reports emits report_render bundles, and the
'reports' kind is registered in tp_emit as an optional BEST_EFFORT artifact (write-set guard passes
whether or not the render succeeded)."""
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve()
SKILLS = HERE.parents[2]                 # skills/  (for _skills_common.report_render)
SCRIPTS = HERE.parents[1] / "scripts"    # target-profile/scripts (for tp_reports, tp_emit)
for _p in (str(SKILLS), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _skills_common.report_render._fixtures import make_nomination
import tp_emit
import tp_reports


def _args(**kw):
    base = dict(emit=None, verdict_only=False, no_figures=False, ground=False,
                full_package=False, substrate_chain_on=False, reports=None, report_backends=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_write_reports_creates_files(tmp_path):
    written = tp_reports.write_reports(tmp_path, make_nomination(), ["exec-brief"], ["markdown", "json"])
    assert written == {"reports"}
    assert (tmp_path / "reports" / "report_exec-brief.md").exists()
    assert (tmp_path / "reports" / "report_exec-brief.json").exists()


def test_write_reports_multiple_presets(tmp_path):
    tp_reports.write_reports(tmp_path, make_nomination(), ["exec-brief", "full"], ["json"])
    assert (tmp_path / "reports" / "report_exec-brief.json").exists()
    assert (tmp_path / "reports" / "report_full.json").exists()


def test_write_reports_failsoft_unknown_preset(tmp_path):
    assert tp_reports.write_reports(tmp_path, make_nomination(), ["nope"], ["json"]) == set()


def test_write_reports_empty_presets_is_noop(tmp_path):
    assert tp_reports.write_reports(tmp_path, make_nomination(), [], None) == set()
    assert not (tmp_path / "reports").exists()


def test_expected_artifacts_includes_reports_only_when_flag_set():
    assert "reports" in tp_emit.expected_artifacts(_args(reports="exec-brief"))
    assert "reports" not in tp_emit.expected_artifacts(_args(reports=None))
    assert "reports" in tp_emit.BEST_EFFORT_ARTIFACTS


def test_assert_write_set_passes_with_and_without_reports_written():
    args = _args(reports="exec-brief")
    want = set(tp_emit.expected_artifacts(args))
    tp_emit.assert_write_set(args, want)              # reports written
    tp_emit.assert_write_set(args, want - {"reports"})  # reports absent (best-effort) → still passes
