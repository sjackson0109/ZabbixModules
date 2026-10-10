# Changelog

All notable changes are recorded here. Versions follow [Semantic Versioning](https://semver.org/); the current version is in [`VERSION`](VERSION).

## [Unreleased]

### Added
- Monitoring → Network Explorer is now the network-wide view, with no global dashboard needed. With no parameters it draws every permitted switch as a Layer 2 topology; Site, Domain, Management subnet and Seed device narrow it; a View selector switches between Layer 2, Spanning Tree and VLAN; switches, links and link ends are selectable, with device, link and interface detail in one panel; findings, collection quality and CSV/JSON exports follow the same scope. The view, VLAN and selected interface are kept in the address.
- Site scope from the administrator-controlled `site` host tag, beside `ne.domain`. Selectors list only values on hosts the user can read.
- `NetworkScope` and `NetworkService::buildScope()`, one validated scope for the page, the JSON route, exports and widgets.

### Changed
- Topology layout v2 (page and Topology widget). Network Explorer uses a deterministic, topology-aware hierarchical layout instead of a square grid. Layer 2 is arranged in levels from a deterministic anchor in each connected component, preferring the current agreed spanning-tree root; Spanning Tree uses observed root ports to form a root-oriented hierarchy, keeps switches without a root-port path in a labelled unresolved area, and falls back to the Layer 2 placement when no root is agreed. Physical cross-links, including blocked ones, stay visible and are never inferred from placement. Components are laid out apart, a few barycentre passes reduce crossings, and positions stay put through selection, search, VLAN, trace, LAG and refresh changes.
- The topology has Zoom in, Zoom out, Fit topology and Reset view buttons, keyboard alternatives (+, −, arrows, F, 0) and background drag to pan, all inside a bounded canvas that no longer widens the page. Links stop at switch boxes, external peers fan out around their switch, selection adds a second outline, link ends and interface rings that do not rely on colour, long names end in an ellipsis, and a compact legend lists only what the drawing shows.
- Pull-request CI runs the Chromium renderer suite, with Playwright locked in `tests/browser/package-lock.json`.
- Zabbix 7.0, 7.2 and 7.4 compatibility labs run nightly, on pull requests that change the frontend, widgets, templates, schemas or lab, and before every release; a release is published only when all three pass.
- Release archives and `manifest.json` carry a signed build-provenance attestation beside `SHA256SUMS` (`gh attestation verify`).
- Every third-party GitHub Action is pinned to a commit SHA, with a test that keeps it so.
- The default Layer 2 view (page and Topology widget) marks the observed spanning-tree root bridge when the visible switches in its domain agree on it and its data is current. A disagreement marks none and is explained.
- The Topology widget's link details make both endpoint interfaces selectable; selecting one shows its interface detail and broadcasts its item, so a linked Interface Detail widget follows. Its view labels are now Layer 2, Spanning Tree and VLAN.
- Documentation matches the implementation: build status, decisions, design pack, frontend architecture and test plan mark superseded passages, the release process states that published releases are immutable and that the next release is 1.3.0, and a [roadmap](docs/network-explorer/ROADMAP.md) records the improvement programme, the backlog and the boundary between the frozen schema 1.0 collector and a future acquisition agent.
- Dashboard recipes are optional examples, not installation steps. The lab acceptance walkthrough runs on Monitoring → Network Explorer; its old fleet dashboard is gone, and a test-only widget fixture checks the Topology widget.

## [1.2.0] - 2026-10-08

### Added
- A tag-driven release workflow: pushing `vX.Y.Z` verifies the version, runs CI, builds the packages and publishes a GitHub release with checksums. `scripts/release.py` bumps every component version and moves the changelog for a release; see [RELEASING.md](docs/operations/RELEASING.md).
- Continuous integration for the Python, Node and PHP checks, on PHP 8.0 and 8.3 and Python 3.10 and 3.12.
- A `templates` release package with the native standard-MIB templates, schemas and dashboard recipes.
- A single `VERSION` file, with a test that keeps every module manifest, the collector and the template normalisers in step.
- A Duktape compile check for every JavaScript step in the native and LAB templates.
- 25G, 40G and 100G media types in the MAU capability table.
- Validation of LAG member state and mode.
- An MIT `LICENSE`, shipped in every release package.
- Optional `warnings` in schema 1.1 envelopes, shown in the Data quality widget and as an informational finding.

### Changed
- Schema 1.1 moved from `schemas/proposed/` to `schemas/`; it is the current schema, and 1.0 is still accepted.
- The collector names the exception class on stderr when a collection fails unexpectedly, and checks timestamps without optional packages.
- Widgets show a message instead of reading data when the Network Explorer module is disabled; the menu entry appears only for users who can open the page.
- The widget runtime and stylesheet have one source in `src/widget/`; topology search dims nodes instead of redrawing, and SVG colours follow the dark theme.
- Every finding has the same fields and one stable ID scheme.
- A normaliser error now produces a failed envelope instead of no envelope.
- The LAB replay templates discard failed collections the same way as the native templates.
- The restart trigger ignores the 497-day `sysUpTime` wrap.
- Collector runtime dependencies are pinned by hash.
- The Python collector is a frozen fallback on schema 1.0.
- A duplicate interface name, a row missing its status columns or an `ifNumber` mismatch no longer makes the whole interfaces dataset partial. The row is skipped or keeps unknown fields, and the snapshot stays current.

### Fixed
- A VLAN row without an interface no longer attaches to LLDP links with an unmapped local port.
- The CSV formula guard also applies to text that is not valid UTF-8.
- A failed inventory read is no longer reported as stale inventory.

## 1.0.0 scope

The first production-capable release covers the specification's acceptance criteria:

- Physical interfaces with state, speed and reduced negotiated speed; port placement by stack member, slot and media; configurable state colours.
- LLDP peers, navigation from a local port to its remote peer, and remote interface highlighting.
- Multi-switch physical topology with a configurable management subnet that annotates, and never hides, connected devices outside it.
- VLAN membership with tagged and untagged distinction, and inter-switch VLAN propagation.
- STP state overlay, and LAG members shown as one logical connection.
- Native Zabbix SNMP templates on standard MIBs for Zabbix 7.0, 7.2 and 7.4, plus an optional Python collector, all feeding one canonical model.
- Zabbix user permissions respected on every read, and collection failures and stale data shown distinctly.
