"""Contract checks for the generated native SNMP templates, independent of a Zabbix daemon."""
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
SPEC = importlib.util.spec_from_file_location("native_templates", ROOT / "templates/generate_snmp.py")
GEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GEN)
FIXTURES = ROOT / "tests/fixtures/walks"
VERSIONS = ("7.0", "7.2", "7.4")


def templates(version: str = "7.0") -> dict:
    return {t["template"]: t for t in GEN.build(version)["zabbix_export"]["templates"]}


def all_items(version: str = "7.0") -> list[dict]:
    result = []
    for template in templates(version).values():
        result += template.get("items", [])
        for rule in template.get("discovery_rules", []):
            result.append(rule)
            result += rule["item_prototypes"]
    return result


def node(script: str, value: str) -> str | None:
    """Runs one preprocessing script the way Zabbix would; None means the script threw."""
    if shutil.which("node") is None:
        pytest.skip("Node is needed to exercise generated JavaScript preprocessing")
    runner = ("const crypto=require('crypto');global.sha256=t=>crypto.createHash('sha256').update(String(t),'utf8').digest('hex');"
              "const i=JSON.parse(require('fs').readFileSync(0,'utf8'));"
              "try{console.log(JSON.stringify({v:String(new Function('value',i.s)(i.v))}));}catch(e){console.log('{}');}")
    out = subprocess.run(["node", "-e", runner], input=json.dumps({"s": script, "v": value}), text=True,
                         capture_output=True, check=True, timeout=20)
    return json.loads(out.stdout).get("v")


def apply(steps: list[dict], value: str) -> str | None:
    """Applies JAVASCRIPT and NOT_MATCHES_REGEX steps; None means the value was discarded."""
    import re
    for step in steps:
        if step["type"] == "JAVASCRIPT":
            value = node(step["parameters"][0], value)
            assert value is not None, "a JavaScript step threw; Zabbix would mark the item not supported"
        elif step["type"] == "NOT_MATCHES_REGEX":
            if re.search(step["parameters"][0], value):
                assert step["error_handler"] == "DISCARD_VALUE"
                return None
        else:
            raise AssertionError(step["type"])
    return value


def attempt(raw_key: str, fixture: str) -> str:
    walk = subprocess.run(["node", str(ROOT / "tests/js/run_normaliser.cjs"), raw_key, str(FIXTURES / fixture), "--walk-only"],
                          text=True, capture_output=True, check=True).stdout.rstrip("\n")
    item = next(i for i in all_items() if i["key"] == GEN.manifest()[[d["raw_key"] for d in GEN.manifest()].index(raw_key)]["attempt_key"])
    return apply(item["preprocessing"], walk)


@pytest.mark.parametrize("version", VERSIONS)
def test_generated_exports_are_current(version):
    path = ROOT / "templates/native" / version / "network_explorer_snmp.yaml"
    assert path.read_text() == GEN.render(version)
    assert yaml.safe_load(path.read_text())["zabbix_export"]["version"] == version


@pytest.mark.parametrize("version", VERSIONS)
def test_dashboard_template_is_current_and_holds_only_the_dashboard(version):
    path = ROOT / "templates/native" / version / "network_explorer_dashboard.yaml"
    assert path.read_text() == GEN.render_dashboard(version)
    template = GEN.build_dashboard(version)["zabbix_export"]["templates"][0]
    assert "items" not in template and "templates" not in template
    kinds = {w["type"] for page in template["dashboards"][0]["pages"] for w in page["widgets"]}
    assert kinds == {"neportpanel", "netopology", "neinterfacedetail", "nedataquality", "nefindings"}
    assert template["dashboards"][0]["auto_start"] == "NO"  # pages are tabs, not a slideshow


def test_uuids_are_unique_v4_and_keys_unique_per_template():
    seen = set()
    for template in templates().values():
        assert uuid.UUID(template["uuid"]).version == 4
        keys = [i["key"] for i in template.get("items", [])]
        assert len(keys) == len(set(keys))
        objects = [template] + template.get("items", []) + template.get("discovery_rules", [])
        for rule in template.get("discovery_rules", []):
            objects += rule["item_prototypes"]
        for obj in objects:
            for trigger in obj.get("triggers", []) + obj.get("trigger_prototypes", []):
                objects.append(trigger)
        for obj in objects:
            assert obj["uuid"] not in seen
            seen.add(obj["uuid"])


def test_every_dataset_has_one_producer_and_profile_links_them_all():
    owners = {}
    for name, template in templates().items():
        for item in template.get("items", []):
            assert item["key"] not in owners, f"{item['key']} owned by {owners.get(item['key'])} and {name}"
            owners[item["key"]] = name
    profile = templates()[GEN.PROFILE]
    assert "items" not in profile
    assert {t["name"] for t in profile["templates"]} == set(templates()) - {GEN.PROFILE}
    for entry in GEN.manifest():
        for key in [entry["raw_key"], entry["attempt_key"], *entry["snapshot_keys"]]:
            assert key in owners


def test_raw_walks_are_not_stored_and_turn_errors_into_failed_attempts():
    for entry in GEN.manifest():
        item = next(i for i in all_items() if i["key"] == entry["raw_key"])
        assert item["type"] == "SNMP_AGENT" and item["history"] == "0"
        assert item["snmp_oid"] == "walk[" + ",".join(entry["walk"]) + "]"
        step = item["preprocessing"][0]
        assert step == {"type": "CHECK_NOT_SUPPORTED", "parameters": ["-1"],
                        "error_handler": "CUSTOM_VALUE", "error_handler_params": GEN.FAILED}
        assert len(item["preprocessing"]) == 1


def test_javascript_steps_never_rely_on_custom_on_fail():
    # Zabbix silently drops error handlers on JavaScript steps at import.
    for item in all_items():
        for step in item.get("preprocessing", []):
            if step["type"] == "JAVASCRIPT":
                assert "error_handler" not in step, item["key"]


def test_no_credentials_or_secret_macros_in_templates():
    text = GEN.render("7.0").lower()
    for needle in ("community", "{$snmp_community", "authpassphrase", "privpassphrase", "password"):
        assert needle not in text


def test_attempt_scripts_emit_the_same_envelope_as_the_node_runner():
    if shutil.which("node") is None:
        pytest.skip("Node is needed")
    for entry in GEN.manifest():
        envelope = json.loads(attempt(entry["raw_key"], "sw-core-01.snmprec"))
        assert envelope["status"] == "ok", (entry["raw_key"], envelope["errors"])
        assert envelope["dataset"] == entry["dataset"]


def test_failed_collection_records_failed_attempt_and_discards_snapshot():
    entry = GEN.manifest()[1]
    items = {i["key"]: i for i in all_items()}
    envelope = apply(items[entry["attempt_key"]]["preprocessing"], GEN.FAILED)
    assert json.loads(envelope)["status"] == "failed"
    assert apply(items[entry["snapshot_keys"][0]]["preprocessing"], envelope) is None
    assert apply(items["ne.collection.success[interfaces]"]["preprocessing"], envelope) is None
    assert apply(items["ne.collection.status[interfaces]"]["preprocessing"], envelope) == "2"


def test_complete_snapshot_passes_gate_and_feeds_discovery_and_scalars():
    items = {i["key"]: i for i in all_items()}
    inventory = attempt("ne.raw.if.inventory", "sw-core-01.snmprec")
    assert apply(items["ne.interfaces.inventory"]["preprocessing"], inventory) == inventory
    lld = json.loads(apply(items["ne.interfaces.discovery"]["preprocessing"], inventory))
    gi23 = next(r for r in lld if r["name"] == "Gi1/0/23")
    assert gi23["physical"] == 1
    state = attempt("ne.raw.if.state", "sw-core-01.snmprec")
    speed = items["ne.if.speed[{#IFUID}]"]["preprocessing"]
    oper = items["ne.if.oper[{#IFUID}]"]["preprocessing"]
    sub = lambda steps: [dict(s, parameters=[p.replace("{#IFUID}", gi23["uid"]) for p in s["parameters"]]) for s in steps]  # noqa: E731
    assert apply(sub(speed), state) == "100000000"
    assert apply(sub(oper), state) == "1"
    absent = [dict(s, parameters=[p.replace("{#IFUID}", "if-absent") for p in s["parameters"]]) for s in speed]
    assert apply(absent, state) is None


def test_unsupported_dataset_does_not_raise_stale_trigger():
    for entry in GEN.manifest():
        name = GEN.producer(entry)
        item = next(i for i in all_items() if i["key"] == f"ne.collection.success[{name}]")
        expression = item["triggers"][0]["expression"]
        assert f"ne.collection.status[{name}])<>3" in expression
        assert GEN.stale_macro(entry) in expression


@pytest.mark.parametrize("version", VERSIONS)
def test_scripts_are_literal_blocks_never_folded(version):
    # Zabbix's YAML import inserts a space at each escaped line fold, which broke a regex literal in a script.
    for name in ("network_explorer_snmp.yaml", "network_explorer_dashboard.yaml"):
        text = (ROOT / "templates/native" / version / name).read_text()
        assert not any(line.endswith("\\") for line in text.splitlines()), name
        for token in yaml.scan(text):
            if isinstance(token, yaml.ScalarToken) and "\n" in token.value:
                assert token.style == "|", (name, token.value[:60])
