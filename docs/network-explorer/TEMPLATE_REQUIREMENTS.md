# Template rebuild requirements

Status: implementation specification for shared contracts and vendor profile development; model support requires inventory/fixture evidence. Scope follows the user's request to rebuild existing SNMP templates from the ground up for Zabbix 7.0–7.4 and Network Explorer.

## 1. Goals

Fleet context: 190+ switches, 10+ vendors and about 8–9 models per vendor. No existing template exports, inventory or SNMP fixtures are currently available. This specification defines what must be collected and qualified; it does not assume a live environment connection. Use customer-neutral names in every build artefact.

Build reusable templates that provide the module's canonical data while maintaining the useful monitoring currently supplied by existing vendor templates. Rebuilding does not mean dropping CPU, memory, power, fan, temperature, availability or inventory coverage unnoticed. Separate required Network Explorer capabilities from monitoring/enrichment supported by each model.

Native SNMPv2c and SNMPv3 interfaces are first-class acquisition paths. Python external checks on the assigned proxy cover justified exceptions. The frontend must see the same contract for either path. Do not require a Python collector for devices fully covered by native acquisition. Reserve an agent-ingestion contract for future use without making it a first-release deployment dependency.

## 2. Template decomposition

Common templates own identity, interfaces, LLDP, LAG, VLAN, STP and quality contracts. Vendor profiles select model/firmware/context handling. Optional hardware-health and enrichment templates own CPU/memory/environment/PoE/optics. A dashboard template supplies inherited host dashboards. All producers use the `ne.*` keys documented in `DESIGN.md`.

Do not create a complete independent template for every model unless its acquisition differs. A profile can cover several models only with evidence that OIDs, joins, enum semantics and layouts agree. Profiles identify supported firmware families, capability coverage and tested fixtures; unsupported fields remain null with reasons.

Native and fallback variants must not coexist as producers for identical keys on one host. An import/provisioning preflight checks duplicate item keys, overlapping LLD, unsupported macro references, missing parent links, unavailable custom widgets and conflicts with existing templates. Define migration names/UUID ownership before exporting the first production bundle.

## 3. Vendor backlog supplied by the user

| Family | Profile discovery tasks | Initial status |
|---|---|---|
| Cisco SBS / small-business switches | Confirm exact product families: legacy SF/SG, Cisco Business/CBS or other models; test LLDP port IDs, VLAN/bridge tables, LAG and stack support | Inventory required; do not map all to Catalyst |
| Cisco Catalyst | Split IOS/IOS-XE and other platforms where evidenced; inspect stack numbering, LLDP identities, EtherChannel, per-VLAN contexts and STP variants | Inventory and firmware evidence required |
| Dell PowerConnect legacy | Enumerate models/firmware; compare standard versus vendor VLAN, LAG and STP behaviour | Inventory required |
| Dell N-Series | Identify OS/version, stacking and bridge-port mappings; verify capability matrix independently of legacy PowerConnect | Inventory required |
| Dell S-Series | Identify networking OS and platform family; evaluate contexts, multi-chassis aggregation and supported sensor MIBs | Inventory required |
| Zyxel | Confirm managed switch product families, VLAN table semantics, port numbering and LLDP mapping | Inventory required |
| Netgear | Separate managed/smart families; test table completeness, LAG, stacking and STP instance visibility | Inventory required |
| Ubiquiti | Separate UniFi/EdgeSwitch/other families; record SNMP fields actually exposed and mark controller-only configuration unavailable | Inventory required |
| Other vendors | Add profiles only through the same inventory/fixture qualification process | Capability-driven generic fallback |

No entry in this table is a claim of implemented support. A vendor marketing name or sysObjectID match does not guarantee full capabilities. Prioritise models by fleet share and operational importance, then select two distinct vendors for the first integration gate.

## 4. Required discovery inventory

Assign a stable customer/network-domain namespace and record proxy separately. Repeated management IPs in different isolated domains are permitted; duplicates in one domain are conflicts. Require globally unique technical and visible host names, preserving repeated device-reported names only as source metadata. Matching, discovery candidates and reports are domain-qualified. A proxy does not replace user/group access permissions.

Per monitored device export: technical/display host name, vendor, exact model, firmware, chassis/stack members, sysObjectID, assigned proxy/site/routing domain, SNMP version and enabled algorithms by name only, template names/versions, existing interface item/discovery method and macro policies. Include capability probe results with date/firmware and read-only SNMP views/context restrictions. Do not export communities, users' secret values, auth/privacy passwords or raw credential macros.

Each qualification fixture contains sanitised numeric-OID walks for system/ENTITY/IF/LLDP/BRIDGE/LAG and later VLAN/STP. Preserve OID indices, binary values, identifier subtypes and meaningful joins while replacing names/IPs/MACs/serials consistently. Include incomplete/time-out/reboot/renumbered variants and SNMPv3 context details without credentials.

Existing template exports are treated as reference data to catalogue coverage, not trusted executable instructions or a mandate to preserve every poll. Review any scripts/URLs before running them. The coverage comparison identifies each metric/trigger as retained, replaced, redundant, unsupported or explicitly deferred.

Use the supplied header-only `VENDOR_INVENTORY.csv`, `CAPABILITY_MATRIX.csv` and `MONITORING_COVERAGE.csv` as intake/qualification formats. Capability values are `supported`, `partial`, `unsupported` or `unknown`; an untested model is `unknown`. Qualification values are `unqualified`, `fixture-tested`, `lab-tested` and `field-validated`. Coverage dispositions are `retained`, `replaced`, `redundant`, `unsupported` or `deferred`, with an explicit reason and impact. Do not place secret values in these files.

## 5. Mandatory acquisition and normalisation contracts

### Device/base

- Read identity and uptime; derive vendor/profile from documented sysObjectID evidence and corroboration.
- Support stack/member identities, serial/firmware when exposed, and multiple management address candidates.
- Publish collection/capability/schema versions and quality with no credentials.
- Detect uptime discontinuity/reboot and firmware change to reassess mappings and capabilities.

### Interfaces

- Collect ifTable/ifXTable efficiently through table masters; use ifHighSpeed and ifSpeed with documented unit/overflow rules.
- Discover physical and logical interfaces, mapping chassis/member/slot/port where exposed.
- Separate inventory from fast state; carry current ifIndex and stable identity evidence.
- Derive admin/oper/speed/duplex and optional counter rates using discontinuity-aware preprocessing.
- Support high-capacity counters; do not fabricate a rate after reset or wrap.
- Exclude logical interfaces from physical geometry while retaining them for LAG/bridge relationships.
- Match expected-speed/duplex policies explicitly; unknown intent cannot trigger an anomaly.

### LLDP

- Parse local tables and remote compound indices, including time marks and multiple peers.
- Preserve local/remote port ID and chassis ID subtypes; map to interfaces using tested evidence.
- Preserve unresolved endpoints, management address multiplicity and collection age.
- Avoid embedding globally resolved privileged host metadata in source-host snapshots.

### LAG

- Discover logical aggregator and member interfaces, modes and current member state where exposed.
- Preserve individual member LLDP observations and actor/partner evidence.
- Never match peers solely because local LAG numbers are equal.
- Represent multi-chassis/stack endpoints without inventing a single chassis identity.

### VLAN, subsequent milestone

- Map bridge ports to ifIndex; decode all bitmap bytes, not only the first 64 ports.
- Preserve static/current membership distinction, tagged/untagged/PVID/native/forbidden evidence.
- Record context/bridge domain and avoid guessing access/trunk solely from one observed VLAN.
- Publish capability limitations, missing tables and configuration/operational uncertainty.

### STP, subsequent milestone

- Preserve protocol, instance/region and VLAN mappings; role/state remain distinct.
- Read root/designated bridge/port, cost/priority and topology-change evidence where available.
- Never claim per-VLAN forwarding where instance mapping or port state is missing.

## 6. Timing, completeness and load

Use the polling defaults from `DESIGN.md`, configurable through macros or supported schedules. Publish success heartbeats even when snapshots are unchanged. Limit raw-walk retention; partition oversized datasets with completeness manifests. Evaluate dependency fan-out and LLD cost on representative 24/48-port and stack devices.

Normalisation must not wait for unrelated datasets: missing VLAN data does not erase interfaces or LLDP. Incomplete inventory never causes mass LLD removal. SNMP authentication failure and timeout are collection faults; noSuchObject/end-of-MIB require context-aware interpretation before marking capability unsupported.

Budget per profile: collection duration, request count/size, timeout/retry, proxy CPU, preprocessing work, dataset bytes and dependent-item count. Bounds are measured during qualification; a template cannot claim production readiness from successful import alone.

## 7. Monitoring and trigger requirements

Mandatory Explorer health: schema mismatch, stale/failed collection, unexpectedly down interface with an explicit monitored-port policy, persistent known speed/duplex degradation and LAG selected-member degradation where supported. Preserve uptime/device availability from existing monitoring or the rebuilt base template.

Hardware health is capability-dependent: CPU, memory, temperature, fans, PSU redundancy, stack-member presence, sensor alarms, PoE budget and optical thresholds. Use device-reported sensor status and per-model units where appropriate. Missing sensors are unsupported, not healthy.

Trigger expressions have persistence/hysteresis, maintenance behaviour and dependencies on device/collection availability. Disable low-value unused-port alerts by policy; do not inherit every existing alarm without assessing intent. Native problems and the custom widget's colour rules share scalar facts but serve different purposes.

Use per-interface context macros based on escaped original stable names where compatible; validate macro resolution in both PHP policy reads and template expressions. Item keys use opaque UID tokens. Alert labels include current interface name, source and expected/actual values. Preserve recovery behaviour and distinguish stale evidence from cleared problems.

## 8. Dashboards and assets

Initial delivery is manual copy-out archives plus import instructions. Choose actual frontend/proxy paths from installation configuration, and provide container bind-mount examples. Python collector dependencies use a dedicated environment and can include an offline wheelhouse. An apt package is optional later work. Template exports have no real customer branding, credentials or hard-coded instance IDs.

Required inherited host pages: Overview, Connectivity and Diagnostics for the first release. Later VLAN/STP pages require their capability modules. Custom Port Panel/Topology/Interface Detail/Quality widgets use inherited host context; native graphs/problems use template item/graph references rather than instance-specific item IDs.

Dashboard artefacts must import and display on each supported Zabbix version. Use a compatibility exporter or version-specific generated exports if schema differences require it; never label a 7.4-only export as 7.0 compatible without testing. Stable source definitions generate YAML and dashboard API recipes deterministically.

Template import dependencies are explicit: common value maps/templates, vendor profiles, module registration, dashboard assets, then optional fleet provisioning. Unavailable optional widget modules produce a preflight failure rather than a silently broken dashboard. Ship an optional native-only diagnostics dashboard for staged deployments if needed.

## 9. Release qualification

For each profile record:

1. Vendor/model/firmware and SNMP v2c/v3/context coverage.
2. Standard/vendor OID sources and all transformation rules.
3. Fixture provenance and expected canonical outputs.
4. Tested Zabbix release/patch and proxy/Python platform where fallback is used.
5. Supported/partial/unsupported capabilities with reasons.
6. Successful template import, polling, preprocessing, LLD and trigger/recovery checks.
7. Dashboard/peer-navigation and permission checks.
8. Polling cost, size limits, restart/renumbering/partial-response behaviour.
9. Migration comparison and retained/deferred monitoring list.

Badges: `fixture-tested`, `lab-tested`, `field-validated`. A synthetic fixture alone cannot promote a profile to field-validated. Generic standard-MIB support provides a useful baseline; model-specific capability claims wait for evidence.

## 10. Migration and autonomous build rules

Export current templates/dashboards before rollout. Build new namespaced templates side by side in the lab; never rewrite the user's current production templates in place. Map legacy items/graphs/alerts to new ownership and identify dependencies in actions/services/reports. Linking a replacement can reset LLD identities/history; document impacts rather than claiming automatic historical migration.

Canary selection includes two vendors, a stack and a relevant proxy. Compare values and alert/recovery behaviour before expanding. Existing template unlink, unlink-and-clear, dashboard replacement and host auto-enrolment require explicit deployment scope; retain rollback exports. No production changes are authorised by this planning request.

When evidence is missing, implement shared schemas/parser contracts and fixture harnesses; leave the vendor adapter explicitly unqualified. Do not invent OIDs, simulate unsupported fields as healthy or wait for every vendor before completing independent shared work.
