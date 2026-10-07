# 07 — Test plan

Status: **proposed, for review** (spec §34, §35, §40.7). Each requirement in spec §34 is traced to a test that exists today, a planned test, or a gap. "Exists" means the test runs in `scripts/test-dev.sh` or the lab harness and passes on the `work` branch as of 7 October 2026.

## Test layers

| Layer | Runs where | What it proves |
|---|---|---|
| Unit: Python | `pytest` | Collector normalisation, schema, inventory tools |
| Unit: JavaScript (template preprocessing) | `node --test` | The exact JS embedded in templates turns captured walks into canonical envelopes |
| Unit: PHP services | `php tests/php/run.php` | Policy, identity resolution, topology, VLAN/STP overlays, exports |
| Unit: widget runtime | `node --test` | Rendering logic, layout, navigation, CSV escaping |
| Integration | Docker lab: Zabbix 7.0, 7.2, 7.4 + proxy + **snmpsim** replaying captured walks | Real templates import, real SNMP polling through the proxy, preprocessing, LLD, triggers, widgets |
| Browser | Playwright against the lab | Dashboards, navigation and highlight, permissions in the page |
| Scale | Generated 300-switch fixture | Render and response budgets |

The step change from today is the integration layer. It currently replays envelopes through `zabbix_sender` into lab trapper templates. It must instead poll **simulated SNMP agents built from captured walks** through the **real** templates, so that the whole native path is tested.

## Spec §34 unit tests

| Requirement | Status | Test |
|---|---|---|
| SNMP parsing | Exists (collector) | `test_complete_standard_fixture`, `test_lldp_multiple_peers_and_ipv6_management_index` |
| | Planned | Template JS: walk-to-envelope for every dataset, run against each captured `.snmprec` |
| Vendor normalisation | Planned | One fixture per qualified profile; expected canonical output checked in |
| Speed normalisation | Exists | `test_interface_speed_units_logical_port_and_identity` (ifHighSpeed and ifSpeed saturation) |
| | Planned | MAU bit decoding to speed lists; effective expected speed (all four precedence rules) |
| Interface state normalisation | Exists | `test_status_mapping_and_unknown_speed_do_not_invent_health`, PHP policy checks |
| | Exists (synthetic) | Custom state colours from the Port panel form (`tests/browser/widgets.runtime.cjs`; lab form check on 7.0, 7.2 and 7.4) |
| | Planned | Seven semantic states, including duplex degraded from the LLDP partner |
| VLAN membership normalisation | Planned | Bitmaps over 64 ports (MSB first), bridge port ≠ ifIndex, egress minus untagged = tagged, access/trunk/hybrid classification, forbidden, static versus current, missing join gives `unknown` |
| LLDP peer matching | Exists | `test_lldp_uses_subtypes_and_compound_indices_not_localnum_ifindex`, PHP identity checks (chassis, address, domain isolation) |
| STP state normalisation | Planned | State enum mapping, derived roles (root, designated, alternate), bridge ID formatting, topology-change counter reset after reboot |
| LAG detection | Exists | `test_standard_lag_member_evidence`, `test_unknown_lag_partner_and_dangling_aggregator_evidence` |
| | Planned | Static LAG from ifStackTable; LACP member selected/distributing bits |
| Inventory tools | Planned in this branch | Secret stripping, capability classification, CSV escaping, walk parser and sanitiser |
| Canonical schema 1.1 | Exists in this branch | `tests/unit/test_proposed_schema.py` |

## Spec §34 integration scenarios

Each scenario is an snmpsim data set built from a real (sanitised) walk where one exists, and synthesised only where none does. Synthetic data proves the parser, not the vendor.

| Scenario | Data set | Pass condition |
|---|---|---|
| 24-port switch | captured | 24 front-panel ports in a 24-port layout; states and speeds match the walk |
| 48-port switch | captured | as above, 48-port layout |
| Stack | synthetic (sw-stack-01); captured planned | Member tabs and ENTITY-MIB placement pass in the lab walkthrough; planned: ports keep identity across a member renumbering replay |
| SFP/SFP+ switch | captured | Media shown per port; 10G uplinks evaluated against 10G expectation |
| Multi-vendor LLDP link | two captured vendors | One confirmed edge; navigation from A highlights the right port on B |
| VLAN trunk | captured | Tagged VLANs and native VLAN correct on both ends; carry/no-carry link classes |
| Access VLAN | captured | Access port with PVID shown as untagged in the selected VLAN |
| STP blocking path | synthesised triangle | One blocking port shown; root bridge and root ports marked |
| LAG | captured | Members grouped into one logical link; member loss shown |
| Reduced speed | synthesised from captured (oper MAU 100M on 1G-capable pair) | Port amber with source "negotiable" (criterion 3) |

## Spec §34 failure tests

| Failure | Status | How |
|---|---|---|
| Unreachable device | Partly exists (collector, lab failed attempts) | Planned: snmpsim stopped; native master unsupported; attempt shows `failed`; panel keeps last data with a "collection failed" badge |
| Incomplete SNMP response | Exists (collector) | `test_partial_walk_cannot_be_complete_discovery`; planned: truncated `.snmprec` through the template JS |
| Unknown vendor | Planned | Unknown sysObjectID gets the generic profile; missing datasets shown as unsupported |
| Unknown peer | Exists | Lab: unresolved peer kept as an external placeholder |
| Invalid management subnet | Exists | PHP CIDR checks, lab CIDR annotation; planned: malformed CIDR rejected in the widget form |
| Stale LLDP data | Exists (policy) | Planned: lab stops LLDP walk only; edge turns dashed and stale after `{$NE.LLDP.STALE}` |
| Missing VLAN data | Planned | VLAN subtree absent: VLAN layer says unsupported; physical layer unaffected |
| Reboot during walk, ifIndex renumbering | Exists (collector) | `test_reboot_discards_incoherent_snapshot`, `test_renumbered_ifindex_preserves_name_identity` |
| Authentication failure | Exists (transport) | `test_incorrect_binding_is_failure_and_redacted`; planned: native v3 wrong key gives `failed`, not `unsupported` |

## Acceptance (spec §35) demonstration script

The release is accepted by running one scripted walkthrough on each Zabbix version in the lab, recorded by the browser suite. It follows Appendix A: open a switch, see an amber port, follow the LLDP peer, see the highlighted remote port; open the topology, apply `10.101.0.0/16`, see the out-of-scope switch flagged; select VLAN 49 and find the first link where it is not permitted; switch to STP and see the blocking port; expand a LAG; log in as a restricted user and confirm the hidden switch is absent from the page, the API response and the CSV export; stop a simulated agent and see "collection failed". Each of the 18 criteria maps to one step and one assertion.

## Security tests (spec §30)

Existing: secrets never in collector output or errors, CSV formula escaping, restricted peer data hidden for a read-only user, inaccessible seed returns an empty graph. Planned: XSS payloads in ifAlias, sysName and LLDP descriptions rendered inert in every widget; widget form inputs (CIDR, VLAN ID, layer) validated server-side; inventory export output contains no interface secrets.
