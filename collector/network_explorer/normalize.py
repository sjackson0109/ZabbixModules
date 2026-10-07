"""Conservative standard-MIB normalizers, independent of SNMP transport."""

import hashlib
import ipaddress
from collections import Counter
from typing import Any

from . import oids
from .models import Evidence


def integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value) if value is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def mac(value: Any) -> str | None:
    if isinstance(value, bytes) and len(value) == 6:
        return ":".join(f"{part:02x}" for part in value)
    if isinstance(value, str):
        compact = value.replace(":", "").replace("-", "").strip().lower()
        if len(compact) == 12 and all(char in "0123456789abcdef" for char in compact):
            return ":".join(compact[index:index + 2] for index in range(0, 12, 2))
    return None


def identifier(subtype: Any, value: Any, kind: str) -> dict:
    subtype = integer(subtype)
    # LLDP subtype numbers differ for chassis and port MAC/network identities.
    mac_type, network_type = (4, 5) if kind == "chassis" else (3, 4)
    if subtype == mac_type:
        normalized = mac(value)
    elif subtype == network_type and isinstance(value, bytes) and value:
        try:
            normalized = str(ipaddress.ip_address(value[1:])) if value[0] in (1, 2) else None
        except ValueError:
            normalized = None
    else:
        if isinstance(value, bytes):
            try:
                normalized = value.decode("utf-8", errors="strict")
            except UnicodeError:
                normalized = "hex:" + value.hex()
        else:
            normalized = text(value)
    if normalized is None and isinstance(value, bytes):
        normalized = "hex:" + value.hex()
    return {"subtype": subtype, "value": normalized or ""}


def interface_uid(name: str | None, description: str | None) -> str | None:
    if name and name.strip():
        basis = "name:" + name.strip()
    elif description and description.strip():
        basis = "description:" + description.strip()
    else:
        return None
    return "if-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


def interfaces(evidence: Evidence, generation: str) -> list[dict]:
    tables = {key: evidence.table(oid) for key, oid in oids.IF.items()}
    rows = []
    for index in sorted(tables["index"]):
        if len(index) != 1 or integer(tables["index"][index]) != index[0] or index[0] < 1:
            evidence.error("malformed_interface", "An IF-MIB row has an inconsistent ifIndex.")
            continue
        def get(key):
            return tables[key].get(index)
        name, description = text(get("name")), text(get("description"))
        if_type = integer(get("type"))
        admin, oper = integer(get("admin")), integer(get("oper"))
        if description is None or if_type is None or admin not in (1, 2, 3) or oper not in range(1, 8):
            evidence.error("missing_interface_fields", "An interface has missing or invalid mandatory fields.")
        high_speed, speed = integer(get("high_speed")), integer(get("speed"))
        # ifSpeed saturates at 2^32-1; this sentinel is not an actual speed.
        speed_bps = high_speed * 1_000_000 if high_speed and high_speed > 0 else (
            speed if speed is not None and 0 < speed < 4_294_967_295 else None
        )
        connector = integer(get("connector"))
        physical = {1: True, 2: False}.get(connector)
        if physical is None:
            if if_type == 6:
                physical = True
            elif if_type in (24, 53, 131, 135, 136, 161):
                physical = False
        rows.append({
            "uid": interface_uid(name, description), "if_index": index[0],
            "name": name, "description": description, "alias": text(get("alias")), "type": if_type,
            "physical": physical,
            "admin_status": {1: "up", 2: "down", 3: "testing"}.get(admin),
            "oper_status": {1: "up", 2: "down", 3: "testing", 4: "unknown", 5: "dormant",
                            6: "not_present", 7: "lower_layer_down"}.get(oper),
            "speed_bps": speed_bps,
            "duplex": {2: "half", 3: "full"}.get(integer(get("duplex"))),
            "mtu": integer(get("mtu")), "mac_address": mac(get("mac")),
        })
    counts = Counter(row["uid"] for row in rows if row["uid"])
    for row in rows:
        if not row["uid"] or counts[row["uid"]] > 1:
            row["uid"] = "uncertain-" + hashlib.sha256(
                (generation + ":" + str(row["if_index"])).encode()
            ).hexdigest()[:24]
            evidence.error("identity_ambiguous", "Interface identity is missing or duplicated; history continuity is uncertain.")
    expected = integer(evidence.scalar(oids.IF_NUMBER))
    if expected is not None and expected != len(rows):
        evidence.error("interface_count_mismatch", "ifNumber does not match the observed interface row count.")
    return rows


def _map_local_port(subtype: int | None, value: Any, description: Any,
                    rows: list[dict], evidence: Evidence) -> str | None:
    value_text = text(value)
    if subtype == 5:
        matches = [row for row in rows if row["name"] == value_text]
    elif subtype == 3:
        identity = mac(value)
        matches = [row for row in rows if identity and row["mac_address"] == identity]
    elif subtype == 1:
        aliases = evidence.table(oids.IF["alias"])
        matches = [row for row in rows if value_text and text(aliases.get((row["if_index"],))) == value_text]
    elif subtype == 7:
        # No assumption that a local port number or locally assigned ID is ifIndex.
        matches = [row for row in rows if value_text and value_text in (row["name"], row["description"])]
        desc = text(description)
        if len(matches) != 1 and desc:
            matches = [row for row in rows if desc == row["description"]]
    else:
        matches = []
    return matches[0]["uid"] if len(matches) == 1 else None


def _management_addresses(evidence: Evidence) -> dict[tuple[int, ...], list[str]]:
    addresses: dict[tuple[int, ...], list[str]] = {}
    for index in evidence.table(oids.LLDP_REMOTE["management"]):
        # timeMark/localPort/remIndex/family/length/address octets.
        if len(index) < 6:
            evidence.error("malformed_management_index", "An LLDP management address index is incomplete.")
            continue
        family, length = index[3:5]
        octets = index[5:]
        if len(octets) != length or any(not 0 <= octet <= 255 for octet in octets):
            evidence.error("malformed_management_index", "An LLDP management address has inconsistent encoded length.")
            continue
        if family not in (1, 2):
            continue
        try:
            address = ipaddress.ip_address(bytes(octets))
            if address.version != {1: 4, 2: 6}[family]:
                raise ValueError("family")
            addresses.setdefault(index[:3], []).append(str(address))
        except ValueError:
            evidence.error("malformed_management_address", "An LLDP address has invalid IP encoding.")
    return {index: sorted(set(values)) for index, values in addresses.items()}


def lldp(evidence: Evidence, interface_rows: list[dict], observed_at: str,
         redact_remote: bool = True) -> list[dict]:
    local = {key: evidence.table(oid) for key, oid in oids.LLDP_LOCAL.items()}
    remote = {key: evidence.table(oid) for key, oid in oids.LLDP_REMOTE.items() if key != "management"}
    addresses = _management_addresses(evidence)
    indices = set().union(*(table.keys() for table in remote.values()))
    rows = []
    for index in sorted(indices):
        if len(index) != 3:
            evidence.error("malformed_lldp_index", "An LLDP row does not contain timeMark/localPort/remIndex.")
            continue
        get = lambda key: remote[key].get(index)
        required = ("chassis_subtype", "chassis_id", "port_subtype", "port_id")
        if any(get(key) is None for key in required):
            evidence.error("missing_lldp_identity", "An LLDP observation lacks a mandatory remote identity.")
            continue
        local_index = (index[1],)
        subtype = integer(local["subtype"].get(local_index))
        port_id = local["id"].get(local_index)
        uid = _map_local_port(subtype, port_id, local["description"].get(local_index), interface_rows, evidence)
        if uid is None:
            evidence.error("local_port_unresolved", "An LLDP local port could not be mapped unambiguously to an interface.")
        chassis = identifier(get("chassis_subtype"), get("chassis_id"), "chassis")
        port = identifier(get("port_subtype"), get("port_id"), "port")
        row = {
            "local_interface_uid": uid,
            "local_port_id": identifier(subtype, port_id, "port"),
            "remote_chassis_id": chassis, "remote_port_id": port,
            "remote_system_name": text(get("system_name")),
            "remote_port_description": text(get("port_description")),
            "remote_management_addresses": addresses.get(index, []),
            "observed_at": observed_at,
        }
        if redact_remote:
            # Collection-boundary suppression protects raw item/API consumers too.
            # It intentionally disables peer identity resolution until explicitly opted in.
            row.update(remote_chassis_id={"subtype": None, "value": ""},
                       remote_port_id={"subtype": None, "value": ""},
                       remote_system_name=None, remote_port_description=None,
                       remote_management_addresses=[])
        rows.append(row)
    return rows


def lag(evidence: Evidence, interface_rows: list[dict], redact_remote: bool = True) -> list[dict]:
    tables = {key: evidence.table(oid) for key, oid in oids.LAG.items()}
    by_index = {row["if_index"]: row for row in interface_rows}
    rows = []
    indices = set().union(*(tables[key].keys() for key in ("individual", "actor", "partner")))
    readable_aggregators = {index[0] for index in indices if len(index) == 1}
    for attached in tables["attached"].values():
        aggregator = integer(attached)
        if aggregator and aggregator > 0 and aggregator not in readable_aggregators:
            evidence.error("lag_aggregator_unresolved", "A LAG member references an aggregator without readable identity evidence.")
    for index in sorted(indices):
        aggregator = index[0] if len(index) == 1 else None
        if not aggregator or aggregator < 1:
            evidence.error("malformed_lag_index", "A LAG aggregator has an invalid index.")
            continue
        interface = by_index.get(aggregator)
        if interface is None:
            evidence.error("lag_interface_unresolved", "An aggregator does not resolve to an IF-MIB interface.")
            continue
        members = []
        for member_index, attached in tables["attached"].items():
            if integer(attached) == aggregator:
                member = by_index.get(member_index[0]) if len(member_index) == 1 else None
                if member:
                    members.append(member["uid"])
                else:
                    evidence.error("lag_member_unresolved", "A LAG member does not resolve to an IF-MIB interface.")
        # dot3adAggAggregateOrIndividual is a TruthValue: 1 (true) is an aggregate, 2 (false) an
        # individual link. Anything not classified as an aggregate needs members or ifType 161.
        if integer(tables["individual"].get(index)) != 1 and not members and interface["type"] != 161:
            continue
        partner = mac(tables["partner"].get(index))
        if partner == "00:00:00:00:00:00":
            partner = None
        rows.append({
            "uid": interface["uid"], "name": interface["name"], "if_index": aggregator,
            "member_interface_uids": sorted(set(members)), "oper_status": interface["oper_status"],
            "actor_system_id": mac(tables["actor"].get(index)),
            "partner_system_id": None if redact_remote else partner,
        })
    return rows


def device(evidence: Evidence, redact_remote: bool = True) -> list[dict]:
    chassis_type = evidence.scalar(oids.LLDP_LOCAL_CHASSIS_SUBTYPE)
    chassis_id = evidence.scalar(oids.LLDP_LOCAL_CHASSIS_ID)
    chassis = [identifier(chassis_type, chassis_id, "chassis")] if chassis_id is not None else []
    return [{"hostname": text(evidence.scalar(oids.SYS_NAME)), "vendor": None,
             "model": None, "firmware": None, "chassis_ids": chassis,
             "management_addresses": []}]
