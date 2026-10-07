# Zabbix Network Explorer

A custom Zabbix frontend package for physical port investigation, LLDP topology, LAG relationships and network data quality. Targets Zabbix 7.0–7.4 and Python 3.10+ for the optional collector.

This is an initial build against synthetic data. Vendor/model monitoring templates are **specifications**, to be developed and qualified later when inventory and SNMP walks are available. No live switch compatibility is claimed. VLAN and STP remain subsequent-release scope.

## What is included

- A Network Explorer page and permission-aware PHP dataset, identity, topology, policy, navigation and report services.
- Five dashboard widgets: Port Panel, Physical Topology, Interface Detail, Data Quality and Findings.
- Versioned canonical JSON Schema, conservative standard-MIB normalisers, fixture replay and a bounded Python SNMP transport.
- Detailed template/discovery contracts and separate vendor-family handoff packs.
- LAB-only replay templates and inherited host dashboards for Zabbix 7.0, 7.2 and 7.4; portable fleet dashboard recipes.
- Disposable integration labs, regression tests and deterministic copy-out packages.

## Develop

Python 3.10+ and Node.js are required. PHP service tests use an installed PHP CLI or a pinned Docker image. A Docker engine is required for actual Zabbix integration labs.

```sh
scripts/setup-dev.sh
scripts/test-dev.sh
```

Set `NE_PYTHON` to a preferred interpreter during setup and `NE_VENV` to use an external virtual environment. See [installation and operations](docs/operations/INSTALL.md) for manual deployment. No apt repository or external frontend CDN is required.

## Template development

Start with [the template contract](templates/specifications/CONTRACT.md) and [vendor-family handoffs](templates/specifications/FAMILY_HANDOFFS.md). The [template rebuild requirements](docs/network-explorer/TEMPLATE_REQUIREMENTS.md) define inventory, capability evidence, monitoring preservation and qualification gates.

The `Network Explorer LAB replay` template is a test data source. It does not perform SNMP monitoring and must not be linked to a production switch. A template author supplies complete canonical datasets using the documented keys; the module contains no vendor-specific SNMP logic.

## Isolation and identity

Assign an administrator-controlled `ne.domain` host tag for each customer/network domain. Repeated IPs across isolated domains remain distinct. Technical and display host names must be globally unique by deployment policy. Zabbix host-group permissions determine visibility; proxy assignment alone does not.

LLDP remote metadata may expose restricted neighbours through raw item history. The Python collector suppresses remote identity by default. Enabling it requires a source-host reader policy that allows those observations. The frontend independently filters its output and never uses a privileged API token.

## Design and build scope

[Design pack](docs/network-explorer/README.md) · [build plan](docs/network-explorer/BUILD_PLAN.md) · [confirmed decisions](docs/network-explorer/DECISIONS.md) · [lab instructions](lab/README.md).

For the implemented state, verified checks and next steps, read [the offline continuation handoff](docs/operations/BUILD_STATUS.md).

Production enrolment, template replacement, customer network scans and scheduled report delivery are separate deployment actions. The build uses no customer credentials or live switch access.

Current limits: no snapshot sharding, coherent topology history or automatic duplicate-IP conflict report. Candidate discovery is bounded to the first 301 permitted monitored hosts before domain filtering; narrow-scope peer coverage can therefore be incomplete in larger mixed estates. Truncation is reported. Full 300-switch/15,000-port production performance remains unverified. See [runtime evidence](lab/VERIFICATION.md) for tested release patches and the distinction between synthetic transport and vendor qualification.
