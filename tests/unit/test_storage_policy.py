"""The native templates' storage policy: what is stored on change, what every poll, and that a device which has not
changed produces byte-identical stored JSON from one poll to the next, so "Discard unchanged with heartbeat" drops it.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("storage_snmp", ROOT / "templates/generate_snmp.py")
GEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GEN)
WIFI_SPEC = importlib.util.spec_from_file_location("storage_wifi", ROOT / "templates/generate_wifi.py")
WIFI = importlib.util.module_from_spec(WIFI_SPEC)
WIFI_SPEC.loader.exec_module(WIFI)
CAPTURES = ROOT / "tests/fixtures/qualification"
NORMALISER = ROOT / "tests/js/run_normaliser.cjs"
STEPS = ROOT / "tests/js/run_steps.cjs"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")

POLL_S = 150
# TimeTicks that advance with the clock; every other TimeTicks value (ifLastChange, LLDP and VLAN time marks) is an
# absolute point in the device's uptime and stays put.
ADVANCING = ("1.3.6.1.2.1.1.3.0", "1.3.6.1.2.1.17.2.3.0")
T0 = 1_795_000_000_000  # 2026-11-17, a fixed clock in milliseconds


def templates(build) -> dict:
    return {t["template"]: t for t in build("7.4")["zabbix_export"]["templates"]}


def all_objects(template: dict):
    yield from template.get("items", [])
    for rule in template.get("discovery_rules", []):
        yield rule
        yield from rule.get("item_prototypes", [])


def later(capture: Path, target: Path, seconds: int) -> Path:
    """The same device `seconds` later: uptime and the time since the last topology change have advanced."""
    lines = []
    for line in capture.read_text(encoding="utf-8").splitlines():
        oid, tag, value = line.split("|", 2)
        if oid in ADVANCING and tag == "67":
            value = str(int(value) + seconds * 100)
        lines.append(f"{oid}|{tag}|{value}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def normalise(raw_key: str, walk: Path, now_ms: int) -> str:
    env = dict(os.environ, NE_TEST_NOW=str(now_ms))
    return subprocess.run(["node", str(NORMALISER), raw_key, str(walk)], check=True, capture_output=True, text=True,
                          encoding="utf-8", env=env).stdout.strip()


def steps(item: dict, value: str) -> dict:
    payload = json.dumps({"steps": item["preprocessing"], "value": value})
    return json.loads(subprocess.run(["node", str(STEPS)], input=payload, check=True, capture_output=True, text=True,
                                     encoding="utf-8").stdout)


# (capture, template, raw key): every stored snapshot, on captured walks.
CASES = [
    ("cisco-cbs350-24fp-4x-3.6.0.3", "ne_cisco_small_business_switch", key)
    for key in ("ne.raw.system", "ne.raw.if.state", "ne.raw.if.link", "ne.raw.if.inventory", "ne.raw.lldp",
                "ne.raw.vlan", "ne.raw.stp", "ne.raw.lag", "ne.raw.hw.ciscosb", "ne.raw.poe.ifindex")
] + [("dell-n1548p-6.8.1.9", "ne_dell_n_series_switch", "ne.raw.hw.dnos6")]


@needs_node
@pytest.mark.parametrize("capture, template, raw_key", CASES)
def test_an_unchanged_device_stores_identical_json(tmp_path, capture, template, raw_key):
    entry = next(e for e in GEN.manifest() if e["raw_key"] == raw_key)
    items = {i["key"]: i for i in templates(GEN.build)[template]["items"]}
    walk = CAPTURES / capture / "capture.snmprec"
    first = normalise(raw_key, walk, T0)
    second = normalise(raw_key, later(walk, tmp_path / "later.snmprec", POLL_S), T0 + POLL_S * 1000)
    assert json.loads(first)["status"] == "ok" and first != second, "the canonical envelopes differ in time"
    for key in [entry["attempt_key"], *entry["snapshot_keys"]]:
        a, b = steps(items[key], first), steps(items[key], second)
        assert a.get("throttle") == "{$NE.HEARTBEAT}", key
        assert "value" in a and a["value"] == b["value"], (key, "a repeat would be stored")
        stored = json.loads(a["value"])
        assert stored["timing"] == "zabbix"
        assert not {"attempted_at", "observed_at", "generation_id"} & set(stored), key
        for row in stored["data"]:
            assert not {"uptime_s", "time_since_topology_change_s", "observed_at"} & set(row), (key, row)


@needs_node
def test_a_change_is_stored(tmp_path):
    walk = CAPTURES / "cisco-cbs350-24fp-4x-3.6.0.3" / "capture.snmprec"
    item = {i["key"]: i for i in templates(GEN.build)["ne_cisco_small_business_switch"]["items"]}["ne.interfaces.state"]
    first = steps(item, normalise("ne.raw.if.state", walk, T0))["value"]
    lines = walk.read_text(encoding="utf-8").splitlines()
    down = next(i for i, line in enumerate(lines) if line.startswith("1.3.6.1.2.1.2.2.1.8.") and line.endswith("|2|1"))
    lines[down] = lines[down][:-1] + "2"   # one port goes down
    changed = tmp_path / "changed.snmprec"
    changed.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert steps(item, normalise("ne.raw.if.state", changed, T0 + POLL_S * 1000))["value"] != first


def test_states_snapshots_and_receipts_are_throttled_and_readings_are_not():
    throttle = {"type": "DISCARD_UNCHANGED_HEARTBEAT", "parameters": ["{$NE.HEARTBEAT}"]}
    readings = re.compile(r"^ne\.(hw\.cpu\.util|hw\.memory\.util|hw\.fan\.speed|hw\.temp\.value|poe\.pse\.consumption"
                          r"|poe\.pse\.util|poe\.port\.power)\b")
    every_poll = re.compile(r"^ne\.(collection\.success|device\.uptime)\b")
    for name, template in templates(GEN.build).items():
        macros = {m["macro"]: m["value"] for m in template["macros"]}
        assert macros["{$NE.HEARTBEAT}"] == "2h" and macros["{$NE.TRENDS}"] == "180d", name
        for obj in all_objects(template):
            key, steps_ = obj["key"], obj.get("preprocessing", [])
            if obj.get("type") == "SNMP_AGENT" or key.startswith("ne.normalised["):
                assert obj["history"] == "0" and throttle not in steps_, key
            elif readings.match(key):
                assert throttle not in steps_ and obj["trends"] == "{$NE.TRENDS}", key
            elif every_poll.match(key):
                assert throttle not in steps_, key
            else:
                # States, snapshots, receipts and discovery lists: stored when they change.
                assert steps_[-1] == throttle, (name, key)
            if key.endswith(".discovery"):
                assert obj["master_item"]["key"].startswith("ne.normalised["), key


def test_trends_are_kept_only_for_readings():
    for template in templates(GEN.build).values():
        for obj in all_objects(template):
            if obj.get("value_type") in ("UNSIGNED", "FLOAT") and "trends" in obj:
                assert obj["trends"] in ("0", "{$NE.TRENDS}"), obj["key"]
            elif obj.get("value_type") in ("UNSIGNED", "FLOAT") and not obj["key"].endswith(".discovery"):
                pytest.fail(f"{obj['key']} would keep Zabbix's default trends")


def test_walks_are_polled_by_how_fast_their_data_changes():
    intervals = {GEN.producer(e): e["interval"] for e in GEN.manifest()}
    assert intervals == {"device": "1h", "interfaces": "150s", "interfaces.link": "15m", "interfaces.inventory": "1h",
                         "port_capability": "6h", "lldp": "15m", "vlan": "30m", "stp": "5m", "lag": "15m",
                         "hardware": "5m", "poe": "5m", "poe.power": "15m"}
    seconds = lambda text: int(text[:-1]) * {"s": 1, "m": 60, "h": 3600}[text[-1]]  # noqa: E731
    for entry in GEN.manifest():
        # The staleness alert allows three missed polls.
        assert seconds(entry["stale"]) == 3 * seconds(entry["interval"]), GEN.producer(entry)
    walks = {GEN.producer(e): set(e["walk"]) for e in GEN.manifest() if not e.get("templates") or
             "ne__generic_switch" in e["templates"]}
    speed, duplex, oper = "1.3.6.1.2.1.31.1.1.1.15", "1.3.6.1.2.1.10.7.2.1.19", "1.3.6.1.2.1.2.2.1.8"
    assert oper in walks["interfaces"] and not {speed, duplex} & walks["interfaces"]
    assert {speed, duplex} <= walks["interfaces.link"] and oper not in walks["interfaces.link"]
    assert "1.3.6.1.2.1.105.1.3.1.1.4" in walks["poe.power"] and "1.3.6.1.2.1.105.1.3.1.1.4" not in walks["poe"]


def test_wifi_templates_follow_the_same_policy():
    throttle = {"type": "DISCARD_UNCHANGED_HEARTBEAT", "parameters": ["{$WE.HEARTBEAT}"]}
    for name, template in templates(WIFI.build).items():
        macros = {m["macro"]: m["value"] for m in template["macros"]}
        assert macros["{$WE.HEARTBEAT}"] == "2h", name
        if "{$WE.CAPACITY.TRENDS}" in macros:
            assert macros["{$WE.CAPACITY.TRENDS}"] == "180d", name
        for item in template["items"]:
            key = item["key"]
            if re.match(r"^we\.(.*\.attempt|.*\.snapshot|ap\.inventory|ap\.state|radio\.inventory|radio\.state|ssid"
                        r"|client\.snapshot|rf\.neighbour|collection\.status\[)", key):
                assert item["preprocessing"][-1] == throttle, (name, key)
            if key.startswith(("we.capacity.", "we.collection.success[")):
                assert throttle not in item["preprocessing"], (name, key)
