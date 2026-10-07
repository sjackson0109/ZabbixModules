"""Meaningful replay-template contract checks independent of a Zabbix daemon."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import uuid

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("lab_templates", ROOT / "templates/generate_lab.py")
LAB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAB)


def evaluate(script: str, value: dict, interface_uid: str = "if-test") -> dict:
    if shutil.which("node") is None:
        pytest.skip("Node is needed to exercise generated JavaScript preprocessing")
    script = script.replace("{#IFUID}", interface_uid)
    runner = ("const fs=require('fs');const input=JSON.parse(fs.readFileSync(0,'utf8'));"
              "try{console.log(JSON.stringify({ok:true,value:new Function('value',input.script)(JSON.stringify(input.value))}));}"
              "catch(e){console.log(JSON.stringify({ok:false,error:String(e)}));}")
    result = subprocess.run(["node", "-e", runner], input=json.dumps({"script": script, "value": value}),
                            text=True, capture_output=True, check=True, timeout=10)
    return json.loads(result.stdout)


def envelope(status: str = "ok", complete: bool = True, data: list | None = None) -> dict:
    return {"schema_version": "1.0", "dataset": "interfaces", "generation_id": "lab-generation",
            "attempted_at": "2026-10-06T12:00:00Z", "observed_at": "2026-10-06T12:00:00Z",
            "status": status, "complete": complete,
            "source": {"method": "fixture", "adapter": "lab", "version": "0.1"},
            "capability": {"state": "supported", "reason": None}, "errors": [],
            "data": data if data is not None else [{"uid": "if-test", "name": "Ethernet1", "if_index": 1,
                                                    "oper_status": "up", "admin_status": "up", "speed_bps": 1_000_000_000}]}


@pytest.mark.parametrize("version", ["7.0", "7.2", "7.4"])
def test_generated_exports_are_current_and_lab_only(version):
    path = ROOT / "templates/lab" / version / "network_explorer_lab.yaml"
    definition = yaml.safe_load(path.read_text())
    assert definition == LAB.build(version)
    templates = definition["zabbix_export"]["templates"]
    assert len(templates) == 1
    assert templates[0]["template"] == "Network Explorer LAB replay"
    assert "LAB ONLY" in templates[0]["description"]
    assert not any(i["type"] == "SNMP_AGENT" for i in templates[0]["items"])
    assert uuid.UUID(templates[0]["uuid"]).version == 4
    keys = [i["key"] for i in templates[0]["items"]]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("status,complete", [("partial", False), ("failed", False), ("unsupported", True), ("ok", False)])
def test_partial_failed_or_unsupported_cannot_overwrite_retained_snapshot(status, complete):
    outcome = evaluate(LAB.gate("interfaces"), envelope(status, complete, []))
    assert not outcome["ok"]
    source = LAB.build("7.0")["zabbix_export"]["templates"][0]
    snapshot = next(i for i in source["items"] if i["key"] == "ne.interfaces.inventory")
    assert snapshot["preprocessing"][0]["error_handler"] == "DISCARD_VALUE"
    assert source["discovery_rules"][0]["master_item"]["key"] == "ne.interfaces.inventory"


def test_complete_empty_inventory_is_distinct_from_a_failed_empty_attempt():
    outcome = evaluate(LAB.gate("interfaces"), envelope(data=[]))
    assert outcome["ok"]
    assert json.loads(outcome["value"])["data"] == []


@pytest.mark.parametrize("timestamp", [None, "not-a-date", "2026-10-06"])
def test_invalid_observation_time_cannot_refresh_success(timestamp):
    value = envelope()
    value["observed_at"] = timestamp
    assert not evaluate(LAB.gate("interfaces"), value)["ok"]


def test_status_mapping_and_unknown_speed_do_not_invent_health():
    value = envelope()
    assert evaluate(LAB.scalar("oper_status"), value)["value"] == 1
    assert evaluate(LAB.scalar("expected_speed_bps", unknown=0), value)["value"] == 0
    value["data"][0]["speed_bps"] = None
    assert not evaluate(LAB.scalar("speed_bps"), value)["ok"]
    value["data"][0]["oper_status"] = "lower_layer_down"
    assert evaluate(LAB.scalar("oper_status"), value)["value"] == 7


def test_absent_interface_does_not_emit_fake_zero():
    assert not evaluate(LAB.scalar("speed_bps"), envelope(data=[]))["ok"]


def test_unsafe_or_duplicate_uid_cannot_reach_lld_or_scalar_javascript():
    duplicate = envelope()
    duplicate["data"].append(dict(duplicate["data"][0]))
    assert not evaluate(LAB.gate("interfaces"), duplicate)["ok"]
    unsafe = envelope()
    unsafe["data"][0]["uid"] = "');throw 'injected';//"
    assert not evaluate(LAB.gate("interfaces"), unsafe)["ok"]


def test_missing_ifname_uses_description_for_discovery_display_only():
    definition = LAB.build("7.0")["zabbix_export"]["templates"][0]
    source = envelope()
    source["data"][0]["name"] = None
    source["data"][0]["description"] = "Port One"
    script = definition["discovery_rules"][0]["preprocessing"][0]["parameters"][0]
    result = evaluate(script, source)
    assert json.loads(result["value"])[0]["name"] == "Port One"


def test_profiles_have_no_unearned_model_support_claims():
    profiles = json.loads((ROOT / "templates/profiles/unqualified.json").read_text())["profiles"]
    assert len(profiles) == 9
    assert all(p["qualification"] == "unqualified" for p in profiles)
    assert all(not p["selector"]["models"] and not p["selector"]["sysobjectid_prefixes"] for p in profiles)
    assert all(set(p["capabilities"].values()) == {"unknown"} for p in profiles)


def test_dashboard_recipes_have_no_instance_ids_or_automatic_writes():
    recipes = json.loads((ROOT / "dashboards/recipes.json").read_text())
    assert recipes["artifact_type"] == "portable provisioning recipes, not direct API payloads"
    for recipe in recipes["recipes"]:
        assert recipe["mutation_policy"].startswith("proposal/diff only")
        assert all("resolve" in f or f["type"] == "STRING"
                   for page in recipe["pages"] for widget in page["widgets"] for f in widget["fields"])
