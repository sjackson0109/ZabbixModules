# 07 — Test plan

Status: **in force**, reviewed 10 October 2026 (spec §34, §35, §40.7). Each requirement in spec §34 is traced to a test that exists today, a planned test, or a gap. "Exists" means the test runs in `scripts/test-dev.sh`, CI or the lab harness and passes on the `work` branch as of 10 October 2026.

## Test layers

| Layer | Runs where | What it proves |
|---|---|---|
| Unit: Python | `pytest` | Collector normalisation, schema, inventory tools |
| Unit: JavaScript (template preprocessing) | `node --test` | The exact JS embedded in templates turns captured walks into canonical envelopes |
| Unit: PHP services | `php tests/php/run.php` | Policy, identity resolution, topology, VLAN/STP overlays, exports |
| Unit: widget runtime | `node --test` | Rendering logic, layout, navigation, CSV escaping |
| Integration | Docker lab: Zabbix 7.0, 7.2, 7.4 + proxy + **snmpsim** replaying captured walks | Real templates import, real SNMP polling through the proxy, preprocessing, LLD, triggers, widgets. The replay suite (`scripts/test-compatibility.sh`) runs in the `Compatibility` workflow nightly, on relevant pull requests and as a release gate |
| Browser: renderer | `tests/browser/widgets.runtime.cjs`, Playwright and Chromium against a static fixture | DOM, escaping, keyboard, selection, VLAN/STP views, root marker, LAG, Explorer selection, CSV. Runs in CI (`Checks`) with Playwright locked in `tests/browser/package-lock.json` |
| Browser: lab | `lab/acceptance.cjs`, Playwright against the lab | Dashboards, Explorer page, navigation and highlight, permissions in the page |
| Scale | Generated 300-switch fixture | Render and response budgets |

The integration layer polls **snmpsim** agents serving the walks in `tests/fixtures/walks/` through the **real** native templates on Zabbix 7.0, 7.2 and 7.4 (`lab/native_snmp.py`, `lab/VERIFICATION.md`), so the whole native path is tested. The older envelope replay through `zabbix_sender` into LAB trapper templates remains for frontend fixtures. The walks are synthetic until real devices are captured.

## Spec §34 unit tests

| Requirement | Status | Test |
|---|---|---|
| SNMP parsing | Exists (collector) | `test_complete_standard_fixture`, `test_lldp_multiple_peers_and_ipv6_management_index` |
| | Exists (synthetic) | Template JS walk-to-envelope for every dataset against each `.snmprec` (`test_every_dataset_is_complete_and_schema_valid`, `tests/unit/test_native_normalisers.py`) |
| Vendor normalisation | Planned | One fixture per qualified profile; expected canonical output checked in |
| Speed normalisation | Exists | `test_interface_speed_units_logical_port_and_identity` (ifHighSpeed and ifSpeed saturation) |
| | Planned | MAU bit decoding to speed lists; effective expected speed (all four precedence rules) |
| Interface state normalisation | Exists | `test_status_mapping_and_unknown_speed_do_not_invent_health`, PHP policy checks |
| | Exists (synthetic) | Custom state colours from the Port panel form (`tests/browser/widgets.runtime.cjs`; lab form check on 7.0, 7.2 and 7.4) |
| | Planned | Seven semantic states, including duplex degraded from the LLDP partner |
| VLAN membership normalisation | Exists (synthetic) | `test_vlan_membership_matches_the_spec_example`, 640-port bitmap decoding in `tests/unit/test_native_normalisers.py` |
| | Planned | Bitmaps over 64 ports (MSB first), bridge port ≠ ifIndex, egress minus untagged = tagged, access/trunk/hybrid classification, forbidden, static versus current, missing join gives `unknown` |
| LLDP peer matching | Exists | `test_lldp_uses_subtypes_and_compound_indices_not_localnum_ifindex`, PHP identity checks (chassis, address, domain isolation) |
| STP state normalisation | Exists (synthetic) | `test_stp_roles_are_derived_from_bridge_evidence`; root disagreement in `tests/php/schema11.php` and the Chromium renderer suite |
| | Planned | State enum mapping, derived roles (root, designated, alternate), bridge ID formatting, topology-change counter reset after reboot |
| LAG detection | Exists | `test_standard_lag_member_evidence`, `test_unknown_lag_partner_and_dangling_aggregator_evidence` |
| | Exists (synthetic) | Static LAG from ifStackTable beside LACP and across stack members, aggregator with no members stays `unknown`, idle LACP aggregator falls back to ifStack, LACP selected/distributing bits (`test_static_bundle_*`, `test_aggregator_without_members_is_unknown_not_static`, `test_idle_lacp_aggregator_lists_ifstack_members`, `test_lacp_bundle`); LACP or Static shown on links and port details in the lab walkthrough |
| Inventory tools | Exists | Walk parser, sanitiser, OID and credential validation (`tests/unit/test_capture_walk.py`), inventory export (`tests/unit/test_inventory_export.py`) |
| Canonical schema 1.1 | Exists | `tests/unit/test_schema_1_1.py`, `tests/php/schema11.php` |

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

## Tests the roadmap adds

Each [roadmap](../network-explorer/ROADMAP.md) unit lands with its tests:

| Unit | Tests |
|---|---|
| B | *Done:* Chromium renderer suite in CI; release blocked unless the Zabbix 7.0/7.2/7.4 compatibility run passes; `tests/unit/test_workflows.py` keeps actions SHA-pinned and the gates wired |
| C | *In review:* `widgets.test.cjs` covers deterministic, capped and natural-order placement, component separation and order, root and no-root anchors, root-port hierarchy, blocked links never becoming parents, the unresolved STP area, fallback when roots are disputed, external peers not moving switches, and previous-position hints; the Chromium suite covers fit/zoom/reset with keyboard, view kept across Layer 2 and VLAN, no movement on selection, search, LAG or trace, root and child placement, non-colour selection markers, the legend and no page overflow. Planned scope: deterministic layout for identical input; STP root-oriented layout from canonical root evidence; disconnected components never overlap; positions stable across view, VLAN, selection, LAG and refresh changes; pan/zoom without page overflow; selected switch, link and link-end styling not carried by colour alone |
| D | Peer resolution with more than 300 permitted candidates; display budget separate from the identity-candidate budget; oversized-scope message; permission and domain isolation unchanged |
| E | Fleet summary counts only accessible objects; search focuses without filtering; STP path-to-root only from sufficient evidence; URL state round-trips and rejects unsafe values |
| F | Qualification matrix entries only reference committed, sanitised evidence |
