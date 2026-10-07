# Changelog

All notable changes are recorded here. Versions follow [Semantic Versioning](https://semver.org/); the current version is in [`VERSION`](VERSION).

## [Unreleased]

### Added
- Continuous integration for the Python, Node and PHP checks, on PHP 8.0 and 8.3 and Python 3.10 and 3.12.
- A `templates` release package with the native standard-MIB templates, schemas and dashboard recipes.
- A single `VERSION` file, with a test that keeps every module manifest, the collector and the template normalisers in step.
- A Duktape compile check for every JavaScript step in the native and LAB templates.
- 25G, 40G and 100G media types in the MAU capability table.
- Validation of LAG member state and mode.
- An MIT `LICENSE`, shipped in every release package.
- Optional `warnings` in schema 1.1 envelopes, shown in the Data quality widget and as an informational finding.

### Changed
- Schema 1.1 moved from `schemas/proposed/` to `schemas/`; it is the current schema, and 1.0 is still accepted.
- The collector names the exception class on stderr when a collection fails unexpectedly, and checks timestamps without optional packages.
- Widgets show a message instead of reading data when the Network Explorer module is disabled; the menu entry appears only for users who can open the page.
- The widget runtime and stylesheet have one source in `src/widget/`; topology search dims nodes instead of redrawing, and SVG colours follow the dark theme.
- Every finding has the same fields and one stable ID scheme.
- A normaliser error now produces a failed envelope instead of no envelope.
- The LAB replay templates discard failed collections the same way as the native templates.
- The restart trigger ignores the 497-day `sysUpTime` wrap.
- Collector runtime dependencies are pinned by hash.
- The Python collector is a frozen fallback on schema 1.0.
- A duplicate interface name, a row missing its status columns or an `ifNumber` mismatch no longer makes the whole interfaces dataset partial. The row is skipped or keeps unknown fields, and the snapshot stays current.

### Fixed
- A VLAN row without an interface no longer attaches to LLDP links with an unmapped local port.
- The CSV formula guard also applies to text that is not valid UTF-8.
- A failed inventory read is no longer reported as stale inventory.

## 1.0.0 scope

The first production-capable release covers the specification's acceptance criteria:

- Physical interfaces with state, speed and reduced negotiated speed; port placement by stack member, slot and media; configurable state colours.
- LLDP peers, navigation from a local port to its remote peer, and remote interface highlighting.
- Multi-switch physical topology with a configurable management subnet that annotates, and never hides, connected devices outside it.
- VLAN membership with tagged and untagged distinction, and inter-switch VLAN propagation.
- STP state overlay, and LAG members shown as one logical connection.
- Native Zabbix SNMP templates on standard MIBs for Zabbix 7.0, 7.2 and 7.4, plus an optional Python collector, all feeding one canonical model.
- Zabbix user permissions respected on every read, and collection failures and stale data shown distinctly.
