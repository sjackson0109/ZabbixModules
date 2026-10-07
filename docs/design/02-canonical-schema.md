# 02 — Canonical schema (Canonical Network Discovery Dataset)

Status: **current 1.1** (spec §13–17, §23, §40.2). The machine-readable contract is [`schemas/envelope-1.1.schema.json`](../../schemas/envelope-1.1.schema.json), with worked examples in [`schemas/examples/`](../../schemas/examples/) checked by `tests/unit/test_schema_1_1.py`. The native templates emit 1.1. Version 1.0 (`schemas/envelope.schema.json`) is still accepted by the frontend and is what the Python collector emits; 1.1 only adds datasets and optional fields, so a 1.0 producer stays readable.

## Envelope (unchanged from 1.0)

Every dataset is published per Zabbix host as one JSON envelope:

| Field | Meaning |
|---|---|
| `schema_version` | `1.1` |
| `dataset` | `device`, `interfaces`, `port_capability`, `lldp`, `vlan`, `stp`, `lag` |
| `generation_id` | Opaque identifier of this collection |
| `attempted_at` / `observed_at` | When collection was tried / when the data was observed. A failure has `observed_at = null` and never moves the observation time forward. |
| `status` | `ok`, `partial`, `failed`, `unsupported` |
| `complete` | True only for `ok` |
| `source` | Method (`native_snmp`, `python_snmp`, `fixture`, `agent`), adapter name and version |
| `capability` | `supported`, `partial`, `unsupported`, `unknown`, with a reason |
| `errors` | Coded, credential-free messages |
| `data` | Rows for the dataset (below) |

## Freshness (spec §23)

The frontend shows the five states the spec requires. Each is computed per dataset per host from the envelope and the Zabbix item state:

| Displayed state | Rule |
|---|---|
| Current | Last `ok` snapshot is younger than the dataset's stale threshold macro |
| Stale | Last `ok` snapshot is older than the threshold, or the latest attempt is `partial` |
| Collection failed | Latest attempt is `failed`, or the native master item is in the *not supported* state with a transport error |
| Unsupported | Latest attempt is `unsupported`, backed by a completed walk |
| Unknown | No snapshot has ever been received |

A stale or failed dataset still shows its last good data, always with the badge. It is never drawn as current (spec §23, §37).

## Field mapping to the specification

Fields marked *read time* are added by the frontend reader from Zabbix itself, not collected over SNMP. This keeps a host's dataset independent of server-assigned IDs.

### Device (spec §13)

| Spec field | Canonical field | Source |
|---|---|---|
| zabbix_host_id | — | read time (owning host) |
| hostname, display_name | — | read time (Zabbix `host`, `name`) |
| management_ip | `management_addresses[]` plus the Zabbix SNMP interface address | LLDP local management table; interface at read time |
| management_subnet | — | read time: compared against the configured scope CIDR |
| vendor, model, serial, firmware | `vendor`, `model`, `serial`, `firmware` | sysObjectID, ENTITY-MIB, vendor profile |
| chassis_or_stack_identifier | `chassis_ids[]`, `stack_members[]` | LLDP local chassis ID, ENTITY-MIB chassis rows |
| discovery_timestamp | envelope `observed_at` | |
| (added) | `sys_object_id`, `sys_name`, `description`, `uptime_s` | SNMPv2-MIB |

### Interface (spec §14)

| Spec field | Canonical field | Notes |
|---|---|---|
| device_id | — | read time |
| ifIndex | `if_index` | Current locator only. Identity is `uid`. |
| interface_name, interface_description | `name`, `description`, `alias` | `description` is ifDescr; `alias` is the configured port description (ifAlias). |
| interface_type | `type`, `physical`, `media` (new) | `media` distinguishes copper, SFP, SFP+ and QSFP for the panel layout. |
| admin_status, oper_status | `admin_status`, `oper_status` | |
| speed, duplex | `speed_bps`, `duplex` | bit/s; null when unknown |
| mtu, mac_address | `mtu`, `mac_address` | |
| last_change | `last_change` (new) | Absolute UTC time derived from ifLastChange and sysUpTime |
| (added) | `member`, `slot`, `port`, `stack_parent_uid` | Stack position and LAG/sub-interface parent |
| expected speed | `expected_speed_bps` | Explicit policy only. The derived expectation is computed at read time from `port_capability` and LLDP; see below. |

**Interface identity** (`uid`): `if-` plus 24 hex characters of SHA-256 over `name:<ifName>`, or `description:<ifDescr>` when ifName is absent. It survives ifIndex renumbering (spec §14, §31). A rename creates a new identity. Ambiguous names make the inventory `partial`, so discovery never acts on it.

### Port capability (new dataset)

Per interface: `autoneg_enabled`, `oper_mau_type`, `oper_speed_bps`, `oper_duplex`, `supported_speeds_bps[]`, `advertised_speeds_bps[]` and `partner_advertised_speeds_bps[]`. A null list means unknown and an empty list means known to be empty. This dataset exists so that expected speed can be **derived** rather than configured on every port (spec §3.2, criterion 16).

**Effective expected speed** (read time, shown with its source in Interface Detail):

| Precedence | Source label | Rule |
|---|---|---|
| 1 | `policy` | Per-port macro or `expected_speed_bps` in the dataset |
| 2 | `negotiable` | Highest speed in both the local advertised list and the partner's advertised list (from MAU or LLDP 802.3) |
| 3 | `uplink_capability` | LLDP peer is a bridge, partner list unknown: highest local advertised speed |
| 4 | `unknown` | No warning raised |

**Port semantic state** (spec §3.1; colours configurable, labels and icons always shown):

| Order | State | Default colour | Rule |
|---|---|---|---|
| 1 | Disabled | grey | admin down |
| 2 | No data | dark | interface dataset unknown or failed |
| 3 | Down | red | admin up, oper down |
| 4 | Error | red | error or discard rate above `{$NE.IF.ERROR_RATE.MAX}` |
| 5 | Degraded: speed | amber | up, effective expected known, actual below expected |
| 6 | Degraded: duplex | amber | half duplex where the partner is full (from LLDP), or half against an expected-duplex policy |
| 7 | Normal | green | up, at or above expected speed, or expectation unknown |

Stale data keeps its colour and adds a stale badge. It never turns green just because the last value was green.

### LLDP (spec §4, §15)

| Spec field | Canonical field |
|---|---|
| local_device | read time |
| local_interface, local_ifIndex | `local_interface_uid`, `local_if_index` (new), `local_port_id {subtype, value}` |
| remote_chassis_id | `remote_chassis_id {subtype, value}` |
| remote_device | read time: resolved Zabbix host, or an *external* or *undisclosed* placeholder |
| remote_port_id, remote_port_description | `remote_port_id {subtype, value}`, `remote_port_description` |
| remote_system_name | `remote_system_name` (plus `remote_system_description`, new) |
| remote_management_address | `remote_management_addresses[]` |
| capabilities | `capabilities {supported[], enabled[]}` (new) |
| last_seen | `observed_at` |
| (added) | `protocol` (`lldp` or `cdp`), `source_index` (timeMark.localPort.remIndex), `remote_advertised_speeds_bps`, `remote_oper_speed_bps`, `remote_duplex`, `remote_lag`, `remote_pvid` |

Peer resolution order (read time, within the user's permitted hosts and the same network domain): exact chassis ID, then unique management address, then system name with corroboration. Unresolved peers are kept as external devices (spec §4).

### VLAN (spec §8, §16)

One `vlan` envelope holds two row kinds, matching the spec's `vlan` and `vlan_membership`:

- `kind: vlan`: `vlan_id`, `name`, `state`, optional `bridge_domain`.
- `kind: port`: `interface_uid`, `bridge_port`, `mode` (`access`, `trunk`, `hybrid`, `unknown`), `pvid`, and VLAN **range strings** `tagged`, `untagged`, `forbidden` (configured) and `current_egress`, `current_untagged` (operational), plus `source`.

Range strings such as `"1,10-20,49"` keep a 48-port trunk carrying 4,000 VLANs to one short row instead of 4,000 rows. The per-VLAN tagging value the spec lists (`tagged`, `untagged`, `native`, `forbidden`, `unknown`) is derived from these lists. Native means untagged and equal to `pvid` on a trunk. Unknown means the lists are null.

### STP (spec §11, §17)

One `stp` envelope holds:

- `kind: bridge` per instance: `instance`, `protocol`, `bridge_id`, `root_bridge_id`, `root_cost`, `root_port_uid`, `priority`, `vlans` (instance-to-VLAN map), `topology_changes`, `time_since_topology_change_s`.
- `kind: port` per instance and port: `interface_uid`, `bridge_port`, `role`, `role_source` (`reported` or `derived`), `state`, `cost`, `priority`, `designated_bridge`, `designated_port`, `edge`, `point_to_point`.

Role and state are separate enums (spec §29). A derived role is labelled as such in the UI.

### LAG (spec §12)

| Spec field | Canonical field |
|---|---|
| device | read time |
| LAG ID, LAG name | `uid`, `if_index`, `name` |
| mode | `mode` (new): `lacp` (dot3adAgg row with a partner), `static` (ifType 161 with active ifStackTable members and no dot3adAgg row), `pagp` (reserved for vendor profiles; none emit it yet), `unknown` (no partner, or no members) |
| member interfaces | `member_interface_uids[]` plus `members[]` (new) with `selected`, `collecting`, `distributing` |
| operational state | `oper_status` |
| peer relationship | `actor_system_id`, `partner_system_id`; links grouped at read time from LLDP on member ports |

## Size limits

`data` holds at most 50,000 rows (raised from 20,000 for VLAN-heavy stacks). Real snapshot sizes must be measured from captured walks before release. Where a value exceeds the database's text limit, the dataset is split by stack member under a manifest (design §4).
