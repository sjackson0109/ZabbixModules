# Interfaces capability: collection and qualification

Implement the common Interfaces owner once, then qualify adapters against vendor/model/firmware evidence. See [the shared contract](CONTRACT.md) for item/UID/macro semantics. Interface inventory is required for the initial build; PHY geometry and expected intent are qualified enrichment.

## Candidate standard objects

IF-MIB candidates: `ifNumber` `.1.3.6.1.2.1.2.1.0`; ifTable columns ifIndex `.2.2.1.1`, ifDescr `.2`, ifType `.3`, ifMtu `.4`, ifSpeed `.5`, ifPhysAddress `.6`, ifAdminStatus `.7`, ifOperStatus `.8`, ifLastChange `.9`, ifInErrors `.14`, ifOutErrors `.20`, and discards `.13`/`.19`, all under `.1.3.6.1.2.1` where abbreviated. ifXTable root `.1.3.6.1.2.1.31.1.1.1`: ifName `.1`, HC in/out octets `.6`/`.10`, ifHighSpeed `.15`, ifConnectorPresent `.17`, ifAlias `.18`, ifCounterDiscontinuityTime `.19`. Verify the actual columns in the fixture; ifAlias is not interface identity.

Use table masters (`walk[]` on a configured SNMP interface) and dependent normalisation where practical. Include ifNumber and sysUpTime evidence to detect truncated/rebooted collections. A full row-count match does not prove every needed column is present: require mandatory column coverage per row, reject duplicate OIDs/indices and record optional gaps. A restricted SNMP view can expose an apparently complete smaller table; document this limitation and administrator-approved view.

ifHighSpeed is in millions of bits/s; ifSpeed is bps and may saturate at 4,294,967,295. Prefer usable ifHighSpeed where trustworthy; zero/overflow/missing values remain unknown when no reliable fallback exists. EtherLike-MIB dot3StatsDuplexStatus candidate `.1.3.6.1.2.1.10.7.2.1.19` maps 1 unknown/2 half/3 full. Do not infer negotiated duplex from interface name or speed.

## Normalised rows and physical geometry

Publish uid, current ifIndex, name/description/type, nullable physical evidence, admin/oper, nullable speed/duplex/MTU/MAC, and an optional intended speed with provenance. Preserve stack/member/slot/port identities when exposed; ENTITY-MIB and vendor tables are candidate enrichments requiring demonstrated joins. IfConnectorPresent is stronger physical evidence than ifType. Logical aggregates (ifType161), VLAN/tunnel/loopback interfaces remain in data with generic geometry excluded. Unknown models use grouped rows; no fabricated front-panel position.

Inventory 1h and state60s may share raw data in a measured adapter but must keep discovery correctness and age explicit. Reboot/stack renumbering updates ifIndex while stable names retain UIDs; names repeated across members require member-scoped evidence or partial identity failure. A duplicate/absent identity must not trigger wholesale rediscovery from uncertain rows.

## Required tests and outputs

Fixtures: 24/48-port, stack, logical LAGs, disabled/unused/10G/high-capacity ports, absent ifName, ambiguous names, renamed port, ifIndex renumbering, reboot during walk, row-count mismatch, missing mandatory columns, v2c/v3 restricted view, counter wrap/discontinuity. Assert exact canonical rows, complete/partial outcomes, LLD non-removal on partial, scalar history continuity only for stable identity, and all alert/recovery predicates with unknown expectation.

Qualify native polling and Python fallback independently. Measure master bytes, table request count, SNMP execution duration, proxy CPU and preprocessing fan-out; no per-port SNMP request on a widget action. Release outputs: deterministic version-specific YAML, normaliser tests, scalar/graph prototypes, coverage comparison, capability matrix and before/after renumbering evidence. Synthetic fixtures qualify parser behaviour only.
