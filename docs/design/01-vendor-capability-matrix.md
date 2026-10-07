# 01 — Vendor capability matrix

Status: **hypotheses only, for review** (spec §32, §33, §40.1). No vendor or model in this document has been verified. The spec says not to assume support without confirming SNMP/MIB behaviour, so every cell below is a *hypothesis to test* against a captured walk. The evidence record is [`docs/network-explorer/CAPABILITY_MATRIX.csv`](../network-explorer/CAPABILITY_MATRIX.csv), which is filled only from evidence.

## How the matrix gets filled

| Step | Tool | Output |
|---|---|---|
| 1. Inventory the estate | `tools/inventory/export_inventory.py` (read-only Zabbix API) | Per-host CSV and per vendor/model/firmware summary: SNMP version, proxy, current templates, and which datasets existing templates already poll (and whether those items work) |
| 2. Choose representatives | Manual: one device per vendor × model × major firmware, prioritising the largest host counts, plus one stack, one 48-port, one with SFP+ uplinks | Capture list |
| 3. Capture walks | `tools/inventory/capture_walk.py` (read-only bulk walks of the standard subtrees in [04](04-snmp-acquisition-matrix.md), optional sanitising) | `.snmprec` file and manifest per device |
| 4. Classify | Walk classifier (next build step) reads each `.snmprec` and records, per dataset, *present with rows*, *present but empty*, *absent* or *capture failed* | One `CAPABILITY_MATRIX.csv` row per model and firmware |
| 5. Qualify | Simulated agent replay through the real templates in the lab (spec §34) | `qualification_level`: `walk-observed`, `lab-replayed`, `field-validated` |

Capability values: `yes` (rows present and joins verified), `partial` (present but a join or column is missing; the limitation is recorded), `no` (completed walk shows the subtree absent), `unknown` (not captured yet). `unknown` is the starting state for every model.

## Families to inventory

These are the families recorded in `DECISIONS.md` from the earlier conversation (190+ switches, 10+ vendors). The enterprise number lets the inventory export group hosts before models are known.

| Family | Enterprise (sysObjectID prefix) | Hypothesis for standard MIBs | Vendor MIBs likely needed | Known risks to check |
|---|---|---|---|---|
| Cisco Catalyst (IOS, IOS-XE) | 1.3.6.1.4.1.9 | IF-MIB yes; LLDP-MIB only when `lldp run` is configured; IEEE8023-LAG-MIB for LACP | CISCO-VTP-MIB and CISCO-VLAN-MEMBERSHIP-MIB (VLANs), CISCO-STP-EXTENSIONS-MIB (roles), CISCO-CDP-MIB (neighbours), CISCO-PAGP-MIB, CISCO-STACKWISE-MIB | Q-BRIDGE is incomplete on IOS. STP and BRIDGE-MIB are per-VLAN contexts (PVST+), which needs the proxy collector. Many Cisco estates run CDP rather than LLDP. |
| Cisco Small Business (SG/CBS) | 1.3.6.1.4.1.9.6.1 | IF-MIB, LLDP-MIB, Q-BRIDGE-MIB, BRIDGE-MIB and RSTP-MIB generally present | CISCOSB-* (stack, PoE, port mode) | LLDP local port subtype may be `local` (7) and need a profile rule. Stack member numbering in ifName. |
| Dell PowerConnect (legacy) | 1.3.6.1.4.1.674.10895 | IF-MIB, Q-BRIDGE-MIB; LLDP-MIB on later firmware | Dell-Vendor-MIB, RADLAN-* on Marvell-based models | Older firmware may lack ifXTable fields (ifAlias, ifHighSpeed). Mixed-generation fleet. |
| Dell N-Series (N1500/N2000/N3000) | 1.3.6.1.4.1.674.10895 | FASTPATH-based; IF-MIB, LLDP-MIB, Q-BRIDGE-MIB, IEEE8023-LAG-MIB expected | FASTPATH-SWITCHING-MIB, DNOS-* | Port-channel ifIndex range differs from PowerConnect. Must be split from PowerConnect by full sysObjectID, not just the enterprise prefix. |
| Dell S-Series (OS9 / OS10) | 1.3.6.1.4.1.6027 (OS9), 1.3.6.1.4.1.674.11000.5000 (OS10) | IF-MIB, LLDP-MIB; Q-BRIDGE varies by OS | FORCE10-* (OS9), DELLEMC-OS10-* (OS10) | Two different operating systems under one family. VLT (multi-chassis LAG) needs representing as one LAG to two peers. |
| Zyxel (GS/XGS) | 1.3.6.1.4.1.890 | IF-MIB, LLDP-MIB, Q-BRIDGE-MIB on managed lines | ZYXEL-* per model | Smart-managed lines may expose a reduced set. Per-model private MIB trees. |
| Netgear (M4300/M4250 and smart switches) | 1.3.6.1.4.1.4526 | M-series is FASTPATH-based with good standard coverage; smart-managed models are much thinner | NETGEAR-SWITCHING-MIB (FASTPATH) | Smart switches may lack LLDP over SNMP or Q-BRIDGE. |
| Ubiquiti (UniFi switches, EdgeSwitch) | 1.3.6.1.4.1.41112 (UniFi), 1.3.6.1.4.1.4413 (EdgeSwitch, Broadcom FASTPATH) | EdgeSwitch: FASTPATH-like coverage. UniFi: IF-MIB yes; LLDP and Q-BRIDGE uncertain | UBNT-* | UniFi SNMP is configured from the controller. VLAN data may be available only from the controller API, which would need an agreed exception to the SNMP-only rule. |
| Others (not yet named) | from inventory | unknown | unknown | Use the generic standard-MIB profile and show missing datasets as unsupported until evidence exists. |

## Profile model

A **profile** is one vendor × model range × firmware range that behaves the same. It is selected by sysObjectID (and a firmware pattern from sysDescr when needed). It contains only *differences* from the generic standard-MIB templates:

- which datasets it supports (capability flags),
- which vendor tables replace or supplement a standard table (for example Cisco VTP for VLANs),
- local-port mapping rules for LLDP subtype 7,
- the port panel geometry (front-panel layout, media per port range),
- SNMP tuning (`max_repetitions`, timeouts),
- whether a dataset needs the proxy collector, with the evidence for that.

Profiles never change the canonical model. The frontend never sees a profile name except as a label in Data Quality (spec §18).

## Additional relationship source: CDP

Spec §6 allows "additional vendor-specific relationship data where necessary". In Cisco estates that do not run LLDP everywhere, CISCO-CDP-MIB `cdpCacheTable` (1.3.6.1.4.1.9.9.23.1.2.1.1) gives the same neighbour facts. The proposal is to normalise CDP into the same `lldp` dataset with `protocol: cdp` and `source.adapter = cisco-cdp`, so the topology treats both the same way. This is only worth building if the inventory shows Cisco links without LLDP.
