# Discovery implementation specification

Discovery has three distinct jobs. Keep their owners, schedules, permissions and failure handling separate.

## Device enrolment

Use administrator-supplied ranges, SNMP credential bindings and a selected site proxy for Zabbix network discovery. Probes are bounded read-only checks for sysObjectID/sysName/sysDescr/sysUpTime and capability hints; SNMPv2c and v3 are native Zabbix interfaces. A Python fallback does not inherit interface credentials: bind a protected proxy-local configuration reference, never pass communities/auth/privacy keys in item parameters or logs.

Default mode produces a candidate report only. It does not sweep ranges without deployment scope, auto-create hosts, open firewall paths or link/unlink templates. If later authorised, a preflight enrolment proposal resolves an explicit network_domain, proxy and host groups, generates globally unique technical/display names, detects duplicates within that domain, and proposes the qualified profile and compatible templates. LLDP neighbours add candidate observations, not executable probe targets.

Repeated IPs across isolated domains are allowed. Within-domain duplicate management addresses are review blockers. sysName may repeat; preserve it as source metadata rather than overwriting Zabbix's globally unique host/name. Proxy ID is a routing attribute; changing a proxy must not alter identity/domain or grant access. Missing domain assignment means reconciliation remains unresolved.

Required candidate report columns: candidate ID, domain/site, source proxy/seed host, observed addresses/identifiers, system name, first/last observation, profile hypothesis, confidence/reasons, conflicts, requested probes, approval/provisioning state. Candidate deduplication is domain-qualified; addresses alone do not merge devices. Scope reports to the requesting user's visible sources; restricted source metadata must not appear in exports/counts.

## Within-device low-level discovery

Only complete valid inventory snapshots drive interface LLD. Inventory and fast interface state have independent cadence; a failed collection cannot translate to an empty successful discovery payload. One Interfaces owner discovers both physical and logical interfaces with stable UID macros and filter policies. A stack/member discovery may enrich geometry after demonstrated ENTITY/vendor joins. Adapter identity ambiguity blocks reconciliation and is shown as a quality finding.

LAG discovery is optional for scalar/graph monitoring; canonical membership remains bulk data. Do not create every possible VLAN×port or STP×VLAN item. Later VLAN/STP LLD exists only for required scalar health facts; their bulk relationships stay snapshots. Discovery of capabilities must not make unsupported sensors look healthy. Remove missing entities only after complete-success evidence and the grace policy in CONTRACT.md.

Required tests: unchanged/added/removed interface; ifIndex renumbering; name collision; stack member removal/return; partial empty inventory; unsupported capability; frontend view of retained stale ports; collector restart/cache replay; 7.0/7.2/7.4 lost-resource behaviour. Observe native preprocessing/LLD queues, generated item count and time-to-discovery at representative scale.

## Across-device relationship reconciliation

Templates publish LLDP and LAG evidence. The module resolves it at read time among permitted hosts in the same declared domain: unique exact chassis identity, unique domain-qualified management address, then corroborated system identity. Hostname alone is insufficient. Preserve unresolved/ambiguous peers and confidence rather than selecting arbitrary matches.

Remote port matching respects subtype and qualified adapter equivalences. Both-direction observations may merge into one edge when identities agree; one-sided evidence stays valid with confidence/freshness. LAG groups keep individual cable observations. Discovery does not make a business-service dependency, infer VLAN forwarding or prove packet reachability.

Strict privacy review includes raw snapshot/item history, not just widget output. Treat neighbour text as untrusted display data; spreadsheets escape formula prefixes. A hidden monitored peer must not be reclassified and exposed as an external unmonitored peer. Default redaction/undisclosed-node behaviour remains until an approved metadata boundary policy is present.

## Future production provisioning boundary

Create an idempotent proposal file with resolved ownership markers, diff and rollback exports before writes. Verify existing names, template-key conflicts, module registration, host groups and domain tags. Network-discovery actions, scheduled probes, host creation, credential bindings and production service rules remain an administrator-deployed change. Read-only page requests never create hosts/services or perform SNMP checks. Future agent ingestion follows the same owning-host schema and cannot enrol neighbours or execute arbitrary commands.
