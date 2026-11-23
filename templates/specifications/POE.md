# Power over Ethernet

The `poe` dataset (canonical schema 1.2, `schemas/envelope-1.2.schema.json`) reports each power-sourcing unit and each PoE port. It comes from POWER-ETHERNET-MIB (RFC 3621), which every PoE-capable captured switch implements, and from a vendor table where one adds what the standard lacks. Every switch template collects it; a switch without PoE reports the dataset unsupported, which raises no alert.

## Rows

- **`pse`**, one per PSE group (`pethMainPseTable`): `power_w` (nominal budget, `pethMainPsePower`), `consumption_w` (`pethMainPseConsumptionPower`), `usage_threshold_pct` (`pethMainPseUsageThreshold`), `util_pct` (consumption as a share of the budget) and `port_count`. `state` is `pethMainPseOperStatus`: `on`, `off` or `faulty`. A group is a stack unit or a module (RFC 3621: 1 on a non-modular device). A group with no PSE ports is a stack slot without a unit and is `not_present`: the two-unit CBS350 stack lists four groups and calls the empty two faulty.
- **`port`**, one per PSE port (`pethPsePortTable`): `state` is `pethPsePortDetectionStatus` (`delivering`, `searching`, `disabled`, `fault`, `test`, `other_fault`), plus `admin_enabled`, `power_class` (0-4, only while delivering, as RFC 3621 says), `priority` (`critical`, `high`, `low`) and the five RFC counters (`mps_absent`, `invalid_signature`, `power_denied`, `overload`, `short`). `power_mw` and `power_limit_mw` come from a vendor table and are null without one.

## Rules

- **The device decides.** Faults are the device's own status. The usage alert compares `util_pct` with the device's own `pethMainPseUsageThreshold`, the threshold it uses for its own `pethMainPowerUsageOnNotification`; the templates add no threshold of their own.
- **A port joins to an interface only where the evidence shows how.** RFC 3621 does not map a PSE port to an ifIndex. In all 14 captured PoE walks (Cisco SB, CBS350, C1200, C1300, SG300, CBS220 and Dell N1548P) `pethPsePortIndex` is the ifIndex of a copper port on the same unit (`gi2/0/1` is group 2), so those templates join by ifIndex and name the port after its interface (`interface_uid`, `{#IFUID}`). The generic template, and the Dell X-Series, whose PoE models have not been captured, name a port `Port <group>/<index>` and claim no interface. A mapped port without an interface of that index is kept, named the same way, with the warning `port_unmapped`.
- **Consumption is what the device calls consumption.** The 350-class Cisco firmware (SG350, CBS350, C1200, C1300) reports in `pethMainPseConsumptionPower` the power it has allocated to its ports, which matches the sum of their `rlPethPsePortStaticPowerAllocation`: 249 W allocated against 81 W drawn on the captured CBS350-24FP-4X. The SG300 1.4 reports the power drawn there. Budget alerts follow the device's own figure, because that is what it denies new devices power against. The power each port draws is the per-port item.
- **Partial walks are partial.** A port row without a detection status, or a PSE table without its port table, makes the snapshot `partial` (`incomplete_row`, `port_table_missing`); a partial snapshot never feeds discovery.

## Producers

PoE is walked twice. Status (port detection, class, priority and fault counters; unit status, budget and threshold) is walked every `{$NE.POE.INTERVAL}` (5m) and feeds discovery and the alerts; power (unit consumption, and the watts each port delivers where the vendor reports them) every `{$NE.POE.POWER.INTERVAL}` (15m). The power walk also reads each port's enable and detection status, only to list the ports.

| Templates | Raw keys (status, power) | Sources | Captures |
|---|---|---|---|
| `ne__generic_switch`, `ne_dell_x_series_switch` | `ne.raw.poe`, `ne.raw.poe.power` | POWER-ETHERNET-MIB port and main PSE tables | Replayed on all 14 |
| `ne_dell_n_series_switch`, `ne_cisco_cbs220_switch` | `ne.raw.poe.ifindex`, `ne.raw.poe.power` | The same, status joined to IF-MIB by ifIndex | N1548P 6.8.1.9 (48 ports), CBS220-24P-4G 2.0.2.15 (24 ports) |
| `ne_cisco_small_business_switch`, `ne_cisco_sg300_switch` | `ne.raw.poe.ifindex`, `ne.raw.poe.power.ciscosb` | The same, plus CISCOSB-POE-MIB `rlPethPsePortOutputPower` and `rlPethPsePortOperPowerLimit` (milliwatts) in the power walk | SG300-28PP, SG350-10MP, SG350-28P (2.5.7.85, 2.5.9.54), SG350X-48P, CBS350-8FP-2G, CBS350-8FP-E-2G, CBS350-24P-4X (two-unit stack), CBS350-24FP-4X, C1200-24P-4X, C1300-24P-4G (4.1.3.36, 4.1.7.17) |

`rlPethPsePortTable` has a different layout on the SG300 1.4 from the 350-class firmware after column 9 (the SG300 has an integer where the 350 class has `rlPethPsePortTimeRangeName`), so the producer reads only columns 5 and 9, which agree on both. The per-port power is within 2% of the standard table's own `pethPsePortActualPower` (column 15) where a 350-class switch publishes that column (the two are sampled separately); it is not read, because RFC 3621 does not define it and the SG300, CBS220 and Dell do not publish it.

## Items and triggers

| Key | What |
|---|---|
| `ne.poe.pse.discovery` | PSE units present (`{#PSEUID}`, `{#PSENAME}`, `{#PSEUNIT}`) |
| `ne.poe.pse.state[]`, `.power[]`, `.consumption[]`, `.util[]`, `.threshold[]` | Status (value map *Network Explorer PoE PSE state*), budget and consumption (W), use and threshold (%) |
| `ne.poe.port.discovery` | PoE ports (`{#POEUID}`, `{#POENAME}`, `{#POEUNIT}`, `{#IFUID}`) |
| `ne.poe.port.state[]` | Detection status (value map *Network Explorer PoE port state*) |
| `ne.poe.port.power[]` | Power the port draws (W), only in templates with a vendor power source |

Triggers: a PSE that reports `faulty` (high), a PSE whose use reaches the device's usage threshold (warning), and a port whose detection status is `fault` or `other_fault` (warning). States, the budget and the threshold are stored when they change; consumption, use and per-port power are readings, stored every power walk (port power to 0.1 W) with `{$NE.TRENDS}` of trends. A complete observation older than `{$NE.POE.STALE}` (15m) or `{$NE.POE.POWER.STALE}` (45m) raises the usual stale-collection warning.

## Not yet evidenced

- IEEE 802.3bt (classes 5-8): `power_class` follows RFC 3621, which stops at class 4; CISCOSB-POEBT-MIB is not read.
- Per-port power on Dell N-Series (DNOS-POWER-ETHERNET-MIB `agentPethPsePortTable`) and on the CBS220: neither capture walked a vendor PoE table.
- Dell X-Series PoE models (X1018P, X1026P, X1052P): not captured, so the generic, unmapped producer is used.
- The Dell N1548P reports `pethPsePortPowerPriority` 4 on every port, outside RFC 3621's 1-3, so its priority is null.
