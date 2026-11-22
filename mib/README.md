# MIB modules

This folder holds the SMI modules used to design and check the Network Explorer vendor templates, each unmodified from its source. **The modules themselves are not in the repository**: their copyright stays with the vendors and the IETF, so only this README and `SHA256SUMS` are published, and the templates do not need them at run time. Rebuild the folder locally:

```sh
mkdir /tmp/observium && cd /tmp/observium           # an empty folder of its own
curl -fLO https://www.observium.org/observium-community-latest.tar.gz
sha256sum observium-community-latest.tar.gz          # compare with the archive SHA-256 below
tar -xzf observium-community-latest.tar.gz
cd - && python -I tools/mib/collect_mibs.py /tmp/observium/observium/mibs mib
git diff --exit-code mib/SHA256SUMS                  # the same files as listed here
```

A later archive may carry newer revisions; `git diff mib/SHA256SUMS` then shows which modules changed.

## Source

[mibs.observium.org](https://mibs.observium.org/all) shows each module but does not offer the files for download. Its "Source file" field points at the `mibs/` folder of the Observium Community Edition, so the files here come from that release:

| | |
|---|---|
| Archive | `https://www.observium.org/observium-community-latest.tar.gz` |
| Last-Modified | 5 May 2026 |
| SHA-256 | `01f4bec0bb01c49afe07e26f2b3f79d4eeeabf412ce5f15193df4ed7fc77d715` |
| Fetched | 22 November 2026 |

`SHA256SUMS` lists every file with its checksum and its path in the archive (below `observium/mibs/`).

## Layout

| Folder | Covers |
|---|---|
| `ciscosb/` | Cisco Small Business (SG300, SG350/X/XG, CBS250/350, C1200, C1300). All CISCOSB modules, including the Physicaldescription, HWENVIROMENT, rndMng and POE MIBs. |
| `radlan/` | The RADLAN originals that the CISCOSB and Dell X-series modules are copies of. They sit under `1.3.6.1.4.1.89`. |
| `dell/` | Dell N-Series (`DNOS-*`, `DELL-REF-MIB`, `Dell-Vendor-MIB`). Dell X-Series (`Dell-*`, RADLAN under `89`). The PowerEdge VRTX switch module (`Dell-VRTX-*`). The VRTX chassis controller (`DELL-RAC-MIB`). The S-Series (`DELL-NETWORKING-*`, `DELLEMC-OS10-*`). |
| `force10/` | Dell S-Series on OS9 (FTOS). |
| `broadcom/` | FASTPATH, which DNOS is derived from. |
| `net-snmp/` | UCD-SNMP-MIB and friends (Ubiquiti, OS10). |
| `rfc/` | Only the standard modules that the vendor modules import, or that the templates read directly. |

The vendor folders are complete. `rfc/` holds the import closure. Two legacy imports (`RFC-1213` in `DNS-SERVER-MIB` and `RFC1158-MIB` in `RFC1271-MIB`) are not in the release, and neither affects these templates.

## Using them

```sh
snmptranslate -M +mib/rfc:mib/ciscosb -m CISCOSB-Physicaldescription-MIB -On \
  CISCOSB-Physicaldescription-MIB::rlPhdUnitEnvParamTempSensorValue
```

## Limits

- Each module appears once, at the revision Observium ships. Firmware-specific bundles (for example Cisco's per-release MIB downloads) can differ, so a capture still decides what a given firmware exposes.
- Some tables changed shape between generations, and the MIB name alone does not say which one a device uses. `rlPhdUnitEnvParamTable` is one example:

  | Layout | Module | Temperature | Status | Uptime (TimeTicks) | Thresholds | Fan speeds |
  |---|---|---|---|---|---|---|
  | 14 columns | `Dell-Physicaldescription-MIB` | 9 | 10 | 11 | none | none |
  | 24 columns | `CISCOSB-Physicaldescription-MIB` | 10 | 11 | 14 | 12 (warning), 13 (critical) | 18-23 |
  | 5 sensors | `RADLAN-Physicaldescription-old-MIB` | 9, 12, 14, 16, 18 | 10, 13, 15, 17, 19 | 11 | none | none |

- Copyright stays with each module's author (the vendors and the IETF), as stated in the files.
