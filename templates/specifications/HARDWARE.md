# Hardware health

The `hardware` dataset (canonical schema 1.2, `schemas/envelope-1.2.schema.json`) reports overall status, CPU, memory, power supplies, fans and temperature sensors. It comes from vendor MIBs only: no standard MIB in the captured switches carries it, and ENTITY-SENSOR-MIB was absent on all 17. Power over Ethernet is a dataset of its own ([POE.md](POE.md)).

## Rules

- **The device decides.** A state is the device's own verdict (RlEnvMonState, EnvMonState, boxServices item and temperature states, rlPhdUnitEnvParamMonitorTemperatureStatus, Dell-Vendor productStatusGlobalStatus), mapped to `ok`, `warning`, `critical`, `shutdown`, `not_present`, `not_functioning`, `unavailable` or `unknown`. The templates never invent a threshold. Warning and critical temperatures are reported only where the device publishes them (`warning_c`, `critical_c`), and the emergency-shutdown temperature where a MIB gives only that (`shutdown_c`, CISCO-ENVMON-MIB).
- **Identity comes from the index.** UIDs are `kind-<index>` built from numeric table indexes, never from descriptions. Duplicate descriptions cannot merge two parts, and a UID is always safe as `{#HWUID}`.
- **Stack units.** RADLAN rlEnv and ENTITY indexes carry the unit from bit 26 up (`index >> 26`). The low byte numbers the fan (from 0x81) or supply (from 0x41) within the unit, matching the `fanN_unitM` / `psN_unitM` descriptions. DNOS boxServices tables are indexed by unit and item, and give the unit in their own column.
- **States are stored when they change, readings every poll.** Part states and the overall status are stored on change and every `{$NE.HEARTBEAT}`; CPU, memory, temperature and fan speed are readings, stored at every poll (every `{$NE.HARDWARE.INTERVAL}`, 5m) with `{$NE.TRENDS}` of trends. The stored `ne.hardware.snapshot` keeps names, states and thresholds; its readings are null, so it changes only when a part does.
- **Layouts are checked, not assumed.** `rlPhdUnitEnvParamTable` has a 24-column layout (CISCOSB-Physicaldescription-MIB: temperature 10, sensor status 11, thresholds 12 and 13, uptime 14, verdict 16, fan speeds 18-23) and a 14-column one (Dell-Physicaldescription-MIB, SG300 1.4: temperature 9, status 10, uptime 11, verdict 13). A producer accepts a row only when its TimeTicks column is where its layout puts it. Otherwise the snapshot is `partial` with `layout_mismatch` and no temperature is reported (`tests/unit/test_hardware_normalisers.py` covers both directions).
- **Present parts only.** Discovery creates items for parts the device reports present and readable. An empty fan or supply slot, a fanless unit's fan rows, and a temperature sensor the device cannot read create none. A discovered part that later reports `not_present` raises "is no longer present".
- **Not measured is not zero.** rlCpuUtil returns 101 when measurement is off; values outside 0-100 become null, and the scalar keeps its last value. Fan speed is stored as the device reports it, because neither MIB gives a unit.

## Producers

| Template | Raw key | Sources | Captures |
|---|---|---|---|
| `ne_cisco_small_business_switch` | `ne.raw.hw.ciscosb` | CISCOSB rndMng CPU (1s, 1m, 5m), rlPhdUnitEnvParamTable (24 columns), rlEnvMonFanStatusTable, rlEnvMonSupplyStatusTable | SG350-10MP, SG350-28P (2.5.7.85, 2.5.9.54), SG350X-48P, SG350XG-24F, CBS350-8FP-2G, CBS350-8FP-E-2G, CBS350-24P-4X (two-unit stack), CBS350-24FP-4X, C1200-24P-4X, C1300-24P-4G (4.1.3.36, 4.1.7.17) |
| `ne_cisco_sg300_switch` | `ne.raw.hw.ciscosb.v1` | The same tables, 14-column environment layout | SG300-28PP 1.4.11.5. The temperature sensor reports unavailable, so it is not discovered. There are no supply rows. |
| `ne_dell_n_series_switch` | `ne.raw.hw.dnos6` | DNOS-SWITCHING-MIB CPU (5s, 60s, 300s) and memory (KB), DNOS-BOXSERVICES fans, supplies and temperature sensors, Dell-Vendor global status | N1548P 6.8.1.9, N4064 6.5.4.23 |
| `ne_dell_x_series_switch` | `ne.raw.hw.dellx` | RADLAN rndMng CPU, rlPhdUnitEnvParamTable (14 columns), rlEnv fans and supplies, Dell-Vendor global status | X1052 3.0.1.9. Both supplies report notPresent on a running unit, so no supply is discovered. |
| `ne_cisco_cbs220_switch` | `ne.raw.hw.envmon` | CISCO-ENVMON-MIB ciscoEnvMonTemperatureStatusTable, ciscoEnvMonFanStatusTable and ciscoEnvMonSupplyStatusTable. No CPU, memory or stack unit: the MIB has none. | None: CBS220-24P-4G 2.0.2.15 answers no-such-object. **Shipped disabled.** |

The CBS220 runs Realtek-based firmware: its private OIDs sit under enterprise 27282 (Realtek Semiconductor in the IANA registry), and it answers none of the CISCOSB or RADLAN tables (no-such-object on every one in the CBS220-24P-4G 2.0.2.15 capture). Cisco's [data sheet](https://www.cisco.com/c/en/us/products/collateral/switches/business-220-series-smart-switches/datasheet-c78-744915.html) lists CISCO-ENVMON-MIB among its MIBs, so `ne_cisco_cbs220_switch` carries a producer for it, built from the module in `mib/cisco/`. The 2026-11-23 capture walked `1.3.6.1.4.1.9.9.13` and the switch answered no-such-object, as a forum report said of the older SF/SG220 series. It has no other hardware source either: ENTITY-SENSOR-MIB, HOST-RESOURCES-MIB and UCD-SNMP-MIB are absent too. The qualification matrix records CBS220 hardware as Unsupported on 2.0.2.15. The producer stays in the template, disabled, as a frame of reference for a model or firmware that answers the MIB; it has run only on a synthetic walk. To qualify such a firmware, capture it with `capture_walk.py --extra-subtree 1.3.6.1.4.1.9.9.13` (the usual sanitise and anonymise steps), replay it with `qualify.py classify --template ne_cisco_cbs220_switch`, and enable the component in `source/datasets.json` only if the producer is complete.

## Not yet evidenced

- Cisco Small Business memory: the CISCOSB MIBs define no memory object.
- Supply power: Dell-Vendor envMonSupplyCurrentPower is captured but its unit is unconfirmed.
- Optics: CISCOSB-PHY-MIB, DNOS boxServicesFiberPortsOptics. No capture had an optic fitted.
- Multi-unit DNOS stacks.
- C1200/C1300 with fans: the C1300-24P-4G lists one fan on 4.1.3.36 and none on 4.1.7.17.
