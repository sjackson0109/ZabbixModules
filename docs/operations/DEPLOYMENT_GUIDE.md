# Deployment guide: Docker test server and multi-proxy production

This guide installs release 2.3.0, which is one package with two pages: **Network Explorer** (switches, links, VLANs, STP, LAGs) and **Wi-Fi Explorer** (access points, radios, SSIDs and, with a vendor template such as Aruba Instant's, clients, and how they reach the wired network). They are installed together, in the same steps, on two kinds of estate:

- **Test:** one Docker host running the Zabbix server, frontend and one or more proxies as containers.
- **Production:** one frontend server and several proxies spread across data centres, each proxy built from a customised Dockerfile.

It assumes Zabbix **7.4** and the official `zabbix/*` images, which is what the lab verifies (7.4.3, see [runtime evidence](../../lab/VERIFICATION.md)). 7.0 and 7.2 work the same way; pick the matching template directory. Where your images or paths differ, the step says what to check. [INSTALL.md](INSTALL.md) is the short reference; this guide is the step-by-step version.

## 1. What goes where

The most important fact first: **with the native SNMP templates, nothing has to be installed on the proxies or the Zabbix server**, for either page.

| Component | Installed on | What it is |
|---|---|---|
| Frontend package (7 module directories) | Every Zabbix frontend (web) container or server | The Network Explorer module, its five dashboard widgets and the Wi-Fi Explorer module. Wi-Fi Explorer is built on Network Explorer's services (permission-aware reads, validation, freshness, and the switch model it uses for AP uplinks and VLAN paths), so the seven directories are one package and are always installed together. Everything is read through the logged-in user's permissions. |
| Native SNMP templates (one file per template) | Imported once, through the frontend, into the Zabbix database | `ne__generic_switch.yaml` and the other `ne_*.yaml` files for switches, and `we__generic_access_point.yaml` and the other `we_*.yaml` files for access points and Aruba Instant clusters. All are `walk[]` SNMP items with JavaScript preprocessing. They run on whichever proxy monitors the host, using the proxy's built-in SNMP poller and JavaScript engine. The switch, AP and cluster templates also carry each host's inherited host dashboard. |
| Python collector (optional fallback) | Only proxies that must reach switches native SNMP items can't | Frozen schema 1.0 fallback for switches only. **Not needed for normal operation.** See section 9. |

So the custom Python libraries and OpenSSL builds in your proxy Dockerfiles are not required. The proxies need only:

- SNMP (UDP 161) reachability to the switches they monitor, and to each Aruba Instant cluster's virtual-controller (AVC) address, plus each AP's own address for APs on the generic template or enrolled individually (sections 7.1a and 7.2);
- the device's SNMP credentials on the host's SNMP interface in Zabbix, as for any SNMP host;
- an SNMP timeout long enough for a bulk walk (section 5.2).

Nothing in either module calls a proxy, runs a command or opens a network connection from a browser request.

What each page needs from the other:

- **Network Explorer** works on its own: with no Wi-Fi hosts, Monitoring → Wi-Fi Explorer simply says no Wi-Fi data source is visible.
- **Wi-Fi Explorer** shows APs, radios, SSIDs, clients and capacity from its own template. Its wired views (each AP's uplink port, VLAN paths to the spanning-tree root, the impact of a switch failure) come from Network Explorer's data about the switches the APs plug into, so those switches must be enrolled in Network Explorer with the same `site` tag as the cluster (2.4, 7.1).

## 2. Before you start

1. **Confirm versions.** Frontend, server and every proxy must run the same Zabbix major version (7.4.x here). Check with `docker exec <container> zabbix_proxy -V` (or `zabbix_server -V`) and the frontend footer.
2. **Back up.**
   - Database: your normal Zabbix database backup.
   - Export any existing templates and dashboards you might touch (Data collection → Templates → Export; dashboards via the API `dashboard.get`).
   - Keep a copy of the current `modules/` directory contents of each frontend, if any.
3. **Build the release packages** from a checkout of the release tag, and verify them:

   ```sh
   python3 scripts/package.py
   cd dist
   sha256sum -c SHA256SUMS
   ```

   You get `network-explorer-frontend-2.3.0.tar` (the seven module directories under `frontend/`, Wi-Fi Explorer included), `network-explorer-templates-2.3.0.tar` (both template files under `templates/native/<version>/`), and the optional collector package. A published release has the same archives attached, built by the release workflow. Copy only the archives to your servers; nothing else from the checkout is needed.
4. **Decide the `ne.domain` value(s).** Every switch host needs exactly one host tag `ne.domain` (for example `ne.domain=corp`). Peer matching only happens between hosts with the same value. Use one value across all five data centres if they are one routed/LLDP-connected network; use different values only for networks that must never be matched to each other (for example separate customers with overlapping IPs). The tag never grants visibility. Wi-Fi hosts get the same value as the switches they connect to.
5. **Decide the `site` values.** The host tag `site=<name>` (for example `site=dc-north`) is what both pages narrow by, and it is how Wi-Fi Explorer finds the switches an Aruba cluster's APs plug into: AP uplinks, VLAN paths and impact are worked out only against switches with the same `site` value as the cluster's host. Pick one value per physical site and use it on that site's switches and Wi-Fi hosts alike.
6. **Check host names.** Technical and visible host names must be unique across the whole installation; LLDP peer matching relies on that.
7. **List your Wi-Fi sources.** For each access point on the generic template note its address, proxy and SNMP credentials. For each Aruba Instant cluster note its virtual-controller (AVC) address, which proxy can reach it, and its SNMP credentials. Instant answers for the whole cluster only on the elected virtual controller, so the floating AVC address is the one to monitor, not a member AP's address.
8. **Decide the client identifier policy.** Wi-Fi Explorer stores client identifiers (MAC, IP address, client name) only as far as `{$WE.CLIENT.IDENTIFIERS}` allows: `partial` (the default) keeps part of each identifier, `pseudonymised` replaces it with a keyed hash, `full` stores it as reported. Agree the setting with whoever owns your privacy policy before enrolling clusters; values already collected keep the form they were stored in.
9. **Gather floor plans** (optional, can come later). Floor plans are images of each floor, at a known width in metres, uploaded later as Zabbix background images (7.5).

## 3. Install the frontend modules

The seven directories must sit side by side in the frontend's `modules/` directory, with their names unchanged:

```
modules/networkexplorer      Monitoring → Network Explorer, and the services the others use
modules/neportpanel          widget: Port panel
modules/netopology           widget: Physical topology
modules/neinterfacedetail    widget: Interface detail
modules/nedataquality        widget: Data quality
modules/nefindings           widget: Findings
modules/wifiexplorer         Monitoring → Wi-Fi Explorer
```

In the official `zabbix/zabbix-web-*` images the frontend root is `/usr/share/zabbix`, so the target is `/usr/share/zabbix/modules/` (verified on 7.0.20, 7.2.7 and 7.4.3). On a package-installed frontend, find the directory that contains `zabbix.php` and use its `modules/` subdirectory; do not assume the path.

Choose one of the methods below. Bind mounts suit the test server; a derived image suits production because the version is baked into an image tag you can roll back.

First check whether your web container already bind-mounts the whole `modules/` directory. The official [zabbix-docker](https://github.com/zabbix/zabbix-docker) compose files do, read-only, on every `web-*` service:

```yaml
      - ${DATA_DIRECTORY}/usr/share/zabbix/modules/:/usr/share/zabbix/modules/:ro
```

```sh
docker compose config | grep 'usr/share/zabbix/modules'
```

If that line is there, use **3.1**. If it is not, use **3.2** or **3.3**. Never combine the two: a per-module mount inside a read-only `modules/` mount fails when the container starts (section 10).

### 3.1 Option A: copy into the mounted modules directory (zabbix-docker compose)

Here Zabbix already reads `${DATA_DIRECTORY}/usr/share/zabbix/modules/` on the Docker host, so the seven directories go straight into it and the compose file needs no change. Zabbix finds a module only at `modules/<name>/manifest.json`, one level down, so the seven directories must sit directly in that directory, not under a sub-folder such as `modules/network-explorer/`.

Keep each release unpacked outside the modules directory, so you can roll back, then copy it in. Use the same `DATA_DIRECTORY` value your compose file uses (it is in the `.env` file next to it; check the path, for example `/media/data` versus `/root/media/data`):

```sh
DATA_DIRECTORY=/media/data            # as in your compose .env
RELEASE=2.3.0
MODULES=$DATA_DIRECTORY/usr/share/zabbix/modules

# 1. Unpack the release outside the modules directory.
mkdir -p "$DATA_DIRECTORY/network-explorer/$RELEASE"
tar -xf network-explorer-frontend-$RELEASE.tar -C "$DATA_DIRECTORY/network-explorer/$RELEASE"

# 2. Replace the seven module directories with this release's.
mkdir -p "${MODULES:?}"
for m in networkexplorer neportpanel netopology neinterfacedetail nedataquality nefindings wifiexplorer; do
  rm -rf "${MODULES:?}/$m"
done
cp -R "$DATA_DIRECTORY/network-explorer/$RELEASE/frontend/." "$MODULES/"
chmod -R a+rX "$MODULES"

# 3. Check: seven manifests, one level down.
ls "$MODULES"/*/manifest.json
```

The `rm -rf` names only the seven package directories (and `${MODULES:?}` stops it if the variable is empty), so other modules in the directory are left alone, and removing them first means files dropped in a new release do not linger. Then recreate the web container so it sees the files (`docker compose up -d --force-recreate <web service>`; no `--build` is needed), and continue at 3.4. A rollback is the same commands with the previous `RELEASE`.

### 3.2 Option B: bind-mount each module directory (compose without a modules mount)

Use this only if your web service does **not** mount the whole `modules/` directory (see above). Unpack the package into a versioned directory on the Docker host:

```sh
sudo mkdir -p /opt/zabbix/network-explorer/2.3.0
sudo tar -xf network-explorer-frontend-2.3.0.tar -C /opt/zabbix/network-explorer/2.3.0
sudo ln -sfn /opt/zabbix/network-explorer/2.3.0 /opt/zabbix/network-explorer/current
sudo chmod -R a+rX /opt/zabbix/network-explorer/2.3.0
```

The web container runs as an unprivileged user, so files must be world-readable and directories traversable; nothing needs to be writable. Then mount each directory read-only. In your compose file (service name and image are examples):

```yaml
services:
  zabbix-web:
    image: zabbix/zabbix-web-nginx-pgsql:alpine-7.4.3
    volumes:
      - /opt/zabbix/network-explorer/current/frontend/networkexplorer:/usr/share/zabbix/modules/networkexplorer:ro
      - /opt/zabbix/network-explorer/current/frontend/neportpanel:/usr/share/zabbix/modules/neportpanel:ro
      - /opt/zabbix/network-explorer/current/frontend/netopology:/usr/share/zabbix/modules/netopology:ro
      - /opt/zabbix/network-explorer/current/frontend/neinterfacedetail:/usr/share/zabbix/modules/neinterfacedetail:ro
      - /opt/zabbix/network-explorer/current/frontend/nedataquality:/usr/share/zabbix/modules/nedataquality:ro
      - /opt/zabbix/network-explorer/current/frontend/nefindings:/usr/share/zabbix/modules/nefindings:ro
      - /opt/zabbix/network-explorer/current/frontend/wifiexplorer:/usr/share/zabbix/modules/wifiexplorer:ro
```

Mount the seven directories individually, not the whole `modules/` directory: a single mount over `modules/` hides any other modules or widgets you have installed there.

Apply it with `docker compose up -d zabbix-web`. Docker resolves the `current` symlink when the container starts, so after switching versions you must recreate the container (section 8).

Check that all seven are visible inside the container:

```sh
docker exec <web container> ls /usr/share/zabbix/modules/
```

### 3.3 Option C: build a frontend image with the modules inside (production)

```dockerfile
# Dockerfile.web
FROM zabbix/zabbix-web-nginx-pgsql:alpine-7.4.3
USER root
# Unpacked from network-explorer-frontend-2.3.0.tar next to this Dockerfile: all seven module directories.
COPY frontend/ /usr/share/zabbix/modules/
RUN chmod -R a+rX /usr/share/zabbix/modules
# Return to the base image's user (check with: docker image inspect -f '{{.Config.User}}' <base image>).
USER 1997
```

```sh
mkdir build && tar -xf network-explorer-frontend-2.3.0.tar -C build
cp Dockerfile.web build/
docker build -t registry.example/zabbix-web-ne:7.4.3-ne2.3.0 -f build/Dockerfile.web build
```

Use the `-mysql` web image instead if your database is MySQL/MariaDB. Tag the image with both the Zabbix and the release version so a rollback is a tag change. If you already maintain a customised web image, add the `COPY` and `chmod` lines to it instead. `COPY frontend/` copies every directory in the package, so Wi-Fi Explorer is in the image with nothing extra to add.

### 3.4 Register and enable the modules

Module state is stored in the Zabbix database, so this is done once per installation, not per container.

1. Log in as a Super admin and open **Administration → General → Modules**.
2. Click **Scan directory**. The message lists the modules added: *Network Explorer*, five *Network Explorer: …* widgets (Port panel, Topology, Interface detail, Data quality, Findings) and *Wi-Fi Explorer*, seven in all. If one is missing, it may already have been registered by an earlier scan (look for it in the list), or see section 10.
3. **Scanning only registers the modules; it does not enable them.** They are listed with the status *Disabled*, nothing appears in the menu yet, and this step is required. Enable them, either by clicking the red *Disabled* in each module's **Status** column, or by ticking the modules and clicking **Enable** below the list. Enable **Network Explorer** first, then the five widgets, then **Wi-Fi Explorer**; each module's status then reads *Enabled*. The widgets and Wi-Fi Explorer show a message saying Network Explorer is needed while it is disabled; that is expected. Keep all seven enabled; disabling Network Explorer later takes Wi-Fi Explorer down with it.
4. Reload the page, then check that **Monitoring → Network Explorer** and **Monitoring → Wi-Fi Explorer** now appear in the menu. They are the network-wide and wireless views; no global dashboard has to be created or imported. Dashboard recipes in `dashboards/` are optional examples. Until Wi-Fi hosts are enrolled (section 7), the Wi-Fi page says no Wi-Fi data source is visible.

If you run more than one frontend against the same database, every frontend must have identical module files; the database tells all of them the modules are enabled.

### 3.5 User roles

- The **Network Explorer** and **Wi-Fi Explorer** menu entries are shown only to roles with access to *Monitoring → Hosts*.
- In **Users → User roles**, each role that should use them must allow all seven modules under *Access to modules*. Roles with *Default access to new modules* enabled get them automatically; check restricted roles explicitly.
- What each user sees is limited by their host group permissions, exactly as elsewhere in Zabbix. On the Wi-Fi page a user sees only the APs whose cluster host they can read, and only the switches they can read in uplinks, VLAN paths and impact. No API token or privileged account is used.
- Wi-Fi Explorer's **Configure** link (floors, AP placement, SSID VLAN intent, events, known BSSIDs) is shown only to **Super admins**, because that configuration is stored in the module's own settings, which only a Super admin can change. Everyone else gets a read-only page.

## 4. Import the templates

Unpack `network-explorer-templates-2.3.0.tar` on your workstation and use the files for your version, here `templates/native/7.4/`. Import the files below with **Data collection → Templates → Import**, one at a time; each stands alone. Leave the default rules (create new, update existing; do not tick *Delete missing* on a first import).

1. The switch templates, one self-contained template per file, in the template group `Templates/Network Explorer` (created by the first import):
   - `ne__generic_switch.yaml`, **Network Explorer - Generic Switch**: everything Network Explorer collects from a switch (device identity, interfaces with port discovery, port capability, LLDP, VLAN, STP, LAG and PoE), and the switch host dashboard (Ports, Topology, Findings) built from the five widgets. One per switch; nothing else needs linking beside it.
   - `ne_cisco_small_business_switch.yaml`, `ne_cisco_sg300_switch.yaml`, `ne_dell_n_series_switch.yaml` and `ne_dell_x_series_switch.yaml`, the vendor switch templates (optional): everything the Generic Switch collects plus hardware health (CPU, memory where the MIBs give it, fans, power supplies and temperature) from the vendor's MIBs, with the same host dashboard. The Cisco and Dell N-Series templates also name PoE ports after their interfaces, and the Cisco ones report the power each port draws. Link one *instead of* the Generic Switch, and only to a model and firmware the [qualification matrix](../qualification/MATRIX.md) lists; every other switch stays on the Generic Switch. To move a switch that is already on the Generic Switch, see 8.6.
   - `ne_cisco_cbs220_switch.yaml`, **Network Explorer - Cisco CBS220 Switch** (optional): the Cisco Business 220, which has none of the Small Business MIBs. It collects what the Generic Switch does, with PoE ports named after their interfaces. Its hardware health (CISCO-ENVMON-MIB) is included but disabled, because the switch does not answer that MIB on firmware 2.0.2.15; enable it only on firmware that does.
2. The access-point templates, one self-contained template per file, in the template group `Templates/Wi-Fi Explorer` (created by the first import):
   - `we__generic_access_point.yaml`, **Wi-Fi Explorer - Generic Access Point**: any access point that implements the standard MIBs (the IEEE 802.11 MIB above all), read at the AP's own address: the AP, its radios (band, channel, transmit power) and SSIDs, and a host dashboard of radios up by band. No standard MIB lists clients, channel utilisation or RF neighbours, so it collects none. It also collects the AP's own LLDP neighbours, which confirm its uplink (7.2). One host per AP.
   - `we_aruba_instant_virtual_controller.yaml`, **Wi-Fi Explorer - Aruba Instant Virtual Controller**: the whole cluster (device, AP inventory and state, radio inventory and state, SSIDs, clients, and the hourly capacity values) from AI-AP-MIB, read at the virtual-controller address, and a cluster host dashboard (APs up and down, clients, channel utilisation and radios by band) built from Zabbix's own widgets. One host per cluster.
   - `we_aruba_instant_access_point.yaml`, **Wi-Fi Explorer - Aruba Instant Access Point**: one AP's own RF view (the neighbouring access points it hears) and its own LLDP neighbours, which confirm its uplink (7.2), read at that AP's own address. Optional, one host per AP.

Keep **Dashboards** ticked in the import rules (it is by default). The templates import whether or not the modules are enabled yet; until they are, the switch host dashboard shows its widgets as *Inaccessible widget*. The Wi-Fi dashboards need no module. Floors, paths, findings and clients stay on the Wi-Fi Explorer page.

None of the templates carries SNMP credentials; they use the host's SNMP interface. Wi-Fi item keys start with `we.` and switch keys with `ne.`, so they coexist with each other and with stock templates. The two per-AP templates also carry Network Explorer's LLDP items (`ne.lldp.*` and the rest of that dataset, the same keys a switch has), so never link a switch template to an access point's host.

Templates live in the database, so import once from the single frontend; every proxy receives the item configuration through the normal proxy configuration sync.

Do not import anything from `templates/lab/`. Those are trapper replay templates for test fixtures, not SNMP monitoring.

## 5. Prepare the proxies

### 5.1 No image changes are needed

Your existing proxy images are fine as they are. The SNMP items use `walk[]`, which the proxy's own SNMP poller handles, and the normalisers run in the proxy's built-in JavaScript preprocessing. No Python, OpenSSL build, MIB files or external scripts are involved.

If you are building new proxy images anyway, keep them on the same Zabbix patch as the server and frontend. A typical customised proxy keeps working unchanged, for example:

```dockerfile
FROM zabbix/zabbix-proxy-mysql:alpine-7.4.3
# Your existing customisation (Python libraries, OpenSSL, CA bundles, ...) stays here.
# Network Explorer adds nothing to this image.
```

### 5.2 SNMP timeout and pollers

Each dataset, switch or Wi-Fi, is one bulk `walk[]` over several tables, which on a large switch or a large Aruba cluster takes longer than a single SNMP get. On an Instant cluster the virtual controller answers for every AP, radio and client in the cluster, so its AP, radio and client walks grow with the cluster. The templates do not set per-item timeouts, so the proxy's SNMP timeout applies.

- In **Administration → Proxies → (proxy) → Timeouts**, set **SNMP agent** to at least **10s** for proxies that poll large switches, stacks or Aruba clusters, or set it globally in **Administration → General → Timeouts** if the proxies inherit the global values. Raise it if the `*.attempt` items report timeouts (section 6).
- In Docker, you can also set the proxy's base `Timeout` with the `ZBX_TIMEOUT` environment variable; the per-proxy frontend setting takes precedence for item types it overrides.
- If proxies already poll many SNMP hosts, watch the SNMP poller busy rate (`zabbix[process,snmp poller,avg,busy]` on the proxy's self-monitoring) after enrolment and raise `StartSNMPPollers` (`ZBX_STARTSNMPPOLLERS` in the official images; check your image's environment variable list) if it stays high.

### 5.3 Load and buffer sizing

**Switches.** Per switch, the template polls eight datasets at the template defaults: interface state every 1m, STP 2m, LLDP, LAG and PoE 5m, VLAN 10m, port capability 15m, interface inventory and device identity 1h. A vendor template adds hardware health every 5m. The PoE snapshot is about 350 bytes per PoE port (measured on the captured 48-port CBS350 stack and N1548P), and PoE discovery adds one or two items per PoE port and five per PSE unit. Snapshots are stored as text values of about 350–400 bytes per port each (measured on the lab's simulated 27- and 48-port switches), and per-port discovered items add roughly 3–5 items per port (151 and 235 items on those two lab hosts).

For a proxy with many switches, check that `ProxyOfflineBuffer` and the proxy database have room for the extra text values during a link outage to the server. Intervals are macros (`{$NE.IF.STATE.INTERVAL}`, `{$NE.LLDP.INTERVAL}` and so on) and can be lengthened per host or per template.

**Generic APs.** Per AP host, the generic template polls six small walks: AP state, radio state and SSIDs every 5m; device, AP inventory and radio inventory every 1h.

**Aruba clusters.** Per cluster host, the VC template polls seven datasets at the template defaults: AP state, radio state, SSIDs and clients every 5m; device, AP inventory and radio inventory every 1h. The capacity values are added hourly. Each is one text snapshot of the whole cluster, so the client snapshot is the largest and grows with the number of associated clients. Each optional AP host adds one RF neighbour walk every 15m. Intervals and history are macros on the template (`{$WE.<DATASET>.INTERVAL}`, `{$WE.<DATASET>.HISTORY}`, for example `{$WE.CLIENT.INTERVAL}`); the Capacity tab reads trends of the `we.capacity.*` items, kept for `{$WE.CAPACITY.TRENDS}` (365d).

**Large stacks and text size:** a single snapshot grows with the port count. At about 370 bytes per port, the interface snapshots of a stack with more than roughly 170 ports approach 64 KB. Zabbix text history is limited in size on some database backends (see "Item value types" in the Zabbix documentation for your version and database). If a value is truncated it is no longer valid JSON; Network Explorer then reports the dataset as invalid on the Data Quality widget rather than drawing wrong ports. This limit is an estimate from lab data and has not been tested against a real large stack; check the first large stack you enrol (section 6).

### 5.4 Proxy groups

If you use proxy groups across data centres, Zabbix can move a host between proxies in the group. Every proxy in the group must then be able to reach that host's SNMP address with the same credentials. If a data centre's switches or Aruba clusters are reachable only from its local proxy, assign those hosts to that proxy directly rather than to a group. For an Aruba cluster, the AVC address moves between APs when the controller role moves, so allow UDP 161 from the proxy to the AVC address itself, not only to the AP that currently holds it.

## 6. Enrol switches and verify

Enrol the switches first: Wi-Fi Explorer's uplinks, VLAN paths and impact views are built on them.

### 6.1 Enrol a pilot switch first

Pick one switch per data centre, ideally one with LLDP neighbours that are also monitored.

1. Make sure the host has an **SNMP interface** (v2c or v3) with working credentials, and is **Monitored by** the right proxy (or proxy group).
2. Add the host tags **`ne.domain`** (2.4) and **`site`** (2.5).
3. Link **`ne__generic_switch`** (Network Explorer - Generic Switch), or the vendor template its model is qualified for (section 4). It is one self-contained template holding every switch item and the host dashboard.

The Network Explorer keys all start with `ne.`, so the templates coexist with existing SNMP templates such as the stock network templates. The switch is then walked by both, so expect more SNMP load on the device.

### 6.2 Check collection (allow one inventory interval)

Interface inventory is polled hourly, so either wait for it or use **Execute now** on the host's `ne.raw.*` items (Data collection → Hosts → Items, filter key `ne.raw`; tick them and click *Execute now*).

In **Monitoring → Latest data**, filter the host and the key `ne.`:

- The `*.attempt` items (`ne.device.attempt`, `ne.interfaces.attempt`, `ne.interfaces.inventory.attempt`, `ne.lldp.attempt`, …) should hold envelopes with `"status":"ok"`. `unsupported` means the switch does not publish that MIB (for example no Q-BRIDGE-MIB means no VLAN overlay); the other datasets keep working.
- `failed` with a timeout means the SNMP timeout (5.2) is too low or UDP 161 is blocked from that proxy.
- Interface discovery should have created per-port items with no items left *Not supported*.
- `ne.poe.attempt` is `unsupported` on a switch without PoE, which raises nothing; on a PoE switch, PoE discovery creates an item per PoE port and per PSE unit.
- If the SNMP interface turns red (unavailable), it is a credentials or reachability problem, not a Network Explorer one.

### 6.3 Check the frontend

1. **Monitoring → Network Explorer**. With no selection it draws every switch you can read as a Layer 2 topology. Choose the pilot host as *Seed device*, or its *Site* if you tag hosts with `site=<name>`. Click the switch to see its interfaces, and click a link to see both ends. If the switches run spanning tree, the root bridge is marked ★.
2. Open the host dashboard (Monitoring → Hosts → *Dashboards*, or *Open host dashboard* on the Explorer page) or add the **Port panel**, **Physical topology** and **Data quality** widgets to a dashboard. Check:
   - ports appear with correct state and speed, and stacks show one tab per member (this needs ENTITY-MIB; switches without it show ports unplaced rather than guessed);
   - an LLDP neighbour that is also monitored, with the same `ne.domain`, can be clicked through to its host;
   - the Data quality widget shows no invalid or stale datasets.
3. Set the management subnet(s) in the Explorer page's *Management subnet* field (or the Physical topology widget's field, or `management_cidr=` on the JSON route) (see the [module README](../../frontend/networkexplorer/README.md)); physically connected devices outside it stay visible and are highlighted.
4. **Log in as an ordinary user** with access to only some host groups and confirm they see only those hosts, and that neighbours they may not see are shown as unresolved placeholders without names.

A quick machine check of the same data, as a logged-in user: `zabbix.php?action=networkexplorer.data&hostid=<id>` returns the permitted current state as JSON.

### 6.4 Roll out

When the pilot switches in every data centre look right, enrol the rest in batches (a host group or a host prototype/auto-registration action that adds the `ne.domain` and `site` tags and links `ne__generic_switch`). Enrol at least the switches the APs plug into, and the path from them to the spanning-tree root, before relying on Wi-Fi Explorer's VLAN paths. Watch the proxies' SNMP poller and preprocessing busy rates after each batch.

Ports to alert on, and expected speeds, are set with per-interface macros:

- `{$NE.IF.MONITOR:"Gi1/0/24"}=1` raises a trigger when that port goes down.
- `{$NE.IF.EXPECTED_SPEED:"Gi1/0/23"}=1000000000` flags that port when it runs below 1 Gbit/s for longer than `{$NE.IF.SPEED.DEGRADED_FOR}` (10m). With `0`, the expected speed is derived from what both ends advertise.

## 7. Enrol Wi-Fi clusters and verify

Pick one Wi-Fi template per access point or cluster, never two for the same APs:

- An Aruba Instant cluster: a cluster host with `we_aruba_instant_virtual_controller` (Wi-Fi Explorer - Aruba Instant Virtual Controller; 7.1 and 7.2 below). It gives the most: clients and channel utilisation as well as APs, radios and SSIDs.
- Any other access point that implements the IEEE 802.11 MIB: one host per AP with `we__generic_access_point` (Wi-Fi Explorer - Generic Access Point; 7.1a). Without a vendor template there are no clients, utilisation or RF neighbours for those APs.
- Another vendor's controller or cluster: a vendor template built to the [Wi-Fi template requirements](../wifi-explorer/TEMPLATE_REQUIREMENTS.md), enrolled the way its template says.

Start with one pilot cluster or AP whose access switches are already enrolled (section 6).

### 7.1 Create the cluster host

1. **Data collection → Hosts → Create host.** Name it after the cluster (for example `wifi-dc-north`). Put it in a host group whose readers should see this cluster's APs: Wi-Fi Explorer shows an AP to a user only if they can read this host.
2. Add an **SNMP interface** at the cluster's **virtual-controller (AVC) address**, with the cluster's SNMP v2c community or v3 credentials. Do not use a member AP's address: on a member every cluster dataset reports *unsupported* (`not_virtual_controller`) and the page says so.
3. Set **Monitored by** to a proxy that can reach the AVC address (5.4).
4. Add the host tags **`site`** with the same value as the switches the APs plug into (2.5), and **`ne.domain`** with the same value as those switches (2.4).
5. Link **`we_aruba_instant_virtual_controller`** (Wi-Fi Explorer - Aruba Instant Virtual Controller).
6. Set the client macros on the host (or globally, under Administration → General → Macros, if one policy covers every cluster):
   - `{$WE.CLIENT.IDENTIFIERS}`: `partial` (default), `pseudonymised` or `full` (2.8).
   - With `pseudonymised`, also `{$WE.CLIENT.KEY}` as a **Secret text** macro holding a long random value (for example the output of `openssl rand -hex 32`). Keep the same key across clusters and over time so the same client keeps the same pseudonym. Without a key, `pseudonymised` falls back to `partial` rather than storing full identifiers.

### 7.1a Standalone APs with the generic template

1. **Data collection → Hosts → Create host** per AP, named like the AP (Wi-Fi Explorer matches APs to switch ports and floor placements by identity, but people find them by name). Use the same host group rule as 7.1.
2. Add an **SNMP interface** at the AP's own address, with its SNMP v2c community or v3 credentials, and set **Monitored by** to a proxy that can reach it.
3. Add the same **`site`** and **`ne.domain`** tags as the switches it plugs into.
4. Link **`we__generic_access_point`** (Wi-Fi Explorer - Generic Access Point). It also reads the AP's own LLDP, which confirms its uplink (7.2).

In Latest data, `we.device.attempt` should hold `"status":"ok"`. If it holds `"status":"unsupported"` with `not_wifi_ap`, the AP does not expose the IEEE 802.11 MIB: unlink the generic template and use a vendor template for it.

### 7.2 Optional: AP hosts

Two Wi-Fi features need a host per AP, at the AP's own address. Skip this unless you want them.

- **RF neighbours tab** (which other access points each AP hears): link **`we_aruba_instant_access_point`** (Wi-Fi Explorer - Aruba Instant Access Point) to the AP's host, with the same SNMP credentials as the cluster. Name the host like the AP, or give its SNMP interface the AP's address, so Wi-Fi Explorer can tell which AP it observes.
- **Confirmed uplinks** (the AP's own LLDP agreeing with the switch's): every per-AP template also collects the AP's own LLDP, `we_aruba_instant_access_point` on an Aruba Instant AP's host as well as `we__generic_access_point` on a standalone AP (7.1a), so the AP host above gives both. Give it the same `ne.domain` and `site` tags as the switches. Without an AP host, uplinks are still found from the switches' LLDP (shown as *switch only*), which covers most APs.

Give each AP host the same host group as its cluster host, so the same users can read both.

### 7.3 Check collection

Use **Execute now** on the cluster host's `we.raw.*` items, or wait one inventory interval (1h). In **Monitoring → Latest data**, filter the cluster host and the key `we.`:

- The `*.attempt` items (`we.device.attempt`, `we.ap.inventory.attempt`, `we.ap.state.attempt`, `we.radio.inventory.attempt`, `we.radio.state.attempt`, `we.ssid.attempt`, `we.client.attempt`) should hold envelopes with `"status":"ok"`.
- `unsupported` with `not_virtual_controller` means the SNMP interface is a member AP, not the AVC address (7.1).
- `failed` with a timeout means the SNMP timeout (5.2) is too low for the cluster's size, or UDP 161 to the AVC address is blocked from that proxy.
- On AP hosts, `we.rf.neighbour.attempt` should be `ok`.
- The `we.capacity.*` items get their first values within the hour; the Capacity tab fills in as trends accumulate.

### 7.4 Check the page

Open **Monitoring → Wi-Fi Explorer** and pick the cluster's site.

1. **Overview** lists the cluster's APs as up, down or unknown, radios by band and channel utilisation. An AP whose data is stale shows as unknown, never as up.
2. **SSIDs** lists the cluster's SSIDs, with VLAN *Unknown: not declared* until you declare intent (7.5); Aruba Instant does not report an SSID's VLAN over SNMP.
3. Open an AP: its **uplink** names the switch and port it plugs into. *Unresolved* on an AP that is up means no enrolled switch with the same `site` reports it over LLDP; check the access switch is enrolled with the same `site` and `ne.domain` tags and that its LLDP dataset is `ok`.
4. **Clients** shows identifiers in the form your policy chose (2.8).
5. **Log in as an ordinary user** with access to only some host groups and confirm they see only the clusters, APs and switches in those groups.
6. Open the cluster host's **Wi-Fi Explorer** host dashboard (Monitoring → Hosts → *Dashboards*): APs up and down, clients and per-band utilisation fill in as the hourly capacity values arrive.

### 7.5 Configure floors, SSID intent and events (Super admin)

Wi-Fi Explorer compares what it observes with what you declare. The declared part lives in one JSON document in the module's settings, stored in the Zabbix database (so every frontend shares it), and is edited by a Super admin from **Configure** on the Wi-Fi page. The page shows an example document and the AP IDs and background images it can refer to; every problem is listed if a save is refused. Never put a password, PSK or RADIUS secret in it.

1. **Floor plans:** upload each plan under **Administration → General → Images** as type **Background**. In Configure, add a floor per plan (`site`, `building`, `name`, `order`, the image's ID and the floor's width in metres). Then place each AP from the **Floor plans** tab by choosing it and clicking its position on the plan.
2. **SSID intent:** for each SSID and site, the VLAN it should carry, where it is expected (`site`) and on which bands. Without it the **VLAN paths**, **Impact** and **Events** tabs have nothing to check.
3. **Events** (optional): a time window, site and SSID with the AP and client numbers it must support; the **Events** tab checks readiness against them.
4. **Known BSSIDs** (optional): neighbouring networks you recognise, labelled so the RF view names them.

Then check the **VLAN paths** tab: each AP's path from its uplink to the spanning-tree root should be *complete* for the VLANs you declared. *Partial* or *unknown* names where the evidence stops (for example a switch on the path that is not enrolled or not visible to you).

### 7.6 Roll out

Enrol the other clusters the same way, each with its site's `site` tag. Watch the proxies' SNMP poller and preprocessing busy rates after each one, as for switches.

## 8. Upgrade and rollback

Upgrade the frontend package and the template files together: a new frontend expects the item keys and schema versions of the matching templates. Do it on the test server first.

### 8.1 Upgrade

1. Back up as in section 2, and export the templates in the `Templates/Network Explorer` and `Templates/Wi-Fi Explorer` groups (Data collection → Templates, filter by group, select them, Export). Copy the Wi-Fi configuration document from **Configure** into a file too; it holds your floors, AP positions, SSID intent and events.
2. **Frontend.**
   - Copy into the mounted modules directory (3.1): rerun the 3.1 commands with the new `RELEASE`, then `docker compose up -d --force-recreate <web service>`.
   - Per-module bind mounts (3.2): unpack the new version into `/opt/zabbix/network-explorer/<new>/`, `chmod -R a+rX` it, repoint the `current` symlink and run `docker compose up -d --force-recreate zabbix-web`.
   - Derived image: build the new tag and redeploy the web container with it.
   - Package install: replace the seven directories in place.
3. **Re-scan modules** (Administration → General → Modules → Scan directory) if the release notes add or rename a module. Module IDs do not change between releases, so a plain upgrade normally needs no re-scan and the modules stay enabled. Make sure all seven directories are in place before any scan: a scan removes modules whose directory is missing, and removing Wi-Fi Explorer's entry discards its configuration document.
4. **Templates.** Import each new template file you use (`ne_*.yaml` for switches, `we_*.yaml` for access points) with *Update existing* ticked. Leave *Delete missing* unticked unless the release notes tell you to remove retired items; deleting items deletes their history.
5. Ask users to reload the page (Ctrl+F5) so browsers fetch the new widget JavaScript and CSS.
6. Repeat the checks in 6.2 and 6.3 on the pilot switches, and 7.3 and 7.4 on the pilot cluster.

Upgrading from 1.4.0 or earlier also needs 8.3, from 2.0.0 or earlier 8.4, and from 2.2.0 or earlier 8.5. To move a switch from the Generic Switch to a vendor template, at any release, see 8.6.

Proxies need nothing for a frontend or template upgrade; they receive the new item configuration automatically. When you upgrade Zabbix itself (for example 7.4 to a later release), upgrade server, proxies and frontend as Zabbix documents, then import the templates from the matching `templates/native/<version>/` directory if one is provided.

### 8.2 Rollback

- **Frontend:** rerun the 3.1 commands with the previous `RELEASE`, or repoint `current` to the previous version (3.2), and recreate the container; or redeploy the previous image tag (3.3). The module stays enabled because its ID does not change.
- **Templates:** re-import the previous release's YAML files with *Update existing*. Do not unlink with *Unlink and clear* as a rollback step: that deletes the items and their history. A re-import without *Delete missing* keeps the items the newer release added; from 2.3.0 back to 2.2.0 that is the PoE dataset on the switch templates, which 2.3.0's frontend ignores, so it can stay, and the LLDP items on the per-AP Wi-Fi templates, which keep collecting and which 2.2.0 reads the same way. The re-import also recreates `Network Explorer - LLDP for access points`; do not link it to those AP hosts again, since their per-AP template already owns its keys. Tick *Delete missing* only if you want those items and their history gone.
- **Wi-Fi configuration:** it stays in the database across a rollback. If the older release refuses it, the page says the stored configuration does not validate; paste the copy you saved in 8.1 into Configure.
- **Removing everything:** unlink the switch, access-point LLDP and Wi-Fi templates from hosts (*Unlink and clear* if you want the data gone), disable the seven modules in Administration → General → Modules (Wi-Fi Explorer first, Network Explorer last), then remove the module files or mounts. Removing the files does not delete users' dashboards; widgets on them show as unavailable until removed.

### 8.3 From 1.4.0 or earlier: switch hosts to the flat templates

Up to 1.4.0, switches were linked to `Network Explorer - Profile - Generic standard MIB`, which linked seven per-dataset templates (`Base`, `Interfaces`, `Port Capability`, `LLDP`, `VLAN`, `STP`, `LAG`). From 2.0.0 each device type has one self-contained template instead. Item keys are unchanged, so hosts keep their items and history if you swap the templates as below. Verified on a Zabbix 7.4.3 lab: every host kept the same item IDs and kept collecting, and history from before the swap was still there.

1. Import the new `ne__generic_switch.yaml` (8.1 step 4). It adds `ne__generic_switch` beside the old templates; nothing changes on hosts yet.
2. Swap each switch's template. Either:
   - **One host:** open it, remove `Network Explorer - Profile - Generic standard MIB` from **Templates** with its ×, add `ne__generic_switch`, and click **Update**, all in the one save; or
   - **Many hosts:** select them in Data collection → Hosts → **Mass update** → Templates: first **Unlink** `Network Explorer - Profile - Generic standard MIB` with **Clear when unlinking unticked**, then a second mass update to **Link** `ne__generic_switch`. Do not use **Replace**: it also unlinks every other template on those hosts.

   Never tick *Clear when unlinking* and never use *Unlink and clear*: that deletes the items and their history. Unlinked items stay on the host until the new template adopts them by key.
3. On Wi-Fi access-point hosts linked to `Network Explorer - LLDP`, unlink it the same way, without clearing. Then import the per-AP Wi-Fi template each AP uses (`we__generic_access_point.yaml` or `we_aruba_instant_access_point.yaml`) and link it if it is not linked already: it carries the LLDP items and adopts them by key (8.5).
4. When no host is linked to them any more (each template's **Linked hosts** is empty), delete the eight old templates in Data collection → Templates with **Delete**, not *Delete and clear*.

### 8.4 From 2.0.0 or earlier: renamed switch template, no separate dashboard template

In 2.0.0 the switch template was called `Network Explorer - Generic standard MIB`, and the switch host dashboard was a separate template, `Network Explorer - Host dashboard` (`network_explorer_dashboard.yaml`). From 2.1.0 the switch template (`Network Explorer - Generic Switch`, now `ne__generic_switch`) carries the dashboard itself, so a switch still linked to the old dashboard template shows two *Network Explorer* dashboards.

1. Import the new `ne__generic_switch.yaml` with **Dashboards** ticked (8.1 step 4). It renames `Network Explorer - Generic standard MIB` to `ne__generic_switch` in place: same template, same host links, items and history, so there is nothing to relink.
2. In Data collection → Templates, select `Network Explorer - Host dashboard` and click **Delete**. It holds no items, so nothing is lost; deleting it unlinks it from every host and removes its dashboard, leaving the one from the Generic template.

### 8.5 From 2.2.0 or earlier: one file per template, new template names, LLDP in the per-AP templates

Up to 2.2.0 the templates came in two files, `network_explorer_snmp.yaml` (the switch template and the access-point LLDP template) and `wifi_explorer_snmp.yaml` (the Wi-Fi templates). Each template now has its own file named after it, and a new name:

| Up to 2.2.0 | Now | Shown as |
|---|---|---|
| `Network Explorer - Generic Switch` | `ne__generic_switch` | Network Explorer - Generic Switch |
| `Network Explorer - LLDP for access points` | Retired: its items are part of `we__generic_access_point` and `we_aruba_instant_access_point` | |
| `Wi-Fi Explorer - Generic AP` | `we__generic_access_point` | Wi-Fi Explorer - Generic Access Point |
| `Wi-Fi Explorer - Aruba Instant VC by SNMP` | `we_aruba_instant_virtual_controller` | Wi-Fi Explorer - Aruba Instant Virtual Controller |
| `Wi-Fi Explorer - Aruba Instant AP by SNMP` | `we_aruba_instant_access_point` | Wi-Fi Explorer - Aruba Instant Access Point |

Every other template keeps its UUIDs, so an import renames it in place. The access-point LLDP template is retired: its LLDP items are now part of the two per-AP templates, so an AP's host needs one template and every AP host confirms its own uplink. An AP host that was not linked to it gains the LLDP items and starts collecting the AP's own LLDP. Verified on Zabbix 7.0.20 and 7.4.3 labs: each template kept its ID, took its new name and group, and hosts linked to it stayed linked with the same item IDs and host dashboard; on AP hosts linked to the LLDP template, the steps below kept every item ID, and the per-AP template took over the LLDP items.

1. **Before importing,** unlink `Network Explorer - LLDP for access points` from every host its **Linked hosts** lists, without clearing: open the host, remove it from **Templates** with its ×, and click **Update**; or Mass update → Templates → **Unlink** with **Clear when unlinking** unticked. Its items stay on the host as plain items. If you import first, the import of `we__generic_access_point.yaml` or `we_aruba_instant_access_point.yaml` fails with *Cannot inherit item with key "ne.raw.lldp" ... already inherited from template "Network Explorer - LLDP for access points"* and changes nothing; unlink, then import again.
2. Import the new file of each template you use (8.1 step 4), with **Dashboards** ticked. Each renames its template in place: same template, host links, items, history and host dashboard, so there is nothing to relink. The per-AP templates adopt the plain LLDP items by key, so those keep their history too.
3. Delete `Network Explorer - LLDP for access points` (Data collection → Templates → **Delete**, not *Delete and clear*). It is linked to nothing any more, so nothing on a host changes.
4. Update anything that looks these templates up by name, such as API scripts or your own runbooks. Host links refer to the template itself, so they follow the rename.
5. Do not import `network_explorer_snmp.yaml` or `wifi_explorer_snmp.yaml` from an earlier release again unless you are rolling back (8.2): they rename the templates back.

### 8.6 Moving a switch from the Generic Switch to a vendor template

A vendor template holds every item of the Generic Switch under the same keys, plus its own. Swap the templates without clearing, and the vendor template adopts the host's items and discovery rules by key, so they keep their history. Verified on Zabbix 7.0.20 and 7.4.3 labs for each vendor template: every item and discovery rule of a host on `ne__generic_switch` kept its ID after the swap, and the vendor template added its own. The lab hosts had no discovered ports; the rules that discover them keep their IDs.

1. Import the vendor template's file (section 4), and check the [qualification matrix](../qualification/MATRIX.md) lists the switch's model and firmware.
2. Swap the template:
   - **One host:** open it, remove `ne__generic_switch` from **Templates** with its ×, add the vendor template, and click **Update**, all in the one save; or
   - **Many hosts:** Data collection → Hosts → select them → **Mass update** → Templates: first **Unlink** `ne__generic_switch` with **Clear when unlinking** unticked, then a second mass update to **Link** the vendor template. Do not use **Replace**: it also unlinks every other template on those hosts.

   Never tick *Clear when unlinking* and never use *Unlink and clear*: that deletes the items and their history.
3. Delete the one item the swap leaves behind. The Generic Switch reads PoE through `ne.raw.poe` (*Raw SNMP walk: poe*); the Cisco, CBS220 and Dell N-Series templates read it through their own walk, so `ne.raw.poe` stays on the host as a plain item with nothing depending on it, and would keep polling. In the host's **Items**, filter the key `ne.raw.poe`, tick the item that has no template prefix, and click **Delete**. The Dell X-Series template keeps `ne.raw.poe`, so nothing is left behind. The walk stores no history, so nothing is lost.
4. The vendor template's disabled components (Port Capability, and Hardware Health on the CBS220) are disabled on the host too after the swap; enable them on a host whose firmware supports them.

To move back, swap the other way in the same manner; the vendor template's own items (hardware health, its PoE walk) then stay behind as plain items, which you delete the same way, losing their history. The lab checked the forward move only.

## 9. Optional: the Python collector on a proxy

The collector exists only for switches that native SNMP items cannot reach; it has no Wi-Fi datasets. It is a frozen schema 1.0 fallback: it does not collect VLAN, STP, port capability or static LAG data, and 2.3.0 ships no template that maps its output to the `ne.*` keys. **Skip this section unless you have such a device.** Never link a collector-fed producer and the native switch template to the same host.

If you do need it, add it to that proxy's Dockerfile. The example below targets the official Alpine proxy image; adjust the package manager for an Ubuntu or RHEL base. Python 3.10 or newer is required.

```dockerfile
FROM zabbix/zabbix-proxy-mysql:alpine-7.4.3
USER root
RUN apk add --no-cache python3
COPY network-explorer-collector-2.3.0.tar /tmp/
RUN mkdir -p /opt/network-explorer/src \
 && tar -xf /tmp/network-explorer-collector-2.3.0.tar -C /opt/network-explorer/src \
 && python3 -m venv /opt/network-explorer/venv \
 && /opt/network-explorer/venv/bin/pip install --no-cache-dir --require-hashes \
      -r /opt/network-explorer/src/collector/requirements.lock \
 && /opt/network-explorer/venv/bin/pip install --no-cache-dir --no-deps /opt/network-explorer/src/collector \
 && install -m 0755 /opt/network-explorer/src/collector/packaging/network-explorer-collect \
      /opt/network-explorer/network-explorer-collect \
 && rm /tmp/network-explorer-collector-2.3.0.tar
# Return to the image's original user (check with: docker image inspect -f '{{.Config.User}}' <base image>).
USER 1997
```

Notes for a customised proxy image:

- The collector pins `cryptography==50.0.1`; PySNMP's AES privacy needs it. If your image installs another `cryptography` system-wide, that does not matter: the collector uses its own virtual environment. Keep it separate from any Python libraries your other external scripts use.
- `requirements.lock` is hash-locked. Building the collector package itself fetches `setuptools` from PyPI; build where PyPI is reachable, or from a verified offline wheelhouse.
- The official images declare the external scripts directory (`/usr/lib/zabbix/externalscripts`) as a volume; files written there during the build can be hidden by the volume at run time. Check with `docker image inspect -f '{{json .Config.Volumes}}' <image>`. Either copy the launcher into the externalscripts volume/bind mount you already use, or set `ExternalScripts` to a directory that is not a volume.
- The launcher hard-codes `/opt/network-explorer/venv` and `/etc/network-explorer/devices.json`. Mount the device file read-only from the host, owned by the proxy's user and mode `0400` or `0600`; the collector refuses files with group or world permissions and refuses symlinks:

  ```sh
  sudo install -o 1997 -g 1995 -m 0400 devices.json /srv/zabbix-proxy/network-explorer/devices.json
  ```

  ```yaml
  volumes:
    - /srv/zabbix-proxy/network-explorer/devices.json:/etc/network-explorer/devices.json:ro
  ```

  The uid/gid above are those of the `zabbix` user in the official images; confirm with `docker run --rm --entrypoint id <image>`.
- Test inside the running proxy container:

  ```sh
  docker exec -it <proxy> /opt/network-explorer/network-explorer-collect switch-example interfaces
  ```

  It must print one JSON envelope. Credentials never go in item keys or command arguments. See the [collector README](../../collector/README.md) for the configuration format and SNMPv3 options.

## 10. Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| Web container fails to start: `error mounting … to rootfs at "/usr/share/zabbix/modules/<name>" … make mountpoint … read-only file system` | Per-module mounts (3.2) added to a compose file that already mounts the whole `modules/` directory read-only (zabbix-docker does) | Remove the seven per-module mounts and copy the directories into `${DATA_DIRECTORY}/usr/share/zabbix/modules/` instead (3.1). |
| *Scan directory* says "No new modules discovered" although `ls ${DATA_DIRECTORY}/usr/share/zabbix/modules/*/manifest.json` on the host lists seven files | Leftover per-module mounts (3.2) in the compose file, or in an override file, cover the copied directories with other host paths, often empty directories Docker created for a source that does not exist | Remove the per-module mounts (check with `docker compose config \| grep usr/share/zabbix/modules`: only the whole-directory line should remain), recreate the container, and check inside it: `docker exec <web container> ls /usr/share/zabbix/modules/networkexplorer/manifest.json`. |
| Modules not listed after *Scan directory* | Files not at `<frontend root>/modules/<name>/manifest.json` (for example unpacked under a sub-folder such as `modules/network-explorer/`), or not readable by the web user | `docker exec <web> ls -l /usr/share/zabbix/modules/*/manifest.json` must list seven files; fix paths or `chmod -R a+rX`. With per-module mounts, check the compose file mounts all seven directories and the host paths exist (a missing host path is mounted as an empty directory). |
| Widgets or the Wi-Fi page say Network Explorer is needed | `Network Explorer` module disabled or its directory missing | Enable it in Administration → General → Modules; mount or copy `networkexplorer`. |
| Scan said the modules were added, but there is no menu entry for anyone | Modules registered but still *Disabled* | Enable them (3.4 step 3); a scan never enables a module. |
| No *Network Explorer* or *Wi-Fi Explorer* menu entry for a user | Role lacks *Monitoring → Hosts*, or the modules under *Access to modules* | Edit the role in Users → User roles. |
| No *Configure* link on the Wi-Fi page | User is not a Super admin | Expected; ask a Super admin. |
| Module works on one frontend but errors on another | Frontends have different module files | Deploy the same image tag or mounts on every frontend. |
| Widgets look old after an upgrade | Browser cache | Ctrl+F5; recreate the web container if the bind-mounted `current` link changed. |
| `*.attempt` shows `failed` with a timeout | SNMP timeout too low for a bulk walk, or UDP 161 filtered from that proxy | Raise the proxy's SNMP agent timeout (5.2); test with `snmpwalk` from the proxy's network. |
| SNMP interface unavailable (red) | Credentials, SNMP version or ACL on the switch | Fix as for any SNMP host. Last good snapshots are kept and stale triggers fire. |
| A dataset shows `unsupported` | The switch does not publish that MIB | Expected; the other datasets still work. VLAN needs Q-BRIDGE-MIB, STP needs BRIDGE-MIB, port placement needs ENTITY-MIB. |
| Ports shown but unplaced, no stack tabs | No ENTITY-MIB port entities | Expected for that device; ports are listed rather than guessed. |
| Neighbours listed but not clickable | Neighbour not monitored, different or missing `ne.domain`, or the user cannot see it | Monitor the neighbour with the same `ne.domain` tag; check the user's host groups. |
| Remote neighbour descriptions missing | `{$NE.LLDP.REDACT_REMOTE}=1` on that host | Intended if set deliberately; set it to `0` only where every reader may see neighbour identities. |
| Data quality reports an invalid dataset on a large stack | Text value truncated by the database (5.3) | Check the item's latest value length; report it with the port count and database type. |
| `Cannot link template … because its parent template "Network Explorer - Interfaces" would be linked twice` | 1.4.0 or earlier templates: the profile and the templates it already links were all selected on one host | Upgrade to the flat templates (8.3), or with 1.4.0 link only `Network Explorer - Profile - Generic standard MIB`. |
| Proxy queue grows after enrolment | SNMP pollers or preprocessing saturated | Raise `StartSNMPPollers` / preprocessing workers, or lengthen the `{$NE.*.INTERVAL}` / `{$WE.*.INTERVAL}` macros. |
| Wi-Fi page: no Wi-Fi data source visible | No cluster host linked, or the user cannot read it | Link the VC template (7.1); check the user's host groups. |
| Wi-Fi datasets `unsupported` with `not_virtual_controller` | SNMP interface points at a member AP | Change it to the cluster's AVC address. |
| Wi-Fi datasets `failed` with a timeout | Large cluster walk, or UDP 161 to the AVC address filtered | Raise the proxy's SNMP agent timeout (5.2); test with `snmpwalk` to the AVC address from the proxy's network. |
| AP uplink *unresolved* | Access switch not enrolled, different `site` or `ne.domain` tag, its LLDP dataset not `ok`, or not visible to the user | Enrol the switch with the cluster's `site` and `ne.domain`; check its `ne.lldp.attempt`. |
| SSID VLAN shows *Unknown: not declared*; VLAN paths and impact empty | No SSID intent | Expected until a Super admin declares it in Configure (7.5). |
| "The stored Wi-Fi configuration does not validate" | Configuration document refused by this release | A Super admin corrects it in Configure, or pastes the saved copy (8.1). |
| Client identifiers still partial after choosing `pseudonymised` | `{$WE.CLIENT.KEY}` empty or not visible on the host | Set it as a secret macro on the host or globally (7.1). |

If something here does not match what you see on your installation, note the Zabbix version, image tag and the item's latest value and raise it; the lab evidence covers simulated switches and simulated generic-AP and Aruba Instant walks only, not real hardware. Neither the generic AP template nor Aruba Instant is yet qualified on real captures ([Wi-Fi qualification matrix](../qualification/WIFI_MATRIX.md)).
