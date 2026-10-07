"""The proposed 1.1 schema accepts its worked examples and keeps 1.0 rules."""
import copy
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]
PROPOSED = ROOT / "schemas/proposed"


@pytest.fixture(scope="module")
def validator():
    schema = json.loads((PROPOSED / "envelope-1.1.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


@pytest.mark.parametrize("name", ["vlan", "stp", "port_capability", "lldp"])
def test_examples_validate(validator, name):
    validator.validate(json.loads((PROPOSED / "examples" / f"{name}.json").read_text()))


def test_vlan_ranges_reject_garbage(validator):
    envelope = json.loads((PROPOSED / "examples/vlan.json").read_text())
    envelope["data"][3]["tagged"] = "49;rm -rf"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(envelope)


def test_stp_rows_need_a_kind(validator):
    envelope = json.loads((PROPOSED / "examples/stp.json").read_text())
    del envelope["data"][1]["kind"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(envelope)


def test_failed_envelope_still_cannot_carry_data(validator):
    envelope = copy.deepcopy(json.loads((PROPOSED / "examples/vlan.json").read_text()))
    envelope.update(status="failed", complete=False, observed_at=None,
                    capability={"state": "unknown", "reason": "timeout"},
                    errors=[{"code": "timeout", "message": "walk timed out"}])
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(envelope)
    envelope["data"] = []
    validator.validate(envelope)
