#!/usr/bin/env python3
"""Read-only vendor/model inventory of an existing Zabbix 7.0+ SNMP estate.

The export answers "what is deployed and what does Zabbix already collect from
it" before vendor adapters are written. Capability columns are EXISTING
MONITORING EVIDENCE: they say whether an enabled Zabbix item or LLD rule already
polls a MIB, not whether the device supports that MIB.

Safety properties:
* Only allowlisted ``*.get`` API methods can be called (``READ_ONLY_METHODS``).
* The API token comes from ``ZABBIX_API_TOKEN`` or a protected ``--token-file``,
  never from argv, and is never printed.
* SNMP interface ``details`` are reduced to non-secret fields before any other
  processing; communities, security names and passphrases are dropped.
* Device-supplied text is untrusted: whitespace is collapsed and CSV cells that
  a spreadsheet would treat as formulas are prefixed with an apostrophe.

Exit codes: 0 ok, 2 usage/configuration error, 3 API/authentication error,
4 partial (some batches failed; everything that succeeded is still written).
"""

from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import os
import re
import ssl
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_API = 3
EXIT_PARTIAL = 4

TOKEN_ENV = "ZABBIX_API_TOKEN"

# Every API call goes through ZabbixClient.call(), which refuses anything else.
READ_ONLY_METHODS = frozenset({
    "hostgroup.get",
    "host.get",
    "proxy.get",
    "proxygroup.get",
    "item.get",
    "discoveryrule.get",
})

INTERFACE_TYPE_SNMP = "2"
ITEM_TYPE_SNMP = 20

HOST_OUTPUT = ["hostid", "host", "name", "status", "monitored_by", "proxyid", "proxy_groupid"]
HOST_OUTPUT_LEGACY = ["hostid", "host", "name", "status", "proxy_hostid"]
INVENTORY_FIELDS = ["type", "type_full", "hardware", "model", "os", "os_full", "vendor", "location"]
INTERFACE_FIELDS = ["interfaceid", "type", "main", "details"]
ITEM_FIELDS = ["itemid", "hostid", "key_", "snmp_oid", "lastvalue", "name", "flags", "status", "state", "error"]
LLD_FIELDS = ["itemid", "hostid", "key_", "snmp_oid", "name", "type", "master_itemid", "status", "state", "error"]
ITEM_TYPE_DEPENDENT = "18"

# Only these SNMP interface detail keys survive; everything else (community,
# securityname, authpassphrase, privpassphrase, future additions) is dropped.
SAFE_SNMP_DETAILS = ("version", "bulk", "contextname", "securitylevel", "max_repetitions",
                     "authprotocol", "privprotocol")

SNMP_VERSIONS = {"1": "v1", "2": "v2c", "3": "v3"}
SECURITY_LEVELS = {"0": "noAuthNoPriv", "1": "authNoPriv", "2": "authPriv"}
AUTH_PROTOCOLS = {"0": "MD5", "1": "SHA1", "2": "SHA224", "3": "SHA256", "4": "SHA384", "5": "SHA512"}
PRIV_PROTOCOLS = {"0": "DES", "1": "AES128", "2": "AES192", "3": "AES256", "4": "AES192C", "5": "AES256C"}

SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"
SYSTEM_SYMBOLS = {
    "SNMPv2-MIB::sysDescr.0": SYS_DESCR,
    "SNMPv2-MIB::sysObjectID.0": SYS_OBJECT_ID,
    "SNMPv2-MIB::sysName.0": SYS_NAME,
}

CAPABILITIES = ("interfaces", "lldp", "vlan", "stp", "lag", "poe", "optics")

# Numeric OID prefix -> capability. Order does not matter; matching is exact
# on whole sub-identifiers.
CAPABILITY_OIDS = {
    "1.3.6.1.2.1.2.2": "interfaces",          # IF-MIB ifTable
    "1.3.6.1.2.1.31.1.1": "interfaces",       # IF-MIB ifXTable
    "1.0.8802.1.1.2": "lldp",                 # LLDP-MIB
    "1.3.111.2.802.1.1.13": "lldp",           # LLDP-V2-MIB
    "1.3.6.1.2.1.17.7": "vlan",               # Q-BRIDGE-MIB
    "1.3.6.1.4.1.9.9.46": "vlan",             # CISCO-VTP-MIB
    "1.3.6.1.2.1.17.2": "stp",                # BRIDGE-MIB dot1dStp
    "1.3.111.2.802.1.1.6": "stp",             # IEEE8021-MSTP-MIB
    "1.3.6.1.4.1.9.9.82": "stp",              # CISCO-STP-EXTENSIONS-MIB
    "1.2.840.10006.300.43": "lag",            # IEEE8023-LAG-MIB
    "1.3.6.1.2.1.105": "poe",                 # POWER-ETHERNET-MIB
    "1.3.6.1.4.1.9.9.402": "poe",             # CISCO-POWER-ETHERNET-EXT-MIB
    "1.3.6.1.2.1.99": "optics",               # ENTITY-SENSOR-MIB
    "1.3.6.1.4.1.9.9.91": "optics",           # CISCO-ENTITY-SENSOR-MIB
}

# Symbolic OIDs (MIB::object) used by older templates.
CAPABILITY_SYMBOLS = (
    ("IF-MIB::", "interfaces"),
    ("LLDP-MIB::", "lldp"),
    ("LLDP-V2-MIB::", "lldp"),
    ("Q-BRIDGE-MIB::", "vlan"),
    ("CISCO-VTP-MIB::", "vlan"),
    ("BRIDGE-MIB::dot1dStp", "stp"),
    ("IEEE8021-MSTP-MIB::", "stp"),
    ("CISCO-STP-EXTENSIONS-MIB::", "stp"),
    ("IEEE8023-LAG-MIB::", "lag"),
    ("POWER-ETHERNET-MIB::", "poe"),
    ("CISCO-POWER-ETHERNET-EXT-MIB::", "poe"),
    ("ENTITY-SENSOR-MIB::", "optics"),
    ("CISCO-ENTITY-SENSOR-MIB::", "optics"),
)

# Server-side narrowing for item.get (SQL LIKE '%pattern%', any field, any
# pattern). Over-matching is harmless: classification is repeated client-side.
ITEM_SEARCH_OIDS = sorted(
    set(CAPABILITY_OIDS) | {"1.3.6.1.2.1.1."} | {symbol for symbol, _ in CAPABILITY_SYMBOLS}
    | {"SNMPv2-MIB::sys"}
)
IDENTITY_KEYS = {
    "model": ("system.hw.model",),
    "firmware": ("system.hw.firmware", "system.sw.os"),
}
ITEM_SEARCH_KEYS = ["system.hw.model", "system.hw.firmware", "system.sw.os"]

# IANA private enterprise numbers. Vendor only: models are never inferred.
ENTERPRISES = {
    9: "Cisco",
    11: "HP",
    674: "Dell",
    890: "Zyxel",
    2636: "Juniper",
    4413: "Broadcom (FASTPATH-based OEM)",
    4526: "Netgear",
    6027: "Dell (Force10/S-series)",
    25506: "H3C / HPE Comware",
    41112: "Ubiquiti",
    47196: "Aruba / HPE",
}

STATUS_MONITORED = "monitored"
STATUS_ERROR = "monitored-error"
STATUS_ABSENT = "absent"
STATUS_UNKNOWN = "unknown"   # evidence could not be fetched for this host

NOTES_LIMIT = 200
ERROR_LIMIT = 120
FIELD_LIMIT = 200

HOST_COLUMNS = [
    "host", "visible_name", "hostid", "host_status", "host_groups", "site", "proxy",
    "vendor", "model", "firmware", "vendor_source", "model_source", "firmware_source",
    "device_type", "enterprise_number", "sys_object_id", "sys_name",
    "snmp_version", "snmp_bulk", "snmp_max_repetitions", "snmp_security_level",
    "snmp_auth_protocol", "snmp_priv_protocol", "snmp_context", "snmp_interface_count",
    "templates", "interface_discovery",
    *[f"existing_monitoring_{name}" for name in CAPABILITIES],
    "existing_monitoring_errors", "notes",
]

SUMMARY_COLUMNS = [
    "vendor", "model", "firmware", "host_count", "enterprise_numbers", "device_types",
    "templates", "snmp_versions", "proxies", "sites", "interface_discovery",
    *[f"existing_monitoring_{name}" for name in CAPABILITIES],
]


class UsageError(Exception):
    """Configuration problem; exit code 2."""


class ApiError(Exception):
    """API or transport failure; exit code 3 when it affects essential calls."""


class AuthError(ApiError):
    """Authentication or authorisation failure."""


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------

def clean_text(value: Any, limit: int = FIELD_LIMIT) -> str:
    """Collapse whitespace and control characters in untrusted text."""
    if value is None:
        return ""
    text = re.sub(r"[\s\x00-\x1f\x7f]+", " ", str(value)).strip()
    if len(text) > limit:
        text = text[: limit - 3].rstrip() + "..."
    return text


FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: Any) -> str:
    """Neutralise spreadsheet formula injection in a single cell."""
    text = "" if value is None else str(value)
    if text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return text


def join_sorted(values: Iterable[str]) -> str:
    return "; ".join(sorted({value for value in values if value}, key=lambda v: (v.casefold(), v)))


def counted(counter: Counter) -> str:
    """'name (n)' entries, most frequent first, ties by name."""
    entries = sorted(counter.items(), key=lambda pair: (-pair[1], pair[0].casefold(), pair[0]))
    return "; ".join(f"{name or '(blank)'} ({count})" for name, count in entries)


# --------------------------------------------------------------------------
# OID handling
# --------------------------------------------------------------------------

NUMERIC_OID = re.compile(r"(?<![\w.])\.?((?:\d+\.)+\d+)(?![\w])")
SYMBOLIC_OID = re.compile(r"[A-Za-z][A-Za-z0-9-]*::[A-Za-z][A-Za-z0-9]*(?:\.[0-9.]+)?")
ENTERPRISE_OID = re.compile(r"^1\.3\.6\.1\.4\.1\.(\d+)(?:\.|$)")


def normalize_oid(text: str) -> str:
    text = text.strip().lstrip(".")
    for prefix, numeric in (("SNMPv2-SMI::enterprises.", "1.3.6.1.4.1."),
                            ("SNMPv2-SMI::mib-2.", "1.3.6.1.2.1."),
                            ("iso.", "1.")):
        if text.startswith(prefix):
            return numeric + text[len(prefix):]
    return text


def oid_references(snmp_oid: str | None) -> tuple[list[str], list[str]]:
    """Numeric and symbolic OIDs mentioned in an item's snmp_oid.

    Handles plain OIDs and Zabbix 6.4+/7.x forms such as ``get[oid]``,
    ``walk[oid1,oid2]`` and ``discovery[{#MACRO},oid,...]``.
    """
    if not snmp_oid:
        return [], []
    text = normalize_oid(snmp_oid)
    text = text.replace("SNMPv2-SMI::enterprises.", "1.3.6.1.4.1.").replace("SNMPv2-SMI::mib-2.", "1.3.6.1.2.1.")
    numeric = [match.group(1) for match in NUMERIC_OID.finditer(text)]
    symbolic = [match.group(0) for match in SYMBOLIC_OID.finditer(text)]
    return numeric, symbolic


def oid_under(oid: str, prefix: str) -> bool:
    return oid == prefix or oid.startswith(prefix + ".")


def capabilities_of(snmp_oid: str | None) -> set[str]:
    numeric, symbolic = oid_references(snmp_oid)
    found = set()
    for oid in numeric:
        for prefix, capability in CAPABILITY_OIDS.items():
            if oid_under(oid, prefix):
                found.add(capability)
    for symbol in symbolic:
        for prefix, capability in CAPABILITY_SYMBOLS:
            if symbol.startswith(prefix):
                found.add(capability)
    return found


def single_system_oid(snmp_oid: str | None) -> str | None:
    """The system scalar an item reads, only when it reads exactly one."""
    numeric, symbolic = oid_references(snmp_oid)
    references = numeric + [SYSTEM_SYMBOLS.get(symbol, symbol) for symbol in symbolic]
    if len(references) == 1 and references[0] in (SYS_DESCR, SYS_OBJECT_ID, SYS_NAME):
        return references[0]
    return None


def enterprise_number(sys_object_id: str) -> int | None:
    match = ENTERPRISE_OID.match(normalize_oid(sys_object_id or ""))
    return int(match.group(1)) if match else None


# --------------------------------------------------------------------------
# Transports and client
# --------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would re-send the bearer token to another URL; refuse it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ApiError(f"HTTP {code} redirect refused; pass the final API URL with --url.")


class HttpTransport:
    def __init__(self, url: str, token: str, timeout: float, ca_file: str | None,
                 max_response_bytes: int):
        self.url = url
        self._token = token
        self.timeout = timeout
        self.max_response_bytes = max_response_bytes
        context = ssl.create_default_context(cafile=ca_file) if url.startswith("https://") else None
        handlers: list[Any] = [_NoRedirect()]
        if context is not None:
            handlers.append(urllib.request.HTTPSHandler(context=context))
        self._opener = urllib.request.build_opener(*handlers)
        self._next_id = 0

    def request(self, method: str, params: dict) -> Any:
        self._next_id += 1
        body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params,
                           "id": self._next_id}).encode("utf-8")
        request = urllib.request.Request(self.url, data=body, method="POST", headers={
            "Content-Type": "application/json-rpc",
            "Authorization": f"Bearer {self._token}",
            "User-Agent": "network-explorer-inventory/1",
        })
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(self.max_response_bytes + 1)
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise AuthError(f"HTTP {error.code} from Zabbix API.") from None
            raise ApiError(f"HTTP {error.code} from Zabbix API.") from None
        except (urllib.error.URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise ApiError(f"Cannot reach Zabbix API: {reason}") from None
        if len(raw) > self.max_response_bytes:
            raise ApiError(f"{method} response exceeds {self.max_response_bytes} bytes; lower --batch-size.")
        try:
            payload = json.loads(raw)
        except ValueError:
            raise ApiError(f"{method} returned a non-JSON response.") from None
        return unwrap_response(method, payload)


def unwrap_response(method: str, payload: Any) -> Any:
    if not isinstance(payload, dict):
        raise ApiError(f"{method} returned an unexpected response.")
    if "error" in payload:
        error = payload["error"] or {}
        message = clean_text(f"{error.get('message', '')} {error.get('data', '')}", 300)
        lowered = message.lower()
        if any(marker in lowered for marker in ("not authorised", "not authorized", "session terminated",
                                                "api token expired", "no permissions")):
            raise AuthError(f"{method}: {message}")
        raise ApiError(f"{method}: {message} (code {error.get('code')})")
    if "result" not in payload:
        raise ApiError(f"{method} returned no result.")
    return payload["result"]


class FixtureTransport:
    """Offline transport: canned results keyed by API method.

    Format: ``{"host.get": [...], "item.get": [...], "proxy.get": {"error": {...}},
    "__fail_hostids__": {"item.get": ["10105"]}}``. A method whose value is an
    ``{"error": ...}`` object always fails; ``__fail_hostids__`` fails only the
    batches containing one of the listed host IDs. Lists are filtered by the
    ``hostids`` parameter when records carry a ``hostid``.
    """

    def __init__(self, data: dict):
        if not isinstance(data, dict):
            raise UsageError("Fixture must be a JSON object keyed by API method.")
        self.data = data
        self.failures = {method: {str(hostid) for hostid in hostids}
                         for method, hostids in data.get("__fail_hostids__", {}).items()}
        self.calls: list[tuple[str, dict]] = []

    @classmethod
    def from_file(cls, path: str) -> "FixtureTransport":
        try:
            with open(path, encoding="utf-8") as stream:
                return cls(json.load(stream))
        except (OSError, ValueError) as error:
            raise UsageError(f"Cannot read fixture: {error}") from None

    def request(self, method: str, params: dict) -> Any:
        self.calls.append((method, params))
        hostids = {str(hostid) for hostid in params.get("hostids", [])}
        if hostids & self.failures.get(method, set()):
            raise ApiError(f"{method}: fixture failure for this batch")
        if method not in self.data:
            return []
        value = self.data[method]
        if isinstance(value, dict) and "error" in value:
            return unwrap_response(method, value)
        if hostids and isinstance(value, list):
            value = [record for record in value
                     if not isinstance(record, dict) or "hostid" not in record
                     or str(record["hostid"]) in hostids]
        return value


class ZabbixClient:
    def __init__(self, transport):
        self.transport = transport

    def call(self, method: str, params: dict) -> Any:
        if method not in READ_ONLY_METHODS:
            raise PermissionError(f"{method} is not an allowlisted read-only method.")
        return self.transport.request(method, params)


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

def read_token_file(path: str) -> str:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise UsageError("Token file must be a regular file.")
            if os.name == "posix" and metadata.st_mode & 0o077:
                raise UsageError("Token file must not be group/world accessible (chmod 600).")
            token = stream.read(4096).strip()
    except UsageError:
        raise
    except (OSError, UnicodeError):
        raise UsageError("Token file cannot be read.") from None
    if not token:
        raise UsageError("Token file is empty.")
    return token


def resolve_token(token_file: str | None) -> str:
    if token_file:
        return read_token_file(token_file)
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        raise UsageError(f"Set {TOKEN_ENV} or pass --token-file.")
    return token


def resolve_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise UsageError("--url must be an https:// URL of the Zabbix frontend or api_jsonrpc.php.")
    if parsed.username or parsed.password:
        raise UsageError("--url must not contain credentials.")
    if parsed.scheme == "http":
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = parsed.hostname == "localhost"
        if not loopback:
            raise UsageError("Plain http:// is only accepted for loopback; use https://.")
    path = parsed.path
    if not path.endswith(".php"):
        path = path.rstrip("/") + "/api_jsonrpc.php"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def parse_tag_filters(values: list[str]) -> list[dict]:
    tags = []
    for value in values:
        tag, sep, tag_value = value.partition("=")
        if not tag:
            raise UsageError("--tag must be NAME or NAME=VALUE.")
        # Zabbix 7.0 tag operators: 1 = equals, 4 = exists.
        tags.append({"tag": tag, "value": tag_value, "operator": 1} if sep else {"tag": tag, "operator": 4})
    return tags


# --------------------------------------------------------------------------
# Collection
# --------------------------------------------------------------------------

def safe_snmp_details(details: Any) -> dict:
    if not isinstance(details, dict):
        return {}
    return {key: str(details[key]) for key in SAFE_SNMP_DETAILS if key in details and details[key] is not None}


def snmp_interfaces(host: dict) -> list[dict]:
    """SNMP interfaces with secrets stripped, main interface first."""
    interfaces = [
        {"interfaceid": str(interface.get("interfaceid", "")),
         "main": str(interface.get("main", "0")),
         "details": safe_snmp_details(interface.get("details"))}
        for interface in host.get("interfaces") or []
        if str(interface.get("type")) == INTERFACE_TYPE_SNMP
    ]
    return sorted(interfaces, key=lambda i: (i["main"] != "1", i["interfaceid"]))


def batches(values: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start:start + size]


class Collector:
    def __init__(self, client: ZabbixClient, batch_size: int = 100):
        self.client = client
        self.batch_size = batch_size
        self.warnings: list[str] = []

    def group_ids(self, names: list[str]) -> list[str]:
        groups = self.client.call("hostgroup.get", {"output": ["groupid", "name"], "filter": {"name": names}})
        found = {group["name"]: group["groupid"] for group in groups}
        missing = sorted(set(names) - set(found))
        if missing:
            raise UsageError("Host group(s) not found: " + ", ".join(missing))
        return sorted(found.values())

    def hosts(self, group_names: list[str], tags: list[dict]) -> list[dict]:
        params: dict[str, Any] = {
            "output": HOST_OUTPUT,
            "selectInterfaces": INTERFACE_FIELDS,
            "selectParentTemplates": ["templateid", "name"],
            "selectInventory": INVENTORY_FIELDS,
            "selectTags": ["tag", "value"],
            "selectHostGroups": ["name"],
            "sortfield": "hostid",
        }
        if group_names:
            params["groupids"] = self.group_ids(group_names)
        if tags:
            params["tags"] = tags
            params["evaltype"] = 0
        try:
            raw = self.client.call("host.get", params)
        except AuthError:
            raise
        except ApiError as error:
            # Pre-7.0 servers reject 7.0 output fields; retry once with legacy names.
            if "output" not in str(error).lower() and "selecthostgroups" not in str(error).lower():
                raise
            params["output"] = HOST_OUTPUT_LEGACY
            params.pop("selectHostGroups", None)
            params["selectGroups"] = ["name"]
            raw = self.client.call("host.get", params)
        hosts = []
        for host in raw:
            interfaces = snmp_interfaces(host)
            if interfaces:
                # Raw interface objects (with secrets) are not retained.
                record = {key: value for key, value in host.items() if key != "interfaces"}
                record["snmp_interfaces"] = interfaces
                hosts.append(record)
        return hosts

    def proxy_names(self, hosts: list[dict]) -> tuple[dict, dict]:
        proxy_ids = sorted({proxy_id(host) for host in hosts} - {""})
        group_ids = sorted({str(host.get("proxy_groupid") or "0") for host in hosts} - {"0", ""})
        proxies: dict[str, str] = {}
        groups: dict[str, str] = {}
        if proxy_ids:
            try:
                for proxy in self.client.call("proxy.get", {"output": ["proxyid", "name"], "proxyids": proxy_ids}):
                    proxies[str(proxy["proxyid"])] = clean_text(proxy.get("name") or proxy.get("host"))
            except AuthError:
                raise
            except ApiError as error:
                self.warnings.append(f"proxy names unresolved: {error}")
        if group_ids:
            try:
                for group in self.client.call("proxygroup.get", {"output": ["proxy_groupid", "name"],
                                                                 "proxy_groupids": group_ids}):
                    groups[str(group["proxy_groupid"])] = clean_text(group.get("name"))
            except AuthError:
                raise
            except ApiError as error:
                self.warnings.append(f"proxy group names unresolved: {error}")
        return proxies, groups

    def _batched(self, method: str, hostids: list[str], params: dict) -> tuple[dict, set]:
        by_host: dict[str, list[dict]] = {hostid: [] for hostid in hostids}
        failed: set[str] = set()
        for batch in batches(hostids, self.batch_size):
            try:
                records = self.client.call(method, {**params, "hostids": batch})
            except AuthError:
                raise
            except ApiError as error:
                failed.update(batch)
                self.warnings.append(f"{method} failed for {len(batch)} host(s) "
                                     f"(hostids {batch[0]}..{batch[-1]}): {error}")
                continue
            for record in records:
                hostid = str(record.get("hostid", ""))
                if hostid in by_host:
                    by_host[hostid].append(record)
        return by_host, failed

    def items(self, hostids: list[str]) -> tuple[dict, set]:
        return self._batched("item.get", hostids, {
            "output": ITEM_FIELDS,
            "filter": {"type": ITEM_TYPE_SNMP},
            "search": {"snmp_oid": ITEM_SEARCH_OIDS, "key_": ITEM_SEARCH_KEYS},
            "searchByAny": True,
            "sortfield": "itemid",
        })

    def lld_rules(self, hostids: list[str]) -> tuple[dict, set]:
        # No type filter: Zabbix 7 templates commonly use dependent LLD rules
        # fed by an SNMP walk[] master item (resolved in resolve_dependent_rules).
        return self._batched("discoveryrule.get", hostids, {
            "output": LLD_FIELDS,
            "sortfield": "itemid",
        })


def proxy_id(host: dict) -> str:
    value = str(host.get("proxyid") or host.get("proxy_hostid") or "0")
    return "" if value == "0" else value


# --------------------------------------------------------------------------
# Derivation
# --------------------------------------------------------------------------

def sort_evidence(records: list[dict]) -> list[dict]:
    """Enabled+supported first, then by numeric item ID, for stable choices."""
    def key(record):
        itemid = str(record.get("itemid", ""))
        return (str(record.get("status", "0")) != "0", str(record.get("state", "0")) != "0",
                int(itemid) if itemid.isdigit() else 0, itemid)
    return sorted(records, key=key)


def resolve_dependent_rules(rules: list[dict], items: list[dict]) -> list[dict]:
    """Give dependent LLD rules the snmp_oid of their SNMP master item."""
    masters = {str(item.get("itemid")): item for item in items}
    resolved = []
    for rule in rules:
        if str(rule.get("type", "")) == ITEM_TYPE_DEPENDENT and not rule.get("snmp_oid"):
            master = masters.get(str(rule.get("master_itemid", "")))
            if master is not None:
                rule = {**rule, "snmp_oid": master.get("snmp_oid", "")}
        resolved.append(rule)
    return resolved


def classify_capabilities(items: list[dict], rules: list[dict]) -> tuple[dict, dict]:
    """Per capability: monitored / monitored-error / absent, plus first error text.

    Disabled items and rules are ignored: they are not current monitoring.
    """
    statuses = {}
    errors = {}
    evidence = sort_evidence(items + rules)
    for capability in CAPABILITIES:
        enabled = [record for record in evidence
                   if str(record.get("status", "0")) == "0" and capability in capabilities_of(record.get("snmp_oid"))]
        if any(str(record.get("state", "0")) == "0" for record in enabled):
            statuses[capability] = STATUS_MONITORED
        elif enabled:
            statuses[capability] = STATUS_ERROR
            message = next((record.get("error") for record in enabled if record.get("error")), "")
            errors[capability] = clean_text(message, ERROR_LIMIT) or "not supported"
        else:
            statuses[capability] = STATUS_ABSENT
    return statuses, errors


def interface_discovery(rules: list[dict]) -> str:
    names = [clean_text(rule.get("name") or rule.get("key_")) for rule in rules
             if str(rule.get("status", "0")) == "0" and "interfaces" in capabilities_of(rule.get("snmp_oid"))]
    return join_sorted(names) or "none"


def system_values(items: list[dict]) -> dict:
    values: dict[str, str] = {}
    for item in sort_evidence(items):
        oid = single_system_oid(item.get("snmp_oid"))
        value = str(item.get("lastvalue") or "").strip()
        if oid and value and oid not in values:
            values[oid] = value
    return values


def key_value(items: list[dict], keys: tuple[str, ...]) -> tuple[str, str]:
    for key in keys:
        for item in sort_evidence(items):
            item_key = str(item.get("key_", ""))
            value = clean_text(item.get("lastvalue"), 120)
            if value and str(item.get("status", "0")) == "0" and (item_key == key or item_key.startswith(key + "[")):
                return value, f"item:{key}"
    return "", ""


def inventory_of(host: dict) -> dict:
    inventory = host.get("inventory")
    # Zabbix returns [] when host inventory is disabled.
    return inventory if isinstance(inventory, dict) else {}


def identity(host: dict, items: list[dict]) -> dict:
    inventory = inventory_of(host)
    system = system_values(items)
    sys_object_id = normalize_oid(system.get(SYS_OBJECT_ID, "")) if system.get(SYS_OBJECT_ID) else ""
    enterprise = enterprise_number(sys_object_id)

    vendor, vendor_source = clean_text(inventory.get("vendor")), "inventory.vendor"
    if not vendor and enterprise in ENTERPRISES:
        vendor, vendor_source = ENTERPRISES[enterprise], "sysObjectID"
    if not vendor:
        vendor_source = ""

    model, model_source = "", ""
    for field in ("model", "hardware"):
        if clean_text(inventory.get(field)):
            model, model_source = clean_text(inventory.get(field)), f"inventory.{field}"
            break
    if not model:
        model, model_source = key_value(items, IDENTITY_KEYS["model"])

    firmware, firmware_source = "", ""
    for field in ("os", "os_full"):
        if clean_text(inventory.get(field)):
            firmware, firmware_source = clean_text(inventory.get(field), 120), f"inventory.{field}"
            break
    if not firmware:
        firmware, firmware_source = key_value(items, IDENTITY_KEYS["firmware"])

    return {
        "vendor": vendor, "vendor_source": vendor_source,
        "model": model, "model_source": model_source,
        "firmware": firmware, "firmware_source": firmware_source,
        "device_type": clean_text(inventory.get("type_full") or inventory.get("type")),
        "enterprise_number": "" if enterprise is None else str(enterprise),
        "sys_object_id": clean_text(sys_object_id),
        "sys_name": clean_text(system.get(SYS_NAME)),
        "notes": clean_text(system.get(SYS_DESCR), NOTES_LIMIT),
    }


def site_of(host: dict, site_tag: str) -> str:
    for tag in sorted(host.get("tags") or [], key=lambda t: (str(t.get("tag")), str(t.get("value")))):
        if str(tag.get("tag", "")).casefold() == site_tag.casefold() and tag.get("value"):
            return clean_text(tag["value"])
    return clean_text(inventory_of(host).get("location"))


def proxy_label(host: dict, proxies: dict, groups: dict) -> str:
    pid = proxy_id(host)
    if pid:
        return proxies.get(pid) or f"proxyid:{pid}"
    group = str(host.get("proxy_groupid") or "0")
    if group != "0":
        return "proxy group: " + (groups.get(group) or f"id {group}")
    return "(server)"


def host_row(host: dict, items: list[dict] | None, rules: list[dict] | None,
             proxies: dict, groups: dict, site_tag: str) -> dict:
    interface = host["snmp_interfaces"][0]
    details = interface["details"]
    row = {
        "host": clean_text(host.get("host")),
        "visible_name": clean_text(host.get("name")),
        "hostid": str(host.get("hostid", "")),
        "host_status": "enabled" if str(host.get("status", "0")) == "0" else "disabled",
        "host_groups": join_sorted(clean_text(g.get("name"))
                                   for g in host.get("hostgroups") or host.get("groups") or []),
        "site": site_of(host, site_tag),
        "proxy": proxy_label(host, proxies, groups),
        "snmp_version": SNMP_VERSIONS.get(details.get("version", ""), details.get("version", "")),
        "snmp_bulk": {"1": "yes", "0": "no"}.get(details.get("bulk", ""), ""),
        "snmp_max_repetitions": details.get("max_repetitions", ""),
        "snmp_security_level": "",
        "snmp_auth_protocol": "",
        "snmp_priv_protocol": "",
        "snmp_context": clean_text(details.get("contextname")),
        "snmp_interface_count": str(len(host["snmp_interfaces"])),
        "templates": join_sorted(clean_text(t.get("name")) for t in host.get("parentTemplates") or []),
    }
    if details.get("version") == "3":
        level = details.get("securitylevel", "")
        row["snmp_security_level"] = SECURITY_LEVELS.get(level, level)
        if level in ("1", "2"):
            row["snmp_auth_protocol"] = AUTH_PROTOCOLS.get(details.get("authprotocol", ""), "")
        if level == "2":
            row["snmp_priv_protocol"] = PRIV_PROTOCOLS.get(details.get("privprotocol", ""), "")
    row.update(identity(host, items or []))
    if rules is not None:
        rules = resolve_dependent_rules(rules, items or [])

    if items is None or rules is None:
        for capability in CAPABILITIES:
            row[f"existing_monitoring_{capability}"] = STATUS_UNKNOWN
        row["existing_monitoring_errors"] = "evidence not fetched (API batch failed)"
        row["interface_discovery"] = STATUS_UNKNOWN if rules is None else interface_discovery(rules)
    else:
        statuses, errors = classify_capabilities(items, rules)
        for capability in CAPABILITIES:
            row[f"existing_monitoring_{capability}"] = statuses[capability]
        row["existing_monitoring_errors"] = "; ".join(f"{cap}: {errors[cap]}" for cap in CAPABILITIES if cap in errors)
        row["interface_discovery"] = interface_discovery(rules)
    return row


def host_sort_key(row: dict):
    hostid = row["hostid"]
    return (row["host"].casefold(), row["host"], int(hostid) if hostid.isdigit() else 0, hostid)


def summarise(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        groups.setdefault((row["vendor"], row["model"], row["firmware"]), []).append(row)

    def split(row, column):
        return [part for part in row[column].split("; ") if part] or [""]

    summary = []
    for (vendor, model, firmware), members in groups.items():
        entry = {
            "vendor": vendor, "model": model, "firmware": firmware,
            "host_count": str(len(members)),
            "enterprise_numbers": counted(Counter(r["enterprise_number"] for r in members)),
            "device_types": counted(Counter(r["device_type"] for r in members)),
            "templates": counted(Counter(t for r in members for t in split(r, "templates"))),
            "snmp_versions": counted(Counter(r["snmp_version"] for r in members)),
            "proxies": counted(Counter(r["proxy"] for r in members)),
            "sites": counted(Counter(r["site"] for r in members)),
            "interface_discovery": counted(Counter(r["interface_discovery"] for r in members)),
        }
        for capability in CAPABILITIES:
            column = f"existing_monitoring_{capability}"
            counts = Counter(r[column] for r in members)
            entry[column] = "; ".join(f"{status}={counts[status]}" for status in
                                      (STATUS_MONITORED, STATUS_ERROR, STATUS_ABSENT, STATUS_UNKNOWN)
                                      if counts[status])
        summary.append(entry)
    # Known values first (blank sorts last), then alphabetical.
    return sorted(summary, key=lambda e: tuple((not e[k], e[k].casefold(), e[k]) for k in ("vendor", "model", "firmware")))


def write_csv(path: str, columns: list[str], rows: list[dict]) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        # O_CREAT's mode only applies to new files; tighten a pre-existing one.
        os.fchmod(fd, 0o600)
    except OSError:
        os.close(fd)
        raise
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([csv_safe(row.get(column, "")) for column in columns])


def build_rows(collector: Collector, group_names: list[str], tags: list[dict], site_tag: str) -> list[dict]:
    hosts = collector.hosts(group_names, tags)
    proxies, proxy_groups = collector.proxy_names(hosts)
    hostids = sorted({str(host["hostid"]) for host in hosts}, key=lambda h: (len(h), h))
    items, failed_items = collector.items(hostids)
    rules, failed_rules = collector.lld_rules(hostids)
    rows = []
    for host in hosts:
        hostid = str(host["hostid"])
        rows.append(host_row(
            host,
            None if hostid in failed_items else items.get(hostid, []),
            None if hostid in failed_rules else rules.get(hostid, []),
            proxies, proxy_groups, site_tag,
        ))
    return sorted(rows, key=host_sort_key)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parse_args(argv: list[str] | None) -> argparse.Namespace:
    # allow_abbrev=False: e.g. '--token' must not silently match '--token-file'.
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        description="Read-only Zabbix SNMP estate inventory (vendor/model/firmware and existing monitoring evidence).",
        epilog=f"The API token is read from ${TOKEN_ENV} or --token-file; it is never accepted on the command line.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="Zabbix frontend URL or full api_jsonrpc.php URL (https://)")
    source.add_argument("--fixture", help="Offline mode: JSON file of canned API results keyed by method")
    parser.add_argument("--token-file", help="File containing the API token (mode 0600)")
    parser.add_argument("--ca-file", help="CA bundle used to verify the Zabbix server certificate")
    parser.add_argument("--group", action="append", default=[], help="Host group name filter (repeatable)")
    parser.add_argument("--tag", action="append", default=[], help="Host tag filter NAME or NAME=VALUE (repeatable)")
    parser.add_argument("--site-tag", default="site", help="Host tag used for the site column (default: site; "
                                                           "falls back to inventory location)")
    parser.add_argument("--hosts-out", required=True, help="Per-host CSV output path")
    parser.add_argument("--summary-out", required=True, help="Per vendor/model/firmware CSV output path")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout in seconds (default 30)")
    parser.add_argument("--batch-size", type=int, default=100, help="Host IDs per item/LLD request (default 100)")
    parser.add_argument("--max-response-mb", type=int, default=256, help="Reject larger API responses (default 256)")
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= 1000:
        parser.error("--batch-size must be between 1 and 1000")
    if not 0 < args.timeout <= 600:
        parser.error("--timeout must be between 0 and 600 seconds")
    if args.fixture and (args.token_file or args.ca_file):
        parser.error("--token-file/--ca-file are not used with --fixture")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    token = ""

    def redact(message: str) -> str:
        return message.replace(token, "***") if token else message

    try:
        if args.fixture:
            transport = FixtureTransport.from_file(args.fixture)
        else:
            url = resolve_url(args.url)
            token = resolve_token(args.token_file)
            if args.ca_file and not Path(args.ca_file).is_file():
                raise UsageError("--ca-file does not exist.")
            transport = HttpTransport(url, token, args.timeout, args.ca_file, args.max_response_mb * 1024 * 1024)
        collector = Collector(ZabbixClient(transport), args.batch_size)
        rows = build_rows(collector, args.group, parse_tag_filters(args.tag), args.site_tag)
        try:
            write_csv(args.hosts_out, HOST_COLUMNS, rows)
            write_csv(args.summary_out, SUMMARY_COLUMNS, summarise(rows))
        except OSError:
            # Report a fixed message rather than a traceback.
            raise UsageError("an output CSV file could not be written.") from None
    except UsageError as error:
        print(f"error: {redact(str(error))}", file=sys.stderr)
        return EXIT_USAGE
    except AuthError as error:
        print(f"authentication/authorisation error: {redact(str(error))}", file=sys.stderr)
        return EXIT_API
    except ApiError as error:
        print(f"API error: {redact(str(error))}", file=sys.stderr)
        return EXIT_API
    except ssl.SSLError as error:
        print(f"TLS error: {redact(str(error))}", file=sys.stderr)
        return EXIT_API

    for warning in collector.warnings:
        print(f"warning: {redact(warning)}", file=sys.stderr)
    print(f"{len(rows)} SNMP host(s) written to {args.hosts_out}; summary written to {args.summary_out}",
          file=sys.stderr)
    if collector.warnings:
        print("partial export: rows marked 'unknown' had evidence batches fail", file=sys.stderr)
        return EXIT_PARTIAL
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
