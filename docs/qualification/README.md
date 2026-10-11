# Hardware qualification

Network Explorer reports observed evidence, and its support claims follow the same rule: a vendor, model or firmware is described only as far as committed evidence shows. Synthetic tests never qualify a vendor.

- [MATRIX.md](MATRIX.md) is the qualification matrix. It is generated from [`matrix.json`](matrix.json) by `tools/qualification/qualify.py matrix --write`.
- Evidence lives in `tests/fixtures/qualification/<id>/`, one directory per walk.
- `qualify.py matrix --check` runs in CI (`Checks` → python). It fails when `MATRIX.md` is stale, when a state lacks cited evidence that shows it, or when cited evidence fails the sanitisation checks below.

## States

Each matrix cell holds one state for one capability: Interfaces, ENTITY, MAU, LLDP, VLAN, STP or LAG.

| State | Meaning | Evidence it needs |
|---|---|---|
| Unqualified | Nothing has been shown for this capability on this model and firmware. This is the starting state for every row. | None |
| Lab simulated | The templates handle the capability on invented devices in the replay lab. This says nothing about any vendor. | `synthetic` evidence whose classification shows `ok` |
| Captured-walk tested | A sanitised walk from a real device, replayed through the native normalisers, produces the capability. Zabbix did not poll the device. | `captured` or `field` evidence showing `ok` |
| Partially qualified | Real-device evidence shows the capability with a gap, such as a missing column or join, or ports without ENTITY placement. | `captured` or `field` evidence showing `partial`, `absent` or `ok`, and a stated limitation |
| Real-device qualified | Zabbix polled the device itself with the native templates, and the result was checked for this capability. | `field` evidence showing `ok`, with the capability listed in `field.verified` |
| Unsupported | A completed real-device walk shows the device does not expose the capability through the MIBs the templates read. | `captured` or `field` evidence showing `unsupported` or `absent` |

Any state other than Unqualified and Lab simulated needs an exact model and firmware on the row: one model never qualifies a family, and one firmware never qualifies another. No cell says PASS.

The earlier vocabulary is **superseded**, but its intent carries over:

| Earlier term | Where it appeared | Now |
|---|---|---|
| `walk-observed` / `lab-replayed` | [01](../design/01-vendor-capability-matrix.md) | Captured-walk tested |
| `field-validated` | [01](../design/01-vendor-capability-matrix.md) and the [family handoffs](../../templates/specifications/FAMILY_HANDOFFS.md) | Real-device qualified |
| `fixture-tested` / `lab-tested` | [template requirements](../network-explorer/TEMPLATE_REQUIREMENTS.md) and the family packs | Lab simulated for an invented walk; Captured-walk tested for a captured one |
| `unqualified` profiles | [family handoffs](../../templates/specifications/FAMILY_HANDOFFS.md) | Unqualified |

## Classification

`qualify.py classify <walk.snmprec>` replays a walk through every native template normaliser, exactly as Zabbix composes them (`tests/js/run_normaliser.cjs`). It records only stable facts for each dataset: its status, row count and error codes. From those it derives one value per capability:

- `ok`: rows present.
- `empty`: collected, but nothing observed (for example no LLDP neighbours or no LAG). This cannot qualify or disqualify a capability.
- `partial`, `unsupported` or `failed`: as the normaliser reported.
- `absent`: ENTITY only, for interfaces collected with no member or slot placement.

The stored classification must equal a fresh replay; a pytest re-runs every committed walk. If a normaliser change alters a classification, the affected matrix states are reviewed in the same PR.

## Evidence workflow

1. **Capture.** Run `tools/inventory/capture_walk.py --sanitise --sanitise-serials --sanitise-aliases` against one representative device per vendor, model and firmware ([inventory README](../../tools/inventory/README.md)). Keep `--sanitise-map` private, and use the same map for every device in one estate so that neighbours still match.
2. **Review by hand.** Read the `.snmprec` file before it leaves the estate. The sanitiser does not change:
   - free-text descriptions (sysDescr, ifDescr, LLDP descriptions);
   - IPv6 addresses;
   - MAC addresses;
   - addresses in other indexes.

   Edit customer names and addresses out of descriptions by hand. If a value is needed to reproduce a behaviour, replace it consistently rather than deleting it.
3. **Create the evidence directory.** Make `tests/fixtures/qualification/<id>/`, where `<id>` is lower case, for example `cisco-cbs350-24t-3.4.0.17`. Put three files in it:
   - `capture.snmprec`: the walk;
   - `manifest.json`: unchanged from `capture_walk.py`;
   - `evidence.json`: the record described below.
4. **Classify.** Run `python3 tools/qualification/qualify.py classify tests/fixtures/qualification/<id>/capture.snmprec`. Store its output as `classification` in `evidence.json`.
5. **Check the evidence.** Run `python3 tools/qualification/qualify.py check-evidence tests/fixtures/qualification/<id>`. It must report no errors, and its warnings (kept MAC addresses) need a deliberate decision.
6. **Update the matrix.** Add or update the row in `matrix.json`, cite the evidence ID, set each state no higher than the evidence supports, and record the known limitations. Run `qualify.py matrix --write`, then commit the matrix and the evidence together.
7. **Add regression tests where they help.** A behaviour worth keeping, such as a vendor port-numbering quirk or an LLDP subtype 7 local port, also gets a normaliser test against the captured walk.

### `evidence.json`

```json
{
  "id": "acme-x24-1.0.2",
  "kind": "captured",
  "description": "Acme X-24, 24 copper + 4 SFP+, standalone, LLDP and RSTP enabled.",
  "walk": "capture.snmprec",
  "device": {"vendor": "Acme", "family": "X series", "model": "X-24", "firmware": "1.0.2"},
  "classification": { "...": "output of qualify.py classify" }
}
```

`kind` is one of the following:

- `synthetic`: an invented device. `walk` may then point at a repository fixture such as `tests/fixtures/walks/`.
- `captured`: a real walk, kept in the evidence directory.
- `field`: a real walk, plus a record that Zabbix polled the device with the native templates:

```json
"field": {
  "observed_on": "2026-11-02",
  "zabbix_version": "7.4.3",
  "verified": ["interfaces", "lldp", "lag"],
  "notes": "Two-switch LACP pair; both ends confirmed bidirectionally in Network Explorer."
}
```

`verified` lists only the capabilities someone checked against the live device. Only those can become Real-device qualified.

### `check-evidence` rejects

- A capture taken without `--sanitise`, `--sanitise-serials` and `--sanitise-aliases`.
- A manifest with keys `capture_walk.py` does not write, such as a target, community or user name.
- An IPv4 address outside 192.0.2.0/24, 198.51.100.0/24 and 203.0.113.0/24, whether in an IpAddress value, in an LLDP management-address index or in free text. Masks, loopback, multicast and 0.0.0.0 are allowed.
- A system name, location, contact, serial number or ifAlias that is not the sanitiser's placeholder.
- Captured or field evidence without a vendor, family, model and firmware, and field evidence without `observed_on`, `zabbix_version` and `verified`.
- A walk path that leaves its evidence directory, or the repository for synthetic evidence.

## Never commit

- Credentials, community strings, SNMPv3 users or passphrases, API tokens or environment dumps.
- The `--sanitise-map` file, which holds the real values.
- Unsanitised walks, even temporarily: Git history keeps them.
- Customer, site or person names in descriptions.
