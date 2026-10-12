# Wi-Fi Explorer Requirements Specification

Source: the maintainer's requirements, received 12 October 2026. Kept here unchanged apart from character-encoding repairs, so the roadmap and design can cite sections by number.

## 1. Purpose

This document defines the requirements for extending the existing Zabbix Network Explorer project with a new **Wi-Fi Explorer** capability.

Wi-Fi Explorer is intended to provide a first-class operational view of wireless infrastructure inside Zabbix, using the same design principles already established for Network Explorer:

- Zabbix remains the monitoring source of truth.
- The Explorer consumes permission-filtered data available to the logged-in Zabbix user.
- The Explorer does not fabricate network state.
- Device, radio, SSID, client and topology relationships must be derived from explicit evidence.
- Wireless data and wired topology data should be correlated where that improves service assurance.
- The solution must remain compatible with Zabbix 7.0, 7.2 and 7.4.
- Existing Network Explorer behaviour and host-level dashboards must not regress.
- Wi-Fi Explorer should reuse existing rendering/runtime components where practical rather than duplicating them.

The new capability is not intended to replace wireless controllers or vendor management platforms. It is intended to provide a vendor-neutral operational and service-assurance view within Zabbix.

## 2. Product outcome

Wi-Fi Explorer shall allow an operator to move from a site-level wireless view to AP, radio, SSID, client and wired-path diagnostics without leaving the Explorer workflow.

The product shall answer operational questions such as:

- Which APs are present at this site?
- Where are they physically located?
- Which radios, bands and channels are active?
- Which SSIDs are being broadcast by each AP?
- Which VLAN is associated with each SSID?
- Is the required VLAN available from the AP-facing switch port through the Layer 2 topology?
- Where does that VLAN path fail?
- Which APs would be affected by a trunk, VLAN or switch failure?
- Which clients are associated to each AP?
- Which APs has a client roamed through?
- Are clients failing authentication or association?
- Is the RF environment congested, imbalanced or subject to co-channel or adjacent-channel interference?
- Are rogue or unexpected APs visible?
- Are APs overloaded, underpowered, disconnected, stale or otherwise degraded?
- Can the operator prove that a selected event SSID is correctly available across every participating AP and its required wired path?

The important design shift is that Wi-Fi Explorer is not only a wireless visualisation tool. It is a **wireless-to-wired service assurance view**.

## 3. Scope

### 3.1 In scope

The implementation shall cover:

- site-level wireless inventory;
- floor-plan views;
- AP placement;
- radio state;
- band and channel visualisation;
- RF heat-map overlays;
- client counts and density;
- SSID inventory;
- SSID-to-VLAN mappings;
- rogue and neighbouring AP visibility;
- interference indicators;
- utilisation and capacity indicators;
- AP wired-uplink resolution;
- LLDP correlation between AP and switch;
- switch-port correlation;
- PoE state where available;
- VLAN path validation from AP-facing port through Layer 2 topology;
- STP-aware path interpretation;
- path description, not merely pass/fail;
- service-impact / blast-radius calculations;
- client association and roaming history where the source platform exposes it;
- client-to-service tracing;
- historical diagnostics;
- permission-aware filtering;
- vendor-neutral canonical schemas;
- vendor-specific acquisition profiles where required;
- deterministic test fixtures;
- automated unit, browser and compatibility tests.

### 3.2 Out of scope for the first implementation unless evidence justifies otherwise

The first implementation does not require:

- wireless configuration push;
- controller configuration changes;
- RF auto-tuning;
- automatic channel or power changes;
- captive-portal configuration;
- authentication-server configuration;
- packet capture;
- active wireless scanning initiated from the frontend;
- arbitrary shell execution;
- a separate authoritative topology database;
- browser-side SNMP access;
- privileged global API tokens.

Wi-Fi Explorer is initially read-only from an operational-control perspective.

## 4. Relationship with Network Explorer

Wi-Fi Explorer shall be implemented as a sibling capability to Network Explorer, not as an unrelated standalone product.

The two components shall remain logically separable, but they shall share common concepts where appropriate:

- site;
- network domain;
- host identity;
- switch identity;
- interface identity;
- VLAN;
- Layer 2 edge;
- LLDP evidence;
- STP evidence;
- LAG evidence;
- findings;
- freshness;
- capability state;
- permission boundaries;
- qualification state.

Wi-Fi Explorer shall consume Network Explorer topology and VLAN evidence where available instead of re-implementing the same switch-topology logic.

It must not introduce a second independent interpretation of:

- switch identity;
- switch interface identity;
- LLDP neighbour matching;
- VLAN membership;
- STP root/path information;
- LAG membership.

Where Wi-Fi Explorer requires data that Network Explorer already holds, it shall reuse that canonical representation.

## 5. Navigation and user experience

### 5.1 Navigation

Wi-Fi Explorer shall appear as a first-class Monitoring view alongside Network Explorer.

The exact menu layout may evolve, but the intended structure is:

- Monitoring
  - Network Explorer
  - Wi-Fi Explorer

Access to Wi-Fi Explorer shall respect Zabbix role/menu permissions.

The visible data within Wi-Fi Explorer shall additionally respect ordinary Zabbix host and item permissions.

### 5.2 Primary views

Wi-Fi Explorer shall provide at minimum:

1. **Site overview**
2. **Floor plan**
3. **AP inventory**
4. **SSID assurance**
5. **RF / channel view**
6. **Clients**
7. **Rogue / neighbour APs**
8. **Findings**
9. **Data quality**

Optional later views may include:

- historical replay;
- capacity planning;
- event readiness;
- service-impact simulation.

## 6. Site overview

The site overview shall provide an operational summary for the currently selected site.

It should include:

- AP count;
- online / offline / degraded AP count;
- radio count;
- client count;
- active SSID count;
- band distribution;
- channel utilisation summary;
- high-utilisation radios;
- authentication or association failure counts where available;
- rogue AP count;
- stale dataset count;
- APs without resolved wired uplinks;
- APs with VLAN-path failures;
- APs with PoE anomalies;
- active findings by severity.

All counts must be calculated only from objects visible to the requesting user.

## 7. Floor-plan view

### 7.1 Floor-plan assets

The Explorer shall support operator-supplied floor-plan images or SVGs.

A site may contain multiple buildings and multiple floors.

Each floor shall have:

- stable floor identifier;
- display name;
- associated site;
- plan asset;
- coordinate system;
- optional physical scale;
- optional floor order / elevation metadata.

AP placement shall use persisted coordinates against the floor-plan coordinate system.

AP placement data is configuration metadata, not automatically inferred from radio measurements.

### 7.2 AP placement

Each AP shall be rendered at its configured physical position.

The operator shall be able to select an AP and inspect:

- hostname;
- controller/VC association where applicable;
- model;
- firmware;
- management status;
- wired uplink;
- switch;
- switch interface;
- PoE state;
- radios;
- bands;
- channels;
- channel width;
- transmit power where available;
- connected clients;
- broadcast SSIDs;
- SSID-to-VLAN mappings;
- current findings.

APs without known placement shall be shown in a separate unplaced list, never silently omitted.

### 7.3 Heat-map overlays

The floor-plan view shall support selectable overlays.

At minimum:

- coverage / observed signal representation;
- client density;
- channel utilisation;
- retry/error pressure;
- co-channel interference;
- adjacent-channel interference;
- rogue / neighbour AP observations.

The implementation must distinguish between:

- measured RF data;
- inferred visual interpolation;
- configured AP position.

A visual heat map must never be presented as a predictive RF survey unless predictive RF modelling has actually been implemented.

The UI shall label whether an overlay is:

- observed;
- interpolated from observed samples;
- configured;
- estimated.

### 7.4 Existing visualisation reuse

Where suitable, existing generic visualisation code from the ZabbixWidgets project may be reused or adapted, including radar/radio-oriented visual components.

Wi-Fi Explorer must not introduce a hard dependency on ZabbixWidgets as a separate product. Reused code should be incorporated through a shared or internalised component boundary as appropriate.

## 8. Radio view

Each AP radio shall expose, where supported:

- radio identifier;
- band;
- channel;
- channel width;
- transmit power;
- administrative state;
- operational state;
- utilisation;
- noise floor;
- retry rate;
- transmit / receive errors;
- connected client count;
- supported PHY / standard;
- spatial stream or MIMO capability where exposed;
- DFS state where relevant;
- configured vs observed channel;
- configured vs observed power.

Bands should be visually distinguishable, including:

- 2.4 GHz;
- 5 GHz;
- 6 GHz.

Channel visualisation shall show:

- APs on the same channel;
- APs on overlapping channels;
- channel reuse;
- congested channels;
- channels with high retry or utilisation rates.

The system shall avoid declaring interference solely from channel equality. A finding must be backed by available RF or overlap evidence.

## 9. SSID inventory and assurance

### 9.1 SSID model

Each SSID shall include, where available:

- SSID name;
- internal stable identifier;
- enabled state;
- site scope;
- AP membership;
- radio / band membership;
- associated VLAN ID;
- authentication mode;
- security mode;
- hidden / broadcast state;
- client count;
- health state;
- freshness.

Secrets such as PSKs must never be stored in Explorer datasets or displayed.

### 9.2 SSID selection

The operator shall be able to select an SSID and immediately see:

- all visible APs expected to broadcast it;
- all APs actually broadcasting it;
- APs missing the SSID unexpectedly;
- radio/band/channel used by each AP;
- configured VLAN;
- wired uplink switch and interface;
- VLAN-path state for each AP;
- findings.

### 9.3 Event readiness use case

The implementation shall explicitly support event/readiness validation.

For a selected SSID, the operator shall be able to determine whether every participating AP has a complete Layer 2 path for the SSID's required VLAN.

This is a core product requirement.

The result shall not be limited to a green/red state.

For each AP, the Explorer shall provide:

- AP;
- SSID;
- VLAN;
- AP radio(s);
- AP Ethernet uplink;
- directly attached switch;
- switch interface;
- each subsequent Layer 2 switch hop;
- relevant trunk or LAG interface at each hop;
- VLAN membership evidence at each hop;
- STP forwarding/path evidence where available;
- root bridge / agreed STP root where applicable;
- path termination;
- first point where evidence or VLAN continuity fails;
- reason for failure or uncertainty.

Example conceptual output:

```text
AP-042
  SSID: Event-WiFi
  VLAN: 56
  AP uplink: AP-042 eth0
  ↓ LLDP
  SW-F3-07 Gi1/0/18
    VLAN 56: tagged
    STP: forwarding
  ↓ LAG Po12
  DIST-B Te1/1/1
    VLAN 56: tagged
    STP: forwarding
  ↓
  CORE-A Po3
    VLAN 56: tagged
    STP root for domain: CORE-A
  Result: complete
```

Failure example:

```text
AP-067
  SSID: Event-WiFi
  VLAN: 56
  AP uplink: AP-067 eth0
  ↓ LLDP
  SW-F5-03 Gi1/0/22
    VLAN 56: tagged
    STP: forwarding
  ↓ Gi1/0/48
  DIST-C Gi1/0/7
    VLAN 56: NOT PRESENT
  Result: failed
  First failing hop: DIST-C Gi1/0/7
```

Unknown evidence must result in `unknown`, not `pass`.

## 10. Wired-uplink correlation

### 10.1 AP-side evidence

Where the AP exposes LLDP neighbour information, Wi-Fi Explorer shall collect or consume:

- local AP Ethernet interface;
- remote switch chassis identity;
- remote switch name;
- remote switch port identifier;
- observation age;
- LLDP identifier subtypes.

### 10.2 Switch-side corroboration

Where Network Explorer also observes the AP from the switch interface, the system shall correlate both directions.

Possible states:

- confirmed bidirectional;
- AP-only observation;
- switch-only observation;
- ambiguous;
- conflicting;
- unresolved.

A one-sided observation remains valid evidence but shall not be presented as confirmed bidirectional adjacency.

### 10.3 Port identity

The system shall use the same stable interface identity rules as Network Explorer.

Do not use display names alone where a stronger identifier exists.

## 11. VLAN path validation

### 11.1 Path type

The path is explicitly a **Layer 2 path**.

A hop means a Layer 2 forwarding adjacency between participating switching devices.

The initial path starts at:

```text
AP -> AP-facing switch interface
```

and continues through the observed Layer 2 topology.

### 11.2 VLAN evidence

At every hop, the selected VLAN shall be evaluated against available evidence including:

- tagged membership;
- untagged membership;
- PVID/native VLAN;
- allowed VLAN membership;
- bridge-port mapping;
- operational state;
- LAG membership;
- STP role/state;
- dataset completeness;
- dataset freshness.

### 11.3 STP interpretation

Where STP evidence is available, the path should follow the observed forwarding/root path appropriate to the VLAN/instance.

The implementation shall not infer STP forwarding solely from diagram geometry.

Where VLAN-to-STP-instance mapping is unavailable, the system shall state the limitation.

Where a domain disagrees about the STP root, no authoritative root path shall be fabricated.

### 11.4 Result states

Per AP/VLAN path:

- `complete`
- `failed`
- `partial`
- `unknown`

A failure must include a first failing hop and reason.

A partial result indicates that some path evidence exists but not enough for complete validation.

An unknown result indicates insufficient evidence to make a path claim.

## 12. Blast-radius and impact analysis

Wi-Fi Explorer shall support reverse analysis from infrastructure to affected wireless services.

Examples:

- if trunk `SW-A Gi1/0/48` loses VLAN 56, which APs and SSIDs are affected?
- if distribution switch `DIST-B` fails, which APs lose service?
- if PoE fails on a switch or switch stack, which APs are affected?
- if a LAG loses members, which AP paths become degraded?
- if a VLAN is removed from a trunk, which SSIDs become partially unavailable?

The impact output should identify:

- affected APs;
- affected floors/sites;
- affected SSIDs;
- affected VLANs;
- estimated affected current clients;
- whether an alternate observed path exists.

This is evidence-driven dependency analysis, not packet-path simulation.

## 13. Client view

### 13.1 Current client state

Where the wireless platform exposes client data, the Explorer shall show:

- anonymisable client identifier;
- associated AP;
- radio;
- band;
- channel;
- SSID;
- VLAN;
- association duration;
- signal / RSSI;
- SNR where available;
- negotiated rate;
- transmit/receive rate;
- retries;
- authentication state;
- association state;
- IP address where policy permits;
- last seen;
- current wired service path health.

Client identifiers may contain sensitive data. The design shall support masking or pseudonymisation where required.

### 13.2 Roaming history

The Explorer shall preserve enough history to reconstruct a client's AP association timeline where the source makes that evidence available.

A client timeline should show:

```text
14:03:11  AP-F2-03  5 GHz  ch 44  RSSI -61
14:08:42  AP-F2-04  5 GHz  ch 44  RSSI -66
14:16:08  AP-F3-01  5 GHz  ch 36  RSSI -58
```

Each roam event may include:

- source AP;
- destination AP;
- SSID;
- band;
- channel;
- RSSI/SNR before and after;
- association/authentication result;
- roam duration where measurable;
- wired path state of destination AP.

The UI must distinguish:

- actual recorded roam;
- inferred change between samples.

Do not describe sampled association changes as exact roam timing unless event evidence supports it.

### 13.3 Client-to-service trace

For a selected client, the system should be able to describe:

```text
Client
 -> AP
 -> radio
 -> SSID
 -> VLAN
 -> AP uplink
 -> access switch
 -> Layer 2 path
 -> VLAN/STP root or gateway boundary
```

Layer 3 continuation may be added later where authoritative gateway/routing data exists.

The trace shall help distinguish:

- RF problem;
- association/authentication problem;
- AP problem;
- switch-port problem;
- VLAN continuity problem;
- upstream service problem.

## 14. Rogue and neighbouring APs

Wi-Fi Explorer shall distinguish:

- managed AP;
- known neighbouring managed AP;
- known external AP;
- rogue / unexpected AP;
- unknown AP.

Where available, observations should include:

- BSSID;
- SSID;
- band;
- channel;
- RSSI;
- observing AP(s);
- first seen;
- last seen;
- classification;
- confidence.

The system may estimate likely physical proximity using observations from multiple managed APs, but it must not claim precise triangulated coordinates without a defensible location model.

Rogue classification must be configurable and evidence-driven.

An AP should not be declared malicious merely because it is unknown.

## 15. RF assurance and findings

Candidate findings include:

- excessive channel utilisation;
- high retry rate;
- high association failure rate;
- high authentication failure rate;
- co-channel contention;
- adjacent-channel overlap;
- AP with no clients for an unexpected period;
- overloaded AP;
- severe client imbalance between adjacent APs;
- radio disabled unexpectedly;
- SSID missing from expected AP;
- VLAN missing from AP uplink;
- VLAN missing further upstream;
- unresolved wired uplink;
- AP-side and switch-side LLDP disagreement;
- AP power / PoE degradation;
- stale AP dataset;
- stale client dataset;
- rogue AP detected;
- unusual roam churn;
- repeated client roam loop;
- coverage gap indication;
- excessive 2.4 GHz reliance where policy expects higher bands;
- DFS/channel-change instability where observable.

Findings shall include:

- stable finding ID;
- severity;
- affected object;
- evidence;
- first observed;
- last observed;
- explanation;
- remediation hint where appropriate;
- confidence;
- freshness.

## 16. Capacity and utilisation

Wi-Fi Explorer shall support operational capacity views at:

- radio;
- AP;
- floor;
- site;
- SSID.

Useful indicators include:

- client count;
- airtime/channel utilisation;
- throughput;
- retry rate;
- error rate;
- channel width;
- peak and percentile client load;
- peak and percentile utilisation;
- band distribution;
- AP imbalance;
- historical growth.

The design shall avoid treating raw client count as a complete measure of capacity.

Historical views should support at least:

- current;
- recent;
- daily;
- monthly trend.

Long-term scalar data should use Zabbix trends where appropriate.

Slow-changing inventory/topology datasets should use discard-unchanged-with-heartbeat or equivalent storage-efficient policy while preserving freshness evidence.

## 17. Intent versus observed state

The product should support explicit operational intent.

Examples:

- expected SSIDs for a site;
- expected AP membership for an SSID;
- expected VLAN for an SSID;
- expected enabled bands;
- permitted channels;
- expected minimum path availability;
- allowed rogue/known external BSSIDs;
- event-specific service definition.

Observed state shall be compared against declared intent.

Do not infer intent from historical state.

## 18. Event-readiness mode

A dedicated workflow should support temporary or recurring major events.

An event definition may contain:

- name;
- site;
- SSID;
- VLAN;
- participating APs or site/floor scope;
- expected bands;
- readiness window;
- optional minimum AP/client-capacity requirements.

The readiness view shall answer:

- is the SSID present everywhere expected?
- is the required VLAN available for every AP?
- is each AP's wired path complete?
- are radios operational?
- are there critical RF anomalies?
- are there unresolved AP uplinks?
- are rogue APs present?
- is there sufficient capacity headroom?

The result should be drillable, not merely an aggregate score.

This workflow is specifically intended to reduce failures caused by incomplete deployment, missing VLANs, incorrect AP participation or other infrastructure mistakes before an event begins.

Credential correctness such as an SSID password cannot be proven from monitoring data unless an authorised synthetic client test is later introduced. Wi-Fi Explorer must not falsely claim to validate secrets it cannot observe.

## 19. Canonical Wi-Fi data model

Introduce versioned canonical datasets analogous to Network Explorer.

Candidate datasets:

```text
we.device.snapshot
we.ap.inventory
we.ap.state
we.radio.inventory
we.radio.state
we.ssid.snapshot
we.client.snapshot
we.client.events
we.rf.neighbours
we.rogue.snapshot
we.collection.status[dataset]
we.collection.success[dataset]
```

The exact key namespace may be changed during design review, but ownership must be deterministic.

Each dataset shall include:

- schema version;
- dataset name;
- generation ID;
- attempted time;
- observed time;
- status;
- completeness;
- source;
- capability;
- errors/warnings;
- data.

The same success/failure/freshness semantics used by Network Explorer should be reused where possible.

## 20. Vendor acquisition model

Wi-Fi acquisition is expected to vary substantially by vendor.

Potential sources include:

- SNMP from AP;
- SNMP from controller / virtual controller;
- vendor controller API;
- locally available controller state;
- existing Zabbix items;
- vendor-specific MIBs.

The architecture shall normalise vendor-specific sources into the canonical Wi-Fi datasets.

Vendor adapters must be qualification-based.

No vendor may be declared supported merely because a MIB or API is documented.

Initial likely vendor families may include, as evidence becomes available:

- Aruba;
- Ubiquiti;
- Cisco;
- other controller-based or autonomous AP platforms.

The architecture must not assume all APs expose equivalent local SNMP data.

## 21. Virtual-controller and controller-based systems

The product must support controller/virtual-controller models without requiring every AP to be a manually managed Zabbix host where this is unnecessary.

A controller or VC may act as the acquisition owner for:

- member AP inventory;
- radio state;
- SSIDs;
- clients;
- RF neighbours;
- rogue AP observations.

Member APs may be materialised as discovered Zabbix hosts if that remains the chosen architecture, but data ownership must remain clear.

The frontend shall not assume that a visible AP necessarily corresponds to a directly polled SNMP endpoint.

## 22. Permissions and data isolation

Wi-Fi Explorer shall use the requesting user's existing Zabbix permissions.

It must not expose:

- inaccessible APs;
- inaccessible switches;
- hidden neighbour identities;
- clients belonging only to inaccessible infrastructure;
- counts that include inaccessible objects;
- topology paths through restricted hosts unless policy explicitly allows anonymised boundary representation.

Cross-customer or cross-domain identity resolution must follow the same isolation principles as Network Explorer.

Raw datasets may themselves contain neighbour/client information. Template and acquisition design must therefore consider source-item visibility, not merely frontend filtering.

## 23. Security and privacy

The Explorer must never collect or expose:

- Wi-Fi PSKs;
- RADIUS shared secrets;
- controller passwords;
- SNMP credentials;
- API tokens;
- private keys.

Client MAC and IP information may be operationally useful but can be sensitive.

The implementation shall support deployment policies that:

- display full identifiers to trusted operators;
- partially mask identifiers;
- pseudonymise identifiers;
- limit historical retention.

Authentication failure information shall avoid exposing credential material.

## 24. Search and selection

Search shall support:

- AP name;
- AP model;
- site;
- floor;
- SSID;
- VLAN;
- channel;
- client identifier where permitted;
- switch;
- switch interface;
- BSSID.

Selection should be persistent within an unchanged scope where safe.

A selection outside the current permitted payload must select nothing and return a safe explanatory message.

## 25. Address / URL state

Safe, opaque identifiers may be retained in the Explorer URL for repeatable operational views.

Potential state:

- site;
- floor;
- selected AP ID;
- selected radio ID;
- selected SSID ID;
- selected client opaque ID;
- selected VLAN;
- overlay;
- view mode.

Do not place:

- SSID passwords;
- client credentials;
- raw MAC addresses unless explicitly approved;
- device secrets;
- controller tokens

in URLs.

## 26. Historical behaviour

Wi-Fi Explorer should retain enough history to support operational investigation without becoming a separate time-series platform.

Historical requirements include:

- AP up/down changes;
- radio/channel changes;
- client count;
- utilisation;
- retry/error rates;
- SSID availability changes;
- client association history where available;
- rogue first/last seen;
- VLAN-path finding changes.

Where topology history is not coherent enough to reconstruct an exact historical path, the UI must state that limitation.

## 27. Data freshness

Every major object should expose freshness.

Examples:

- AP state age;
- radio state age;
- SSID observation age;
- client observation age;
- wired LLDP age;
- VLAN snapshot age;
- STP snapshot age.

A stale green result is prohibited.

An SSID path cannot be declared fully healthy if a required topology dataset is stale beyond its accepted threshold.

## 28. Performance and scale

The implementation shall be designed for large sites.

Initial design target:

- 300+ APs per site;
- several radios per AP;
- several SSIDs per AP;
- thousands of concurrent clients;
- multiple buildings/floors;
- integration with Network Explorer estates of up to the existing switch design ceiling.

The floor-plan renderer shall:

- avoid unbounded physics simulations;
- use deterministic coordinates;
- render incrementally where practical;
- avoid redrawing the whole site for simple selection/filter changes;
- keep interactions responsive.

Large client populations should be aggregated until the operator drills into a specific AP, SSID or area.

Do not send every historical client observation to the browser by default.

## 29. Storage efficiency

Wireless datasets can become significantly larger than switch topology datasets.

The implementation shall:

- separate inventory from state;
- separate aggregate metrics from per-client detail;
- avoid writing unchanged inventory repeatedly;
- use discard-unchanged-with-heartbeat where appropriate;
- use trends for long-lived numeric metrics;
- keep short retention for high-cardinality client event data unless there is an operational requirement for longer retention;
- avoid duplicating controller-level data into every AP where it can be referenced safely;
- measure actual database impact before production rollout.

Retention shall be configurable.

## 30. Test requirements

### 30.1 Unit tests

Tests shall cover:

- schema validation;
- AP identity;
- radio identity;
- SSID identity;
- client identity/masking;
- AP-to-switch LLDP matching;
- bidirectional LLDP corroboration;
- unresolved adjacency;
- conflicting adjacency;
- SSID-to-VLAN mapping;
- VLAN path success;
- first failing VLAN hop;
- unknown path evidence;
- STP disagreement;
- LAG traversal;
- blast-radius calculation;
- permission filtering;
- stale evidence;
- rogue classification;
- roam history ordering;
- sampled association change vs explicit roam event.

### 30.2 Browser tests

Browser coverage shall include:

- site overview;
- floor-plan load;
- AP selection;
- band/channel overlays;
- SSID selection;
- path rendering;
- failed path highlighting;
- path hop description;
- client selection;
- roaming timeline;
- rogue AP view;
- search;
- URL state;
- inaccessible object handling;
- large-site rendering.

### 30.3 Compatibility

The existing Zabbix compatibility matrix shall remain:

- Zabbix 7.0;
- Zabbix 7.2;
- Zabbix 7.4.

Wi-Fi Explorer must be included in the compatibility workflow before release.

## 31. Qualification

Wireless vendor support shall use the same disciplined qualification approach as Network Explorer.

For each vendor/model/controller family record:

- vendor;
- model;
- controller family;
- firmware;
- acquisition source;
- capabilities;
- evidence;
- fixtures;
- tested Zabbix versions;
- polling/API cost;
- limitations;
- qualification state.

Unknown remains unknown until evidenced.

Synthetic fixtures do not establish real-hardware support.

## 32. Deployment and migration

Wi-Fi Explorer shall be introduced without requiring immediate replacement of existing wireless monitoring.

Deployment sequence should support:

1. install frontend module;
2. import Wi-Fi schemas/templates;
3. connect or qualify one vendor source;
4. onboard a small representative site or controller;
5. verify Zabbix load and storage;
6. validate AP/radio/SSID data;
7. validate wired-uplink correlation;
8. validate VLAN path assurance;
9. validate permissions;
10. expand to additional sites.

Existing monitoring shall remain until replacement coverage is proven.

## 33. Findings integration with Network Explorer

Where a wireless problem has a wired cause, the finding should cross-link directly to Network Explorer.

Examples:

- AP SSID VLAN missing from switch port;
- upstream trunk missing VLAN;
- switch interface down;
- LAG degraded;
- STP evidence incomplete;
- LLDP mismatch.

Likewise, Network Explorer should be able to show impacted APs/SSIDs when a selected switch/link/VLAN has known Wi-Fi dependencies.

The products should share identifiers and evidence, not duplicate state.

## 34. Reporting

Wi-Fi Explorer should provide exportable operational reports.

Potential reports:

- AP inventory by site/floor;
- radio/channel plan;
- SSID coverage by AP;
- SSID-to-VLAN assurance;
- failed VLAN paths;
- rogue APs;
- client density;
- high-utilisation radios;
- authentication/association failures;
- roaming anomalies;
- AP wired-uplink mapping;
- PoE health;
- event readiness.

Reports must include:

- scope;
- generation time;
- data freshness;
- unsupported/unknown coverage;
- permission-filtered content.

## 35. Acceptance criteria

The first usable Wi-Fi Explorer release shall not be considered complete until all of the following are demonstrated:

- Wi-Fi Explorer appears as a first-class Zabbix Monitoring view.
- A site can be selected.
- A floor plan can be displayed.
- APs can be placed and selected.
- AP radios, bands and channels can be viewed.
- SSIDs can be enumerated per AP.
- SSID-to-VLAN mapping can be shown.
- At least one supported vendor source has been qualified on real evidence.
- AP wired uplinks can be resolved through LLDP.
- Switch-side LLDP can corroborate AP-side adjacency where both are available.
- A selected SSID can enumerate all participating APs.
- A selected SSID/VLAN can perform a Layer 2 path check for each AP.
- Each path is described hop-by-hop.
- A missing VLAN at an intermediate hop is identified accurately.
- STP evidence is incorporated without fabricating paths.
- Blast radius can identify AP/SSID impact from a selected wired failure.
- Client state can be displayed where the source exposes it.
- Roaming history can be displayed where event or sampled association evidence exists.
- Permission filtering prevents inaccessible APs/switches/clients from leaking through counts, paths or search.
- All unit/browser tests pass.
- Zabbix 7.0/7.2/7.4 compatibility passes.
- Storage and polling/API load have been measured on a representative canary.

## 36. Recommended implementation phases

### Phase A — Wi-Fi canonical model and site/AP inventory

Implement:

- schemas;
- permission-aware reader;
- site/AP/radio model;
- module navigation;
- site overview;
- AP inventory;
- qualification scaffolding.

### Phase B — Floor plan and RF visualisation

Implement:

- floor-plan assets;
- AP placement;
- selectable overlays;
- band/channel visualisation;
- client density;
- rogue/neighbour view.

### Phase C — SSID and wired-uplink correlation

Implement:

- SSID inventory;
- SSID-to-VLAN mapping;
- AP LLDP;
- switch-side LLDP corroboration;
- AP-to-switch relationship.

### Phase D — VLAN service-path assurance

Implement:

- per-SSID VLAN selection;
- Layer 2 path traversal;
- hop-by-hop path description;
- VLAN membership validation;
- STP-aware interpretation;
- first failing hop;
- uncertainty handling.

This phase is a key product milestone.

### Phase E — Blast radius and event readiness

Implement:

- reverse dependency analysis;
- affected AP/SSID views;
- event definitions;
- event-readiness status;
- capacity/readiness summary.

### Phase F — Client journey

Implement:

- current client state;
- client search;
- association timeline;
- roaming timeline;
- client-to-service trace.

### Phase G — Vendor expansion and optimisation

Implement:

- additional vendor families;
- storage tuning;
- long-term capacity views;
- further RF analytics;
- qualification evidence.

## 37. Design principles that must not be violated

1. **Do not fabricate evidence.**
2. **Do not infer a healthy VLAN path merely from topology geometry.**
3. **Do not treat unknown as healthy.**
4. **Do not bypass Zabbix permissions.**
5. **Do not introduce a global privileged fleet token.**
6. **Do not duplicate Network Explorer's canonical switch/VLAN/STP interpretation.**
7. **Do not expose wireless credentials.**
8. **Do not call an interpolated RF map a predictive survey.**
9. **Do not equate an unknown AP with a malicious rogue AP.**
10. **Do not claim exact roaming events when only sampled association state exists.**
11. **Do not make a controller mandatory where direct AP evidence is sufficient.**
12. **Do not make direct AP polling mandatory where a controller/VC is the authoritative source.**
13. **Do not replace existing operational monitoring until coverage equivalence is demonstrated.**
14. **Do not allow storage volume to grow without explicit measurement and retention policy.**
15. **Keep the product operationally explainable: every finding and service-path result must expose the evidence behind it.**

## 38. Product definition

The intended end state is:

> **Wi-Fi Explorer provides a permission-aware operational model of APs, radios, SSIDs, clients and RF conditions, correlated with Network Explorer's physical and Layer 2 topology so an operator can prove whether a wireless service is actually available from the radio through the wired network, identify exactly where it fails, and understand the resulting service impact.**

That cross-domain assurance capability is the principal differentiator. The floor plan and RF overlays are valuable, but the strongest operational outcome is the ability to select an SSID and prove, AP by AP, that its required VLAN and Layer 2 forwarding path exist end-to-end.
