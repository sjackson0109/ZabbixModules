# Canonical datasets

| Schema | File | Status |
|---|---|---|
| 1.1 | [`envelope-1.1.schema.json`](envelope-1.1.schema.json), [examples](examples/) | Current. Emitted by the native SNMP templates. Adds `vlan`, `stp` and `port_capability`, and optional fields on the 1.0 datasets. |
| 1.0 | [`envelope.schema.json`](envelope.schema.json) | Still accepted by the frontend. Emitted by the Python collector, which packages an identical copy checked by the test suite. |

Both are JSON Schema 2020-12. 1.1 only adds datasets and optional fields, so a 1.0 producer stays readable. [The design note](../docs/design/02-canonical-schema.md) explains each field.

## Rules common to both versions

Numeric identifiers and timestamps are never replaced by host IDs; the Zabbix reader associates each item with its owning host.

An `ok` envelope is complete, has a UTC observation timestamp and supported capability. `partial` is incomplete and contains current partial evidence. `failed` and `unsupported` have no new observations and an empty data array; their `observed_at` is null. Attempt and observation time are distinct.

Absent information is null, not invented vendor/model/layout data. LLDP IDs carry their MIB subtype; MAC and IP values are normalised; unknown non-UTF-8 binary identities preserve hexadecimal octets. Suppressed remote identities use null subtype and empty value. Safe interface UIDs are opaque tokens; ifIndex is a positive current locator. All speeds are bits per second. Interface `description` is IF-MIB `ifDescr`; optional nullable `alias` is IF-MIB `ifAlias` and provides separate interface-alias identity evidence.

Future agent sources reserve `source_instance` and `collection_mode` (`once` or `periodic`). Schema validity does not prove host ownership or authenticate the source. A major version change requires reader compatibility work.
