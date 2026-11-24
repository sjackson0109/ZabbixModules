"""Hardware health producers of the vendor templates, replayed on the anonymised captures under
tests/fixtures/qualification and validated against canonical schema 1.2."""
import json
import shutil
import subprocess
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tests/js/run_normaliser.cjs"
CAPTURES = ROOT / "tests/fixtures/qualification"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")


@pytest.fixture(scope="module")
def validator():
    schema = json.loads((ROOT / "schemas/envelope-1.2.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def run(raw_key: str, path: Path, *extra: str):
    out = subprocess.run(["node", str(RUNNER), raw_key, str(path), *extra],
                         check=True, capture_output=True, text=True).stdout
    return out if extra else json.loads(out)


def capture(label: str) -> Path:
    return CAPTURES / label / "capture.snmprec"


def kinds(envelope: dict, kind: str) -> list[dict]:
    return [row for row in envelope["data"] if row["kind"] == kind]


def present(envelope: dict, kind: str) -> list[dict]:
    return [row for row in kinds(envelope, kind) if row["state"] != "not_present"]


SMALL_BUSINESS = sorted(d.name for d in CAPTURES.iterdir()
                        if d.name.startswith("cisco-") and not d.name.startswith(("cisco-sg300", "cisco-cbs220")))


@pytest.mark.parametrize("label", SMALL_BUSINESS)
def test_small_business_captures_are_complete(validator, label):
    envelope = run("ne.raw.hw.ciscosb", capture(label))
    validator.validate(envelope)
    assert (envelope["status"], envelope["schema_version"], envelope["errors"]) == ("ok", "1.2", [])
    (cpu,) = kinds(envelope, "cpu")
    assert all(0 <= cpu[k] <= 100 for k in ("util_1s_pct", "util_1m_pct", "util_5m_pct"))
    for temperature in kinds(envelope, "temperature"):
        # The unit's own thresholds, never ours.
        assert temperature["state"] == "ok" and temperature["state_source"] == "device"
        assert 0 < temperature["celsius"] < temperature["warning_c"] < temperature["critical_c"]
    assert len(present(envelope, "psu")) == len(kinds(envelope, "temperature"))  # one supply fitted per unit


def test_stack_reports_each_unit():
    envelope = run("ne.raw.hw.ciscosb", capture("cisco-cbs350-24p-4x-3.6.0.3"))
    assert [(r["uid"], r["unit"]) for r in kinds(envelope, "temperature")] == [("temperature-1", 1), ("temperature-2", 2)]
    assert sorted({r["unit"] for r in kinds(envelope, "psu")}) == [1, 2]
    assert [r["name"] for r in present(envelope, "psu")] == ["ps1_unit1", "ps1_unit2"]
    # Fanless units list their fan slots as not present, and those carry no speed.
    assert present(envelope, "fan") == [] and all(r["speed"] is None for r in kinds(envelope, "fan"))


def test_fan_speeds_join_by_fan_number():
    envelope = run("ne.raw.hw.ciscosb", capture("cisco-sg350x-48p-2.5.9.54"))
    fans = present(envelope, "fan")
    assert [r["name"] for r in fans] == ["fan1_unit1", "fan2_unit1", "fan3_unit1"]
    assert all(r["state"] == "ok" and r["speed"] > 0 for r in fans)


def test_sg300_unreadable_sensor_is_unavailable_not_zero(validator):
    envelope = run("ne.raw.hw.ciscosb.v1", capture("cisco-sg300-28pp-1.4.11.5"))
    validator.validate(envelope)
    assert envelope["status"] == "ok"
    (temperature,) = kinds(envelope, "temperature")
    assert (temperature["state"], temperature["celsius"]) == ("unavailable", None)
    assert kinds(envelope, "psu") == []


@pytest.mark.parametrize("raw_key, label", [
    ("ne.raw.hw.ciscosb", "cisco-sg300-28pp-1.4.11.5"),     # 14-column table read as 24
    ("ne.raw.hw.ciscosb.v1", "cisco-sg350-28p-2.5.9.54"),   # 24-column table read as 14
])
def test_wrong_layout_is_partial_and_never_guessed(validator, raw_key, label):
    envelope = run(raw_key, capture(label))
    validator.validate(envelope)
    assert envelope["status"] == "partial"
    assert [e["code"] for e in envelope["errors"]] == ["layout_mismatch"]
    assert kinds(envelope, "temperature") == []


def test_dell_x_reports_overall_status_and_its_own_sensor(validator):
    envelope = run("ne.raw.hw.dellx", capture("dell-x1052-3.0.1.9"))
    validator.validate(envelope)
    assert envelope["status"] == "ok"
    assert [r["state"] for r in kinds(envelope, "global")] == ["ok"]
    (temperature,) = kinds(envelope, "temperature")
    assert temperature["state"] == "ok" and temperature["celsius"] > 0 and temperature["warning_c"] is None


@pytest.mark.parametrize("label, sensors, fans", [("dell-n1548p-6.8.1.9", 8, 2), ("dell-n4064-6.5.4.23", 4, 6)])
def test_dell_n_unit_tables(validator, label, sensors, fans):
    envelope = run("ne.raw.hw.dnos6", capture(label))
    validator.validate(envelope)
    assert envelope["status"] == "ok"
    assert len(present(envelope, "temperature")) == sensors and len(present(envelope, "fan")) == fans
    assert all(r["unit"] == 1 and r["speed"] > 0 for r in present(envelope, "fan"))
    (memory,) = kinds(envelope, "memory")
    assert memory["free_bytes"] < memory["total_bytes"] and 0 < memory["util_pct"] < 100
    (cpu,) = kinds(envelope, "cpu")
    assert {"util_5s_pct", "util_1m_pct", "util_5m_pct"} <= set(cpu)


def test_device_without_vendor_tables_is_unsupported(validator):
    envelope = run("ne.raw.hw.ciscosb", capture("cisco-cbs220-24p-4g-2.0.2.15"))
    validator.validate(envelope)
    assert (envelope["status"], envelope["data"]) == ("unsupported", [])


def test_dropped_column_is_partial(tmp_path, validator):
    # A walk that lost the uptime column (a timeout part-way through the table) must not look complete.
    walk = run("ne.raw.hw.ciscosb", capture("cisco-sg350-28p-2.5.9.54"), "--walk-only")
    cut = "\n".join(line for line in walk.splitlines() if ".1.3.6.1.4.1.9.6.1.101.53.15.1.14." not in line)
    path = tmp_path / "cut.walk"
    path.write_text(cut, encoding="utf-8")
    envelope = run("ne.raw.hw.ciscosb", path)
    validator.validate(envelope)
    assert envelope["status"] == "partial" and kinds(envelope, "temperature") == []


@pytest.mark.parametrize("raw_key", ["ne.raw.hw.ciscosb", "ne.raw.hw.dnos6"])
def test_failed_collection(validator, tmp_path, raw_key):
    path = tmp_path / "failed.walk"
    path.write_text("__NE_COLLECTION_FAILED__", encoding="utf-8")
    envelope = run(raw_key, path)
    validator.validate(envelope)
    assert (envelope["status"], envelope["data"]) == ("failed", [])


def test_uids_are_unique_and_safe():
    import re
    for raw_key, label in [("ne.raw.hw.ciscosb", "cisco-cbs350-24p-4x-3.6.0.3"), ("ne.raw.hw.dnos6", "dell-n4064-6.5.4.23")]:
        uids = [r["uid"] for r in run(raw_key, capture(label))["data"]]
        assert len(uids) == len(set(uids))
        assert all(re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", u) for u in uids)
