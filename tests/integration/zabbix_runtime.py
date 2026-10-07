#!/usr/bin/env python3
"""Exercise real Zabbix ingestion, LLD, dashboards and permission boundaries.

Only runs against labs created by lab/lab.py. Fixtures are invented public data.
No SNMP network scan, production host enrolment, or external service is involved.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import http.cookiejar
import io
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lab"))
from lab import api_request, compose, install_modules, login, ready, settings  # noqa: E402


def assert_that(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def poll(callback, timeout: int = 60):
    deadline = time.monotonic() + timeout
    while True:
        result = callback()
        if result:
            return result
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out waiting for asynchronous Zabbix processing.")
        time.sleep(1)


def deliver(config: dict, host: str, key: str, envelope: dict) -> bool:
    """Send one trapper value; True when Zabbix accepted it (host and item are in the config cache)."""
    data = json.dumps({"request": "sender data", "data": [{
        "host": host, "key": key, "value": json.dumps(envelope, separators=(",", ":")),
    }]}).encode()
    with socket.create_connection(("127.0.0.1", config["sender_port"]), 10) as stream:
        stream.sendall(b"ZBXD\x01" + struct.pack("<Q", len(data)) + data)
        prefix = receive(stream, 13)
        assert_that(prefix[:5] == b"ZBXD\x01", "Invalid sender protocol response.")
        response = json.loads(receive(stream, struct.unpack("<Q", prefix[5:])[0]))
    return response.get("response") == "success" and "processed: 1; failed: 0" in response.get("info", "")


def send(config: dict, host: str, key: str, envelope: dict) -> None:
    assert_that(deliver(config, host, key, envelope), "Zabbix sender did not accept the lab fixture.")


def receive(stream: socket.socket, length: int) -> bytes:
    result = bytearray()
    while len(result) < length:
        data = stream.recv(length - len(result))
        if not data:
            raise AssertionError("Sender disconnected before full response.")
        result.extend(data)
    return bytes(result)


def canonical(dataset: str, rows: list, status: str = "ok", complete: bool = True) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {"schema_version": "1.0", "dataset": dataset, "generation_id": secrets.token_hex(16),
            "attempted_at": now, "observed_at": now if status in ["ok", "partial"] else None,
            "status": status, "complete": complete,
            "source": {"method": "fixture", "adapter": "integration-lab", "version": "0.1.0"},
            "capability": {"state": "supported", "reason": None}, "errors": [], "data": rows}


def interface(uid: str, index: int, name: str) -> dict:
    return {"uid": uid, "if_index": index, "name": name, "description": "Synthetic lab port",
            "type": 6, "physical": True, "admin_status": "up", "oper_status": "up",
            "speed_bps": 1000000000, "expected_speed_bps": 1000000000,
            "duplex": "full", "mtu": 1500, "mac_address": "02:00:00:00:00:01"}


def browser(config: dict, username: str, password: str):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))
    payload = urllib.parse.urlencode({"name": username, "password": password,
                                      "enter": "Sign in", "autologin": "1"}).encode()
    with opener.open(urllib.request.Request(config["url"] + "/index.php", payload), timeout=15) as response:
        content = response.read().decode()
    assert_that("Login name or password is incorrect" not in content, "Frontend login failed.")
    return opener


def frontend(opener, config: dict, action: str, params: dict | None = None, post: bool = False) -> str:
    params = params or {}
    values = {"action": action, **params}
    encoded = urllib.parse.urlencode(values, doseq=True)
    if post:
        request = urllib.request.Request(config["url"] + "/zabbix.php?action=" + urllib.parse.quote(action),
                                         json.dumps(params).encode(), {"Content-Type": "application/json"})
    else:
        request = urllib.request.Request(config["url"] + "/zabbix.php?" + encoded)
    with opener.open(request, timeout=30) as response:
        content = response.read().decode()
    assert_that("Fatal error" not in content and "Parse error" not in content, f"PHP failure in {action}.")
    return content


def run(version: str, require_frontend: bool = True) -> dict:
    config = settings(version)
    ready(config)
    install_modules(config)
    token = login(config)

    def api(method: str, params: dict):
        return api_request(config["url"], method, params, None if method == "apiinfo.version" else token)

    result = {"family": version, "version": api("apiinfo.version", {}), "checks": []}
    proxies = poll(lambda: [p for p in api("proxy.get", {
        "output": ["proxyid", "version", "lastaccess"], "filter": {"name": "ne-lab-proxy"},
    }) if int(p["lastaccess"]) > 0])
    major, minor, patch = (int(part) for part in config["patch"].split("."))
    assert_that(proxies[0]["version"] == str(major * 10000 + minor * 100 + patch), "Proxy/server version mismatch.")
    result["checks"].append("active-proxy-connected-matching-version")
    rules = {k: {"createMissing": True, "updateExisting": True}
             for k in ["template_groups", "templates", "items", "discoveryRules", "graphs", "triggers", "templateDashboards", "valueMaps"]}
    assert_that(api("configuration.import", {"format": "yaml", "source": (ROOT / "templates" / "lab" / version / "network_explorer_lab.yaml").read_text(),
                                             "rules": rules}) is True, "LAB template import failed.")
    result["checks"].append("lab-template-import")
    template = api("template.get", {"output": ["templateid"], "filter": {"host": "Network Explorer LAB replay"}})[0]

    def group(name: str) -> str:
        current = api("hostgroup.get", {"output": ["groupid"], "filter": {"name": name}})
        return current[0]["groupid"] if current else api("hostgroup.create", {"name": name})["groupids"][0]

    visible_group, private_group = group("Network Explorer LAB visible"), group("Network Explorer LAB private")
    hostids = {}
    host_addresses = {}
    for name, domain, groupid, address in [
        ("ne-lab-a", "lab-main", visible_group, "192.0.2.1"),
        ("ne-lab-b", "lab-main", visible_group, "192.0.2.2"),
        ("ne-lab-hidden", "lab-main", private_group, "192.0.2.3"),
        ("ne-lab-other-domain", "lab-isolated", visible_group, "192.0.2.2"),
    ]:
        found = api("host.get", {"output": ["hostid"], "filter": {"host": name}})
        if found:
            hostid = found[0]["hostid"]
        else:
            hostid = api("host.create", {"host": name, "name": name,
                "groups": [{"groupid": groupid}], "templates": [{"templateid": template["templateid"]}],
                "tags": [{"tag": "ne.domain", "value": domain}],
                "interfaces": [{"type": 1, "main": 1, "useip": 1, "ip": address, "dns": "", "port": "10050"}],
            })["hostids"][0]
        hostids[name] = hostid
        host_addresses[name] = address
    compose(config, "exec", "-T", "server", "zabbix_server", "-R", "config_cache_reload", capture=True)
    saved = {}
    for number, name in enumerate(hostids, start=1):
        chassis = f"02:00:00:00:00:{number:02x}"
        rows = [interface("port1", 1, "Ethernet1"), interface("port2", 2, "Ethernet2")]
        datasets = {
            "device": [{"hostname": name, "chassis_ids": [{"subtype": 4, "value": chassis}], "management_addresses": [host_addresses[name]]}],
            "interfaces": rows,
            "lldp": [],
            "lag": [{"uid": "lag1", "name": "PortChannel1", "member_interface_uids": ["port1", "port2"],
                      "oper_status": "up", "actor_system_id": None, "partner_system_id": None,
                      "member_states": [], "aggregate_interface_uid": None}],
        }
        if name == "ne-lab-a":
            datasets["lldp"] = [{"uid": "peer-b", "local_port_number": 1, "local_interface_uid": "port1",
                                  "local_port_id": {"subtype": 5, "value": "Ethernet1"},
                                  "remote_chassis_id": {"subtype": 4, "value": "02:00:00:00:00:02"},
                                  "remote_port_id": {"subtype": 5, "value": "Ethernet1"},
                                  "remote_system_name": "ne-lab-b", "remote_management_addresses": ["192.0.2.2"]},
                                 {"uid": "peer-hidden", "local_port_number": 2, "local_interface_uid": "port2",
                                  "local_port_id": {"subtype": 5, "value": "Ethernet2"},
                                  "remote_chassis_id": {"subtype": 4, "value": "02:00:00:00:00:03"},
                                  "remote_port_id": {"subtype": 5, "value": "Ethernet1"},
                                  "remote_system_name": "ne-lab-hidden", "remote_management_addresses": ["192.0.2.3"]}]
        if name == "ne-lab-b":
            datasets["lldp"] = [{"uid": "peer-a", "local_port_number": 1, "local_interface_uid": "port1",
                                  "local_port_id": {"subtype": 5, "value": "Ethernet1"},
                                  "remote_chassis_id": {"subtype": 4, "value": "02:00:00:00:00:01"},
                                  "remote_port_id": {"subtype": 5, "value": "Ethernet1"},
                                  "remote_system_name": "ne-lab-a", "remote_management_addresses": ["192.0.2.1"]}]
        for dataset, payload in datasets.items():
            value = canonical(dataset, payload)
            # A rejected value is not stored, so retry until the reloaded config cache knows the host and item.
            poll(lambda: deliver(config, name, f"ne.{dataset}.attempt", value))
            saved[(name, dataset)] = value
    result["checks"].append("sender-four-datasets-four-hosts")

    def items(hostid: str) -> dict:
        return {i["key_"]: i for i in api("item.get", {"hostids": [hostid], "output": ["itemid", "key_", "lastvalue", "state", "error", "value_type"]})}

    expected = saved[("ne-lab-a", "interfaces")]["generation_id"]
    poll(lambda: json.loads(items(hostids["ne-lab-a"]).get("ne.interfaces.inventory", {}).get("lastvalue") or "{}").get("generation_id") == expected)
    poll(lambda: len([k for k in items(hostids["ne-lab-a"]) if k.startswith("ne.if.")]) == 10)
    poll(lambda: len(api("graph.get", {"hostids": [hostids["ne-lab-a"]], "output": ["graphid", "name"]})) == 2)
    # The first inventory creates scalar items asynchronously; resend state to populate those new items.
    compose(config, "exec", "-T", "server", "zabbix_server", "-R", "config_cache_reload", capture=True)

    def speed_populated() -> bool:
        if items(hostids["ne-lab-a"]).get("ne.if.speed[port1]", {}).get("lastvalue") == "1000000000":
            return True
        # Resend until the reloaded cache includes the new scalar items and the value lands in them.
        send(config, "ne-lab-a", "ne.interfaces.attempt", saved[("ne-lab-a", "interfaces")])
        return False

    poll(speed_populated)
    assert_that(items(hostids["ne-lab-a"])["ne.if.oper[port1]"]["lastvalue"] == "1", "Canonical operational state not converted to scalar.")
    result["checks"].extend(["complete-inventory-lld", "per-interface-dependent-scalars", "native-speed-graph-prototype-discovery"])

    failed = canonical("interfaces", [], "failed", False)
    send(config, "ne-lab-a", "ne.interfaces.attempt", failed)
    poll(lambda: items(hostids["ne-lab-a"]).get("ne.collection.status[interfaces]", {}).get("lastvalue") == "2")
    preserved = json.loads(items(hostids["ne-lab-a"])["ne.interfaces.inventory"]["lastvalue"])
    assert_that(preserved["generation_id"] == expected, "Failed attempt overwrote last successful inventory.")
    result["checks"].append("failed-attempt-retains-successful-inventory")
    partial = canonical("interfaces", [interface("port1", 1, "Ethernet1")], "partial", False)
    send(config, "ne-lab-a", "ne.interfaces.attempt", partial)
    poll(lambda: items(hostids["ne-lab-a"]).get("ne.collection.status[interfaces]", {}).get("lastvalue") == "1")
    assert_that(json.loads(items(hostids["ne-lab-a"])["ne.interfaces.inventory"]["lastvalue"])["generation_id"] == expected,
                "Partial attempt replaced the complete inventory.")
    assert_that(len([key for key in items(hostids["ne-lab-a"]) if key.startswith("ne.if.")]) == 10,
                "Partial attempt removed previously discovered interfaces.")
    result["checks"].append("partial-attempt-preserves-discovery-and-success")
    send(config, "ne-lab-a", "ne.interfaces.attempt", saved[("ne-lab-a", "interfaces")])

    dashboards = api("templatedashboard.get", {"templateids": [template["templateid"]], "output": ["dashboardid", "name"], "selectPages": "extend"})
    assert_that(any(d["name"] == "Network Explorer LAB" for d in dashboards), "Inherited template dashboard missing.")
    result["checks"].append("template-dashboard-pages-and-widgets")

    usergroups = api("usergroup.get", {"output": ["usrgrpid"], "filter": {"name": "Network Explorer LAB viewers"}})
    if usergroups:
        usergroup = usergroups[0]["usrgrpid"]
    else:
        usergroup = api("usergroup.create", {"name": "Network Explorer LAB viewers", "hostgroup_rights": [{"id": visible_group, "permission": 2}]})["usrgrpids"][0]
    viewer_file = config["state"] / "viewer.json"
    if not viewer_file.exists():
        descriptor = os.open(viewer_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump({"password": secrets.token_urlsafe(30)}, stream)
    password = json.loads(viewer_file.read_text())["password"]
    viewers = api("user.get", {"output": ["userid"], "filter": {"username": "ne-lab-viewer"}})
    if not viewers:
        api("user.create", {"username": "ne-lab-viewer", "passwd": password, "roleid": "1", "usrgrps": [{"usrgrpid": usergroup}]})
    viewer_token = api_request(config["url"], "user.login", {"username": "ne-lab-viewer", "password": password})
    viewable = api_request(config["url"], "host.get", {"output": ["hostid"]}, viewer_token)
    assert_that(hostids["ne-lab-hidden"] not in [row["hostid"] for row in viewable], "Viewer can access private host.")
    result["checks"].append("native-user-host-permissions")

    if require_frontend:
        admin_browser = browser(config, "Admin", config["credentials"]["admin"])
        user_browser = browser(config, "ne-lab-viewer", password)
        page = frontend(admin_browser, config, "host.dashboard.view", {"hostid": hostids["ne-lab-a"]})
        assert_that("Network Explorer LAB" in page, "Host inherited dashboard does not render.")
        result["checks"].append("host-dashboard-page-renders")
        assert_that("action=networkexplorer.view" in page, "Monitoring menu has no Network Explorer entry for a permitted user.")
        result["checks"].append("menu-entry-for-permitted-user")
        for module in ["neportpanel", "netopology", "neinterfacedetail", "nedataquality", "nefindings"]:
            response = json.loads(frontend(admin_browser, config, f"widget.{module}.view", {
                "name": "Runtime test", "fields": {"override_hostid": [hostids["ne-lab-a"]]}, "templateid": template["templateid"],
                "_hostid": hostids["ne-lab-a"], "dashboardid": dashboards[0]["dashboardid"],
            }, post=True))
            assert_that("ne_payload" in response and "error" not in response, f"Widget {module} did not render: {response}")
            assert_that(len(response["ne_payload"].get("interfaces", [])) >= 2,
                        f"Widget {module} returned no host observations.")
        result["checks"].append("all-five-widget-render-actions")
        base = api("module.get", {"output": ["moduleid"], "filter": {"id": "networkexplorer"}})[0]["moduleid"]
        api("module.update", {"moduleid": base, "status": 0})
        try:
            response = json.loads(frontend(admin_browser, config, "widget.nefindings.view", {
                "name": "Runtime test", "fields": {}, "dashboardid": dashboards[0]["dashboardid"]}, post=True))
        finally:
            api("module.update", {"moduleid": base, "status": 1})
        payload = response.get("ne_payload", {})
        assert_that(payload.get("message") == "Install and enable the Network Explorer base module."
                    and not payload.get("interfaces"), f"A widget read data while its base module was disabled: {payload}")
        result["checks"].append("widgets-stop-when-base-module-disabled")
        data = json.loads(frontend(user_browser, config, "networkexplorer.data", {"hostids[]": list(hostids.values())}))
        encoded = json.dumps(data)
        assert_that("ne-lab-hidden" not in encoded and "192.0.2.3" not in encoded, "Private peer data leaked through Explorer.")
        assert_that(len(data.get("interfaces", [])) >= 4, "Explorer returned no canonical interfaces.")
        result["checks"].append("explorer-data-and-private-peer-redaction")
        denied = json.loads(frontend(user_browser, config, "networkexplorer.data", {"hostid": hostids["ne-lab-hidden"]}))
        assert_that(denied["hosts"] == [] and denied["interfaces"] == [] and denied["edges"] == [],
                    "An inaccessible seed widened into a fleet query.")
        result["checks"].append("inaccessible-seed-does-not-widen-scope")
        links = [edge for edge in data["edges"] if edge.get("target") is not None]
        assert_that(len(links) == 1 and links[0]["status"] == "bidirectional",
                    "Reciprocal LLDP observations were not deduplicated and confirmed.")
        assert_that(set([links[0]["source"], links[0]["target"]]) == set([hostids["ne-lab-a"], hostids["ne-lab-b"]]),
                    "Repeated address in another domain changed the peer match.")
        assert_that(bool(data.get("lags")), "LAG data was not exposed.")
        result["checks"].append("bidirectional-link-lag-and-domain-resolution")
        cidr = "192.0.2.0/31"
        scoped = json.loads(frontend(user_browser, config, "networkexplorer.data", {
            "hostid": hostids["ne-lab-a"], "management_cidr": cidr,
        }))
        scoped_hosts = {row["hostid"]: row for row in scoped["hosts"]}
        assert_that(hostids["ne-lab-b"] in scoped_hosts, "Subnet annotation removed the authorised physical neighbour.")
        assert_that(scoped_hosts[hostids["ne-lab-a"]]["addressing"]["status"] == "within",
                    "Seed management address was not matched to the CIDR.")
        assert_that(scoped_hosts[hostids["ne-lab-b"]]["addressing"]["status"] == "outside"
                    and scoped_hosts[hostids["ne-lab-b"]]["out_of_subnet"] is True,
                    "Outside-subnet neighbour was not annotated.")
        addressed = json.loads(frontend(user_browser, config, "networkexplorer.export", {
            "hostid": hostids["ne-lab-a"], "management_cidr": cidr, "format": "json", "report": "addressing",
        }))
        assert_that(any(row["hostid"] == hostids["ne-lab-b"] and row["assessment"]["status"] == "outside"
                        for row in addressed["rows"]), "Addressing report lost the outside-subnet peer.")
        result["checks"].append("subnet-annotation-retains-physical-peer-in-api-and-report")
        explorer = frontend(user_browser, config, "networkexplorer.view", {"hostid": hostids["ne-lab-a"]})
        assert_that("Network Explorer" in explorer, "Explorer page did not render.")
        result["checks"].append("explorer-html-page")
        for report in ["inventory", "peers", "addressing", "degradation", "quality", "findings"]:
            exported = frontend(user_browser, config, "networkexplorer.export", {"format": "json", "report": report, "hostids[]": list(hostids.values())})
            assert_that("ne-lab-hidden" not in exported and "192.0.2.3" not in exported, f"Private peer leaked through {report} report.")
            json.loads(exported)
            csv_export = frontend(user_browser, config, "networkexplorer.export", {"format": "csv", "report": report, "hostids[]": list(hostids.values())})
            assert_that("ne-lab-hidden" not in csv_export and "192.0.2.3" not in csv_export,
                        f"Private peer leaked through {report} CSV report.")
            csv_rows = list(csv.reader(io.StringIO(csv_export)))
            assert_that(bool(csv_rows) and all(len(row) == len(csv_rows[0]) for row in csv_rows),
                        f"Inconsistent CSV report columns for {report}.")
        result["checks"].append("six-permission-filtered-json-reports")
        result["checks"].append("six-permission-filtered-csv-reports")
        # The producer must not refresh observations by calling fresh data failed.
        malformed = canonical("interfaces", [interface("injected", 3, "InjectedPort")])
        malformed["status"] = "failed"
        send(config, "ne-lab-a", "ne.interfaces.attempt", malformed)
        poll(lambda: items(hostids["ne-lab-a"]).get("ne.collection.status[interfaces]", {}).get("lastvalue") == "2")
        poisoned = json.loads(frontend(user_browser, config, "networkexplorer.data", {"hostid": hostids["ne-lab-a"]}))
        assert_that(all(row["uid"] != "injected" for row in poisoned["interfaces"]),
                    "Malformed failure data reached the interface view.")
        poisoned_quality = next(q for q in poisoned["quality"] if q["hostid"] == hostids["ne-lab-a"] and q["dataset"] == "interfaces")
        assert_that(poisoned_quality["status"] == "failed" and bool(poisoned_quality["errors"]),
                    "Malformed failure envelope did not produce a structural health failure.")
        result["checks"].append("malformed-outcome-does-not-refresh-or-publish-data")
        # Rejected preprocessing is native item state, even though old text remains in history.
        send(config, "ne-lab-a", "ne.interfaces.attempt", {"invalid": True})
        poll(lambda: items(hostids["ne-lab-a"]).get("ne.interfaces.attempt", {}).get("state") == "1")
        rejected = json.loads(frontend(user_browser, config, "networkexplorer.data", {"hostid": hostids["ne-lab-a"]}))
        rejected_quality = next(q for q in rejected["quality"] if q["hostid"] == hostids["ne-lab-a"] and q["dataset"] == "interfaces")
        assert_that(rejected_quality["status"] == "failed" and "item_not_supported" in rejected_quality["errors"],
                    "An unsupported producer/master item was reported healthy.")
        result["checks"].append("native-rejected-master-marks-health-failed")
        send(config, "ne-lab-a", "ne.interfaces.attempt", saved[("ne-lab-a", "interfaces")])
        poll(lambda: items(hostids["ne-lab-a"]).get("ne.interfaces.attempt", {}).get("state") == "0")
    reportfile = config["state"] / "integration-result.json"
    reportfile.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=["7.0", "7.2", "7.4"], default="7.0")
    parser.add_argument("--data-only", action="store_true", help="Skip frontend only while modules are under development.")
    args = parser.parse_args()
    run(args.version, not args.data_only)


if __name__ == "__main__":
    main()
