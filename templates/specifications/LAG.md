# Link aggregation capability specification

LAG is in the initial release. Basic membership/grouping is required where data exists; selected/distributing state, min-links and multichassis semantics are capability-dependent. Missing LAG evidence is unknown/unsupported, not an empty healthy member list.

## Standard MIB candidates

IEEE8023-LAG-MIB root is `.1.2.840.10006.300.43` (not an IETF enterprise OID). Aggregator entry `.1.1.1.1` is indexed by aggregator ifIndex. Candidate columns: actor system ID4, partner system ID8, administrative/operational keys6/7 and aggregate-or-individual5. Aggregation port entry `.1.2.1.1` is indexed by member ifIndex; attached aggregator ID13 identifies the current logical aggregate, 0 means unattached. Actor port14 is a LACP actor identifier, not necessarily ifIndex. Actor/partner state bitmap columns require explicit MIB enum/bit decoding and demonstrated semantics.

The aggregation port-list table `.1.1.2.1.1` uses Actor Port bitmap values. It must not be decoded directly to ifIndex without a qualified mapping. Prefer the explicit attached-aggregator-ID join, and use the bitmap only for corroboration or an adapter with actor-port→ifIndex evidence. IF-MIB supplies names, type, oper status and stable interface UIDs. Some devices expose only proprietary/static-aggregation tables; inspect family-specific evidence before adding OIDs.

## Rows, completeness and behaviour

Publish aggregator UID/name/current ifIndex, member interface UIDs, oper_status and nullable actor/partner system identifiers. UID uses stable interface identity with an aggregation namespace only if versioned consistently across collectors and template adapters. Keep configured membership distinct from selected/collecting/distributing state when those fields are added; static bundles may have no LACP partner evidence. Actor/partner zero IDs mean unknown partner, not a peer with address zero.

A full LAG query with zero supported aggregates can publish complete empty data. If logical ifType161 interfaces exist but the relationship table is absent, show unavailable membership rather than inventing or dropping groups. An attached member whose aggregator or interface cannot be joined is a partial snapshot, retaining prior complete relationships. Preserve multichassis observations as multiple endpoint evidence; never match bundles across devices by equal local port-channel number.

The topology groups physical member links without deleting the member observations. Capacity remains unknown unless speed/selection policies justify a sum. Alert on selected member loss only when selection and expected-member policy are available; configured two-member bundles are not automatically broken because one member is administratively disabled. Proposed minimum-selected-member policy defaults unknown/off and is supplied explicitly.

## Qualification

Capture no-LAG, dynamic LACP, static bundle, disabled member, collecting-only/distributing transitions, partner change, stack/MLAG, ifIndex renumbering and partial member/aggregator table fixtures. Validate member IDs against IF-MIB; test an actor-port number that differs from ifIndex. Confirm logical and physical status separation, retained snapshots on partial, link grouping with reciprocal LLDP and multichassis representation. Deliver canonical fixture output, adapter capability limits and manual min-links policy notes. No family is marked supported without device evidence.
