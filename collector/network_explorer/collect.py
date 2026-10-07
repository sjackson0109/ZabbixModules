"""Independent dataset acquisition with explicit success and failure evidence."""

import json

from . import normalize, oids
from .models import Evidence, envelope, utc_now

DATASETS = ("device", "interfaces", "lldp", "lag")


async def collect(transport, dataset: str, *, redact_remote: bool = True,
                  generation_id: str | None = None, attempted_at: str | None = None) -> dict:
    if dataset not in DATASETS:
        raise ValueError("Unknown dataset.")
    output = envelope(dataset, attempted_at, generation_id, transport.method)
    evidence = Evidence()
    requirements: set[str] = {oids.UPTIME}

    async def read(oid: str, *, scalar: bool = False, required: bool = False):
        evidence.reads[oid] = await transport.read(oid, scalar=scalar)
        if required:
            requirements.add(oid)

    await read(oids.UPTIME, scalar=True, required=True)
    uptime_start = normalize.integer(evidence.scalar(oids.UPTIME))
    if dataset == "device":
        await read(oids.SYS_NAME, scalar=True, required=True)
        await read(oids.LLDP_LOCAL_CHASSIS_SUBTYPE, scalar=True)
        await read(oids.LLDP_LOCAL_CHASSIS_ID, scalar=True)
    else:
        await read(oids.IF_NUMBER, scalar=True, required=True)
        for key, oid in oids.IF.items():
            await read(oid, required=key in oids.IF_REQUIRED)
        if dataset == "lldp":
            await read(oids.LLDP_LOCAL_CHASSIS_SUBTYPE, scalar=True, required=True)
            await read(oids.LLDP_LOCAL_CHASSIS_ID, scalar=True, required=True)
            for key, oid in oids.LLDP_LOCAL.items():
                await read(oid, required=key in ("subtype", "id"))
            for key, oid in oids.LLDP_REMOTE.items():
                await read(oid, required=key in ("chassis_subtype", "chassis_id", "port_subtype", "port_id"))
        elif dataset == "lag":
            for key, oid in oids.LAG.items():
                await read(oid, required=key in ("individual", "attached"))
    ending = await transport.read(oids.UPTIME, scalar=True)
    uptime_end = normalize.integer(ending.values.get(oids.UPTIME))
    if uptime_start is not None and uptime_end is not None and uptime_end < uptime_start:
        # A wrap is indistinguishable from reboot here; both invalidate snapshot coherence.
        evidence.error("device_restarted", "Device uptime changed backwards during collection; snapshot discarded.")
        output["errors"] = evidence.errors
        return output
    if not ending.complete or ending.error or uptime_end is None:
        evidence.error("ending_uptime_unavailable", "Collection could not confirm final device uptime.")
    for oid, result in evidence.reads.items():
        if result.error or not result.complete:
            evidence.error(result.error or "incomplete_walk", "A bounded SNMP read was unsuccessful or incomplete.")
        elif result.unsupported and oid in requirements:
            evidence.error("required_oid_unsupported", "A required standard OID is not available in this context.")
    observed_at = utc_now()
    if dataset == "device":
        rows = normalize.device(evidence, redact_remote)
        if rows[0]["hostname"] is None:
            rows = []
        proof = oids.SYS_NAME
    else:
        interface_rows = normalize.interfaces(evidence, output["generation_id"])
        if dataset == "interfaces":
            rows, proof = interface_rows, oids.IF["index"]
        elif dataset == "lldp":
            rows, proof = normalize.lldp(evidence, interface_rows, observed_at, redact_remote), oids.LLDP_LOCAL_CHASSIS_ID
        else:
            rows, proof = normalize.lag(evidence, interface_rows, redact_remote), oids.LAG["individual"]
    output["errors"] = evidence.errors
    proof_result = evidence.reads[proof]
    if proof_result.unsupported and not rows:
        output.update(status="unsupported", capability={"state": "unsupported", "reason": "Required OID is absent."})
    elif evidence.errors:
        if rows:
            output.update(status="partial", observed_at=observed_at, data=rows,
                          capability={"state": "partial", "reason": "Collection evidence is incomplete."})
        else:
            output["capability"]["reason"] = "Collection did not produce usable observations."
    else:
        output.update(status="ok", complete=True, observed_at=observed_at, data=rows,
                      capability={"state": "supported", "reason": None})
    return output


def serialize(output: dict, max_bytes: int = 61440) -> str:
    serialized = json.dumps(output, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    if len(serialized.encode("utf-8")) > max_bytes:
        failed = dict(output)
        failed.update(status="failed", complete=False, observed_at=None, data=[],
                      capability={"state": "unknown", "reason": "Snapshot requires partitioning."},
                      errors=[{"code": "output_limit", "message": "Snapshot exceeded the configured output size; nothing was truncated."}])
        return json.dumps(failed, separators=(",", ":"))
    return serialized
