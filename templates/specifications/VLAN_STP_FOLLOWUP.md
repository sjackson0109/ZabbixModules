# VLAN and STP next-milestone contract

Do not extend the initial profile's support claim to VLAN/STP merely because interface/LLDP collection passed. A dedicated evidence and integration gate follows the first release.

VLAN candidates: Q-BRIDGE-MIB current/static tables and dot1qPvid, plus BRIDGE-MIB dot1dBasePortIfIndex. Map bridge-port numbers to interface UIDs before interpreting bitmaps. Decode every bitmap octet, including stacks beyond64 ports; configured static membership differs from current operational membership. Keep egress/untagged/forbidden and PVID separate, identify bridge domain/SNMP context, and distinguish explicit native/access/trunk/hybrid configuration from inferred membership. Snapshot key: `ne.vlan.snapshot`; dataset owner adds its own attempt, status/success health and complete-snapshot retention.

STP candidates: BRIDGE-MIB dot1dStp plus RSTP/MSTP and vendor per-instance/per-VLAN objects where documented. Preserve roles separately from states, protocol/instance/region, root/designated bridge/port/cost/priority and topology-change counters. Explicitly map VLANs to STP instances/MST regions; absence of that mapping prevents a forwarding claim. Snapshot key: `ne.stp.snapshot`, with independent capability/health.

VLAN overlay describes configured membership and potential forwarding using interface/LAG operational state and known STP state. Unknown contexts/translation/QinQ/multichassis semantics become boundaries with reasons. It never proves end-to-end packet delivery, customer service availability or SLA. Physical loops are ordinary redundancy, not an STP failure trigger by themselves.

Future handoff must include >64-port bitmap fixtures, bridgePort≠ifIndex, static/current disagreement, tagged/untagged/native mismatch, VLAN context isolation, unsupported table, MST region/instance mapping, blocked versus forwarding state, topology-change counter reset, and partial collection. Demonstrate domain/user visibility and bounded item counts; bulk relationships must not expand into a port×VLAN×instance scalar explosion. Add VLAN/STP host pages only after module and dataset readiness checks pass.
