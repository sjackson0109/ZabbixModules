# Shared production template implementation contract

Status: ready for family-specific implementation and qualification. This document is a specification, not a claim that device polling works.

## Template ownership and linking

Use capability templates named `Network Explorer Base`, `Network Explorer Interfaces`, `Network Explorer LLDP`, and `Network Explorer LAG`, plus `Network Explorer Host dashboards`. Later add VLAN/STP and optional Hardware Health/PoE/Optics. A family profile selects supported producers and documented overrides; it does not duplicate common keys. A deployable family bundle links each owner once. Test template inheritance for duplicate keys before import, including diamond inheritance. Native and Python external-script variants cannot coexist for the same dataset on a host.

Own `ne.device.snapshot` in Base, `ne.interfaces.inventory`/`ne.interfaces.state` in Interfaces, `ne.lldp.snapshot` in LLDP, and `ne.lag.snapshot` in LAG. `ne.<dataset>.attempt` retains the latest emitted attempt envelope where the producer can emit one. Retained primary snapshots advance only for `status=ok` and `complete=true`; failures/partial attempts update quality evidence while leaving primary data intact. A frontend read must also inspect latest attempt and source item unsupported/error state. A retained snapshot is not evidence of present health.

Every envelope has `schema_version=1.0`, dataset, generation ID, attempted/observed ISO UTC timestamps, status, complete flag, source method/adapter/version, capability state/reason, errors and a data array. The schemas in `schemas/` are authoritative for field typing. A successful empty LLDP or LAG table means a completed supported query found no rows. A timed-out/denied/unsupported table is never represented as healthy empty data. Independently collect each dataset; missing LAG cannot erase interfaces.

## Identity and low-level discovery

The shared name identity baseline is `if-` plus the first 24 lowercase hex SHA-256 characters of UTF-8 `name:` followed by trimmed ifName. If name is absent, hash `description:` plus trimmed ifDescr. Adapter namespacing/hardware identity may supersede this only in a separately versioned migration. Names remain display metadata; item keys contain UID tokens. Preserve optional nullable `alias` from ifAlias separately from `description` (ifDescr); remote LLDP port-ID subtype 1 requires this alias evidence for interface matching. ifIndex is a current locator, never a stable UID. Name change creates a new identity unless a qualified hardware mapping explicitly reconciles it; document history impact.

When names/fallback descriptions collide, generate uncertainty identities scoped to the collection generation and publish `identity_ambiguous` with a partial envelope. Partial inventories never reach LLD. Do not silently choose the first match. Discovery macros are `{#IFUID}`, `{#IFNAME}`, `{#IFINDEX}`, `{#IFDESCR}` and an optional escaped `{#IFCONTEXT}`. Use inventory discovery for additions/removals and fast state for metrics. Retain logical interfaces for relationships while excluding them from physical panel geometry. A physical boolean may be null when evidence is insufficient.

Gate LLD on valid schema, complete success, plausible row count, mandatory column alignment and identity uniqueness. Feed the last successful inventory only. Lost-resource policy defaults: disable after 24 hours of absence in complete successful observations; delete after 7 days. Verify Zabbix version-specific `enabled_lifetime_type`, `enabled_lifetime` and `lifetime` import/runtime behaviour. Never count timeouts as confirmed absence.

## Scalar item contract

Dependent prototypes on canonical state: `ne.if.oper[uid]`, `ne.if.admin[uid]`, `ne.if.speed[uid]`, `ne.if.duplex[uid]`, `ne.if.expected.speed[uid]`, `ne.if.degraded[uid]`. Use standard IF-MIB admin/oper enums and duplex values `unknown`, `half`, `full`. Missing actual speed stays unknown, with no zero substitution that looks like observed degradation. The unsigned expected-speed scalar alone uses 0 as an explicit *unknown policy* sentinel; canonical `expected_speed_bps` is null/absent for unknown intent. Per-interface quality/age remains separate from values.

Each capability owner supplies `ne.collection.status[dataset]` (`0 ok`, `1 partial`, `2 failed`, `3 unsupported`) and `ne.collection.success[dataset]` (observation epoch of complete success). These facts do not capture an unreturned native poll by themselves. Native failure detection must include source item state/error and last-good age; preprocessing cannot execute on a nonexistent poll value. A transport/authentication failure must not update a success heartbeat or produce `unsupported` without evidence.

Optional counters use 64-bit HC octets when present and explicit 32-bit fallback limitations. Detect discontinuities using ifCounterDiscontinuityTime plus sysUpTime evidence; first sample after reset/reboot produces no rate. Derive bps and packets/errors/discards per second with proper delta/time semantics; cumulative errors alone never make a port unhealthy. Proposed graph prototypes: traffic bps, utilisation where meaningful speed is known, and error/discard rate. Avoid a VLAN×port scalar cross-product.

## Macro and trigger policy

Defaults: interface state 60s, inventory 1h, LLDP/LAG 5m, device identity 24h. Stale thresholds initially interface 5m, LLDP/LAG 15m, device 2d; all are configurable. Minimum polling requires measured request/CPU/preprocessing budgets and jitter/scheduling on the proxy.

`{$NE.IF.MONITOR}` defaults 0; per-interface context 1 explicitly enables unexpected-down alerts. `{$NE.IF.EXPECTED_SPEED}` defaults 0 (unknown); context examples are documented by escaped stable interface name. Expected-speed precedence: explicit host policy, qualified role/model policy, reliably configured intent, otherwise unknown. Maximum hardware or previously negotiated speed is not a policy. `{$NE.IF.EXPECTED_DUPLEX}` defaults `unknown`. Validate context quoting and macro resolution in both triggers and frontend enrichment before release. Do not interpolate arbitrary ifName directly into JavaScript source.

Unexpected-down: policy enabled, admin up, sustained oper down, current complete collection. Known-speed degradation: oper up, actual/expected positive, actual below intended target persistently; unknown target has no warning. Add hysteresis/recovery and dependencies on device availability/collection health. Selected LAG member alerts require actual selected/distributing state, not merely configured membership. Suppress related noise during maintenance, stale source and device outage; retained old data cannot falsely recover a problem. Untested/native-to-canonical policy enrichment is an explicit qualification gate.

Problem tags: `component=network-explorer`, `dataset`, `interface_uid`, `scope`. Administrator-controlled host tags `ne.domain`, `site`, `ne_profile`, `vendor` define policy/scope; collection metadata never assigns access rights. Bound tag sizes and escape device-provided text.

## Permission and migration boundaries

The same Zabbix host owns all its raw and normalised datasets. No global fleet dataset host or privileged frontend API token. Frontend peer resolution uses the current user's host/item permissions and network domain. Repeated private IPs across separate domains are valid; technical and visible Zabbix host names must be globally unique. A proxy supplies network reachability, not frontend authorisation.

Raw LLDP items can expose neighbour names/IPs to readers of the source host. Deployment must assess this channel separately from widget filtering: redact metadata at acquisition across strict boundaries, limit source-host/item access, or use the profile only in a trusted administrative scope. Do not claim that a widget alone provides strict isolation.

Before rollout, compare current monitoring coverage (CPU/memory/sensors/PoE/availability/triggers/actions/graphs), record retained/replaced/deferred coverage, export rollback definitions, and qualify a canary. Template linking, unlink/clear, auto-enrolment, production credential setup and service-tree writes remain explicit administrator deployment steps. IDs/UUIDs and key ownership are deterministic; history remapping is not automatic.
