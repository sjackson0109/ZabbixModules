# Wi-Fi Explorer roadmap

The [requirements](REQUIREMENTS.md) define seven phases (section 36). Each lands as one pull request to `main`, reviewed before the next starts. A phase is complete when its tests pass on Zabbix 7.0, 7.2 and 7.4. Vendor support moves only with evidence in the [Wi-Fi qualification matrix](../qualification/WIFI_MATRIX.md).

| Phase | Scope | Status |
|---|---|---|
| A | Canonical model, site/AP/radio inventory, qualification scaffolding | In review |
| B | Floor plans and RF visualisation | Not started |
| C | SSID inventory and wired-uplink correlation | Not started |
| D | VLAN service-path assurance | Not started |
| E | Blast radius and event readiness | Not started |
| F | Client journey | Not started |
| G | Vendor expansion and optimisation | Not started |

## Phase A: canonical model and site/AP inventory

Delivered:

- `wifi-1.0` envelope schema with five datasets: `device`, `ap_inventory`, `ap_state`, `radio_inventory`, `radio_state`.
- Aruba Instant producer: AI-AP-MIB normalisers and the generated template *Wi-Fi Explorer - Aruba Instant VC by SNMP* for 7.0, 7.2 and 7.4.
- `frontend/wifiexplorer`: Monitoring → Wi-Fi Explorer with site scope, overview, findings, AP inventory, AP and radio detail and data quality, all permission-filtered through Network Explorer's gateway.
- Qualification: `qualify.py --product wifi`, `capture_walk.py --profile aruba-instant`, synthetic VC and member evidence. Aruba Instant itself stays Unqualified.

Open before Aruba Instant can move past Unqualified: sanitised captures of a VC and a member AP with model and firmware ([what qualification needs](ARUBA_TEMPLATE_REVIEW.md#what-qualification-needs)).

## Phase B: floor plans and RF

- Floor-plan assets per site and building, with AP placement stored by `ap_uid` (never by name or MAC).
- Overlays: band, channel, utilisation and, from Phase F data, client density. An interpolated overlay is labelled as observed-data interpolation, never a predictive survey (principle 8).
- RF neighbour and rogue view from `aiInterferAccessPointTable`, owned by each **observing AP**, not the VC. It needs per-AP owner hosts, a bounded and deduplicated snapshot (900+ rows were seen on one AP), and the device's own classification kept as evidence without calling anything malicious (principle 9).

## Phase C: SSIDs and wired uplinks

- `ssid` dataset from the Instant SSID table: name, status, hidden flag, client count.
- **SSID-to-VLAN mapping** is not exposed by AI-AP-MIB on Instant. It will come from declared intent (an operator-maintained mapping) or a verified source, and the page will say which. Walking AI-AP-MIB `.2.3` (a possible per-BSS table) is the first thing to check against a capture.
- AP-to-switch relationship from LLDP. The Aruba template's LLDP walk lacks chassis IDs and subtypes, so Network Explorer's standard LLDP producer is linked to AP hosts instead; AP-side and switch-side observations then share one parser and corroborate each other.

## Phase D: VLAN service-path assurance

Per SSID, prove AP by AP that the required VLAN reaches each AP's switch port and continues hop by hop through Network Explorer's Layer 2 and STP model, naming the first failing hop and stating uncertainty instead of inferring a path from geometry (principle 2).

## Phase E: blast radius and event readiness

Reverse dependencies from a wired failure to affected APs and SSIDs; event definitions and a readiness status built from Phases A–D.

## Phase F: client journey

- One bounded, maskable client snapshot per owner with short retention, instead of per-client items keyed by MAC.
- The Instant client table as walked does not include the associated AP or radio, so clients cannot be attributed to an AP yet; the column must be found in a capture first.
- Roaming is shown as sampled association changes unless the source provides events (principle 10).

## Phase G: vendors and optimisation

Additional vendor families (Ubiquiti UniFi, Cisco WLC and others) as evidence arrives, storage tuning from canary measurements, long-term capacity views and further RF analytics.

## Not carried over from the reviewed Aruba template

The global API-token relay, heuristic analytics presented as measurements, per-client items and "malicious" rogue severity are not adopted; see the [review](ARUBA_TEMPLATE_REVIEW.md#practices-that-wi-fi-explorer-will-not-carry-over).
