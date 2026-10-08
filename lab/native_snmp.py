#!/usr/bin/env python3
"""LAB ONLY: import the native SNMP templates and poll simulated switches.

Requires a running lab (lab.py start) and an SNMP simulator reachable from the Zabbix server,
for example snmpsim serving tests/fixtures/walks/*.snmprec, where the community is the file name.

  python lab/native_snmp.py import --version 7.0
  python lab/native_snmp.py hosts --version 7.0 --address 172.18.0.1 --port 1161
  python lab/native_snmp.py poll --version 7.0      # poll every raw walk now
  python lab/native_snmp.py report --version 7.0
  python lab/native_snmp.py break|repair --version 7.0  # make sw-access-17 time out, then restore it
  python lab/native_snmp.py dashboard --version 7.0  # after lab.py install-modules: link the host dashboard
  python lab/native_snmp.py viewer --version 7.0     # a user who can read every switch except sw-dist-01

Never point --address at a production device.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "Network Explorer - Profile - Generic standard MIB"
DASHBOARD = "Network Explorer - Host dashboard"
GROUP = "Network Explorer lab"
# sw-dist-01 sits in its own group so a restricted viewer can be denied it.
HIDDEN_GROUP = "Network Explorer lab restricted"
SWITCHES = ("sw-core-01", "sw-access-17", "sw-dist-02", "sw-dist-01", "sw-stack-01")
VIEWER = "ne-lab-viewer"
# Administrator-set site tags: sw-dist-01 is the one switch at another site (and outside the management subnet).
SITES = {name: "lab-west" if name == "sw-dist-01" else "lab-east" for name in SWITCHES}
# Demonstrates both interface triggers: Gi1/0/24 is monitored, Gi1/0/23 should run at 1G but runs at 100M.
CORE_MACROS = [{"macro": "{$NE.IF.MONITOR:\"Gi1/0/24\"}", "value": "1"},
               {"macro": "{$NE.IF.EXPECTED_SPEED:\"Gi1/0/23\"}", "value": "1000000000"},
               {"macro": "{$NE.IF.SPEED.DEGRADED_FOR}", "value": "1m"}]


def import_templates(config: dict, token: str) -> None:
    source = (ROOT / "templates" / "native" / config["version"] / "network_explorer_snmp.yaml").read_text()
    rules = {kind: {"createMissing": True, "updateExisting": True}
             for kind in ("template_groups", "templates", "items", "triggers", "discoveryRules", "valueMaps",
                          "templateLinkage")}
    rules["templateLinkage"] = {"createMissing": True}
    rules["templates"] = {"createMissing": True, "updateExisting": True}
    lab.api_request(config["url"], "configuration.import", {"format": "yaml", "rules": rules, "source": source}, token)
    print("Imported native SNMP templates.")


def group_id(config: dict, token: str, name: str) -> str:
    groups = lab.api_request(config["url"], "hostgroup.get", {"filter": {"name": [name]}}, token)
    return groups[0]["groupid"] if groups else lab.api_request(config["url"], "hostgroup.create", {"name": name}, token)["groupids"][0]


def create_hosts(config: dict, token: str, address: str, port: int) -> None:
    url = config["url"]
    template = lab.api_request(url, "template.get", {"filter": {"host": [PROFILE]}, "output": ["templateid"]}, token)[0]
    for name in SWITCHES:
        tags = [{"tag": "ne.domain", "value": "lab"}, {"tag": "site", "value": SITES[name]}]
        existing = lab.api_request(url, "host.get", {"filter": {"host": [name]}, "output": ["hostid"]}, token)
        if existing:
            lab.api_request(url, "host.update", {"hostid": existing[0]["hostid"], "tags": tags}, token)
            continue
        groupid = group_id(config, token, HIDDEN_GROUP if name == "sw-dist-01" else GROUP)
        lab.api_request(url, "host.create", {
            "host": name, "groups": [{"groupid": groupid}], "templates": [{"templateid": template["templateid"]}],
            "tags": tags,
            "macros": CORE_MACROS if name == "sw-core-01" else [],
            # Every simulated switch answers on the one simulator address. Connecting by "DNS name" keeps that shared
            # address out of the host's management addresses, so each switch is placed by the address it reports.
            "interfaces": [{"type": 2, "main": 1, "useip": 0, "ip": "", "dns": address, "port": str(port),
                            "details": {"version": 2, "bulk": 1, "community": name}}]}, token)
        print(f"Created lab host {name}.")


def poll(config: dict, token: str) -> None:
    """Ask the server to poll every raw walk now instead of waiting for long intervals."""
    url = config["url"]
    hosts = lab.api_request(url, "host.get", {"filter": {"host": list(SWITCHES)}, "output": ["hostid"]}, token)
    items = lab.api_request(url, "item.get", {"hostids": [h["hostid"] for h in hosts], "output": ["itemid"],
                                              "search": {"key_": "ne.raw."}, "startSearch": True}, token)
    lab.api_request(url, "task.create", [{"type": 6, "request": {"itemid": i["itemid"]}} for i in items], token)
    print(f"Requested an immediate poll of {len(items)} raw walks.")


def link_dashboard(config: dict, token: str) -> None:
    """Imports the host dashboard template (needs the frontend modules) and links it to every lab switch."""
    url = config["url"]
    source = (ROOT / "templates" / "native" / config["version"] / "network_explorer_dashboard.yaml").read_text()
    rules = {"template_groups": {"createMissing": True}, "templates": {"createMissing": True, "updateExisting": True},
             "templateDashboards": {"createMissing": True, "updateExisting": True}}
    lab.api_request(url, "configuration.import", {"format": "yaml", "rules": rules, "source": source}, token)
    template = lab.api_request(url, "template.get", {"filter": {"host": [DASHBOARD]}, "output": ["templateid"]}, token)[0]
    hosts = lab.api_request(url, "host.get", {"filter": {"host": list(SWITCHES)}, "output": ["hostid"]}, token)
    lab.api_request(url, "host.massadd", {"hosts": hosts, "templates": [template]}, token)
    print(f"Linked {DASHBOARD} to {len(hosts)} lab switches.")


def create_viewer(config: dict, token: str) -> None:
    """A Zabbix User-role account that can read every lab switch except sw-dist-01. Password kept in lab state."""
    url = config["url"]
    name = "Network Explorer lab viewers"
    groups = lab.api_request(url, "usergroup.get", {"output": ["usrgrpid"], "filter": {"name": name}}, token)
    usergroup = groups[0]["usrgrpid"] if groups else lab.api_request(url, "usergroup.create", {
        "name": name, "hostgroup_rights": [{"id": group_id(config, token, GROUP), "permission": 2}]}, token)["usrgrpids"][0]
    secret = config["state"] / "viewer.json"
    if not secret.exists():
        fd = os.open(secret, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump({"username": VIEWER, "password": secrets.token_urlsafe(30)}, stream)
    password = json.loads(secret.read_text())["password"]
    if not lab.api_request(url, "user.get", {"output": ["userid"], "filter": {"username": VIEWER}}, token):
        lab.api_request(url, "user.create", {"username": VIEWER, "passwd": password, "roleid": "1",
                                             "usrgrps": [{"usrgrpid": usergroup}]}, token)
    print(f"Viewer {VIEWER} can read {GROUP} but not {HIDDEN_GROUP}.")


def set_community(config: dict, token: str, host: str, community: str) -> None:
    """Simulates an unreachable agent: a community the simulator does not serve times out."""
    url = config["url"]
    found = lab.api_request(url, "host.get", {"filter": {"host": [host]}, "output": ["hostid"],
                                              "selectInterfaces": ["interfaceid"]}, token)[0]
    lab.api_request(url, "hostinterface.update", {"interfaceid": found["interfaces"][0]["interfaceid"],
                                                  "details": {"version": 2, "bulk": 1, "community": community}}, token)
    print(f"{host} now uses community {community!r}.")


def report(config: dict, token: str) -> None:
    url = config["url"]
    hosts = lab.api_request(url, "host.get", {"filter": {"host": list(SWITCHES)}, "output": ["host"]}, token)
    for host in hosts:
        items = lab.api_request(url, "item.get", {"hostids": host["hostid"], "output": ["itemid", "key_", "lastvalue", "state", "error"],
                                                  "search": {"key_": "ne."}}, token)
        status = {i["key_"]: i for i in items}
        print(f"== {host['host']}: {len(items)} items")
        for key in sorted(k for k in status if k.startswith("ne.collection.status[")):
            print(f"  {key:45} {status[key]['lastvalue'] or '-':>3}")
        attempts = [status[k] for k in sorted(status) if k.endswith(".attempt")]
        history = lab.api_request(url, "history.get", {"history": 4, "itemids": [i["itemid"] for i in attempts],
                                                       "sortfield": "clock", "sortorder": "DESC", "limit": 200}, token)
        for item in attempts:
            key = item["key_"]
            value = next((h["value"] for h in history if h["itemid"] == item["itemid"]), "")
            try:
                env = json.loads(value)
                summary = f"{env['status']:<11} rows={len(env['data']):<4} errors={[e['code'] for e in env['errors']]}"
            except (ValueError, KeyError):
                summary = f"no envelope ({status[key]['error'] or 'no value yet'})"
            print(f"  {key:45} {summary}")
        bad = [k for k, i in status.items() if i["state"] == "1"]
        print(f"  not supported: {len(bad)} {bad[:5]}")
        triggers = lab.api_request(url, "trigger.get", {"hostids": host["hostid"], "only_true": True,
                                                        "output": ["description"], "expandDescription": True}, token)
        print(f"  problems: {[t['description'] for t in triggers]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("operation", choices=["import", "hosts", "poll", "break", "repair", "report", "dashboard", "viewer"])
    parser.add_argument("--version", choices=["7.0", "7.2", "7.4"], default="7.0")
    parser.add_argument("--address", default="172.18.0.1")
    parser.add_argument("--port", type=int, default=1161)
    args = parser.parse_args()
    config = lab.settings(args.version)
    token = lab.login(config)
    if args.operation == "import":
        import_templates(config, token)
    elif args.operation == "hosts":
        create_hosts(config, token, args.address, args.port)
    elif args.operation == "break":
        set_community(config, token, "sw-access-17", "ne-lab-unknown")
    elif args.operation == "repair":
        set_community(config, token, "sw-access-17", "sw-access-17")
    elif args.operation == "dashboard":
        link_dashboard(config, token)
    elif args.operation == "viewer":
        create_viewer(config, token)
    elif args.operation == "poll":
        poll(config, token)
    else:
        report(config, token)


if __name__ == "__main__":
    main()
