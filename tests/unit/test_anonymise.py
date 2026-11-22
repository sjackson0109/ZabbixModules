"""anonymise.py: public evidence keeps its joins and loses every real asset detail."""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "qualification"))

import anonymise  # noqa: E402
import qualify  # noqa: E402

REM = "1.0.8802.1.1.2.1.4.1.1."
LOC_CHASSIS = [("1.0.8802.1.1.2.1.3.1.0", "2", "4")]


def run(tmp_path, walk, config=None, places=None):
    places = places or anonymise.Placeholders(tmp_path / "map.json")
    macs = anonymise.Macs(places, anonymise.mac_values(walk))
    return anonymise.anonymise_walk(walk, places, macs, config or {}, Counter()), places


def values(walk):
    return {oid: value for oid, _, value in walk}


def test_the_same_mac_gets_the_same_placeholder_in_every_walk(tmp_path):
    """Switch A's own chassis ID is what switch B sees as its LLDP neighbour: both must still match."""
    a = LOC_CHASSIS + [("1.0.8802.1.1.2.1.3.2.0", "4x", "00005e005301")]
    b = [(REM + "4.0.1.1", "2", "4"), (REM + "5.0.1.1", "4x", "00005e005301")]
    places = anonymise.Placeholders(tmp_path / "map.json")
    macs = anonymise.Macs(places, anonymise.mac_values(a) | anonymise.mac_values(b))
    out_a = values(anonymise.anonymise_walk(a, places, macs, {}, Counter()))
    out_b = values(anonymise.anonymise_walk(b, places, macs, {}, Counter()))
    assert out_a["1.0.8802.1.1.2.1.3.2.0"] == out_b[REM + "5.0.1.1"] != "00005e005301"
    assert out_a["1.0.8802.1.1.2.1.3.2.0"].startswith("0200")


def test_bitmaps_and_protocol_ids_are_not_mistaken_for_macs(tmp_path):
    """Regression: six- and eight-octet values that are not MACs must come through byte for byte."""
    walk = [("1.3.6.1.2.1.2.2.1.6.1", "4x", "00005e005301"),
            ("1.3.6.1.2.1.17.7.1.4.3.1.2.10", "4x", "00005e005301"),             # PortList equal to a MAC
            ("1.3.6.1.2.1.17.7.1.4.3.1.4.10", "4x", "ff00005e00530100"),         # PortList containing one
            ("1.0.8802.1.1.2.1.5.32962.1.2.4.1.1.1", "4x", "0026424203000000"),  # protocol identity
            ("1.3.6.1.2.1.17.2.5.0", "4x", "800000005e005301")]                  # bridge ID: priority + MAC
    out, _ = run(tmp_path, walk)
    v = values(out)
    assert v["1.3.6.1.2.1.17.7.1.4.3.1.2.10"] == "00005e005301"
    assert v["1.3.6.1.2.1.17.7.1.4.3.1.4.10"] == "ff00005e00530100"
    assert v["1.0.8802.1.1.2.1.5.32962.1.2.4.1.1.1"] == "0026424203000000"
    assert v["1.3.6.1.2.1.17.2.5.0"] == "8000" + v["1.3.6.1.2.1.2.2.1.6.1"]


def test_macs_written_as_text_are_replaced(tmp_path):
    walk = [("1.3.6.1.2.1.2.2.1.6.1", "4x", "00005e0053a1"),
            ("1.3.6.1.2.1.17.2.15.1.6.1", "4", "32768-00.00.5e.00.53.a1"),     # CBS220 text bridge ID
            ("1.3.6.1.2.1.17.2.5.0", "4", "24576/00:00:5E:00:53:A1"),
            ("1.3.6.1.4.1.9.6.1.101.1.21.0", "4", "switch0053a1")]             # Cisco SB default host name
    out, places = run(tmp_path, walk)
    fake = places.data["mac"]["00005e0053a1"]
    v = values(out)
    assert v["1.3.6.1.2.1.17.2.15.1.6.1"] == "32768-" + ".".join(fake[i:i + 2] for i in range(0, 12, 2))
    assert v["1.3.6.1.2.1.17.2.5.0"] == "24576/" + ":".join(fake[i:i + 2] for i in range(0, 12, 2)).upper()
    assert v["1.3.6.1.4.1.9.6.1.101.1.21.0"] == "switch" + fake[-6:]


def test_serials_are_replaced_everywhere_but_a_model_name_is_not(tmp_path):
    gen = "1.3.6.1.4.1.9.6.1.101.53.14.1."
    walk = [(gen + "5.1", "4", "TST0000001X"), (gen + "7.1", "4", "C1200-24P-4X"), (gen + "11.1", "4", "C1200-24P-4X"),
            ("1.0.8802.1.1.2.1.5.1.1.2.5.0", "4", "TST0000001X"), ("1.3.6.1.2.1.1.1.0", "4", "C1200-24P-4X switch")]
    v = values(run(tmp_path, walk)[0])
    assert v[gen + "5.1"] == v["1.0.8802.1.1.2.1.5.1.1.2.5.0"] == "SERIAL-9001"
    assert v[gen + "7.1"] == "C1200-24P-4X" and v["1.3.6.1.2.1.1.1.0"] == "C1200-24P-4X switch"


def test_neighbour_details_are_replaced_but_interface_names_are_kept(tmp_path):
    walk = [(REM + "6.0.1.1", "2", "5"), (REM + "7.0.1.1", "4", "gi1/0/16"),
            (REM + "6.0.2.1", "2", "7"), (REM + "7.0.2.1", "4", "PCIDEV01 NIC Slot(01) Port(01)"),
            (REM + "6.0.3.1", "2", "7"), (REM + "7.0.3.1", "4", "ABC1234 Dedicated"),
            (REM + "8.0.1.1", "4", "port 22 on vSwitch example"), (REM + "10.0.1.1", "4", "VMware ESXi Releasebuild-1"),
            (REM + "10.0.2.1", "4", ""),
            ("1.0.8802.1.1.2.1.4.4.1.4.0.3.1.0.18.15.1.1", "4", "ExampleServer 1000"),
            ("1.3.6.1.2.1.17.7.1.4.3.1.1.20", "4", "Tenant-Guest"), ("1.3.6.1.2.1.17.7.1.4.3.1.1.1", "4", "default"),
            ("1.3.6.1.2.1.105.1.1.1.9.1.3", "4", "Lobby-AP02")]
    v = values(run(tmp_path, walk)[0])
    assert v[REM + "7.0.1.1"] == "gi1/0/16"
    assert v[REM + "7.0.2.1"].startswith("port-") and v[REM + "7.0.3.1"].startswith("port-")
    assert v[REM + "8.0.1.1"].startswith("portdesc-") and v[REM + "10.0.1.1"].startswith("sysdesc-")
    assert v[REM + "10.0.2.1"] == "" and v["1.0.8802.1.1.2.1.4.4.1.4.0.3.1.0.18.15.1.1"].startswith("orgdef-")
    assert v["1.3.6.1.2.1.17.7.1.4.3.1.1.20"] == "VLAN0020" and v["1.3.6.1.2.1.17.7.1.4.3.1.1.1"] == "default"
    assert v["1.3.6.1.2.1.105.1.1.1.9.1.3"] == "label-001"
    assert qualify.check_walk(run(tmp_path, walk)[0])[0] == []


def test_uptime_is_hidden_and_time_marks_keep_their_joins(tmp_path):
    day = 8_640_000
    walk = [("1.3.6.1.2.1.1.3.0", "67", str(400 * day)),
            ("1.3.6.1.2.1.2.2.1.9.1", "67", str(400 * day - 3600 * 100)),       # an hour ago
            ("1.3.6.1.2.1.2.2.1.9.2", "67", str(10 * day)),                      # 390 days ago
            ("1.3.6.1.2.1.2.2.1.9.3", "67", "0"),
            ("1.3.6.1.2.1.17.2.3.0", "67", str(30 * day)),                       # a duration
            (REM + "9." + str(400 * day - 100) + ".7.1", "4", "device-001"),
            ("1.0.8802.1.1.2.1.4.2.1.3." + str(400 * day - 100) + ".7.1.1.4.192.0.2.9", "2", "2")]
    v = values(run(tmp_path, walk)[0])
    assert v["1.3.6.1.2.1.1.3.0"] == str(anonymise.UPTIME)
    assert v["1.3.6.1.2.1.2.2.1.9.1"] == str(anonymise.UPTIME - 3600 * 100)
    assert v["1.3.6.1.2.1.2.2.1.9.2"] == "0" and v["1.3.6.1.2.1.2.2.1.9.3"] == "0"
    assert v["1.3.6.1.2.1.17.2.3.0"] == str(anonymise.UPTIME)
    mark = str(anonymise.UPTIME - 100)
    assert REM + f"9.{mark}.7.1" in v and f"1.0.8802.1.1.2.1.4.2.1.3.{mark}.7.1.1.4.192.0.2.9" in v


def test_a_real_address_in_the_lldp_config_index_becomes_the_sanitised_management_address(tmp_path):
    """Regression: captures sanitised before capture_walk.py covered lldpConfigManAddrTable kept the real address."""
    walk = [("1.0.8802.1.1.2.1.1.7.1.1.1.4.10.0.0.5", "4x", "00"),
            ("1.0.8802.1.1.2.1.3.8.1.3.1.4.192.0.2.7", "2", "2")]
    oids = [o for o, _, _ in run(tmp_path, walk)[0]]
    assert "1.0.8802.1.1.2.1.1.7.1.1.1.4.192.0.2.7" in oids and not any("10.0.0.5" in o for o in oids)
    assert qualify.check_walk(run(tmp_path, walk)[0])[0] == []
    errors = qualify.check_walk(walk)[0]
    assert errors == ["1.0.8802.1.1.2.1.1.7.1.1.1.4.10.0.0.5: LLDP management-address index holds 10.0.0.5,"
                      " not a documentation address"]


def test_the_end_device_table_is_dropped_and_the_manifest_is_cleaned(tmp_path):
    walk = [("1.3.6.1.2.1.17.7.1.2.2.1.2.1.0.17.34.51.68.85", "2", "3"), ("1.3.6.1.2.1.17.7.1.4.3.1.1.1", "4", "default")]
    out, _ = run(tmp_path, walk)
    assert [o for o, _, _ in out] == ["1.3.6.1.2.1.17.7.1.4.3.1.1.1"]
    manifest = anonymise.anonymise_manifest({"net_snmp_version": "5.9", "record_count": 2,
                                             "subtrees": [{"oid": "1.3.6.1.2.1.17.7.1", "records": 2}]},
                                            out, anonymise.RULES)
    assert "net_snmp_version" not in manifest and manifest["record_count"] == 1
    assert manifest["subtrees"][0]["records"] == 1 and manifest["anonymised"]["version"] == anonymise.FORMAT_VERSION


def test_estate_rules_come_from_the_private_config(tmp_path):
    walk = [("1.3.6.1.2.1.1.9.1.3.1", "4", "Uplink to SITE-CORE-01"),
            ("1.3.6.1.4.1.9.6.1.101.108.2.1.2.1", "4x", "392e392e302e31000000")]   # "9.9.0.1" + padding
    config = {"name_patterns": [r"\bSITE-[A-Z0-9-]+"],
              "version_masks": {"1.3.6.1.4.1.9.6.1.101.108.2.1.2.": ["9.9.0.1"]}}
    v = values(run(tmp_path, walk, config)[0])
    assert v["1.3.6.1.2.1.1.9.1.3.1"] == "Uplink to name-001"
    assert bytes.fromhex(v["1.3.6.1.4.1.9.6.1.101.108.2.1.2.1"]).startswith(b"x.x.x.x")


def test_the_private_map_is_reused_across_runs(tmp_path):
    walk = [("1.3.6.1.2.1.2.2.1.6.1", "4x", "00005e005301")]
    _, places = run(tmp_path, walk)
    places.save()
    again = anonymise.Placeholders(tmp_path / "map.json")
    assert values(run(tmp_path, walk, places=again)[0]) == values(run(tmp_path, walk)[0])
    assert json.loads((tmp_path / "map.json").read_text())["mac"]["00005e005301"].startswith("0200")
