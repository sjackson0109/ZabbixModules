# Offline continuation handoff

Status, 10 October 2026: **1.2.0** is the latest published release (8 October 2026). The `work` branch is ahead of it: PR #12 made Monitoring → Network Explorer the network-wide application, a minor-version feature, so the next release is **1.3.0**. Its changes are under *Unreleased* in the [changelog](../../CHANGELOG.md) until it is cut. The current improvement programme and its pull-request sequence are in the [roadmap](../network-explorer/ROADMAP.md).

Everything below is tested against simulated switches only; no vendor or model has been qualified on real hardware.

## Implemented

- Network Explorer frontend module and five widgets: Port Panel, Physical Topology, Interface Detail, Data Quality and Findings.
- Monitoring → Network Explorer is the network-wide view: multi-switch Layer 2 topology with the observed STP root, Spanning Tree and VLAN views, site/domain/subnet/seed scope, switch, link and link-end selection with interface detail, and same-scope findings and quality. No global dashboard is needed; dashboard recipes are optional.
- Topology layout v2: deterministic hierarchical placement from each component's anchor (the agreed STP root where observed), a root-port hierarchy in Spanning Tree with an unresolved area for switches without a root-port path, separated components, stable positions, and fit/zoom/reset/pan with keyboard alternatives inside a bounded canvas.
- Permission-filtered datasets, domain-qualified LLDP identity resolution, one-hop graph scope, LAG grouping, management CIDR annotations, peer navigation/highlighting and current-state CSV/JSON reports.
- Canonical schema and optional bounded Python SNMPv2c/v3 collector with fixture mode, explicit failure/completeness outcomes, alias preservation and default remote-identity suppression.
- Shared template contract, nine family handoff packs, unqualified profile metadata and portable dashboard recipes.
- LAB-only replay templates, inherited dashboards, native scalar/graph discovery and reproducible integration labs for Zabbix 7.0/7.2/7.4.
- Development setup/test scripts and deterministic copy-out packages.

## Verification

- Python: 249 unit, transport, template, schema and package tests pass (`scripts/test-dev.sh`, and in CI on Python 3.10 and 3.12).
- Collector transport and normalisation tests also passed on Python 3.10 and 3.12; localhost SNMPv2c and SNMPv3 SHA256/AES128 roundtrips used disposable credentials.
- PHP: the service, topology, schema 1.1, lab-fixture and gateway-authorisation suites pass on PHP 8.0 and 8.3.
- JavaScript: the widget algorithm, manifest and export checks pass in CI (`node --test tests/browser/widgets.test.cjs`). The Chromium suite (`tests/browser/widgets.runtime.cjs`: DOM, escaping, keyboard, topology layout stability, fit/zoom/reset, selection markers, legend, no page overflow, port, node, link and link-end selection, VLAN and STP views, root marker, LAG, Explorer selection, CSV) runs in CI with Playwright locked in `tests/browser/package-lock.json`.
- Real Zabbix 7.0.20, 7.2.7 and 7.4.3 labs (`Compatibility` workflow: nightly, on pull requests that change the frontend, widgets, templates, schemas or lab, and before every release) exercise module registration, replay ingestion, LLD, native graphs, inherited dashboards, ordinary-user permissions, API/report behaviour and malformed/failing collection preservation. See [runtime evidence](../../lab/VERIFICATION.md).
- Ports are placed by stack member, slot and position from ENTITY-MIB, with media (copper, SFP, SFP+) from the MAU tables; the Port panel shows stack members as tabs and takes its state colours from the widget form.
- The acceptance walkthrough passes in Chromium against five simulated switches on 7.0.20, 7.2.7 and 7.4.3 (`lab/acceptance.cjs`, 18 steps): host dashboards (amber port, peer navigation, stack tabs, static LAG), then Monitoring → Network Explorer with no dashboard (default Layer 2 with the root marked, LAG, Spanning Tree, VLAN journey, switch, link and link-end selection, Open host dashboard, off-subnet switch, site and seed scope with matching findings, quality and export), the Topology widget on a test-only dashboard, and a restricted viewer. The stopped-agent step passes on the Explorer page on 7.4.3.
- Live browser tests exercised inherited dashboards, host/item broadcasts and peer-interface highlighting. These are synthetic lab hosts, not customer switches.

## Continue locally

Check out the `work` branch. Start at the root README, then use:

```sh
scripts/setup-dev.sh
scripts/test-dev.sh
sh scripts/test-compatibility.sh
python3 scripts/package.py
```

Python dependencies and Docker images must already be cached or supplied through a verified offline wheelhouse/image export for a completely disconnected machine. Generated packages and local lab credentials/state are deliberately not committed. Recreate them with the included scripts; do not copy another environment's credentials into Git.

The Chromium suite installs its locked Playwright with `npm ci` in `tests/browser/`; the lab walkthrough (`lab/acceptance.cjs`) still uses an externally installed Playwright. See [lab instructions](../../lab/README.md). The production frontend itself uses no Playwright dependency or remote CDN.

## Known limits

- One view draws at most `Limits::DISPLAY_HOSTS` (300) switches; a larger scope (fleet, site or domain filter, or a seed with its neighbours) is not drawn and states its device count, so it must be narrowed. Peers are resolved against up to `Limits::CANDIDATE_HOSTS` (1,000) permitted Network Explorer hosts in the scope's domains; a larger domain raises an `identity_candidates_truncated` warning.

## Next implementation threads

Follow the [roadmap](../network-explorer/ROADMAP.md) sequence. For vendor work, use [the family handoff index](../../templates/specifications/FAMILY_HANDOFFS.md), [shared contract](../../templates/specifications/CONTRACT.md) and the current [schema 1.1](../../schemas/envelope-1.1.schema.json). Obtain sanitised model/firmware inventory and numeric-OID walks before implementing or claiming support for a family profile. Preserve existing monitoring coverage and qualify each producer against the module contracts.

Production vendor templates remain specifications; the generic standard-MIB native templates and the frontend read VLAN, STP and port capability (schema 1.1). Snapshot partitioning, coherent topology history, automatic duplicate-address conflict reporting, scheduled PDFs and business service provisioning are later scope. At the spec's 300-switch/15,000-port scale, synthetic data builds in under 3 s and renders in under 0.5 s (layout v2 included: about 0.17 s for 300 switches and 1,000 links in headless Chromium, `tests/perf/render.cjs`); production performance, including Zabbix API and history latency, is not established.

No production host enrolment, private network scan, vendor qualification or customer credential access was performed.
