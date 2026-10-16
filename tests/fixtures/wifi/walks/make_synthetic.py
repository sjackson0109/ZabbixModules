#!/usr/bin/env python3
"""Write the invented walks used by the Wi-Fi Explorer tests and lab (snmpsim .snmprec).

Every value is invented: documentation addresses (192.0.2.0/24), documentation MAC addresses (00:00:5e:00:53:xx,
RFC 7042) and lab names. The Aruba layout follows AI-AP-MIB as the operator's Aruba template records it
(docs/wifi-explorer/ARUBA_TEMPLATE_REVIEW.md). These walks qualify the parsers only, never Aruba hardware.

  aruba-instant-vc       the cluster's virtual controller: APs, radios, SSIDs, clients and its own RF detections
  aruba-instant-member   a member AP linked by mistake (no roster)
  aruba-instant-ap-01    lab-ap-01 polled at its own address: RF detections, and LLDP towards its switch
  generic-ap             a standalone AP that implements the standard MIBs only (IEEE 802.11 MIB, ENTITY-MIB,
                         HOST-RESOURCES-MIB): a 2.4 GHz and a 5 GHz radio, three SSID interfaces, one switched off
  generic-ap-tri         the same AP with a third radio on a channel that does not prove its band
  sw-wifi-dist-01        RSTP root; LACP Po1 to sw-wifi-access-01 (VLANs 1, 49, 56 but not 57) and Gi1/0/3 to
                         sw-wifi-access-02 (1, 49, 56, 57)
  sw-wifi-access-01      lab-ap-01..03 on Gi1/0/1-3 (native 49, tagged 56 and 57); lab-ap-03's port is down
  sw-wifi-access-02      lab-ap-04 on Gi1/0/1 (tagged 57 only, so VLAN 56 stops here) and lab-ap-05 on Gi1/0/2;
                         lab-ap-06 is on no switch that reports it

The switch walks use the Network Explorer lab helpers (tests/fixtures/walks/make_synthetic.py) so the standard
templates read them exactly as they read the Network Explorer lab.

  python3 tests/fixtures/wifi/walks/make_synthetic.py [--check]
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("ne_lab", HERE.parents[1] / "walks" / "make_synthetic.py")
NE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(NE)
AI = "1.3.6.1.4.1.14823.2.3.3.1"
AP = AI + ".2.1.1"
RADIO = AI + ".2.2.1"

# name, model, serial, status (1 up, 2 down), cpu, (free, total), uptime ticks, radios
# radio: (index, channel, width bits, tx power dBm, noise magnitude, 64 s utilisation, status)
APS = [
    ("lab-ap-01", "AP-515", "LAB0000001", 1, 7, (310000, 512000), 864000000,
     [(0, 36, 1, 18, 94, 23, 1), (1, 6, 0, 12, 90, 41, 1)]),
    ("lab-ap-02", "AP-515", "LAB0000002", 1, 12, (300000, 512000), 864000000,
     [(0, 149, 3, 21, 93, 82, 1), (1, 11, 0, 12, 89, 64, 1)]),
    ("lab-ap-03", "AP-505", "LAB0000003", 2, 0, (0, 0), 0,
     [(0, 52, 1, 0, 0, 0, 2), (1, 1, 0, 0, 0, 0, 2)]),
    ("lab-ap-04", "AP-505", "LAB0000004", 1, 4, (280000, 512000), 360000,
     [(0, 100, 0, 17, 95, 12, 1), (1, 6, 0, 0, 0, 0, 2)]),
    ("lab-ap-05", "AP-635", "LAB0000005", 1, 9, (700000, 1024000), 7200000,
     [(0, 44, 1, 19, 92, 31, 1), (1, 1, 0, 11, 88, 47, 1), (2, 197, 3, 20, 96, 8, 1)]),
    ("lab-ap-06", "AP-505", "LAB0000006", 1, 3, (290000, 512000), 9000000, []),
]


def mac(n: int) -> str:
    return f"00005e0053{n:02x}"


def arcs(hex_mac: str) -> str:
    return ".".join(str(int(hex_mac[i:i + 2], 16)) for i in range(0, 12, 2))


def system(name: str, vc_ip: str, version: str | None) -> list[tuple[str, str, str]]:
    rows = [("1.3.6.1.2.1.1.1.0", "4", "Synthetic Aruba Instant lab agent (invented)"),
            ("1.3.6.1.2.1.1.2.0", "6", "1.3.6.1.4.1.14823.1.2.999"),
            ("1.3.6.1.2.1.1.3.0", "67", "8640000"),
            ("1.3.6.1.2.1.1.4.0", "4", "contact-redacted"),
            ("1.3.6.1.2.1.1.5.0", "4", name),
            ("1.3.6.1.2.1.1.6.0", "4", "location-001"),
            (AI + ".1.5.0", "64", vc_ip)]
    if version is not None:
        rows.append((AI + ".1.4.0", "4", version))
    return rows


def controller() -> list[tuple[str, str, str]]:
    rows = system("lab-vc-01", "192.0.2.10", "8.13.2.0")
    for n, (name, model, serial, status, cpu, (free, total), ticks, radios) in enumerate(APS, 1):
        m = mac(n)
        index = arcs(m)
        rows += [(f"{AP}.1.{index}", "4x", m), (f"{AP}.2.{index}", "4", name), (f"{AP}.3.{index}", "64", f"192.0.2.{10 + n}"),
                 (f"{AP}.4.{index}", "4", serial), (f"{AP}.6.{index}", "4", model), (f"{AP}.7.{index}", "2", str(cpu)),
                 (f"{AP}.8.{index}", "2", str(free)), (f"{AP}.9.{index}", "67", str(ticks)),
                 (f"{AP}.10.{index}", "2", str(total)), (f"{AP}.11.{index}", "2", str(status))]
        for radio, channel, bits, power, noise, util, radio_status in radios:
            r = f"{index}.{radio}"
            rows += [(f"{RADIO}.1.{r}", "4x", m), (f"{RADIO}.2.{r}", "2", str(radio)),
                     (f"{RADIO}.3.{r}", "4x", radio_bssid(n, radio)),
                     (f"{RADIO}.4.{r}", "2", str(channel | bits << 8)), (f"{RADIO}.5.{r}", "2", str(power)),
                     (f"{RADIO}.6.{r}", "2", str(noise)), (f"{RADIO}.8.{r}", "2", str(util)),
                     (f"{RADIO}.20.{r}", "2", str(radio_status))]
    # The VC is also an AP: its own detections (lab-ap-02's 5 GHz radio, and the external networks).
    return rows + wlan() + detections([(2, 0, "149")])


# SSID table rows: name, status (0 broadcasting, 1 disabled), client count, hide (0 visible, 1 hidden)
SSIDS = [("Lab-Corp", 0, 5, 0), ("Lab-Event", 0, 0, 0), ("Lab-Guest", 0, 3, 1), ("Lab-Legacy", 1, 0, 0)]
# Clients: AP number (by its address; 0 = an AP address the roster does not hold), radio index (BSSID) or None,
# SNR, seconds connected.
CLIENTS = [(1, 0, 41, 3600), (1, 0, 35, 600), (1, 1, 22, 120), (2, 0, 30, 7200), (2, 1, 18, 60),
           (4, 0, 38, 900), (5, 0, 44, 300), (5, 1, 25, 30), (5, 2, 50, 4000), (0, None, 20, 15)]
# RF detections: BSSID, SSID, channel text, PHY text, encryption, SNR, classification as the AP prints it.
EXTERNAL = [("00:00:5e:00:53:f1", "CoffeeShop", "36", "5GHz-AX-40", "wpa2-psk-aes", 31, "interfering"),
            ("00:00:5e:00:53:f2", "FreeWiFi", "1", "2.4GHz-HT-20", "open", 24, "suspectedUnsecure"),
            ("00:00:5e:00:53:f3", "", "157+", "5GHz-AC-80", "wpa2-8021x-aes", 9, "unknown"),
            ("00:00:5e:00:53:f4", "Neighbour-Office", "11", "2.4GHz", "wpa3-sae-aes", 15, "knownInterfering"),
            ("00:00:5e:00:53:f2", "FreeWiFi", "1", "2.4GHz-HT-20", "open", 11, "suspectedUnsecure")]
INTERFER = AI + ".1.8.1"


def radio_bssid(n: int, radio: int) -> str:
    return f"00005e0053{0x80 + n * 4 + radio:02x}"


def colon(hex_mac: str) -> str:
    return ":".join(hex_mac[i:i + 2] for i in range(0, 12, 2))


def detections(managed: list[tuple[int, int, str]]) -> list[tuple[str, str, str]]:
    """aiInterferAccessPointTable rows: managed (AP number, radio, channel) detections, then the external ones."""
    rows = []
    entries = [(colon(radio_bssid(n, r)), "Lab-Corp", ch, "5GHz-AX-40" if int(ch) > 14 else "2.4GHz-HT-20",
                "wpa2-8021x-aes", 40, "valid") for n, r, ch in managed] + EXTERNAL
    for i, (bssid, ssid, channel, phy, encr, snr, kind) in enumerate(entries):
        rows += [(f"{INTERFER}.1.{i}", "2", str(i)), (f"{INTERFER}.2.{i}", "4x", bssid.replace(":", "")),
                 (f"{INTERFER}.3.{i}", "4", ssid), (f"{INTERFER}.4.{i}", "4", channel),
                 (f"{INTERFER}.5.{i}", "4", phy), (f"{INTERFER}.6.{i}", "4", encr),
                 (f"{INTERFER}.7.{i}", "2", str(snr)), (f"{INTERFER}.8.{i}", "4", kind)]
    return rows


def wlan() -> list[tuple[str, str, str]]:
    rows = []
    for i, (name, status, clients, hide) in enumerate(SSIDS, 1):
        rows += [(f"{AI}.1.7.1.2.{i}", "4", name), (f"{AI}.1.7.1.3.{i}", "2", str(status)),
                 (f"{AI}.1.7.1.4.{i}", "2", str(clients)), (f"{AI}.1.7.1.5.{i}", "2", str(hide))]
    client = AI + ".2.4.1"
    for i, (ap, radio, snr, seconds) in enumerate(CLIENTS, 1):
        cmac = f"00005e0054{i:02x}"
        index = arcs(cmac)
        rows += [(f"{client}.1.{index}", "4x", cmac), (f"{client}.3.{index}", "64", f"198.51.100.{i}"),
                 (f"{client}.4.{index}", "64", f"192.0.2.{10 + ap}" if ap else "192.0.2.99"),
                 (f"{client}.5.{index}", "4", f"client-{i:02d}"), (f"{client}.7.{index}", "2", str(snr)),
                 (f"{client}.16.{index}", "67", str(seconds * 100))]
        if radio is not None:
            rows.append((f"{client}.2.{index}", "4x", radio_bssid(ap, radio)))
    return rows


def member() -> list[tuple[str, str, str]]:
    # A member AP: AI-AP-MIB answers, but the VC address is 0.0.0.0 and the roster tables are empty.
    return system("lab-ap-02", "0.0.0.0", None)


def ap01() -> list[tuple[str, str, str]]:
    """lab-ap-01 at its own address: a member AP whose detections include its neighbours lab-ap-02 and lab-ap-04,
    and whose LLDP names sw-wifi-access-01 Gi1/0/1."""
    a = NE.Agent()
    for oid, tag, value in system("lab-ap-01", "0.0.0.0", None) + detections([(2, 1, "11"), (4, 0, "100"), (5, 0, "44")]):
        a.rows[oid] = (tag, value)
    NE.interface(a, 1, "eth0", "eth0", mac_addr=colon(mac(1)))
    NE.lldp_local(a, 1, "eth0", "eth0")
    NE.lldp_remote(a, 1, 1, chassis=ACCESS1, port="Gi1/0/1", port_desc="lab-ap-01", sys_name="sw-wifi-access-01",
                   address="192.0.2.201", pvid=49)
    return [(oid, tag, value) for oid, (tag, value) in a.rows.items()]


DOT11 = "1.2.840.10036"
# A generic AP's radios: ifIndex, name, dot11PHYType (6 erp, 7 ht), DSSS channel, OFDM channel, current power level
# (of levels in mW), ifOperStatus. Its SSID interfaces: ifIndex, name, SSID, ifAdminStatus.
GENERIC_RADIOS = [(2, "wifi0", 6, 6, None, 2, [100, 50, 25], 1), (3, "wifi1", 7, None, 36, 1, [200, 100], 1)]
GENERIC_SSIDS = [(4, "ath0", "Lab-Corp", 1), (5, "ath1", "Lab-Corp", 1), (6, "ath2", "Lab-Guest", 2)]


def generic_ap(tri: bool = False) -> list[tuple[str, str, str]]:
    """A standalone AP with the standard MIBs only; its identity is eth0's MAC, 00:00:5e:00:53:31."""
    a = NE.Agent()
    a.str("1.3.6.1.2.1.1.1.0", "Synthetic standards-only access point (invented)")
    a.oid("1.3.6.1.2.1.1.2.0", "1.3.6.1.4.1.32473.1.1")
    a.ticks("1.3.6.1.2.1.1.3.0", 8640000)
    a.str("1.3.6.1.2.1.1.5.0", "lab-gap-01")
    a.ticks("1.3.6.1.2.1.25.1.1.0", 17280000)
    NE.interface(a, 1, "eth0", "eth0", mac_addr="00:00:5e:00:53:31")
    radios = GENERIC_RADIOS + ([(7, "wifi2", 7, None, 37, 1, [100], 1)] if tri else [])
    for ix, name, phy, dsss, ofdm, level, levels, oper in radios:
        NE.interface(a, ix, name, name, if_type=71, oper=oper, mac_addr=f"00:00:5e:00:53:{0x30 + ix * 16:02x}")
        a.int(f"{DOT11}.4.1.1.1.{ix}", phy)
        a.hex(f"{DOT11}.2.1.1.1.{ix}", NE.mac(f"00:00:5e:00:53:{0x30 + ix * 16:02x}"))
        a.str(f"{DOT11}.1.1.1.9.{ix}", "")
        a.int(f"{DOT11}.4.3.1.1.{ix}", len(levels))
        for n, mw in enumerate(levels, 1):
            a.int(f"{DOT11}.4.3.1.{n + 1}.{ix}", mw)
        a.int(f"{DOT11}.4.3.1.10.{ix}", level)
        if dsss is not None:
            a.int(f"{DOT11}.4.5.1.1.{ix}", dsss)
        if ofdm is not None:
            a.int(f"{DOT11}.4.11.1.1.{ix}", ofdm)
    for ix, name, ssid, admin in GENERIC_SSIDS:
        NE.interface(a, ix, name, name, if_type=71, admin=admin, oper=admin, mac_addr=f"00:00:5e:00:53:{0x40 + ix:02x}")
        a.str(f"{DOT11}.1.1.1.9.{ix}", ssid)
    a.int("1.3.6.1.2.1.47.1.1.1.1.5.1", 3)
    a.str("1.3.6.1.2.1.47.1.1.1.1.10.1", "1.0.4")
    a.str("1.3.6.1.2.1.47.1.1.1.1.11.1", "LABGAP0001")
    a.str("1.3.6.1.2.1.47.1.1.1.1.13.1", "LAB-AP-STD")
    a.int("1.3.6.1.2.1.25.3.3.1.2.196608", 10)
    a.int("1.3.6.1.2.1.25.3.3.1.2.196609", 20)
    a.oid("1.3.6.1.2.1.25.2.3.1.2.1", "1.3.6.1.2.1.25.2.1.2")
    a.int("1.3.6.1.2.1.25.2.3.1.5.1", 262144)
    a.int("1.3.6.1.2.1.25.2.3.1.6.1", 65536)
    a.oid("1.3.6.1.2.1.25.2.3.1.2.31", "1.3.6.1.2.1.25.2.1.4")
    a.int("1.3.6.1.2.1.25.2.3.1.5.31", 1000)
    a.int("1.3.6.1.2.1.25.2.3.1.6.31", 999)
    for ip in ("127.0.0.1", "192.0.2.30"):
        a.rows[f"1.3.6.1.2.1.4.20.1.1.{ip}"] = ("64", ip)
    return agent_rows(a)


DIST = "00:00:5e:00:53:c0"
ACCESS1 = "00:00:5e:00:53:c1"
ACCESS2 = "00:00:5e:00:53:c2"
ROOT = (4096).to_bytes(2, "big") + NE.mac(DIST)


def bridge(a, own: str, priority: int, root_cost: int, root_port: int) -> None:
    a.hex("1.3.6.1.2.1.17.1.1.0", NE.mac(own))
    a.int("1.3.6.1.2.1.17.2.1.0", 3)
    a.int("1.3.6.1.2.1.17.2.2.0", priority)
    a.ticks("1.3.6.1.2.1.17.2.3.0", 720_000)
    a.int("1.3.6.1.2.1.17.2.4.0", 2)
    a.hex("1.3.6.1.2.1.17.2.5.0", ROOT)
    a.int("1.3.6.1.2.1.17.2.6.0", root_cost)
    a.int("1.3.6.1.2.1.17.2.7.0", root_port)
    a.int("1.3.6.1.2.1.17.2.16.0", 2)


def stp(a, port: int, state: int, cost: int, designated: bytes, designated_port: int, edge: bool = False) -> None:
    a.int(f"1.3.6.1.2.1.17.2.15.1.1.{port}", port)
    a.int(f"1.3.6.1.2.1.17.2.15.1.2.{port}", 128)
    a.int(f"1.3.6.1.2.1.17.2.15.1.3.{port}", state)
    a.int(f"1.3.6.1.2.1.17.2.15.1.4.{port}", 1)
    a.int(f"1.3.6.1.2.1.17.2.15.1.5.{port}", cost)
    a.hex(f"1.3.6.1.2.1.17.2.15.1.6.{port}", ROOT)
    a.int(f"1.3.6.1.2.1.17.2.15.1.7.{port}", 2000)
    a.hex(f"1.3.6.1.2.1.17.2.15.1.8.{port}", designated)
    a.hex(f"1.3.6.1.2.1.17.2.15.1.9.{port}", (0x8000 | designated_port).to_bytes(2, "big"))
    a.int(f"1.3.6.1.2.1.17.2.15.1.11.{port}", cost)
    a.int(f"1.3.6.1.2.1.17.2.19.1.3.{port}", 1 if edge else 2)
    a.int(f"1.3.6.1.2.1.17.2.19.1.5.{port}", 1)


def lacp(a, aggregator: int, own: str, partner: str, members: list[tuple[int, int]]) -> None:
    a.hex(f"1.2.840.10006.300.43.1.1.1.1.4.{aggregator}", NE.mac(own))
    a.int(f"1.2.840.10006.300.43.1.1.1.1.5.{aggregator}", 1)
    a.hex(f"1.2.840.10006.300.43.1.1.1.1.8.{aggregator}", NE.mac(partner))
    for member, partner_port in members:
        a.int(f"1.2.840.10006.300.43.1.2.1.1.12.{member}", aggregator)
        a.int(f"1.2.840.10006.300.43.1.2.1.1.13.{member}", aggregator)
        a.int(f"1.2.840.10006.300.43.1.2.1.1.17.{member}", partner_port)
        a.hex(f"1.2.840.10006.300.43.1.2.1.1.21.{member}", bytes([0xBC]))


def ap_link(a, port: int, n: int) -> None:
    NE.lldp_remote(a, port, 1, chassis=colon(mac(n)), port="eth0", port_desc="eth0", sys_name=f"lab-ap-{n:02d}",
                   address=f"192.0.2.{10 + n}", pvid=49)


def dist() -> NE.Agent:
    a = NE.Agent()
    NE.system(a, "sw-wifi-dist-01", "Synthetic switch OS 1.2.3, distribution", DIST, "192.0.2.200", "SYN-8X", "SYNWDIST01")
    a.int("1.3.6.1.2.1.2.1.0", 4)
    for ix, name in ((1, "Te1/0/1"), (2, "Te1/0/2")):
        NE.interface(a, ix, name, name.replace("Te", "TenGigabitEthernet"), high_speed=NE.SPEED_10G,
                     mac_addr=f"00:00:5e:00:53:{0xd0 + ix:02x}", alias="Po1 member")
        NE.lldp_local(a, ix, name, name)
        NE.lldp_remote(a, ix, 1, chassis=ACCESS1, port=f"Te1/0/{ix}", port_desc="Po1 member",
                       sys_name="sw-wifi-access-01", address="192.0.2.201", aggregated_port=1001, pvid=1)
    NE.interface(a, 3, "Gi1/0/3", "GigabitEthernet1/0/3", mac_addr="00:00:5e:00:53:d3", alias="To access-02")
    NE.lldp_local(a, 3, "Gi1/0/3", "GigabitEthernet1/0/3")
    NE.lldp_remote(a, 3, 1, chassis=ACCESS2, port="Gi1/0/24", port_desc="Uplink", sys_name="sw-wifi-access-02",
                   address="192.0.2.202", pvid=1)
    NE.interface(a, 1001, "Po1", "Port-channel1", if_type=161, high_speed=20000, duplex=None, connector=2,
                 mac_addr=DIST, alias="To access-01")
    for member in (1, 2):
        a.int(f"1.3.6.1.2.1.31.1.2.1.3.1001.{member}", 1)
    a.int("1.3.6.1.2.1.17.1.4.1.2.3", 3)
    a.int("1.3.6.1.2.1.17.1.4.1.2.10", 1001)
    # Po1 (bridge port 10) carries 49 and 56 but not 57; Gi1/0/3 carries all three.
    NE.vlans(a, {1: ("default", [3, 10], [3, 10], []), 49: ("AP management", [3, 10], [], []),
                 56: ("Event", [3, 10], [], []), 57: ("Guest", [3], [], [])}, {3: 1, 10: 1}, size=2)
    bridge(a, DIST, 4096, 0, 0)
    for port in (3, 10):
        stp(a, port, 5, 2000, ROOT, port)
    lacp(a, 1001, DIST, ACCESS1, [(1, 1), (2, 2)])
    return a


def access1() -> NE.Agent:
    a = NE.Agent()
    NE.system(a, "sw-wifi-access-01", "Synthetic switch OS 1.2.3, 24-port", ACCESS1, "192.0.2.201", "SYN-24T-2X",
              "SYNWACC001")
    a.int("1.3.6.1.2.1.2.1.0", 6)
    for ix in (1, 2, 3):
        NE.interface(a, ix, f"Gi1/0/{ix}", f"GigabitEthernet1/0/{ix}", oper=2 if ix == 3 else 1,
                     mac_addr=f"00:00:5e:00:53:{0xe0 + ix:02x}", alias=f"lab-ap-{ix:02d}")
        NE.lldp_local(a, ix, f"Gi1/0/{ix}", f"GigabitEthernet1/0/{ix}")
        a.int(f"1.3.6.1.2.1.17.1.4.1.2.{ix}", ix)
    for ix, n in ((25, 1), (26, 2)):
        NE.interface(a, ix, f"Te1/0/{n}", f"TenGigabitEthernet1/0/{n}", high_speed=NE.SPEED_10G,
                     mac_addr=f"00:00:5e:00:53:{0xe8 + n:02x}", alias="Po1 member")
        NE.lldp_local(a, ix, f"Te1/0/{n}", f"TenGigabitEthernet1/0/{n}")
        NE.lldp_remote(a, ix, 1, chassis=DIST, port=f"Te1/0/{n}", port_desc="Po1 member", sys_name="sw-wifi-dist-01",
                       address="192.0.2.200", aggregated_port=1001, pvid=1)
    NE.interface(a, 1001, "Po1", "Port-channel1", if_type=161, high_speed=20000, duplex=None, connector=2,
                 mac_addr=ACCESS1, alias="To dist")
    for member in (25, 26):
        a.int(f"1.3.6.1.2.1.31.1.2.1.3.1001.{member}", 1)
    a.int("1.3.6.1.2.1.17.1.4.1.2.10", 1001)
    ap_link(a, 1, 1)
    ap_link(a, 2, 2)
    # AP ports: native 49, tagged 56 and 57. Po1 (bridge port 10) trunks 49, 56 and 57.
    NE.vlans(a, {1: ("default", [10], [10], []), 49: ("AP management", [1, 2, 3, 10], [1, 2, 3], []),
                 56: ("Event", [1, 2, 3, 10], [], []), 57: ("Guest", [1, 2, 3, 10], [], [])},
             {1: 49, 2: 49, 3: 49, 10: 1}, size=2)
    own = (32768).to_bytes(2, "big") + NE.mac(ACCESS1)
    bridge(a, ACCESS1, 32768, 2000, 10)
    for port in (1, 2):
        stp(a, port, 5, 20000, own, port, edge=True)
    stp(a, 10, 5, 2000, ROOT, 10)
    lacp(a, 1001, ACCESS1, DIST, [(25, 1), (26, 2)])
    return a


def access2() -> NE.Agent:
    a = NE.Agent()
    NE.system(a, "sw-wifi-access-02", "Synthetic switch OS 1.2.3, 24-port", ACCESS2, "192.0.2.202", "SYN-24T",
              "SYNWACC002")
    a.int("1.3.6.1.2.1.2.1.0", 3)
    for ix in (1, 2, 24):
        NE.interface(a, ix, f"Gi1/0/{ix}", f"GigabitEthernet1/0/{ix}", mac_addr=f"00:00:5e:00:53:{0xf0 + ix % 16:02x}",
                     alias={1: "lab-ap-04", 2: "lab-ap-05", 24: "Uplink"}[ix])
        NE.lldp_local(a, ix, f"Gi1/0/{ix}", f"GigabitEthernet1/0/{ix}")
        a.int(f"1.3.6.1.2.1.17.1.4.1.2.{ix}", ix)
    ap_link(a, 1, 4)
    ap_link(a, 2, 5)
    NE.lldp_remote(a, 24, 1, chassis=DIST, port="Gi1/0/3", port_desc="To access-02", sys_name="sw-wifi-dist-01",
                   address="192.0.2.200", pvid=1)
    # lab-ap-04's port carries 57 but not 56.
    NE.vlans(a, {1: ("default", [24], [24], []), 49: ("AP management", [1, 2, 24], [1, 2], []),
                 56: ("Event", [2, 24], [], []), 57: ("Guest", [1, 2, 24], [], [])}, {1: 49, 2: 49, 24: 1}, size=3)
    own = (32768).to_bytes(2, "big") + NE.mac(ACCESS2)
    bridge(a, ACCESS2, 32768, 2000, 24)
    for port in (1, 2):
        stp(a, port, 5, 20000, own, port, edge=True)
    stp(a, 24, 5, 2000, ROOT, 3)
    return a


def agent_rows(agent: NE.Agent) -> list[tuple[str, str, str]]:
    return [(oid, tag, value) for oid, (tag, value) in agent.rows.items()]


def key(oid: str) -> tuple[int, ...]:
    return tuple(int(part) for part in oid.split("."))


def render(rows: list[tuple[str, str, str]]) -> str:
    return "".join(f"{oid}|{tag}|{value}\n" for oid, tag, value in sorted(rows, key=lambda r: key(r[0])))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if a committed walk differs")
    args = parser.parse_args()
    outputs = {HERE / "aruba-instant-vc.snmprec": render(controller()),
               HERE / "aruba-instant-member.snmprec": render(member()),
               HERE / "aruba-instant-ap-01.snmprec": render(ap01()),
               HERE / "generic-ap.snmprec": render(generic_ap()),
               HERE / "generic-ap-tri.snmprec": render(generic_ap(tri=True)),
               HERE / "sw-wifi-dist-01.snmprec": render(agent_rows(dist())),
               HERE / "sw-wifi-access-01.snmprec": render(agent_rows(access1())),
               HERE / "sw-wifi-access-02.snmprec": render(agent_rows(access2()))}
    for path, text in outputs.items():
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                raise SystemExit(f"Synthetic walk differs: {path}")
        else:
            path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
