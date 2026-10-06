# Zabbix Network Explorer: design pack

Prepared 6 October 2026. Status: proposed build baseline, pending deployment facts.

- [Architecture and product design](DESIGN.md): collection, canonical data, templates, discovery, widgets, dashboards, reports, services, security, operations.
- [Build plan and acceptance](BUILD_PLAN.md): dependency order, deliverables, validation and requirement traceability.
- [Template rebuild requirements](TEMPLATE_REQUIREMENTS.md): common acquisition contracts, vendor evidence, dashboards, monitoring coverage and migration.
- [Decisions and deployment inputs](DECISIONS.md): defaults for autonomous development and facts required for real deployment.
- [Research provenance](research/sources.json): immutable official Zabbix source URLs and local SHA-256 hashes.
- Inventory inputs: [vendor inventory](VENDOR_INVENTORY.csv), [capability matrix](CAPABILITY_MATRIX.csv), [monitoring migration coverage](MONITORING_COVERAGE.csv). These are header-only intake templates, not populated or verified inventories.

This pack interprets the uploaded requirements specification. It does not authorise access to a customer environment, production changes, automatic enrolment of neighbours, or report delivery. No production collectors, templates or widgets have been implemented. Source inspection is evidence of framework contracts, not runtime validation.

At initial inspection, the selected checkout had no commit or source files and its remote read returned no `main` ref. This directory now contains the committed design baseline; application implementation has not started. During build, use the existing isolated checkout; do not create a worktree unless the user requests one. Do not modify installed Zabbix core.
