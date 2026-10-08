# Deployment guide: Docker test server and multi-proxy production

This guide installs Network Explorer 1.2.0 on two kinds of estate:

- **Test:** one Docker host running the Zabbix server, frontend and one or more proxies as containers.
- **Production:** one frontend server and several proxies spread across data centres, each proxy built from a customised Dockerfile.

It assumes Zabbix **7.4** and the official `zabbix/*` images, which is what the lab verifies (7.4.3, see [runtime evidence](../../lab/VERIFICATION.md)). 7.0 and 7.2 work the same way; pick the matching template directory. Where your images or paths differ, the step says what to check. [INSTALL.md](INSTALL.md) is the short reference; this guide is the step-by-step version.

## 1. What goes where

The most important fact first: **with the native SNMP templates, nothing has to be installed on the proxies or the Zabbix server.**

| Component | Installed on | What it is |
|---|---|---|
| Frontend package (6 module directories) | Every Zabbix frontend (web) container or server | PHP module and five dashboard widgets. Reads item values through the logged-in user's permissions. |
| Native SNMP templates | Imported once, through the frontend, into the Zabbix database | Standard-MIB `walk[]` SNMP items with JavaScript preprocessing. They run on whichever proxy monitors the host, using the proxy's built-in SNMP poller and JavaScript engine. |
| Host dashboard template (optional) | Imported once, after the modules are enabled | An inherited host dashboard built from the five widgets. |
| Python collector (optional fallback) | Only proxies that must reach devices native SNMP items can't | Frozen schema 1.0 fallback. **Not needed for normal operation.** See section 8. |

So the custom Python libraries and OpenSSL builds in your proxy Dockerfiles are not required by Network Explorer. The proxies need only:

- SNMP (UDP 161) reachability to the switches they monitor;
- the switch's SNMP credentials on the host's SNMP interface in Zabbix, as for any SNMP host;
- an SNMP timeout long enough for a bulk walk (section 5.2).

Nothing in the module calls a proxy, runs a command or opens a network connection from a browser request.

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

   You get `network-explorer-frontend-1.2.0.tar` (directories under `frontend/`), `network-explorer-templates-1.2.0.tar` (under `templates/native/`), and the optional collector package. Copy only the archives to your servers; nothing else from the checkout is needed.
4. **Decide the `ne.domain` value(s).** Every switch host needs exactly one host tag `ne.domain` (for example `ne.domain=corp`). Peer matching only happens between hosts with the same value. Use one value across all five data centres if they are one routed/LLDP-connected network; use different values only for networks that must never be matched to each other (for example separate customers with overlapping IPs). The tag never grants visibility.
5. **Check host names.** Technical and visible host names must be unique across the whole installation; LLDP peer matching relies on that.

## 3. Install the frontend modules

The six directories must sit side by side in the frontend's `modules/` directory, with their names unchanged:

```
modules/networkexplorer
modules/neportpanel
modules/netopology
modules/neinterfacedetail
modules/nedataquality
modules/nefindings
```

In the official `zabbix/zabbix-web-*` images the frontend root is `/usr/share/zabbix`, so the target is `/usr/share/zabbix/modules/` (verified on 7.0.20, 7.2.7 and 7.4.3). On a package-installed frontend, find the directory that contains `zabbix.php` and use its `modules/` subdirectory; do not assume the path.

Choose one of the two methods below. Bind mounts suit the test server; a derived image suits production because the version is baked into an image tag you can roll back.

### 3.1 Option A: bind-mount the module directories (test server)

Unpack the package into a versioned directory on the Docker host:

```sh
sudo mkdir -p /opt/zabbix/network-explorer/1.2.0
sudo tar -xf network-explorer-frontend-1.2.0.tar -C /opt/zabbix/network-explorer/1.2.0
sudo ln -sfn /opt/zabbix/network-explorer/1.2.0 /opt/zabbix/network-explorer/current
sudo chmod -R a+rX /opt/zabbix/network-explorer/1.2.0
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
```

Mount the six directories individually, not the whole `modules/` directory: a single mount over `modules/` hides any other modules or widgets you have installed there.

Apply it with `docker compose up -d zabbix-web`. Docker resolves the `current` symlink when the container starts, so after switching versions you must recreate the container (section 7).

### 3.2 Option B: build a frontend image with the modules inside (production)

```dockerfile
# Dockerfile.web
FROM zabbix/zabbix-web-nginx-pgsql:alpine-7.4.3
USER root
# Unpacked from network-explorer-frontend-1.2.0.tar next to this Dockerfile.
COPY frontend/ /usr/share/zabbix/modules/
RUN chmod -R a+rX /usr/share/zabbix/modules
# Return to the base image's user (check with: docker image inspect -f '{{.Config.User}}' <base image>).
USER 1997
```

```sh
mkdir build && tar -xf network-explorer-frontend-1.2.0.tar -C build
cp Dockerfile.web build/
docker build -t registry.example/zabbix-web-ne:7.4.3-ne1.2.0 -f build/Dockerfile.web build
```

Use the `-mysql` web image instead if your database is MySQL/MariaDB. Tag the image with both the Zabbix and the Network Explorer version so a rollback is a tag change. If you already maintain a customised web image, add the `COPY` and `chmod` lines to it instead.

### 3.3 Register and enable the modules

Module state is stored in the Zabbix database, so this is done once per installation, not per container.

1. Log in as a Super admin and open **Administration → General → Modules**.
2. Click **Scan directory**. Six entries appear: *Network Explorer* and five *Network Explorer: …* widgets.
3. Enable **Network Explorer** first, then the five widgets. The widgets show an installation message while the base module is disabled; that is expected.
4. Check that **Monitoring → Network Explorer** now appears in the menu. That page is the network-wide view; no global dashboard has to be created or imported. Dashboard recipes in `dashboards/` are optional examples.

If you run more than one frontend against the same database, every frontend must have identical module files; the database tells all of them the modules are enabled.

### 3.4 User roles

- The **Network Explorer** menu entry is shown only to roles with access to *Monitoring → Hosts*.
- In **Users → User roles**, each role that should use it must allow the six modules under *Access to modules*. Roles with *Default access to new modules* enabled get them automatically; check restricted roles explicitly.
- What each user sees is limited by their host group permissions, exactly as elsewhere in Zabbix. No API token or privileged account is used.

## 4. Import the templates

Unpack `network-explorer-templates-1.2.0.tar` on your workstation and use the files for your version, here `templates/native/7.4/`.

1. **Data collection → Templates → Import**, choose `network_explorer_snmp.yaml`. Leave the default rules (create new, update existing; do not tick *Delete missing* on a first import). This creates the template group `Templates/Network Explorer` and eight templates: `Base`, `Interfaces`, `Port Capability`, `LLDP`, `VLAN`, `STP`, `LAG` and the profile `Network Explorer - Profile - Generic standard MIB`.
2. Only after the modules are enabled (3.3): import `network_explorer_dashboard.yaml`. It creates `Network Explorer - Host dashboard`, which holds a host dashboard (Ports, Topology, Findings) and no items.

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

Each Network Explorer dataset is one bulk `walk[]` over several tables, which on a large switch takes longer than a single SNMP get. The templates do not set per-item timeouts, so the proxy's SNMP timeout applies.

- In **Administration → Proxies → (proxy) → Timeouts**, set **SNMP agent** to at least **10s** for proxies that poll large switches or stacks, or set it globally in **Administration → General → Timeouts** if the proxies inherit the global values. Raise it if the `*.attempt` items report timeouts (section 6).
- In Docker, you can also set the proxy's base `Timeout` with the `ZBX_TIMEOUT` environment variable; the per-proxy frontend setting takes precedence for item types it overrides.
- If proxies already poll many SNMP hosts, watch the SNMP poller busy rate (`zabbix[process,snmp poller,avg,busy]` on the proxy's self-monitoring) after enrolment and raise `StartSNMPPollers` (`ZBX_STARTSNMPPOLLERS` in the official images; check your image's environment variable list) if it stays high.

### 5.3 Load and buffer sizing

Per switch, the profile polls seven datasets at the template defaults: interface state every 1m, STP 2m, LLDP and LAG 5m, VLAN 10m, port capability 15m, interface inventory and device identity 1h. Snapshots are stored as text values of about 350–400 bytes per port each (measured on the lab's simulated 27- and 48-port switches), and per-port discovered items add roughly 3–5 items per port (151 and 235 items on those two lab hosts).

For a proxy with many switches, check that `ProxyOfflineBuffer` and the proxy database have room for the extra text values during a link outage to the server. Intervals are macros (`{$NE.IF.STATE.INTERVAL}`, `{$NE.LLDP.INTERVAL}` and so on) and can be lengthened per host or per template.

**Large stacks and text size:** a single snapshot grows with the port count. At about 370 bytes per port, the interface snapshots of a stack with more than roughly 170 ports approach 64 KB. Zabbix text history is limited in size on some database backends (see "Item value types" in the Zabbix documentation for your version and database). If a value is truncated it is no longer valid JSON; Network Explorer then reports the dataset as invalid on the Data Quality widget rather than drawing wrong ports. This limit is an estimate from lab data and has not been tested against a real large stack; check the first large stack you enrol (section 6).

### 5.4 Proxy groups

If you use proxy groups across data centres, Zabbix can move a host between proxies in the group. Every proxy in the group must then be able to reach that host's SNMP address with the same credentials. If a data centre's switches are reachable only from its local proxy, assign those hosts to that proxy directly rather than to a group.

## 6. Enrol switches and verify

### 6.1 Enrol a pilot switch first

Pick one switch per data centre, ideally one with LLDP neighbours that are also monitored.

1. Make sure the host has an **SNMP interface** (v2c or v3) with working credentials, and is **Monitored by** the right proxy (or proxy group).
2. Add the host tag **`ne.domain`** with your chosen value (2.4).
3. Link **`Network Explorer - Profile - Generic standard MIB`** only. It links the seven dataset templates itself; linking them individually as well is unnecessary.
4. Optionally link **`Network Explorer - Host dashboard`** beside it.

The Network Explorer keys all start with `ne.`, so the templates coexist with existing SNMP templates such as the stock network templates. The switch is then walked by both, so expect more SNMP load on the device.

### 6.2 Check collection (allow one inventory interval)

Interface inventory is polled hourly, so either wait for it or use **Execute now** on the host's `ne.raw.*` items (Data collection → Hosts → Items, filter key `ne.raw`; tick them and click *Execute now*).

In **Monitoring → Latest data**, filter the host and the key `ne.`:

- The `*.attempt` items (`ne.device.attempt`, `ne.interfaces.attempt`, `ne.interfaces.inventory.attempt`, `ne.lldp.attempt`, …) should hold envelopes with `"status":"ok"`. `unsupported` means the switch does not publish that MIB (for example no Q-BRIDGE-MIB means no VLAN overlay); the other datasets keep working.
- `failed` with a timeout means the SNMP timeout (5.2) is too low or UDP 161 is blocked from that proxy.
- Interface discovery should have created per-port items with no items left *Not supported*.
- If the SNMP interface turns red (unavailable), it is a credentials or reachability problem, not a Network Explorer one.

### 6.3 Check the frontend

1. **Monitoring → Network Explorer**. With no selection it draws every switch you can read as a Layer 2 topology. Choose the pilot host as *Seed device*, or its *Site* if you tag hosts with `site=<name>`. Click the switch to see its interfaces, and click a link to see both ends. If the switches run spanning tree, the root bridge is marked ★.
2. Open the host dashboard (from *Open host dashboard* on the Explorer page, if linked) or add the **Port panel**, **Physical topology** and **Data quality** widgets to a dashboard. Check:
   - ports appear with correct state and speed, and stacks show one tab per member (this needs ENTITY-MIB; switches without it show ports unplaced rather than guessed);
   - an LLDP neighbour that is also monitored, with the same `ne.domain`, can be clicked through to its host;
   - the Data quality widget shows no invalid or stale datasets.
3. Set the management subnet(s) in the Explorer page's *Management subnet* field (or the Physical topology widget's field, or `management_cidr=` on the JSON route) (see the [module README](../../frontend/networkexplorer/README.md)); physically connected devices outside it stay visible and are highlighted.
4. **Log in as an ordinary user** with access to only some host groups and confirm they see only those hosts, and that neighbours they may not see are shown as unresolved placeholders without names.

A quick machine check of the same data, as a logged-in user: `zabbix.php?action=networkexplorer.data&hostid=<id>` returns the permitted current state as JSON.

### 6.4 Roll out

When the pilot switches in every data centre look right, enrol the rest in batches (a host group or a host prototype/auto-registration action that adds the `ne.domain` tag and links the profile). Watch the proxies' SNMP poller and preprocessing busy rates after each batch.

Ports to alert on, and expected speeds, are set with per-interface macros:

- `{$NE.IF.MONITOR:"Gi1/0/24"}=1` raises a trigger when that port goes down.
- `{$NE.IF.EXPECTED_SPEED:"Gi1/0/23"}=1000000000` flags that port when it runs below 1 Gbit/s for longer than `{$NE.IF.SPEED.DEGRADED_FOR}` (10m). With `0`, the expected speed is derived from what both ends advertise.

## 7. Upgrade and rollback

Upgrade the frontend package and templates together: a new frontend expects the item keys and schema version of the matching templates. Do it on the test server first.

### 7.1 Upgrade

1. Back up as in section 2, and export the `Network Explorer -` templates (Data collection → Templates, select them, Export).
2. **Frontend.**
   - Bind mounts: unpack the new version into `/opt/zabbix/network-explorer/<new>/`, `chmod -R a+rX` it, repoint the `current` symlink and run `docker compose up -d --force-recreate zabbix-web`.
   - Derived image: build the new tag and redeploy the web container with it.
   - Package install: replace the six directories in place.
3. **Re-scan modules** (Administration → General → Modules → Scan directory) if the release notes add or rename a module. Module IDs are stable within 1.x, so a plain upgrade normally needs no re-scan and the modules stay enabled.
4. **Templates.** Import the new `network_explorer_snmp.yaml` with *Update existing* ticked. Leave *Delete missing* unticked unless the release notes tell you to remove retired items; deleting items deletes their history.
5. Ask users to reload the page (Ctrl+F5) so browsers fetch the new widget JavaScript and CSS.
6. Repeat the checks in 6.2 and 6.3 on the pilot switches.

Proxies need nothing for a frontend or template upgrade; they receive the new item configuration automatically. When you upgrade Zabbix itself (for example 7.4 to a later release), upgrade server, proxies and frontend as Zabbix documents, then import the templates from the matching `templates/native/<version>/` directory if one is provided.

### 7.2 Rollback

- **Frontend:** repoint `current` to the previous version and recreate the container, or redeploy the previous image tag. The module stays enabled because its ID does not change.
- **Templates:** re-import the previous release's YAML with *Update existing*. Do not unlink with *Unlink and clear* as a rollback step: that deletes the items and their history.
- **Removing Network Explorer entirely:** unlink the profile and dashboard templates from hosts (*Unlink and clear* if you want the data gone), disable the six modules in Administration → General → Modules, then remove the module files or mounts. Removing the files does not delete users' dashboards; widgets on them show as unavailable until removed.

## 8. Optional: the Python collector on a proxy

The collector exists only for devices that native SNMP items cannot reach. It is a frozen schema 1.0 fallback: it does not collect VLAN, STP, port capability or static LAG data, and 1.2.0 ships no template that maps its output to the `ne.*` keys. **Skip this section unless you have such a device.** Never link a collector-fed producer and the native profile to the same host.

If you do need it, add it to that proxy's Dockerfile. The example below targets the official Alpine proxy image; adjust the package manager for an Ubuntu or RHEL base. Python 3.10 or newer is required.

```dockerfile
FROM zabbix/zabbix-proxy-mysql:alpine-7.4.3
USER root
RUN apk add --no-cache python3
COPY network-explorer-collector-1.2.0.tar /tmp/
RUN mkdir -p /opt/network-explorer/src \
 && tar -xf /tmp/network-explorer-collector-1.2.0.tar -C /opt/network-explorer/src \
 && python3 -m venv /opt/network-explorer/venv \
 && /opt/network-explorer/venv/bin/pip install --no-cache-dir --require-hashes \
      -r /opt/network-explorer/src/collector/requirements.lock \
 && /opt/network-explorer/venv/bin/pip install --no-cache-dir --no-deps /opt/network-explorer/src/collector \
 && install -m 0755 /opt/network-explorer/src/collector/packaging/network-explorer-collect \
      /opt/network-explorer/network-explorer-collect \
 && rm /tmp/network-explorer-collector-1.2.0.tar
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

## 9. Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| Modules not listed after *Scan directory* | Files not at `<frontend root>/modules/<name>/manifest.json`, or not readable by the web user | `docker exec <web> ls -l /usr/share/zabbix/modules/*/manifest.json`; fix paths or `chmod -R a+rX`. |
| Widgets say the base module is required | `Network Explorer` module disabled | Enable it in Administration → General → Modules. |
| No *Network Explorer* menu entry for a user | Role lacks *Monitoring → Hosts*, or the modules under *Access to modules* | Edit the role in Users → User roles. |
| Module works on one frontend but errors on another | Frontends have different module files | Deploy the same image tag or mounts on every frontend. |
| Widgets look old after an upgrade | Browser cache | Ctrl+F5; recreate the web container if the bind-mounted `current` link changed. |
| `*.attempt` shows `failed` with a timeout | SNMP timeout too low for a bulk walk, or UDP 161 filtered from that proxy | Raise the proxy's SNMP agent timeout (5.2); test with `snmpwalk` from the proxy's network. |
| SNMP interface unavailable (red) | Credentials, SNMP version or ACL on the switch | Fix as for any SNMP host. Last good snapshots are kept and stale triggers fire. |
| A dataset shows `unsupported` | The switch does not publish that MIB | Expected; the other datasets still work. VLAN needs Q-BRIDGE-MIB, STP needs BRIDGE-MIB, port placement needs ENTITY-MIB. |
| Ports shown but unplaced, no stack tabs | No ENTITY-MIB port entities | Expected for that device; ports are listed rather than guessed. |
| Neighbours listed but not clickable | Neighbour not monitored, different or missing `ne.domain`, or the user cannot see it | Monitor the neighbour with the same `ne.domain` tag; check the user's host groups. |
| Remote neighbour descriptions missing | `{$NE.LLDP.REDACT_REMOTE}=1` on that host | Intended if set deliberately; set it to `0` only where every reader may see neighbour identities. |
| Data quality reports an invalid dataset on a large stack | Text value truncated by the database (5.3) | Check the item's latest value length; report it with the port count and database type. |
| Proxy queue grows after enrolment | SNMP pollers or preprocessing saturated | Raise `StartSNMPPollers` / preprocessing workers, or lengthen the `{$NE.*.INTERVAL}` macros. |

If something here does not match what you see on your installation, note the Zabbix version, image tag and the item's latest value and raise it; the lab evidence covers simulated switches only, not real hardware.
