# Build plan and acceptance

Status: executable delivery plan for the next build phase. This document does not claim the software or tests already exist. User-confirmed first-release scope is interfaces, LLDP, physical topology and LAG. VLAN/STP and optional enrichment remain planned subsequent releases.

## 1. Build order

Work follows dependency gates, not calendar estimates. Produce a running end-to-end slice early instead of completing every vendor adapter before validating the frontend.

### Gate 0 — Lab and evidence

Confirmed runtime input is Python 3.14; proposed collector minimum is 3.10 pending tests. Installation artefacts target manual copy-out deployment. Current fleet is 190+ devices with many model families; inventory and real walk fixtures are unavailable, so generic work proceeds without claiming model qualification.

- Use the existing repository/build branch and preserve user files. Planning artefacts are stored in `docs/network-explorer`.
- Select accessible patch releases for 7.0/7.2/7.4 and matched PHP/database/server/proxy packages or official containers. Record versions and image digests, runtime resource limits and supported deployment platform.
- Make a disposable Zabbix server/frontend/database/proxy lab plus SNMP fixtures if platform capabilities permit. No production scan or private connectivity is assumed.
- Obtain template exports/model inventory/walk evidence where available; catalogue existing coverage. Missing vendor fixtures do not block generic work but prevent a model qualification badge.
- Verify tooling and installation/startup with real tests. Save tested environment installation/startup instructions through the cloud configuration flow when building the environment; do not save unexecuted plans as working setup scripts.

Exit: reproducible lab or an explicit runtime blocker, version matrix, inventory intake format, preserved checkout state and test fixture conventions.

### Gate 1 — Architectural spikes

Five small experiments precede broad implementation:

1. Native SNMP table → canonical text dependent item → selected scalar prototypes and LLD → permission-filtered widget request. Confirm units, completeness and retry/freshness behaviour.
2. Python external check → explicit success/failure envelope → separate successful snapshot/quality. Demonstrate that nonzero exit alone cannot be the health contract; test exception/time-out handling and secret redaction.
3. Template dashboard with custom widget and native host context on every version; peer dashboard navigation with remote interface highlight. Confirm native host/item broadcasts and the contextual fallback route.
4. Multi-item latest text retrieval, payload limits and partition manifests on the largest representative stack. Measure query counts, history behaviour, incomplete generation handling and rendering cost.
5. Authorisation of host/item/peer metadata, exports and caches using admin, site-limited and restricted users; include raw LLDP item/API reads. Determine the safe collection profile for strict tenant boundaries.

Exit: recorded executable results and finalised transport/reader/dashboard contracts. A failed spike changes its adapter/approach; it is not replaced with a trivial passing check. Version differences are captured centrally.

### Gate 2 — Data foundation and rebuilt templates

- Implement versioned JSON Schemas and canonical factories, units/enums/identity tokens, structured diagnostics and fixture sanitisation.
- Implement shared native interface/LLDP acquisition and canonical preprocessing; Python normalisation interfaces for justified gaps.
- Implement complete-observation-only LLD, heartbeat/stale logic and reboot/renumbering handling.
- Implement shared Base/Interfaces/LLDP/LAG templates, selected health triggers and explicit policy macros.
- Implement vendor profile dispatch and two evidence-backed vendor families; leave additional profiles visibly unqualified until walks/lab evidence arrive.
- Publish deterministic import assets/value maps and the template coverage/migration comparison.

Exit: real polling and canonical output on two vendor profiles plus simulated failures; no duplicated producer keys or unintended lost-resource deletion; raw credential values absent from all emitted data/logs.

### Gate 3 — First usable host workflow

- Implement dataset reader, policy/quality/navigation services and compatibility layer.
- Ship Port Panel, Interface Detail and Data Quality widgets plus Explorer host page.
- Render generic, 24-port, 48-port, mixed copper/SFP and stack layouts from discovered identities and geometry profiles.
- Inherit Overview/Connectivity/Diagnostics dashboards from templates; reuse native traffic/error/problem widgets.
- Demonstrate actual/expected speed, duplex evidence, stale states and peer navigation/highlight.

Exit: a user can investigate a port on A, follow its LLDP peer to B, retain the selected remote port and understand incomplete data. No browser SNMP, hard-coded item IDs or manually maintained topology are required.

### Gate 4 — First-release fleet topology and LAG

- Implement identity reconciliation with subtypes, one-sided/ambiguous edges, external placeholders and conservative security filtering.
- Implement automatic topology layout, scope/expansion, CIDR validation, out-of-scope management anomaly annotation and LAG member grouping.
- Ship Network Operations, Site Network and Discovery/Coverage dashboard recipes. *Changed:* the fleet and site topology now live on Monitoring → Network Explorer, which needs no dashboard; the recipes are optional examples.
- Implement Findings widget and current-state inventory, peer, addressing, degradation and collection-health exports.
- Run the 300-switch scale fixture and capture agreed response/layout budgets.
- Package compatible modules/templates/collector with rollback/canary documentation and licence manifest.

Exit: first production candidate satisfies first-release checks below. Claims of real vendor support correspond to evidence badges. Production rollout itself requires an authorised target scope.

### Gate 5 — VLAN release

- Qualify Q-BRIDGE/bridge/vendor table mappings and SNMP contexts with fixtures and actual representative devices.
- Implement VLAN membership/PVID/native/forbidden semantics and static/current distinctions.
- Add selectors, host VLAN page, graph overlay, both-end membership analysis and mismatch/boundary findings.
- Mark uncertain translation/tunnel/context cases; avoid claiming traffic delivery.

Exit: tagged/untagged membership and inter-switch candidate propagation are validated against known trunk/access/mismatch scenarios. Unknown/missing membership stays explicit.

### Gate 6 — STP release

- Implement protocol/instance/region and VLAN mapping; roles/states and root evidence.
- Add host STP page, graph overlay, potential-forwarding analysis and topology-change reporting.
- Validate redundant physical graph, blocking/forwarding paths and unsupported/missing mappings.

Exit: VLAN membership and potential forwarding are separately explained; root paths have consistent evidence. All applicable original specification acceptance criteria now pass or have capability-qualified results.

### Gate 7 — Optional extensions

Independently scoped: PoE/optics/hardware enrichment; native scheduled PDF rendering; business-defined service tree/SLOs with synthetic evidence; agent acquisition transport; coherent topology history/drift; MAC/ARP/IP-to-port/endpoint discovery. Each addition receives a capability, security and retention contract before coding.

## 2. Proposed repository layout

```text
docs/
  design/                 this plan, decisions and architecture
  vendors/                model/firmware capability evidence and OID sources
  operations/             install, upgrade, rollback and secret provisioning
schemas/                  canonical datasets and collector result envelope
collector/
  network_explorer/       acquisition, adapters, joins, validation, redaction
  packaging/              proxy install/config examples and fixed launcher
frontend/
  networkexplorer/        base module, PHP services and Explorer routes
  neportpanel/            manifest, Widget, actions, fields, views, assets
  netopology/
  neinterfacedetail/
  nedataquality/
  nefindings/
templates/
  source/                 deterministic shared definitions
  generated/7.0/          version-compatible import exports
  generated/7.2/
  generated/7.4/
  profiles/               evidence-backed vendor selection definitions
dashboards/               host definitions and fleet provisioning recipes
provisioning/             preflight, diff, import/link and optional service proposals
tests/
  fixtures/               sanitised SNMP and canonical datasets
  unit/                   parsing, joins, policies, graph algorithms
  integration/            actual Zabbix ingest/read/LLD/trigger workflows
  browser/                dashboard, navigation, exports and report rendering
  performance/            300-device workload, retrieval/layout budgets
lab/                      pinned disposable runtime and fixture agent setup
```

This is a proposed coding layout, not existing repository content. Pin dependency versions/locks during build. Use framework-supported widget folders/manifests and a package-local shared library; validate autoloading instead of patching Zabbix's core loader.

## 3. First-release acceptance

Additional mandatory checks: repeated IPs across separate customer/network domains remain separate; names are globally unique; no cross-domain peer matching occurs by default; raw device sysName cannot replace the namespaced host identity. Scan build output, source, docs, fixtures, UI and package metadata for prohibited organisation branding, with patterns held outside distributed artefacts. Installation succeeds by documented manual copy without an apt repository.

| Check | Evidence required |
|---|---|
| Versions | Modules register, templates import, items poll, widgets render and navigation works on pinned 7.0/7.2/7.4 runtimes; label any unavailable runtime untested |
| Models | At least two vendor families with real captured/representative lab evidence; 24-port, 48-port, mixed SFP and stack coverage |
| Interface state | Known admin/oper/speed/duplex inputs produce correct labelled states and units |
| Intended speed | Valid known policy creates persistent degradation; unknown intent remains unknown; capacity alone causes no warning |
| LLDP | ID subtypes/compound indices, multiple peers and one-sided links handled; ambiguous resolution stays ambiguous |
| Navigation | A selected port opens permitted peer B and highlights its actual matching interface; invalid context safely rejected |
| Physical graph | Parallel links, unresolved peers and out-of-management-CIDR neighbours retained according to visibility policy |
| LAG | Members inspectable; aggregators grouped correctly despite differing local numbers; multi-chassis case represented or clearly unsupported |
| Discovery | Partial/failing polls do not purge existing entities; complete absence follows grace policy; renumbering does not misassociate ports |
| Security | No secrets, XSS or command injection; restricted host/peer data absent from payloads, exports, suggestions, caches and applicable raw-item collection profile |
| Quality | Current/stale/unknown plus partial/failed/unsupported are distinct; delayed proxy delivery does not refresh old data |
| Scale | 300 switches/15,000 physical ports/1,000 links; p95 timings/query counts/memory recorded against agreed budgets |
| Reports | CSV/JSON reflect current user scope, include age/coverage, defend spreadsheet injection and agree with displayed findings |
| Migration | Existing monitoring comparison, canary plan, configuration exports and rollback instructions complete |

## 4. Test strategy

Unit/property tests exercise SNMP numeric/text/binary parsing, VLAN bitmap boundaries beyond 64 ports, multi-part LLDP indices, speed/counter units, UID reconciliation, quality state transitions, CIDR parsing, peer matching, LAG grouping, scope expansion and VLAN/STP rule logic. Unknown data must never become false success.

Integration tests execute real template imports, SNMP fixture polling through the proxy, preprocessing, dependent item updates, LLD additions/removals, failure/lifetime behaviour, history retrieval and trigger recovery. A schema-only test does not validate the collector/template contract. Track tests actually executed; zero-test runs and skipped version targets are not passes.

Browser tests exercise ordinary and template dashboards, host broadcasts, remote port highlight, legends/keyboard interaction, stale update handling, escaping, permission revocation and exports. Print/PDF tests become mandatory only when scheduled reports are included.

Failure fixtures: timeout, auth failure, unsupported OID/context, partial walk, empty complete walk, reboot during collection, ifIndex renumbering, stack member replacement, clock skew, proxy backlog, oversized/truncated snapshot, manifest mismatch, malformed JSON, unsupported schema, XSS-like descriptions and hostile identifiers. SNMPv2c/v3 transport is validated without exposing secrets.

Avoid a full Cartesian product of every model/version/protocol. Run the shared framework contract on every Zabbix version; qualify each model/firmware on representative protocols and the relevant adapter; include both v2c and v3 and a multi-vendor link in the end-to-end suite. Record coverage gaps explicitly.

## 5. Original acceptance traceability

| Specification §35 | Delivery gate |
|---|---|
| 1 Physical interfaces | 2–3 |
| 2 Correct state/speed | 2–3 |
| 3 Reduced speed distinction | 3, with known intended-speed policy |
| 4 LLDP discovery | 2 |
| 5 Peer navigation | 3 |
| 6 Remote-interface highlight | 3 |
| 7 Multi-switch topology | 4 |
| 8 Configurable management subnet | 4 |
| 9 Out-of-subnet connected peers visible/highlighted | 4, subject to user visibility |
| 10 VLAN selection/membership | 5 |
| 11 Tagged/untagged | 5 |
| 12 VLAN propagation | 5 for observed membership; 6 for STP-aware potential forwarding |
| 13 STP overlay | 6, capability-qualified |
| 14 LAG logical connection | 4 |
| 15 Multiple vendors | 2 and 4 qualification gates |
| 16 No manual port/VLAN/topology membership | 3–6; geometry and intent policies remain configuration |
| 17 Permissions | 1 security spike and every release |
| 18 Failures/staleness distinct | 2 and every release |

Specification §33/40 inventory/design work is incorporated into Gates 0–2 and `TEMPLATE_REQUIREMENTS.md`; it does not authorise accessing a customer environment. §34 integration/failure scenarios appear above and in later VLAN/STP gates. Deferred scope is explicit, not removed.

## 6. Autonomous execution contract for the build phase

Start from the confirmed decisions in `DECISIONS.md`. Choose routine implementation details autonomously, record meaningful tradeoffs and continue through code, dependency installation, startup and tests. Do not ask repeatedly for settled defaults or to continue each milestone.

Complete independent schema, fixture, frontend and native-template work while external access/model fixtures are pending. Do not invent vendor capability or claim runtime validation from source inspection. If container execution is unavailable, investigate supported local runtime options before reporting a lab blocker; retain required integration gates.

Use supported onboarding configuration to save tested install/start instructions after executing them. Build/live setup is a separate task from this design pack. No untested environment script is saved here.

Production import/link, host enrolment, private network scans and report delivery require explicit target/action scope. A later authorised build may create all code, packages and disposable lab resources within its scope before asking about a blocked deployment action. Protect existing secrets/user changes, preserve verification, and do not fork or modify Zabbix core.
