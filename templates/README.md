# Network Explorer template work

## Native SNMP templates (generic standard MIB)

`native/<version>/network_explorer_snmp.yaml` holds the first native templates: `Network Explorer - Base`, `Interfaces`, `Port Capability`, `LLDP`, `VLAN`, `STP`, `LAG` and the profile `Network Explorer - Profile - Generic standard MIB`, which links them all. Link only the profile to a switch with an SNMP interface. They use standard MIBs only and have been tested against simulated switches, not yet against real devices ([evidence](../lab/VERIFICATION.md)).

They are generated from `source/datasets.json` and `source/js/`. Do not edit the YAML by hand:

```sh
python templates/generate_snmp.py          # regenerate
python templates/generate_snmp.py --check  # fail if stale
node tests/js/run_normaliser.cjs ne.raw.lldp tests/fixtures/walks/sw-core-01.snmprec   # run one normaliser
```

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

Install/enable the five Network Explorer widget modules before importing the custom host dashboard. Its inherited host context is supplied by Zabbix; it contains no numeric host, item or dashboard IDs. For a staged deployment, keep the existing native diagnostics dashboard until modules are enabled. The replay template's collection age triggers are lab diagnostics and its prototype speed policy uses a declared `expected_speed_bps` only; absent intent is scalar `0`, meaning unknown.

Package/update rule: one owner per key and UUID; never link native, proxy-script and lab producers of the same keys together. Export existing templates and dashboard definitions before any administrator-controlled deployment. No live host linking or replacement is performed by these files.
