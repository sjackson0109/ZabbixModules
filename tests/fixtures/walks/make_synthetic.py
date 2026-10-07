#!/usr/bin/env python3
"""Generate the synthetic standard-MIB switch walks used by tests and the lab.

These are invented devices, not captures. They exercise every standard table
the native templates read, in the snmpsim .snmprec format that
tools/inventory/capture_walk.py produces for real devices:

  sw-core-01   24 copper + 2 SFP+ ports, LACP Po1 on the SFP+ pair, RSTP,
               VLAN 49 access on ports 1-2, trunk with 49 on port 3, trunk
               without 49 on port 4, port 23 negotiated at 100M half duplex
               against a 1G-capable partner (the spec's Appendix A journey).
  sw-access-17 48 copper ports; port 48 is the far end of sw-core-01 port 23.

Run with --check to verify the committed files are current.
"""
from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path

HERE = Path(__file__).resolve().parent


def oid_key(oid: str) -> tuple[int, ...]:
    return tuple(int(part) for part in oid.split("."))


class Agent:
    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, str]] = {}

    def int(self, oid: str, value: int) -> None:
        self.rows[oid] = ("2", str(value))

    def str(self, oid: str, value: str) -> None:
        self.rows[oid] = ("4", value)

    def hex(self, oid: str, data: bytes) -> None:
        self.rows[oid] = ("4x", data.hex())

    def oid(self, oid: str, value: str) -> None:
        self.rows[oid] = ("6", value)

    def gauge(self, oid: str, value: int) -> None:
        self.rows[oid] = ("66", str(value))

    def ticks(self, oid: str, value: int) -> None:
        self.rows[oid] = ("67", str(value))

    def ip(self, oid: str, value: str) -> None:
        self.rows[oid] = ("64", value)

    def render(self) -> str:
        return "".join(f"{oid}|{tag}|{value}\n" for oid, (tag, value) in
                       sorted(self.rows.items(), key=lambda item: oid_key(item[0])))


def mac(text: str) -> bytes:
    return bytes.fromhex(text.replace(":", ""))


def portlist(ports: list[int], size: int = 8) -> bytes:
    data = bytearray(size)
    for port in ports:
        data[(port - 1) // 8] |= 0x80 >> ((port - 1) % 8)
    return bytes(data)


def bits(positions: list[int], size: int = 2) -> bytes:
    return portlist([p + 1 for p in positions], size)


UPTIME = 8_640_000  # 1 day in TimeTicks
SPEED_1G, SPEED_10G = 1000, 10000
AUTONEG_10_100_1000 = [1, 2, 4, 5, 14, 15]   # 10T, 10TFD, 100TX, 100TXFD, 1000T, 1000TFD
MAU_COPPER_SUPPORTED = [10, 11, 15, 16, 29, 30]
MAU_TYPE = "1.3.6.1.2.1.26.4."


def system(a: Agent, name: str, descr: str, chassis: str, address: str, model: str, serial: str) -> None:
    a.str("1.3.6.1.2.1.1.1.0", descr)
    a.oid("1.3.6.1.2.1.1.2.0", "1.3.6.1.4.1.99999.1.1")
    a.ticks("1.3.6.1.2.1.1.3.0", UPTIME)
    a.str("1.3.6.1.2.1.1.5.0", name)
    a.int("1.3.6.1.2.1.47.1.1.1.1.5.1", 3)
    a.str("1.3.6.1.2.1.47.1.1.1.1.7.1", "Unit 1")
    a.str("1.3.6.1.2.1.47.1.1.1.1.10.1", "1.2.3")
    a.str("1.3.6.1.2.1.47.1.1.1.1.11.1", serial)
    a.str("1.3.6.1.2.1.47.1.1.1.1.13.1", model)
    a.int("1.0.8802.1.1.2.1.3.1.0", 4)
    a.hex("1.0.8802.1.1.2.1.3.2.0", mac(chassis))
    a.str("1.0.8802.1.1.2.1.3.3.0", name)
    octets = ".".join(str(o) for o in ipaddress.ip_address(address).packed)
    a.int(f"1.0.8802.1.1.2.1.3.8.1.3.1.4.{octets}", 2)


def interface(a: Agent, ix: int, name: str, descr: str, *, if_type: int = 6, admin: int = 1, oper: int = 1,
              high_speed: int = SPEED_1G, duplex: int | None = 3, mac_addr: str | None = None,
              alias: str = "", connector: int = 1) -> None:
    a.str(f"1.3.6.1.2.1.2.2.1.2.{ix}", descr)
    a.int(f"1.3.6.1.2.1.2.2.1.3.{ix}", if_type)
    a.int(f"1.3.6.1.2.1.2.2.1.4.{ix}", 1500)
    a.gauge(f"1.3.6.1.2.1.2.2.1.5.{ix}", min(high_speed * 1_000_000 if oper == 1 else 0, 4_294_967_295))
    a.hex(f"1.3.6.1.2.1.2.2.1.6.{ix}", mac(mac_addr or f"00:11:22:aa:00:{ix % 256:02x}"))
    a.int(f"1.3.6.1.2.1.2.2.1.7.{ix}", admin)
    a.int(f"1.3.6.1.2.1.2.2.1.8.{ix}", oper)
    a.ticks(f"1.3.6.1.2.1.2.2.1.9.{ix}", UPTIME - 360_000)
    a.str(f"1.3.6.1.2.1.31.1.1.1.1.{ix}", name)
    a.gauge(f"1.3.6.1.2.1.31.1.1.1.15.{ix}", high_speed if oper == 1 else 0)
    a.int(f"1.3.6.1.2.1.31.1.1.1.17.{ix}", connector)
    a.str(f"1.3.6.1.2.1.31.1.1.1.18.{ix}", alias)
    if duplex is not None:
        a.int(f"1.3.6.1.2.1.10.7.2.1.19.{ix}", duplex)


def mau(a: Agent, ix: int, oper_type: int, supported: list[int], advertised: list[int] | None,
        received: list[int] | None) -> None:
    a.oid(f"1.3.6.1.2.1.26.2.1.1.3.{ix}.1", MAU_TYPE + str(oper_type))
    a.hex(f"1.3.6.1.2.1.26.2.1.1.13.{ix}.1", bits(supported, 8))
    if advertised is not None:
        a.int(f"1.3.6.1.2.1.26.5.1.1.1.{ix}.1", 1)
        a.hex(f"1.3.6.1.2.1.26.5.1.1.10.{ix}.1", bits(advertised))
        a.hex(f"1.3.6.1.2.1.26.5.1.1.11.{ix}.1", bits(received or []))


def lldp_local(a: Agent, port_num: int, name: str, descr: str) -> None:
    a.int(f"1.0.8802.1.1.2.1.3.7.1.2.{port_num}", 5)
    a.str(f"1.0.8802.1.1.2.1.3.7.1.3.{port_num}", name)
    a.str(f"1.0.8802.1.1.2.1.3.7.1.4.{port_num}", descr)


def lldp_remote(a: Agent, port_num: int, rem: int, *, chassis: str, port: str, port_desc: str, sys_name: str,
                address: str | None, oper_mau: int | None = None, advertised: list[int] | None = None,
                aggregated_port: int | None = None, pvid: int | None = None) -> None:
    index = f"0.{port_num}.{rem}"
    a.int(f"1.0.8802.1.1.2.1.4.1.1.4.{index}", 4)
    a.hex(f"1.0.8802.1.1.2.1.4.1.1.5.{index}", mac(chassis))
    a.int(f"1.0.8802.1.1.2.1.4.1.1.6.{index}", 5)
    a.str(f"1.0.8802.1.1.2.1.4.1.1.7.{index}", port)
    a.str(f"1.0.8802.1.1.2.1.4.1.1.8.{index}", port_desc)
    a.str(f"1.0.8802.1.1.2.1.4.1.1.9.{index}", sys_name)
    a.str(f"1.0.8802.1.1.2.1.4.1.1.10.{index}", "Synthetic switch OS 1.2.3")
    a.hex(f"1.0.8802.1.1.2.1.4.1.1.11.{index}", bits([2, 4]))
    a.hex(f"1.0.8802.1.1.2.1.4.1.1.12.{index}", bits([2]))
    if address:
        octets = ".".join(str(o) for o in ipaddress.ip_address(address).packed)
        a.int(f"1.0.8802.1.1.2.1.4.2.1.3.{index}.1.4.{octets}", 2)
    if oper_mau is not None:
        a.int(f"1.0.8802.1.1.2.1.5.4623.1.3.1.1.1.{index}", 1)
        a.int(f"1.0.8802.1.1.2.1.5.4623.1.3.1.1.2.{index}", 1)
        a.hex(f"1.0.8802.1.1.2.1.5.4623.1.3.1.1.3.{index}", bits(advertised or []))
        a.int(f"1.0.8802.1.1.2.1.5.4623.1.3.1.1.4.{index}", oper_mau)
    if aggregated_port is not None:
        a.hex(f"1.0.8802.1.1.2.1.5.4623.1.3.3.1.1.{index}", bits([0, 1], 1))
        a.int(f"1.0.8802.1.1.2.1.5.4623.1.3.3.1.2.{index}", aggregated_port)
    if pvid is not None:
        a.int(f"1.0.8802.1.1.2.1.5.32962.1.3.1.1.1.{index}", pvid)


def vlans(a: Agent, table: dict[int, tuple[str, list[int], list[int], list[int]]], pvids: dict[int, int],
          size: int) -> None:
    for vid, (name, egress, untagged, forbidden) in table.items():
        a.str(f"1.3.6.1.2.1.17.7.1.4.3.1.1.{vid}", name)
        a.hex(f"1.3.6.1.2.1.17.7.1.4.3.1.2.{vid}", portlist(egress, size))
        a.hex(f"1.3.6.1.2.1.17.7.1.4.3.1.3.{vid}", portlist(forbidden, size))
        a.hex(f"1.3.6.1.2.1.17.7.1.4.3.1.4.{vid}", portlist(untagged, size))
        a.hex(f"1.3.6.1.2.1.17.7.1.4.2.1.4.0.{vid}", portlist(egress, size))
        a.hex(f"1.3.6.1.2.1.17.7.1.4.2.1.5.0.{vid}", portlist(untagged, size))
        a.int(f"1.3.6.1.2.1.17.7.1.4.2.1.6.0.{vid}", 2)
    for port, pvid in pvids.items():
        a.gauge(f"1.3.6.1.2.1.17.7.1.4.5.1.1.{port}", pvid)
        a.int(f"1.3.6.1.2.1.17.7.1.4.5.1.2.{port}", 1)


def stp_port(a: Agent, port: int, state: int, cost: int, designated_bridge: bytes, designated_port: int,
             edge: bool = False) -> None:
    a.int(f"1.3.6.1.2.1.17.2.15.1.1.{port}", port)
    a.int(f"1.3.6.1.2.1.17.2.15.1.2.{port}", 128)
    a.int(f"1.3.6.1.2.1.17.2.15.1.3.{port}", state)
    a.int(f"1.3.6.1.2.1.17.2.15.1.4.{port}", 1)
    a.int(f"1.3.6.1.2.1.17.2.15.1.5.{port}", cost)
    a.hex(f"1.3.6.1.2.1.17.2.15.1.6.{port}", ROOT_BRIDGE)
    a.int(f"1.3.6.1.2.1.17.2.15.1.7.{port}", 2000)
    a.hex(f"1.3.6.1.2.1.17.2.15.1.8.{port}", designated_bridge)
    a.hex(f"1.3.6.1.2.1.17.2.15.1.9.{port}", (0x8000 | designated_port).to_bytes(2, "big"))
    a.int(f"1.3.6.1.2.1.17.2.15.1.11.{port}", cost)
    a.int(f"1.3.6.1.2.1.17.2.19.1.3.{port}", 1 if edge else 2)
    a.int(f"1.3.6.1.2.1.17.2.19.1.5.{port}", 1)


CORE_MAC = "00:11:22:33:44:01"
ACCESS_MAC = "00:11:22:33:44:17"
DIST1_MAC = "00:11:22:33:44:a1"
DIST2_MAC = "00:11:22:33:44:a2"
ROOT_BRIDGE = (4096).to_bytes(2, "big") + mac(DIST2_MAC)


def core() -> Agent:
    a = Agent()
    system(a, "sw-core-01", "Synthetic switch OS 1.2.3, 24-port", CORE_MAC, "10.101.1.10", "SYN-24T-2X", "SYNCORE0001")
    a.int("1.3.6.1.2.1.2.1.0", 27)
    for ix in range(1, 25):
        oper, admin, speed, duplex = 1, 1, SPEED_1G, 3
        if ix == 5:
            oper, speed = 2, SPEED_1G
        if ix == 6:
            admin, oper = 2, 2
        if ix == 23:
            speed, duplex = 100, 2
        interface(a, ix, f"Gi1/0/{ix}", f"GigabitEthernet1/0/{ix}", admin=admin, oper=oper, high_speed=speed,
                  duplex=duplex, alias={1: "AP office 1", 2: "AP office 2", 23: "Uplink to access-17",
                                        24: "Uplink to dist-01"}.get(ix, ""))
        if oper == 1:
            mau(a, ix, 15 if ix == 23 else 30, MAU_COPPER_SUPPORTED, AUTONEG_10_100_1000, AUTONEG_10_100_1000)
        else:
            mau(a, ix, 30, MAU_COPPER_SUPPORTED, AUTONEG_10_100_1000, [])
    for ix, n in ((25, 1), (26, 2)):
        interface(a, ix, f"Te1/0/{n}", f"TenGigabitEthernet1/0/{n}", high_speed=SPEED_10G, alias="Po1 member")
        mau(a, ix, 33, [33], None, None)
    interface(a, 1001, "Po1", "Port-channel1", if_type=161, high_speed=20000, duplex=None, connector=2,
              mac_addr="00:11:22:33:44:01", alias="To dist-02")
    for member in (25, 26):
        a.int(f"1.3.6.1.2.1.31.1.2.1.3.1001.{member}", 1)
    # Bridge ports: 1-24 are the copper ports, 27 is Po1.
    a.hex("1.3.6.1.2.1.17.1.1.0", mac(CORE_MAC))
    for port in range(1, 25):
        a.int(f"1.3.6.1.2.1.17.1.4.1.2.{port}", port)
    a.int("1.3.6.1.2.1.17.1.4.1.2.27", 1001)
    # LLDP
    for port_num, ix in [(p, p) for p in range(1, 25)] + [(25, 25), (26, 26)]:
        name = f"Gi1/0/{ix}" if ix <= 24 else f"Te1/0/{ix - 24}"
        lldp_local(a, port_num, name, ("GigabitEthernet1/0/" if ix <= 24 else "TenGigabitEthernet1/0/") +
                   str(ix if ix <= 24 else ix - 24))
    lldp_remote(a, 23, 1, chassis=ACCESS_MAC, port="Gi1/0/48", port_desc="Uplink to core-01",
                sys_name="sw-access-17", address="10.101.2.17", oper_mau=16, advertised=AUTONEG_10_100_1000, pvid=1)
    lldp_remote(a, 24, 1, chassis=DIST1_MAC, port="Gi0/1", port_desc="Downlink core-01",
                sys_name="sw-dist-01", address="10.102.5.10", oper_mau=30, advertised=AUTONEG_10_100_1000, pvid=1)
    for port_num, peer in ((25, "Te0/1"), (26, "Te0/2")):
        lldp_remote(a, port_num, 1, chassis=DIST2_MAC, port=peer, port_desc="Po10 member", sys_name="sw-dist-02",
                    address="10.101.0.2", oper_mau=33, aggregated_port=1010, pvid=1)
    # VLANs (bridge ports): 1-2 access 49; 3 trunk 49,50 native 1; 4 trunk 50 only; 27 (Po1) trunk 49,50.
    vlans(a, {
        1: ("default", [3, 4, 7, 8, 24, 27], [3, 4, 7, 8, 24, 27], []),
        49: ("Wireless APs", [1, 2, 3, 27], [1, 2], [4]),
        50: ("Voice", [3, 4, 27], [], []),
    }, {1: 49, 2: 49, 3: 1, 4: 1, 7: 1, 8: 1, 24: 1, 27: 1}, size=4)
    # RSTP: root is dist-02 via Po1 (bridge port 27); port 24 to dist-01 is the alternate path.
    own = (32768).to_bytes(2, "big") + mac(CORE_MAC)
    a.int("1.3.6.1.2.1.17.2.1.0", 3)
    a.int("1.3.6.1.2.1.17.2.2.0", 32768)
    a.ticks("1.3.6.1.2.1.17.2.3.0", 720_000)
    a.int("1.3.6.1.2.1.17.2.4.0", 7)
    a.hex("1.3.6.1.2.1.17.2.5.0", ROOT_BRIDGE)
    a.int("1.3.6.1.2.1.17.2.6.0", 2000)
    a.int("1.3.6.1.2.1.17.2.7.0", 27)
    a.int("1.3.6.1.2.1.17.2.16.0", 2)
    for port in (1, 2, 3, 4, 7, 8, 23):
        stp_port(a, port, 5, 20000, own, port, edge=port in (1, 2, 7, 8))
    stp_port(a, 24, 2, 20000, (32768).to_bytes(2, "big") + mac(DIST1_MAC), 1)
    stp_port(a, 27, 5, 1000, ROOT_BRIDGE, 10)
    # LACP Po1 to dist-02.
    a.hex("1.2.840.10006.300.43.1.1.1.1.4.1001", mac(CORE_MAC))
    a.int("1.2.840.10006.300.43.1.1.1.1.5.1001", 1)
    a.hex("1.2.840.10006.300.43.1.1.1.1.8.1001", mac(DIST2_MAC))
    for member, partner_port in ((25, 1), (26, 2)):
        a.int(f"1.2.840.10006.300.43.1.2.1.1.12.{member}", 1001)
        a.int(f"1.2.840.10006.300.43.1.2.1.1.13.{member}", 1001)
        a.int(f"1.2.840.10006.300.43.1.2.1.1.17.{member}", partner_port)
        a.hex(f"1.2.840.10006.300.43.1.2.1.1.21.{member}", bytes([0xBC]))
    return a


def access() -> Agent:
    a = Agent()
    system(a, "sw-access-17", "Synthetic switch OS 1.2.3, 48-port", ACCESS_MAC, "10.101.2.17", "SYN-48T", "SYNACC0017")
    a.int("1.3.6.1.2.1.2.1.0", 48)
    for ix in range(1, 49):
        oper = 1 if ix in (1, 2, 10, 48) else 2
        interface(a, ix, f"Gi1/0/{ix}", f"GigabitEthernet1/0/{ix}", oper=oper,
                  high_speed=100 if ix == 48 else SPEED_1G, alias="Uplink to core-01" if ix == 48 else "")
        mau(a, ix, 16 if ix == 48 else 30, MAU_COPPER_SUPPORTED, AUTONEG_10_100_1000,
            AUTONEG_10_100_1000 if oper == 1 else [])
        a.int(f"1.3.6.1.2.1.17.1.4.1.2.{ix}", ix)
        lldp_local(a, ix, f"Gi1/0/{ix}", f"GigabitEthernet1/0/{ix}")
    a.hex("1.3.6.1.2.1.17.1.1.0", mac(ACCESS_MAC))
    lldp_remote(a, 48, 1, chassis=CORE_MAC, port="Gi1/0/23", port_desc="Uplink to access-17",
                sys_name="sw-core-01", address="10.101.1.10", oper_mau=15, advertised=AUTONEG_10_100_1000, pvid=1)
    vlans(a, {
        1: ("default", list(range(3, 49)), list(range(3, 49)), []),
        49: ("Wireless APs", [1, 2, 48], [1, 2], []),
        50: ("Voice", [48], [], []),
    }, {**{p: 1 for p in range(3, 49)}, 1: 49, 2: 49}, size=8)
    # RSTP: root (dist-02) is reached through core-01 on port 48; up ports 1, 2, 10 are edge ports.
    a.int("1.3.6.1.2.1.17.2.1.0", 3)
    a.int("1.3.6.1.2.1.17.2.2.0", 32768)
    a.ticks("1.3.6.1.2.1.17.2.3.0", 360_000)
    a.int("1.3.6.1.2.1.17.2.4.0", 3)
    a.hex("1.3.6.1.2.1.17.2.5.0", ROOT_BRIDGE)
    a.int("1.3.6.1.2.1.17.2.6.0", 22000)
    a.int("1.3.6.1.2.1.17.2.7.0", 48)
    a.int("1.3.6.1.2.1.17.2.16.0", 2)
    own = (32768).to_bytes(2, "big") + mac(ACCESS_MAC)
    for port in (1, 2, 10):
        stp_port(a, port, 5, 20000, own, port, edge=True)
    stp_port(a, 48, 5, 200000, (32768).to_bytes(2, "big") + mac(CORE_MAC), 23)
    return a


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, agent in (("sw-core-01", core()), ("sw-access-17", access())):
        target = HERE / f"{name}.snmprec"
        text = agent.render()
        if args.check:
            if not target.exists() or target.read_text() != text:
                raise SystemExit(f"{target} is out of date; run {Path(__file__).name}")
        else:
            target.write_text(text)


if __name__ == "__main__":
    main()
