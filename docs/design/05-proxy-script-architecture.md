# 05 — Proxy-side script architecture

Status: **implemented and frozen** (spec §20, §40.5). The collector in `collector/` is tested and, by the 7 October 2026 release decision, frozen on envelope schema 1.0 with security and correctness fixes only. Passages below that give it schema 1.1 work (per-VLAN contexts, long per-VLAN STP walks) are **superseded**: that work belongs to a future acquisition agent described in the [roadmap](../network-explorer/ROADMAP.md#future-acquisition-agent).

## Role: a fallback, not the main path

Native Zabbix SNMP walks are the primary acquisition path ([03](03-template-architecture.md)). The Python collector runs on the proxy only for a dataset and profile where native collection cannot reach a device. It produces schema 1.0 `device`, `interfaces`, `lldp` and `lag` envelopes, which the frontend reads like any other producer (spec §18); it does not produce VLAN, STP or port capability. ~~The known cases are listed at the end of [04](04-snmp-acquisition-matrix.md), mainly Cisco per-VLAN contexts and oversized walks.~~ **Superseded:** those cases go to the future acquisition agent.

Python replaces the spec's suggested shell layout (`discover.sh`, `collect.sh`). This was agreed in the earlier conversation. Shell is limited to a fixed launcher that never parses SNMP data or builds commands from device text.

## Layout on the proxy

Mapped from the spec's proposed tree:

| Spec §20 | Implementation |
|---|---|
| `/usr/lib/zabbix/network-discovery/` | Virtual environment under an administrator-chosen path (e.g. `/opt/network-explorer/venv`); launcher in the proxy's `ExternalScripts` directory |
| `discover.sh`, `collect.sh` | `network-explorer-collect collect --device <id> --dataset <name>` |
| `normalise.sh` | `network_explorer/normalize.py` (pure functions, unit-tested) |
| `vendors/<vendor>/` | `network_explorer/adapters/<family>.py`, added only with walk evidence (none yet) |
| `lib/snmp.sh` | `transport.py` (PySNMP, bounded bulk walks, v2c and v3) |
| `lib/json.sh`, `lib/validation.sh` | `validation.py` against the canonical JSON Schema |
| `lib/logging.sh` | Standard logging with credential redaction |
| `schemas/*.json` | One packaged copy of the canonical schema, tested identical to `schemas/` |
| (new) inventory and capture | `tools/inventory/` (run by an administrator, not by Zabbix) |

## Invocation

1. **External check (short datasets).** The Zabbix item `network-explorer-collect[<device-id>,<dataset>]` runs on the proxy that monitors the host. Arguments are an allowlisted device ID and dataset name only. The collector always prints one envelope. A handled failure is a valid `failed` envelope with exit code 0, because Zabbix 7.0 does not use external-check exit codes as a health signal.
2. ~~**Scheduled worker (long datasets, e.g. per-VLAN STP across 200 VLANs).** A systemd timer runs the collector, writes the envelope atomically to a protected cache, and a cheap external check returns the cached envelope. This keeps long walks out of the Zabbix poller timeout.~~ **Superseded:** never built; a cached long-walk mode is a candidate for the future acquisition agent.

## Requirements from spec §20

| Requirement | How it is met |
|---|---|
| Non-interactive execution | CLI only; no prompts |
| Machine-readable output | One JSON envelope on stdout, schema-validated before printing |
| Secure credential handling | Credentials live in a 0600 JSON file outside the web root, keyed by device ID; never in item keys, argv or environment of child processes. Native templates keep using Zabbix's own SNMP interface credentials. |
| Deterministic exit codes | 0 whenever an envelope is printed, including configuration and internal errors, which become `failed` envelopes with the codes `configuration_error` or `collection_error`; 2 for command-line usage errors. Zabbix reads the envelope, not the exit code. |
| Useful logs | Structured log lines to the proxy's log facility: device ID, dataset, duration, varbind count, outcome |
| No credentials in logs | Redaction filter on every log record and exception message; tested |
| Validate collected data | Schema validation plus row-level checks (mandatory columns, duplicate indices, row counts against ifNumber) |
| Tolerate incomplete vendor data | Missing optional columns become null; a missing mandatory column makes the envelope `partial` |
| Identify unsupported capabilities | `unsupported` only after a completed walk returns noSuchObject or an empty subtree |
| Report stale or failed collection | `failed` envelopes with coded errors; freshness is computed by the reader from `observed_at` |
| Least privilege | Runs as the proxy's service user; read-only SNMP; no SET; destinations restricted to the configured allowlist, never to addresses learnt from LLDP |

## A default to revisit

Still open; the collector keeps `redact_remote: true` by default.

The collector currently **suppresses remote LLDP identity by default** (`redact_remote: true`), removing remote chassis IDs, names and addresses before storage. This protects multi-tenant estates, but it also stops peer resolution and navigation from working out of the box, which spec §4 and criteria 4–6 require. The proposal is to default to `false`, and to enable redaction per network domain where tenants share a Zabbix but must not see each other's neighbours. The frontend permission filter applies in both cases.
