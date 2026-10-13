# Wi-Fi Explorer roadmap

The [requirements](REQUIREMENTS.md) define seven phases (section 36). Phase A landed as its own pull request; Phases B–F were built back to back and land together, one commit per phase, in one pull request. A phase is complete when its tests pass on Zabbix 7.0, 7.2 and 7.4. Vendor support moves only with evidence in the [Wi-Fi qualification matrix](../qualification/WIFI_MATRIX.md).

| Phase | Scope | Status |
|---|---|---|
| A | Canonical model, site/AP/radio inventory, qualification scaffolding | Done (PR #21) |
| B | Floor plans and RF visualisation | In review |
| C | SSID inventory and wired-uplink correlation | In review |
| D | VLAN service-path assurance | In review |
| E | Blast radius and event readiness | In review |
| F | Client journey | In review |
| G | Vendor expansion and optimisation | Not started |

## Phase A: canonical model and site/AP inventory

Delivered:

- `wifi-1.0` envelope schema with five datasets: `device`, `ap_inventory`, `ap_state`, `radio_inventory`, `radio_state`.
- Aruba Instant producer: AI-AP-MIB normalisers and the generated template *Wi-Fi Explorer - Aruba Instant VC by SNMP* for 7.0, 7.2 and 7.4.
- `frontend/wifiexplorer`: Monitoring → Wi-Fi Explorer with site scope, overview, findings, AP inventory, AP and radio detail and data quality, all permission-filtered through Network Explorer's gateway.
- Qualification: `qualify.py --product wifi`, `capture_walk.py --profile aruba-instant`, synthetic VC and member evidence. Aruba Instant itself stays Unqualified.

Open before Aruba Instant can move past Unqualified: sanitised captures of a VC and a member AP with model and firmware ([what qualification needs](ARUBA_TEMPLATE_REVIEW.md#what-qualification-needs)).

## Phase B: floor plans and RF

Delivered: floors and AP placement (by `ap_uid`) in the module configuration, edited under **Configure**; the **Floor plans** tab with status, band, channel, utilisation, clients, neighbours and retries overlays, interpolated fields labelled as interpolation, channel-reuse lines backed by RF evidence and an unplaced-AP list; the per-AP template *Wi-Fi Explorer - Aruba Instant AP by SNMP* and the `rf_neighbour` dataset (deduplicated, bounded to the strongest 500); the **RF neighbours** tab with evidence-based classes that keep the AP's own label and never say malicious. See [design](DESIGN.md#floor-plans-and-rf-phase-b-sections-14-and-19).

## Phase C: SSIDs and wired uplinks

Delivered: the `ssid` dataset and the **SSIDs** tab; SSID intent (VLAN, where expected, bands) as declared configuration, because AI-AP-MIB on Instant does not expose an SSID's VLAN (walking `.2.3` against a real capture is still open); inferred per-AP broadcasting; uplinks from switch LLDP (chassis MAC or management address) and the AP's own LLDP through Network Explorer's resolver, with confirmed, one-sided, conflicting, ambiguous and unresolved states. See [design](DESIGN.md#ssids-and-wired-uplinks-phase-c-sections-10-and-11).

## Phase D: VLAN service-path assurance

Delivered: per SSID with a declared VLAN, AP by AP, the instance-0 root-port walk to the root bridge with every port checked (up, VLAN in current egress, not blocking), the first failing hop named, and partial or unknown results whenever data is stale, missing, disagreeing or MSTP-mapped. The **VLAN paths** tab. See [design](DESIGN.md#vlan-service-paths-phase-d-section-12).

## Phase E: blast radius and event readiness

Delivered: the **Impact** tab (a switch or port fails: APs lost, degraded, possibly rerouted or not assessable; SSIDs, VLANs, floors and clients now, as an estimate) and the **Events** tab (declared events with a checklist and ready, not ready or unknown). See [design](DESIGN.md#blast-radius-and-event-readiness-phase-e-sections-15-and-16).

## Phase F: client journey

Delivered: one bounded client snapshot per cluster, masked by `{$WE.CLIENT.IDENTIFIERS}` and keyed by the secret `{$WE.CLIENT.KEY}`; the client's AP from the client table's AP address column and its radio by exact BSSID; the **Clients** tab with search, trace (AP, radio, uplink, VLAN paths) and a sampled association timeline from snapshot history, with changes reported between samples. Open: the client's SSID, which the Instant client table does not carry. See [design](DESIGN.md#clients-phase-f-section-13).

## Phase G: vendors and optimisation

Additional vendor families (Ubiquiti UniFi, Cisco WLC and others) as evidence arrives, storage tuning from canary measurements, long-term capacity views and further RF analytics.

## Not carried over from the reviewed Aruba template

The global API-token relay, heuristic analytics presented as measurements, per-client items and "malicious" rogue severity are not adopted; see the [review](ARUBA_TEMPLATE_REVIEW.md#practices-that-wi-fi-explorer-will-not-carry-over).
