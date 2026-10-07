# Design artefacts for review (spec §40)

The requirements specification asks for these seven artefacts to be reviewed before implementation continues. They are short by design. The longer background reasoning stays in [`docs/network-explorer/DESIGN.md`](../network-explorer/DESIGN.md), and [`REVIEW.md`](../network-explorer/REVIEW.md) explains why this set was written.

| # | Artefact | Status |
|---|---|---|
| 1 | [Vendor capability matrix](01-vendor-capability-matrix.md) | Hypotheses only; waiting on inventory and walks |
| 2 | [Canonical schema](02-canonical-schema.md) and [`schemas/proposed/`](../../schemas/proposed/) | Proposed 1.1, adds VLAN, STP and port capability |
| 3 | [Zabbix template architecture](03-template-architecture.md) | Proposed |
| 4 | [SNMP acquisition matrix](04-snmp-acquisition-matrix.md) | Proposed; OIDs marked *verify* need a MIB check |
| 5 | [Proxy script architecture](05-proxy-script-architecture.md) | Proposed; describes the existing collector |
| 6 | [Frontend module architecture](06-frontend-module-architecture.md) | Proposed |
| 7 | [Test plan](07-test-plan.md) | Proposed |

Tools for the first action in spec §40 (collect the vendor/model matrix) are in [`tools/inventory/`](../../tools/inventory/).

## Working assumptions until confirmed

These follow the specification where it differs from the earlier `DECISIONS.md`:

- VLAN and STP are part of the first production release (spec §35 criteria 10–13).
- Expected speed is derived from port and partner capability, with a per-port override (spec §3.2).
- Generic standard-MIB native templates are built before vendor profiles and before the Python collector is extended (spec §19).

Other open decisions (spec §39) use these defaults: one Zabbix host per stack; automatic topology layout; current state only, no topology history; no MAC/endpoint discovery in the first release; the frontend reads structured items; existing Zabbix maps are not reused.
