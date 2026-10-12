# Wi-Fi Explorer

Wi-Fi Explorer is the wireless sibling of Network Explorer: a permission-aware operational view of access points and radios inside Zabbix, built on Network Explorer's dataset services. It ships as a second frontend module (`frontend/wifiexplorer`) and a native SNMP template, and adds **Monitoring → Wi-Fi Explorer**.

It is at **Phase A** of the [roadmap](ROADMAP.md): canonical schemas, the permission-aware reader, the site/AP/radio model, the site overview, AP inventory and qualification scaffolding. SSIDs, clients, RF, floor plans, wired uplinks and VLAN service paths come in later phases; the page names them as *not collected yet* instead of showing zeros.

| Document | What it holds |
|---|---|
| [REQUIREMENTS.md](REQUIREMENTS.md) | The product requirements specification (sections 1–38, phases A–G). |
| [DESIGN.md](DESIGN.md) | How Phase A meets them: ownership, datasets, identities, freshness, permissions, reuse of Network Explorer, storage. |
| [ROADMAP.md](ROADMAP.md) | Phases A–G as pull requests, with the gaps the Aruba review found. |
| [ARUBA_TEMPLATE_REVIEW.md](ARUBA_TEMPLATE_REVIEW.md) | Review of an existing Aruba Instant template: what AI-AP-MIB proves, what each canonical dataset still needs. |
| [Wi-Fi qualification matrix](../qualification/WIFI_MATRIX.md) | Which vendor sources are qualified, and on what evidence. |

## Install

1. Install the `networkexplorer` and `wifiexplorer` frontend modules side by side under the Zabbix frontend's `modules/` directory and enable both (Administration → General → Modules). Wi-Fi Explorer reuses Network Explorer's services; without it the page says so.
2. Import `templates/native/<7.0|7.2|7.4>/wifi_explorer_snmp.yaml`. It adds the template **Wi-Fi Explorer - Aruba Instant VC by SNMP** in the group *Templates/Wi-Fi Explorer*. Nothing is needed on the server or proxies.
3. Link the template to **one host per Aruba Instant cluster**, whose SNMP interface points at the cluster's floating virtual-controller (AVC) address. Set the SNMP community or v3 credentials on the host or globally; the template carries none.
4. Give the host a `site` tag (the same tag Network Explorer scopes by) so the page can narrow by site.
5. Users whose role can open Monitoring → Hosts see the menu entry, and see only the APs whose owner host they can read.

A host linked to a member AP instead of the AVC address reports its cluster datasets as *unsupported* and the page explains it once; it is never shown as an empty site.

## Status

Aruba Instant is **Unqualified**: only the synthetic lab walks are qualified (Lab simulated). See [what qualification needs](ARUBA_TEMPLATE_REVIEW.md#what-qualification-needs).
