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
