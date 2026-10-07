"""Disposable localhost SNMP transport checks, not vendor/model qualification."""

import asyncio
import bisect
import json
import secrets
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "collector"))

from network_explorer import oids
from network_explorer.collect import collect
from network_explorer.config import validate_device
from network_explorer.transport import SnmpTransport
from network_explorer.validation import validate_envelope


class StaticReadOnlyInstrumentation:
    """Only synthetic GET/GETNEXT evidence, no write implementation."""

    def __init__(self):
        from pysnmp.proto import rfc1902
        raw = json.loads((ROOT / "tests/fixtures/snmp/standard-switch.json").read_text())["values"]
        self.values = {}
        for name, value in raw.items():
            if isinstance(value, dict):
                value = rfc1902.OctetString(bytes.fromhex(value["hex"]))
            elif isinstance(value, str):
                value = rfc1902.OctetString(value)
            else:
                value = rfc1902.Integer32(value)
            self.values[tuple(int(part) for part in name.split("."))] = value
        self.names = sorted(self.values)

    def read_variables(self, *varbinds, **context):
        from pysnmp.proto.rfc1905 import noSuchObject, noSuchInstance
        result = []
        for name, _ in varbinds:
            key = tuple(name)
            if key in self.values:
                value = self.values[key]
            elif any(oid[:len(key)] == key for oid in self.names):
                value = noSuchInstance
            else:
                value = noSuchObject
            result.append((name, value))
        return result

    def read_next_variables(self, *varbinds, **context):
        from pysnmp.proto.rfc1902 import ObjectName
        from pysnmp.proto.rfc1905 import endOfMibView
        result = []
        for name, _ in varbinds:
            offset = bisect.bisect_right(self.names, tuple(name))
            if offset < len(self.names):
                found = self.names[offset]
                result.append((ObjectName(found), self.values[found]))
            else:
                result.append((name, endOfMibView))
        return result


async def responder_and_collect(version, *, max_varbinds=20000, bad_binding=False):
    from pysnmp.entity import config
    from pysnmp.entity.engine import SnmpEngine
    from pysnmp.entity.rfc3413 import cmdrsp, context
    from pysnmp.carrier.asyncio.dgram import udp
    from pysnmp.hlapi.v3arch.asyncio import usmHMAC192SHA256AuthProtocol, usmAesCfb128Protocol
    server = SnmpEngine()
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind(("127.0.0.1", 0))
    port = server_socket.getsockname()[1]
    carrier = udp.UdpTransport().open_server_mode(sock=server_socket)
    config.add_transport(server, udp.DOMAIN_NAME, carrier)
    credential = secrets.token_urlsafe(16)
    if version == "2c":
        config.add_v1_system(server, "test-v2c", credential)
        config.add_vacm_user(server, 2, "test-v2c", "noAuthNoPriv", (1,))
        binding = {"version": "2c", "community": credential if not bad_binding else secrets.token_urlsafe(16)}
    else:
        password = secrets.token_urlsafe(16)
        config.add_v3_user(server, "test-v3", usmHMAC192SHA256AuthProtocol,
                           credential, usmAesCfb128Protocol, password)
        config.add_vacm_user(server, 3, "test-v3", "authPriv", (1,))
        binding = {"version": "3", "username": "test-v3", "security_level": "authPriv",
                   "auth_protocol": "sha256", "auth_key": credential,
                   "priv_protocol": "aes128", "priv_key": password}
    ctx = context.SnmpContext(server)
    ctx.unregister_context_name(b"")
    ctx.register_context_name(b"", StaticReadOnlyInstrumentation())
    # Keep responders alive until the engine closes.
    responders = [cmdrsp.GetCommandResponder(server, ctx),
                  cmdrsp.NextCommandResponder(server, ctx),
                  cmdrsp.BulkCommandResponder(server, ctx)]
    await carrier._lport
    device = validate_device({"address": "127.0.0.1", "port": port, "timeout": 0.1,
                              "deadline": 3, "max_varbinds": max_varbinds, "snmp": binding})
    transport = SnmpTransport(device)
    try:
        if bad_binding:
            result = await transport.read(oids.UPTIME, scalar=True)
            assert result.complete is False
            assert result.error == "snmp_error"
            assert credential not in repr(result)
            return
        output = await collect(transport, "interfaces")
        validate_envelope(output)
        if max_varbinds == 20000:
            assert output["status"] == "ok", output["errors"]
            assert output["data"][0]["speed_bps"] == 1_000_000_000
            assert len(output["data"]) == 3
            assert output["source"]["method"] == "python_snmp"
        else:
            assert output["status"] in ("failed", "partial")
            assert output["complete"] is False
            assert "varbind_limit" in {error["code"] for error in output["errors"]}
        assert credential not in json.dumps(output)
    finally:
        await transport.close()
        for responder in responders:
            responder.close(server)
        server.close_dispatcher()
        await asyncio.sleep(0)


@pytest.mark.parametrize("version", ["2c", "3"])
def test_real_localhost_snmp_roundtrip(version):
    asyncio.run(responder_and_collect(version))


def test_transport_varbind_budget_never_reports_complete():
    asyncio.run(responder_and_collect("2c", max_varbinds=2))


def test_incorrect_binding_is_failure_and_redacted():
    asyncio.run(responder_and_collect("2c", bad_binding=True))
