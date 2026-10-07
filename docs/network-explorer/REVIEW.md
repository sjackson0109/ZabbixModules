# Review of the first design and alpha build against the requirements specification

Reviewed 7 October 2026 against *Zabbix Network Explorer — Requirements Specification* (draft for build planning) and the `work` branch at `73248a0`.

## Verdict

The earlier agent understood the **architecture** very well, but it **inverted the build order** the specification asks for and **narrowed the release scope**. The result is a well-tested frontend running on synthetic replay data, with no path yet from a real switch into Zabbix.

- Architectural understanding: strong. Zabbix stays authoritative, data is per host, the frontend is vendor-neutral, freshness is a first-class state, unresolved peers are kept, the management subnet is an annotation and not a filter, LAG groups member links, and ifIndex is never treated as identity. All of this matches spec §2, §4, §7, §12, §18, §23, §30 and §37.
- Process: the spec (§40) says to produce seven design artefacts and have them reviewed *before* implementation. The agent wrote a dense design pack and then built a frontend, PHP services, a Python collector and lab harnesses. The artefacts that most depend on the real estate (inventory and capability matrix) are empty CSV headers.
- Scope: VLAN and STP were deferred to later releases. Spec §35 lists VLAN selection, tagged/untagged, VLAN propagation and the STP overlay (criteria 10–13) as part of the *first production-capable release*. `DECISIONS.md` records this deferral as a user decision; it needs reconfirming because it contradicts the spec and the project brief.

The existing checks all pass when re-run (50 Python tests, 92 PHP checks, 7 JavaScript tests).

## What matches the specification

| Spec | Status in the repository |
|---|---|
| §2 Zabbix authoritative, no parallel database | Met. Each host owns its datasets as text items; the graph is derived at read time. |
| §4 LLDP, unresolved peers retained | Met in design and services. Subtype-aware local port mapping is specified; compound LLDP indices are preserved. |
| §5 Peer navigation and remote highlight | Implemented and browser-tested on synthetic hosts (URL fragment context). |
| §7 Out-of-subnet peers stay visible and are flagged | Implemented in `SubnetService` and the topology widget. |
| §12 LAG as a logical grouping | Implemented (grouping keeps member links). Mode and per-member state are missing from the schema. |
| §14 ifIndex not identity | Met. A name-based SHA-256 UID is used; ifIndex is a locator. |
| §18 Vendor abstraction | Met. No vendor logic in the frontend. |
| §23 Freshness states | Met. `current/stale/unknown` plus `ok/partial/failed/unsupported` are separate dimensions, and failed attempts never overwrite the last good snapshot. |
| §30 Security | Strong. Permission-filtered reads, no privileged API token, CSV formula escaping, LLDP raw-item disclosure risk called out. |
| §31 Failure handling | Designed thoroughly; partially exercised with synthetic failures. |

## What is misunderstood, weak or missing

### 1. No real SNMP acquisition exists (critical path)

Spec §19 and §22 prefer native Zabbix SNMP table walks feeding dependent items. The repository contains **no SNMP template at all**. The only templates are `Network Explorer LAB replay` (trapper items fed by `zabbix_sender`). Every production template is deferred until vendor evidence arrives, even the vendor-neutral standard-MIB parts (IF-MIB, LLDP-MIB, IEEE8023-LAG-MIB, Q-BRIDGE-MIB, BRIDGE-MIB) that could be built and tested against a simulated agent today. Meanwhile the *fallback* path (Python collector) was built first. That is the reverse of the spec's stated priority.

Consequence: acceptance criteria 1–4 cannot be demonstrated against any real switch.

### 2. The §40 artefacts are scattered, and two are empty

| §40 artefact | Where it lives today | Gap |
|---|---|---|
| 1. Vendor capability matrix | `CAPABILITY_MATRIX.csv` | Header only. No tooling exists to gather the inventory from an existing Zabbix. |
| 2. Canonical schema | `schemas/envelope.schema.json` | Covers device, interfaces, LLDP and LAG only. No VLAN or STP. Missing spec fields: device `serial`; interface `last_change` and media (copper/SFP); LLDP `capabilities` and `local_ifIndex`; LAG `mode` and per-member state. |
| 3. Template architecture | `DESIGN.md` §8, `templates/specifications/` | Reasonable, but VLAN/STP templates are a one-paragraph placeholder. |
| 4. SNMP acquisition matrix | `DESIGN.md` §5, `templates/contract.json`, `oids.py` | High-level table only. No per-object matrix with Zabbix item type, master/dependent split, interval and cost. Nothing for VLAN, STP, MAU (port capability) or the LLDP 802.3 extension (remote speed/duplex). |
| 5. Proxy script architecture | `collector/README.md` | Done (Python, user-approved instead of the spec's shell sketch). |
| 6. Frontend module architecture | `DESIGN.md` §9 | Done, but see 4 and 5 below. |
| 7. Test plan | `BUILD_PLAN.md` §4 | Done in prose; not traced test-by-test to spec §34. |

### 3. Expected speed defaults to "unknown", so amber never appears out of the box

The design makes expected speed come only from a per-interface macro. With nothing configured, a 1 Gbps port negotiating 100 Mbps shows as normal. That undermines criterion 3 (reduced speed visibly distinguishable) and sits awkwardly with criterion 16 (no manual port data for normal operation). Spec §3.2 asks to *derive* expected speed where SNMP supports it. Candidate derivations not considered: MAU-MIB advertised/supported capability, the LLDP 802.3 extension (peer's advertised capability and operational MAU type, which also enables a true two-ended duplex-mismatch check), and the port's media type.

### 4. Port Panel is missing the semantic layer switch and configurable colours

Spec §9 and §25 require the Port Panel to switch between Physical, VLAN, STP and LLDP layers. Spec §3.1 requires configurable colour rules. Neither exists; the widget form only offers a layout choice.

### 5. Topology layout will not scale to ~300 switches

`graphLayout` places nodes in a breadth-first grid with straight lines. That is not an automatic graph layout, and at 300 nodes it produces a dense lattice of crossing lines. The design names Cytoscape.js but the build does not use it. Scale testing (§27, §34) has not been done.

### 6. Maintainability

The same 350-line, densely formatted `runtime.js` and the same CSS are copied into all five widgets. Zabbix needs each widget to ship its own assets, but the copies should be generated from one source at package time rather than committed five times.

### 7. Over-specification in prose

The design documents are accurate but very dense; much of the content restates caveats. That makes the §40 review step harder for a human reviewer. The new artefacts in `docs/design/` aim to be short and tabular.

## What is worth keeping

Nearly all of it. The canonical envelope, freshness model, permission model, identity rules, PHP services, peer navigation and the lab harness are sound and tested. The work needed is to add the missing acquisition layer, complete the schema to the full spec model, and restore VLAN/STP to the release, rather than to restart.

## Recommended next steps

1. Complete the seven §40 artefacts in `docs/design/` (this branch).
2. Provide a read-only inventory export from the existing Zabbix plus a safe SNMP walk-capture script, so the vendor/model matrix (§33, §40) can be filled with evidence.
3. After review: build generic standard-MIB native templates (`walk[]` master items + JavaScript preprocessing to the canonical model) and test them against simulated agents built from captured walks.
4. Then extend the frontend: semantic layers, VLAN selector, configurable colours, a real graph layout.
