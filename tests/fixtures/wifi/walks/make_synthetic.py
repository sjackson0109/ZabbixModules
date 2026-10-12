#!/usr/bin/env python3
"""Write the invented Aruba Instant walks used by the Wi-Fi Explorer tests (snmpsim .snmprec).

Every value is invented: documentation addresses (192.0.2.0/24), documentation MAC addresses (00:00:5e:00:53:xx,
RFC 7042) and lab names. The layout follows AI-AP-MIB as the operator's Aruba template records it
(docs/wifi-explorer/ARUBA_TEMPLATE_REVIEW.md). These walks qualify the parsers only, never Aruba hardware.

  python3 tests/fixtures/wifi/walks/make_synthetic.py [--check]
"""
from __future__ import annotations

import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
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
                     (f"{RADIO}.3.{r}", "4x", f"00005e0053{0x80 + n * 4 + radio:02x}"),
                     (f"{RADIO}.4.{r}", "2", str(channel | bits << 8)), (f"{RADIO}.5.{r}", "2", str(power)),
                     (f"{RADIO}.6.{r}", "2", str(noise)), (f"{RADIO}.8.{r}", "2", str(util)),
                     (f"{RADIO}.20.{r}", "2", str(radio_status))]
    return rows


def member() -> list[tuple[str, str, str]]:
    # A member AP: AI-AP-MIB answers, but the VC address is 0.0.0.0 and the roster tables are empty.
    return system("lab-ap-02", "0.0.0.0", None)


def key(oid: str) -> tuple[int, ...]:
    return tuple(int(part) for part in oid.split("."))


def render(rows: list[tuple[str, str, str]]) -> str:
    return "".join(f"{oid}|{tag}|{value}\n" for oid, tag, value in sorted(rows, key=lambda r: key(r[0])))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if a committed walk differs")
    args = parser.parse_args()
    outputs = {HERE / "aruba-instant-vc.snmprec": render(controller()),
               HERE / "aruba-instant-member.snmprec": render(member())}
    for path, text in outputs.items():
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                raise SystemExit(f"Synthetic walk differs: {path}")
        else:
            path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
