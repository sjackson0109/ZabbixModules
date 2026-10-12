"""Wi-Fi Explorer producers: the Aruba Instant normalisers run in Node exactly as composed for Zabbix, the canonical
wifi-1.0 schema, and the generated native templates."""
from __future__ import annotations

import hashlib
import importlib.util
import json
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
RAW_KEYS = [entry["raw_key"] for entry in GEN.manifest()["datasets"]]

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
@pytest.mark.parametrize("raw_key", RAW_KEYS[1:])
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
                   "discovery_rules", "client"):
        assert needle not in text, needle


def test_template_keys_and_uuids_are_unique():
    export = yaml.safe_load(GEN.render("7.4"))["zabbix_export"]
    uuids, keys = [], []
    for template in export["templates"]:
        uuids.append(template["uuid"])
        for item in template["items"]:
            uuids.append(item["uuid"])
            keys.append(item["key"])
            uuids += [t["uuid"] for t in item.get("triggers", [])]
    assert len(uuids) == len(set(uuids))
    assert len(keys) == len(set(keys))
    assert all(k.startswith("we.") for k in keys), "Wi-Fi keys never collide with Network Explorer's ne.* keys"


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
