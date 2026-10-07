# Canonical datasets 1.0

`envelope.schema.json` is the authoritative JSON Schema 2020-12 contract for
`device`, `interfaces`, `lldp` and `lag`. The collector packages an identical
copy, checked by the test suite. Numeric identifiers and timestamps are never
replaced by host IDs; the Zabbix reader associates each item with its owning host.

An `ok` envelope is complete, has a UTC observation timestamp and supported
capability. `partial` is incomplete and contains current partial evidence.
`failed` and `unsupported` have no new observations and an empty data array;
their `observed_at` is null. Attempt and observation time are distinct.

Absent information is null, not invented vendor/model/layout data. LLDP IDs
carry their MIB subtype; MAC and IP values are normalized; unknown non-UTF8
binary identities preserve hexadecimal octets. Suppressed remote identities
use null subtype and empty value. Safe interface UIDs are opaque tokens;
ifIndex is a positive current locator. All speeds are bits per second.
Interface `description` is IF-MIB `ifDescr`; optional nullable `alias` is
IF-MIB `ifAlias` and provides separate interface-alias identity evidence.

Future agent sources reserve `source_instance` and `collection_mode` (`once` or
`periodic`). Schema validity does not prove host ownership or authenticate the
source. VLAN/STP and version-major changes require separate schema expansion and
reader compatibility work.
