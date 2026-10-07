"""snmpbulkwalk capture wrapper: parser, snmprec rendering, sanitiser and mocked runs."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "inventory"))

import capture_walk as cw  # noqa: E402

COMMUNITY = "s3cr3t-Community!"

SAMPLE = "\n".join([
    ".1.3.6.1.2.1.1.1.0 = Hex-STRING: 43 69 73 63 6F 20 49 4F 53 20 53 6F 66 74 77 61 ",
    "72 65 2C 20 56 65 72 73 69 6F 6E 20 31 35 2E 32 ",
    "28 37 29 45 38 ",
    ".1.3.6.1.2.1.1.2.0 = OID: .1.3.6.1.4.1.9.1.1208",
    ".1.3.6.1.2.1.1.3.0 = Timeticks: (123456) 0:20:34.56",
    ".1.3.6.1.2.1.1.4.0 = STRING: \"ops \\\"team\\\" @ example\"",
    ".1.3.6.1.2.1.1.5.0 = STRING: \"line one",
    "line two = still the string\"",
    ".1.3.6.1.2.1.1.7.0 = INTEGER: 6",
    ".1.3.6.1.2.1.1.8.0 = 42",
    ".1.3.6.1.2.1.2.2.1.6.1 = \"\"",
    ".1.3.6.1.2.1.2.2.1.7.1 = INTEGER: up(1)",
    ".1.3.6.1.2.1.2.2.1.5.1 = Gauge32: 1000000000",
    ".1.3.6.1.2.1.2.2.1.10.1 = Counter32: 4294967295",
    ".1.3.6.1.2.1.31.1.1.1.6.1 = Counter64: 18446744073709551615",
    ".1.3.6.1.2.1.31.1.1.1.15.1 = Gauge32: 1000 Mbps",
    ".1.3.6.1.2.1.4.20.1.1.10.1.2.3 = IpAddress: 10.1.2.3",
    ".1.3.6.1.2.1.17.7.1.4.3.1.2.10 = BITS: 80 00 01 port1(0)",
    ".1.3.6.1.2.1.99.1.1.1.4.1 = Wrong Type (should be INTEGER): Gauge32: 7",
    ".1.3.6.1.2.1.105.1.1.1.3.1.1 = UInteger32: 3",
    ".1.3.6.1.2.1.1.9.1.4.1 = NULL",
    ".1.3.6.1.2.1.1.9.1.5.1 = Opaque: Float: 1.5",
    ".1.3.6.1.2.1.1.9.1.6.1 = Network Address: 0A:00:00:01",
    "",
])


def records_by_oid(records):
    return {record.oid: record for record in records}


def test_parser_handles_every_value_type():
    result = cw.parse_walk_output(SAMPLE)
    values = {r.oid: (r.tag, r.value) for r in result.records}
    assert values["1.3.6.1.2.1.1.1.0"] == ("4", b"Cisco IOS Software, Version 15.2(7)E8")
    assert values["1.3.6.1.2.1.1.2.0"] == ("6", "1.3.6.1.4.1.9.1.1208")
    assert values["1.3.6.1.2.1.1.3.0"] == ("67", 123456)
    assert values["1.3.6.1.2.1.1.4.0"] == ("4", b'ops "team" @ example')
    assert values["1.3.6.1.2.1.1.5.0"] == ("4", b"line one\nline two = still the string")
    assert values["1.3.6.1.2.1.1.7.0"] == ("2", 6)
    assert values["1.3.6.1.2.1.1.8.0"] == ("67", 42)           # -Ot bare TimeTicks
    assert values["1.3.6.1.2.1.2.2.1.6.1"] == ("4", b"")
    assert values["1.3.6.1.2.1.2.2.1.7.1"] == ("2", 1)
    assert values["1.3.6.1.2.1.2.2.1.5.1"] == ("66", 1000000000)
    assert values["1.3.6.1.2.1.2.2.1.10.1"] == ("65", 4294967295)
    assert values["1.3.6.1.2.1.31.1.1.1.6.1"] == ("70", 18446744073709551615)
    assert values["1.3.6.1.2.1.31.1.1.1.15.1"] == ("66", 1000)
    assert values["1.3.6.1.2.1.4.20.1.1.10.1.2.3"] == ("64", "10.1.2.3")
    assert values["1.3.6.1.2.1.17.7.1.4.3.1.2.10"] == ("4", b"\x80\x00\x01")
    assert values["1.3.6.1.2.1.99.1.1.1.4.1"] == ("66", 7)
    assert values["1.3.6.1.2.1.105.1.1.1.3.1.1"] == ("66", 3)
    assert values["1.3.6.1.2.1.1.9.1.4.1"] == ("5", None)
    assert values["1.3.6.1.2.1.1.9.1.6.1"] == ("64", "10.0.0.1")
    assert "1.3.6.1.2.1.1.9.1.5.1" not in values
    assert len(result.skipped) == 1 and "Opaque" in result.skipped[0]
    assert result.absent is False


@pytest.mark.parametrize("line", [
    ".1.0.8802.1.1.2.1 = No Such Object available on this agent at this OID",
    ".1.3.6.1.2.1.1.99.0 = No Such Instance currently exists at this OID",
    ".1.3.6.1.2.1.105 = No more variables left in this MIB View (It is past the end of the MIB tree)",
])
def test_parser_reports_absent_subtrees(line):
    result = cw.parse_walk_output(line + "\n")
    assert result.records == [] and result.absent is True


def test_parser_ignores_non_varbind_noise():
    result = cw.parse_walk_output("Created directory: /tmp/x\n.1.3.6.1.2.1.1.7.0 = INTEGER: 72\n")
    assert [(r.oid, r.value) for r in result.records] == [("1.3.6.1.2.1.1.7.0", 72)]


def test_snmprec_rendering_and_order():
    records = [
        cw.Record("1.3.6.1.2.1.2.2.1.10.1", "65", 5),
        cw.Record("1.3.6.1.2.1.1.9.1.4.1", "5", None),
        cw.Record("1.3.6.1.2.1.1.5.0", "4", b"sw1"),
        cw.Record("1.3.6.1.2.1.1.1.0", "4", b"a|b"),
        cw.Record("1.3.6.1.2.1.2.2.1.6.1", "4", b"\x00\x11\x22\x33\x44\x55"),
        cw.Record("1.3.6.1.2.1.1.2.0", "6", "1.3.6.1.4.1.9.1.1"),
        cw.Record("1.3.6.1.2.1.2.2.1.2.10", "4", b" padded "),
        cw.Record("1.3.6.1.2.1.2.2.1.2.9", "4", b""),
    ]
    assert cw.render_snmprec(records).splitlines() == [
        "1.3.6.1.2.1.1.1.0|4x|617c62",
        "1.3.6.1.2.1.1.2.0|6|1.3.6.1.4.1.9.1.1",
        "1.3.6.1.2.1.1.5.0|4|sw1",
        "1.3.6.1.2.1.1.9.1.4.1|5|",
        "1.3.6.1.2.1.2.2.1.2.9|4|",
        "1.3.6.1.2.1.2.2.1.2.10|4x|2070616464656420",
        "1.3.6.1.2.1.2.2.1.6.1|4x|001122334455",
        "1.3.6.1.2.1.2.2.1.10.1|65|5",
    ]


LLDP_REM = "1.0.8802.1.1.2.1.4.1.1"


def sanitiser_input():
    return [
        cw.Record("1.3.6.1.2.1.1.5.0", "4", b"core-sw1"),
        cw.Record("1.3.6.1.2.1.1.6.0", "4", b"Building 7, Rack 4"),
        cw.Record("1.3.6.1.2.1.1.4.0", "4", b"noc@example.com"),
        cw.Record("1.0.8802.1.1.2.1.3.3.0", "4", b"core-sw1"),
        cw.Record(f"{LLDP_REM}.9.0.5.1", "4", b"dist-sw1"),
        cw.Record(f"{LLDP_REM}.9.0.6.2", "4", b"core-sw1"),
        cw.Record(f"{LLDP_REM}.4.0.5.1", "2", 5),
        cw.Record(f"{LLDP_REM}.5.0.5.1", "4", bytes([1, 10, 20, 30, 40])),
        cw.Record(f"{LLDP_REM}.4.0.6.2", "2", 4),
        cw.Record(f"{LLDP_REM}.5.0.6.2", "4", bytes([1, 0, 0x11, 0x22, 0x33])),   # MAC-like, subtype 4
        cw.Record("1.0.8802.1.1.2.1.4.2.1.3.0.5.1.1.4.10.20.30.40", "2", 2),
        cw.Record("1.0.8802.1.1.2.1.3.8.1.3.1.4.10.0.0.1", "2", 2),
        cw.Record("1.3.6.1.2.1.4.20.1.1.10.0.0.1", "64", "10.0.0.1"),
        cw.Record("1.3.6.1.2.1.4.20.1.3.10.0.0.1", "64", "255.255.255.0"),
        cw.Record("1.3.6.1.2.1.4.20.1.1.127.0.0.1", "64", "127.0.0.1"),
        cw.Record("1.3.6.1.2.1.47.1.1.1.1.11.1", "4", b"FOC1234X0YZ"),
        cw.Record("1.3.6.1.2.1.47.1.1.1.1.11.2", "4", b""),
        cw.Record("1.3.6.1.2.1.31.1.1.1.18.1", "4", b"Uplink to ACME Corp"),
    ]


def test_sanitiser_replaces_identifiers_consistently():
    output = records_by_oid(cw.Sanitiser(serials=True).apply(sanitiser_input()))
    # Placeholders follow OID order: lldpLocSysName (1.0.8802...) is seen first.
    assert output["1.3.6.1.2.1.1.5.0"].value == b"device-001"            # same as lldpLocSysName
    assert output["1.0.8802.1.1.2.1.3.3.0"].value == b"device-001"
    assert output[f"{LLDP_REM}.9.0.5.1"].value == b"device-002"
    assert output[f"{LLDP_REM}.9.0.6.2"].value == b"device-001"
    assert output["1.3.6.1.2.1.1.6.0"].value == b"location-001"
    assert output["1.3.6.1.2.1.1.4.0"].value == b"contact-redacted"
    # The chassis-id address, man-addr index and IpAddress values share one mapping.
    chassis = output[f"{LLDP_REM}.5.0.5.1"].value
    assert chassis[0] == 1 and bytes(chassis[1:]) != bytes([10, 20, 30, 40])
    mapped = ".".join(str(b) for b in chassis[1:])
    assert f"1.0.8802.1.1.2.1.4.2.1.3.0.5.1.1.4.{mapped}" in output
    assert output["1.3.6.1.2.1.4.20.1.1.10.0.0.1"].value == "192.0.2.1"
    assert "1.0.8802.1.1.2.1.3.8.1.3.1.4.192.0.2.1" in output
    assert mapped == "192.0.2.2"
    assert output[f"{LLDP_REM}.5.0.6.2"].value == bytes([1, 0, 0x11, 0x22, 0x33])   # not networkAddress
    assert output["1.3.6.1.2.1.4.20.1.3.10.0.0.1"].value == "255.255.255.0"      # mask kept
    assert output["1.3.6.1.2.1.4.20.1.1.127.0.0.1"].value == "127.0.0.1"
    assert output["1.3.6.1.2.1.47.1.1.1.1.11.1"].value == b"SERIAL-0001"
    assert output["1.3.6.1.2.1.47.1.1.1.1.11.2"].value == b""
    assert output["1.3.6.1.2.1.31.1.1.1.18.1"].value == b"Uplink to ACME Corp"   # aliases off
    rendered = cw.render_snmprec(output.values())
    for original in ("core-sw1", "dist-sw1", "10.20.30.40", "|10.0.0.1", "FOC1234", "noc@", "Building"):
        assert original not in rendered
    # Documented limit: addresses inside non-LLDP indexes (ipAddrTable here) are kept.
    assert "1.3.6.1.2.1.4.20.1.1.10.0.0.1|64|192.0.2.1" in rendered


def test_sanitiser_is_deterministic_and_map_is_reusable():
    first = cw.Sanitiser(serials=True, aliases=True)
    one = cw.render_snmprec(first.apply(sanitiser_input()))
    two = cw.render_snmprec(cw.Sanitiser(serials=True, aliases=True).apply(list(reversed(sanitiser_input()))))
    assert one == two
    mapping = json.loads(json.dumps(first.mapping()))
    neighbour = [cw.Record("1.3.6.1.2.1.1.5.0", "4", b"dist-sw1"),
                 cw.Record("1.3.6.1.2.1.4.20.1.1.10.20.30.40", "64", "10.20.30.40")]
    reused = records_by_oid(cw.Sanitiser(mapping=mapping).apply(neighbour))
    assert reused["1.3.6.1.2.1.1.5.0"].value == b"device-002"
    assert reused["1.3.6.1.2.1.4.20.1.1.10.20.30.40"].value == "192.0.2.2"


def test_serial_only_sanitiser_leaves_names():
    output = records_by_oid(cw.SerialSanitiser(serials=True).apply(sanitiser_input()))
    assert output["1.3.6.1.2.1.1.5.0"].value == b"core-sw1"
    assert output["1.3.6.1.2.1.47.1.1.1.1.11.1"].value == b"SERIAL-0001"


@pytest.mark.parametrize("text,expected", [
    ("1.3.6.1.4.1.9.9.23", "1.3.6.1.4.1.9.9.23"),
    (".1.3.6.1.4.1.2636", "1.3.6.1.4.1.2636"),
])
def test_validate_oid_accepts(text, expected):
    assert cw.validate_oid(text) == expected


@pytest.mark.parametrize("text", ["1.3.6.1; rm -rf /", "-On", "IF-MIB::ifTable", "1", "3.6.1", "1.3.6.01", ""])
def test_validate_oid_rejects(text):
    with pytest.raises(cw.UsageError):
        cw.validate_oid(text)


def test_credentials_validation():
    assert cw.validate_credentials({"version": "2c", "community": "x"}) == {"version": "2c", "community": "x"}
    v3 = cw.validate_credentials({"version": "3", "username": "u", "security_level": "authPriv",
                                  "auth_protocol": "sha256", "auth_passphrase": "a b c",
                                  "priv_protocol": "aes256", "priv_passphrase": "p q r"})
    assert (v3["auth_protocol"], v3["priv_protocol"]) == ("SHA-256", "AES-256")
    for bad in ({"version": "1", "community": "x"}, {"version": "2c", "community": "a\nb"},
                {"version": "2c", "community": " x"}, {"version": "3", "username": "u",
                                                        "auth_protocol": "SHA", "auth_passphrase": "a"}):
        with pytest.raises(cw.UsageError):
            cw.validate_credentials(bad)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_credentials_file_must_be_private(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text(json.dumps({"version": "2c", "community": COMMUNITY}))
    path.chmod(0o640)
    with pytest.raises(cw.UsageError, match="group/world"):
        cw.read_protected_json(str(path), "Credentials file")
    path.chmod(0o600)
    assert cw.read_protected_json(str(path), "Credentials file")["community"] == COMMUNITY


class FakeRunner:
    """Stands in for subprocess.run; records argv/env and serves canned output per subtree."""

    def __init__(self, outputs):
        self.outputs = outputs
        self.calls = []
        self.conf_texts = []

    def __call__(self, command, **kwargs):
        assert isinstance(command, list) and not kwargs.get("shell")
        self.calls.append((command, kwargs))
        if command[1:] == ["-V"]:
            return subprocess.CompletedProcess(command, 0, b"", b"NET-SNMP version: 5.9.4\n")
        conf = Path(kwargs["env"]["SNMPCONFPATH"]) / "snmp.conf"
        self.conf_texts.append(conf.read_text())
        assert conf.stat().st_mode & 0o077 == 0
        oid = command[-1]
        behaviour = self.outputs.get(oid, ("", "", 0))
        if behaviour == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=b".%s.1.0 = INTEGER: 1\n" % oid.encode())
        stdout, stderr, code = behaviour
        return subprocess.CompletedProcess(command, code, stdout.encode(), stderr.encode())


def capture_args(tmp_path, *extra):
    return cw.parse_args(["--host", "192.0.2.10", "--label", "lab-sw1", "--out-dir", str(tmp_path), *extra])


def test_capture_with_mocked_snmpbulkwalk(tmp_path, capsys):
    runner = FakeRunner({
        "1.3.6.1.2.1.1": (".1.3.6.1.2.1.1.5.0 = Hex-STRING: 73 77 31 \n.1.3.6.1.2.1.1.3.0 = Timeticks: (5) 0:00:00.05\n",
                          "", 0),
        "1.3.6.1.2.1.2.2": "timeout",
        "1.3.6.1.2.1.31.1.1": ("", f"snmpbulkwalk: Authentication failure for community {COMMUNITY}\n", 1),
        "1.0.8802.1.1.2.1": (".1.0.8802.1.1.2.1 = No Such Object available on this agent at this OID\n", "", 0),
    })
    args = capture_args(tmp_path, "--extra-subtree", "1.3.6.1.4.1.9.9.23")
    code = cw.capture(args, runner=runner, environ={"NE_SNMP_COMMUNITY": COMMUNITY, "PATH": "/usr/bin"})
    assert code == cw.EXIT_PARTIAL

    walk_calls = [(c, k) for c, k in runner.calls if c[1:] != ["-V"]]
    assert len(walk_calls) == len(cw.DEFAULT_SUBTREES) + 1
    for command, kwargs in walk_calls:
        assert COMMUNITY not in " ".join(command)
        assert command[:6] == ["snmpbulkwalk", "-m", "", "-On", "-Oe", "-Ox"]
        assert command[-2] == "udp:192.0.2.10:161"
        assert not any(key.startswith("NE_SNMP_") for key in kwargs["env"])
    assert walk_calls[-1][0][-1] == "1.3.6.1.4.1.9.9.23"
    assert all(f"defCommunity {COMMUNITY}" in text for text in runner.conf_texts)

    snmprec = (tmp_path / "lab-sw1.snmprec").read_text()
    assert snmprec.splitlines()[:2] == ["1.3.6.1.2.1.1.3.0|67|5", "1.3.6.1.2.1.1.5.0|4|sw1"]
    assert "1.3.6.1.2.1.2.2.1.0|2|1" in snmprec            # partial data from the timed-out subtree

    manifest_text = (tmp_path / "lab-sw1.manifest.json").read_text()
    manifest = json.loads(manifest_text)
    outcomes = {s["oid"]: s for s in manifest["subtrees"]}
    assert outcomes["1.3.6.1.2.1.1"]["outcome"] == "ok" and outcomes["1.3.6.1.2.1.1"]["records"] == 2
    assert outcomes["1.3.6.1.2.1.2.2"]["outcome"] == "timeout" and outcomes["1.3.6.1.2.1.2.2"]["partial"]
    assert outcomes["1.3.6.1.2.1.31.1.1"]["outcome"] == "error"
    assert "***" in outcomes["1.3.6.1.2.1.31.1.1"]["message"]
    assert outcomes["1.0.8802.1.1.2.1"]["outcome"] == "no-such-object"
    assert manifest["net_snmp_version"] == "5.9.4" and manifest["device_label"] == "lab-sw1"
    assert manifest["captured_at"].endswith("Z")
    for forbidden in (COMMUNITY, "192.0.2.10"):
        assert forbidden not in manifest_text
        assert forbidden not in capsys.readouterr().err


def test_capture_unreachable_device(tmp_path):
    runner = FakeRunner({oid: ("", "Timeout: No Response from udp:192.0.2.10:161\n", 1)
                         for _, oid in cw.DEFAULT_SUBTREES})
    code = cw.capture(capture_args(tmp_path), runner=runner, environ={"NE_SNMP_COMMUNITY": COMMUNITY})
    assert code == cw.EXIT_UNREACHABLE
    manifest = json.loads((tmp_path / "lab-sw1.manifest.json").read_text())
    assert {s["outcome"] for s in manifest["subtrees"]} == {"timeout"}


def test_capture_v3_conf_and_context(tmp_path):
    creds = tmp_path / "creds.json"
    creds.write_text(json.dumps({"version": "3", "username": "nms-ro", "security_level": "authPriv",
                                 "auth_protocol": "SHA-256", "auth_passphrase": "auth secret 1",
                                 "priv_protocol": "AES", "priv_passphrase": "priv secret 2"}))
    creds.chmod(0o600)
    runner = FakeRunner({})
    args = capture_args(tmp_path, "--credentials", str(creds), "--context", "vlan-10", "--only-extra",
                        "--extra-subtree", "1.3.6.1.2.1.17.4.3")
    assert cw.capture(args, runner=runner, environ={}) == cw.EXIT_OK
    command = runner.calls[-1][0]
    assert command[-4:] == ["-n", "vlan-10", "udp:192.0.2.10:161", "1.3.6.1.2.1.17.4.3"]
    assert "auth secret 1" not in " ".join(command)
    conf = runner.conf_texts[-1].splitlines()
    assert conf == ["defVersion 3", "defSecurityName nms-ro", "defSecurityLevel authPriv",
                    "defAuthType SHA-256", "defAuthPassphrase auth secret 1",
                    "defPrivType AES", "defPrivPassphrase priv secret 2"]
    manifest = (tmp_path / "lab-sw1.manifest.json").read_text()
    assert "secret" not in manifest and "nms-ro" not in manifest


def test_capture_sanitised_with_map(tmp_path):
    runner = FakeRunner({"1.3.6.1.2.1.1": (".1.3.6.1.2.1.1.5.0 = Hex-STRING: 63 6F 72 65 \n", "", 0)})
    map_path = tmp_path / "map.json"
    args = capture_args(tmp_path, "--sanitise", "--sanitise-map", str(map_path))
    cw.capture(args, runner=runner, environ={"NE_SNMP_COMMUNITY": COMMUNITY})
    assert "1.3.6.1.2.1.1.5.0|4|device-001" in (tmp_path / "lab-sw1.snmprec").read_text()
    assert json.loads(map_path.read_text())["names"] == {"core": "device-001"}
    assert map_path.stat().st_mode & 0o077 == 0
    manifest = json.loads((tmp_path / "lab-sw1.manifest.json").read_text())
    assert manifest["sanitised"]["enabled"] and manifest["sanitisation_limits"]


def test_missing_credentials_is_usage_error(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith("NE_SNMP_"):
            monkeypatch.delenv(key)
    assert cw.main(["--host", "192.0.2.10", "--label", "x", "--out-dir", str(tmp_path)]) == cw.EXIT_USAGE


@pytest.mark.parametrize("host,expected", [
    ("192.0.2.1", "udp:192.0.2.1:161"),
    ("2001:db8::1", "udp6:[2001:db8::1]:161"),
    ("sw1.example.net", "udp:sw1.example.net:161"),
])
def test_snmp_target(host, expected):
    assert cw.snmp_target(host, 161) == expected


@pytest.mark.parametrize("host", ["-Cc", "a b", "host;rm", ""])
def test_snmp_target_rejects(host):
    with pytest.raises(cw.UsageError):
        cw.snmp_target(host, 161)


@pytest.mark.parametrize("label", ["lab-sw1\n", "lab-sw1\nx", "-lab", "a/b", ""])
def test_label_rejects_trailing_newline_and_bad_characters(tmp_path, label):
    with pytest.raises(SystemExit):
        cw.parse_args(["--host", "192.0.2.10", "--label", label, "--out-dir", str(tmp_path)])


@pytest.mark.parametrize("host", ["sw1.example.net\n", "sw1\n.example.net", "-sw1"])
def test_hostname_rejects_trailing_newline(host):
    with pytest.raises(cw.UsageError):
        cw.snmp_target(host, 161)


def test_validate_oid_rejects_embedded_newline():
    with pytest.raises(cw.UsageError):
        cw.validate_oid("1.3.6.1\n.2")


def test_write_private_tightens_existing_file_mode(tmp_path):
    path = tmp_path / "out.snmprec"
    path.write_text("old")
    os.chmod(path, 0o644)
    cw.write_private(path, "new\n")
    assert path.read_text() == "new\n"
    assert path.stat().st_mode & 0o777 == 0o600


def test_write_private_failure_is_usage_error(tmp_path):
    with pytest.raises(cw.UsageError) as error:
        cw.write_private(tmp_path / "missing-dir" / "out.snmprec", "x")
    assert "missing-dir" not in str(error.value)
