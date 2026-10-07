# Changelog

All notable changes are recorded here. Versions follow [Semantic Versioning](https://semver.org/); the current version is in [`VERSION`](VERSION).

## [Unreleased]

### Added
- Continuous integration for the Python, Node and PHP checks, on PHP 8.0 and 8.3 and Python 3.10 and 3.12.
- A `templates` release package with the native standard-MIB templates, schemas and dashboard recipes.
- A single `VERSION` file, with a test that keeps every module manifest and the collector in step.

### Changed
- Schema 1.1 moved from `schemas/proposed/` to `schemas/`; it is the current schema, and 1.0 is still accepted.
- The collector names the exception class on stderr when a collection fails unexpectedly, and checks timestamps without optional packages.

## 1.0.0 scope

The first production-capable release covers the specification's acceptance criteria:

- Physical interfaces with state, speed and reduced negotiated speed; port placement by stack member, slot and media; configurable state colours.
- LLDP peers, navigation from a local port to its remote peer, and remote interface highlighting.
- Multi-switch physical topology with a configurable management subnet that annotates, and never hides, connected devices outside it.
- VLAN membership with tagged and untagged distinction, and inter-switch VLAN propagation.
- STP state overlay, and LAG members shown as one logical connection.
- Native Zabbix SNMP templates on standard MIBs for Zabbix 7.0, 7.2 and 7.4, plus an optional Python collector, all feeding one canonical model.
- Zabbix user permissions respected on every read, and collection failures and stale data shown distinctly.
