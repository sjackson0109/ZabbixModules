# Disposable compatibility lab

This lab tests Network Explorer against real Zabbix servers, frontends and active SQLite proxies, using PostgreSQL 16.10. It imports the explicitly laboratory-only replay template, registers all custom modules, creates synthetic hosts, sends canonical fixture envelopes, verifies dependent snapshots and low-level discovery, and checks frontend rendering and ordinary-user privacy.

No production connectivity, SNMP walks, or existing customer credentials are needed. The sender and frontend publish only on the host's loopback address. This lab supplies evidence for the shared contracts and widgets; it does not qualify any vendor/model SNMP template.

Requirements: Docker Engine, Docker Compose v2, Python 3.10+, sufficient disk space for the official images, and roughly 1 GB RAM per running version. All image references are immutable registry digests in [images.lock.json](images.lock.json). TLS and artifact verification remain enabled during image acquisition.

```sh
sh scripts/test-compatibility.sh
# Run only one family:
sh scripts/test-compatibility.sh 7.0
```

The matrix pins Zabbix 7.0.20, 7.2.7 and 7.4.3. These are tested release patches, not a promise that every patch between them has been tested. The web URLs are `http://127.0.0.1:18070`, `:18072` and `:18074`; do not publish them as shared previews. These are disposable HTTP loopback endpoints.

Generated database/admin/viewer passwords and reports stay in ignored `lab/.state/<family>/` with restrictive permissions. The first successful startup changes the supplied default admin password to a generated value. Never commit this directory or disclose its contents. Access the credentials locally if interactive lab access is needed.

Commands can also be run separately:

```sh
python3 lab/lab.py start --version 7.4
python3 lab/lab.py install-modules --version 7.4
python3 tests/integration/zabbix_runtime.py --version 7.4
python3 lab/lab.py status --version 7.4
python3 lab/lab.py stop --version 7.4
```

`stop` retains the generated lab database. `destroy` removes only that family's named Compose containers/network/database volume, and resets its admin-initialisation marker:

```sh
python3 lab/lab.py destroy --version 7.4
```

Startup does not copy modules automatically. The integration command copies the current frontend files into the web container and registers/enables them through the official Zabbix module API. This avoids assumptions about bind-mount ownership and makes each integration run exercise the current source. Installing different files with the same module identifier remains limited to these disposable labs.

For local troubleshooting, run Docker Compose with the generated environment file and the correct project. Logs are not saved to the repository. Do not paste container inspection output or configuration dumps; those may contain generated passwords.

The replay template includes an inherited host dashboard with Overview, Connectivity and Diagnostics pages. Production SNMP acquisition and vendor-specific templates are intentionally separate deliverables. Current tests use invented `192.0.2.0/24` identities; they perform no scans.
