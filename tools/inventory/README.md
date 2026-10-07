# Estate inventory tools

Two stdlib-only Python 3.10+ tools that gather the vendor/model inventory the
Network Explorer spec requires before vendor adapters are written. Both are
**read-only**: neither one changes Zabbix or any device.

| Tool | Reads | Writes (locally, mode 0600) |
| --- | --- | --- |
| `export_inventory.py` | Zabbix API `hostgroup.get`, `host.get`, `proxy.get`, `proxygroup.get`, `item.get`, `discoveryrule.get` (the code refuses any other method) | per-host CSV, per vendor/model/firmware summary CSV |
| `capture_walk.py` | One device, using net-snmp `snmpbulkwalk` (GETBULK only) on a fixed list of standard subtrees | `<label>.snmprec` (snmpsim format) and `<label>.manifest.json` |

## 1. Zabbix inventory export

Requirements: Zabbix 7.0–7.4 and an API token for a user that can **read** the
SNMP hosts. A read-only user role is enough.

```sh
export ZABBIX_API_TOKEN=...            # or: --token-file ~/.zabbix-token (chmod 600)
python3 tools/inventory/export_inventory.py \
    --url https://zabbix.example.net/ \
    --ca-file /etc/ssl/certs/internal-ca.pem \
    --group "Network switches" --tag site=HQ \
    --hosts-out inventory-hosts.csv --summary-out inventory-summary.csv
```

- The token is never accepted on the command line and is never printed.
  TLS certificates are always verified. Use `--ca-file` for a private CA.
  Plain `http://` is accepted only for loopback addresses.
- `--group` and `--tag` (`NAME` or `NAME=VALUE`) can be repeated. Without them,
  every host with an SNMP interface is exported.
- `--batch-size` (default 100) sets how many hosts go in each `item.get` or
  `discoveryrule.get` call. `--timeout` (default 30 s) applies to each request.
- Exit codes: `0` ok, `2` usage/configuration error, `3` API/authentication
  error, `4` partial. On a partial export the CSVs are still written, and rows
  whose evidence could not be fetched say `unknown`.
- Offline/demo: `--fixture api.json`, with canned API results keyed by method.

### What the columns mean

- `vendor`, `model`, `firmware`, plus `*_source`. Values come from host
  inventory first, then the standard template items `system.hw.model`,
  `system.hw.firmware` and `system.sw.os`. Only the vendor can come from the
  sysObjectID enterprise number. Models are never guessed: a blank means unknown.
- `existing_monitoring_<capability>` (interfaces, lldp, vlan, stp, lag, poe,
  optics) is **existing monitoring evidence, not device capability**. Values:
  - `monitored`: an enabled SNMP item or LLD rule polls that MIB.
  - `monitored-error`: one exists but is unsupported. The first error is shown
    in `existing_monitoring_errors`.
  - `absent`: no enabled item or rule polls that MIB. This does not mean the
    device lacks the MIB.
  - `unknown`: the API batch failed.

  `optics` means ENTITY-SENSOR evidence, which also covers non-optical sensors.
- `interface_discovery` lists the LLD rule(s) that use IF-MIB, including
  dependent rules fed by an SNMP `walk[]` master item. It shows `none` when
  there are no such rules.
- `notes` holds sysDescr, collapsed to a single line and cut to 200 characters.
- SNMP interface details are reduced to version, bulk, max repetitions,
  security level, auth/priv protocol names and context. Communities, security
  names and passphrases are dropped before any processing. Interface IP
  addresses are not exported.
- Cells that a spreadsheet would treat as a formula are prefixed with `'`.

## 2. Per-device SNMP capture

Requirements: net-snmp command-line tools (`snmpbulkwalk`). Run the capture
from a host that the device already allows to poll it, such as the Zabbix
proxy. Capture one representative device per vendor/model/firmware row of the
summary.

Credentials go in a JSON file with mode 0600. The tool refuses a file that is
group or world readable.

```json
{"version": "2c", "community": "..."}
{"version": "3", "username": "...", "security_level": "authPriv",
 "auth_protocol": "SHA-256", "auth_passphrase": "...",
 "priv_protocol": "AES", "priv_passphrase": "..."}
```

The tool can also read them from environment variables: `NE_SNMP_COMMUNITY`, or
`NE_SNMP_V3_USER`, `NE_SNMP_V3_SECURITY_LEVEL`, `NE_SNMP_V3_AUTH_PROTOCOL`,
`NE_SNMP_V3_AUTH_PASSPHRASE`, `NE_SNMP_V3_PRIV_PROTOCOL` and
`NE_SNMP_V3_PRIV_PASSPHRASE`. Credentials reach net-snmp through a temporary
private `snmp.conf`, so they never appear in the process list, the output or
the manifest. Any credential text in error messages is replaced by `***`.

```sh
python3 tools/inventory/capture_walk.py --host 10.0.0.10 --label cisco-c2960x-15.2-7-E8 \
    --credentials ~/.snmp-ro.json --out-dir captures \
    --sanitise --sanitise-serials --sanitise-aliases --sanitise-map ~/private/sanitise-map.json
```

- The default subtrees are system, ifTable/ifXTable/ifStackTable, EtherLike
  duplex, MAU-MIB, ENTITY-MIB entPhysical and alias mapping, BRIDGE-MIB base
  ports and STP, Q-BRIDGE, LLDP, IEEE8023-LAG, POWER-ETHERNET, ENTITY-SENSOR
  and IEEE8021-MSTP. To add a vendor subtree, pass `--extra-subtree <numeric OID>`
  (this option can be repeated).
- Time limits: `--subtree-timeout` (default 120 s) and `--total-timeout`
  (default 900 s). Request pacing is set with `--request-timeout`, `--retries`
  and `--max-repetitions`.
- The manifest records the outcome of each subtree (`ok`, `timeout`,
  `no-such-object`, `error` or `skipped`), record counts, `captured_at` (UTC)
  and the net-snmp version. It contains no credentials and no target address.
- Exit codes: `0` complete, `2` usage error, `3` nothing could be read, `4`
  partial.
- To replay a capture, copy `<label>.snmprec` into an snmpsim data directory
  and poll it with community `<label>`.

### Sanitisation: what it does and does not do

- `--sanitise` replaces the following:
  - IPv4 `IpAddress` values, LLDP management-address indexes and LLDP
    chassis/port IDs of subtype networkAddress, with addresses from
    192.0.2.0/24, 198.51.100.0/24 and 203.0.113.0/24.
  - sysName, lldpLocSysName and lldpRemSysName, with `device-NNN`.
  - sysLocation, with `location-NNN`.
  - sysContact, with `contact-redacted`.

  Netmasks, loopback, multicast and 0.0.0.0 are kept.
- `--sanitise-serials` replaces entPhysicalSerialNum, and `--sanitise-aliases`
  replaces ifAlias.
- **Not altered:**
  - MAC addresses
  - IPv6 addresses
  - sysDescr, ifDescr, LLDP port and system descriptions, entPhysical
    descriptions
  - IPv4 text inside free-text strings
  - addresses inside other indexes, for example an `--extra-subtree` of
    ipAddrTable

  Read the `.snmprec` file before you share it.
- Replacements are consistent within one capture. They are consistent across
  captures only if every capture reuses the same `--sanitise-map` file. That
  file holds the real values, so **keep it private**.

## What to send back

- `inventory-hosts.csv` and `inventory-summary.csv`. Review them first: they
  contain host names, sites and proxy names.
- For each representative device, the sanitised `<label>.snmprec` and
  `<label>.manifest.json`.

## What NOT to share

- API tokens, token files, SNMP credential files or environment dumps.
- The `--sanitise-map` file.
- Unsanitised `.snmprec` files, unless the data owner has agreed to share
  them.
