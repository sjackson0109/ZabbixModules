# Manual installation and operations

Applies to release 1.2.0 on Zabbix 7.0, 7.2 and 7.4. Try the lab workflow before deploying to an existing Zabbix installation. For a step-by-step installation on Docker-based frontends and multi-proxy estates, follow the [deployment guide](DEPLOYMENT_GUIDE.md). The native templates use standard MIBs only and have been tested against simulated switches; no vendor or model has been qualified on real hardware yet.

## Frontend package

1. Back up current module files and export dashboards that will be changed.
2. Locate the actual Zabbix frontend root. Copy all six directories under `frontend/` into its `modules/` directory, preserving each directory name. The base `networkexplorer` module and all five widgets are one compatible package; the widgets use the base module's services and show an install message while it is disabled.
3. Make files readable by the frontend account and directories traversable. The package needs no writable web directory. Match local ownership/security policy; do not make the web root world-writable.
4. In the administrator frontend, scan modules and enable Network Explorer and its widget modules. No Zabbix core files are changed. Container deployments bind-mount or copy the same directories into the image's actual frontend modules path.
5. Configure authorised hosts and their controlled `ne.domain` tags, and link a dataset producer (see Templates below); without data, widgets show missing/unknown observations rather than invented ports.
6. Add Port Panel, Interface Detail, Data Quality, Findings or Physical Topology to a dashboard, selecting a host or using native Host navigator communication. Template dashboards use the inherited host context. Validate with an ordinary scoped user as well as an administrator.

`/usr/share/zabbix/modules` is verified in the included official-container labs; it is not assumed to be the path of every package installation.

## Python collector

The collector is an optional fallback; the native SNMP templates are the preferred acquisition path. Use the collector's [runtime guide](../../collector/README.md) and protected configuration example. Install it in a dedicated virtual environment and use the fixed external-check launcher in the proxy's configured `ExternalScripts` directory. A Python script does not inherit native Zabbix SNMP interface credentials.

Keep actual credential configuration outside the checkout, archive and web root. Use an owner-only regular file, not a symlink; never put passwords/communities in item-key arguments. The runtime accepts an allowlisted device ID and dataset, returns a bounded envelope and records fixed diagnostic codes. External checks do not reliably validate script exit status; the result envelope is the collection-health contract.

Do not enable unrestricted neighbour-address chasing or host auto-enrolment. Collection completeness and last successful observations are separate; a failed/partial collection must not purge existing discovered entities.

## Templates and dashboards

The `templates` package holds the native templates under `templates/native/<7.0|7.2|7.4>/`:

1. Import `network_explorer_snmp.yaml` for your Zabbix version (Data collection > Templates > Import).
2. Link `Network Explorer - Profile - Generic standard MIB` to each switch that has an SNMP interface. Link only the profile; it links the dataset templates.
3. Optionally, after enabling the modules, import `network_explorer_dashboard.yaml` and link `Network Explorer - Host dashboard` beside the profile for the inherited host dashboard.

See [the templates README](../../templates/README.md) for what each template reads. `templates/specifications/` remains the contract for future vendor-family templates; no model should be advertised as supported from its vendor name alone.

The replay YAML exports under `templates/lab/` are only for isolated lab hosts and are not packaged. They accept fixture envelopes through trapper items and perform no SNMP collection. Never link a LAB replay producer and a real producer of the same canonical keys to one host.

Fleet dashboard recipes resolve installation-local IDs at provisioning time. Back up existing definitions and review a diff before replacing them. Dashboard sharing must not grant visibility to otherwise restricted hosts.

## Reports, history and service models

On-demand tables/CSV/JSON use the current user's permitted scope and identify observation age/quality. Exported CSV cells are protected against spreadsheet formula execution. Scheduled PDF/email reports are later scope and require rendering/access-user/delivery configuration.

This build does not claim coherent historical topology, packet delivery from VLAN membership, or a business SLA from physical links. Business service trees require explicit service boundaries, redundancy aggregation and appropriate availability evidence.

## Packages and rollback

```sh
python3 scripts/package.py
cd dist
sha256sum -c SHA256SUMS
```

The frontend, collector, templates and template-specification archives have deterministic metadata and a manifest. They exclude local lab state and dependencies. Supply an independently verified offline wheelhouse where proxy Internet access is unavailable; Python dependency wheels depend on the target platform/runtime.

Upgrade compatible producer/schema/reader versions together, first on a small lab/canary scope. Keep old archives and template/dashboard exports. Restore module directories and compatible producer assets to roll back. Template unlink-and-clear deletes data and is not part of ordinary rollback. Removing module files does not automatically delete user dashboards or monitoring history.
