"""Wi-Fi Explorer producers: the generic AP and Aruba Instant normalisers run in Node exactly as composed for Zabbix,
the canonical wifi-1.0 schema, and the generated native templates."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
import shutil
import subprocess
import sys

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tests/js/run_normaliser.cjs"
WALKS = ROOT / "tests/fixtures/wifi/walks"
VC = WALKS / "aruba-instant-vc.snmprec"
MEMBER = WALKS / "aruba-instant-member.snmprec"
SPEC = importlib.util.spec_from_file_location("wifi_templates", ROOT / "templates/generate_wifi.py")
GEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GEN)
RAW_KEYS = [entry["raw_key"] for entry in GEN.manifest()["datasets"] if entry["template"].startswith("Aruba")]
GENERIC_KEYS = [entry["raw_key"] for entry in GEN.manifest()["datasets"] if entry["template"] == "Generic AP"]
GENERIC = WALKS / "generic-ap.snmprec"
GENERIC_TRI = WALKS / "generic-ap-tri.snmprec"
GENERIC_NAME = "Wi-Fi Explorer - Generic AP"
ARUBA_VC = "Wi-Fi Explorer - Aruba Instant VC by SNMP"
# Cluster datasets need the virtual controller; the per-AP RF dataset answers on any Instant AP.
VC_ONLY = [e["raw_key"] for e in GEN.manifest()["datasets"]
           if e["template"] == "Aruba Instant VC" and e["dataset"] != "device"]
AP01 = WALKS / "aruba-instant-ap-01.snmprec"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")


@pytest.fixture(scope="module")
def validator():
    schema = json.loads((ROOT / "schemas/wifi-envelope-1.0.schema.json").read_text())
    return jsonschema.Draft202012Validator(schema)


def run(raw_key: str, path: Path) -> dict:
    out = subprocess.run(["node", str(RUNNER), raw_key, str(path)], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def ap_uid(mac: str) -> str:
    return "ap-" + hashlib.sha256(("ap:" + mac).encode()).hexdigest()[:24]


def mac(n: int) -> str:
    return f"00:00:5e:00:53:{n:02x}"


@needs_node
@pytest.mark.parametrize("raw_key", RAW_KEYS)
def test_virtual_controller_datasets_are_complete_and_schema_valid(validator, raw_key):
    envelope = run(raw_key, VC)
    validator.validate(envelope)
    assert envelope["status"] == "ok" and envelope["complete"], envelope["errors"]
    assert envelope["schema_version"] == "wifi-1.0"
    assert envelope["source"]["method"] == "native_snmp"


@needs_node
@pytest.mark.parametrize("raw_key", VC_ONLY)
def test_member_ap_is_unsupported_not_failed(validator, raw_key):
    envelope = run(raw_key, MEMBER)
    validator.validate(envelope)
    assert (envelope["status"], envelope["data"]) == ("unsupported", [])
    assert envelope["errors"][0]["code"] == "not_virtual_controller"


@needs_node
def test_member_device_row_says_member(validator):
    envelope = run("we.raw.aruba.system", MEMBER)
    assert envelope["status"] == "ok"
    assert envelope["data"][0]["role"] == "member" and envelope["data"][0]["controller_address"] is None


def test_fixtures_are_current():
    subprocess.run([sys.executable, str(WALKS / "make_synthetic.py"), "--check"], check=True)


@needs_node
def test_identities_are_opaque_hashes_of_the_ap_mac():
    inventory = run("we.raw.aruba.ap.inventory", VC)["data"]
    by_name = {row["name"]: row for row in inventory}
    assert len(by_name) == 6
    assert by_name["lab-ap-01"]["ap_uid"] == ap_uid(mac(1))
    assert by_name["lab-ap-01"]["mac_address"] == mac(1)
    radios = run("we.raw.aruba.radio.inventory", VC)["data"]
    expected = "radio-" + hashlib.sha256(("radio:" + mac(1) + ":0").encode()).hexdigest()[:24]
    assert expected in {r["radio_uid"] for r in radios}
    assert not [r for r in radios if r["ap_uid"] == ap_uid(mac(6))], "lab-ap-06 has no radios"


@needs_node
def test_state_matches_the_lab_scenarios():
    state = {row["ap_uid"]: row for row in run("we.raw.aruba.ap.state", VC)["data"]}
    assert state[ap_uid(mac(3))]["status"] == "down"
    assert state[ap_uid(mac(1))]["status"] == "up"
    radios = run("we.raw.aruba.radio.state", VC)["data"]
    busy = [r for r in radios if r["ap_uid"] == ap_uid(mac(2)) and r["utilisation_percent"] >= 70]
    assert len(busy) == 1 and busy[0]["band"] == "5"
    ap4 = sorted((r["status"] for r in radios if r["ap_uid"] == ap_uid(mac(4))))
    assert ap4 == ["down", "up"]
    assert all(r["noise_floor_dbm"] is None or r["noise_floor_dbm"] < 0 for r in radios), "noise is negative dBm"


@needs_node
def test_band_is_never_guessed_on_a_tri_radio_ap():
    envelope = run("we.raw.aruba.radio.state", VC)
    tri = [r for r in envelope["data"] if r["ap_uid"] == ap_uid(mac(5))]
    assert sorted((r["channel"], r["band"]) for r in tri) == [(1, None), (44, None), (197, "6")]
    assert "radio_band_ambiguous" in [w["code"] for w in envelope["warnings"]]


@needs_node
def test_failed_collection_is_a_valid_failed_envelope(validator, tmp_path):
    path = tmp_path / "failed.walk"
    path.write_text(GEN.FAILED)
    envelope = run("we.raw.aruba.ap.state", path)
    validator.validate(envelope)
    assert (envelope["status"], envelope["observed_at"], envelope["data"]) == ("failed", None, [])


@needs_node
def test_other_vendor_is_unsupported(validator, tmp_path):
    path = tmp_path / "other.snmprec"
    path.write_text("1.3.6.1.2.1.1.3.0|67|100\n1.3.6.1.2.1.1.5.0|4|switch\n")
    envelope = run("we.raw.aruba.ap.inventory", path)
    validator.validate(envelope)
    assert envelope["status"] == "unsupported"
    assert envelope["errors"][0]["code"] == "not_aruba_instant"


@pytest.mark.parametrize("version", ["7.0", "7.2", "7.4"])
def test_generated_templates_are_current(version):
    path = ROOT / "templates/native" / version / "wifi_explorer_snmp.yaml"
    assert path.read_text() == GEN.render(version)


def test_templates_carry_no_credentials_token_or_per_client_items():
    text = GEN.render("7.4").lower()
    for needle in ("community", "{$snmp_community", "api.token", "authpassphrase", "privpassphrase", "password",
                   "discovery_rules", "item_prototypes"):
        assert needle not in text, needle
    export = yaml.safe_load(GEN.render("7.4"))["zabbix_export"]
    keys = [i["key"] for t in export["templates"] for i in t["items"]]
    assert [k for k in keys if "client" in k] == ["we.raw.aruba.client", "we.normalised[client]", "we.client.attempt",
        "we.client.snapshot", "we.collection.status[client]", "we.collection.success[client]", "we.capacity.clients",
        "we.capacity.clients.ap_max"], "clients are one bounded snapshot per owner, plus two cluster totals"
    macros = {m["macro"]: m for t in export["templates"] for m in t["macros"]}
    assert macros["{$WE.CLIENT.KEY}"]["value"] == "" and macros["{$WE.CLIENT.KEY}"]["type"] == "SECRET_TEXT"
    assert macros["{$WE.CLIENT.IDENTIFIERS}"]["value"] == "partial", "masked unless an operator chooses otherwise"


def test_macros_appear_only_where_zabbix_should_expand_them():
    """Zabbix expands user macros anywhere in a JavaScript step, comments and strings included. Only the client
    normaliser's call may name the client macros, so the secret key can never reach a stored value."""
    export = yaml.safe_load(GEN.render("7.4"))["zabbix_export"]
    for template in export["templates"]:
        for item in template["items"]:
            for step in item.get("preprocessing", []):
                if step["type"] != "JAVASCRIPT":
                    continue
                script = step["parameters"][0]
                found = sorted(set(re.findall(r"\{\$[A-Z0-9_.]+\}", script)))
                expected = ["{$WE.CLIENT.IDENTIFIERS}", "{$WE.CLIENT.KEY}"] if item["key"] == "we.normalised[client]" else []
                assert found == expected, (item["key"], found)


@needs_node
def test_complete_attempts_are_stored_as_receipts(validator):
    """The attempt item keeps every outcome, but a complete success without its rows: they are in the snapshot."""
    export = yaml.safe_load(GEN.render("7.4"))["zabbix_export"]
    items = {i["key"]: i for t in export["templates"] for i in t["items"]}
    attempt, normalised = items["we.client.attempt"], items["we.normalised[client]"]
    assert attempt["master_item"]["key"] == "we.normalised[client]" and normalised["history"] == "0"
    assert items["we.client.snapshot"]["master_item"]["key"] == "we.normalised[client]"
    assert attempt["history"] == "{$WE.CLIENT.HISTORY}", "retention is a macro"
    step = attempt["preprocessing"][0]["parameters"][0]
    receipt = lambda envelope: json.loads(subprocess.run(
        ["node", "-e", "const value=require('fs').readFileSync(0,'utf8');process.stdout.write((function(value){"
         + step + "})(value));"], input=json.dumps(envelope), check=True, capture_output=True, text=True).stdout)
    complete = run("we.raw.aruba.client", VC)
    stored = receipt(complete)
    validator.validate(stored)
    assert stored["data"] == [] and stored["data_omitted"] is True and stored["data_rows"] == len(complete["data"]) > 0
    assert stored["observed_at"] == complete["observed_at"] and stored["warnings"] == complete["warnings"]
    failed = dict(complete, status="failed", complete=False, observed_at=None, data=[])
    assert receipt(failed) == failed, "a failed attempt is stored as it is"


@needs_node
def test_capacity_items_are_cluster_totals_with_trends():
    """Numeric capacity values come only from complete observations and are never a zero standing in for unknown."""
    export = yaml.safe_load(GEN.render("7.4"))["zabbix_export"]
    items = {i["key"]: i for t in export["templates"] if t["template"] == ARUBA_VC for i in t["items"]}
    capacity = {k: i for k, i in items.items() if k.startswith("we.capacity.")}
    assert all(i["trends"] == "{$WE.CAPACITY.TRENDS}" and i["value_type"] in ("UNSIGNED", "FLOAT") for i in capacity.values())

    def value(key, envelope):
        steps = capacity[key]["preprocessing"]
        out = subprocess.run(["node", "-e", "const value=require('fs').readFileSync(0,'utf8');"
                              "process.stdout.write(String((function(value){" + steps[0]["parameters"][0] + "})(value)));"],
                             input=json.dumps(envelope), check=True, capture_output=True, text=True).stdout
        return None if out == GEN._common.DISCARD else float(out)

    aps, radios, clients = (run(raw, VC) for raw in ("we.raw.aruba.ap.state", "we.raw.aruba.radio.state",
                                                     "we.raw.aruba.client"))
    assert value("we.capacity.aps.up", aps) == sum(r["status"] == "up" for r in aps["data"])
    assert value("we.capacity.aps.down", aps) == sum(r["status"] == "down" for r in aps["data"]) == 1
    assert value("we.capacity.clients", clients) == len(clients["data"])
    five = [r["utilisation_percent"] for r in radios["data"] if r["status"] == "up" and r["band"] == "5"
            and r["utilisation_percent"] is not None]
    assert value("we.capacity.utilisation.max[5]", radios) == max(five)
    assert abs(value("we.capacity.utilisation.avg[5]", radios) - sum(five) / len(five)) < 1e-9
    no_six = dict(radios, data=[r for r in radios["data"] if r["band"] != "6"])
    assert value("we.capacity.utilisation.max[6]", no_six) is None, "no 6 GHz radio: no value, not 0"
    assert value("we.capacity.radios.up[6]", no_six) == 0, "a complete observation does count zero radios"
    assert value("we.capacity.clients", dict(clients, status="partial", complete=False)) is None, "partial: no value"


def test_cluster_template_carries_a_host_dashboard_of_builtin_widgets():
    templates = {t["template"]: t for t in GEN.build("7.4")["zabbix_export"]["templates"]}
    owners = {GENERIC_NAME, ARUBA_VC}
    assert all("dashboards" not in t for name, t in templates.items() if name not in owners)
    for name in owners:
        template = templates[name]
        keys = {i["key"] for i in template["items"]}
        widgets = [w for page in template["dashboards"][0]["pages"] for w in page["widgets"]]
        assert {w["type"] for w in widgets} <= {"item", "svggraph"}  # no widget module needed
        for w in widgets:
            for field in w["fields"]:
                if field["type"] == "ITEM":
                    assert field["value"]["host"] == name and field["value"]["key"] in keys


def test_template_keys_and_uuids_are_unique():
    """UUIDs are unique across the export; keys within each template, since every vendor template feeds the same
    canonical keys (they are never linked to the same host)."""
    export = yaml.safe_load(GEN.render("7.4"))["zabbix_export"]
    uuids = []
    for template in export["templates"]:
        uuids.append(template["uuid"])
        keys = []
        for item in template["items"]:
            uuids.append(item["uuid"])
            keys.append(item["key"])
            uuids += [t["uuid"] for t in item.get("triggers", [])]
        uuids += [d["uuid"] for d in template.get("dashboards", [])]
        assert len(keys) == len(set(keys)), template["template"]
        assert all(k.startswith("we.") for k in keys), "Wi-Fi keys never collide with Network Explorer's ne.* keys"
    assert len(uuids) == len(set(uuids))


def test_aruba_instant_uuids_are_unchanged_by_the_generic_template():
    """Importing over an earlier release must update the Aruba items in place, never recreate them."""
    templates = {t["template"]: t for t in GEN.build("7.4")["zabbix_export"]["templates"]}
    for item in templates[ARUBA_VC]["items"]:
        assert item["uuid"] == GEN.uid("item:" + item["key"]), item["key"]


def test_snapshot_keys_match_the_frontend_reader():
    reader = (ROOT / "frontend/wifiexplorer/include/Services/WifiDatasetReader.php").read_text()
    for entry in GEN.manifest()["datasets"]:
        for key in entry["snapshot_keys"] + [entry["attempt_key"]]:
            assert f"'{key}'=>'{entry['dataset']}'" in reader, key


def test_javascript_is_ecmascript_5_for_duktape():
    dukpy = pytest.importorskip("dukpy")
    export = yaml.safe_load(GEN.render("7.0"))["zabbix_export"]
    for template in export["templates"]:
        for item in template["items"]:
            for step in item.get("preprocessing", []):
                if step["type"] == "JAVASCRIPT":
                    dukpy.evaljs("new Function('value', dukpy['script']); true", script=step["parameters"][0])


@needs_node
def test_ssids_keep_unknown_columns_unknown(validator, tmp_path):
    rows = {r["name"]: r for r in run("we.raw.aruba.ssid", VC)["data"]}
    assert set(rows) == {"Lab-Corp", "Lab-Event", "Lab-Guest", "Lab-Legacy"}
    assert rows["Lab-Guest"]["hidden"] is True and rows["Lab-Legacy"]["enabled"] is False
    assert all(r["vlan_id"] is None and r["security"] is None for r in rows.values()), "Instant exposes no VLAN"
    # Firmware 6.5.4.11 has no client-count or hide column: unknown, never 0 or visible.
    older = tmp_path / "old.snmprec"
    older.write_text("".join(line for line in VC.read_text().splitlines(keepends=True)
                             if not line.startswith(("1.3.6.1.4.1.14823.2.3.3.1.1.7.1.4.", "1.3.6.1.4.1.14823.2.3.3.1.1.7.1.5."))))
    envelope = run("we.raw.aruba.ssid", older)
    validator.validate(envelope)
    assert all(r["client_count"] is None and r["hidden"] is None for r in envelope["data"])


@needs_node
def test_rf_neighbours_are_deduplicated_bounded_and_never_malicious(validator, tmp_path):
    envelope = run("we.raw.aruba.rf.neighbour", AP01)
    validator.validate(envelope)
    rows = envelope["data"]
    bssids = [r["bssid"] for r in rows]
    assert len(bssids) == len(set(bssids)), "one row per BSSID"
    free = [r for r in rows if r["ssid"] == "FreeWiFi"]
    assert len(free) == 1 and free[0]["snr_db"] == 24, "the strongest detection is kept"
    assert free[0]["classification"] == "suspected_unsecure"
    assert {r["classification"] for r in rows} <= {"valid", "interfering", "unsecure", "dos", "unknown",
                                                  "known_interfering", "suspected_unsecure", "other"}
    assert "malicious" not in json.dumps(envelope)
    channel = {r["ssid"]: (r["channel"], r["band"], r["channel_width"]) for r in rows if r["ssid"]}
    assert channel["CoffeeShop"] == (36, "5", "40")
    assert [r for r in rows if r["ssid"] is None][0]["channel"] == 157, "157+ is primary channel 157"
    # A busy AP: 600 distinct BSSIDs are bounded to the strongest 500 and the snapshot says so.
    lines = [line for line in AP01.read_text().splitlines() if not line.startswith("1.3.6.1.4.1.14823.2.3.3.1.1.8.1.")]
    base = "1.3.6.1.4.1.14823.2.3.3.1.1.8.1"
    for i in range(600):
        lines += [f"{base}.2.{i}|4x|02000000{i // 256:02x}{i % 256:02x}", f"{base}.4.{i}|4|6",
                  f"{base}.5.{i}|4|2.4GHz", f"{base}.7.{i}|2|{i % 90}", f"{base}.8.{i}|4|interfering"]
    busy = tmp_path / "busy.snmprec"
    busy.write_text("\n".join(lines) + "\n")
    envelope = run("we.raw.aruba.rf.neighbour", busy)
    validator.validate(envelope)
    assert envelope["status"] == "ok" and len(envelope["data"]) == 500
    assert "neighbours_bounded" in [w["code"] for w in envelope["warnings"]]
    assert min(r["snr_db"] for r in envelope["data"]) >= max(i % 90 for i in range(600)) - 89


@needs_node
@pytest.mark.parametrize("order", [(40, None), (None, 40)])
def test_rf_detection_without_snr_never_displaces_one_with_snr(validator, tmp_path, order):
    base = "1.3.6.1.4.1.14823.2.3.3.1.1.8.1"
    lines = [line for line in AP01.read_text().splitlines() if not line.startswith(base + ".")]
    for i, snr in enumerate(order):
        lines += [f"{base}.2.{i}|4x|020000000001", f"{base}.4.{i}|4|6", f"{base}.5.{i}|4|2.4GHz",
                  f"{base}.8.{i}|4|interfering"] + ([f"{base}.7.{i}|2|{snr}"] if snr is not None else [])
    walk = tmp_path / "pair.snmprec"
    walk.write_text("\n".join(lines) + "\n")
    envelope = run("we.raw.aruba.rf.neighbour", walk)
    validator.validate(envelope)
    assert [r["snr_db"] for r in envelope["data"]] == [40], "the reading with an SNR is kept, in either order"


@needs_node
def test_ssid_profiles_sharing_a_name_merge_counts_and_visibility(validator, tmp_path):
    base = "1.3.6.1.4.1.14823.2.3.3.1.1.7.1"
    walk = tmp_path / "dup.snmprec"
    # A second Lab-Guest profile with an invalid client count, broadcasting visibly.
    walk.write_text(VC.read_text() + "".join(f"{base}.{col}.9|{kind}|{value}\n" for col, kind, value in
                                             [(2, 4, "Lab-Guest"), (3, 2, 0), (4, 2, -1), (5, 2, 0)]))
    envelope = run("we.raw.aruba.ssid", walk)
    validator.validate(envelope)
    guest = [r for r in envelope["data"] if r["name"] == "Lab-Guest"][0]
    assert guest["profiles"] == 2 and guest["client_count"] is None, "an invalid count makes the total unknown"
    assert guest["hidden"] is False, "one visible profile makes the SSID visible"


@needs_node
def test_clients_are_masked_before_storage(validator):
    envelope = run("we.raw.aruba.client", VC)
    validator.validate(envelope)
    rows = envelope["data"]
    assert len(rows) == 10
    assert all(r["identifiers"] == "partial" and r["ip_address"] is None and r["name"] is None
               and r["mac_address"].endswith(":xx:xx:xx") for r in rows), "partial is the default"
    assert "198.51.100." not in json.dumps(envelope) and "client-01" not in json.dumps(envelope)
    by_ap = {}
    for r in rows:
        by_ap.setdefault(r["ap_uid"], []).append(r)
    assert len(by_ap[ap_uid(mac(1))]) == 3 and len(by_ap[ap_uid(mac(5))]) == 3
    assert by_ap[None][0]["ap_basis"] == "ap_address_unmatched", "an address outside the roster is not guessed"


@needs_node
@pytest.mark.parametrize("policy,key,expect", [("full", "", "full"), ("pseudonymised", "s3cret", "pseudonymised"),
                                               ("pseudonymised", "", "partial"), ("bogus", "", "partial")])
def test_client_identifier_policy(validator, tmp_path, policy, key, expect):
    """The policy and key reach the normaliser as macro values, exactly as Zabbix expands them."""
    entry = next(e for e in GEN.manifest()["datasets"] if e["dataset"] == "client")
    script = GEN.compose(entry).replace("{$WE.CLIENT.IDENTIFIERS}", policy).replace("{$WE.CLIENT.KEY}", key)
    walk = subprocess.run(["node", str(RUNNER), entry["raw_key"], str(VC), "--walk-only"], check=True,
                          capture_output=True, text=True).stdout
    program = ("const crypto=require('crypto');global.sha256=t=>crypto.createHash('sha256').update(String(t),'utf8')"
               ".digest('hex');const value=require('fs').readFileSync(0,'utf8');"
               "process.stdout.write((function(value){" + script + "})(value));")
    envelope = json.loads(subprocess.run(["node", "-e", program], input=walk, check=True, capture_output=True,
                                         text=True).stdout)
    validator.validate(envelope)
    rows = envelope["data"]
    assert {r["identifiers"] for r in rows} == {expect}
    if expect == "full":
        assert rows[0]["ip_address"] and rows[0]["name"] and not rows[0]["mac_address"].endswith("xx")
    if expect == "pseudonymised":
        assert all(r["mac_address"] is None and r["ip_address"] is None and r["name"] is None for r in rows)
        plain = {r["client_uid"] for r in run("we.raw.aruba.client", VC)["data"]}
        assert plain.isdisjoint({r["client_uid"] for r in rows}), "the key changes every ID"
    if policy == "pseudonymised" and not key:
        assert "client_pseudonym_key_missing" in [w["code"] for w in envelope["warnings"]]
    codes = [w["code"] for w in envelope["warnings"]]
    assert ("client_key_missing" in codes) == (expect != "full" and not key), "unkeyed masked IDs are reported"
    assert key == "" or key not in json.dumps(envelope), "the key never reaches the stored value"


# ---------------------------------------------------------------- the generic AP template (standard MIBs only)

def test_generic_template_is_named_like_the_generic_switch_and_reads_standard_mibs_only():
    templates = {t["template"]: t for t in GEN.build("7.4")["zabbix_export"]["templates"]}
    template = templates[GENERIC_NAME]
    assert list(templates)[0] == GENERIC_NAME, "the generic template comes first, vendor templates complement it"
    walks = [i["snmp_oid"] for i in template["items"] if i["type"] == "SNMP_AGENT"]
    oids = [oid for walk in walks for oid in walk[len("walk["):-1].split(",")]
    assert oids and all(oid.startswith(("1.3.6.1.2.1.", "1.2.840.10036.")) for oid in oids), "no enterprise MIB"
    datasets = {e["dataset"] for e in GEN.manifest()["datasets"] if e["template"] == "Generic AP"}
    assert datasets == {"device", "ap_inventory", "ap_state", "radio_inventory", "radio_state", "ssid"}
    keys = {i["key"] for i in template["items"]}
    assert not [k for k in keys if "client" in k or "utilisation" in k or "rf." in k], \
        "no standard MIB carries clients, utilisation or neighbours: the template has no items for them"


@needs_node
@pytest.mark.parametrize("raw_key", GENERIC_KEYS)
def test_generic_ap_datasets_are_complete_and_schema_valid(validator, raw_key):
    envelope = run(raw_key, GENERIC)
    validator.validate(envelope)
    assert envelope["status"] == "ok" and envelope["complete"], envelope["errors"]
    assert envelope["warnings"] == []


@needs_node
def test_generic_ap_is_one_ap_identified_by_its_ethernet_mac():
    inventory = run("we.raw.generic.ap.inventory", GENERIC)["data"]
    assert inventory == [{"ap_uid": ap_uid("00:00:5e:00:53:31"), "mac_address": "00:00:5e:00:53:31",
                          "name": "lab-gap-01", "ip_address": "192.0.2.30", "serial": "LABGAP0001",
                          "model": "LAB-AP-STD", "firmware": "1.0.4"}]
    device = run("we.raw.generic.system", GENERIC)["data"][0]
    assert (device["role"], device["platform"], device["vendor"], device["controller_address"]) == \
        ("standalone", "generic_ap", None, None)
    state = run("we.raw.generic.ap.state", GENERIC)["data"]
    assert state == [{"ap_uid": ap_uid("00:00:5e:00:53:31"), "status": "up", "uptime_s": 172800,
                      "cpu_percent": 15, "memory_used_percent": 25}]


@needs_node
def test_generic_radios_are_dot11_interfaces_and_never_guess_what_the_mib_lacks():
    radios = run("we.raw.generic.radio.inventory", GENERIC)["data"]
    assert [(r["radio_index"], r["bssid"]) for r in radios] == [(2, "00:00:5e:00:53:50"), (3, "00:00:5e:00:53:60")]
    expected = "radio-" + hashlib.sha256(b"radio:00:00:5e:00:53:31:2").hexdigest()[:24]
    assert radios[0]["radio_uid"] == expected
    state = {r["radio_uid"]: r for r in run("we.raw.generic.radio.state", GENERIC)["data"]}
    first, second = state[radios[0]["radio_uid"]], state[radios[1]["radio_uid"]]
    assert (first["band"], first["channel"], first["tx_power_dbm"]) == ("2.4", 6, 17), "level 2 of 50 mW"
    assert (second["band"], second["channel"], second["tx_power_dbm"]) == ("5", 36, 23), "level 1 of 200 mW"
    for row in state.values():
        assert row["channel_width"] is row["noise_floor_dbm"] is row["utilisation_percent"] is None


@needs_node
def test_generic_band_is_never_guessed_on_a_tri_radio_ap():
    envelope = run("we.raw.generic.radio.state", GENERIC_TRI)
    assert sorted((r["channel"], r["band"]) for r in envelope["data"]) == [(6, "2.4"), (36, None), (37, None)], \
        "a 2.4 GHz-only PHY proves its band; channel 36 or 37 on a tri-radio AP may be 6 GHz"
    assert "radio_band_ambiguous" in [w["code"] for w in envelope["warnings"]]


@needs_node
def test_generic_ssids_merge_interfaces_and_keep_unknowns_unknown():
    ssids = {r["name"]: r for r in run("we.raw.generic.ssid", GENERIC)["data"]}
    assert set(ssids) == {"Lab-Corp", "Lab-Guest"}, "radio interfaces with an empty SSID broadcast none"
    assert (ssids["Lab-Corp"]["enabled"], ssids["Lab-Corp"]["profiles"]) == (True, 2)
    assert ssids["Lab-Guest"]["enabled"] is False
    for row in ssids.values():
        assert row["hidden"] is row["client_count"] is row["vlan_id"] is row["security"] is None


@needs_node
@pytest.mark.parametrize("raw_key", GENERIC_KEYS)
@pytest.mark.parametrize("walk", ["aruba-instant-vc.snmprec", "sw-wifi-access-01.snmprec"])
def test_an_agent_without_the_802_11_mib_is_not_an_ap(validator, raw_key, walk):
    envelope = run(raw_key, WALKS / walk)
    validator.validate(envelope)
    assert (envelope["status"], envelope["data"]) == ("unsupported", [])
    assert envelope["errors"][0]["code"] == "not_wifi_ap"


@needs_node
def test_generic_ap_without_an_ethernet_mac_is_incomplete_not_empty(validator, tmp_path):
    path = tmp_path / "no-eth.snmprec"
    path.write_text("".join(line + "\n" for line in GENERIC.read_text().splitlines()
                            if not line.startswith("1.3.6.1.2.1.2.2.1.3.1|")))
    envelope = run("we.raw.generic.ap.inventory", path)
    validator.validate(envelope)
    assert (envelope["status"], envelope["data"]) == ("partial", [])
    assert envelope["errors"][0]["code"] == "ap_identity_missing"


@needs_node
def test_generic_capacity_items_count_aps_and_radios_only():
    export = yaml.safe_load(GEN.render("7.4"))["zabbix_export"]
    template = next(t for t in export["templates"] if t["template"] == GENERIC_NAME)
    capacity = {i["key"]: i for i in template["items"] if i["key"].startswith("we.capacity.")}
    assert sorted(capacity) == sorted(["we.capacity.aps.up", "we.capacity.aps.down"]
                                      + [f"we.capacity.radios.up[{b}]" for b in GEN.BANDS])
    step = capacity["we.capacity.radios.up[5]"]["preprocessing"][0]["parameters"][0]
    out = subprocess.run(["node", "-e", "const value=require('fs').readFileSync(0,'utf8');"
                          "process.stdout.write(String((function(value){" + step + "})(value)));"],
                         input=json.dumps(run("we.raw.generic.radio.state", GENERIC)), check=True,
                         capture_output=True, text=True).stdout
    assert out == "1"
