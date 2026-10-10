# Roadmap: post-PR #12 improvement and hardening

Status: active programme, started 10 October 2026 from `work` at `a0bc11f` (PR #12 merged). The next release is **1.3.0**; its changes collect under *Unreleased* in the [changelog](../../CHANGELOG.md) until it is deliberately cut.

The guiding principle is to polish and prove the existing architecture before widening the feature surface. Network Explorer reports observed evidence and never manufactures network state.

## Baseline (what already exists)

- **Monitoring → Network Explorer** is the network-wide application: default multi-switch Layer 2 topology with the agreed, current STP root marked; Layer 2 / Spanning Tree / VLAN views; site, domain, management-subnet and seed-device scope; selectable switches, links and link ends with Interface Detail; findings, collection quality and CSV/JSON exports for the same scope; restricted-user filtering; outside-site permitted neighbours kept as context. No global dashboard is required.
- Template host dashboards (Ports, Topology, Findings) stay the single-switch experience. Global dashboards are optional compositions.
- `v1.2.0` is the latest published release (8 October 2026). PR #12 landed after it and is a minor-version feature, so the next release is 1.3.0, not 1.2.1.
- Network Explorer is independent of `sjackson0109/ZabbixWidgets`: neither repository imports, packages or loads the other.

## Gap analysis against the programme (10 October 2026)

| Area | Current implementation | Gap |
|---|---|---|
| Topology layout | `graphLayout()` in `src/widget/runtime.js`: breadth-first order placed on a square grid; positions kept in page state | Not topology-aware; no STP root-oriented layout; components not separated; no fit/zoom/reset controls; legend is a single text line |
| Scope scaling | `Limits::HOSTS = 300` bounds both what is drawn and the candidate population used to resolve LLDP peers (`NetworkService::scopeHosts()` reads `HOSTS + 1`) | Display budget and identity-resolution budget are one number; peers can stay unresolved in large mixed estates; truncation is reported only as an info finding |
| Browser tests in CI | `tests/browser/widgets.test.cjs` (Node, fast) runs in CI; `tests/browser/widgets.runtime.cjs` (Chromium) runs only by hand | Chromium suite not in CI; releases are not gated on the Zabbix 7.0/7.2/7.4 integration path |
| Release supply chain | Deterministic packages, `VERSION`, version checks, changelog notes, `SHA256SUMS`, workflow_dispatch release | Actions pinned by tag, not SHA; no build provenance |
| Browser source | One canonical `src/widget/runtime.js` (about 1,800 lines) and `widget.css`, copied by `scripts/sync_widget_assets.py` | Single file holds every concern |
| Explorer UX | Selection, view, VLAN trace source dropdown, root marker | No scope summary, switch search/focus, STP path-to-root or click-to-trace; selected host/view/VLAN/interface already in the URL |
| Hardware qualification | Family handoffs, `tools/inventory/` walk capture and inventory export; no real device qualified | No qualification matrix or evidence states |
| Collector strategy | Python collector frozen as a schema 1.0 fallback | Future non-native acquisition had no documented home (now [below](#future-acquisition-agent)) |

## Delivery sequence

Each unit is one pull request into `work`, stopped at review-ready and merged only by the maintainer.

| PR | Scope | State |
|---|---|---|
| A | Documentation convergence and 1.3.0 preparation: status, superseded decisions, this roadmap, release-immutability policy, collector boundary | This change |
| B | Browser CI and release gate: Chromium suite in `Checks`, Zabbix 7.0/7.2/7.4 compatibility as a release/nightly gate, Actions pinned to commit SHAs, build provenance attestations alongside `SHA256SUMS` | Planned |
| C | Topology layout v2: topology-aware deterministic Layer 2 layout, STP root-oriented hierarchy from canonical STP evidence, separated components, stable positions, fit/zoom/reset with keyboard alternatives, stronger selection styling, compact legend | Planned |
| D | Fleet scaling: separate display, identity-candidate, option and item budgets; domain-aware candidate retrieval; explicit oversized-scope message; tests with more than 300 candidates | Planned |
| E | Explorer UX: scope summary, switch search/focus, STP path-to-root, VLAN click-to-trace, stable link selection in the URL where safe | Planned |
| F | Hardware qualification framework: `docs/qualification/MATRIX.md`, sanitised evidence workflow, qualification states | Planned |

Internal source organisation (splitting `src/widget/` by responsibility while still shipping one `runtime.js` per module) is done alongside C and E where it reduces risk, not as a separate rewrite.

### Constraints that apply to every unit

- Current-user Zabbix permissions only; no privileged token, background superuser query or unrestricted neighbour lookup; no hidden-host or hidden-neighbour leakage.
- No `eval`, no unsafe HTML interpolation; CSV formula neutralisation; bounded request, history and item reads; server-side validation of every query parameter.
- Never invent links, infer a trunk from shared VLANs, infer an STP root from layout, treat stale data as current, treat failed collection as unsupported, or infer an L2 link from FDB entries. Unknown, ambiguous, partial, stale and disputed are valid outcomes.
- PR #12 behaviour is mandatory: no dashboard dependency, host dashboards intact.
- Performance is measured at 4, 50 and 300 switches and up to 15,000 ports, split into API retrieval, parsing, identity resolution, topology construction, layout and rendering. Synthetic CPU timings are not quoted as production Zabbix performance.

## Release policy

- Published releases are immutable: never delete, recreate, re-tag or overwrite a published version or its assets. Corrections ship in a newer version.
- A new user-facing capability is a minor version; fixes only are a patch.
- 1.3.0 is cut when the units selected for it are merged and reviewed; see [RELEASING.md](../operations/RELEASING.md).

## Future acquisition agent

The Python collector in `collector/` is **Collector v1**: frozen on envelope schema 1.0, security and correctness fixes only. It does not collect VLAN, STP, port capability or static LAG data, and will not be extended to collect them.

Some acquisition cannot be expressed by native Zabbix SNMP items. If real-hardware qualification proves such a gap, it belongs in a separate, not-yet-built component, the **Network Explorer Acquisition Agent** (collector v2), with its own design review before code. Candidate responsibilities:

- schema 1.1+ envelopes for the same canonical keys the native templates produce;
- per-VLAN SNMP contexts (Cisco PVST/Rapid-PVST community or context indexing) and MST/PVST instances native items cannot iterate;
- sharding of oversized datasets;
- workarounds for problematic legacy SNMP agents and vendor-specific acquisition where evidence requires it.

It must keep the existing rules: credentials stay outside item keys and archives, results are bounded envelopes with explicit failure states, remote identity is suppressed unless policy allows it, and it is never linked beside a native producer of the same keys on one host. It is not part of 1.3.0.

## Backlog specifications (not before the units above)

Each needs a capability, security and retention contract, and real-device evidence, before code.

- **STP instances.** An instance selector (CIST, MSTI n, or PVST VLAN n) listing only instances actually collected. VLAN-to-instance mapping is never assumed. Today the UI shows instance 0 / CIST.
- **CDP.** Another neighbour-evidence producer feeding the same canonical topology, not a second engine. Agreeing LLDP and CDP observations keep source attribution and raise confidence only when justified; disagreement keeps both and raises a finding. Needs vendor qualification.
- **PoE and optics.** From POWER-ETHERNET-MIB, ENTITY-SENSOR-MIB and vendor extensions: PoE state, power and class; optical TX/RX power, temperature, voltage, bias current, transceiver identity. Unqualified sensor-index joins are never presented as authoritative.
- **Endpoints (MAC/FDB/ARP).** Kept separate from switch-to-switch infrastructure topology; a learned MAC is not proof of a physical link.
- **Layer 3.** Not advertised until routing evidence (addressing, ARP/ND, routes, OSPF, BGP, VRFs) has its own canonical contracts. Never inferred from management subnets.

## Proposals awaiting approval

These are evaluated separately and are not performed by any unit above.

- **Repository name.** The current repository name, `ZabbixModules`, is generic. Renaming stays deferred until the broader product and module boundary is settled, since the repository may come to hold sibling applications beside Network Explorer. The repository is not renamed as part of this programme without explicit approval.
- **Default branch.** `work` is the default branch. A move to `main` touches the `Checks` push trigger (already lists `main`), the release workflow (reads the default branch at run time), RELEASING.md and this documentation. A migration plan comes with the proposal.
