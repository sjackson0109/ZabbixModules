"""PoE producers replayed on the anonymised captures under tests/fixtures/qualification, and the CISCO-ENVMON-MIB
hardware producer on a synthetic walk, all validated against canonical schema 1.2."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tests/js/run_normaliser.cjs"
CAPTURES = ROOT / "tests/fixtures/qualification"
UPTIME = "1.3.6.1.2.1.1.3.0|67|60480000"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")


@pytest.fixture(scope="module")
def validator():
    schema = json.loads((ROOT / "schemas/envelope-1.2.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def run(raw_key: str, path: Path) -> dict:
    return json.loads(subprocess.run(["node", str(RUNNER), raw_key, str(path)], check=True, capture_output=True,
                                     text=True).stdout)


def capture(label: str) -> Path:
    return CAPTURES / label / "capture.snmprec"


def rows(envelope: dict, kind: str) -> list[dict]:
    return [row for row in envelope["data"] if row["kind"] == kind]


def walk(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "synthetic.snmprec"
    path.write_text("\n".join([UPTIME, *lines]) + "\n", encoding="utf-8")
    return path


POE_CAPTURES = sorted(d.name for d in CAPTURES.iterdir() if (d / "capture.snmprec").is_file()
                      and "1.3.6.1.2.1.105.1.1.1.3." in (d / "capture.snmprec").read_text(encoding="utf-8"))
CISCOSB = [label for label in POE_CAPTURES if label.startswith("cisco-") and "cbs220" not in label]


def test_every_poe_capture_is_covered():
    assert len(POE_CAPTURES) == 14 and "dell-n1548p-6.8.1.9" in POE_CAPTURES and "cisco-cbs220-24p-4g-2.0.2.15" in POE_CAPTURES


@pytest.mark.parametrize("label", POE_CAPTURES)
@pytest.mark.parametrize("raw_key", ["ne.raw.poe", "ne.raw.poe.ifindex"])
def test_standard_tables_are_complete(validator, raw_key, label):
    envelope = run(raw_key, capture(label))
    validator.validate(envelope)
    assert (envelope["status"], envelope["schema_version"], envelope["errors"]) == ("ok", "1.2", [])
    ports, units = rows(envelope, "port"), rows(envelope, "pse")
    assert ports and units
    # Each delivering port has a class; no other port does (RFC 3621: valid only while delivering power).
    assert all((p["power_class"] is not None) == (p["state"] == "delivering") for p in ports)
    for unit in units:
        if unit["state"] != "not_present":
            assert unit["port_count"] > 0 and 0 < unit["power_w"] and unit["consumption_w"] <= unit["power_w"]
            assert unit["usage_threshold_pct"] is not None
    assert sum(u["port_count"] for u in units) == len(ports)
    if raw_key == "ne.raw.poe":
        # RFC 3621 maps no port to an interface, so the generic producer never claims one.
        assert all(p["interface_uid"] is None and re.fullmatch(r"Port \d+/\d+", p["name"]) for p in ports)
    else:
        # In every capture the port index is the ifIndex of a copper port on the same unit.
        assert all(p["if_index"] == p["port"] and p["interface_uid"].startswith("if-") for p in ports)
        assert envelope["warnings"] == []


@pytest.mark.parametrize("label", CISCOSB)
def test_cisco_small_business_reports_port_power(validator, label):
    envelope = run("ne.raw.poe.ciscosb", capture(label))
    validator.validate(envelope)
    assert (envelope["status"], envelope["warnings"]) == ("ok", [])
    ports = rows(envelope, "port")
    assert all(p["power_mw"] is not None and p["power_limit_mw"] > 0 for p in ports)
    # Power flows only to the ports the PSE reports as delivering.
    assert {p["uid"] for p in ports if p["power_mw"] > 0} <= {p["uid"] for p in ports if p["state"] == "delivering"}
    for unit in rows(envelope, "pse"):
        if unit["state"] == "on":
            drawn = sum(p["power_mw"] for p in ports if p["unit"] == unit["unit"]) / 1000
            # pethMainPseConsumptionPower is whole watts. The 350-class firmware reports the power allocated to
            # its ports there (the sum of rlPethPsePortStaticPowerAllocation), the SG300 the power drawn, so the
            # unit's figure is never below what its ports draw (templates/specifications/POE.md).
            assert drawn <= unit["consumption_w"] + 1, (label, unit)


def test_350_class_consumption_is_the_allocated_power():
    envelope = run("ne.raw.poe.ciscosb", capture("cisco-cbs350-24fp-4x-3.6.0.3"))
    (unit,) = [u for u in rows(envelope, "pse") if u["state"] != "not_present"]
    drawn = sum(p["power_mw"] for p in rows(envelope, "port")) / 1000
    assert unit["consumption_w"] == 249 and round(drawn) == 81


def test_stack_slots_without_a_unit_are_not_present():
    envelope = run("ne.raw.poe.ciscosb", capture("cisco-cbs350-24p-4x-3.6.0.3"))
    units = {u["uid"]: u for u in rows(envelope, "pse")}
    assert [u["state"] for u in units.values()] == ["on", "on", "not_present", "not_present"]
    assert units["pse-3"]["raw_state"] == 3 and units["pse-3"]["power_w"] is None  # the agent calls it faulty
    assert {p["name"].split("/")[0] for p in rows(envelope, "port")} == {"gi1", "gi2"}


def test_vendor_power_needs_the_vendor_table():
    envelope = run("ne.raw.poe.ciscosb", capture("cisco-cbs220-24p-4g-2.0.2.15"))
    assert envelope["status"] == "ok" and [w["code"] for w in envelope["warnings"]] == ["vendor_power_missing"]
    assert all(p["power_mw"] is None for p in rows(envelope, "port"))


def test_a_device_without_poe_is_unsupported(validator):
    envelope = run("ne.raw.poe", capture("cisco-sg350xg-24f-2.5.9.54"))
    validator.validate(envelope)
    assert (envelope["status"], envelope["data"]) == ("unsupported", [])


def test_a_lost_port_table_is_partial(validator, tmp_path):
    path = walk(tmp_path, ["1.3.6.1.2.1.105.1.3.1.1.2.1|66|195", "1.3.6.1.2.1.105.1.3.1.1.3.1|2|1",
                           "1.3.6.1.2.1.105.1.3.1.1.4.1|66|40", "1.3.6.1.2.1.105.1.3.1.1.5.1|2|95"])
    envelope = run("ne.raw.poe", path)
    validator.validate(envelope)
    assert envelope["status"] == "partial" and [e["code"] for e in envelope["errors"]] == ["port_table_missing"]


def test_unmapped_port_is_named_by_group_and_port(validator, tmp_path):
    path = walk(tmp_path, ["1.3.6.1.2.1.2.2.1.2.1|4|eth1", "1.3.6.1.2.1.31.1.1.1.1.1|4|eth1",
                           "1.3.6.1.2.1.105.1.1.1.3.1.7|2|1", "1.3.6.1.2.1.105.1.1.1.6.1.7|2|4",
                           "1.3.6.1.2.1.105.1.3.1.1.3.1|2|3"])
    envelope = run("ne.raw.poe.ifindex", path)
    validator.validate(envelope)
    assert envelope["status"] == "ok" and [w["code"] for w in envelope["warnings"]] == ["port_unmapped"]
    (port,) = rows(envelope, "port")
    assert (port["name"], port["state"], port["interface_uid"]) == ("Port 1/7", "fault", None)
    assert rows(envelope, "pse")[0]["state"] == "faulty"


ENVMON = "1.3.6.1.4.1.9.9.13.1"


def test_envmon_rows_carry_the_devices_own_states(validator, tmp_path):
    # Synthetic: built from CISCO-ENVMON-MIB, not from a device; no capture has walked it yet.
    path = walk(tmp_path, [
        f"{ENVMON}.3.1.2.1|4|Board", f"{ENVMON}.3.1.3.1|66|41", f"{ENVMON}.3.1.4.1|2|75", f"{ENVMON}.3.1.6.1|2|1",
        f"{ENVMON}.3.1.7.1|2|41",
        f"{ENVMON}.3.1.2.2|4|Inlet", f"{ENVMON}.3.1.3.2|66|0", f"{ENVMON}.3.1.6.2|2|5",
        f"{ENVMON}.4.1.2.1|4|Fan 1", f"{ENVMON}.4.1.3.1|2|1", f"{ENVMON}.4.1.2.2|4|Fan 2", f"{ENVMON}.4.1.3.2|2|3",
        f"{ENVMON}.5.1.2.1|4|PSU 1", f"{ENVMON}.5.1.3.1|2|1", f"{ENVMON}.5.1.4.1|2|2",
    ])
    envelope = run("ne.raw.hw.envmon", path)
    validator.validate(envelope)
    assert envelope["status"] == "ok"
    board, inlet = rows(envelope, "temperature")
    assert (board["celsius"], board["state"], board["shutdown_c"], board["critical_c"]) == (41, "ok", 75, None)
    assert (inlet["state"], inlet["celsius"]) == ("not_present", None)
    assert [(f["name"], f["state"]) for f in rows(envelope, "fan")] == [("Fan 1", "ok"), ("Fan 2", "critical")]
    assert [(p["state"], p["source"]) for p in rows(envelope, "psu")] == [("ok", "ac")]


def test_envmon_absent_is_unsupported(validator):
    envelope = run("ne.raw.hw.envmon", capture("cisco-cbs220-24p-4g-2.0.2.15"))
    validator.validate(envelope)
    assert envelope["status"] == "unsupported"
