# Decisions and deployment inputs

Decisions that later work replaced stay here for history, marked **Superseded** with what replaced them. Unmarked entries are current.

## Confirmed by the user

- Compatibility range: Zabbix 7.0 to 7.4.
- Acquisition: SNMPv2 and SNMPv3 through native Zabbix support; Python external scripts on assigned proxies are acceptable.
- Rebuild existing vendor SNMP templates from the ground up to satisfy Network Explorer contracts.
- Known families: Cisco SBS/small-business, Cisco Catalyst, legacy Dell PowerConnect, Dell N-Series, Dell S-Series, Zyxel, Netgear, Ubiquiti and additional vendors yet to be inventoried.
- ~~First release: interfaces, LLDP, physical topology and LAG; VLAN/STP follow.~~ **Superseded:** VLAN and STP shipped in the first release line (schema 1.1, native templates and frontend overlays).
- Design future support for customer agent-based, possibly one-off collection and programmatic ingestion.
- Python 3.14 is installed; use Python 3 rather than a Python 2-compatible implementation. Candidate dependencies currently require Python ≥3.10; proposed minimum is 3.10, with 3.14 as the primary test target. Do not claim every historical Python 3 minor is supported.
- Installation is initially manual copy/deployment, suitable for package-based or container-based Zabbix. Native apt packaging is optional later work.
- Build, source, UI, examples, fixtures, package metadata and reports must be customer-neutral and contain no real organisation branding from the supplied document.
- Repeated IPs may exist across isolated customer/proxy domains. Both technical host names and display names must remain globally unique by project policy.
- Current estate is 190+ switches, 10+ vendors and approximately 8–9 models per vendor; actual inventory/template exports cannot yet be supplied.

## Autonomous defaults unless corrected

| Decision | Default | Reason |
|---|---|---|
| Version matrix | Pinned patch releases of 7.0, 7.2, 7.4; no undocumented core changes | User-selected range; exact patches recorded in test results |
| Canonical source | Per-host structured Zabbix items plus selected scalar dependent items | Reuses permissions/history; avoids parallel authority |
| Acquisition priority | Native tables first; Python for evidenced gaps | Keeps credentials within native SNMP when possible |
| Collector language | Python ≥3.10, 3.14 primary runtime, pinned dependencies, minimal launcher | Current candidate dependency metadata; runtime validation required |
| Templates | Shared capability contracts with rebuilt vendor profiles | Supports many models without duplicated monitoring logic |
| Model support | Capability/evidence badges; two vendors at initial gate | Prevents unsupported model claims |
| Graph library | ~~Pinned self-hosted Cytoscape.js candidate behind renderer interface~~ **Superseded:** an in-house deterministic SVG renderer in `src/widget/runtime.js`, no third-party graph library. Layout v2 stays in-house unless a library is justified, licence-reviewed, packaged locally and noted in third-party notices | No runtime CDN; replace if restrictions require it |
| Network-wide view | Monitoring → Network Explorer page; global dashboards optional (decided 8 October 2026, PR #12) | Fleet investigation must not depend on a dashboard someone has to build |
| Discovery enrolment | Existing hosts first; candidate proposals; no automatic host creation | LLDP is evidence, not enrolment authority |
| Scope | Site/domain seeds plus bounded neighbour expansion | Keeps out-of-subnet peers visible without unbounded traversal |
| Expected speed | ~~Explicit per-port or role policy; otherwise unknown~~ **Superseded:** derived expectation, in order: explicit policy (per-port macro), the speed both link ends can negotiate, then uplink capability towards a bridge peer; otherwise unknown. Each port shows which source applied | Capacity and negotiated speed do not prove intent on their own |
| Agent support | Reserve ingestion interface now; deploy agent transport later | Avoids delaying first release |
| History | Current state and dated evidence; no coherent topology timeline initially | First-release scope; avoid false historical claims |
| Reports | On-demand permission-filtered tables/CSV/JSON | No mail/web-service dependency for first release |
| Service trees | Optional proposals using native problems and business-defined aggregation | Topology membership cannot establish an SLA |
| Permissions | Strict filtering, generic peer placeholder where disclosure cannot be proven safe | Secure default; raw-item exposure needs a deployment gate |
| Port layout | Model geometry profiles and generic fallback | No manual port/VLAN membership requirement |
| Build environment | Disposable lab if supported; no production writes or scans | Reproducible development and integration evidence |
| Distribution | Copy-out archives, offline dependency wheelhouse where needed, install/check/uninstall guide | User preference; no mandatory apt repository |
| Identity domains | Stable customer/network-domain ID, proxy association, globally unique technical/display names | IPs may overlap across isolated domains |

## Follow-up answers incorporated

1. Python 3.14; manual copy deployment; no packaging preference that blocks the design. Exact proxy OS remains an installation-time fact.
2. Customer probes may be isolated by proxy; repeated IPs across customer domains are allowed, and host names must not conflict. Proxy assignment is not a substitute for Zabbix user/group permissions.
3. Inventory/walks/exports are unavailable for now. Deliver the qualification specification and generic contracts, not fabricated vendor support. Expected-speed source and first-release history were not specified; retain the explicit-policy/current-state defaults.

No answer is required to continue shared design, schema/policy/parser development, synthetic test fixtures and packaging. Missing facts remain explicit and may block the affected integration/vendor/deployment work. A user reply updates this file and the relevant design rather than restarting the plan.

## Release decisions (7 October 2026)

1. Licence: MIT.
2. The Python collector is a frozen fallback on envelope schema 1.0, with security and correctness fixes only. The native SNMP templates are the primary producer.
3. One bad interface row (duplicate or missing name, missing status columns, `ifNumber` mismatch) is a warning: the row is skipped or keeps unknown fields and the snapshot stays complete. Only a walk with no identifiable interface fails the dataset.

## Programme decisions (10 October 2026)

1. The next release is **1.3.0**, not 1.2.1: PR #12's network-wide application is a new user-facing feature. Changes stay under *Unreleased* until the release is cut.
2. Published releases are immutable. `v1.2.0` and later tags, releases and assets are never deleted, recreated, moved or overwritten; corrections go in a newer release.
3. Monitoring → Network Explorer is the network-wide application, template host dashboards are the single-switch experience, and global dashboards are optional. None of these is replaced by another.
4. Network Explorer and `sjackson0109/ZabbixWidgets` stay independent: no shared source, runtime dependency or asset loading in either direction.
5. The frozen schema 1.0 Python collector is not extended. Acquisition native Zabbix items cannot express goes to a future, separately designed acquisition agent (see the [roadmap](ROADMAP.md#future-acquisition-agent)).
6. Renaming the repository and changing the default branch from `work` are proposals that need explicit approval; no code change performs them.

## Build gates requiring facts or capabilities

| Gate | What is needed | Work that proceeds independently |
|---|---|---|
| Exact compatibility validation | Accessible pinned Zabbix releases and matching PHP/database runtime; deployment packaging | Framework adapter design, schemas, pure policy/graph tests |
| Profile qualification | Exact model/firmware inventory and sanitised walks or authorised read-only lab devices | Generic standard-MIB contracts, fixture harness, vendor skeletons |
| Python deployment | Proxy OS/Python minimum, package/install rules and protected credential route if fallback is needed | Native templates and pure adapter tests |
| Cross-device security | Tenant/security-domain policy and raw LLDP item disclosure decision | Permission-filtered UI and generic placeholders |
| Real expected-speed warnings | Intended-speed/duplex policies | Display actual values and explicit unknown expectations |
| Scheduled PDF | Report infrastructure, generating-user/recipient policy and rendering checks | On-demand reports/export |
| Agent transport | Chosen agent/UserParameter or sender route, ownership/TLS rules | Schema/provenance/idempotency interface |
| Production deployment | Explicit target hosts/proxies and change scope; credential bindings entered securely | Full lab builds, packages, import diffs and canary proposal |

The planning request does not authorise production enrolment, template imports, scans, report delivery or access to a customer environment. It does authorise producing this design. During a later autonomous build, finish all authorised code/lab work and raise only concrete missing requirements; do not repeatedly ask about defaults already settled here.

## Environment state

**Superseded:** this records the empty checkout at planning time (6 October 2026). The repository now holds the full implementation; see [build status](../operations/BUILD_STATUS.md).

The cloud machine is available. At initial inspection, the selected checkout had no source/commit and its remote read returned no `main` ref. The design baseline is now stored in `docs/network-explorer` on the existing branch. No deployable Zabbix runtime was validated; the build must establish a lab runtime. No application source, lockfiles or current templates were modified.
