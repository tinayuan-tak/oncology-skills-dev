"""report_render — schema validation: the spine + JSON report-view validate against their JSON Schemas,
and the skill_report schema tolerates the additive slots the spine-repoint workstream introduces."""
import json
from pathlib import Path

import pytest

from _skills_common.report_render._fixtures import make_nomination, make_null_heavy_nomination
from _skills_common.report_render import PRESETS, build_ir, resolve_spec
from _skills_common.report_render.backends.json_backend import JsonBackend

SKILLS = Path(__file__).resolve().parents[2]  # skills/

jsonschema = pytest.importorskip("jsonschema")

SCHEMA_DIR = SKILLS / "_skills_common" / "report_render" / "schemas"


def _load(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text())


def test_each_skill_report_validates():
    schema = _load("skill_report.schema.json")
    reports = make_nomination()["target_report"]["skill_reports"]
    assert reports
    for rep in reports.values():
        jsonschema.validate(rep, schema)


def test_target_report_validates():
    jsonschema.validate(make_nomination()["target_report"], _load("target_report.schema.json"))


def test_report_view_validates_every_preset_and_fixture():
    schema = _load("report_view.schema.json")
    for nom in (make_nomination(), make_null_heavy_nomination(), {}):
        for preset in list(PRESETS) + [None]:
            obj = JsonBackend().to_obj(build_ir(nom, resolve_spec(preset)))
            jsonschema.validate(obj, schema)  # internal #/definitions refs only


def test_skill_report_schema_tolerates_incoming_spine_slots():
    # feat/spine-repoint-modality-fit adds modality_scope + claim_scalars — schema must stay valid.
    schema = _load("skill_report.schema.json")
    rep = dict(next(iter(make_nomination()["target_report"]["skill_reports"].values())),
               modality_scope={"small_molecule": "supportive", "degrader": "supportive"},
               claim_scalars={"homogeneity": 0.82})
    jsonschema.validate(rep, schema)
