# Network Explorer base module

Copy this directory together with all five widget directories into the configured Zabbix frontend `modules` directory. Scan and enable the base module and widgets using Administration → General → Modules. No Zabbix core changes, frontend API token or separate network database are required. Supported runtime validation is recorded in the repository's lab evidence; the manifest alone does not prove compatibility.

The base module adds Monitoring → Network Explorer. Network Explorer's network-wide view is available directly from `Monitoring → Network Explorer`. Global dashboards are optional custom compositions and are not required for ordinary Network Explorer use. Host dashboards (from the `Network Explorer - Host dashboard` template) remain the place to investigate one switch.

### The Explorer page

Opening Monitoring → Network Explorer with no parameters shows every permitted switch with Network Explorer data as a Layer 2 topology:

- **Scope** (reloads the page): Site, Domain, Management subnet and Seed device. Site and domain values come from the administrator-controlled `site` and `ne.domain` host tags, and the selectors list only values on hosts the current user can read. They narrow what the user may already see and never grant access. A site shows its switches plus their permitted direct neighbours at other sites, marked as context. A seed device shows itself and its one-hop neighbours. The management subnet is an annotation, never a cut.
- **View** (no reload): Layer 2 (default), Spanning Tree and VLAN, the same renderer and semantics as the Topology widget. Layer 2 marks the observed instance-0 root bridge (★) when every visible switch in its domain reports the same root, that switch reports itself as root (`bridge_id == root_bridge_id`), and its STP collection is current. A root outside the visible topology, or a disagreement, is explained instead of drawn. Spanning Tree adds root paths and blocking port ends; VLAN adds VLAN selection and path tracing.
- **Selection**: a switch shows identity, health, collection state, its interfaces and *Open host dashboard*; a link shows each member's two endpoints, LAG, VLANs, native VLAN, STP role and state, confidence and freshness; a link end or interface shows the full interface detail, with its LLDP peers selectable in place. Everything is keyboard-activatable.
- **Findings and collection quality** cover the same scope as the graph; the view only changes the drawing. *Exports and tables* has CSV and JSON for every report in the same scope, and the device and interface tables.

The address keeps `site`, `domain`, `management_cidr`, `hostid` (seed), `view` (`layer2`, `stp`, `vlan`), `vlan`, `interface_hostid` and `interface_uid`, so a view can be bookmarked or shared; every load re-checks the viewer's permissions. The page draws with the same `runtime.js` as the widgets (copied into `assets/js/` by `scripts/sync_widget_assets.py`) and uses no dashboard broadcasts.

### Routes

- `zabbix.php?action=networkexplorer.view` opens the Explorer page; `&hostid=123&interface_uid=…` deep-links a seed and selected interface.
- `zabbix.php?action=networkexplorer.data&hostid=123` returns the same permitted current state as JSON.
- `zabbix.php?action=networkexplorer.export&report=inventory&format=csv&hostid=123` downloads a report. Reports are `inventory`, `peers`, `addressing`, `degradation`, `vlans`, `stp`, `quality` and `findings`; formats are CSV and JSON.

Every route accepts the same scope: `hostid`/`hostids[]=123` seeds, `site`, `domain` and `management_cidr`. `management_cidr=192.0.2.0/24,2001:db8::/32` annotates permitted peers outside the configured management ranges, preserving them in the graph. A seed request exposes one hop. It resolves identities against up to 1,000 permitted hosts in the seed domains (device and LLDP snapshots only for hosts it does not draw) before projecting the response. A request without seeds or filters covers every permitted Network Explorer host. A scope that would draw more than 300 switches is not drawn; it returns its device count and a message asking for a narrower scope.

Matching requires one nonempty, administrator/provisioner-controlled `ne.domain` tag on each host. Missing or conflicting tags suppress peer matching. The tag partitions identity indexes and never grants permissions. Host and item visibility is always determined by the requesting user's Zabbix API permissions. Raw LLDP data can reveal adjacent devices independently of these widgets: use collection-boundary redaction or a trusted administrative profile before enabling raw neighbour metadata. Unresolved placeholders contain no remote names, addresses or remote-derived identifiers.

The reader requires text items `ne.device.snapshot`, `ne.interfaces.inventory`, `ne.interfaces.state`, `ne.lldp.snapshot` and `ne.lag.snapshot`. These primary items retain complete success snapshots. Optional `ne.device.attempt`, `ne.interfaces.attempt`, `ne.lldp.attempt` and `ne.lag.attempt` preserve the latest collection result. Current operational freshness defaults to 180 seconds for interfaces, 900 seconds for LLDP/LAG and 172800 seconds for device identity. Inventory older than two hours adds a quality diagnostic. Collection failures never advance retained observation timestamps, and old attempts never override newer success. Inventory-only interfaces remain visible with unknown operational freshness.

Unknown intended speed never causes a speed warning. A low negotiated speed with explicit intent is an observation; schema 1.0 provides no persistence evidence, so the frontend does not claim a sustained degradation. Native sustained triggers are a separate template contract. Half duplex is observed separately from a proven mismatch.

Every request reauthorises hosts/items and keeps no shared graph cache. The history adapter uses the supported frontend history manager only after item authorisation, preserving text history types and a per-item row limit. Wrapper batches contain 50 items; the manager may execute individual SQL lookups, so wrapper-batch counts are not database-query counts. Requests are capped at 300 drawn hosts, 1,000 identity candidates, 30000 interfaces, 6000 dataset items per read, 2 MiB per envelope and 64 MiB of envelope input. Oversized data returns an explicit error; sharded datasets are not supported yet. No collector or SNMP operation runs from a browser request.

Host dashboard links omit an originating dashboard ID, allowing Zabbix to choose the destination host's permitted inherited dashboard. A validated `#ne=` fragment supplies JSON `{hostid,uid}` for widget highlighting. CSV downloads defend spreadsheet formula injection and include scope, generation time and per-host observation coverage. JSON includes the same request scope and overall quality coverage.

Pure service validation: `php tests/php/run.php` from the repository root. Fixture gateways are confined to tests; production always uses the current frontend session.
