# Network Explorer template work

## Native SNMP templates (switches)

`native/<version>/` holds one file per template, named after it (`ne__generic_switch.yaml`, `we__generic_access_point.yaml` and so on). Each template is flat and self-contained, and each file imports on its own; link exactly one switch template to a host.

Every template is named after its product, `ne_` (Network Explorer, switches) or `we_` (Wi-Fi Explorer, access points), then its words in lowercase with single underscores: vendor switches as `ne_<vendor>_<series>_switch`. The visible name is the product's name, " - ", and the same words in Title Case, such as `Network Explorer - Cisco Small Business Switch`. Each product's generic template alone has a double underscore, `ne__generic_switch` and `we__generic_access_point`, so it and its file sort first. The prefix also sets the template group: `Templates/Network Explorer` for `ne_`, `Templates/Wi-Fi Explorer` for `we_`. The rule is in `_common.py`, and both generators check it.

| Template (technical name) | Visible name | For |
|---|---|---|
| `ne__generic_switch` | Network Explorer - Generic Switch | Any switch with an SNMP interface: device, interfaces, port capability, LLDP, VLAN, STP, LAG and PoE from standard MIBs. |
| `ne_cisco_cbs220_switch` | Network Explorer - Cisco CBS220 Switch | Cisco Business 220 (Realtek-based firmware, no CISCOSB MIBs): the generic datasets with PoE ports joined to their interfaces, plus hardware health from CISCO-ENVMON-MIB, shipped disabled because firmware 2.0.2.15 does not answer it. |
| `ne_cisco_sg300_switch` | Network Explorer - Cisco SG300 Switch | SG300 on firmware 1.4: the generic datasets plus hardware health from the CISCOSB MIBs, with the older 14-column environment table, and per-port PoE power. |
| `ne_cisco_small_business_switch` | Network Explorer - Cisco Small Business Switch | SG350, SG350X, SG350XG, CBS350, C1200 and C1300: the generic datasets plus hardware health from the CISCOSB MIBs (24-column environment table) and per-port PoE power. |
| `ne_dell_n_series_switch` | Network Explorer - Dell N Series Switch | Dell N-Series on DNOS 6: the generic datasets plus hardware health from DNOS-SWITCHING, DNOS-BOXSERVICES and Dell-Vendor MIBs, with PoE ports joined to their interfaces. |
| `ne_dell_x_series_switch` | Network Explorer - Dell X Series Switch | Dell X-Series (RADLAN): the generic datasets plus hardware health from the RADLAN and Dell-Vendor MIBs. |
| `we_lldp_for_access_points` | Wi-Fi Explorer - LLDP for Access Points | Network Explorer's LLDP dataset only, for access-point hosts, so an AP confirms its own uplink. Built here because it reuses the switch LLDP producer; never beside a switch template. |

Up to 2.2.0 the generic template was `Network Explorer - Generic Switch` and the access-point LLDP template `Network Explorer - LLDP for access points`, both in one `network_explorer_snmp.yaml`; they keep their UUIDs (the profile's `scope`), so an import renames them in place. Each vendor template carries Port Capability disabled, because none of the captured models implements MAU-MIB; enable it on a host whose firmware does. The CBS220 template also carries Hardware Health disabled, because no capture has shown its MIB yet. Which models and firmware each has been tested on is in the [qualification matrix](../docs/qualification/MATRIX.md); a model that is not listed there is unqualified.

All are generated from per-dataset components in `source/` by `generate_snmp.py`. The templates and their components are listed under `templates` in `source/datasets.json`; a producer with a `templates` list belongs to those templates only, so each template has exactly one producer per dataset. Port positions come from ENTITY-MIB (entAliasMappingTable and the containment tree), so agents that publish no port entities leave ports unplaced rather than guessed. The vendor hardware and PoE producers are tested against the anonymised captures in `tests/fixtures/qualification/` (`tests/unit/test_hardware_normalisers.py`, `tests/unit/test_poe_normalisers.py`); column positions follow the MIBs listed in [`mib/`](../mib/README.md), which are kept locally rather than published.

Hardware health (`ne.hardware.*`, canonical schema 1.2) reports each part's state as the device judges it, against the device's own thresholds: the templates never invent a temperature limit. Parts are discovered while the device reports them present and readable (`ne.hw.fan.discovery`, `ne.hw.psu.discovery`, `ne.hw.temp.discovery`), so empty fan or supply slots create no items. CPU and memory utilisation alert above `{$NE.HW.CPU.UTIL.MAX}` / `{$NE.HW.MEMORY.UTIL.MAX}` (90%) for `{$NE.HW.CPU.UTIL.FOR}` / `{$NE.HW.MEMORY.UTIL.FOR}` (15m). The rules and producers are in [HARDWARE.md](specifications/HARDWARE.md).

Power over Ethernet (`ne.poe.*`, canonical schema 1.2) is in every switch template: each PSE unit's budget, consumption and status, and each port's detection status, with the power each port draws where the vendor MIB reports it. A unit raises a problem when it reports a fault or reaches the device's own usage threshold, and a port when it reports a fault. RFC 3621 does not map a PoE port to an interface, so only the vendor templates whose captures show the mapping name ports after their interfaces; the generic template names them by unit and port. The rules and producers are in [POE.md](specifications/POE.md).

They are generated from `source/datasets.json` and `source/js/`. Scripts are written as YAML literal blocks: Zabbix's import adds a space at every escaped line fold, which corrupts scripts. Zabbix also drops custom on-fail handlers from JavaScript steps at import, so a step that must discard its value returns a sentinel that a following regular-expression step discards. Both generators share these helpers in `_common.py`, take the vendor version from the root `VERSION` file, and the tests compile every generated script with Duktape (`dukpy`, pinned in `requirements-dev.txt`) so ES2015+ syntax is caught before Zabbix sees it. Do not edit the YAML by hand:

```sh
python templates/generate_snmp.py          # regenerate
python templates/generate_snmp.py --check  # fail if stale
node tests/js/run_normaliser.cjs ne.raw.lldp tests/fixtures/walks/sw-core-01.snmprec   # run one normaliser
```

## Native SNMP templates (Wi-Fi)

The Wi-Fi templates follow the same pattern, one file each. `we__generic_access_point` (Wi-Fi Explorer - Generic Access Point) is the generic template, linked on its own to one host per access point at the AP's own address. It reads standard MIBs only (SNMPv2-MIB, IF-MIB, the IEEE 802.11 MIB, ENTITY-MIB, HOST-RESOURCES-MIB, IP-MIB) and feeds the AP, radio and SSID datasets; no standard MIB lists clients, measured utilisation or RF neighbours, so it has no items for them, and an agent without the IEEE 802.11 MIB reports every dataset as unsupported (`not_wifi_ap`). Vendor templates complement it with what only a vendor MIB carries: `we_aruba_instant_virtual_controller` (one host per cluster) and `we_aruba_instant_access_point` (RF neighbours, per AP) are the first. Up to 2.2.0 they were `Wi-Fi Explorer - Generic AP`, `Wi-Fi Explorer - Aruba Instant VC by SNMP` and `Wi-Fi Explorer - Aruba Instant AP by SNMP`, all in one `wifi_explorer_snmp.yaml`; each manifest entry's `uuid_name` keeps the UUIDs of that name, so an import renames it in place. All are generated by `generate_wifi.py` from `source/wifi/datasets.json` and `source/js/wifi/`; a vendor template is another entry in that manifest, built to the [Wi-Fi template requirements](../docs/wifi-explorer/TEMPLATE_REQUIREMENTS.md). Every Wi-Fi template feeds the same canonical `we.*` keys, so never link two to the same APs.

Host dashboards travel with the device templates. `ne__generic_switch` and each vendor switch template carry the switch host dashboard (Ports, Topology and Findings pages built from the five widgets); until the widget modules are enabled, Zabbix shows those widgets as inaccessible. `we__generic_access_point` (radios up by band) and `we_aruba_instant_virtual_controller` (the cluster's APs, clients, utilisation and radios) carry host dashboards built only from Zabbix's own Item value and Graph widgets over the `we.capacity.*` items. Up to 2.0.0 the switch dashboard was a separate `Network Explorer - Host dashboard` template (`network_explorer_dashboard.yaml`); the deployment guide's section 8.4 removes it.

## Earlier specification and LAB replay

The specifications below came first, written before any device walks were available. Captured-walk evidence for specific models and firmware now lives in [docs/qualification](../docs/qualification/README.md); the specifications remain the design reference for families that have none.

Start with [the shared contract](specifications/CONTRACT.md), [discovery](specifications/DISCOVERY.md), and the [family handoff index](specifications/FAMILY_HANDOFFS.md). [The machine-readable contract](contract.json) defines ownership, item keys, macro policy and candidate OIDs as first specified (schema 1.0); it is not maintained with the templates, whose source is `source/datasets.json`. Candidate OIDs identify standard objects to investigate; they do not promise that a particular device exposes them.

The `lab/` exports are deliberately named **Network Explorer LAB replay**. They contain trapper/dependent items, safe complete-snapshot LLD, scalar interface facts and inherited widget dashboards. They perform no SNMP collection and must never be used as production monitoring templates. They let the shared module and data contract be tested while vendor evidence is being collected. Send only sanitised fixture envelopes to a lab host; do not link them to an existing monitored device.

Generate or check the deterministic exports with:

```sh
python templates/generate_lab.py
python templates/generate_lab.py --check
```

The generator requires PyYAML. Exports target 7.0/7.2/7.4 schemas. Actual lab imports, replay ingestion, safe LLD retention, dependent scalar values, inherited dashboards and discovered native graphs passed on pinned Zabbix **7.0.20, 7.2.7 and 7.4.3**; see [runtime evidence](../lab/VERIFICATION.md). This establishes the replay contract on those patches, not live SNMP or vendor qualification.

Enable the five Network Explorer widget modules for the host dashboard to render. Its inherited host context is supplied by Zabbix; it contains no numeric host, item or dashboard IDs. For a staged deployment, keep the existing native diagnostics dashboard until modules are enabled. The replay template's collection age triggers are lab diagnostics and its prototype speed policy uses a declared `expected_speed_bps` only; absent intent is scalar `0`, meaning unknown.

Package/update rule: one owner per key and UUID; never link native, proxy-script and lab producers of the same keys together. Export existing templates and dashboard definitions before any administrator-controlled deployment. No live host linking or replacement is performed by these files.
