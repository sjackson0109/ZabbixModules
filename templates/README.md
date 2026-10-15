# Network Explorer template work

## Native SNMP templates (generic standard MIB)

`native/<version>/network_explorer_snmp.yaml` holds two flat templates, each self-contained: `Network Explorer - Generic standard MIB`, linked on its own to a switch with an SNMP interface (device, interfaces, port capability, LLDP, VLAN, STP and LAG), and `Network Explorer - LLDP for access points`, LLDP only, for Wi-Fi access-point hosts. Never link both to one host. They are generated from per-dataset components in `source/` by `generate_snmp.py`; a vendor template is another entry in its `PROFILES` list. Port positions come from ENTITY-MIB (entAliasMappingTable and the containment tree), so agents that publish no port entities leave ports unplaced rather than guessed. They use standard MIBs only and have been tested against simulated switches, not yet against real devices ([evidence](../lab/VERIFICATION.md)).

They are generated from `source/datasets.json` and `source/js/`. Scripts are written as YAML literal blocks: Zabbix's import adds a space at every escaped line fold, which corrupts scripts. Zabbix also drops custom on-fail handlers from JavaScript steps at import, so a step that must discard its value returns a sentinel that a following regular-expression step discards. Both generators share these helpers in `_common.py`, take the vendor version from the root `VERSION` file, and the tests compile every generated script with Duktape (`dukpy`, pinned in `requirements-dev.txt`) so ES2015+ syntax is caught before Zabbix sees it. Do not edit the YAML by hand:

```sh
python templates/generate_snmp.py          # regenerate
python templates/generate_snmp.py --check  # fail if stale
node tests/js/run_normaliser.cjs ne.raw.lldp tests/fixtures/walks/sw-core-01.snmprec   # run one normaliser
```

Host dashboards travel with the device templates. `Network Explorer - Generic standard MIB` carries the switch host dashboard (Ports, Topology and Findings pages built from the five widgets); until the widget modules are enabled, Zabbix shows those widgets as inaccessible. `Wi-Fi Explorer - Aruba Instant VC by SNMP` carries a cluster host dashboard built only from Zabbix's own Item value and Graph widgets over the `we.capacity.*` items. Up to 2.0.0 the switch dashboard was a separate `Network Explorer - Host dashboard` template (`network_explorer_dashboard.yaml`); the deployment guide's section 8.4 removes it.

## Earlier specification and LAB replay

The production deliverable at this stage is an implementation specification. No vendor/model has been qualified: live SNMP access, firmware inventory and representative walks are unavailable. Production SNMP templates will be implemented in separate family-specific work after those inputs are supplied.

Start with [the shared contract](specifications/CONTRACT.md), [discovery](specifications/DISCOVERY.md), and the [family handoff index](specifications/FAMILY_HANDOFFS.md). [The machine-readable contract](contract.json) defines ownership, item keys, macro policy and candidate OIDs. Candidate OIDs identify standard objects to investigate; they do not promise that a particular device exposes them.

The `lab/` exports are deliberately named **Network Explorer LAB replay**. They contain trapper/dependent items, safe complete-snapshot LLD, scalar interface facts and inherited widget dashboards. They perform no SNMP collection and must never be used as production monitoring templates. They let the shared module and data contract be tested while vendor evidence is being collected. Send only sanitised fixture envelopes to a lab host; do not link them to an existing monitored device.

Generate or check the deterministic exports with:

```sh
python templates/generate_lab.py
python templates/generate_lab.py --check
```

The generator requires PyYAML. Exports target 7.0/7.2/7.4 schemas. Actual lab imports, replay ingestion, safe LLD retention, dependent scalar values, inherited dashboards and discovered native graphs passed on pinned Zabbix **7.0.20, 7.2.7 and 7.4.3**; see [runtime evidence](../lab/VERIFICATION.md). This establishes the replay contract on those patches, not live SNMP or vendor qualification.

Enable the five Network Explorer widget modules for the host dashboard to render. Its inherited host context is supplied by Zabbix; it contains no numeric host, item or dashboard IDs. For a staged deployment, keep the existing native diagnostics dashboard until modules are enabled. The replay template's collection age triggers are lab diagnostics and its prototype speed policy uses a declared `expected_speed_bps` only; absent intent is scalar `0`, meaning unknown.

Package/update rule: one owner per key and UUID; never link native, proxy-script and lab producers of the same keys together. Export existing templates and dashboard definitions before any administrator-controlled deployment. No live host linking or replacement is performed by these files.
