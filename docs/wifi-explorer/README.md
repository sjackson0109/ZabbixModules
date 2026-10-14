# Wi-Fi Explorer

Wi-Fi Explorer is the wireless sibling of Network Explorer: a permission-aware operational view of access points and radios inside Zabbix, built on Network Explorer's dataset services. It ships as a second frontend module (`frontend/wifiexplorer`) and a native SNMP template, and adds **Monitoring → Wi-Fi Explorer**.

It covers Phases A–F of the [roadmap](ROADMAP.md): the site/AP/radio model and overview; floor plans with AP placement and labelled interpolation; RF neighbours as each AP hears them; SSIDs with declared VLAN intent; each AP's wired uplink from LLDP; VLAN service paths from every AP to the spanning-tree root; the blast radius of a switch or port failure; event readiness; and clients with a masked, searchable list, a trace and a sampled timeline. Every value says whether it is observed, inferred, interpolated, declared, configured or estimated.

| Document | What it holds |
|---|---|
| [REQUIREMENTS.md](REQUIREMENTS.md) | The product requirements specification (sections 1–38, phases A–G). |
| [TEMPLATE_REQUIREMENTS.md](TEMPLATE_REQUIREMENTS.md) | Requirements every Wi-Fi access-point template must meet: items, envelope, datasets, capacity, macros, triggers, privacy, errors and acceptance. |
| [DESIGN.md](DESIGN.md) | How Phases A–F meet them: ownership, datasets, identities, freshness, permissions, configuration, uplinks, paths, impact, events, client privacy, storage. |
| [ROADMAP.md](ROADMAP.md) | Phases A–G as pull requests, with the gaps the Aruba review found. |
| [ARUBA_TEMPLATE_REVIEW.md](ARUBA_TEMPLATE_REVIEW.md) | Review of an existing Aruba Instant template: what AI-AP-MIB proves, what each canonical dataset still needs. |
| [Wi-Fi qualification matrix](../qualification/WIFI_MATRIX.md) | Which vendor sources are qualified, and on what evidence. |

## Install

1. Install the `networkexplorer` and `wifiexplorer` frontend modules side by side under the Zabbix frontend's `modules/` directory and enable both (Administration → General → Modules). Wi-Fi Explorer reuses Network Explorer's services; without it the page says so.
2. Import `templates/native/<7.0|7.2|7.4>/wifi_explorer_snmp.yaml`. It adds the template **Wi-Fi Explorer - Aruba Instant VC by SNMP** in the group *Templates/Wi-Fi Explorer*. Nothing is needed on the server or proxies.
3. Link the template to **one host per Aruba Instant cluster**, whose SNMP interface points at the cluster's floating virtual-controller (AVC) address. Set the SNMP community or v3 credentials on the host or globally; the template carries none.
4. Give the host a `site` tag (the same tag Network Explorer scopes by) so the page can narrow by site.
5. Optional, for RF neighbours: link **Wi-Fi Explorer - Aruba Instant AP by SNMP** to a host per AP at the AP's own address (same SNMP credentials). Name the host like the AP, or give it the AP's address, so Wi-Fi Explorer can tell which AP it observes.
6. Optional, for confirmed uplinks: link Network Explorer's LLDP collection to those AP hosts too, with the same `ne.domain` tag as the switches. Switch-side LLDP alone already finds most uplinks; both sides together confirm them.
7. Client privacy: the cluster template keeps partial client identifiers by default. To use pseudonymised IDs set `{$WE.CLIENT.IDENTIFIERS}` to `pseudonymised` and `{$WE.CLIENT.KEY}` to a long random value, as a **secret** macro on the host or globally. `full` stores MAC, IP address and client name; choose it only where policy allows.
8. Retention: each dataset's history is `{$WE.<DATASET>.HISTORY}` on the template (for example `{$WE.CLIENT.HISTORY}`), and the **Capacity** tab reads the trends of the `we.capacity.*` items, kept for `{$WE.CAPACITY.TRENDS}` (365 days by default). Capacity builds up hour by hour from the moment the template is linked.
9. A Super admin opens **Configure** on the page to add floors (a plan uploaded under Administration → General → Images), SSID intent (VLAN per SSID and site), events and known BSSIDs, then places APs from the **Floor plans** tab. Without SSID intent the VLAN paths, impact and event checks have nothing to check.
10. Users whose role can open Monitoring → Hosts see the menu entry, and see only the APs whose owner host they can read, and only the switches they can read in uplinks, paths and impact.

A host linked to a member AP instead of the AVC address reports its cluster datasets as *unsupported* and the page explains it once; it is never shown as an empty site.

## Status

Aruba Instant is **Unqualified**: only the synthetic lab walks are qualified (Lab simulated). See [what qualification needs](ARUBA_TEMPLATE_REVIEW.md#what-qualification-needs).
