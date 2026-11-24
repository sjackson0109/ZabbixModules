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
WIFI_SPEC = importlib.util.spec_from_file_location("native_wifi_templates", ROOT / "templates/generate_wifi.py")
WIFI = importlib.util.module_from_spec(WIFI_SPEC)
WIFI_SPEC.loader.exec_module(WIFI)
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
        elif step["type"] == "DISCARD_UNCHANGED_HEARTBEAT":
            assert step["parameters"] == ["{$NE.HEARTBEAT}"]  # needs the previous value; tests/unit/test_storage_policy.py
        else:
            raise AssertionError(step["type"])
    return value


def entry_for(raw_key: str) -> dict:
    return next(e for e in GEN.manifest() if e["raw_key"] == raw_key)


def owner(raw_key: str) -> dict:
    """The first template that holds this producer: canonical keys repeat across templates, raw keys never do."""
    return next(t for t in templates().values() if any(i["key"] == raw_key for i in t["items"]))


def observe(raw_key: str, fixture: str | Path, template: str | None = None) -> str:
    """A walk's unstored canonical envelope, as the template's ne.normalised[<producer>] item produces it."""
    path = fixture if isinstance(fixture, Path) else FIXTURES / fixture
    walk = subprocess.run(["node", str(ROOT / "tests/js/run_normaliser.cjs"), raw_key, str(path), "--walk-only"],
                          text=True, capture_output=True, check=True).stdout.rstrip("\n")
    key = GEN.normalised_key(entry_for(raw_key))
    holder = templates()[template] if template else owner(raw_key)
    item = next(i for i in holder["items"] if i["key"] == key)
    return apply(item["preprocessing"], walk)


def stored(envelope: str) -> dict:
    """What a snapshot item keeps of a complete envelope: the same rows, no timestamps (StoredEnvelope.php)."""
    return {k: v for k, v in json.loads(envelope).items() if k not in ("attempted_at", "observed_at", "generation_id")}


def generic_producer(entry: dict) -> bool:
    return "templates" not in entry


@pytest.mark.parametrize("version", VERSIONS)
def test_generated_exports_are_current(version):
    files = GEN.render(version)
    # One file per template, named after it, and no stale export beside them.
    assert sorted(files) == sorted(p["template"] + ".yaml" for p in GEN.PROFILES)
    folder = ROOT / "templates/native" / version
    # The native folder holds exactly the two generators' files: ne_ switches, we_ access points.
    assert sorted(p.name for p in folder.iterdir()) == sorted([*files, *WIFI.render(version)])
    assert not any((folder / name).exists() for name in GEN.LEGACY_EXPORTS + WIFI.LEGACY_EXPORTS)
    for name, text in files.items():
        assert (folder / name).read_text(encoding="utf-8") == text, name
        export = yaml.safe_load(text)["zabbix_export"]
        assert export["version"] == version
        assert [t["template"] + ".yaml" for t in export["templates"]] == [name]
        # Each file carries only its own template group, the one its prefix names.
        assert [g["name"] for g in export["template_groups"]] == [g["name"] for g in export["templates"][0]["groups"]]


def test_generic_template_carries_the_host_dashboard():
    templates = {t["template"]: t for t in GEN.build("7.4")["zabbix_export"]["templates"]}
    dashboards = templates[GEN.PROFILE]["dashboards"]
    assert len(dashboards) == 1
    kinds = {w["type"] for page in dashboards[0]["pages"] for w in page["widgets"]}
    assert kinds == {"neportpanel", "netopology", "neinterfacedetail", "nedataquality", "nefindings"}
    assert dashboards[0]["auto_start"] == "NO"  # pages are tabs, not a slideshow
    assert not list((ROOT / "templates/native").glob("*/network_explorer_dashboard.yaml"))


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


def test_one_flat_template_per_device_type_owns_every_dataset():
    # Linking templates beside each other must never be needed: each exported template is self-contained.
    exported = templates()
    assert set(exported) == {p["template"] for p in GEN.PROFILES}
    for template in exported.values():
        assert "templates" not in template
    for profile in GEN.PROFILES:
        keys = {i["key"] for i in exported[profile["template"]]["items"]}
        for short in profile["components"]:
            mine = GEN.producers(profile, short, GEN.manifest())
            # Exactly one producer per dataset in each template, so every canonical key has one owner.
            assert mine and len({GEN.producer(e) for e in mine}) == len(mine), (profile["template"], short)
            for entry in mine:
                for key in [entry["raw_key"], entry["attempt_key"], *entry["snapshot_keys"]]:
                    assert key in keys, (profile["template"], key)
    generic = exported[GEN.PROFILE]
    keys = {i["key"] for i in generic["items"]}
    for entry in filter(generic_producer, GEN.manifest()):
        for key in [entry["raw_key"], entry["attempt_key"], *entry["snapshot_keys"]]:
            assert key in keys
    assert [r["key"] for r in generic["discovery_rules"]] == ["ne.interfaces.discovery", "ne.poe.pse.discovery",
                                                              "ne.poe.port.discovery"]
    # The per-AP Wi-Fi templates embed the LLDP component, item for item, under their own UUIDs.
    lldp = [i for i in generic["items"] if {"tag": "dataset", "value": "lldp"} in i["tags"]]
    def comparable(items, template):
        items = json.loads(json.dumps(items).replace(f"/{template}/", "/TEMPLATE/"))
        for item in items:
            item.pop("uuid")
            for trigger in item.get("triggers", []):
                trigger.pop("uuid")
        return items
    switch_uuids = {i["uuid"] for t in exported.values() for i in t["items"]}
    wifi = {t["template"]: t for t in WIFI.build("7.0")["zabbix_export"]["templates"]}
    for name in ("we__generic_access_point", "we_aruba_instant_access_point"):
        embedded = [i for i in wifi[name]["items"] if i["key"].startswith("ne.")]
        assert comparable(embedded, name) == comparable(lldp, GEN.PROFILE), name
        assert not {i["uuid"] for i in embedded} & switch_uuids, name
    assert not [i for i in wifi["we_aruba_instant_virtual_controller"]["items"] if i["key"].startswith("ne.")], \
        "the virtual controller's address floats between APs, so its LLDP would describe whichever AP holds it"


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
    text = "\n".join(GEN.render("7.0").values()).lower()
    for needle in ("community", "{$snmp_community", "authpassphrase", "privpassphrase", "password"):
        assert needle not in text


def test_attempt_scripts_emit_the_same_envelope_as_the_node_runner():
    if shutil.which("node") is None:
        pytest.skip("Node is needed")
    items = {i["key"]: i for i in all_items()}
    for entry in filter(generic_producer, GEN.manifest()):
        normalised = observe(entry["raw_key"], "sw-core-01.snmprec")
        envelope = json.loads(normalised)
        assert envelope["status"] == "ok", (entry["raw_key"], envelope["errors"])
        assert envelope["dataset"] == entry["dataset"]
        # The attempt item keeps a receipt: the outcome and row count, no rows and no timestamps.
        receipt = json.loads(apply(items[entry["attempt_key"]]["preprocessing"], normalised))
        assert receipt["data"] == [] and receipt["data_rows"] == len(envelope["data"]), entry["raw_key"]
        assert receipt["timing"] == "zabbix" and "attempted_at" not in receipt


def test_failed_collection_records_failed_attempt_and_discards_snapshot():
    entry = GEN.manifest()[1]
    items = {i["key"]: i for i in all_items()}
    envelope = apply(items[GEN.normalised_key(entry)]["preprocessing"], GEN.FAILED)
    assert json.loads(apply(items[entry["attempt_key"]]["preprocessing"], envelope))["status"] == "failed"
    assert apply(items[entry["snapshot_keys"][0]]["preprocessing"], envelope) is None
    assert apply(items["ne.collection.success[interfaces]"]["preprocessing"], envelope) is None
    assert apply(items["ne.collection.status[interfaces]"]["preprocessing"], envelope) == "2"


def test_complete_snapshot_passes_gate_and_feeds_discovery_and_scalars():
    items = {i["key"]: i for i in all_items()}
    inventory = observe("ne.raw.if.inventory", "sw-core-01.snmprec")
    kept = GEN.unpacked(json.loads(apply(items["ne.interfaces.inventory"]["preprocessing"], inventory)))
    assert kept.pop("timing") == "zabbix"
    # Rows are kept as observed, except that a port's last change, worked out from the device's uptime, is rounded
    # to the minute so that it reads the same at every poll.
    from datetime import datetime
    when = lambda text: datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()  # noqa: E731
    for row, original in zip(kept["data"], stored(inventory)["data"], strict=True):
        changed, exact = row.pop("last_change"), original.pop("last_change")
        assert row == original
        if exact is not None:
            assert changed.endswith(":00Z") and abs(when(changed) - when(exact)) <= 30
    lld = json.loads(apply(items["ne.interfaces.discovery"]["preprocessing"], inventory))
    gi23 = next(r for r in lld if r["name"] == "Gi1/0/23")
    assert gi23["physical"] == 1
    state = observe("ne.raw.if.state", "sw-core-01.snmprec")
    link = observe("ne.raw.if.link", "sw-core-01.snmprec")
    speed = items["ne.if.speed[{#IFUID}]"]["preprocessing"]
    oper = items["ne.if.oper[{#IFUID}]"]["preprocessing"]
    sub = lambda steps: [dict(s, parameters=[p.replace("{#IFUID}", gi23["uid"]) for p in s["parameters"]]) for s in steps]  # noqa: E731
    # Status from the status walk, speed from the link walk.
    assert apply(sub(speed), link) == "100000000"
    assert apply(sub(oper), state) == "1"
    assert items["ne.if.speed[{#IFUID}]"]["master_item"]["key"] == "ne.normalised[interfaces.link]"
    assert items["ne.if.oper[{#IFUID}]"]["master_item"]["key"] == "ne.normalised[interfaces]"
    absent = [dict(s, parameters=[p.replace("{#IFUID}", "if-absent") for p in s["parameters"]]) for s in speed]
    assert apply(absent, link) is None


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
    for name in [*GEN.render(version), *WIFI.render(version)]:
        text = (ROOT / "templates/native" / version / name).read_text(encoding="utf-8")
        assert not any(line.endswith("\\") for line in text.splitlines()), name
        for token in yaml.scan(text):
            if isinstance(token, yaml.ScalarToken) and "\n" in token.value:
                assert token.style == "|", (name, token.value[:60])


def test_versions_follow_the_release():
    import re
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    lib = (ROOT / "templates/source/js/lib.js").read_text(encoding="utf-8")
    assert re.search(r"^NE\.VERSION = '([^']+)';", lib, re.M).group(1) == version  # envelope source.version
    for template in templates().values():
        assert template["vendor"]["version"] == version


def test_restart_trigger_ignores_a_sysuptime_wrap():
    item = next(i for i in all_items() if i["key"] == "ne.device.uptime")
    expression = item["triggers"][0]["expression"]
    uptime = "/ne__generic_switch/ne.device.uptime"
    assert expression == f"last({uptime})<600 and last({uptime},#2)<{2**32 // 100 - 86400}"
    bound = int(expression.rsplit("<", 1)[1])
    # The hourly poll before a wrap is above the bound, so the drop to near zero is not a restart.
    assert 2**32 // 100 - 3600 > bound


def test_javascript_is_ecmascript_5_for_duktape():
    # Zabbix runs preprocessing in Duktape (ES5.1); Node accepts ES2015+ syntax the server would reject at run time.
    import dukpy  # pinned in requirements-dev.txt; a Duktape build, unlike later QuickJS-based releases
    with pytest.raises(dukpy.JSRuntimeError):
        dukpy.evaljs("new Function('value', dukpy['script']); true", script="var f = (x) => x;")
    for version in VERSIONS:
        for item in all_items(version):
            for step in item.get("preprocessing", []):
                if step["type"] == "JAVASCRIPT":
                    dukpy.evaljs("new Function('value', dukpy['script']); true", script=step["parameters"][0])


CAPTURES = ROOT / "tests/fixtures/qualification"
VENDOR = [p for p in GEN.PROFILES if p["template"] != GEN.PROFILE and p["template"].endswith("_switch")]
# Short words that stay lowercase inside a Title Case name.
MINOR_WORDS = {"for", "and", "of", "to"}


PRODUCTS = {"ne": ("Network Explorer", "Templates/Network Explorer", "ne__generic_switch"),
            "we": ("Wi-Fi Explorer", "Templates/Wi-Fi Explorer", "we__generic_access_point")}


def test_template_names_follow_the_convention():
    import re
    assert VENDOR
    exported = [t for build in (GEN.build, WIFI.build) for t in build("7.4")["zabbix_export"]["templates"]]
    generics = {generic for _, _, generic in PRODUCTS.values()}
    for template in exported:
        technical, visible = template["template"], template["name"]
        prefix = technical.split("_", 1)[0]
        product, group, generic = PRODUCTS[prefix]
        assert re.fullmatch(r"(ne|we)_[a-z0-9]+(_[a-z0-9]+)+", technical.replace("__", "_", 1)), technical
        # Only each product's generic template has the double underscore, which sorts it (and its file) first.
        assert ("__" in technical) == (technical in generics), technical
        # Access points are Wi-Fi Explorer's, switches Network Explorer's, whichever generator builds them.
        assert template["groups"] == [{"name": group}], technical
        # The visible name is the product, then the same words in Title Case; a model code such as SG300 or an
        # acronym such as LLDP keeps its capitals.
        shown_product, _, title = visible.partition(" - ")
        assert shown_product == product, visible
        words = technical[len(prefix) + 1:].lstrip("_").split("_")
        assert title.lower().split(" ") == words, visible
        assert all(shown in (word.title(), word.upper()) or (shown == word and word in MINOR_WORDS and i)
                   for i, (shown, word) in enumerate(zip(title.split(" "), words))), visible
    for prefix, (_, _, generic) in PRODUCTS.items():
        assert sorted(t["template"] for t in exported if t["template"].startswith(prefix + "_"))[0] == generic
    assert GEN.PROFILE == "ne__generic_switch"


COMPONENT_DATASETS = {"Port Capability": "port_capability", "Hardware Health": "hardware"}


def test_port_capability_ships_disabled_in_vendor_templates_only():
    exported = templates()
    capability = {"tag": "dataset", "value": "port_capability"}
    generic = [i for i in exported[GEN.PROFILE]["items"] if capability in i["tags"]]
    assert generic and all("status" not in i for i in generic)
    assert "disabled" not in GEN.PROFILES[0]
    for profile in VENDOR:
        assert "Port Capability" in profile["disabled"], profile["template"]
        off = [{"tag": "dataset", "value": COMPONENT_DATASETS[c]} for c in profile["disabled"]]
        template = exported[profile["template"]]
        items = [i for i in template["items"] if any(tag in i["tags"] for tag in off)]
        assert items and all(i["status"] == "DISABLED" for i in items), profile["template"]
        others = [i for i in template["items"] if not any(tag in i["tags"] for tag in off)]
        assert all("status" not in i for i in others)


def test_shared_value_maps_keep_their_released_uuids():
    # Adding a component (PoE in 2.3.0) must not move the collection-status map off the UUID hosts already use.
    released = {"ne__generic_switch": "ee36b38384a941d6b53cbf5d854f4b1a",
                "ne_cisco_small_business_switch": "2760ea115d56487bb426ee150c9b81dd"}
    exported = templates()
    for name, uuid_hex in released.items():
        maps = {m["name"]: m["uuid"] for m in exported[name]["valuemaps"]}
        assert maps[GEN.STATUS_MAP] == uuid_hex, name


def test_cbs220_hardware_ships_disabled():
    # CISCO-ENVMON-MIB is listed in Cisco's data sheet, but the CBS220 capture answers it with no-such-object; the
    # producer stays, disabled, for firmware that answers it (HARDWARE.md).
    profile = next(p for p in GEN.PROFILES if p["template"] == "ne_cisco_cbs220_switch")
    assert profile["disabled"] == ["Port Capability", "Hardware Health"]
    template = templates()["ne_cisco_cbs220_switch"]
    rules = {r["key"]: r for r in template["discovery_rules"]}
    assert all(rules[k]["status"] == "DISABLED" for k in ("ne.hw.psu.discovery", "ne.hw.fan.discovery",
                                                           "ne.hw.temp.discovery"))
    assert all("status" not in rules[k] for k in ("ne.interfaces.discovery", "ne.poe.pse.discovery",
                                                   "ne.poe.port.discovery"))
    assert "ENVMON" in template["description"] and "disabled" in template["description"]


def test_schema_versions_match_lib_js():
    import re
    lib = (ROOT / "templates/source/js/lib.js").read_text(encoding="utf-8")
    declared = dict(re.findall(r"(\w+): '([0-9.]+)'", re.search(r"^NE\.SCHEMAS = \{([^}]*)\};", lib, re.M).group(1)))
    assert declared == GEN.SCHEMAS


def hardware_template(raw_key: str) -> dict:
    return owner(raw_key)


def substitute(steps: list[dict], macro: str, value: str) -> list[dict]:
    return [dict(s, parameters=[p.replace(macro, value) for p in s["parameters"]]) for s in steps]


@pytest.mark.parametrize("raw_key, label, fans, cpu5m", [
    ("ne.raw.hw.ciscosb", "cisco-sg350x-48p-2.5.9.54", 3, "4"),
    ("ne.raw.hw.dnos6", "dell-n4064-6.5.4.23", 6, "5"),
])
def test_hardware_snapshot_feeds_discovery_and_scalars(raw_key, label, fans, cpu5m):
    template = hardware_template(raw_key)
    items = {i["key"]: i for i in template["items"]}
    rules = {r["key"]: r for r in template["discovery_rules"]}
    envelope = observe(raw_key, CAPTURES / label / "capture.snmprec")
    kept = GEN.unpacked(json.loads(apply(items["ne.hardware.snapshot"]["preprocessing"], envelope)))
    # The stored snapshot keeps states and thresholds; readings are numeric items only.
    assert len(kept["data"]) == len(json.loads(envelope)["data"])
    assert all(r.get(f) is None for r in kept["data"] for f in ("util_5m_pct", "celsius", "speed"))
    assert apply(items["ne.hw.cpu.util[5m]"]["preprocessing"], envelope) == cpu5m
    found = json.loads(apply(rules["ne.hw.fan.discovery"]["preprocessing"], envelope))
    assert len(found) == fans
    prototypes = {p["key"]: p for p in rules["ne.hw.fan.discovery"]["item_prototypes"]}
    state = substitute(prototypes["ne.hw.fan.state[{#HWUID}]"]["preprocessing"], "{#HWUID}", found[0]["uid"])
    assert apply(state, envelope) == "0"  # ok
    speed = substitute(prototypes["ne.hw.fan.speed[{#HWUID}]"]["preprocessing"], "{#HWUID}", found[0]["uid"])
    assert int(apply(speed, envelope)) > 0
    gone = substitute(prototypes["ne.hw.fan.state[{#HWUID}]"]["preprocessing"], "{#HWUID}", "fan-999")
    assert apply(gone, envelope) is None  # an absent part keeps its last value
    temperatures = json.loads(apply(rules["ne.hw.temp.discovery"]["preprocessing"], envelope))
    value = {p["key"]: p for p in rules["ne.hw.temp.discovery"]["item_prototypes"]}["ne.hw.temp.value[{#HWUID}]"]
    assert float(apply(substitute(value["preprocessing"], "{#HWUID}", temperatures[0]["uid"]), envelope)) > 0


def test_hardware_discovery_skips_unreadable_sensors_and_missing_parts():
    template = hardware_template("ne.raw.hw.ciscosb.v1")
    rules = {r["key"]: r for r in template["discovery_rules"]}
    envelope = observe("ne.raw.hw.ciscosb.v1", CAPTURES / "cisco-sg300-28pp-1.4.11.5" / "capture.snmprec")
    assert json.loads(apply(rules["ne.hw.temp.discovery"]["preprocessing"], envelope)) == []
    assert [f["name"] for f in json.loads(apply(rules["ne.hw.fan.discovery"]["preprocessing"], envelope))] == ["fan1_unit1"]
    assert "ne.hw.memory.util" not in {i["key"] for i in template["items"]}  # no memory source on this family


@pytest.mark.parametrize("name, raw_key, power_key, label, delivering, power", [
    ("ne_cisco_small_business_switch", "ne.raw.poe.ifindex", "ne.raw.poe.power.ciscosb", "cisco-cbs350-24p-4x-3.6.0.3",
     3, True),
    ("ne_dell_n_series_switch", "ne.raw.poe.ifindex", "ne.raw.poe.power", "dell-n1548p-6.8.1.9", 24, False),
    ("ne__generic_switch", "ne.raw.poe", "ne.raw.poe.power", "cisco-cbs220-24p-4g-2.0.2.15", 6, False),
])
def test_poe_snapshot_feeds_discovery(name, raw_key, power_key, label, delivering, power):
    template = templates()[name]
    items = {i["key"]: i for i in template["items"]}
    rules = {r["key"]: r for r in template["discovery_rules"]}
    envelope = observe(raw_key, CAPTURES / label / "capture.snmprec", name)
    readings = observe(power_key, CAPTURES / label / "capture.snmprec", name)
    kept = GEN.unpacked(json.loads(apply(items["ne.poe.snapshot"]["preprocessing"], envelope)))
    assert kept.pop("timing") == "zabbix" and kept == stored(envelope)
    units = json.loads(apply(rules["ne.poe.pse.discovery"]["preprocessing"], envelope))
    # A stack slot without a unit is never discovered (the CBS350 agent lists four groups for two units).
    assert [u["uid"] for u in units] == (["pse-1", "pse-2"] if "cbs350" in label else ["pse-1"])
    pse = {p["key"]: p for p in rules["ne.poe.pse.discovery"]["item_prototypes"]}
    used = float(apply(substitute(pse["ne.poe.pse.util[{#PSEUID}]"]["preprocessing"], "{#PSEUID}", "pse-1"), readings))
    assert 0 < used < 100
    assert apply(substitute(pse["ne.poe.pse.state[{#PSEUID}]"]["preprocessing"], "{#PSEUID}", "pse-1"), envelope) == "0"
    ports = json.loads(apply(rules["ne.poe.port.discovery"]["preprocessing"], envelope))
    assert all(p["ifuid"].startswith("if-") for p in ports) == (raw_key != "ne.raw.poe")
    prototypes = {p["key"]: p for p in rules["ne.poe.port.discovery"]["item_prototypes"]}
    states = [apply(substitute(prototypes["ne.poe.port.state[{#POEUID}]"]["preprocessing"], "{#POEUID}", p["uid"]),
                    envelope) for p in ports]
    assert states.count("0") == delivering
    assert ("ne.poe.port.power[{#POEUID}]" in prototypes) == power
    if power:
        watts = [float(apply(substitute(prototypes["ne.poe.port.power[{#POEUID}]"]["preprocessing"], "{#POEUID}",
                                        p["uid"]), readings)) for p in ports]
        assert watts[0] == 5.5 and sum(1 for w in watts if w > 0) == delivering  # 5476 mW, to 0.1 W


def test_poe_triggers_use_the_devices_own_verdicts_and_threshold():
    template = templates()["ne_cisco_small_business_switch"]
    rules = {r["key"]: r for r in template["discovery_rules"]}
    triggers = {t["name"]: t["expression"] for rule in ("ne.poe.pse.discovery", "ne.poe.port.discovery")
                for p in rules[rule]["item_prototypes"] for t in p.get("trigger_prototypes", [])}
    assert sorted(triggers) == ["Network Explorer: PoE port {#POENAME} reports a fault",
                                "Network Explorer: PoE {#PSENAME} reports a fault",
                                "Network Explorer: PoE {#PSENAME} uses its budget above the device's usage threshold"]
    assert "ne.poe.pse.threshold[{#PSEUID}]" in triggers[
        "Network Explorer: PoE {#PSENAME} uses its budget above the device's usage threshold"]
    assert not [m for m in template["macros"] if m["macro"].startswith("{$NE.POE.") and "INTERVAL" not in m["macro"]
                and "STALE" not in m["macro"]]


def test_hardware_gate_rejects_unsafe_identity():
    template = hardware_template("ne.raw.hw.ciscosb")
    rules = {r["key"]: r for r in template["discovery_rules"]}
    envelope = json.loads(observe("ne.raw.hw.ciscosb", CAPTURES / "cisco-sg350x-48p-2.5.9.54" / "capture.snmprec"))
    envelope["data"][-1]["uid"] = "fan-1\"]"
    assert apply(rules["ne.hw.fan.discovery"]["preprocessing"], json.dumps(envelope)) is None
