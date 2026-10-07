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
