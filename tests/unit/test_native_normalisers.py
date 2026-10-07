"""Native template JavaScript normalisers, run in Node exactly as composed for Zabbix.

The synthetic walks in tests/fixtures/walks are rendered the way Zabbix prints
walk[] output, normalised by templates/source/js, and validated against the
proposed canonical schema 1.1.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "collector"))
from network_explorer.normalize import interface_uid  # noqa: E402

RUNNER = ROOT / "tests/js/run_normaliser.cjs"
WALKS = ROOT / "tests/fixtures/walks"
CORE = WALKS / "sw-core-01.snmprec"
ACCESS = WALKS / "sw-access-17.snmprec"
RAW_KEYS = ["ne.raw.system", "ne.raw.if.state", "ne.raw.if.inventory", "ne.raw.if.capability",
            "ne.raw.lldp", "ne.raw.vlan", "ne.raw.stp", "ne.raw.lag"]

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")


@pytest.fixture(scope="module")
def validator():
    schema = json.loads((ROOT / "schemas/envelope-1.1.schema.json").read_text())
    return jsonschema.Draft202012Validator(schema)


def run(raw_key: str, path: Path, *extra: str) -> dict | str:
    out = subprocess.run(["node", str(RUNNER), raw_key, str(path), *extra],
                         check=True, capture_output=True, text=True).stdout
    return out if extra else json.loads(out)


def rows(envelope: dict, **match) -> list[dict]:
    return [r for r in envelope["data"] if all(r.get(k) == v for k, v in match.items())]


def uid(name: str) -> str:
    return interface_uid(name, None)


@pytest.mark.parametrize("path", [CORE, ACCESS], ids=["core", "access"])
@pytest.mark.parametrize("raw_key", RAW_KEYS)
def test_every_dataset_is_complete_and_schema_valid(validator, raw_key, path):
    envelope = run(raw_key, path)
    validator.validate(envelope)
    assert envelope["status"] == "ok", envelope["errors"]
    assert envelope["source"]["method"] == "native_snmp"


def test_fixtures_are_current():
    subprocess.run([sys.executable, str(WALKS / "make_synthetic.py"), "--check"], check=True)


def test_interface_identity_matches_the_python_collector():
    envelope = run("ne.raw.if.inventory", CORE)
    by_name = {r["name"]: r for r in envelope["data"]}
    assert by_name["Gi1/0/23"]["uid"] == uid("Gi1/0/23")
    assert by_name["Po1"]["physical"] is False and by_name["Po1"]["type"] == 161
    assert by_name["Te1/0/1"]["stack_parent_uid"] == uid("Po1")
    assert by_name["Te1/0/1"]["speed_bps"] == 10_000_000_000


def test_reduced_speed_port_has_evidence_for_amber():
    state = rows(run("ne.raw.if.state", CORE), name="Gi1/0/23")[0]
    assert (state["speed_bps"], state["duplex"]) == (100_000_000, "half")
    capability = rows(run("ne.raw.if.capability", CORE), uid=uid("Gi1/0/23"))[0]
    assert capability["oper_speed_bps"] == 100_000_000 and capability["oper_duplex"] == "half"
    assert max(capability["partner_advertised_speeds_bps"]) == 1_000_000_000
    assert max(capability["advertised_speeds_bps"]) == 1_000_000_000


def test_down_and_disabled_ports():
    envelope = run("ne.raw.if.state", CORE)
    down, disabled = rows(envelope, name="Gi1/0/5")[0], rows(envelope, name="Gi1/0/6")[0]
    assert (down["admin_status"], down["oper_status"], down["speed_bps"]) == ("up", "down", None)
    assert disabled["admin_status"] == "down"


def test_lldp_maps_local_ports_and_carries_peer_evidence():
    envelope = run("ne.raw.lldp", CORE)
    peer = rows(envelope, local_interface_uid=uid("Gi1/0/23"))[0]
    assert peer["remote_chassis_id"] == {"subtype": 4, "value": "00:11:22:33:44:17"}
    assert peer["remote_port_id"] == {"subtype": 5, "value": "Gi1/0/48"}
    assert peer["remote_management_addresses"] == ["10.101.2.17"]
    assert (peer["remote_oper_speed_bps"], peer["remote_duplex"]) == (100_000_000, "full")
    assert peer["capabilities"]["enabled"] == ["bridge"]
    lag_members = rows(envelope, remote_system_name="sw-dist-02")
    assert {m["local_interface_uid"] for m in lag_members} == {uid("Te1/0/1"), uid("Te1/0/2")}
    assert all(m["remote_lag"] == {"aggregated": True, "port_id": 1010} for m in lag_members)


def test_lldp_redaction_macro(tmp_path):
    from_walk = run("ne.raw.lldp", CORE, "--walk-only")
    walk = tmp_path / "lldp.walk"
    walk.write_text(from_walk)
    runner = ROOT / "tests/js/run_normaliser.cjs"
    script = ("const r=require(%s);const fs=require('fs');const e=r.datasetFor('ne.raw.lldp');"
              "const s=r.compose(e).replace(\"'{$NE.LLDP.REDACT_REMOTE}'\",\"'1'\");"
              "process.stdout.write(new Function('value',s)(fs.readFileSync(%s,'utf8')));") % (
        json.dumps(str(runner)), json.dumps(str(walk)))
    envelope = json.loads(subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True).stdout)
    assert envelope["status"] == "ok"
    assert all(r["remote_system_name"] is None and r["remote_chassis_id"]["value"] == "" for r in envelope["data"])
    assert all(r["local_interface_uid"] for r in envelope["data"])


def test_vlan_membership_matches_the_spec_example():
    envelope = run("ne.raw.vlan", CORE)
    assert rows(envelope, kind="vlan", vlan_id=49)[0]["name"] == "Wireless APs"
    port = {r["bridge_port"]: r for r in rows(envelope, kind="port")}
    assert (port[1]["mode"], port[1]["untagged"], port[1]["tagged"], port[1]["pvid"]) == ("access", "49", "", 49)
    assert (port[3]["mode"], port[3]["tagged"], port[3]["untagged"]) == ("trunk", "49-50", "1")
    assert (port[4]["mode"], port[4]["tagged"], port[4]["forbidden"]) == ("trunk", "50", "49")
    assert port[27]["interface_uid"] == uid("Po1") and port[27]["tagged"] == "49-50"
    assert port[5]["mode"] == "unknown" and port[5]["tagged"] == ""


def test_stp_roles_are_derived_from_bridge_evidence():
    envelope = run("ne.raw.stp", CORE)
    bridge = rows(envelope, kind="bridge")[0]
    assert (bridge["protocol"], bridge["root_port_uid"]) == ("rstp", uid("Po1"))
    assert bridge["root_bridge_id"] == "10000011223344a2"
    port = {r["bridge_port"]: r for r in rows(envelope, kind="port")}
    assert (port[27]["role"], port[27]["state"]) == ("root", "forwarding")
    assert (port[24]["role"], port[24]["state"]) == ("alternate", "blocking")
    assert (port[1]["role"], port[1]["edge"]) == ("designated", True)
    assert all(r["role_source"] == "derived" for r in port.values())


def test_lacp_bundle():
    lag = run("ne.raw.lag", CORE)["data"][0]
    assert (lag["uid"], lag["mode"], lag["partner_system_id"]) == (uid("Po1"), "lacp", "00:11:22:33:44:a2")
    assert lag["member_interface_uids"] == [uid("Te1/0/1"), uid("Te1/0/2")]
    assert all(m["selected"] and m["distributing"] for m in lag["members"])


def test_static_bundle_from_ifstack_beside_lacp(validator):
    envelope = run("ne.raw.lag", WALKS / "sw-dist-02.snmprec")
    validator.validate(envelope)
    lags = {row["name"]: row for row in envelope["data"]}
    assert (lags["Po10"]["mode"], lags["Po20"]["mode"]) == ("lacp", "static")
    assert lags["Po20"]["member_interface_uids"] == [uid("Te0/4"), uid("Te0/5")]
    assert lags["Po20"]["partner_system_id"] is None
    assert all(m["selected"] is None and m["distributing"] is None for m in lags["Po20"]["members"])


def test_static_bundle_across_stack_members(validator):
    envelope = run("ne.raw.lag", WALKS / "sw-stack-01.snmprec")
    validator.validate(envelope)
    assert envelope["status"] == "ok"
    (lag,) = envelope["data"]
    assert (lag["name"], lag["mode"], lag["if_index"]) == ("Po1", "static", 5001)
    assert lag["member_interface_uids"] == [uid("Te1/1/1"), uid("Te2/1/1")]


def test_aggregator_without_members_is_unknown_not_static(tmp_path):
    path = walk_file(tmp_path, "ne.raw.lag", WALKS / "sw-stack-01.snmprec",
                     lambda text: "\n".join(l for l in text.splitlines() if not l.startswith(".1.3.6.1.2.1.31.1.2.1.3.")))
    (lag,) = run("ne.raw.lag", path)["data"]
    assert (lag["mode"], lag["member_interface_uids"]) == ("unknown", [])


def test_idle_lacp_aggregator_lists_ifstack_members(tmp_path):
    path = walk_file(tmp_path, "ne.raw.lag", CORE,
                     lambda text: "\n".join(l for l in text.splitlines() if not l.startswith(".1.2.840.10006.300.43.1.2.1.1.13.")))
    (lag,) = run("ne.raw.lag", path)["data"]
    assert (lag["mode"], lag["member_interface_uids"]) == ("lacp", [uid("Te1/0/1"), uid("Te1/0/2")])


def test_switch_without_lag_reports_complete_empty(validator):
    envelope = run("ne.raw.lag", ACCESS)
    assert (envelope["status"], envelope["data"]) == ("ok", [])


def walk_file(tmp_path: Path, raw_key: str, source: Path, transform) -> Path:
    path = tmp_path / f"{raw_key}.walk"
    path.write_text(transform(run(raw_key, source, "--walk-only")))
    return path


@pytest.mark.parametrize("value", ["__NE_COLLECTION_FAILED__", ""])
def test_failed_collection_is_a_valid_failed_envelope(validator, tmp_path, value):
    path = tmp_path / "failed.walk"
    path.write_text(value)
    envelope = run("ne.raw.lldp", path)
    validator.validate(envelope)
    assert (envelope["status"], envelope["observed_at"], envelope["data"]) == ("failed", None, [])
    assert envelope["errors"][0]["code"] == "collection_failed"


def test_walk_without_uptime_is_failed_not_unsupported(validator, tmp_path):
    path = walk_file(tmp_path, "ne.raw.vlan", CORE,
                     lambda text: "\n".join(l for l in text.splitlines() if not l.startswith(".1.3.6.1.2.1.1.3.")))
    envelope = run("ne.raw.vlan", path)
    validator.validate(envelope)
    assert (envelope["status"], envelope["errors"][0]["code"]) == ("failed", "agent_unreachable")


@pytest.mark.parametrize("raw_key,prefix", [("ne.raw.vlan", ".1.3.6.1.2.1.17.7."), ("ne.raw.lldp", ".1.0.8802."),
                                            ("ne.raw.stp", ".1.3.6.1.2.1.17.2."), ("ne.raw.if.capability", ".1.3.6.1.2.1.26.")])
def test_absent_mib_is_unsupported(validator, tmp_path, raw_key, prefix):
    path = walk_file(tmp_path, raw_key, CORE,
                     lambda text: "\n".join(l for l in text.splitlines() if not l.startswith(prefix)))
    envelope = run(raw_key, path)
    validator.validate(envelope)
    assert (envelope["status"], envelope["capability"]["state"]) == ("unsupported", "unsupported")


def test_missing_mandatory_interface_column_keeps_the_snapshot_complete(validator, tmp_path):
    path = walk_file(tmp_path, "ne.raw.if.state", CORE,
                     lambda text: "\n".join(l for l in text.splitlines() if not l.startswith(".1.3.6.1.2.1.2.2.1.8.7 ")))
    envelope = run("ne.raw.if.state", path)
    validator.validate(envelope)
    assert (envelope["status"], envelope["complete"], envelope["errors"]) == ("ok", True, [])
    assert {w["code"] for w in envelope["warnings"]} == {"missing_interface_fields"}
    assert [r["oper_status"] for r in envelope["data"] if r["if_index"] == 7] == [None]


def test_duplicate_interface_names_skip_those_rows_only(validator, tmp_path):
    complete = run("ne.raw.if.inventory", CORE)
    path = walk_file(tmp_path, "ne.raw.if.inventory", CORE,
                     lambda text: text.replace('.1.3.6.1.2.1.31.1.1.1.1.2 = STRING: "Gi1/0/2"',
                                               '.1.3.6.1.2.1.31.1.1.1.1.2 = STRING: "Gi1/0/1"'))
    envelope = run("ne.raw.if.inventory", path)
    validator.validate(envelope)
    assert (envelope["status"], envelope["complete"], envelope["errors"]) == ("ok", True, [])
    assert {w["code"] for w in envelope["warnings"]} == {"identity_ambiguous"}
    assert not rows(envelope, name="Gi1/0/1") and len(envelope["data"]) == len(complete["data"]) - 2


def test_interface_count_mismatch_is_a_warning(validator, tmp_path):
    path = walk_file(tmp_path, "ne.raw.if.inventory", CORE,
                     lambda text: "\n".join(l if not l.startswith(".1.3.6.1.2.1.2.1.0 ")
                                            else ".1.3.6.1.2.1.2.1.0 = INTEGER: 999" for l in text.splitlines()))
    envelope = run("ne.raw.if.inventory", path)
    validator.validate(envelope)
    assert envelope["status"] == "ok"
    assert {w["code"] for w in envelope["warnings"]} == {"interface_count_mismatch"}


def test_no_identifiable_interface_is_partial(validator, tmp_path):
    path = walk_file(tmp_path, "ne.raw.if.inventory", ACCESS,
                     lambda text: "\n".join(l for l in text.splitlines()
                                            if not l.startswith((".1.3.6.1.2.1.31.1.1.1.1.", ".1.3.6.1.2.1.2.2.1.2."))))
    envelope = run("ne.raw.if.inventory", path)
    validator.validate(envelope)
    assert (envelope["status"], envelope["data"]) == ("partial", [])
    assert {e["code"] for e in envelope["errors"]} == {"identity_ambiguous"}


def test_wrapped_hex_and_display_hint_values_decode(tmp_path):
    bitmap = " \n".join(" ".join(["FF"] * 16) for _ in range(5))   # 80 octets: ports 1-640
    walk = tmp_path / "vlan.walk"
    walk.write_text("\n".join([
        ".1.3.6.1.2.1.1.3.0 = Timeticks: 100",
        '.1.3.6.1.2.1.31.1.1.1.1.640 = STRING: "Gi9/0/48"',
        ".1.3.6.1.2.1.17.1.4.1.2.640 = INTEGER: 640",
        '.1.3.6.1.2.1.17.7.1.4.3.1.1.10 = STRING: "Big \\"quoted\\" VLAN"',
        ".1.3.6.1.2.1.17.7.1.4.3.1.2.10 = Hex-STRING: " + bitmap,
        ".1.3.6.1.2.1.17.7.1.4.3.1.4.10 = \"\"",
    ]))
    envelope = run("ne.raw.vlan", walk)
    assert rows(envelope, kind="vlan")[0]["name"] == 'Big "quoted" VLAN'
    port = rows(envelope, kind="port", bridge_port=640)[0]
    assert (port["interface_uid"], port["tagged"]) == (uid("Gi9/0/48"), "10")

    lldp = tmp_path / "lldp.walk"
    lldp.write_text("\n".join([
        ".1.3.6.1.2.1.1.3.0 = Timeticks: 100",
        '.1.0.8802.1.1.2.1.4.1.1.4.0.1.1 = INTEGER: 4',
        '.1.0.8802.1.1.2.1.4.1.1.5.0.1.1 = STRING: "0:1b:2c:3d:4e:5f"',
        '.1.0.8802.1.1.2.1.4.1.1.6.0.1.1 = INTEGER: 3',
        '.1.0.8802.1.1.2.1.4.1.1.7.0.1.1 = Hex-STRING: 00 1B 2C 3D 4E 60',
        ".1.0.8802.1.1.2.1.4.2.1.3.0.1.1.2.16.32.1.13.184.0.0.0.0.0.0.0.0.0.0.0.1 = INTEGER: 2",
    ]))
    peer = run("ne.raw.lldp", lldp)["data"][0]
    assert peer["remote_chassis_id"]["value"] == "00:1b:2c:3d:4e:5f"
    assert peer["remote_port_id"] == {"subtype": 3, "value": "00:1b:2c:3d:4e:60"}
    assert peer["remote_management_addresses"] == ["2001:db8::1"]
    assert peer["local_interface_uid"] is None


def test_normaliser_bug_is_a_failed_envelope_without_device_text(validator, tmp_path):
    walk = tmp_path / "vlan.walk"
    walk.write_text(".1.3.6.1.2.1.1.3.0 = Timeticks: 100\n")
    broken = "(function () { throw new TypeError('secret-device-text'); })()"
    script = ("const r=require(%s);const fs=require('fs');"
              "const e=Object.assign({},r.datasetFor('ne.raw.vlan'),{call:%s});"
              "process.stdout.write(new Function('value',r.compose(e))(fs.readFileSync(%s,'utf8')));") % (
        json.dumps(str(RUNNER)), json.dumps(broken), json.dumps(str(walk)))
    out = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True).stdout
    envelope = json.loads(out)
    validator.validate(envelope)
    assert (envelope["status"], envelope["complete"], envelope["observed_at"], envelope["data"]) == ("failed", False, None, [])
    assert [e["code"] for e in envelope["errors"]] == ["normaliser_error"]
    assert "secret-device-text" not in out


def bits(*positions: int) -> str:
    octets = [0] * 13
    for position in positions:
        octets[position // 8] |= 0x80 >> (position % 8)
    return " ".join(f"{o:02X}" for o in octets)


def test_mau_types_above_10g(validator, tmp_path):
    mau = ".1.3.6.1.2.1.26"
    walk = tmp_path / "capability.walk"
    walk.write_text("\n".join([
        ".1.3.6.1.2.1.1.3.0 = Timeticks: 100",
        '.1.3.6.1.2.1.31.1.1.1.1.1 = STRING: "Tw1/0/1"',
        '.1.3.6.1.2.1.31.1.1.1.1.2 = STRING: "Hu1/0/2"',
        '.1.3.6.1.2.1.31.1.1.1.1.3 = STRING: "Tw1/0/3"',
        f"{mau}.2.1.1.3.1.1 = OID: {mau}.4.94",     # dot3MauType25GbaseT
        f"{mau}.2.1.1.3.2.1 = OID: {mau}.4.98",     # dot3MauType100GbaseCR4
        f"{mau}.2.1.1.13.1.1 = Hex-STRING: " + bits(54, 94),
        f"{mau}.2.1.1.13.2.1 = Hex-STRING: " + bits(72, 102),
        f"{mau}.2.1.1.13.3.1 = Hex-STRING: " + bits(36, 93),
    ]))
    envelope = run("ne.raw.if.capability", walk)
    validator.validate(envelope)
    by_uid = {r["uid"]: r for r in envelope["data"]}
    copper = by_uid[uid("Tw1/0/1")]
    assert (copper["oper_speed_bps"], copper["oper_duplex"], copper["media"]) == (25_000_000_000, "full", "copper")
    assert copper["supported_speeds_bps"] == [10_000_000_000, 25_000_000_000]
    dac = by_uid[uid("Hu1/0/2")]
    assert (dac["oper_speed_bps"], dac["media"]) == (100_000_000_000, None)
    assert dac["supported_speeds_bps"] == [40_000_000_000, 100_000_000_000]
    # No operating MAU: 10GBASE-SR (SFP+) and 25GBASE-SR (no media value) share no one media.
    idle = by_uid[uid("Tw1/0/3")]
    assert (idle["oper_speed_bps"], idle["media"]) == (None, None)
    assert idle["supported_speeds_bps"] == [10_000_000_000, 25_000_000_000]
