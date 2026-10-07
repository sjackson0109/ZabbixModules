# 03 — Zabbix template architecture

Status: **proposed, for review** (spec §21, §22, §40.3). This replaces the "LAB replay only" position in `templates/README.md`. Generic standard-MIB templates are built *first* and tested against simulated agents. Vendor profiles add only differences once walks prove them.

## Layers

```text
Host
 └── Network Explorer - Profile - <vendor/model family>     (exactly one per host)
      ├── Network Explorer - Base                            (always)
      ├── Network Explorer - Interfaces                      (always)
      ├── Network Explorer - Port Capability [MAU | LLDP-dot3]
      ├── Network Explorer - LLDP [standard | + CDP]
      ├── Network Explorer - VLAN [Q-BRIDGE | Cisco VTP | collector]
      ├── Network Explorer - STP [BRIDGE/RSTP | MSTP | collector]
      ├── Network Explorer - LAG [IEEE8023 | ifStack static]
      └── Network Explorer - Host dashboards
```

- **One producer per dataset per host.** Each bracketed option is a separate template that owns the same canonical keys. A profile links exactly one option per dataset, so producers can never collide (spec §21: vendor templates complement rather than duplicate).
- **Profiles are thin.** A profile template contains no items. It links producer templates and sets macros: capability flags, intervals, `max_repetitions`, LLDP local-port rule and port-panel geometry ID.
- **`Network Explorer - Profile - Generic standard MIB`** links the standard producers. It is the default for any unqualified model. Datasets the device lacks report `unsupported` and never break the others (spec §31).

Naming follows spec §21 with the project name in place of "Network Device".

## Item flow per dataset

```text
ne.raw.<dataset>                SNMP agent item, walk[oid,...], history 0d
   │  preprocessing: "Check for not supported value" → custom value __NE_COLLECTION_FAILED__
   ▼
ne.<dataset>.attempt            dependent, TEXT, history 7d
   │  JavaScript: SNMP walk → canonical envelope (ok | partial | failed | unsupported)
   ├──▶ ne.<dataset>.snapshot      dependent, TEXT, 7d — JS throws unless status=ok,
   │                               then "does not match __NE_DISCARD__" discards it, so only complete data lands
   ├──▶ ne.collection.status[<dataset>]    dependent, 0..3
   ├──▶ ne.collection.success[<dataset>]   dependent, unixtime, discarded unless ok
   └──▶ LLD rule (interfaces only), fed from the snapshot so partial data never deletes ports
```

Key points:

- **Failures are visible without a collector, in two ways.** Spike 1, partly answered in the lab on 7.0.20: "Check for not supported value" is meant to turn an SNMP error the agent returns into the value `__NE_COLLECTION_FAILED__`, so the attempt item records `failed`. That path imports on all three versions and is unit-tested, but the lab has not yet forced such an error. A timeout or wrong community is different: Zabbix treats it as a network error, marks the host's SNMP interface unavailable and processes no value at all, so no attempt is recorded. In both cases the last good snapshot stays untouched and the stale trigger fires once `{$NE.<DATASET>.STALE}` passes. The frontend therefore reads the SNMP interface availability alongside the attempt items and reports `agent_unreachable` from it.
- **JavaScript steps cannot discard on failure.** Zabbix offers no custom on-fail for JavaScript steps and an import silently drops one. Each gate returns the sentinel `__NE_DISCARD__` and a following "Does not match regular expression" step discards it. Per-port scalars return an explicit unknown (speed 0, status 4, duplex `unknown`) rather than discarding, because a discarded value never clears an item that is already unsupported.
- **Canonical JavaScript is shared.** The JS normaliser for each standard dataset is one source file in `templates/source/js/`, unit-tested in Node against the captured `.snmprec` fixtures, and embedded into the generated YAML. The same code therefore runs in tests and in Zabbix.
- **Self-contained walks.** Each raw walk includes its own join columns (see [04](04-snmp-acquisition-matrix.md)).

## Per-dataset contents

| Template | Masters (interval macro) | Canonical items | LLD and scalars | Triggers (all macro-tunable) |
|---|---|---|---|---|
| Base | `ne.raw.system` (1h) | `ne.device.snapshot` | — | collection failing; device rebooted (uptime reset) |
| Interfaces | `ne.raw.if.inventory` (1h), `ne.raw.if.state` (60s), optional `ne.raw.if.counters` (60s) | `ne.interfaces.inventory`, `ne.interfaces.state` | Interface LLD from inventory: `ne.if.oper/admin/speed/duplex[{#IFUID}]`, traffic and errors per port | unexpected down (only where `{$NE.IF.MONITOR:"<name>"}`=1 or an LLDP peer is a bridge); sustained speed or duplex degradation; error-rate |
| Port Capability | `ne.raw.if.capability` (15m) | `ne.port_capability.snapshot` | — | — |
| LLDP | `ne.raw.lldp` (5m) | `ne.lldp.snapshot` | — | neighbour lost on an uplink (optional) |
| VLAN | `ne.raw.vlan` (10m) | `ne.vlan.snapshot` | None by default. No VLAN × port items (avoids item explosion). | VLAN collection failing |
| STP | `ne.raw.stp` (2m) | `ne.stp.snapshot` | Per instance: root bridge ID, topology-change count | root bridge changed; topology changes above rate |
| LAG | `ne.raw.lag` (5m) | `ne.lag.snapshot` | Per LAG: selected member count | member not distributing (when LACP state is exposed) |
| Host dashboards | — | — | Template dashboards: Overview, Connectivity, VLAN, STP, Diagnostics | — |

Cross-host findings, such as a VLAN missing on one end of a trunk or a duplex mismatch between two monitored devices, are computed by the frontend at read time and shown in the Findings widget. They are not native triggers, because a template item cannot read another host. If alerting on them is needed later, it becomes a separate, permission-reviewed design.

## Macros

| Macro | Default | Purpose |
|---|---|---|
| `{$NE.<DATASET>.INTERVAL}` | per table above | Polling cadence (spec §22) |
| `{$NE.<DATASET>.STALE}` | 3 × interval | Freshness threshold (spec §23) |
| `{$NE.<DATASET>.ENABLED}` | 1 | Profile capability flag |
| `{$NE.IF.EXPECTED_SPEED:"<ifName>"}` | 0 (derive) | Per-port override of the derived expectation |
| `{$NE.IF.EXPECTED_DUPLEX:"<ifName>"}` | `auto` | Per-port duplex policy |
| `{$NE.IF.MONITOR:"<ifName>"}` | 0 | Alert when this port goes down |
| `{$NE.IF.ERROR_RATE.MAX}` | 1/s | Error state threshold |
| `{$NE.SNMP.MAX_REPETITIONS}` | 25 | Bulk tuning per profile |
| `{$NE.PANEL.GEOMETRY}` | `auto` | Port panel layout ID |

Interface UIDs, not names, are used in item keys. Macro contexts use the interface name because that is what an operator types.

## Coexistence with existing templates

Section 39 items 4–7 ask what is already monitored. The inventory export answers this per host.

- **Phase A (companion):** link Network Explorer templates *alongside* existing templates. Keys are in the `ne.*` namespace, so there are no conflicts. The cost is one extra set of table walks per host, which is measured during the canary.
- **Phase B (replace):** once a profile is qualified, the existing vendor template's interface and neighbour items are retired by the administrator. Health items the spec does not cover (CPU, memory, fans, PSU) stay in the existing templates or move into the profile, decided per family in the coverage CSV.

No template is linked, unlinked or replaced automatically.

## Build and export

Built: `templates/source/datasets.json` lists each producer (walk roots, keys, intervals) and `templates/source/js/` holds the shared normalisers. `python templates/generate_snmp.py` writes `templates/native/<version>/network_explorer_snmp.yaml` for 7.0, 7.2 and 7.4 with stable UUIDs, and `--check` fails if they are stale. `tests/unit/test_native_templates.py` runs the generated preprocessing chains in Node against the synthetic switch walks. `lab/native_snmp.py` imports them into the Docker lab and polls simulated switches; see `lab/VERIFICATION.md`. The existing LAB replay template stays as a test fixture.
