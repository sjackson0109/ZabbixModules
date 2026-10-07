# Network Explorer collector

This proxy-local Python package collects read-only standard SNMP evidence and
normalizes independently collected `device`, `interfaces`, `lldp` and `lag`
datasets. Synthetic fixtures and localhost SNMP tests exercise the contract;
they do not qualify a vendor, model or firmware. Customer template development
and captured-walk qualification remain separate work.

Python 3.10 is the minimum. Python 3.14 is the primary runtime. Installation is
manual copy-out; a Zabbix external check does not inherit the credentials of its
host's SNMP interface. Never pass communities, usernames or passphrases as item
key arguments or command arguments.

## Install

Create a virtual environment at an administrator-selected location and install
the package with the pinned runtime dependencies. The example uses a protected
application directory; adapt paths to the deployment.

```sh
python3 -m venv /opt/network-explorer/venv
/opt/network-explorer/venv/bin/python -m pip install -r collector/requirements.lock
/opt/network-explorer/venv/bin/python -m pip install --no-deps ./collector
```

Copy `packaging/devices.example.json` to an administrator-controlled location
outside the frontend/web root. Fill bindings locally, set ownership to the
collector service account (or a readable root-owned file), and mode `0600`.
The example strings are placeholders, not operational credentials. JSON is
non-executable, symlinks are refused, and destinations must occur in the local
device allowlist.

SNMPv2c binding:

```json
{"version":"2c","community":"SET_LOCALLY"}
```

SNMPv3 supports `noAuthNoPriv`, `authNoPriv` and `authPriv`, SHA1/SHA224/
SHA256/SHA384/SHA512 authentication, and AES128 privacy. The recommended profile
is SHA256/AES128 `authPriv`. MD5, DES and nonstandard extended AES are not
implemented. Context names are supported. Cryptography 50.0.1 is required by the
selected PySNMP AES implementation; older cryptography packages can install
successfully while silently leaving privacy support unusable. The crypto
roundtrip test verifies this prerequisite.

## Run

```sh
/opt/network-explorer/venv/bin/network-explorer-collect collect \
  --config /etc/network-explorer/devices.json \
  --device switch-example --dataset interfaces
```

For development without a switch:

```sh
PYTHONPATH=collector python3 -m network_explorer fixture \
  --path tests/fixtures/snmp/standard-switch.json --dataset interfaces
PYTHONPATH=collector python3 -m network_explorer fixture \
  --path tests/fixtures/snmp/standard-switch.json --dataset lldp --show-remote
```

The JSON envelope is authoritative; handled failure returns a valid `failed`
envelope and process status zero because external-check exit status is not a
reliable Zabbix collection contract. Argument syntax errors remain conventional
CLI errors. Configure external-check timeout above the local `deadline`; an
external process killed by Zabbix cannot emit its failure envelope.

`packaging/network-explorer-collect` is a fixed-path launcher accepting only an
allowlisted device identifier and dataset. Install it under the proxy's actual
`ExternalScripts` location, make it executable, and set the two application
paths before installation. Use only this collector or another producer for a
given canonical key; production vendor templates are developed independently.

## Collection and permission boundaries

`redact_remote` defaults to `true`: remote LLDP chassis IDs, port IDs, names,
descriptions and addresses are suppressed before storage. This also protects
users reading raw Zabbix items/API history. LAG partner-system IDs are also
suppressed. Peer matching is unavailable under
this profile. Set `redact_remote=false` only when every reader of the source
host may receive its collected peer identities. A frontend filter cannot
repair disclosure through raw item history. Proxy assignment provides network
reachability separation; use Zabbix host permissions for access control.

Only configured endpoints are polled. LLDP addresses are observations and are
never followed. No SNMP SET, shell interpolation, runtime MIB downloads,
frontend command channel or agent execution endpoint exists.

Resource limits cover the overall collection deadline, per-request timeout,
retries, total returned varbinds and serialized output bytes. Oversized output
returns `output_limit` with an empty failed envelope; no array is silently
truncated. Partitioned snapshots/manifests are not implemented in this first
package, so large devices require a future partitioning adapter before their
full snapshots can be used.

Complete empty tables differ from absent OIDs or timeouts. Required OIDs and
`ifNumber` consistency prevent partial discovery from appearing complete.
Uptime moving backwards discards the snapshot. Failure never supplies a new
observation timestamp. Separate attempt and successful-snapshot items in Zabbix;
do not feed an incomplete discovery array into LLD.

Interface UIDs use `if-` plus the first 24 hex characters of
`SHA256("name:" + trimmed_ifName)`, with `description:`/trimmed `ifDescr` as
fallback. `ifIndex` remains a locator. Duplicate/missing identities generate
per-generation `uncertain-` UIDs and a partial outcome, preserving uncertainty.
Names changing or hardware replacement are not automatically reconciled.
`description` preserves `ifDescr`; `alias` separately preserves `ifAlias` for
display and subtype-aware LLDP port matching.

LLDP preserves compound timeMark/localPort/remoteIndex row grouping and
chassis/port subtype meanings. Local port numbers are never assumed to be
ifIndex. Interface-name, interface-alias, MAC and conservative locally assigned
description evidence resolve local interfaces. Unresolved mapping remains null
and partial. Standard LAG membership uses the readable aggregator columns and
attached-aggregator mapping; inaccessible index objects are not polled.

Model/firmware/chassis layout enrichment and expected-speed policy are not
inferred. Unknown values stay null. Intended-speed policy can be supplied by the
canonical producer or Zabbix policy layer; hardware maximum is not intent.

## Future agent acquisition

`validate_agent_snapshot` reserves schema, owning-source, repeated-generation
and clock-skew checks. It does not authenticate an agent or accept data over a
network. A future authenticated adapter must bind `source_instance` to the
authorised owning host and retain accepted generations. `collection_mode=once`
supports inventory collection; it does not keep operational evidence fresh.

## Validation

```sh
python3 -m pytest tests/unit/test_collector.py tests/unit/test_collector_transport.py
```

Transport tests start a disposable UDP responder on localhost using random
in-memory credentials. They perform actual SNMPv2c and SNMPv3 SHA256/AES128
roundtrips without a customer device. Normalizer tests cover partial/failed/
unsupported/empty data, renumbering, duplicated identity, compound LLDP indices,
IPv6 addresses, suppression, LAG membership, size limits and reserved agent rules.
