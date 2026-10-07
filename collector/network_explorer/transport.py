"""Bounded SNMP GET/GETBULK, with no SET or destination discovery."""

import asyncio
import ipaddress
import json
import time
from pathlib import Path
from typing import Any

from .models import ReadResult


def _decode_fixture(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"hex"}:
        return bytes.fromhex(value["hex"])
    if value is None or isinstance(value, (str, int)) and not isinstance(value, bool):
        return value
    raise ValueError("Fixture value must be an integer, string, null or hexadecimal octets.")


class FixtureTransport:
    """Synthetic evidence transport. Fixtures must never contain credentials."""

    method = "fixture"

    def __init__(self, fixture: dict):
        if fixture.get("format") != "network-explorer-snmp-fixture-1":
            raise ValueError("Unknown fixture format.")
        self.values = {key.lstrip("."): _decode_fixture(value) for key, value in fixture["values"].items()}
        self.results = fixture.get("results", {})
        self.uptime_reads = iter(fixture.get("uptime_reads", []))

    @classmethod
    def from_file(cls, path: str | Path):
        with open(path, encoding="utf-8") as stream:
            return cls(json.load(stream))

    async def read(self, oid: str, scalar: bool = False) -> ReadResult:
        from .oids import UPTIME
        state = self.results.get(oid, {})
        # An explicitly unknown fixture subtree is unsupported, not an empty success.
        present = {key: value for key, value in self.values.items()
                   if key == oid} if scalar else {
                       key: value for key, value in self.values.items() if key.startswith(oid + ".")
                   }
        if oid == UPTIME:
            value = next(self.uptime_reads, None)
            if value is not None:
                present = {oid: value}
        return ReadResult(present, state.get("complete", True),
                          state.get("unsupported", not present and not state), state.get("error"))

    async def close(self):
        return None


class SnmpTransport:
    method = "python_snmp"

    def __init__(self, device: dict):
        self.device = device
        self.deadline = time.monotonic() + device["deadline"]
        self.count = 0
        self.engine = self.auth = self.target = self.context = None

    async def initialize(self):
        import pysnmp.hlapi.v3arch.asyncio as hlapi
        self.engine = hlapi.SnmpEngine()
        snmp = self.device["snmp"]
        if snmp["version"] == "2c":
            self.auth = hlapi.CommunityData(snmp["community"], mpModel=1)
        else:
            level = snmp.get("security_level", "authPriv")
            auth_map = {"sha1": hlapi.usmHMACSHAAuthProtocol,
                        "sha224": hlapi.usmHMAC128SHA224AuthProtocol,
                        "sha256": hlapi.usmHMAC192SHA256AuthProtocol,
                        "sha384": hlapi.usmHMAC256SHA384AuthProtocol,
                        "sha512": hlapi.usmHMAC384SHA512AuthProtocol}
            self.auth = hlapi.UsmUserData(
                snmp["username"],
                authKey=snmp.get("auth_key") if level != "noAuthNoPriv" else None,
                privKey=snmp.get("priv_key") if level == "authPriv" else None,
                authProtocol=auth_map[snmp.get("auth_protocol", "sha256")] if level != "noAuthNoPriv" else hlapi.usmNoAuthProtocol,
                privProtocol=hlapi.usmAesCfb128Protocol if level == "authPriv" else hlapi.usmNoPrivProtocol,
            )
        target_class = hlapi.UdpTransportTarget
        try:
            if ipaddress.ip_address(self.device["address"]).version == 6:
                target_class = hlapi.Udp6TransportTarget
        except ValueError:
            pass  # Hostname resolution is restricted to the configured allowlist entry.
        self.target = await asyncio.wait_for(target_class.create(
            (self.device["address"], self.device["port"]),
            timeout=self.device["timeout"], retries=self.device["retries"],
        ), timeout=max(0.01, self.deadline - time.monotonic()))
        self.context = hlapi.ContextData(contextName=snmp.get("context", ""))

    @staticmethod
    def _value(value):
        from pysnmp.proto import rfc1902
        if isinstance(value, rfc1902.OctetString):
            return bytes(value.asOctets())
        if isinstance(value, (rfc1902.Integer, rfc1902.Integer32, rfc1902.Counter32,
                              rfc1902.Counter64, rfc1902.Gauge32, rfc1902.TimeTicks,
                              rfc1902.Unsigned32)):
            return int(value)
        return value.prettyPrint()

    async def read(self, oid: str, scalar: bool = False) -> ReadResult:
        if self.deadline <= time.monotonic():
            return ReadResult(complete=False, error="deadline_exceeded")
        if self.count >= self.device["max_varbinds"]:
            return ReadResult(complete=False, error="varbind_limit")
        result = ReadResult()
        try:
            if self.engine is None:
                await self.initialize()
            await asyncio.wait_for(self._read(oid, scalar, result),
                                   timeout=max(0.01, self.deadline - time.monotonic()))
        except asyncio.TimeoutError:
            result.complete, result.error = False, "deadline_exceeded"
        except Exception:
            # Library/authentication errors may contain credentials. Emit fixed code.
            result.complete, result.error = False, "transport_error"
        return result

    async def _read(self, oid: str, scalar: bool, result: ReadResult):
        import pysnmp.hlapi.v3arch.asyncio as hlapi
        from pysnmp.proto.rfc1905 import NoSuchObject, NoSuchInstance, EndOfMibView
        obj = hlapi.ObjectType(hlapi.ObjectIdentity(tuple(int(part) for part in oid.split("."))))
        if scalar:
            response = await hlapi.get_cmd(self.engine, self.auth, self.target, self.context,
                                           obj, lookupMib=False)
            responses = _one(response)
        else:
            responses = hlapi.bulk_walk_cmd(self.engine, self.auth, self.target, self.context,
                                           0, 20, obj, lookupMib=False, lexicographicMode=False,
                                           ignoreNonIncreasingOid=False)
        async for indication, status, _, varbinds in responses:
            if indication or status:
                result.complete, result.error = False, "snmp_error"
                break
            for name, value in varbinds:
                full = str(name)
                if isinstance(value, NoSuchObject):
                    result.unsupported = True
                    continue
                if isinstance(value, (NoSuchInstance, EndOfMibView)):
                    if scalar:
                        result.unsupported = True
                    continue
                if (full != oid) if scalar else (not full.startswith(oid + ".")):
                    continue
                if self.count >= self.device["max_varbinds"]:
                    result.complete, result.error = False, "varbind_limit"
                    return
                self.count += 1
                result.values[full] = self._value(value)
        if not scalar and result.complete and not result.values:
            # Walking an empty subtree alone cannot distinguish absent table support.
            probe = await hlapi.get_cmd(self.engine, self.auth, self.target, self.context,
                                       obj, lookupMib=False)
            indication, status, _, varbinds = probe
            if indication or status:
                result.complete, result.error = False, "snmp_error"
            elif any(isinstance(value, NoSuchObject) for _, value in varbinds):
                result.unsupported = True

    async def close(self):
        if self.engine is not None:
            self.engine.close_dispatcher()


async def _one(value):
    yield value
