# Wi-Fi Explorer design

How Phases A–F meet the [requirements](REQUIREMENTS.md). Section numbers refer to that document. Phase A (the model, inventory and overview) comes first; [Phases B–F](#phases-bf-floors-rf-ssids-paths-impact-events-and-clients) build on it.

## Principles carried over from Network Explorer

Wi-Fi Explorer does not have its own trust model. It reuses Network Explorer's, so the two products cannot drift:

| Concern | Reused from Network Explorer | Wi-Fi addition |
|---|---|---|
| Permissions | `ApiGateway`: every host, item and history read runs as the viewing user | None. No API token, no relay, no privileged reader (principles 4 and 5). |
| Envelope trust boundary | `EnvelopeValidator::envelope()`: size, schema version, dataset, common fields, outcome invariants | `WifiEnvelopeValidator`: Wi-Fi row contracts; any invalid row rejects the whole envelope. |
| Freshness and outcomes | `DatasetQuality::describe()`: stale is never current; a failed attempt keeps the last complete observation as retained evidence | Per-dataset TTLs matching the template's `{$WE.*.STALE}` macros. |
| Findings | `Finding::create()`: stable IDs | `WifiFinding`: affected object, evidence, last observed, freshness, confidence and remediation (section 26). |
| Scope | `NetworkScope::validTagValue()` and the `site` host tag | Site scope for Wi-Fi owners. |
| Templates | The walk → attempt → gated snapshot item pattern and its stale triggers | `templates/generate_wifi.py`. |

Network Explorer's switch, VLAN and STP interpretation is not duplicated (principle 6). Uplinks, VLAN paths and impact (Phases C–E) read Network Explorer's own model of the site through `NetworkService::buildScope()`, and AP-side LLDP comes from Network Explorer's LLDP producer linked to the AP host, resolved with Network Explorer's `IdentityResolver`.

## Acquisition owners (sections 20 and 21)

An **owner** is a Zabbix host that carries a Wi-Fi producer. For the generic AP template (`Wi-Fi Explorer - Generic AP`, standard MIBs only) it is one host per AP, a `standalone` owner of exactly that AP, its radios and SSIDs. For Aruba Instant it is one host per cluster, pointed at the floating virtual-controller address, because only the elected VC lists the cluster's APs and radios (see the [Aruba review](ARUBA_TEMPLATE_REVIEW.md)).

- An AP is visible because a readable owner's dataset lists it. Wi-Fi Explorer never assumes an AP is itself a polled SNMP endpoint, and creates no per-AP hosts in Phase A.
- When two readable owners list the same AP (a cluster linked twice, or a VC move), the owner with the newest complete inventory owns it, the AP is counted once, and an info finding names both sources.
- A member AP linked by mistake reports `unsupported` (`not_virtual_controller`) for every cluster dataset and the page raises one info finding with the fix. It does not raise stale or failure warnings.
- Owners are found by exact item key (`we.device.snapshot`, `we.device.attempt`) under the viewer's permissions, then narrowed by the `site` tag.

## Canonical datasets (`wifi-1.0`)

Schema: [`schemas/wifi-envelope-1.0.schema.json`](../../schemas/wifi-envelope-1.0.schema.json). The envelope is Network Explorer's (generation, attempted/observed time, status, completeness, capability, errors, warnings); `schema_version` is `wifi-1.0`.

| Dataset | Item key | Interval / stale / history | Rows |
|---|---|---|---|
| `device` | `we.device.snapshot` | 1 h / 3 h / 7 d | One: role (`virtual_controller`, `member`, ...), controller address, cluster firmware, uptime |
| `ap_inventory` | `we.ap.inventory` | 1 h / 3 h / 7 d | Per AP: `ap_uid`, MAC, name, IP, serial, model |
| `ap_state` | `we.ap.state` | 5 min / 15 min / 1 d | Per AP: status, uptime, CPU, memory used % |
| `radio_inventory` | `we.radio.inventory` | 1 h / 3 h / 7 d | Per radio: `radio_uid`, `ap_uid`, index, BSSID |
| `radio_state` | `we.radio.state` | 5 min / 15 min / 1 d | Per radio: status, band, channel, width class, transmit power, noise floor, utilisation and its window |
| `ssid` | `we.ssid.snapshot` | 5 min / 15 min / 1 d | Per SSID name: `ssid_uid`, enabled, hidden, client count (where the firmware reports it); VLAN and security are `null` (not exposed) |
| `client` | `we.client.snapshot` | 5 min / 15 min / 1 d | Per client, masked by policy: `client_uid`, MAC/IP/name as the policy allows, AP (by the AP address column), BSSID, SNR, connected time; at most 4,000 |
| `rf_neighbour` | `we.rf.neighbour` (per-AP template) | 15 min / 45 min / 1 d | Per detected BSSID, deduplicated (strongest SNR kept), at most the strongest 500: SSID, channel, band, width, encryption, SNR, the AP's own classification |

Intervals and staleness are host-overridable macros (`{$WE.AP.STATE.INTERVAL}`, `{$WE.AP.STATE.STALE}`, ...).

### Identities

- `ap_uid` = `ap-` + the first 24 hex digits of SHA-256(`ap:` + AP MAC). `radio_uid` = `radio-` + SHA-256(`radio:` + AP MAC + `:` + radio index). Both are stable across renames, IP changes and VC elections.
- The address bar carries only `site` and `ap=<ap_uid>`. A MAC address or AP name never reaches a URL. An invalid or unreadable `ap` selects nothing and says so.

### Values that are never guessed (principles 1 and 3)

- **Band** comes from the channel number. Channels 1–14 are 2.4 GHz and 32–177 are 5 GHz on APs with at most two radios; 178–233 are 6 GHz. On an AP with three or more radios a channel below 178 could be 6 GHz, so its band is `null` and the dataset carries `radio_band_ambiguous`. The overview counts it under *unknown*.
- **Width** above 40 MHz is one class, `80+`, because AI-AP-MIB does not distinguish 80 and 160 MHz.
- **Utilisation** is the observed 64-second channel utilisation, labelled with its window; one high sample is a finding that says it is not a trend.
- **State**: an AP or radio whose state dataset is stale, missing or absent from the latest state is `unknown` with the reason, never the last value seen. A stale "up" is never shown as healthy.

## Page (sections 8–10)

Monitoring → Wi-Fi Explorer, server-rendered with Zabbix's escaping HTML classes, so device strings never reach the page as markup:

1. Site selector (sites carried by readable owners only).
2. Overview tiles: APs (up, down, unknown, degraded), radios and bands, channel utilisation per band, findings, data sources.
3. A *Not collected yet* line naming the capabilities later phases add.
4. Selected AP: identity, state and radios with band, channel, width, utilisation, power, noise and observation freshness.
5. Findings, warnings first, each with reason, evidence freshness and a next step.
6. AP inventory.
7. Data quality per owner and dataset.

`wifiexplorer.data` returns the same model as JSON for tests and later widgets.

## Findings in Phase A

| Rule | Severity | Raised when |
|---|---|---|
| `wifi_ap_down` | Warning | Current state reports the AP down |
| `wifi_radio_down` | Warning | The AP is up and current state reports a radio down |
| `wifi_radio_high_utilisation` | Warning | An up radio's current utilisation is 70% or more |
| `wifi_dataset_failed`, `wifi_dataset_stale` | Warning | An owner dataset failed or is stale |
| `wifi_owner_not_controller` | Info | A member AP is linked instead of the VC |
| `wifi_owner_unsupported` | Info | The host answered without the data this template reads |
| `wifi_ap_multiple_owners` | Info | Two readable owners list the same AP |
| `wifi_radio_band_unknown` | Info | Radios whose channel does not prove the band |

## Budgets

At most 500 visible owners and 5,000 visible APs per view; Network Explorer's item, history and response budgets apply to the reader. A scope over a budget asks for a narrower site instead of drawing part of it.

## Storage (principle 14)

Measured on the synthetic lab envelopes (about 115 bytes per AP state row, 175 per AP inventory row, 130 per radio inventory row and 240 per radio state row). Each dataset stores its last complete snapshot and a record of every attempt; since Phase G a complete attempt is stored as a receipt without its rows (`data_omitted`, `data_rows`), because the rows are already in the snapshot, so rows are written once per poll instead of twice. For one cluster of 100 APs and 200 radios at the default intervals:

| Dataset | Envelope | Written per day | Held (history) |
|---|---|---|---|
| `ap_state` | ~12 KB | ~3.5 MB | ~3.5 MB (1 d) |
| `radio_state` | ~48 KB | ~14 MB | ~14 MB (1 d) |
| `ap_inventory` | ~18 KB | ~0.45 MB | ~3 MB (7 d) |
| `radio_inventory` | ~26 KB | ~0.65 MB | ~4.5 MB (7 d) |

About 19 MB written and 25 MB held per 100-AP cluster before database compression (37 MB and 50 MB before Phase G). Retention is configurable per dataset with `{$WE.<DATASET>.HISTORY}`. These are estimates from synthetic rows; the release gate (section 35) still needs a measurement on a representative canary. Radio state dominates; lengthen `{$WE.RADIO.STATE.INTERVAL}` before shortening history if it is too much.

## Verification

- `tests/unit/test_wifi.py`: normalisers in Node over the synthetic VC and member walks, schema validation, identities, band ambiguity, unsupported and failed outcomes, generated templates (current, no credentials, no per-client items, ES5 for Duktape).
- `tests/php/wifi.php`: reader and model fed by the real normaliser output: hidden owners, duplicate owners, member APs, stale state, unreachable SNMP, rejected envelopes.
- `tests/integration/zabbix_runtime.py`: the template imports on Zabbix 7.0/7.2/7.4, and a restricted viewer sees only the readable cluster on the page and the data route.
- `qualify.py --product wifi matrix --check` in CI.

## Phases B–F: floors, RF, SSIDs, paths, impact, events and clients

Each phase adds a tab to the page: **Floor plans**, **RF neighbours**, **SSIDs**, **VLAN paths**, **Impact**, **Events** and **Clients**. Every value on them carries one of these labels, so a reader can tell evidence from assumption (principle 3): *Observed*, *Inferred*, *Interpolated*, *Declared intent*, *Configured*, *Estimated* or *Not collected*.

### Configuration (sections 17 and 18)

Floors, AP placement, SSID intent, events and known BSSIDs are one JSON document kept in the module's own configuration (`module.update`), edited under **Configure** by a Super admin and validated whole before it is saved (`WifiConfig`): unknown keys are refused (so a PSK cannot be stored by mistake), every problem is reported at once, and the stored form must fit the module configuration's 65,535-byte column (64,000 bytes allowed). A document that fits is stored as plain JSON, about 750 AP placements; a larger one is packed into one string (deflated JSON of everything but the placements, followed by 22-byte placement records, base64), about 2,300 placements across 40 floors. A save that would not fit even packed is refused with its size. A packed document that is damaged is refused whole. A stored document that no longer validates is ignored entirely and the page says so; nothing is half-applied.

- **Floors**: per site and building, an optional Zabbix image (Administration → General → Images) as the plan, its aspect ratio read once on save, an optional width in metres.
- **Placements**: by `ap_uid` only, never by name or MAC, as fractions of the plan. A Super admin places an AP by clicking the plan.
- **SSID intent**: per SSID and site (or every site), the VLAN (1–4094), where it is expected (`site`, listed `floors` or listed `aps`) and, optionally, its bands.
- **Events**: name, site, SSID, start and end, optional floors, minimum APs, expected clients and the declared clients per AP.
- **Known BSSIDs**: networks the operator recognises (a neighbour's office).

A viewer only sees the floors, intent and events of the sites they can see, and the placements of APs they can see.

### Floor plans and RF (Phase B, sections 14 and 19)

- Overlays: status, band, channel, utilisation, clients, neighbours, retries. Markers show observed values at configured positions. Utilisation, clients and neighbours can also be drawn as a field interpolated between APs (inverse-distance weighting on a 40-cell grid, reach 18% of the plan width), labelled *Interpolated*, with a legend saying the shading is no measurement and not a predictive survey (principle 8). Retry rates are not exposed by AI-AP-MIB, so that overlay says *Not collected*.
- Channel reuse: pairs of placed APs on the same channel, drawn dashed, and solid where one AP actually hears the other in its RF data.
- RF neighbours come from a per-AP host with **Wi-Fi Explorer - Aruba Instant AP by SNMP** (the AP's own address), because each AP lists only what it hears. The observing AP is matched by the host's SNMP address, then by host name. Each BSSID is one row with every observer; *heard best by* is proximity evidence, not a location.
- Classes: *managed* (a visible radio's BSSID: observed; or the same first five octets: inferred), *known external* (configured), *known neighbour* (the AP says valid or known-interfering), *flagged* (the AP says unsecure, DoS or suspected-unsecure), *unknown*. The AP's own label is kept as evidence. Nothing is called malicious (principle 9).

### SSIDs and wired uplinks (Phase C, sections 10 and 11)

- `SsidService` merges each cluster's SSID table with declared intent. The VLAN is only ever declared: AI-AP-MIB on Instant does not expose it, and an SSID without intent says *Unknown: not declared*.
- Per expected AP, broadcasting is **inferred**: the SSID is enabled on the AP's cluster (current data), the AP is up, and a radio is up in an expected band. Instant zones can restrict an SSID to some APs and are not visible over SNMP.
- `UplinkService` finds each AP's switch port from two independent sides:
  - switch side: a switch's LLDP neighbour whose chassis ID (MAC subtype) is the AP's MAC, or whose management address is the AP's address; a system name alone never identifies an AP;
  - AP side: the AP host's own LLDP (Network Explorer's LLDP producer, linked to the AP host), resolved by Network Explorer's `IdentityResolver` with the same domain rules.
- States: *confirmed* (both sides agree), *switch only*, *AP only*, *conflicting* (they disagree: warning), *ambiguous* (several ports) and *unresolved* (info, only for APs that are up). The uplink carries the port's link state, VLAN membership and freshness from Network Explorer.
- Uplinks need a site (Network Explorer's model of that site) and are read only for the views that use them.

### VLAN service paths (Phase D, section 12)

`PathService` builds, per AP, the VLAN-independent walk from its uplink port to the spanning-tree root: on each switch its instance-0 (CST/CIST) root port, then the LLDP link or LAG from that port to the upstream switch's port, until a switch reports itself as root. For each SSID with a declared VLAN, every port on the walk is checked from current observations:

| Check | Fails as | Unknown as |
|---|---|---|
| Port state current and up | `port_down` | `port_state_stale`, `port_state_unknown` |
| VLAN in the port's current egress membership | `vlan_not_on_ap_port` (hop 1), `vlan_not_carried` | `vlan_not_collected`, `vlan_data_stale`, `vlan_membership_unknown` |
| Instance-0 STP state not blocking | `stp_blocking` | |

The result is *complete* only when every port passes and the walk reached the root; *failed* names the first failing hop (and says when an earlier hop was also unproven); *unknown* and *partial* say where evidence stops (`uplink_unresolved`, `uplink_stale`, `stp_stale`, `stp_not_collected`, `no_root_port`, `upstream_link_unresolved`, `upstream_link_stale`, `upstream_not_visible`, `stp_root_disagreement`, `loop`). With MSTP the walk follows the CIST: a VLAN that a bridge maps to another instance is *partial* (`mstp_instance`) and every MSTP path carries the caveat. The VLAN's gateway (Layer 3) is not checked. Failures are grouped into one warning per SSID and failing trunk (access-port failures one per SSID).

### Blast radius and event readiness (Phase E, sections 15 and 16)

- `ImpactService` takes a visible switch, or one of its ports, and reverses the uplinks and walks. Per AP: *loses service* (its own switch or port, or on its path with no alternative seen), *degraded* (a LAG member fails and another member is up), *reroute possible* (a switch between the AP and the failure has an STP alternate or backup port that is up; whether it carries each VLAN is shown, reconvergence is not simulated), *cannot assess* (uplink or path unknown, or the other LAG members' state is not current). Only alternates whose own state is current count, and when a whole switch fails an alternate leading back to that switch does not. It totals the SSIDs (lost of broadcasting, *all lost*), VLANs, floors and the clients associated now, labelled an estimate. Failing the root bridge says another root would be elected and does not predict the result. PoE is not collected.
- `EventService` gives each declared event a checklist and one status: *ready* (every check passes), *not ready* (one fails) or *unknown* (nothing fails, something unproven). Checks: SSID enabled at the event's own site (observed), APs up and SSID on air against the minimum (inferred), VLAN path complete for enough broadcasting APs (needs the wired model), declared capacity (serving APs × declared clients per AP; *unknown* rather than failed while APs of unknown state could still make it up), high utilisation now (a warning only; *not checked* when no expected radio reports utilisation) and credentials, always *not checked*. A not-ready event that has not ended is a warning finding; without the wired model an unknown event raises nothing.

### Clients (Phase F, section 13)

- The client snapshot is masked before storage by the template's `{$WE.CLIENT.IDENTIFIERS}`: `full` (MAC, IP, name), `partial` (manufacturer prefix only; the default) or `pseudonymised` (no identifiers, a keyed ID). `{$WE.CLIENT.KEY}` is a secret macro: user macros are expanded anywhere in a JavaScript preprocessing step, so the macro's name appears only in the step's call, never in a comment or a message, and the key never reaches the stored value (checked on Zabbix 7.4). The validator refuses an envelope whose rows hold more than its policy allows.
- Without `{$WE.CLIENT.KEY}`, a partial or pseudonymised client ID is a plain hash of the MAC address, which together with the shown manufacturer prefix can be reversed. The snapshot then carries the `client_key_missing` warning and the Clients tab says so; set the key wherever client identifiers matter.
- The page lists the clients associated now (a stale list is not shown as current), searchable only over what the policy kept, and addresses a client by its opaque `client_uid`; a MAC address is never accepted in the address bar.
- A selected client is traced: AP (by the AP address the client table reports), radio (exact BSSID: observed; same five-octet family on that AP: inferred), the AP's wired uplink and its VLAN paths. Aruba Instant does not report a client's SSID, so every SSID path of its AP is listed.
- The timeline reads the cluster's client snapshot history through the permission-checked API (`WifiHistory`, `API::History`) over the last 6 hours, at most 72 samples and 16 MB; values are read a few at a time so reading stops at the byte bound. A change of AP or BSSID between two samples is reported as an association change *between* those times (inferred), never as an exact roam (principle 10). Invalid samples are skipped. Changing `{$WE.CLIENT.KEY}` changes every client ID, so the timeline restarts.

### RF freshness

A neighbour heard only in stale RF snapshots is listed with when it was last seen and marked stale; it is not counted in the overview or the class counts, cannot raise a flagged finding, and does not mark two placed APs as hearing each other.

### Not exposed by the sources, so not shown

Beyond the items above: PHY, MIMO, DFS state, 80 versus 160 MHz width, and configured versus observed channel and power are not exposed by AI-AP-MIB on Instant, so none is shown or derived. Snapshots are text, so Zabbix builds no trends from them; since Phase G the numeric capacity items below carry the long-term view.

### Findings added in Phases B–F

| Rule | Severity | Raised when |
|---|---|---|
| `wifi_rf_flagged` | Warning | A current detection the AP itself labels unsecure, DoS or suspected-unsecure |
| `wifi_co_channel_managed`, `wifi_co_channel_external` | Info | An up radio's own AP hears another network on its channel at 25 dB SNR or more |
| `wifi_channel_overlap` | Info (inferred) | An up radio's own AP hears, at 25 dB SNR or more, a network in the same band on a different channel whose spectrum overlaps by the 802.11 channel plan (bonded block from the width; 2.4 GHz 40 MHz, 80+80 and unknown widths use only the primary 20 MHz, so overlap may be missed but is never invented) |
| `wifi_ssid_missing`, `wifi_ssid_disabled` | Warning | A declared SSID that the site's current clusters do not list, or list as disabled |
| `wifi_ssid_coverage_gap` | Warning | Expected APs that are down or have no radio up in a declared band (inferred) |
| `wifi_ssid_vlan_undeclared` | Info | An enabled SSID without intent: its VLAN, and so its path, is unknown |
| `wifi_uplink_conflict` | Warning | The AP's LLDP and a switch's LLDP name different ports |
| `wifi_uplink_ambiguous`, `wifi_uplink_unresolved` | Info | Several ports report the AP, or an up AP has no uplink evidence |
| `wifi_path_failed` | Warning | A declared VLAN stops at a named hop |
| `wifi_path_unproven` | Info | Some expected APs' paths are partial or unknown |
| `wifi_event_not_ready` | Warning | A declared event that has not ended fails a check |
| `wifi_event_unknown` | Info | Nothing fails but a check cannot be shown (only with the wired model read) |

### Storage added in Phases B–F

From the synthetic envelopes: about 155 bytes per SSID row, 255 per client row and 200 per RF detection row; like Phase A, each dataset stores its attempt and its snapshot. For one 100-AP cluster with 1,500 clients at the defaults the client dataset is about 380 KB per snapshot, roughly 110 MB written and held per day (1-day history) now that complete attempts are receipts (220 MB before Phase G); lengthen `{$WE.CLIENT.INTERVAL}` or shorten `{$WE.CLIENT.HISTORY}` first if that is too much. Per-AP RF snapshots are bounded to 500 rows (about 100 KB) every 15 minutes, about 10 MB per AP per day. SSID snapshots are negligible. As in Phase A these are estimates; the release gate still needs a canary measurement.

### Verification added in Phases B–F

- `tests/php/wifi_floors.php`, `wifi_wired.php`, `wifi_paths.php`, `wifi_impact.php`, `wifi_clients.php` run the real normalisers over the Wi-Fi lab walks (a cluster, lab-ap-01's own host and three switches) and cover hidden switches, stale STP and VLAN data, blocking ports, root disagreement, MSTP instances, LAG members, STP alternates, events, privacy policies and the sampled timeline.
- `tests/integration/zabbix_runtime.py` replays the lab into a real Zabbix, then checks the uplinks and paths on the data route and renders every tab as a restricted viewer.

## Phase G without hardware: capacity, storage, RF overlap, large sites (section 36)

The parts of Phase G that need no new vendor evidence. Vendor families and Aruba qualification wait for sanitised walks.

### Long-term capacity (section 16)

Each cluster template has 13 numeric items, dependent on the normalised envelope and discarded unless the observation is complete, so a failed poll is a gap and never a zero: APs up and down, radios up per band, average and peak channel utilisation per band, clients, and the most clients on one AP (`we.capacity.*`). History is `{$WE.CAPACITY.HISTORY}` (7 days) and trends `{$WE.CAPACITY.TRENDS}` (365 days), so a year of a cluster costs 13 hourly trend rows.

The **Capacity** tab reads those hourly trends through the API (`API::Trend()`, only for clusters the viewer can read) for the last 24 hours (hourly), 30 days (daily) or 12 months (monthly). A site value adds the clusters that reported in that hour; each period says how many of its hours had data, and one without data shows a dash. Per period: average clients, the busiest hour, the 95th-percentile hour, the busiest AP, APs up and down, and utilisation average, 95th-percentile hour and peak per band, beside client counts so a count is never read as capacity alone. Growth compares the last seven days with the seven before, only when both have data for at least half their hours. The year view reads peaks only, to stay within `WifiLimits::TREND_ROWS` (250,000); a scope beyond it says so instead of truncating.

Not covered yet: capacity per AP, radio, floor or SSID over time (it would need per-AP numeric items, which the per-cluster template avoids), throughput, retry and error rates (not exposed by AI-AP-MIB on Instant), and percentiles of single samples (trends keep hourly averages and peaks only).

### Storage

A complete attempt is stored as a receipt without its rows (see [Storage](#storage-principle-14)), and every dataset's history is a macro. The normalised envelope itself is not kept (`history 0`); it only feeds the attempt, snapshot and capacity items.

### Overlapping channels

`wifi_channel_overlap` (see the findings table) works out the spectrum each channel occupies from the 802.11 channel plan (`ChannelPlan`) and flags a strong neighbour in the same band whose channel differs but still overlaps. It is inferred from channel numbers and widths, not measured, and says so.

### Large sites

The configuration document is packed when it no longer fits as plain JSON (see [Configuration](#configuration-sections-17-and-18)), raising the practical limit from about 750 to about 2,300 AP placements. A save that does not fit is refused with its size.

### Verification added in Phase G

- `tests/php/wifi_capacity.php`: periods, gaps, growth, hidden clusters, the year view's keys and every unavailable reason. `tests/php/wifi_floors.php`: the channel plan, overlap findings, packing and damaged packed documents.
- `tests/browser/wifi.lab.cjs` runs in Chromium after the integration suite (required in the Compatibility workflow): every tab and capacity range, placing and removing an AP by clicking the plan, saving in the editor and reloading, and an event name with markup shown as text.
- On a real 7.4 lab with SNMP polling: receipts, the capacity items' values, the Capacity tab over inserted trend rows, and a packed configuration with 1,500 extra placements that loads, edits and saves again.
