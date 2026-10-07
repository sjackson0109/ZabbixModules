"""Offline tests for the read-only Zabbix inventory export (canned API results only)."""

import copy
import csv
import http.server
import json
import os
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "inventory"))

import export_inventory as inv  # noqa: E402

SECRETS = ["SECRET-COMMUNITY-123", "secret-v3-user", "AUTH-SECRET-456", "PRIV-SECRET-789", "TOKEN-abc123"]


def api_fixture():
    return {
        "host.get": [
            {
                "hostid": "10101", "host": "core-sw1", "name": "Core switch 1", "status": "0",
                "monitored_by": "0", "proxyid": "0", "proxy_groupid": "0",
                "interfaces": [{"interfaceid": "1", "type": "2", "main": "1", "ip": "10.0.0.1",
                                "details": {"version": "2", "bulk": "1", "community": SECRETS[0],
                                            "max_repetitions": "10"}}],
                "parentTemplates": [{"templateid": "1", "name": "Cisco IOS by SNMP"}],
                "inventory": {"vendor": "", "model": "WS-C2960X-48FPD-L", "os": "15.2(7)E8", "type": "",
                              "type_full": "Access switch", "hardware": "", "os_full": "", "location": "Rack 1"},
                "tags": [{"tag": "site", "value": "HQ"}],
                "hostgroups": [{"name": "Switches"}, {"name": "HQ"}],
            },
            {
                "hostid": "10105", "host": "edge-sw2", "name": "edge-sw2", "status": "0",
                "monitored_by": "1", "proxyid": "20001", "proxy_groupid": "0",
                "interfaces": [{"interfaceid": "2", "type": "2", "main": "1",
                                "details": {"version": "3", "bulk": "1", "securityname": SECRETS[1],
                                            "securitylevel": "2", "authprotocol": "3",
                                            "authpassphrase": SECRETS[2], "privprotocol": "3",
                                            "privpassphrase": SECRETS[3], "contextname": ""}}],
                "parentTemplates": [{"templateid": "2", "name": "Netgear Fastpath by SNMP"}],
                "inventory": [],
                "tags": [],
                "hostgroups": [{"name": "Switches"}],
            },
            {
                "hostid": "10110", "host": "agent-only", "name": "agent-only", "status": "0",
                "proxyid": "0", "interfaces": [{"interfaceid": "3", "type": "1", "main": "1", "details": []}],
                "parentTemplates": [], "inventory": [], "tags": [], "hostgroups": [],
            },
            {
                "hostid": "10120", "host": "AA-unknown", "name": "AA-unknown", "status": "1",
                "proxy_hostid": "0",
                "interfaces": [{"interfaceid": "4", "type": "2", "main": "1",
                                "details": {"version": "2", "bulk": "0", "community": SECRETS[0]}}],
                "parentTemplates": [{"templateid": "3", "name": "Generic by SNMP"}],
                "inventory": {"vendor": "", "model": "", "os": "", "location": "Plant"},
                "tags": [], "hostgroups": [{"name": "Switches"}],
            },
        ],
        "proxy.get": [{"proxyid": "20001", "name": "proxy-dc1"}],
        "item.get": [
            {"itemid": "500", "hostid": "10101", "key_": "system.objectid[sysObjectID.0]",
             "snmp_oid": "get[1.3.6.1.2.1.1.2.0]", "lastvalue": "SNMPv2-SMI::enterprises.9.1.1208",
             "status": "0", "state": "0", "error": "", "flags": "0", "name": "sysObjectID"},
            {"itemid": "501", "hostid": "10101", "key_": "system.descr[sysDescr.0]",
             "snmp_oid": "get[1.3.6.1.2.1.1.1.0]",
             "lastvalue": "Cisco IOS Software,\n  C2960X Software   Version 15.2(7)E8",
             "status": "0", "state": "0", "error": "", "flags": "0", "name": "sysDescr"},
            {"itemid": "502", "hostid": "10101", "key_": "net.if.walk",
             "snmp_oid": "walk[1.3.6.1.2.1.2.2.1.2,1.3.6.1.2.1.31.1.1.1.1]", "lastvalue": "",
             "status": "0", "state": "0", "error": "", "flags": "0", "name": "Interfaces walk"},
            {"itemid": "503", "hostid": "10101", "key_": "lldp.walk",
             "snmp_oid": "walk[.1.0.8802.1.1.2.1.4.1.1]", "lastvalue": "",
             "status": "0", "state": "0", "error": "", "flags": "0", "name": "LLDP walk"},
            {"itemid": "504", "hostid": "10101", "key_": "poe.status[Gi1/0/1]",
             "snmp_oid": "1.3.6.1.2.1.105.1.1.1.6.1.1", "lastvalue": "",
             "status": "0", "state": "1", "flags": "4", "name": "PoE status",
             "error": "No Such Object available on this agent at this OID"},
            {"itemid": "505", "hostid": "10101", "key_": "vtp",
             "snmp_oid": "CISCO-VTP-MIB::vtpVlanState.1.{#VLAN}", "lastvalue": "",
             "status": "0", "state": "0", "error": "", "flags": "4", "name": "VTP vlan"},
            {"itemid": "600", "hostid": "10105", "key_": "system.objectid",
             "snmp_oid": "1.3.6.1.2.1.1.2.0", "lastvalue": ".1.3.6.1.4.1.4526.100.4.10",
             "status": "0", "state": "0", "error": "", "flags": "0", "name": "sysObjectID"},
            {"itemid": "601", "hostid": "10105", "key_": "system.descr",
             "snmp_oid": "SNMPv2-MIB::sysDescr.0", "lastvalue": "=cmd|' /C calc'!A0",
             "status": "0", "state": "0", "error": "", "flags": "0", "name": "sysDescr"},
            {"itemid": "602", "hostid": "10105", "key_": "lldp.rem",
             "snmp_oid": "1.0.8802.1.1.2.1.4.1.1.9", "lastvalue": "",
             "status": "1", "state": "0", "error": "", "flags": "0", "name": "LLDP disabled"},
            {"itemid": "603", "hostid": "10105", "key_": "system.hw.firmware",
             "snmp_oid": "1.3.6.1.4.1.4526.10.1.1.1.13.0", "lastvalue": "12.0.9.3",
             "status": "0", "state": "0", "error": "", "flags": "0", "name": "Firmware"},
            {"itemid": "700", "hostid": "10120", "key_": "system.objectid",
             "snmp_oid": "get[1.3.6.1.2.1.1.2.0]", "lastvalue": "1.3.6.1.4.1.99999.1",
             "status": "0", "state": "0", "error": "", "flags": "0", "name": "sysObjectID"},
        ],
        "discoveryrule.get": [
            {"itemid": "900", "hostid": "10101", "key_": "net.if.discovery", "name": "Network interfaces discovery",
             "snmp_oid": "", "type": "18", "master_itemid": "502", "status": "0", "state": "0", "error": ""},
            {"itemid": "901", "hostid": "10105", "key_": "ifx.discovery", "name": "IF-MIB ifXTable discovery",
             "snmp_oid": "discovery[{#IFNAME},1.3.6.1.2.1.31.1.1.1.1]", "type": "20", "master_itemid": "0",
             "status": "0", "state": "0", "error": ""},
            {"itemid": "902", "hostid": "10105", "key_": "stp.discovery", "name": "STP ports",
             "snmp_oid": "discovery[{#PORT},1.3.6.1.2.1.17.2.15.1.3]", "type": "20", "master_itemid": "0",
             "status": "0", "state": "1", "error": "Cannot fetch\nSNMP table"},
        ],
    }


def write_fixture(tmp_path, data, name="api.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path


def run(tmp_path, data, *extra):
    fixture = write_fixture(tmp_path, data)
    hosts, summary = tmp_path / "hosts.csv", tmp_path / "summary.csv"
    code = inv.main(["--fixture", str(fixture), "--hosts-out", str(hosts), "--summary-out", str(summary), *extra])
    return code, hosts, summary


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_secrets_never_reach_outputs_or_console(tmp_path, capsys):
    code, hosts, summary = run(tmp_path, api_fixture())
    assert code == inv.EXIT_OK
    captured = capsys.readouterr()
    blob = hosts.read_text() + summary.read_text() + captured.out + captured.err
    for secret in SECRETS:
        assert secret not in blob
    assert "10.0.0.1" not in blob   # interface addresses are not exported


def test_snmp_details_keep_only_allowlisted_fields():
    details = {"version": "3", "bulk": "1", "community": "x", "securityname": "u", "authpassphrase": "a",
               "privpassphrase": "p", "authprotocol": "1", "privprotocol": "1", "securitylevel": "2",
               "contextname": "ctx", "max_repetitions": "10", "some_future_secret": "s"}
    assert inv.safe_snmp_details(details) == {
        "version": "3", "bulk": "1", "contextname": "ctx", "securitylevel": "2", "max_repetitions": "10",
        "authprotocol": "1", "privprotocol": "1"}
    assert inv.safe_snmp_details([]) == {}
    host = {"interfaces": [{"interfaceid": "1", "type": "2", "main": "1", "details": details}]}
    assert "community" not in json.dumps(inv.snmp_interfaces(host))


def test_only_snmp_hosts_and_identity(tmp_path):
    _, hosts, _ = run(tmp_path, api_fixture())
    rows = {row["host"]: row for row in read_rows(hosts)}
    assert set(rows) == {"core-sw1", "edge-sw2", "AA-unknown"}

    core = rows["core-sw1"]
    assert (core["vendor"], core["vendor_source"]) == ("Cisco", "sysObjectID")
    assert (core["model"], core["model_source"]) == ("WS-C2960X-48FPD-L", "inventory.model")
    assert (core["firmware"], core["firmware_source"]) == ("15.2(7)E8", "inventory.os")
    assert core["sys_object_id"] == "1.3.6.1.4.1.9.1.1208"
    assert core["enterprise_number"] == "9"
    assert core["notes"] == "Cisco IOS Software, C2960X Software Version 15.2(7)E8"
    assert core["site"] == "HQ" and core["proxy"] == "(server)"
    assert core["snmp_version"] == "v2c" and core["snmp_bulk"] == "yes" and core["snmp_max_repetitions"] == "10"
    assert core["host_groups"] == "HQ; Switches"

    edge = rows["edge-sw2"]
    assert edge["vendor"] == "Netgear" and edge["model"] == ""   # model is never guessed
    assert (edge["firmware"], edge["firmware_source"]) == ("12.0.9.3", "item:system.hw.firmware")
    assert edge["proxy"] == "proxy-dc1"
    assert (edge["snmp_version"], edge["snmp_security_level"]) == ("v3", "authPriv")
    assert (edge["snmp_auth_protocol"], edge["snmp_priv_protocol"]) == ("SHA256", "AES256")

    unknown = rows["AA-unknown"]
    assert unknown["vendor"] == "" and unknown["vendor_source"] == ""
    assert unknown["enterprise_number"] == "99999"
    assert unknown["host_status"] == "disabled" and unknown["site"] == "Plant"


@pytest.mark.parametrize("value,expected", [
    ("1.3.6.1.4.1.9.1.1208", 9),
    (".1.3.6.1.4.1.2636.1.1.1.2.29", 2636),
    ("SNMPv2-SMI::enterprises.41112.1.6", 41112),
    ("iso.3.6.1.4.1.25506.11.1.1", 25506),
    ("1.3.6.1.4.1.6027", 6027),
    ("1.3.6.1.2.1.1", None),
    ("", None),
    ("garbage", None),
])
def test_enterprise_number(value, expected):
    assert inv.enterprise_number(value) == expected


def test_enterprise_map_covers_requested_vendors():
    for number in (9, 674, 6027, 890, 4526, 41112, 11, 47196, 2636, 25506, 4413):
        assert inv.ENTERPRISES[number]


def test_capability_classification(tmp_path):
    _, hosts, _ = run(tmp_path, api_fixture())
    rows = {row["host"]: row for row in read_rows(hosts)}
    core = rows["core-sw1"]
    assert core["existing_monitoring_interfaces"] == "monitored"
    assert core["existing_monitoring_lldp"] == "monitored"
    assert core["existing_monitoring_vlan"] == "monitored"            # symbolic CISCO-VTP-MIB
    assert core["existing_monitoring_poe"] == "monitored-error"
    assert core["existing_monitoring_stp"] == "absent"
    assert core["existing_monitoring_errors"] == "poe: No Such Object available on this agent at this OID"
    assert core["interface_discovery"] == "Network interfaces discovery"   # dependent rule via walk master

    edge = rows["edge-sw2"]
    assert edge["existing_monitoring_lldp"] == "absent"               # only a disabled item
    assert edge["existing_monitoring_stp"] == "monitored-error"
    assert edge["existing_monitoring_errors"] == "stp: Cannot fetch SNMP table"
    assert edge["interface_discovery"] == "IF-MIB ifXTable discovery"

    assert rows["AA-unknown"]["interface_discovery"] == "none"


@pytest.mark.parametrize("snmp_oid,expected", [
    ("walk[1.3.6.1.2.1.2.2.1.2,1.3.6.1.2.1.31.1.1.1.1]", {"interfaces"}),
    ("discovery[{#IFNAME},1.3.6.1.2.1.31.1.1.1.1,{#P},1.0.8802.1.1.2.1.3.7.1.3]", {"interfaces", "lldp"}),
    ("get[.1.3.6.1.2.1.17.7.1.4.3.1.1.{#VID}]", {"vlan"}),
    ("1.3.111.2.802.1.1.6.1.1", {"stp"}),
    ("1.3.6.1.2.1.17.2.15.1.3.{#SNMPINDEX}", {"stp"}),
    ("1.3.6.1.2.1.17.1.4.1.2", set()),                        # bridge base port, not STP
    ("1.2.840.10006.300.43.1.2.1.1.13", {"lag"}),
    ("1.3.6.1.4.1.9.9.402.1.2.1.7.1", {"poe"}),
    ("1.3.6.1.2.1.99.1.1.1.4.{#SNMPINDEX}", {"optics"}),
    ("1.3.6.1.4.1.9.9.91.1.1.1.1.4", {"optics"}),
    ("1.3.6.1.4.1.9.9.46.1.3.1.1.2", {"vlan"}),
    ("1.3.6.1.4.1.9.9.82.1.6.1", {"stp"}),
    ("1.3.6.1.2.1.1050", set()),                              # prefix must match whole arcs
    ("IF-MIB::ifHCInOctets.{#SNMPINDEX}", {"interfaces"}),
    ("BRIDGE-MIB::dot1dStpPortState.{#SNMPINDEX}", {"stp"}),
    ("BRIDGE-MIB::dot1dBasePortIfIndex.1", set()),
    ("", set()),
    (None, set()),
])
def test_capabilities_of(snmp_oid, expected):
    assert inv.capabilities_of(snmp_oid) == expected


def test_csv_formula_injection_is_neutralised(tmp_path):
    for value in ("=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx"):
        assert inv.csv_safe(value) == "'" + value
    assert inv.csv_safe("Cisco") == "Cisco"
    _, hosts, _ = run(tmp_path, api_fixture())
    rows = {row["host"]: row for row in read_rows(hosts)}
    assert rows["edge-sw2"]["notes"] == "'=cmd|' /C calc'!A0"


def test_deterministic_output_regardless_of_api_order(tmp_path):
    data = api_fixture()
    first_dir, second_dir = tmp_path / "a", tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()
    run(first_dir, data)
    shuffled = copy.deepcopy(data)
    for key in ("host.get", "item.get", "discoveryrule.get"):
        shuffled[key].reverse()
    run(second_dir, shuffled)
    for name in ("hosts.csv", "summary.csv"):
        assert (first_dir / name).read_bytes() == (second_dir / name).read_bytes()
    assert [row["host"] for row in read_rows(first_dir / "hosts.csv")] == ["AA-unknown", "core-sw1", "edge-sw2"]


def test_summary_aggregates_by_vendor_model_firmware(tmp_path):
    data = api_fixture()
    clone = copy.deepcopy(data["host.get"][0])
    clone.update({"hostid": "10102", "host": "core-sw2", "tags": [{"tag": "site", "value": "DR"}]})
    data["host.get"].append(clone)
    data["item.get"].append({**data["item.get"][0], "itemid": "510", "hostid": "10102"})
    _, _, summary = run(tmp_path, data)
    rows = read_rows(summary)
    assert [(r["vendor"], r["model"], r["firmware"]) for r in rows] == [
        ("Cisco", "WS-C2960X-48FPD-L", "15.2(7)E8"), ("Netgear", "", "12.0.9.3"), ("", "", "")]
    cisco = rows[0]
    assert cisco["host_count"] == "2"
    assert cisco["templates"] == "Cisco IOS by SNMP (2)"
    assert cisco["sites"] == "DR (1); HQ (1)"
    assert cisco["snmp_versions"] == "v2c (2)"
    assert cisco["existing_monitoring_lldp"] == "monitored=1; absent=1"
    assert cisco["existing_monitoring_poe"] == "monitored-error=1; absent=1"


def test_partial_failure_exit_code_and_unknown_evidence(tmp_path, capsys):
    data = api_fixture()
    data["__fail_hostids__"] = {"item.get": ["10105"]}
    code, hosts, summary = run(tmp_path, data, "--batch-size", "1")
    assert code == inv.EXIT_PARTIAL
    assert "item.get failed for 1 host(s)" in capsys.readouterr().err
    rows = {row["host"]: row for row in read_rows(hosts)}
    assert rows["edge-sw2"]["existing_monitoring_lldp"] == "unknown"
    assert rows["edge-sw2"]["vendor"] == ""                        # no items, no sysObjectID
    assert rows["core-sw1"]["existing_monitoring_lldp"] == "monitored"
    assert summary.exists()


def test_proxy_resolution_failure_is_partial(tmp_path):
    data = api_fixture()
    data["proxy.get"] = {"error": {"code": -32500, "message": "Application error.", "data": "boom"}}
    code, hosts, _ = run(tmp_path, data)
    assert code == inv.EXIT_PARTIAL
    rows = {row["host"]: row for row in read_rows(hosts)}
    assert rows["edge-sw2"]["proxy"] == "proxyid:20001"


def test_auth_error_exit_code(tmp_path, capsys):
    data = api_fixture()
    data["host.get"] = {"error": {"code": -32602, "message": "Invalid params.", "data": "Not authorized."}}
    code, hosts, _ = run(tmp_path, data)
    assert code == inv.EXIT_API
    assert not hosts.exists()
    assert "authentication" in capsys.readouterr().err


def test_unknown_group_is_usage_error(tmp_path):
    data = api_fixture()
    data["hostgroup.get"] = [{"groupid": "5", "name": "Switches"}]
    code, _, _ = run(tmp_path, data, "--group", "Switches", "--group", "Missing")
    assert code == inv.EXIT_USAGE


def test_group_and_tag_filters_are_passed_to_host_get(tmp_path):
    transport = inv.FixtureTransport({**api_fixture(), "hostgroup.get": [{"groupid": "5", "name": "Switches"}]})
    collector = inv.Collector(inv.ZabbixClient(transport), 50)
    inv.build_rows(collector, ["Switches"], inv.parse_tag_filters(["site=HQ", "role"]), "site")
    host_params = next(params for method, params in transport.calls if method == "host.get")
    assert host_params["groupids"] == ["5"]
    assert host_params["tags"] == [{"tag": "site", "value": "HQ", "operator": 1}, {"tag": "role", "operator": 4}]
    assert {method for method, _ in transport.calls} <= inv.READ_ONLY_METHODS


def test_items_are_batched(tmp_path):
    transport = inv.FixtureTransport(api_fixture())
    inv.build_rows(inv.Collector(inv.ZabbixClient(transport), 2), [], [], "site")
    item_calls = [params["hostids"] for method, params in transport.calls if method == "item.get"]
    assert item_calls == [["10101", "10105"], ["10120"]]


def test_client_refuses_non_read_methods():
    client = inv.ZabbixClient(inv.FixtureTransport({}))
    for method in ("host.update", "item.create", "user.login", "host.massupdate", "script.execute"):
        with pytest.raises(PermissionError):
            client.call(method, {})


def test_token_is_never_accepted_on_command_line(tmp_path):
    with pytest.raises(SystemExit):
        inv.parse_args(["--url", "https://zabbix.example", "--token", "x", "--hosts-out", "a", "--summary-out", "b"])


def test_missing_token_is_usage_error(tmp_path, monkeypatch):
    monkeypatch.delenv(inv.TOKEN_ENV, raising=False)
    code = inv.main(["--url", "https://zabbix.example", "--hosts-out", str(tmp_path / "h"),
                     "--summary-out", str(tmp_path / "s")])
    assert code == inv.EXIT_USAGE


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_token_file_must_be_private(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("TOKEN-abc123\n")
    token_file.chmod(0o644)
    with pytest.raises(inv.UsageError):
        inv.read_token_file(str(token_file))
    token_file.chmod(0o600)
    assert inv.read_token_file(str(token_file)) == "TOKEN-abc123"


@pytest.mark.parametrize("url,expected", [
    ("https://zabbix.example", "https://zabbix.example/api_jsonrpc.php"),
    ("https://zabbix.example/zabbix/", "https://zabbix.example/zabbix/api_jsonrpc.php"),
    ("https://zabbix.example/api_jsonrpc.php", "https://zabbix.example/api_jsonrpc.php"),
    ("http://127.0.0.1:8080", "http://127.0.0.1:8080/api_jsonrpc.php"),
])
def test_resolve_url(url, expected):
    assert inv.resolve_url(url) == expected


@pytest.mark.parametrize("url", ["http://zabbix.example", "ftp://x", "https://user:pw@zabbix.example", "zabbix"])
def test_resolve_url_rejects(url):
    with pytest.raises(inv.UsageError):
        inv.resolve_url(url)


def test_http_transport_sends_bearer_token_and_json_rpc():
    seen = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen["auth"] = self.headers.get("Authorization")
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            body = json.dumps({"jsonrpc": "2.0", "result": [{"proxyid": "1", "name": "p"}], "id": 1}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = inv.resolve_url(f"http://127.0.0.1:{server.server_port}")
        transport = inv.HttpTransport(url, "TOKEN-abc123", 5, None, 1024 * 1024)
        result = inv.ZabbixClient(transport).call("proxy.get", {"output": ["proxyid", "name"]})
    finally:
        server.shutdown()
    assert result == [{"proxyid": "1", "name": "p"}]
    assert seen["auth"] == "Bearer TOKEN-abc123"
    assert seen["body"]["method"] == "proxy.get" and "auth" not in seen["body"]


def test_api_error_messages_are_classified():
    with pytest.raises(inv.AuthError):
        inv.unwrap_response("host.get", {"error": {"code": -32602, "message": "Invalid params.",
                                                   "data": "Not authorised."}})
    with pytest.raises(inv.ApiError):
        inv.unwrap_response("host.get", {"error": {"code": -32500, "message": "Application error."}})
