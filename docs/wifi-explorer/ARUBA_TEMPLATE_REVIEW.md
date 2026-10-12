# Aruba wireless template review

Review of the operator's existing `Aruba Wireless` Zabbix 7.0 template (export dated 2026-10, 40 items, 14 discovery rules, 2 template dashboards) against the [Wi-Fi Explorer requirements](REQUIREMENTS.md). It is the first real wireless evidence for the project. The template itself is not committed: it is an operational template with its own history, and Wi-Fi Explorer ships its own producer (see [DESIGN.md](DESIGN.md)).

The review records what the template proves, what the canonical `we.*` datasets still need, and which data has a controller or virtual-controller (VC) owner. Nothing here qualifies Aruba: qualification needs a sanitised walk (see [Qualification](#what-qualification-needs)).

## What the template's own notes establish

The template description records live `snmpwalk` checks against five Aruba Instant APs in two clusters (firmware 8.13.2.0 and 6.5.4.11) and six captures. Those notes are operator evidence, and Wi-Fi Explorer relies on them as follows.

| Finding recorded in the template | Consequence for Wi-Fi Explorer |
|---|---|
| WLSX-WLAN-MIB (`1.3.6.1.4.1.14823.2.2`) does not exist on Instant firmware | Not used. Controller-based (Mobility Controller) APs are a separate, unqualified family. |
| AI-AP-MIB (`1.3.6.1.4.1.14823.2.3.3`) is the working source on Instant | The Aruba Instant adapter reads AI-AP-MIB only. |
| `aiAccessPointTable` (`.2.1`) and `aiRadioTable` (`.2.2`) are populated only on the elected VC or the cluster's floating AVC address, and empty on every member | The AP roster and radio data have exactly one owner: the Zabbix host pointed at the AVC address. A member host reports `unsupported`, never an empty site. |
| `aiVirtualControllerIPAddress` (`.1.1.5.0`) is the VC's address on the VC and `0.0.0.0` on members | Used as the ownership gate in every AP and radio normaliser. |
| `aiRadioChannel` (`.2.2.1.4`) is bit-packed: first byte is the primary channel, two bits of the second byte are the bonding indicator; the fourth state covers every width above 40 MHz | Channel is decoded; width is reported as `20`, `40` or `80+`, never `80` or `160`. |
| Radio index 0 reported 5 GHz channels and index 1 reported 2.4 GHz channels on every sampled radio (8 radios, dual-radio APs) | Band is derived from the decoded channel, not the index. A third radio reporting a channel below 178 is ambiguous (6 GHz channel numbers overlap 2.4 and 5 GHz) and is reported as an unknown band with a warning. |
| `aiRadioNoiseFloor` (`.2.2.1.6`) is a positive magnitude (94 means -94 dBm) | The normaliser negates it. |
| `aiRadioUtilization64` (`.2.2.1.8`) is a 64-second channel utilisation, 0 to 100 | Reported as observed 64-second utilisation, not airtime capacity. |
| `aiInterferAccessPointTable` (`.1.1.8`) works on every AP, is local to the observing AP, held 900+ rows on one AP, and excludes the fleet's own BSSIDs | Rogue and neighbour data (Phase B) is owned by each observing AP, not the VC, and needs a bounded, deduplicated snapshot. |
| Per-client 802.1X/PSK failures and DHCP timeouts are not in AI-AP-MIB | Authentication and association failure counts stay *not collected* for Instant over SNMP. They are not estimated. |

## Coverage against the canonical datasets

Owner: **VC** means only the AVC/VC host returns rows; **AP** means each AP answers for itself.

| Canonical dataset | Template source | Owner | Coverage | Gap |
|---|---|---|---|---|
| `we.device.snapshot` | `aiVirtualControllerIPAddress`, `aiControllerVersion`, SNMPv2-MIB system group | VC (role on every AP) | Role and cluster firmware | No cluster name collected. The template's earlier use of `aiVirtualControllerKey` was withdrawn; Wi-Fi Explorer does not collect that key. |
| `we.ap.inventory` | `aiAccessPointTable` columns 1 to 6 (MAC, name, IP, serial, model) | VC | Complete for Phase A | No per-AP firmware column is walked; AP firmware is reported unknown and the cluster firmware is shown on the controller. |
| `we.ap.state` | `aiAccessPointTable` columns 7 to 11 (CPU, free memory, uptime, total memory, status) | VC | Complete for Phase A | Memory units are not stated in the template; Wi-Fi Explorer keeps the raw values and reports only the used percentage. |
| `we.radio.inventory` | `aiRadioTable` columns 1 to 3 (AP MAC, radio index, radio MAC/BSSID) | VC | Complete for Phase A | No PHY type, spatial streams or supported standards. |
| `we.radio.state` | `aiRadioTable` columns 4, 5, 6, 8 and 20 | VC | Channel, width class, band, transmit power, noise floor, utilisation, status | Width above 40 MHz is one class. Columns 9 to 19 (frame, byte and error counters) exist but are not walked, so retry and error rates are not available yet. No DFS state. No per-radio client count. |
| `we.ssid.snapshot` | Instant SSID table (`.1.1.7.1`: name, status, client count, hidden) | VC | Name, status, hidden, client count | **No SSID-to-VLAN mapping** (WLSX VLAN columns are absent on Instant), no authentication or security mode, and **no per-AP or per-radio SSID membership**. The template does not walk AI-AP-MIB `.2.3`, which may hold a per-BSS table; that is unverified until a walk shows it. |
| `we.client.snapshot` | `aiClientTable` (`.2.4.1`) columns 1, 3, 5, 6, 7, 9, 13, 16 | VC for the cluster, AP for its own clients | MAC, IP, name, OS, SNR, byte counters, uptime | **No associated-AP or radio column is walked**, so clients cannot be attributed to an AP, radio or band, and no roaming timeline can be built from these columns. |
| `we.client.events` | None | | Not available | No roam or authentication events over SNMP; no traps captured. |
| `we.rf.neighbours`, `we.rogue.snapshot` | `aiInterferAccessPointTable` (`.1.1.8.1`: BSSID, SSID, channel string, PHY string, encryption, average SNR, classification) | AP | Observation per observing AP | Needs a bounded snapshot (900+ rows on one AP); channel is a string with width suffixes; classification is the device's own enum. |
| AP-side LLDP (Phase C) | `aruba.lldp.walk`: remote port ID, port description and system name only | AP | **Not usable as evidence** | No chassis ID or ID subtypes, and the discovery script derives its index from the last OID arc and invents names. Wi-Fi Explorer will instead link Network Explorer's standard LLDP producer to AP hosts, so AP-side and switch-side LLDP share one parser. |

## Practices that Wi-Fi Explorer will not carry over

These work for the template's own purpose, but conflict with the requirements' design principles, so Wi-Fi Explorer does not consume or copy them.

1. **Global API token relay.** `aruba.radios.relay` reads the VC's radio walk through the Zabbix API with a global secret `{$ZABBIX.API.TOKEN}`, two API calls per AP host every five minutes. Wi-Fi Explorer reads the VC's datasets in the frontend under the viewing user's own permissions, so it needs no relay and no token (principle 5).
2. **Heuristic analytics.** Authentication failures, deauthentication attacks, WPA compliance, roaming rate and session duration are estimated from client-count variance, and the template labels them as estimates. Wi-Fi Explorer never presents them as evidence (principles 1 and 10).
3. **Per-client items.** Client discovery creates items keyed by client MAC and named with the client's name and IP address. That puts personal identifiers in item names visible to anyone with read access to the host, and churns items as clients come and go. Wi-Fi Explorer will use one bounded, maskable client snapshot per owner with short retention (sections 22, 23 and 29).
4. **Rogue severity.** `Potentially malicious AP detected` is raised at High for the `unsecure` and `dos` classifications. `unsecure` describes an open network, not intent. Wi-Fi Explorer keeps the device's classification as evidence and does not call an AP malicious (principle 9).
5. **SNMP community in the template.** The export sets `{$SNMP_COMMUNITY}` to a non-default value at template level. A shared or committed template should leave credentials empty and set them on hosts or globally; Wi-Fi Explorer's template uses the host's SNMP interface settings and carries no credential.

## Ownership summary

| Data | Acquisition owner | Zabbix host to link |
|---|---|---|
| AP roster, AP state, radios, SSIDs, cluster clients | Elected VC | One host per cluster, pointed at the floating AVC address |
| Rogue and neighbour observations, AP-local clients, AP-side LLDP | Each AP | One host per AP (the template's AP host prototypes already create these) |

Wi-Fi Explorer never assumes a visible AP is a polled SNMP endpoint: an AP is visible because its owner's dataset lists it, and the viewer can read that owner (section 21).

## What qualification needs

The operator's captures (`snmpwalks/aruba/*.log`, six devices) are the right evidence, but are not in the repository. To move Aruba Instant from *Unqualified*:

1. One sanitised walk of an elected VC and one of a member AP, taken with `tools/inventory/capture_walk.py --profile aruba-instant --sanitise --sanitise-serials --sanitise-aliases`. The profile adds only the AI-AP-MIB objects Phase A reads (VC version and address, `aiAccessPointTable`, `aiRadioTable`) to the standard subtrees, and the sanitiser replaces AP names, AP serials and IP addresses (see the [qualification README](../qualification/README.md#wi-fi-evidence)). Client, SSID and rogue tables hold names of people and other organisations; they are not needed for Phase A and are left out until their phases.
2. Model and firmware for each walk.
3. Replay through the Aruba Instant normalisers (`qualify.py --product wifi classify`) and review.

Walks taken before sanitisation must not be committed, even temporarily.
