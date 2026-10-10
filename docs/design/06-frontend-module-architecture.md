# 06 — Frontend module architecture

Status: **implemented**, with the open items marked below (spec §24–29, §38, §40.6). This document started as the proposal for the module and five widgets; items since built are marked *Implemented*, replaced ones **Superseded**, and the remaining gaps point at the [roadmap](../network-explorer/ROADMAP.md).

## Packages

| Zabbix module | Type | Spec component | Exists | Changes needed |
|---|---|---|---|---|
| `networkexplorer` | module (page, services, exports) | data layer, Explorer page (network-wide view) | yes | *Implemented:* VLAN/STP readers and overlays, derived expected speed, the Explorer page as the fleet application (below). Open: default domain; separate display and identity budgets (roadmap PR D) |
| `neportpanel` | widget | Port Panel (§3.1, §9, §25) | yes | *Implemented:* semantic layer switch, VLAN selector, configurable colours, media-aware layout and stack tabs |
| `netopology` | widget | Physical Topology, VLAN and STP overlays (§6, §27–29) | yes | *Implemented:* VLAN and STP modes, VLAN path trace, topology-aware layout with fit/zoom/reset (roadmap PR C) |
| `neinterfacedetail` | widget | Interface Detail (§26) | yes | *Implemented:* VLAN, STP and capability sections; expected-speed source |
| `nedataquality` | widget | freshness and capability (§23) | yes | *Implemented:* all seven datasets |
| `nefindings` | widget | anomalies and exports | yes | *Implemented:* VLAN and STP findings |

Spec §38 names separate "VLAN Overlay" and "STP Overlay" components. These are implemented as **modes** of the Port Panel and Topology widgets, not separate widgets, so that one renderer serves all layers (spec §24 allows this). Each widget has a mode field, so a dashboard can still hold a dedicated "VLAN topology" widget instance.

## Data path

```text
Browser widget ──▶ widget view action (PHP, current user session)
                      │
                      ▼
               NetworkService ── DatasetReader ── ApiGateway (item.get + history manager,
                      │                              only for hosts/items this user can read)
                      ├── IdentityResolver  (LLDP/CDP peer → permitted host or placeholder)
                      ├── TopologyService   (edges, LAG grouping, scope, CIDR annotation)
                      ├── PortPolicy        (state, effective expected speed, colours)
                      ├── SpeedIntent       (effective expected speed and its source)
                      ├── VlanService       (port membership, edge carry/no-carry, VLAN findings)
                      ├── StpService        (bridges, port roles/states per link, STP findings)
                      └── ReportService     (findings, CSV/JSON exports)
```

This answers open decision 14: the frontend reads **dedicated structured items** (the canonical snapshots) through the user's own session. It does not query SNMP or call the API with a privileged token (spec §30, §37). Every request re-authorises; there is no shared cache across users.

Every widget refresh runs a full `NetworkService::build()` for its scope. That is deliberate for 1.0. The work is bounded by `Limits`: 300 drawn switches (`DISPLAY_HOSTS`), 1,000 identity candidates (`CANDIDATE_HOSTS`), 50,000 items and 6,000 snapshot items per read, and 64 MiB of history. The 300-switch synthetic fixture builds in about 1.5 s and renders in under 0.2 s; a seed in a 1,000-switch domain builds in about 0.5 s (`tests/perf`).

**Scope and identity (roadmap PR D).** `NetworkService::scopeHosts()` finds the primary hosts first: for the whole fleet, the permitted hosts with a Network Explorer device or interface item (`DataGateway::networkHostids()`, so servers and other devices never use up the budget); for a site or domain filter or a seed, the hosts that match. The identity candidates are every permitted host in the primary hosts' `ne.domain` values, found by domain tag. Candidates that are not drawn are read for their device and LLDP snapshots only (`DatasetReader::IDENTITY`), which is enough to resolve peers (including ambiguity between them) and to find a neighbour whose own LLDP names a drawn switch. Only drawn switches (primary hosts and, for a narrowed scope, their direct neighbours) are read in full. A scope with more than 300 drawn switches returns `scope.oversized` with its count and a message, and nothing else: no partial drawing, findings or quality. Exports refuse it with `scope_oversized`. A cache would have to be keyed per user and per scope to keep permissions exact, and would show stale state after a link change. Revisit this with a short per-user scope cache, or a single-host read for the Port Panel, if a real estate measures slower than the refresh interval.

Findings all come from `Finding::create()`: one shape (`id`, `hostid`, `interface_uid`, `edge_id`, `severity`, `rule`, `title`, `reason`) and one ID, a SHA-256 over rule, host, interface and link, so an ID stays stable across refreshes.

## Changes needed

### Port Panel

- **Layer switch** (spec §9): Physical, VLAN, STP and LLDP buttons in the widget toolbar, and a default layer field in the widget form.
  - *VLAN*: a VLAN selector populated from the host's `vlan` snapshot. Each port shows Access/untagged, Trunk/tagged, Trunk/native, Not permitted (forbidden or absent on a trunk) or Unrelated, as in the spec's example.
  - *STP*: an instance selector; each port shows state (forwarding, blocking, learning, disabled) and role (root, designated, alternate). Derived roles are marked.
  - *LLDP*: ports with a neighbour are highlighted and labelled with the peer name (or "external" or "undisclosed").
- **Configurable colours** (spec §3.1): widget form colour fields (`CWidgetFieldColor`) for each semantic state, defaulting to the table in [02](02-canonical-schema.md). Every state also has a label and an icon, so colour is never the only signal.
- **Layouts** (spec §3.1, §25): 24-port, 48-port and mixed copper/SFP/SFP+ come from the new `media` field and ENTITY-MIB positions. Stack members appear as tabs. Unknown models use generic grouped rows. Geometry is a profile setting, never per-port manual data. *Implemented:* the inventory walk places ports by member, slot and position (entAliasMappingTable and the containment tree), port capability reports `media` from the MAU tables, and the panel shows members as tabs when a host has more than one. Ports the agent does not place are grouped as unplaced, never guessed from names.

### Physical Topology

- **Layout engine**: ~~replace the current grid placement with **Cytoscape.js** (MIT licence, self-hosted inside the module, no CDN) using a force-directed layout (`cose`). Node positions persist per user in browser storage so a refresh does not reshuffle the graph.~~ **Superseded:** the renderer stays in-house SVG with no third-party graph library. Manual dragging is optional and never required (spec §27).
- **Layout v2** (roadmap PR C). Network Explorer uses a deterministic topology-aware hierarchical layout. Layer 2 is arranged from a deterministic component anchor, preferring the current agreed STP root where available. Spanning Tree uses root-port evidence to form a root-oriented hierarchy. Physical cross-links remain visible and are never inferred from placement.
  - `layoutTopology()` in `src/widget/runtime.js` is a pure function (no DOM): hosts and links in, `{nodes, components, bounds}` out. `graphLayout()` returns the nodes only.
  - Only links between two visible switches shape it; external and undisclosed peers are drawn afterwards as stubs fanned around their switch.
  - Connected components are placed separately and never overlap: rooted components first, then larger, then by natural name. Unlinked switches share a block at the end but remain separate components in the returned model. Blocks wrap into bands eight switches wide.
  - Levels are shortest hop counts from the anchor (Layer 2), or root-port hop counts from the observed root (Spanning Tree). A switch whose root-port chain does not reach the root, or whose root ports point to different upstream switches, goes to a labelled unresolved area (conflicting evidence never picks a parent); a component with no agreed root uses the Layer 2 placement. Each level is ordered by four down-and-up barycentre sweeps, starting from the previous x position when there is one, then natural name and host ID.
  - Layer 2 and VLAN share one placement, Spanning Tree has another; each is kept in page state with a signature of its visible switches, internal links and (Spanning Tree) root and root-port evidence, and laid out again only when that changes.
  - Pan and zoom change only the SVG `viewBox` (world coordinates never change), kept per placement; the canvas is bounded, so the page never scrolls sideways.
- **Scale**: at about 300 switches, collapse by site or stack, filter by scope and use level-of-detail labels. Budget: first render within 5 seconds at p95 for 300 nodes and 1,000 links. This must be measured with a generated fixture before release.
- **VLAN mode** (spec §10, §28): select a VLAN, then:
  - participating switches are highlighted;
  - a link is solid when both ends carry the VLAN, broken-red when the physical link exists but one end does not permit it ("Physical link: YES / VLAN 49: NO"), and grey when neither carries it;
  - a **path trace** from a chosen switch walks carrying links and marks the first link where propagation stops, with the reason (Appendix A VLAN journey).
- **STP mode** (spec §11, §29): blocking ports drawn on link ends, root bridge marked, root paths highlighted. Physical links stay visible because STP is an overlay (spec §11).
- **Management subnet** (spec §7): unchanged. Out-of-scope devices stay visible and are flagged. Missing and multiple management addresses are separate findings.

### Defaults that block out-of-the-box use

- **Domain tag** (open, not implemented): peer matching needs an `ne.domain` tag on every host, and no tag means no matching (`domain_missing`). Proposal: a host with no tag belongs to the `default` domain, and tags are only needed where IP ranges overlap between customers.
- **Expected speed**: *Implemented:* the derived expectation from [02](02-canonical-schema.md) (`SpeedIntent::derive()`), not explicit policy only.

### Explorer page: the network-wide view

Network Explorer's network-wide view is available directly from `Monitoring → Network Explorer`. Global dashboards are optional custom compositions and are not required for ordinary Network Explorer use.

```text
Monitoring -> Network Explorer   network or site investigation: multi-switch Layer 2 topology, STP and VLAN
                                 views, selection detail, findings and collection quality; no dashboard
Host -> Host dashboard           one switch: Port panel, interface detail, host-local topology, findings;
                                 inherited from the template
```

- **One data path.** `networkexplorer.view` calls `NetworkService::buildScope()` with a `NetworkScope` (seed host IDs, `site`, `domain`, management CIDRs), the same service the widgets, the JSON route and exports use. `build()` keeps the widgets' seed-and-CIDR signature. Site and domain filters become exact `site` / `ne.domain` tag conditions in the user's own `host.get`, so they narrow the permitted population and cannot widen it. The primary hosts (seeds, or hosts passing the filters) plus the permitted hosts of their matching domains are read for peer resolution; the response keeps the primary hosts and their one-hop neighbours. A neighbour at another site is kept as context (`outside_site`). Selector values come from `NetworkService::scopeOptions()`, the tags of readable hosts only.
- **One renderer, two hosts.** The topology engine in `src/widget/runtime.js` serves the Topology widget and the page (`render(…, 'explorer')`, started by `mountExplorer`). `scripts/sync_widget_assets.py` copies it into each widget and into `networkexplorer/assets/`; no module loads another module's assets.
- **Selection model.** Switch nodes, links and link ends are buttons (pointer, Enter, Space). The selection lives in page state (`state.selection`): a switch shows identity, health and interfaces without choosing an interface; a link shows both endpoints per member; an endpoint shows interface detail for that exact `hostid` + `interface_uid`. On a dashboard the widget also broadcasts the standard `_hostid` / `_itemid`, so an Interface Detail widget follows a selected link end; the page uses direct callbacks and broadcasts nothing.
- **Root bridge.** `stpRoots()` takes the root from `bridge_id == root_bridge_id` (`StpService::split()`), per matching domain. Layer 2 marks it only when every visible switch in the domain agrees and its STP data is current; Spanning Tree also marks a root with older data. A root outside the visible scope is named, not drawn; a disagreement marks none in Layer 2 and shows each self-declared root as disputed (☆) in Spanning Tree, alongside the `stp_root_disagreement` finding. Layout position never decides it.
- **State in the address.** `site`, `domain`, `management_cidr`, `hostid`, `view`, `vlan`, `interface_hostid` and `interface_uid`. Graph placements, the pan and zoom view, LAG expansion and the trace source stay in the page.

### Navigation (spec §5)

Unchanged and already tested: the peer link opens the peer's host dashboard with a validated `#ne={hostid,uid}` fragment, and the destination Port Panel highlights that interface and shows the origin breadcrumb.

### Maintainability

`runtime.js` and `widget.css` have one source in `src/widget/`. Zabbix serves a module's assets only from its own directory, so `scripts/sync_widget_assets.py` copies them into each widget; the copies are committed, and the dev checks, CI and a Node test fail if any copy drifts. Edit the source, then run the script.

## Native widgets reused

Problems, item history graphs, availability and the Host navigator stay native (spec §24 says the structure may follow Zabbix's architecture). Existing maps are not reused (open decision 15, default): Zabbix maps need manually placed elements, which conflicts with spec §27 and §37.
