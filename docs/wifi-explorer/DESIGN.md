# Wi-Fi Explorer design (Phase A)

How Phase A meets the [requirements](REQUIREMENTS.md). Section numbers refer to that document.

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

Network Explorer's switch, VLAN and STP interpretation is not duplicated (principle 6). Phase C links Network Explorer's own LLDP producer to AP hosts rather than parsing LLDP a second time.

## Acquisition owners (sections 20 and 21)

An **owner** is a Zabbix host that carries a Wi-Fi producer. For Aruba Instant that is one host per cluster, pointed at the floating virtual-controller address, because only the elected VC lists the cluster's APs and radios (see the [Aruba review](ARUBA_TEMPLATE_REVIEW.md)).

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

Measured on the synthetic lab envelopes (about 115 bytes per AP state row, 175 per AP inventory row, 130 per radio inventory row and 240 per radio state row). Each dataset stores both its attempt and its last complete snapshot. For one cluster of 100 APs and 200 radios at the default intervals:

| Dataset | Envelope | Written per day | Held (history) |
|---|---|---|---|
| `ap_state` | ~12 KB | ~7 MB | ~7 MB (1 d) |
| `radio_state` | ~48 KB | ~28 MB | ~28 MB (1 d) |
| `ap_inventory` | ~18 KB | ~0.9 MB | ~6 MB (7 d) |
| `radio_inventory` | ~26 KB | ~1.3 MB | ~9 MB (7 d) |

About 37 MB written and 50 MB held per 100-AP cluster before database compression. These are estimates from synthetic rows; the release gate (section 35) still needs a measurement on a representative canary. Radio state dominates; lengthen `{$WE.RADIO.STATE.INTERVAL}` before shortening history if it is too much.

## Verification

- `tests/unit/test_wifi.py`: normalisers in Node over the synthetic VC and member walks, schema validation, identities, band ambiguity, unsupported and failed outcomes, generated templates (current, no credentials, no per-client items, ES5 for Duktape).
- `tests/php/wifi.php`: reader and model fed by the real normaliser output: hidden owners, duplicate owners, member APs, stale state, unreachable SNMP, rejected envelopes.
- `tests/integration/zabbix_runtime.py`: the template imports on Zabbix 7.0/7.2/7.4, and a restricted viewer sees only the readable cluster on the page and the data route.
- `qualify.py --product wifi matrix --check` in CI.
