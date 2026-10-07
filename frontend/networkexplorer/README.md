# Network Explorer base module

Copy this directory together with all five widget directories into the configured Zabbix frontend `modules` directory. Scan and enable the base module and widgets using Administration → General → Modules. No Zabbix core changes, frontend API token or separate network database are required. Supported runtime validation is recorded in the repository's lab evidence; the manifest alone does not prove compatibility.

The base module adds Monitoring → Network Explorer. Read-only routes:

- `zabbix.php?action=networkexplorer.view&hostid=123` opens the investigation table.
- `zabbix.php?action=networkexplorer.data&hostid=123` returns the same permitted current state as JSON.
- `zabbix.php?action=networkexplorer.export&report=inventory&format=csv&hostid=123` downloads a report. Reports are `inventory`, `peers`, `addressing`, `degradation`, `quality` and `findings`; formats are CSV and JSON.

`hostids[]=123` accepts multiple seeds. `management_cidr=192.0.2.0/24,2001:db8::/32` annotates permitted peers outside the configured management ranges, preserving them in the graph. A seed request exposes one hop. It resolves identities against up to 300 permitted hosts in the seed domains before projecting the response. A request without seeds exposes the bounded permitted scope.

Matching requires one nonempty, administrator/provisioner-controlled `ne.domain` tag on each host. Missing or conflicting tags suppress peer matching. The tag partitions identity indexes and never grants permissions. Host and item visibility is always determined by the requesting user's Zabbix API permissions. Raw LLDP data can reveal adjacent devices independently of these widgets: use collection-boundary redaction or a trusted administrative profile before enabling raw neighbour metadata. Unresolved placeholders contain no remote names, addresses or remote-derived identifiers.

The reader requires text items `ne.device.snapshot`, `ne.interfaces.inventory`, `ne.interfaces.state`, `ne.lldp.snapshot` and `ne.lag.snapshot`. These primary items retain complete success snapshots. Optional `ne.device.attempt`, `ne.interfaces.attempt`, `ne.lldp.attempt` and `ne.lag.attempt` preserve the latest collection result. Current operational freshness defaults to 180 seconds for interfaces, 900 seconds for LLDP/LAG and 172800 seconds for device identity. Inventory older than two hours adds a quality diagnostic. Collection failures never advance retained observation timestamps, and old attempts never override newer success. Inventory-only interfaces remain visible with unknown operational freshness.

Unknown intended speed never causes a speed warning. A low negotiated speed with explicit intent is an observation; schema 1.0 provides no persistence evidence, so the frontend does not claim a sustained degradation. Native sustained triggers are a separate template contract. Half duplex is observed separately from a proven mismatch. VLAN/STP are explicitly unsupported in this release.

Every request reauthorises hosts/items and keeps no shared graph cache. The history adapter uses the supported frontend history manager only after item authorisation, preserving text history types and a per-item row limit. Wrapper batches contain 50 items; the manager may execute individual SQL lookups, so wrapper-batch counts are not database-query counts. Requests are capped at 300 hosts, 30000 interfaces, 3000 dataset items, 2 MiB per envelope and 64 MiB of envelope input. Oversized data returns an explicit error; sharded datasets are not supported yet. No collector or SNMP operation runs from a browser request.

Host dashboard links omit an originating dashboard ID, allowing Zabbix to choose the destination host's permitted inherited dashboard. A validated `#ne=` fragment supplies JSON `{hostid,uid}` for widget highlighting. CSV downloads defend spreadsheet formula injection and include scope, generation time and per-host observation coverage. JSON includes the same request scope and overall quality coverage.

Pure service validation: `php tests/php/run.php` from the repository root. Fixture gateways are confined to tests; production always uses the current frontend session.
