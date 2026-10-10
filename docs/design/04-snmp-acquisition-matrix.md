# 04 — SNMP acquisition matrix

Status: **proposed, for review** (spec §19, §22, §40.4). Every OID below is a standard or published vendor object to *investigate*. None is confirmed on a real device until a captured walk proves it (see `tools/inventory/`). Column numbers were taken from the MIB definitions; rows marked **verify** need a check against the MIB text before implementation.

## Collection principles

1. **One table walk per dataset, not one request per interface.** Each dataset has one native Zabbix master item using `walk[oid,oid,...]` on the host's SNMP interface (available in Zabbix 6.4 and later, so in all 7.x). Dependent items with JavaScript preprocessing turn the walk into the canonical JSON in [02 — canonical schema](02-canonical-schema.md).
2. **Each walk carries its own join columns.** Preprocessing cannot read another item, so a dataset that needs `ifName` (to build interface UIDs) or `dot1dBasePortIfIndex` (to map bridge ports) includes those columns in its own walk. This costs a few extra varbinds and keeps every dataset self-contained, so one failing dataset never corrupts another.
3. **Frequency follows how fast the data changes** (spec §22). All intervals are template macros.
4. **Capability probing is separate from polling.** An `unsupported` result needs a completed walk that returned `noSuchObject` or an empty subtree on a reachable agent. A timeout or authentication failure is a *collection failure*, never evidence of missing support.
5. **The Python proxy collector is only for gaps native items cannot fill.** These are listed at the end of this document.

## Master items

| Master item key | Dataset | Default interval (macro) | Feeds |
|---|---|---|---|
| `ne.raw.system` | device | 1h (`{$NE.DEVICE.INTERVAL}`) | `ne.device.snapshot`, uptime heartbeat |
| `ne.raw.if.state` | interface state | 60s (`{$NE.IF.STATE.INTERVAL}`) | `ne.interfaces.state`, per-port scalars |
| `ne.raw.if.inventory` | interface inventory | 1h (`{$NE.IF.INVENTORY.INTERVAL}`) | `ne.interfaces.inventory`, interface LLD |
| `ne.raw.if.capability` | port capability (expected speed) | 15m (`{$NE.IF.CAPABILITY.INTERVAL}`) | `ne.interfaces.capability` |
| `ne.raw.lldp` | LLDP | 5m (`{$NE.LLDP.INTERVAL}`) | `ne.lldp.snapshot` |
| `ne.raw.vlan` | VLAN | 10m (`{$NE.VLAN.INTERVAL}`) | `ne.vlan.snapshot` |
| `ne.raw.stp` | STP | 2m (`{$NE.STP.INTERVAL}`) | `ne.stp.snapshot` |
| `ne.raw.lag` | LAG | 5m (`{$NE.LAG.INTERVAL}`) | `ne.lag.snapshot` |
| `ne.raw.if.counters` | traffic and errors (optional) | 60s | per-port rate items; reuse existing items where present |

Raw master items keep history for 0 days (or 1 day while debugging). Canonical snapshots keep 7 days. Scalars keep 30 days of history and 365 days of trends.

## Device — `ne.raw.system`

| Object | MIB | OID | Canonical field | Notes |
|---|---|---|---|---|
| sysDescr | SNMPv2-MIB | 1.3.6.1.2.1.1.1.0 | `device.description`, firmware hint | Vendor-specific parsing of firmware from free text lives in the vendor profile's preprocessing, not the frontend. |
| sysObjectID | SNMPv2-MIB | 1.3.6.1.2.1.1.2.0 | `device.sys_object_id`, vendor/model | Enterprise number gives the vendor; the full OID selects the profile. |
| sysUpTime | SNMPv2-MIB | 1.3.6.1.2.1.1.3.0 | `device.uptime_s` | Reboot detection; every dataset also records it to reject walks that straddle a reboot. |
| sysName | SNMPv2-MIB | 1.3.6.1.2.1.1.5.0 | `device.sys_name` | Device-reported name only; never replaces the Zabbix host name. |
| entPhysicalClass | ENTITY-MIB | 1.3.6.1.2.1.47.1.1.1.1.5 | stack members (class 3 = chassis) | Stack membership: one chassis row per member. |
| entPhysicalContainedIn | ENTITY-MIB | 1.3.6.1.2.1.47.1.1.1.1.4 | containment tree | |
| entPhysicalName | ENTITY-MIB | 1.3.6.1.2.1.47.1.1.1.1.7 | member label | |
| entPhysicalSoftwareRev | ENTITY-MIB | 1.3.6.1.2.1.47.1.1.1.1.10 | `device.firmware` | Preferred over sysDescr parsing when populated. |
| entPhysicalSerialNum | ENTITY-MIB | 1.3.6.1.2.1.47.1.1.1.1.11 | `device.serial`, `stack_members[].serial` | |
| entPhysicalModelName | ENTITY-MIB | 1.3.6.1.2.1.47.1.1.1.1.13 | `device.model`, `stack_members[].model` | |
| lldpLocChassisIdSubtype / Id | LLDP-MIB | 1.0.8802.1.1.2.1.3.1.0 / .3.2.0 | `device.chassis_ids[]` | Primary key for matching this device as somebody's LLDP peer. |
| lldpLocManAddrTable | LLDP-MIB | 1.0.8802.1.1.2.1.3.8.1 | `device.management_addresses[]` (source `lldp_local`) | Address is encoded in the index (subtype, length, octets). |

The configured Zabbix SNMP interface address is added by the frontend reader as `management_address` (source `zabbix_interface`); it is never collected.

## Interface state — `ne.raw.if.state`

| Object | MIB | OID | Canonical field | Notes |
|---|---|---|---|---|
| ifAdminStatus | IF-MIB | 1.3.6.1.2.1.2.2.1.7 | `admin_status` | 1 up, 2 down, 3 testing |
| ifOperStatus | IF-MIB | 1.3.6.1.2.1.2.2.1.8 | `oper_status` | 1–7 per IF-MIB; 5 dormant, 6 notPresent, 7 lowerLayerDown |
| ifHighSpeed | IF-MIB (ifXTable) | 1.3.6.1.2.1.31.1.1.1.15 | `speed_bps` (×1,000,000) | Preferred. 0 on a down port means unknown, not 0 bit/s. |
| ifSpeed | IF-MIB | 1.3.6.1.2.1.2.2.1.5 | `speed_bps` fallback | Saturates at 4,294,967,295; only used when ifHighSpeed is absent. |
| dot3StatsDuplexStatus | EtherLike-MIB | 1.3.6.1.2.1.10.7.2.1.19 | `duplex` | 1 unknown, 2 half, 3 full. Indexed by ifIndex. |
| ifLastChange | IF-MIB | 1.3.6.1.2.1.2.2.1.9 | `last_change` | TimeTicks of sysUpTime; converted to an absolute time using sysUpTime in the same walk. |
| ifName | IF-MIB (ifXTable) | 1.3.6.1.2.1.31.1.1.1.1 | join column → `uid` | |
| ifDescr | IF-MIB | 1.3.6.1.2.1.2.2.1.2 | join column → `uid` fallback | |
| sysUpTime | SNMPv2-MIB | 1.3.6.1.2.1.1.3.0 | walk consistency | |

Cost: about 8 varbinds per interface per minute. A 48-port switch with ~60 ifTable rows is about 480 varbinds, or roughly 20 GETBULK exchanges at 25 repetitions.

## Interface inventory — `ne.raw.if.inventory`

| Object | MIB | OID | Canonical field | Notes |
|---|---|---|---|---|
| ifDescr, ifName, ifAlias | IF-MIB | .2.2.1.2, .31.1.1.1.1, .31.1.1.1.18 (under 1.3.6.1.2.1) | `name`, `description`, `alias` | Alias is the operator's port description. |
| ifType | IF-MIB | 1.3.6.1.2.1.2.2.1.3 | `type`, `physical` | 6 ethernetCsmacd, 161 ieee8023adLag, 53 propVirtual, 136 l3ipvlan, 24 softwareLoopback |
| ifMtu | IF-MIB | 1.3.6.1.2.1.2.2.1.4 | `mtu` | |
| ifPhysAddress | IF-MIB | 1.3.6.1.2.1.2.2.1.6 | `mac_address` | |
| ifConnectorPresent | IF-MIB | 1.3.6.1.2.1.31.1.1.1.17 | `physical` evidence | Stronger evidence of a front-panel port than ifType. |
| ifStackStatus | IF-MIB | 1.3.6.1.2.1.31.1.2.1.3 | `stack_parent_uid` | Index is (higher ifIndex, lower ifIndex); used for LAG and sub-interface parents. |
| entAliasMappingIdentifier | ENTITY-MIB | 1.3.6.1.2.1.47.1.3.2.1.2 | `member`, `slot`, `port` | Maps an entPhysical port to its ifIndex. Combined with entPhysicalContainedIn/ParentRelPos it gives stack member and slot without parsing names. |
| entPhysicalParentRelPos | ENTITY-MIB | 1.3.6.1.2.1.47.1.1.1.1.6 | `port` position | |
| entPhysicalVendorType / Descr | ENTITY-MIB | .47.1.1.1.1.3 / .47.1.1.1.1.2 | `media` (copper, sfp, sfp_plus, qsfp) | Transceiver cage detection is vendor-specific; vendor profile maps it. Fallback media comes from ifMauType. |

## Port capability — `ne.raw.if.capability` (new; drives expected speed)

| Object | MIB | OID | Canonical field | Notes |
|---|---|---|---|---|
| ifMauType | MAU-MIB | 1.3.6.1.2.1.26.2.1.1.3 | `oper_mau_type` → speed/duplex/media | Index is (ifIndex, mauIndex). Value is an OID from IANA-MAU-MIB, e.g. dot3MauType1000BaseTFD. |
| ifMauTypeListBits | MAU-MIB | 1.3.6.1.2.1.26.2.1.1.13 | `supported_speeds_bps[]` | **verify** column number. |
| ifMauAutoNegAdminStatus | MAU-MIB | 1.3.6.1.2.1.26.5.1.1.1 | `autoneg_enabled` | |
| ifMauAutoNegCapAdvertisedBits | MAU-MIB | 1.3.6.1.2.1.26.5.1.1.10 | `advertised_speeds_bps[]` | What this port offers. **verify** column number. |
| ifMauAutoNegCapReceivedBits | MAU-MIB | 1.3.6.1.2.1.26.5.1.1.11 | `partner_advertised_speeds_bps[]` | What the link partner offered. This works even when the partner is not running LLDP. **verify**. |
| lldpXdot3LocPortAutoNegAdvertisedCap | LLDP-EXT-DOT3-MIB | 1.0.8802.1.1.2.1.5.4623.1.2.1.1.3 | `advertised_speeds_bps[]` fallback | For devices without MAU-MIB. |

The bit positions come from IANA-MAU-MIB (`b10baseT`, `b100baseTXFD`, `b1000baseTFD` and so on). Multi-gigabit bits (2.5G, 5G, 10GBASE-T) are later additions and need checking against each vendor.

**Expected-speed derivation** (proposed default; see decision question 2):

1. A per-port macro `{$NE.IF.EXPECTED_SPEED:"<ifName>"}` always wins.
2. Otherwise, when both ends' capabilities are known (from MAU received bits or the LLDP 802.3 remote table below), expected speed is **the highest speed both ends advertise**. Negotiating below that is a fault: a bad cable, a forced setting or a failing transceiver.
3. Otherwise, when the LLDP peer is a bridge (an inter-switch link) and only local capability is known, expected speed is the local maximum.
4. Otherwise expected speed is `unknown`. An access port with an unidentified endpoint does not go amber just because a 100M printer is plugged into a 1G port.

The same data gives a **two-ended duplex check**: local `duplex` against the remote operational MAU type from `lldpXdot3RemPortOperMauType`.

## LLDP — `ne.raw.lldp`

| Object | MIB | OID | Canonical field | Notes |
|---|---|---|---|---|
| lldpLocPortIdSubtype / Id / Desc | LLDP-MIB | 1.0.8802.1.1.2.1.3.7.1.2 / .3 / .4 | `local_port_id`, `local_interface_uid` | lldpLocPortNum is **not** ifIndex. Map it by subtype (5 interfaceName → ifName, 1 interfaceAlias → ifAlias, 3 macAddress → ifPhysAddress, 7 local → vendor rule). |
| lldpRemChassisIdSubtype / Id | LLDP-MIB | 1.0.8802.1.1.2.1.4.1.1.4 / .5 | `remote_chassis_id` | Index is (timeMark, localPortNum, remIndex). Keep the whole triple. |
| lldpRemPortIdSubtype / Id | LLDP-MIB | .4.1.1.6 / .7 | `remote_port_id` | |
| lldpRemPortDesc | LLDP-MIB | .4.1.1.8 | `remote_port_description` | |
| lldpRemSysName | LLDP-MIB | .4.1.1.9 | `remote_system_name` | |
| lldpRemSysDesc | LLDP-MIB | .4.1.1.10 | `remote_system_description` | Truncated to 255 characters. |
| lldpRemSysCapSupported / Enabled | LLDP-MIB | .4.1.1.11 / .12 | `capabilities` | Bits: other, repeater, bridge, wlanAccessPoint, router, telephone, docsis, station. Spec §15 requires this. |
| lldpRemManAddrIfSubtype | LLDP-MIB | 1.0.8802.1.1.2.1.4.2.1.3 | `remote_management_addresses[]` | The address itself is in the index after the remote triple: (subtype, length, octets). |
| lldpXdot3RemPortAutoNegAdvertisedCap | LLDP-EXT-DOT3-MIB | 1.0.8802.1.1.2.1.5.4623.1.3.1.1.3 | `remote_advertised_speeds_bps[]` | Expected-speed derivation. |
| lldpXdot3RemPortOperMauType | LLDP-EXT-DOT3-MIB | 1.0.8802.1.1.2.1.5.4623.1.3.1.1.4 | `remote_oper_speed_bps`, `remote_duplex` | Two-ended speed and duplex mismatch evidence. |
| lldpXdot3RemLinkAggStatus / PortId | LLDP-EXT-DOT3-MIB | 1.0.8802.1.1.2.1.5.4623.1.3.3.1.1 / .2 | `remote_lag` | Lets the topology group LAG members even when the peer is not monitored. |
| lldpXdot1RemPortVlanId | LLDP-EXT-DOT1-MIB | 1.0.8802.1.1.2.1.5.32962.1.3.1.1.1 | `remote_pvid` | Corroboration only (spec §8, §37: LLDP is not authoritative for VLANs). Enables a native-VLAN mismatch finding. |
| lldpStatsRemTablesLastChangeTime | LLDP-MIB | 1.0.8802.1.1.2.1.2.1.0 | change evidence | Not a per-neighbour timestamp. |
| ifName, ifAlias, ifDescr, ifPhysAddress | IF-MIB | — | join columns | For local port mapping and UID. |

## VLAN — `ne.raw.vlan`

| Object | MIB | OID | Canonical field | Notes |
|---|---|---|---|---|
| dot1dBasePortIfIndex | BRIDGE-MIB | 1.3.6.1.2.1.17.1.4.1.2 | bridge port → interface | Q-BRIDGE bitmaps are by **bridge port**, not ifIndex. Without this join, membership is `unknown`. |
| dot1qVlanStaticName | Q-BRIDGE-MIB | 1.3.6.1.2.1.17.7.1.4.3.1.1 | `vlans[].name` | |
| dot1qVlanStaticEgressPorts | Q-BRIDGE-MIB | 1.3.6.1.2.1.17.7.1.4.3.1.2 | configured members | Port bitmap: first octet MSB = bridge port 1. Decode every octet (stacks exceed 64 ports). |
| dot1qVlanForbiddenEgressPorts | Q-BRIDGE-MIB | 1.3.6.1.2.1.17.7.1.4.3.1.3 | `tagging = forbidden` | |
| dot1qVlanStaticUntaggedPorts | Q-BRIDGE-MIB | 1.3.6.1.2.1.17.7.1.4.3.1.4 | `tagging = untagged` | Egress minus untagged = tagged. |
| dot1qVlanCurrentEgressPorts / UntaggedPorts | Q-BRIDGE-MIB | 1.3.6.1.2.1.17.7.1.4.2.1.4 / .5 | operational membership | Index is (timeMark, vlanIndex). Includes dynamically learned membership (GVRP/MVRP), which the static table lacks. |
| dot1qVlanStatus | Q-BRIDGE-MIB | 1.3.6.1.2.1.17.7.1.4.2.1.6 | `vlans[].state` | 1 other, 2 permanent, 3 dynamicGvrp |
| dot1qPvid | Q-BRIDGE-MIB | 1.3.6.1.2.1.17.7.1.4.5.1.1 | `native_vlan` / access VLAN | Indexed by bridge port. |
| dot1qPortAcceptableFrameTypes | Q-BRIDGE-MIB | 1.3.6.1.2.1.17.7.1.4.5.1.2 | access versus trunk evidence | 2 admitOnlyVlanTagged |
| ifName, ifDescr | IF-MIB | — | join columns | |

**Membership classification**: an interface is `access` when it is an untagged member of exactly one VLAN and a tagged member of none. It is `trunk` when it is a tagged member of one or more VLANs (with a native/PVID untagged VLAN allowed). It is `hybrid` when it is untagged in more than one VLAN. It is `unknown` when the bridge-port join is missing.

**Vendor gaps** (handled by vendor profiles, see [01](01-vendor-capability-matrix.md)):

- Cisco Catalyst exposes trunk state in CISCO-VTP-MIB (`vlanTrunkPortDynamicStatus`, `vlanTrunkPortVlansEnabled` bitmaps by ifIndex, `vlanTrunkPortNativeVlan`) and access VLAN in CISCO-VLAN-MEMBERSHIP-MIB `vmVlan` (1.3.6.1.4.1.9.9.68.1.2.2.1.2). Q-BRIDGE support on IOS is partial. **verify** per platform.
- Some vendors expose Q-BRIDGE bitmaps only up to 4094 VLAN rows or only the current table. The profile records which.

## STP — `ne.raw.stp`

| Object | MIB | OID | Canonical field | Notes |
|---|---|---|---|---|
| dot1dStpProtocolSpecification | BRIDGE-MIB | 1.3.6.1.2.1.17.2.1.0 | `bridge.protocol` | 3 ieee8021d. RSTP and MSTP agents also report here and are told apart by vendor or MSTP tables. |
| dot1dStpPriority | BRIDGE-MIB | 1.3.6.1.2.1.17.2.2.0 | `bridge.priority` | |
| dot1dStpTimeSinceTopologyChange / TopChanges | BRIDGE-MIB | .17.2.3.0 / .17.2.4.0 | `bridge.topology_change` | Counter reset on reboot; compare with sysUpTime. |
| dot1dStpDesignatedRoot | BRIDGE-MIB | 1.3.6.1.2.1.17.2.5.0 | `bridge.root_bridge_id` | 8-octet bridge ID |
| dot1dStpRootCost / RootPort | BRIDGE-MIB | .17.2.6.0 / .17.2.7.0 | `bridge.root_cost`, root port | RootPort 0 means this bridge is root. |
| dot1dBaseBridgeAddress | BRIDGE-MIB | 1.3.6.1.2.1.17.1.1.0 | `bridge.bridge_address` | Own bridge ID = priority + this MAC. |
| dot1dStpPortState | BRIDGE-MIB | 1.3.6.1.2.1.17.2.15.1.3 | `state` | 1 disabled, 2 blocking, 3 listening, 4 learning, 5 forwarding, 6 broken |
| dot1dStpPortEnable | BRIDGE-MIB | .17.2.15.1.4 | `enabled` | |
| dot1dStpPortPathCost / PathCost32 | BRIDGE-MIB / RSTP-MIB | .17.2.15.1.5 / .17.2.15.1.11 | `cost` | Prefer PathCost32 when present. |
| dot1dStpPortPriority | BRIDGE-MIB | .17.2.15.1.2 | `priority` | |
| dot1dStpPortDesignatedRoot / Bridge / Port | BRIDGE-MIB | .17.2.15.1.6 / .8 / .9 | `designated_bridge`, `designated_port` | |
| dot1dStpExtPortOperEdgePort / OperPointToPoint | RSTP-MIB | 1.3.6.1.2.1.17.2.19.1.3 / .5 | `edge`, `point_to_point` | |
| ieee8021MstpCistPortRole and MSTI port tables | IEEE8021-MSTP-MIB | 1.3.111.2.802.1.1.6.1.3 … | `role`, per-instance state | **verify** table and column numbers. MSTP also needs the VLAN-to-instance map (ieee8021MstpVlanTable). |
| dot1dBasePortIfIndex, ifName | BRIDGE-MIB, IF-MIB | — | join columns | STP ports are bridge ports. |

**Port role** is not in BRIDGE-MIB or RSTP-MIB. Where no role table exists, it is *derived* and labelled as derived: the root port is `dot1dStpRootPort`; a port is designated when its designated bridge equals this bridge; a non-forwarding port that is neither is alternate or backup. Otherwise the role is `unknown`.

## LAG — `ne.raw.lag`

| Object | MIB | OID | Canonical field | Notes |
|---|---|---|---|---|
| dot3adAggActorSystemID / PartnerSystemID | IEEE8023-LAG-MIB | 1.2.840.10006.300.43.1.1.1.1.4 / .8 | `actor_system_id`, `partner_system_id` | Indexed by aggregator ifIndex. Partner ID of zeros means no LACP partner. |
| dot3adAggAggregateOrIndividual | IEEE8023-LAG-MIB | .43.1.1.1.1.5 | aggregate flag | |
| dot3adAggPortSelectedAggID / AttachedAggID | IEEE8023-LAG-MIB | 1.2.840.10006.300.43.1.2.1.1.12 / .13 | `members[].selected`, membership | Indexed by member ifIndex. 0 means not attached. |
| dot3adAggPortActorOperState / PartnerOperState | IEEE8023-LAG-MIB | .43.1.2.1.1.21 / .23 | `members[].collecting`, `distributing`, `lacp_active` | Bit string: activity, timeout, aggregation, synchronisation, collecting, distributing, defaulted, expired. |
| ifStackStatus | IF-MIB | 1.3.6.1.2.1.31.1.2.1.3 | static LAG membership | Static bundles often have no dot3ad rows; ifStack (ifType 161 parent) still shows members. Mode is then `static`. |
| ifName, ifType, ifOperStatus | IF-MIB | — | join columns | |

Cisco EtherChannel without LACP: CISCO-PAGP-MIB (1.3.6.1.4.1.9.9.98) **verify**.

## Enrichment (phase 6, not polled by default)

| Dataset | Sources |
|---|---|
| PoE | POWER-ETHERNET-MIB pethPsePortTable 1.3.6.1.2.1.105.1.1.1 (indexed by group and port, not ifIndex, so it needs entity or vendor mapping); CISCO-POWER-ETHERNET-EXT-MIB 1.3.6.1.4.1.9.9.402 |
| Optics (DOM) | ENTITY-SENSOR-MIB entPhySensorTable 1.3.6.1.2.1.99.1.1.1 linked through entPhysicalContainedIn; CISCO-ENTITY-SENSOR-MIB 1.3.6.1.4.1.9.9.91; vendor-specific elsewhere |
| MAC/endpoints | Q-BRIDGE dot1qTpFdbTable 1.3.6.1.2.1.17.7.1.2.2; IP-MIB ipNetToPhysicalTable 1.3.6.1.2.1.4.35 |

## Where native collection is not enough

**Superseded in part:** this table first assigned these gaps to the Python proxy collector. That collector is now frozen on schema 1.0 and will not collect VLAN or STP, so the gaps below belong to a future, separately designed acquisition agent ([roadmap](../network-explorer/ROADMAP.md#future-acquisition-agent)). The gaps themselves still stand.

| Gap | Why native fails | Fallback |
|---|---|---|
| Cisco per-VLAN STP and BRIDGE-MIB (PVST+) | Data lives in per-VLAN SNMP contexts (`vlan-<id>` for v3, `community@<id>` for v2c). A Zabbix SNMP interface has one fixed context. | Future acquisition agent iterates the VLAN list and merges into one canonical STP snapshot. |
| Walks too large for one item value | Very large stacks with full VLAN bitmaps can exceed the text value or preprocessing budget. | Future acquisition agent shards by member or VLAN range under a manifest (design §4). To be measured with real walks first. |
| Agents that time out on large bulk walks | Some older switches fail GETBULK with high repetitions. | Tune `max_repetitions` per interface first; future acquisition agent only if evidence shows it is necessary. |

Every fallback row needs a captured walk showing the problem before a non-native acquisition path is enabled for a profile.
