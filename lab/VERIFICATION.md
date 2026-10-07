# Runtime evidence

The shared module and laboratory replay contract were tested on actual disposable runtimes on 6 October 2026. Image digests and original official image tags are recorded in [images.lock.json](images.lock.json).

| Zabbix server / frontend / proxy | Frontend PHP | Database | API/data/frontend integration |
| --- | --- | --- | --- |
| 7.0.20 | 8.4.14 FPM | PostgreSQL 16.10 | Passed |
| 7.2.7 | 8.3.19 FPM | PostgreSQL 16.10 | Passed |
| 7.4.3 | 8.4.13 FPM | PostgreSQL 16.10 | Passed |

Each runtime passed these independent observations through [the integration harness](../tests/integration/zabbix_runtime.py):

- The active proxy connected and reported the matching runtime version.
- Six frontend modules registered through the official API and the lab YAML imported successfully.
- Real Zabbix sender ingestion accepted device, interface, LLDP and LAG envelopes for four invented hosts.
- Complete interface inventory produced ten dependent interface scalar items from two discovered interfaces; operational status and negotiated speed had correct values.
- Native graph prototypes produced two inherited negotiated-speed graphs from the discovered interface scalars.
- A failed attempt updated health without replacing the last successful complete inventory.
- A partial attempt retained the complete inventory and previously discovered interfaces.
- The inherited host dashboard rendered, and all five custom widget view actions returned canonical host observations.
- Reciprocal LLDP observations became one confirmed bidirectional edge. LAG data remained visible, and duplicate management addresses in another domain did not alter peer resolution.
- An ordinary read-only user's Explorer API and reports concealed the private neighbour's name and management address.
- Querying an inaccessible seed returned an empty graph instead of widening into a fleet query.
- A CIDR annotation marked the seed inside and its authorised physical neighbour outside while retaining the neighbour in the API graph and addressing report.
- The Explorer HTML route and all six JSON and CSV report types rendered; CSV column counts were consistent.

These tests use explicitly laboratory-only trapper replay templates. They do not validate live SNMP transport, real switch models, vendor-specific templates, production proxy deployment or collection load. No customer network was accessed. The tested release patches are the matrix above; other patches and frontend PHP combinations require their own checks.

Browser interaction and native host/item broadcast tests are maintained separately in `tests/browser/`. Performance targets for 300 switches and 15,000 physical ports remain unmeasured production-scale acceptance criteria. Static fixture validation and successful imports do not establish those limits.

Run `sh scripts/test-compatibility.sh` to reproduce the API/data/frontend tests against all three pinned release families. The generated detailed check lists remain in ignored `lab/.state/<family>/integration-result.json` and contain no generated credentials.

## Native SNMP templates (7 October 2026)

`templates/native/<version>/network_explorer_snmp.yaml` was imported into fresh 7.0.20, 7.2.7 and 7.4.3 labs (same image digests as the lock, pulled through `mirror.gcr.io` because Docker Hub rate-limited the session). Two hosts linked only `Network Explorer - Profile - Generic standard MIB` and polled snmpsim serving the synthetic walks in `tests/fixtures/walks/` over SNMPv2c. Drive it with [`native_snmp.py`](native_snmp.py).

On every version:

- All 8 producers on both switches returned `status: ok` envelopes. sw-core-01 gave 27 interfaces, 4 LLDP neighbours, 28 VLAN rows, 10 STP rows and 1 LACP bundle. sw-access-17 gave 48 interfaces and an empty but supported LAG dataset.
- Interface discovery created the per-port items (151 and 235 items per host), and none were left not supported.

On 7.0.20 only:

- With `{$NE.IF.EXPECTED_SPEED:"Gi1/0/23"}` set to 1G, the core switch raised "Gi1/0/23 below expected speed" (the port runs at 100M). With `{$NE.IF.MONITOR:"Gi1/0/24"}=1` on a down port, "Gi1/0/24 is down" was raised.
- Giving sw-access-17 a community the simulator does not serve made Zabbix mark the SNMP interface unavailable. No attempt value was produced (a timeout is a network error, not a not-supported value). The last snapshots stayed in place and the stale triggers fired.

Two import behaviours found here are now designed around (see [03](../docs/design/03-template-architecture.md)):

- Zabbix drops `error_handler` on JavaScript steps at import. The native gates return a sentinel that a regular-expression step discards. The LAB replay template still relies on the dropped handler: its failed or partial gates make the snapshot item *not supported* rather than discarding the value, so the last value is retained but the item state flips.
- A discarded value does not clear an item that is already not supported, so per-port scalars return explicit unknown values.

Not covered yet: forcing an agent-side SNMP error to prove the `__NE_COLLECTION_FAILED__` path end to end, real switch walks, SNMPv3, and load.

## Frontend on schema 1.1 (7 October 2026)

The same two simulated switches were read through the installed frontend modules as Admin, on 7.0.20 and 7.4.3, using the Network Explorer JSON exports and a dashboard holding the Port Panel (VLAN layer), Topology (STP overlay) and Findings widgets. No browser errors were raised on either version.

- Findings, matching the spec's Appendix A journey: sw-core-01 Gi1/0/23 below its configured 1G (`policy`, from the per-port macro) and half duplex against a full-duplex peer; sw-access-17 Gi1/0/48 below the 1G both ends advertise (`negotiable`, with no macro set); and "VLAN 49 is carried by sw-access-17 Gi1/0/48 but not permitted on sw-core-01 Gi1/0/23".
- The core-to-access link carries VLANs 1 and 50, with native VLAN 1 on both ends. The STP overlay highlights it as the access switch's root-port link, marks the core's blocking alternate port towards sw-dist-01, and names the unmonitored root bridge.
- The Zabbix server host, which has no Network Explorer items, is no longer drawn in the topology.
- Outage (7.0.20): after `native_snmp.py break`, Zabbix marked sw-access-17's SNMP interface unavailable. All seven of its datasets then reported `failed` with `agent_unreachable`, it was flagged as SNMP unreachable in the topology, and one `snmp_unreachable` finding replaced the per-dataset collection findings.

The live check found two frontend defects, which are fixed in the same change: native state rows erased inventory attributes (every port showed as unclassified), and the fixture gave sw-core-01 Gi1/0/23 no VLAN membership.

## Spec acceptance walkthrough (7 October 2026)

The lab now simulates four switches. sw-dist-02 is the RSTP root and bundles two 10G ports (Po10, LACP) towards sw-core-01 Po1. sw-dist-01 closes a triangle, so sw-core-01 Gi1/0/24 blocks as an alternate port, and its management address 10.102.5.10 sits outside the 10.101.0.0/16 management subnet. sw-dist-01 is in its own host group, which a lab viewer user cannot read. `lab/acceptance.cjs` drives the spec's acceptance steps in Chromium against each version, from a fresh lab (`native_snmp.py import`, `hosts`, `poll`, `lab.py install-modules`, `native_snmp.py dashboard`, `viewer`):

1. sw-core-01 Gi1/0/23 shows amber, below its expected speed.
2. Following its LLDP peer opens sw-access-17 with Gi1/0/48 highlighted and "Navigated from Gi1/0/23".
3. With the 10.101.0.0/16 management subnet, the topology draws four switches and flags sw-dist-01 as off-subnet without hiding it.
4. Tracing VLAN 49 from sw-access-17 stops at sw-core-01 Gi1/0/23.
5. The STP overlay names sw-dist-02 as root and marks one blocking port.
6. Po1/Po10 is drawn as one logical link labelled "LAG ×2"; expanding it shows the two member links.
7. The viewer sees three switches. sw-dist-01's name and address appear nowhere in the page, in the inventory, peers, findings and STP exports (JSON and CSV), or in `host.get`. Bridge IDs of switches the viewer cannot read are replaced with opaque per-request placeholders.
8. After `native_snmp.py break`, sw-access-17 is drawn as SNMP unreachable and the Findings widget lists `snmp_unreachable`.

All eight steps passed on 7.0.20, 7.2.7 and 7.4.3 with no browser errors, and all 4 switches polled with no unsupported items.

The walkthrough found three defects, fixed in the same change: LAG member links carried no VLAN or STP state, the browser grouped parallel links without regard to their LAG, and a restricted viewer could read a hidden switch's MAC address through the STP designated bridge of a visible port.

Build cost at scale (`php -d memory_limit=2G tests/perf/scale.php 3`): 300 switches with 50 ports each (15,000 interfaces) and 1,000 links, all with VLAN, STP, capability and LLDP data, built in a median of 1.86 s (slowest 2.98 s) with a 25.5 MB payload and 382 MB peak memory, on this lab container. `tests/perf/render.cjs` then draws that payload in the Topology widget in headless Chromium: 300 nodes and 1,000 links reached first paint in a median of 0.37 s (slowest 0.42 s over five runs), inside the spec's 5 s budget. Neither figure includes Zabbix API or history latency, which a real estate adds.

## Port placement, media and state colours (7 October 2026)

The lab adds sw-stack-01, a two-member stack (24 copper and 2 SFP+ ports per member) uplinked to sw-dist-02. sw-core-01, sw-access-17 and the stack publish ENTITY-MIB port entities; the two distribution switches do not. On 7.0.20, 7.2.7 and 7.4.3, all five switches polled with no unsupported items, and the acceptance walkthrough (`lab/acceptance.cjs`) passed its eight steps plus the stopped-agent step, with no browser errors. The new step opens sw-stack-01: the Port panel shows Member 1 and Member 2 tabs, groups each member's ports by slot, and the mixed layout separates the empty SFP+ cages (media from their supported MAU types) from copper. The distribution switches' ports stay unplaced rather than being guessed from names.

A Port panel configured with custom normal and down colours drew its ports in those colours, and its edit form showed working colour pickers on all three versions (7.0 and 7.2 use the jQuery picker; 7.4 its own).

The first 7.0 run found that stack positions never reached Zabbix: the generator folded a long script line inside a regex, and Zabbix's YAML import adds a space at each escaped fold. Scripts are now written as literal blocks, and a unit test rejects folded or quoted multi-line scalars.
