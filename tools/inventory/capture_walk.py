#!/usr/bin/env python3
"""Capture a bounded, read-only SNMP walk of one device into an snmpsim .snmprec file.

Wraps net-snmp ``snmpbulkwalk`` (GETBULK only; nothing is ever SET). Each
subtree is walked by a separate process started from an argument list, never a
shell. Credentials reach net-snmp through a private, temporary ``snmp.conf``
(``SNMPCONFPATH``), so they never appear in argv, logs, the manifest or error
text.

Output, written to ``--out-dir``:
* ``<label>.snmprec``        ``OID|TAG|VALUE`` records sorted by OID (snmpsim format)
* ``<label>.manifest.json``  per-subtree outcome, counts, timestamps, net-snmp
                             version and sanitisation settings; no credentials
                             and no target address.

Exit codes: 0 every subtree ok or absent, 2 usage/configuration error, 3 no
subtree could be read (unreachable/auth failure), 4 partial capture.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_UNREACHABLE = 3
EXIT_PARTIAL = 4

DEFAULT_SUBTREES = (
    ("system", "1.3.6.1.2.1.1"),
    ("ifTable", "1.3.6.1.2.1.2.2"),
    ("ifXTable", "1.3.6.1.2.1.31.1.1"),
    ("ifStackTable", "1.3.6.1.2.1.31.1.2"),
    ("dot3StatsDuplexStatus", "1.3.6.1.2.1.10.7.2.1.19"),
    ("MAU-MIB", "1.3.6.1.2.1.26"),
    ("entPhysicalTable", "1.3.6.1.2.1.47.1.1.1"),
    ("entAliasMappingTable", "1.3.6.1.2.1.47.1.3.2"),
    ("dot1dBasePortTable", "1.3.6.1.2.1.17.1.4"),
    ("dot1dStp", "1.3.6.1.2.1.17.2"),
    ("Q-BRIDGE dot1qBase/Tp/Static/Vlan", "1.3.6.1.2.1.17.7.1"),
    ("LLDP-MIB objects", "1.0.8802.1.1.2.1"),
    ("IEEE8023-LAG-MIB", "1.2.840.10006.300.43"),
    ("POWER-ETHERNET-MIB", "1.3.6.1.2.1.105"),
    ("ENTITY-SENSOR-MIB", "1.3.6.1.2.1.99"),
    ("IEEE8021-MSTP-MIB", "1.3.111.2.802.1.1.6"),
)

NUMERIC_OID = re.compile(r"^\.?([0-2](?:\.(?:0|[1-9]\d{0,9}))+)$")
LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
HOSTNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62})(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}))*\.?$")

AUTH_PROTOCOLS = {"MD5": "MD5", "SHA": "SHA", "SHA1": "SHA", "SHA-1": "SHA", "SHA-224": "SHA-224",
                  "SHA224": "SHA-224", "SHA-256": "SHA-256", "SHA256": "SHA-256", "SHA-384": "SHA-384",
                  "SHA384": "SHA-384", "SHA-512": "SHA-512", "SHA512": "SHA-512"}
PRIV_PROTOCOLS = {"DES": "DES", "AES": "AES", "AES128": "AES", "AES-128": "AES", "AES192": "AES-192",
                  "AES-192": "AES-192", "AES256": "AES-256", "AES-256": "AES-256"}
SECURITY_LEVELS = ("noAuthNoPriv", "authNoPriv", "authPriv")

ENV_PREFIX = "NE_SNMP_"
ENV_COMMUNITY = "NE_SNMP_COMMUNITY"
ENV_V3 = {
    "username": "NE_SNMP_V3_USER",
    "security_level": "NE_SNMP_V3_SECURITY_LEVEL",
    "auth_protocol": "NE_SNMP_V3_AUTH_PROTOCOL",
    "auth_passphrase": "NE_SNMP_V3_AUTH_PASSPHRASE",
    "priv_protocol": "NE_SNMP_V3_PRIV_PROTOCOL",
    "priv_passphrase": "NE_SNMP_V3_PRIV_PASSPHRASE",
}

# snmprec tags (snmpsim)
TAG_INTEGER = "2"
TAG_OCTETS = "4"
TAG_NULL = "5"
TAG_OID = "6"
TAG_IPADDRESS = "64"
TAG_COUNTER32 = "65"
TAG_GAUGE32 = "66"
TAG_TIMETICKS = "67"
TAG_COUNTER64 = "70"

OUTCOME_OK = "ok"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_ABSENT = "no-such-object"
OUTCOME_ERROR = "error"
OUTCOME_SKIPPED = "skipped"


class UsageError(Exception):
    """Configuration problem; exit code 2. Messages never contain secrets."""


# --------------------------------------------------------------------------
# Records and snmpbulkwalk output parsing
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Record:
    oid: str            # numeric, no leading dot
    tag: str            # snmprec tag
    value: Any          # int, bytes (octets), str (OID / IPv4) or None (Null)


@dataclass
class ParseResult:
    records: list[Record] = field(default_factory=list)
    absent: bool = False       # agent reported noSuchObject/noSuchInstance/endOfMibView
    skipped: list[str] = field(default_factory=list)   # unparseable value types (no values kept)


VARBIND = re.compile(r"^\.?(\d+(?:\.\d+)*) = (.*)$")
ABSENT_MESSAGES = ("No Such Object available", "No Such Instance currently exists",
                   "No more variables left in this MIB View")
WRONG_TYPE = re.compile(r"^Wrong Type \(should be [^)]*\): ")
TYPED = re.compile(r"^(STRING|Hex-STRING|INTEGER|Gauge32|Counter32|Counter64|UInteger32|Timeticks|"
                   r"IpAddress|OID|BITS|Opaque|Network Address|NULL)(?::\s?(.*))?$", re.DOTALL)
LEADING_INT = re.compile(r"-?\d+")


def oid_tuple(oid: str) -> tuple[int, ...]:
    return tuple(int(part) for part in oid.split("."))


def _string_closed(raw: str) -> bool:
    """True when a quoted net-snmp STRING value has its closing quote."""
    raw = WRONG_TYPE.sub("", raw)
    if raw.startswith("STRING: "):
        raw = raw[len("STRING: "):]
    if not raw.startswith('"'):
        return True
    body = raw[1:]
    escaped = False
    for char in body:
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            return True
    return False


def _unescape_string(raw: str) -> str:
    if not (raw.startswith('"') and raw.endswith('"') and len(raw) >= 2):
        return raw
    body = raw[1:-1]
    return re.sub(r'\\(["\\])', r"\1", body)


def _parse_int(text: str) -> int:
    # "up(1)" (without -Oe) carries the number in parentheses.
    enum = re.search(r"\((-?\d+)\)\s*$", text)
    if enum:
        return int(enum.group(1))
    match = LEADING_INT.match(text.strip())
    if not match:
        raise ValueError(f"not an integer: {text!r}")
    return int(match.group(0))


def _parse_hex(text: str) -> bytes:
    tokens = text.split()
    octets = []
    for token in tokens:
        if re.fullmatch(r"[0-9A-Fa-f]{2}", token):
            octets.append(token)
        else:
            break   # BITS values end with "name(n)" labels
    return bytes.fromhex("".join(octets))


def parse_value(oid: str, raw: str) -> Record | None:
    """Convert one net-snmp value (``-On -Oe -Ox -OU``, optionally ``-Ot``) to a Record.

    Returns None for exception values (noSuchObject etc.). Raises ValueError
    for types snmpsim cannot represent here (e.g. Opaque).
    """
    raw = WRONG_TYPE.sub("", raw.strip("\r\n"))
    if raw.startswith(ABSENT_MESSAGES):
        return None
    if raw.startswith('"'):
        # Untyped quoted value: net-snmp prints empty octet strings as "".
        return Record(oid, TAG_OCTETS, _unescape_string(raw).encode("latin-1"))
    if re.fullmatch(r"\d+", raw.strip()):
        # -Ot prints TimeTicks as a bare number without a type prefix.
        return Record(oid, TAG_TIMETICKS, int(raw.strip()))
    match = TYPED.match(raw)
    if not match:
        raise ValueError(f"unrecognised value format: {raw[:40]!r}")
    kind, text = match.group(1), match.group(2) or ""
    if kind == "STRING":
        return Record(oid, TAG_OCTETS, _unescape_string(text).encode("latin-1"))
    if kind in ("Hex-STRING", "BITS"):
        return Record(oid, TAG_OCTETS, _parse_hex(text))
    if kind == "INTEGER":
        return Record(oid, TAG_INTEGER, _parse_int(text))
    if kind in ("Gauge32", "UInteger32"):
        return Record(oid, TAG_GAUGE32, _parse_int(text))
    if kind == "Counter32":
        return Record(oid, TAG_COUNTER32, _parse_int(text))
    if kind == "Counter64":
        return Record(oid, TAG_COUNTER64, _parse_int(text))
    if kind == "Timeticks":
        ticks = re.match(r"^\((\d+)\)", text.strip())
        return Record(oid, TAG_TIMETICKS, int(ticks.group(1)) if ticks else _parse_int(text))
    if kind == "IpAddress":
        return Record(oid, TAG_IPADDRESS, str(ipaddress.IPv4Address(text.strip())))
    if kind == "Network Address":
        octets = bytes.fromhex(text.strip().replace(":", ""))
        return Record(oid, TAG_IPADDRESS, str(ipaddress.IPv4Address(octets)))
    if kind == "OID":
        value = text.strip().lstrip(".")
        if not NUMERIC_OID.fullmatch(value) and value not in ("0", "0.0"):
            raise ValueError(f"non-numeric OID value: {value[:40]!r}")
        return Record(oid, TAG_OID, value)
    if kind == "NULL":
        return Record(oid, TAG_NULL, None)
    raise ValueError(f"unsupported type {kind}")


def parse_walk_output(text: str) -> ParseResult:
    """Parse ``snmpbulkwalk -On -Oe -Ox -OU`` output, including wrapped values.

    net-snmp wraps long Hex-STRING values over several lines and prints
    embedded newlines of quoted STRING values literally; any line that does
    not start a new varbind continues the previous value.
    """
    result = ParseResult()
    pending: list[list[str]] = []   # [oid, raw value]
    for line in text.splitlines():
        if pending and not _string_closed(pending[-1][1]):
            pending[-1][1] += "\n" + line
            continue
        match = VARBIND.match(line)
        if match:
            pending.append([match.group(1), match.group(2)])
        elif pending and line.strip():
            separator = " " if pending[-1][1].startswith(("Hex-STRING", "BITS")) else "\n"
            pending[-1][1] += separator + line
    for oid, raw in pending:
        try:
            record = parse_value(oid, raw)
        except (ValueError, ipaddress.AddressValueError) as error:
            result.skipped.append(f"{oid}: {error}")
            continue
        if record is None:
            result.absent = True
        else:
            result.records.append(record)
    return result


# --------------------------------------------------------------------------
# snmprec rendering
# --------------------------------------------------------------------------

def _printable(value: bytes) -> bool:
    return (all(0x20 <= byte <= 0x7E for byte in value) and b"|" not in value
            and value == value.strip())


def snmprec_line(record: Record) -> str:
    if record.tag == TAG_OCTETS:
        if _printable(record.value):
            return f"{record.oid}|4|{record.value.decode('ascii')}"
        return f"{record.oid}|4x|{record.value.hex()}"
    if record.tag == TAG_NULL:
        return f"{record.oid}|5|"
    return f"{record.oid}|{record.tag}|{record.value}"


def render_snmprec(records: Iterable[Record]) -> str:
    ordered = sorted(records, key=lambda r: oid_tuple(r.oid))
    return "".join(snmprec_line(record) + "\n" for record in ordered)


# --------------------------------------------------------------------------
# Sanitisation
# --------------------------------------------------------------------------

SYS_CONTACT = "1.3.6.1.2.1.1.4.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"
SYS_LOCATION = "1.3.6.1.2.1.1.6.0"
LLDP_LOC_SYS_NAME = "1.0.8802.1.1.2.1.3.3.0"
LLDP_REM_SYS_NAME = "1.0.8802.1.1.2.1.4.1.1.9"
ENT_SERIAL = "1.3.6.1.2.1.47.1.1.1.1.11"
IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.18"
LLDP_LOC_MAN_ADDR_ENTRY = "1.0.8802.1.1.2.1.3.8.1"   # index: subtype, len, addr
LLDP_REM_MAN_ADDR_ENTRY = "1.0.8802.1.1.2.1.4.2.1"   # index: timeMark, localPort, remIndex, subtype, len, addr
# (value column, subtype column, subtype value meaning "networkAddress")
LLDP_NETWORK_ADDRESS_IDS = (
    ("1.0.8802.1.1.2.1.3.2", "1.0.8802.1.1.2.1.3.1", 5),        # lldpLocChassisId
    ("1.0.8802.1.1.2.1.4.1.1.5", "1.0.8802.1.1.2.1.4.1.1.4", 5),  # lldpRemChassisId
    ("1.0.8802.1.1.2.1.3.7.1.3", "1.0.8802.1.1.2.1.3.7.1.2", 4),  # lldpLocPortId
    ("1.0.8802.1.1.2.1.4.1.1.7", "1.0.8802.1.1.2.1.4.1.1.6", 4),  # lldpRemPortId
)
DOCUMENTATION_NETS = ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")

SANITISATION_LIMITS = [
    "IPv4 addresses are replaced only in IpAddress values, LLDP management-address indexes and "
    "LLDP chassis/port IDs of subtype networkAddress; IPv4 text inside descriptions is not altered.",
    "IPv6 addresses are not altered; IPv4 netmasks, loopback, multicast and 0.0.0.0 are kept.",
    "Addresses embedded in other OID indexes (e.g. ipAddrTable from an --extra-subtree) are not altered.",
    "sysName, lldpLocSysName and lldpRemSysName are replaced by exact value; a neighbour that "
    "advertises an FQDN where the device reports a short name gets a different placeholder.",
    "MAC addresses (ifPhysAddress, LLDP chassis IDs, bridge addresses) are not altered.",
    "sysDescr, lldpRemSysDesc, ifDescr, port descriptions and entPhysical descriptions are not altered.",
    "Serial numbers are replaced only with --sanitise-serials; ifAlias only with --sanitise-aliases.",
    "Placeholders are consistent across devices only when the same --sanitise-map file is reused.",
]


def _is_netmask(address: ipaddress.IPv4Address) -> bool:
    value = int(address)
    inverted = ~value & 0xFFFFFFFF
    return value >> 24 == 0xFF and inverted & (inverted + 1) == 0


def _is_mappable_ipv4(address: ipaddress.IPv4Address) -> bool:
    """Addresses that identify something; masks and special addresses are kept."""
    return not (address.is_unspecified or address.is_loopback or address.is_multicast
                or _is_netmask(address))


class Sanitiser:
    """Deterministic replacement of identifying values.

    Assignment order follows sorted OIDs, so the same input always produces the
    same output. A mapping file lets several captures share placeholders.
    """

    CATEGORIES = ("ipv4", "names", "locations", "serials", "aliases")

    def __init__(self, serials: bool = False, aliases: bool = False, mapping: dict | None = None):
        self.serials = serials
        self.aliases = aliases
        self.maps: dict[str, dict[str, str]] = {name: dict((mapping or {}).get(name, {})) for name in self.CATEGORIES}
        self.pool = [str(host) for net in DOCUMENTATION_NETS for host in ipaddress.IPv4Network(net).hosts()]

    def mapping(self) -> dict:
        return {"format": "network-explorer-sanitise-map-1", **{name: dict(sorted(self.maps[name].items()))
                                                                for name in self.CATEGORIES}}

    def ipv4(self, value: str) -> str:
        address = ipaddress.IPv4Address(value)
        if not _is_mappable_ipv4(address):
            return value
        table = self.maps["ipv4"]
        if value not in table:
            used = set(table.values())
            replacement = next((candidate for candidate in self.pool if candidate not in used), None)
            if replacement is None:
                raise UsageError("More distinct IPv4 addresses than documentation addresses available.")
            table[value] = replacement
        return table[value]

    def _placeholder(self, category: str, value: bytes, template: str) -> bytes:
        if not value:
            return value
        key = value.decode("latin-1")
        table = self.maps[category]
        if key not in table:
            table[key] = template.format(len(table) + 1)
        return table[key].encode("ascii")

    def _ipv4_octets(self, octets: bytes) -> bytes:
        return ipaddress.IPv4Address(self.ipv4(str(ipaddress.IPv4Address(octets)))).packed

    def _man_addr_oid(self, oid: str) -> str:
        for entry, index_before in ((LLDP_LOC_MAN_ADDR_ENTRY, 0), (LLDP_REM_MAN_ADDR_ENTRY, 3)):
            if not oid.startswith(entry + "."):
                continue
            arcs = oid[len(entry) + 1:].split(".")
            position = 1 + index_before        # skip column and preceding index parts
            if len(arcs) == position + 2 + 4 and arcs[position] == "1" and arcs[position + 1] == "4":
                octets = bytes(int(arc) for arc in arcs[position + 2:])
                mapped = self._ipv4_octets(octets)
                arcs[position + 2:] = [str(byte) for byte in mapped]
                return f"{entry}.{'.'.join(arcs)}"
        return oid

    def apply(self, records: list[Record]) -> list[Record]:
        ordered = sorted(records, key=lambda r: oid_tuple(r.oid))
        by_oid = {record.oid: record for record in ordered}
        output = []
        for record in ordered:
            oid, value = self._man_addr_oid(record.oid), record.value
            if record.tag == TAG_IPADDRESS:
                value = self.ipv4(value)
            elif record.tag == TAG_OCTETS:
                value = self._octets(record, by_oid)
            output.append(Record(oid, record.tag, value))
        return sorted(output, key=lambda r: oid_tuple(r.oid))

    def _octets(self, record: Record, by_oid: dict) -> bytes:
        oid, value = record.oid, record.value
        if oid in (SYS_NAME, LLDP_LOC_SYS_NAME) or oid.startswith(LLDP_REM_SYS_NAME + "."):
            return self._placeholder("names", value, "device-{:03d}")
        if oid == SYS_LOCATION:
            return self._placeholder("locations", value, "location-{:03d}")
        if oid == SYS_CONTACT:
            return b"contact-redacted" if value else value
        if self.serials and oid.startswith(ENT_SERIAL + "."):
            return self._placeholder("serials", value, "SERIAL-{:04d}")
        if self.aliases and oid.startswith(IF_ALIAS + "."):
            return self._placeholder("aliases", value, "alias-{:04d}")
        for column, subtype_column, network_subtype in LLDP_NETWORK_ADDRESS_IDS:
            if oid == column or oid.startswith(column + "."):
                subtype = by_oid.get(subtype_column + oid[len(column):])
                if (subtype is not None and subtype.value == network_subtype
                        and len(value) == 5 and value[0] == 1):   # IANA address family 1 = IPv4
                    return value[:1] + self._ipv4_octets(value[1:])
        return value


class SerialSanitiser(Sanitiser):
    """--sanitise-serials/--sanitise-aliases without --sanitise: only those columns."""

    def _octets(self, record: Record, by_oid: dict) -> bytes:
        if self.serials and record.oid.startswith(ENT_SERIAL + "."):
            return self._placeholder("serials", record.value, "SERIAL-{:04d}")
        if self.aliases and record.oid.startswith(IF_ALIAS + "."):
            return self._placeholder("aliases", record.value, "alias-{:04d}")
        return record.value

    def apply(self, records: list[Record]) -> list[Record]:
        ordered = sorted(records, key=lambda r: oid_tuple(r.oid))
        return [Record(r.oid, r.tag, self._octets(r, {}) if r.tag == TAG_OCTETS else r.value) for r in ordered]


# --------------------------------------------------------------------------
# Credentials and protected files
# --------------------------------------------------------------------------

def read_protected_json(path: str, what: str, max_bytes: int = 1_048_576) -> Any:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise UsageError(f"{what} must be a regular file.")
            if os.name == "posix" and metadata.st_mode & 0o077:
                raise UsageError(f"{what} must not be group/world accessible (chmod 600).")
            if metadata.st_size > max_bytes:
                raise UsageError(f"{what} exceeds the size limit.")
            return json.load(stream)
    except UsageError:
        raise
    except (OSError, ValueError, UnicodeError):
        raise UsageError(f"{what} cannot be read as protected JSON.") from None


def write_private(path: Path, content: str) -> None:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            # O_CREAT's mode only applies to new files; tighten a pre-existing one.
            os.fchmod(fd, 0o600)
        except OSError:
            os.close(fd)
            raise
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    except OSError:
        raise UsageError(f"Cannot write output file {path.name}.") from None


def _secret(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise UsageError(f"Credential field '{name}' is missing.")
    if value != value.strip() or any(char in value for char in "\r\n\x00"):
        raise UsageError(f"Credential field '{name}' must not contain leading/trailing whitespace or line breaks.")
    if len(value) > 256:
        raise UsageError(f"Credential field '{name}' is too long.")
    return value


def validate_credentials(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise UsageError("Credentials must be a JSON object.")
    version = str(raw.get("version", ""))
    if version == "2c":
        return {"version": "2c", "community": _secret(raw.get("community"), "community")}
    if version != "3":
        raise UsageError("Credentials 'version' must be \"2c\" or \"3\" (SNMPv1 is not supported).")
    level = raw.get("security_level", "authPriv")
    if level not in SECURITY_LEVELS:
        raise UsageError("security_level must be noAuthNoPriv, authNoPriv or authPriv.")
    credentials = {"version": "3", "security_level": level, "username": _secret(raw.get("username"), "username")}
    if level in ("authNoPriv", "authPriv"):
        protocol = AUTH_PROTOCOLS.get(str(raw.get("auth_protocol", "")).upper())
        if not protocol:
            raise UsageError("auth_protocol must be one of MD5, SHA, SHA-224, SHA-256, SHA-384, SHA-512.")
        credentials["auth_protocol"] = protocol
        credentials["auth_passphrase"] = _secret(raw.get("auth_passphrase"), "auth_passphrase")
    if level == "authPriv":
        protocol = PRIV_PROTOCOLS.get(str(raw.get("priv_protocol", "")).upper())
        if not protocol:
            raise UsageError("priv_protocol must be one of DES, AES, AES-192, AES-256.")
        credentials["priv_protocol"] = protocol
        credentials["priv_passphrase"] = _secret(raw.get("priv_passphrase"), "priv_passphrase")
    return credentials


def credentials_from_env(environ: dict) -> dict:
    if environ.get(ENV_COMMUNITY):
        return validate_credentials({"version": "2c", "community": environ[ENV_COMMUNITY]})
    if environ.get(ENV_V3["username"]):
        raw = {"version": "3"}
        raw.update({key: environ[name] for key, name in ENV_V3.items() if environ.get(name)})
        return validate_credentials(raw)
    raise UsageError(f"Pass --credentials or set {ENV_COMMUNITY} / {ENV_V3['username']} and related variables.")


def secret_values(credentials: dict) -> list[str]:
    keys = ("community", "username", "auth_passphrase", "priv_passphrase")
    return sorted((credentials[key] for key in keys if credentials.get(key)), key=len, reverse=True)


def redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        text = text.replace(secret, "***")
    return text


def snmp_conf(credentials: dict) -> str:
    """net-snmp client defaults (snmp.conf(5)); keeps credentials out of argv."""
    if credentials["version"] == "2c":
        lines = ["defVersion 2c", f"defCommunity {credentials['community']}"]
    else:
        lines = ["defVersion 3", f"defSecurityName {credentials['username']}",
                 f"defSecurityLevel {credentials['security_level']}"]
        if "auth_protocol" in credentials:
            lines += [f"defAuthType {credentials['auth_protocol']}",
                      f"defAuthPassphrase {credentials['auth_passphrase']}"]
        if "priv_protocol" in credentials:
            lines += [f"defPrivType {credentials['priv_protocol']}",
                      f"defPrivPassphrase {credentials['priv_passphrase']}"]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Running snmpbulkwalk
# --------------------------------------------------------------------------

def validate_oid(text: str) -> str:
    match = NUMERIC_OID.fullmatch(text.strip())
    if not match:
        raise UsageError(f"Subtree must be a numeric OID such as 1.3.6.1.4.1.9.9.23: {text[:60]!r}")
    return match.group(1)


def snmp_target(host: str, port: int) -> str:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if not HOSTNAME.fullmatch(host):
            raise UsageError("--host must be an IP address or DNS name.") from None
        return f"udp:{host}:{port}"
    return f"udp6:[{address}]:{port}" if address.version == 6 else f"udp:{address}:{port}"


def build_command(binary: str, target: str, oid: str, request_timeout: float, retries: int,
                  max_repetitions: int, context: str | None) -> list[str]:
    command = [
        binary,
        "-m", "",            # load no MIBs: numeric OIDs, no display hints
        "-On",               # numeric OIDs
        "-Oe",               # enums as numbers
        "-Ox",               # octet strings always as Hex-STRING (unambiguous)
        "-OU",               # no UNITS suffixes
        "-t", f"{request_timeout:g}",
        "-r", str(retries),
        f"-Cr{max_repetitions}",
    ]
    if context:
        command += ["-n", context]
    return command + [target, oid]


def child_environment(conf_dir: str) -> dict:
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(ENV_PREFIX) and key not in ("MIBS", "MIBDIRS", "SNMPCONFFILE")}
    env["SNMPCONFPATH"] = conf_dir          # replaces ~/.snmp and /etc/snmp search paths
    env["SNMP_PERSISTENT_DIR"] = conf_dir   # engine boots/cert indexes stay in the temp dir
    return env


def net_snmp_version(binary: str, runner=subprocess.run) -> str:
    try:
        completed = runner([binary, "-V"], capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    output = (completed.stdout or b"") + (completed.stderr or b"")
    match = re.search(rb"NET-SNMP version:\s*(\S+)", output)
    return match.group(1).decode("ascii", "replace") if match else "unknown"


@dataclass
class SubtreeOutcome:
    name: str
    oid: str
    outcome: str
    records: int = 0
    duration_s: float = 0.0
    partial: bool = False
    message: str = ""
    skipped_values: int = 0

    def as_dict(self) -> dict:
        return {"name": self.name, "oid": self.oid, "outcome": self.outcome, "records": self.records,
                "duration_s": round(self.duration_s, 3), "partial": self.partial,
                "skipped_values": self.skipped_values, "message": self.message}


def _first_error_line(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return lines[-1][:200] if lines else ""


def walk_subtree(name: str, oid: str, command: list[str], env: dict, timeout: float,
                 secrets: list[str], runner=subprocess.run) -> tuple[SubtreeOutcome, list[Record]]:
    started = time.monotonic()
    timed_out = False
    try:
        completed = runner(command, env=env, capture_output=True, timeout=timeout, check=False)
        stdout, stderr, returncode = completed.stdout or b"", completed.stderr or b"", completed.returncode
    except subprocess.TimeoutExpired as error:
        stdout, stderr, returncode, timed_out = error.stdout or b"", error.stderr or b"", None, True
    except OSError as error:
        outcome = SubtreeOutcome(name, oid, OUTCOME_ERROR, message=redact(f"cannot run snmpbulkwalk: {error}", secrets))
        return outcome, []
    duration = time.monotonic() - started
    parsed = parse_walk_output(stdout.decode("latin-1"))
    records = [record for record in parsed.records if record.oid == oid or record.oid.startswith(oid + ".")]
    error_text = redact(stderr.decode("utf-8", "replace"), secrets)
    outcome = SubtreeOutcome(name, oid, OUTCOME_OK, records=len(records), duration_s=duration,
                             skipped_values=len(parsed.skipped))
    if timed_out or "Timeout: No Response" in error_text:
        outcome.outcome = OUTCOME_TIMEOUT
        outcome.partial = bool(records)
        outcome.message = "subtree time bound reached" if timed_out else _first_error_line(error_text)
    elif returncode not in (0, None):
        outcome.outcome = OUTCOME_ERROR
        outcome.partial = bool(records)
        outcome.message = _first_error_line(error_text) or f"snmpbulkwalk exited {returncode}"
    elif not records:
        outcome.outcome = OUTCOME_ABSENT
        outcome.message = "agent returned no instances in this subtree"
    if parsed.skipped:
        outcome.message = (outcome.message + "; " if outcome.message else "") + \
            f"{len(parsed.skipped)} value(s) of unsupported type omitted"
    return outcome, records


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parse_args(argv: list[str] | None) -> argparse.Namespace:
    # allow_abbrev=False: e.g. '--token' must not silently match '--token-file'.
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        description="Capture a bounded read-only SNMP walk of one device as an snmpsim .snmprec file.",
        epilog=f"Credentials: --credentials FILE (mode 0600) or {ENV_COMMUNITY} / {ENV_V3['username']} "
               "and related NE_SNMP_V3_* variables. They are never accepted as arguments.",
    )
    parser.add_argument("--host", required=True, help="Device IP address or DNS name")
    parser.add_argument("--port", type=int, default=161)
    parser.add_argument("--label", required=True, help="Device label used for output file names (A-Z a-z 0-9 _ . -)")
    parser.add_argument("--credentials", help="Protected JSON credentials file")
    parser.add_argument("--context", help="SNMPv3 context name (not secret)")
    parser.add_argument("--out-dir", default=".", help="Output directory (default: current directory)")
    parser.add_argument("--extra-subtree", action="append", default=[], metavar="OID",
                        help="Additional numeric subtree, e.g. a vendor MIB (repeatable)")
    parser.add_argument("--only-extra", action="store_true", help="Walk only --extra-subtree OIDs")
    parser.add_argument("--request-timeout", type=float, default=5.0, help="Per-request timeout seconds (default 5)")
    parser.add_argument("--retries", type=int, default=1, help="Per-request retries (default 1)")
    parser.add_argument("--max-repetitions", type=int, default=10, help="GETBULK max-repetitions (default 10)")
    parser.add_argument("--subtree-timeout", type=float, default=120.0, help="Time bound per subtree (default 120)")
    parser.add_argument("--total-timeout", type=float, default=900.0, help="Time bound for the capture (default 900)")
    parser.add_argument("--snmpbulkwalk", default="snmpbulkwalk", help="Path to net-snmp snmpbulkwalk")
    parser.add_argument("--sanitise", action="store_true",
                        help="Replace IPv4 addresses, sysName/LLDP system names, sysLocation and sysContact")
    parser.add_argument("--sanitise-serials", action="store_true", help="Replace entPhysicalSerialNum values")
    parser.add_argument("--sanitise-aliases", action="store_true", help="Replace ifAlias values")
    parser.add_argument("--sanitise-map", help="Private JSON mapping file reused across captures (never share it)")
    args = parser.parse_args(argv)
    if not LABEL.fullmatch(args.label):
        parser.error("--label must be 1-64 characters of A-Z a-z 0-9 _ . - and start with a letter or digit")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be 1-65535")
    if not 0 < args.request_timeout <= 60 or not 0 <= args.retries <= 5:
        parser.error("--request-timeout must be 0-60 s and --retries 0-5")
    if not 1 <= args.max_repetitions <= 100:
        parser.error("--max-repetitions must be 1-100")
    if not 0 < args.subtree_timeout <= args.total_timeout <= 7200:
        parser.error("require 0 < --subtree-timeout <= --total-timeout <= 7200")
    if args.context is not None and (not args.context or any(c in args.context for c in "\r\n\x00")):
        parser.error("--context is invalid")
    if args.sanitise_map and not (args.sanitise or args.sanitise_serials or args.sanitise_aliases):
        parser.error("--sanitise-map requires a --sanitise option")
    if args.only_extra and not args.extra_subtree:
        parser.error("--only-extra requires --extra-subtree")
    return args


def subtrees_for(args) -> list[tuple[str, str]]:
    chosen = [] if args.only_extra else list(DEFAULT_SUBTREES)
    seen = {oid for _, oid in chosen}
    for text in args.extra_subtree:
        oid = validate_oid(text)
        if oid not in seen:
            chosen.append((f"extra {oid}", oid))
            seen.add(oid)
    return chosen


def make_sanitiser(args) -> Sanitiser | None:
    if not (args.sanitise or args.sanitise_serials or args.sanitise_aliases):
        return None
    mapping = None
    if args.sanitise_map and Path(args.sanitise_map).exists():
        mapping = read_protected_json(args.sanitise_map, "Sanitise map")
        if not isinstance(mapping, dict) or mapping.get("format") != "network-explorer-sanitise-map-1":
            raise UsageError("Sanitise map format is not recognised.")
    cls = Sanitiser if args.sanitise else SerialSanitiser
    return cls(serials=args.sanitise_serials, aliases=args.sanitise_aliases, mapping=mapping)


def capture(args, runner=subprocess.run, environ: dict | None = None) -> int:
    environ = os.environ if environ is None else environ
    if args.credentials:
        credentials = validate_credentials(read_protected_json(args.credentials, "Credentials file"))
    else:
        credentials = credentials_from_env(environ)
    secrets = secret_values(credentials)
    subtrees = subtrees_for(args)
    target = snmp_target(args.host, args.port)
    sanitiser = make_sanitiser(args)
    out_dir = Path(args.out_dir)
    if not out_dir.is_dir():
        raise UsageError("--out-dir does not exist.")

    outcomes: list[SubtreeOutcome] = []
    records: dict[str, Record] = {}
    deadline = time.monotonic() + args.total_timeout
    with tempfile.TemporaryDirectory(prefix="ne-walk-") as conf_dir:
        write_private(Path(conf_dir) / "snmp.conf", snmp_conf(credentials))
        env = child_environment(conf_dir)
        version = net_snmp_version(args.snmpbulkwalk, runner)
        for name, oid in subtrees:
            remaining = deadline - time.monotonic()
            if remaining <= 1:
                outcomes.append(SubtreeOutcome(name, oid, OUTCOME_SKIPPED, message="total time bound reached"))
                continue
            command = build_command(args.snmpbulkwalk, target, oid, args.request_timeout, args.retries,
                                    args.max_repetitions, args.context)
            outcome, found = walk_subtree(name, oid, command, env, min(args.subtree_timeout, remaining),
                                          secrets, runner)
            outcomes.append(outcome)
            for record in found:
                records.setdefault(record.oid, record)
            print(f"{name} ({oid}): {outcome.outcome}, {outcome.records} record(s)"
                  + (f" - {outcome.message}" if outcome.message else ""), file=sys.stderr)

    final = list(records.values())
    if sanitiser is not None:
        final = sanitiser.apply(final)
        if args.sanitise_map:
            write_private(Path(args.sanitise_map), json.dumps(sanitiser.mapping(), indent=2, sort_keys=True) + "\n")

    snmprec_path = out_dir / f"{args.label}.snmprec"
    manifest_path = out_dir / f"{args.label}.manifest.json"
    write_private(snmprec_path, render_snmprec(final))
    manifest = {
        "format": "network-explorer-walk-manifest-1",
        "device_label": args.label,
        "captured_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "net_snmp_version": version,
        "snmp_version": credentials["version"],
        "snmp_security_level": credentials.get("security_level", ""),
        "walk_options": {"max_repetitions": args.max_repetitions, "request_timeout_s": args.request_timeout,
                         "retries": args.retries, "subtree_timeout_s": args.subtree_timeout,
                         "total_timeout_s": args.total_timeout,
                         "snmpbulkwalk_flags": ["-m", "", "-On", "-Oe", "-Ox", "-OU"]},
        "sanitised": {"enabled": bool(args.sanitise), "serials": bool(args.sanitise_serials),
                      "aliases": bool(args.sanitise_aliases), "shared_map": bool(args.sanitise_map)},
        "sanitisation_limits": SANITISATION_LIMITS if sanitiser is not None else [],
        "snmprec_file": snmprec_path.name,
        "record_count": len(final),
        "subtrees": [outcome.as_dict() for outcome in outcomes],
    }
    write_private(manifest_path, json.dumps(manifest, indent=2) + "\n")
    print(f"{len(final)} record(s) written to {snmprec_path}; manifest {manifest_path}", file=sys.stderr)

    failed = [o for o in outcomes if o.outcome in (OUTCOME_TIMEOUT, OUTCOME_ERROR, OUTCOME_SKIPPED)]
    if outcomes and len(failed) == len(outcomes) and not final:
        return EXIT_UNREACHABLE
    return EXIT_PARTIAL if failed else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return capture(args)
    except UsageError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
