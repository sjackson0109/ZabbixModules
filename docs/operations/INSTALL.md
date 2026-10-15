# Manual installation and operations

Applies to release 2.1.0 (Network Explorer and Wi-Fi Explorer) on Zabbix 7.0, 7.2 and 7.4. Try the lab workflow before deploying to an existing Zabbix installation. For a step-by-step installation on Docker-based frontends and multi-proxy estates, follow the [deployment guide](DEPLOYMENT_GUIDE.md). The native templates use standard MIBs only and have been tested against simulated switches; no vendor or model has been qualified on real hardware yet.

## Frontend package

1. Back up current module files and export dashboards that will be changed.
2. Locate the actual Zabbix frontend root. Copy all seven directories under `frontend/` into its `modules/` directory, preserving each directory name. The base `networkexplorer` module, its five widgets and `wifiexplorer` are one compatible package; the widgets and Wi-Fi Explorer use the base module's services and show an install message while it is disabled.
3. Make files readable by the frontend account and directories traversable. The package needs no writable web directory. Match local ownership/security policy; do not make the web root world-writable.
4. In the administrator frontend (Administration → General → Modules), click *Scan directory*, then enable Network Explorer, its widget modules and Wi-Fi Explorer: a scan only registers modules as *Disabled*, it does not enable them. No Zabbix core files are changed. Container deployments bind-mount or copy the same directories into the image's actual frontend modules path.
5. Configure authorised hosts and their controlled `ne.domain` tags, and link a dataset producer (see Templates below); without data, widgets show missing/unknown observations rather than invented ports.
6. Open **Monitoring → Network Explorer** for the network-wide view; it needs no dashboard. For one switch, use the inherited host dashboard (see Templates below). The widgets can also be added to any dashboard you build, selecting a host or using native Host navigator communication. Validate with an ordinary scoped user as well as an administrator.

For Wi-Fi, import `templates/native/<version>/wifi_explorer_snmp.yaml` and link `Wi-Fi Explorer - Aruba Instant VC by SNMP` to one host per Aruba Instant cluster, pointed at the virtual-controller address, with the same `site` and `ne.domain` tags as the switches its APs plug into. The [deployment guide](DEPLOYMENT_GUIDE.md#7-enrol-wi-fi-clusters-and-verify) has the full steps, and the [Wi-Fi Explorer README](../wifi-explorer/README.md) describes the page.

`/usr/share/zabbix/modules` is verified in the included official-container labs; it is not assumed to be the path of every package installation.

## Python collector

The collector is an optional fallback; the native SNMP templates are the preferred acquisition path. Use the collector's [runtime guide](../../collector/README.md) and protected configuration example. Install it in a dedicated virtual environment and use the fixed external-check launcher in the proxy's configured `ExternalScripts` directory. A Python script does not inherit native Zabbix SNMP interface credentials.

Keep actual credential configuration outside the checkout, archive and web root. Use an owner-only regular file, not a symlink; never put passwords/communities in item-key arguments. The runtime accepts an allowlisted device ID and dataset, returns a bounded envelope and records fixed diagnostic codes. External checks do not reliably validate script exit status; the result envelope is the collection-health contract.

Do not enable unrestricted neighbour-address chasing or host auto-enrolment. Collection completeness and last successful observations are separate; a failed/partial collection must not purge existing discovered entities.

## Templates and dashboards

The `templates` package holds the native templates under `templates/native/<7.0|7.2|7.4>/`:

1. Import `network_explorer_snmp.yaml` and `wifi_explorer_snmp.yaml` for your Zabbix version (Data collection > Templates > Import), with *Dashboards* ticked.
2. Link `Network Explorer - Generic standard MIB` to each switch that has an SNMP interface. It is one self-contained template holding every item and the switch host dashboard (Ports, Topology, Findings); nothing else needs linking. Until the widget modules are enabled, that dashboard shows its widgets as inaccessible.
3. Link `Wi-Fi Explorer - Aruba Instant VC by SNMP` to each Aruba Instant cluster; it carries a cluster host dashboard built from Zabbix's own widgets.

See [the templates README](../../templates/README.md) for what each template reads. `templates/specifications/` remains the contract for future vendor-family templates; no model should be advertised as supported from its vendor name alone.

The replay YAML exports under `templates/lab/` are only for isolated lab hosts and are not packaged. They accept fixture envelopes through trapper items and perform no SNMP collection. Never link a LAB replay producer and a real producer of the same canonical keys to one host.

Dashboard recipes in `dashboards/` are optional examples, not installation steps; they resolve installation-local IDs at provisioning time. Back up existing definitions and review a diff before replacing them. Dashboard sharing must not grant visibility to otherwise restricted hosts.

## Reports, history and service models

On-demand tables/CSV/JSON use the current user's permitted scope and identify observation age/quality. Exported CSV cells are protected against spreadsheet formula execution. Scheduled PDF/email reports are later scope and require rendering/access-user/delivery configuration.

This build does not claim coherent historical topology, packet delivery from VLAN membership, or a business SLA from physical links. Business service trees require explicit service boundaries, redundancy aggregation and appropriate availability evidence.

## Packages and rollback

```sh
python3 scripts/package.py
cd dist
sha256sum -c SHA256SUMS
```

For a downloaded release from 1.4.0 on, `gh attestation verify <archive> --repo sjackson0109/ZabbixModules` also confirms it was built by this repository's release workflow ([releasing](RELEASING.md)).

The frontend, collector, templates and template-specification archives have deterministic metadata and a manifest. They exclude local lab state and dependencies. Supply an independently verified offline wheelhouse where proxy Internet access is unavailable; Python dependency wheels depend on the target platform/runtime.

Upgrade compatible producer/schema/reader versions together, first on a small lab/canary scope. Keep old archives and template/dashboard exports. Restore module directories and compatible producer assets to roll back. Template unlink-and-clear deletes data and is not part of ordinary rollback. Removing module files does not automatically delete user dashboards or monitoring history.
