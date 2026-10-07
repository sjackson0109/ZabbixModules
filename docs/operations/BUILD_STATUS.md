# Offline continuation handoff

Status: initial alpha implementation, reviewed 7 October 2026. This is a working fixture-driven module/data pipeline, not a vendor-qualified monitoring release.

## Implemented

- Network Explorer frontend module and five widgets: Port Panel, Physical Topology, Interface Detail, Data Quality and Findings.
- Permission-filtered datasets, domain-qualified LLDP identity resolution, one-hop graph scope, LAG grouping, management CIDR annotations, peer navigation/highlighting and current-state CSV/JSON reports.
- Canonical schema and optional bounded Python SNMPv2c/v3 collector with fixture mode, explicit failure/completeness outcomes, alias preservation and default remote-identity suppression.
- Shared template contract, nine family handoff packs, unqualified profile metadata and portable dashboard recipes.
- LAB-only replay templates, inherited dashboards, native scalar/graph discovery and reproducible integration labs for Zabbix 7.0/7.2/7.4.
- Development setup/test scripts and deterministic copy-out packages.

## Verification

- Python 3.14.7: 50 unit/transport/template/package tests passed.
- Collector transport and normalisation tests also passed on Python 3.10 and 3.12; localhost SNMPv2c and SNMPv3 SHA256/AES128 roundtrips used disposable credentials.
- PHP: 64 dataset/policy/report/navigation checks and 28 topology/subnet checks passed.
- JavaScript: seven algorithm/manifest/export checks passed; Chromium DOM, escaping, keyboard, navigation, LAG and CSV checks passed.
- Real Zabbix 7.0.20, 7.2.7 and 7.4.3 labs exercise module registration, replay ingestion, LLD, native graphs, inherited dashboards, ordinary-user permissions, API/report behaviour and malformed/failing collection preservation. See [runtime evidence](../../lab/VERIFICATION.md).
- Ports are placed by stack member, slot and position from ENTITY-MIB, with media (copper, SFP, SFP+) from the MAU tables; the Port panel shows stack members as tabs and takes its state colours from the widget form.
- The spec's acceptance walkthrough (amber port, peer navigation, off-subnet switch, VLAN journey, STP root and blocking port, LAG as one link, a restricted viewer, a stopped agent) passes in Chromium against four simulated switches on 7.0.20, 7.2.7 and 7.4.3 (`lab/acceptance.cjs`).
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

Browser scripts require the externally installed Playwright test dependency and a compatible Chromium executable; see [lab instructions](../../lab/README.md). The production frontend itself uses no Playwright dependency or remote CDN.

## Next implementation threads

Use [the family handoff index](../../templates/specifications/FAMILY_HANDOFFS.md), [shared contract](../../templates/specifications/CONTRACT.md) and authoritative [schema](../../schemas/envelope.schema.json). Obtain sanitised model/firmware inventory and numeric-OID walks before implementing or claiming support for a family profile. Preserve existing monitoring coverage and qualify each producer against the module contracts.

Production vendor templates remain specifications; the generic standard-MIB native templates and the frontend read VLAN, STP and port capability (schema 1.1). Snapshot partitioning, coherent topology history, automatic duplicate-address conflict reporting, scheduled PDFs and business service provisioning are later scope. At the spec's 300-switch/15,000-port scale, synthetic data builds in under 3 s and renders in under 0.5 s; production performance, including Zabbix API and history latency, is not established. Candidate host retrieval currently applies a 301-host cap before domain filtering; larger mixed estates can therefore have incomplete peer coverage, with truncation reported.

No production host enrolment, private network scan, vendor qualification or customer credential access was performed.
