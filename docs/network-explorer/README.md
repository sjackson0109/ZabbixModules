# Zabbix Network Explorer: design pack

Prepared 6 October 2026 as the build baseline; kept as the design record. The implementation now exists: current state is in [build status](../operations/BUILD_STATUS.md) and planned work in the [roadmap](ROADMAP.md). Passages later work replaced are marked **Superseded**.

- [Architecture and product design](DESIGN.md): collection, canonical data, templates, discovery, widgets, dashboards, reports, services, security, operations.
- [Build plan and acceptance](BUILD_PLAN.md): dependency order, deliverables, validation and requirement traceability.
- [Template rebuild requirements](TEMPLATE_REQUIREMENTS.md): common acquisition contracts, vendor evidence, dashboards, monitoring coverage and migration.
- [Decisions and deployment inputs](DECISIONS.md): defaults for autonomous development and facts required for real deployment.
- [Roadmap](ROADMAP.md): the post-PR #12 improvement programme, gap analysis, backlog and proposals awaiting approval.
- [Research provenance](research/sources.json): immutable official Zabbix source URLs and local SHA-256 hashes.
- Inventory inputs: [vendor inventory](VENDOR_INVENTORY.csv), [capability matrix](CAPABILITY_MATRIX.csv), [monitoring migration coverage](MONITORING_COVERAGE.csv). These are header-only intake templates, not populated or verified inventories.

This pack interprets the uploaded requirements specification. It does not authorise access to a customer environment, production changes, automatic enrolment of neighbours, or report delivery. Source inspection is evidence of framework contracts, not runtime validation. Do not modify installed Zabbix core.

**Superseded:** when this pack was written the checkout was empty and no collector, template or widget existed. All of them now exist in this repository.
