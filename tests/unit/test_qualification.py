"""Hardware qualification: the matrix only claims what cited evidence shows, and evidence is sanitised."""
import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "qualification"))
sys.path.insert(0, str(ROOT / "tools" / "inventory"))

import anonymise  # noqa: E402
import capture_walk as cw  # noqa: E402
import qualify  # noqa: E402
from collections import Counter  # noqa: E402

WALKS = ROOT / "tests/fixtures/walks"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")


def matrix():
    return json.loads(qualify.MATRIX_JSON.read_text())


def row(**states):
    base = {c: "Unqualified" for c in qualify.CAPABILITIES}
    return {"vendor": "Acme", "family": "X", "model": "X-24", "firmware": "1.0", "states": {**base, **states},
            "limitations": "", "evidence": []}


def evidence(ident, kind, **caps):
    full = {c: "ok" for c in qualify.CAPABILITIES}
    return {"id": ident, "kind": kind, "classification": {"capabilities": {**full, **caps}}}


def test_matrix_is_current_and_every_claim_has_evidence():
    assert qualify.main(["matrix", "--check"]) == 0


def test_no_real_vendor_is_claimed_without_evidence():
    for entry in matrix()["rows"]:
        if not entry["evidence"]:
            assert set(entry["states"].values()) == {"Unqualified"}, entry
        assert "PASS" not in json.dumps(entry)


@needs_node
def test_committed_classifications_match_a_fresh_replay():
    index = qualify.evidence_index()
    assert index, "the synthetic lab evidence is committed"
    for ident, item in index.items():
        assert qualify.classify_evidence(item) == item["classification"], ident


@needs_node
def test_classification_reports_what_the_walk_shows():
    stack = qualify.classify(WALKS / "sw-stack-01.snmprec")["capabilities"]
    # The generic template has no hardware producer; the synthetic walks carry no PoE tables.
    assert stack == {**{c: "ok" for c in qualify.CAPABILITIES}, "hardware": "not_collected", "poe": "unsupported"}
    dist = qualify.classify(WALKS / "sw-dist-01.snmprec")["capabilities"]
    # No port entities and no LAG rows: absent/empty, never "ok" and never "unsupported".
    assert dist["entity"] == "absent" and dist["lag"] == "empty" and dist["interfaces"] == "ok"


@needs_node
def test_a_walk_without_lldp_or_mau_is_classified_unsupported(tmp_path):
    lines = [line for line in (WALKS / "sw-core-01.snmprec").read_text().splitlines()
             if not line.startswith(("1.0.8802.", "1.3.6.1.2.1.26."))]
    walk = tmp_path / "reduced.snmprec"
    walk.write_text("\n".join(lines) + "\n")
    caps = qualify.classify(walk)["capabilities"]
    assert caps["lldp"] == "unsupported" and caps["mau"] == "unsupported" and caps["interfaces"] == "ok"


CAPTURES = ROOT / "tests/fixtures/qualification"


@needs_node
def test_evidence_replays_its_own_templates_producers():
    walk = CAPTURES / "cisco-cbs350-24p-4x-3.6.0.3" / "capture.snmprec"
    vendor = qualify.classify(walk, "ne_cisco_small_business_switch")
    assert vendor["template"] == "ne_cisco_small_business_switch"
    assert (vendor["capabilities"]["hardware"], vendor["capabilities"]["poe"]) == ("ok", "ok")
    assert qualify.classify(walk)["capabilities"]["hardware"] == "not_collected"
    with pytest.raises(qualify.UsageError):
        qualify.classify(walk, "we__generic_access_point")


@needs_node
def test_a_subtree_the_capture_never_walked_is_not_walked_not_unsupported(tmp_path):
    # The CBS220 capture walked CISCO-ENVMON-MIB and the switch answered no-such-object: unsupported. The same walk
    # with that subtree missing from its manifest, as in the first CBS220 capture, shows nothing either way.
    source = CAPTURES / "cisco-cbs220-24p-4g-2.0.2.15"
    caps = qualify.classify(source / "capture.snmprec", "ne_cisco_cbs220_switch")["capabilities"]
    assert (caps["hardware"], caps["poe"], caps["mau"]) == ("unsupported", "ok", "unsupported")
    shutil.copy(source / "capture.snmprec", tmp_path / "capture.snmprec")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    manifest["subtrees"] = [s for s in manifest["subtrees"] if s["oid"] != "1.3.6.1.4.1.9.9.13"]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    caps = qualify.classify(tmp_path / "capture.snmprec", "ne_cisco_cbs220_switch")["capabilities"]
    assert (caps["hardware"], caps["poe"], caps["mau"]) == ("not_walked", "ok", "unsupported")
    entry = row(hardware="Unsupported")
    entry["evidence"] = ["c"]
    errors = qualify.validate_matrix({"rows": [entry]}, {"c": evidence("c", "captured", hardware="not_walked")})
    assert any("no cited captured/field evidence" in e for e in errors)


def test_evidence_must_be_classified_through_its_template(tmp_path):
    source = CAPTURES / "cisco-sg300-28pp-1.4.11.5"
    target = tmp_path / source.name
    shutil.copytree(source, target)
    item = json.loads((target / "evidence.json").read_text(encoding="utf-8"))
    item["template"] = "ne_cisco_small_business_switch"
    (target / "evidence.json").write_text(json.dumps(item), encoding="utf-8")
    errors, _ = qualify.check_evidence(target)
    assert any("was not replayed through ne_cisco_small_business_switch" in e for e in errors)
    item["template"] = "ne_acme_switch"
    (target / "evidence.json").write_text(json.dumps(item), encoding="utf-8")
    assert any("not a switch template" in e for e in qualify.check_evidence(target)[0])


@pytest.mark.parametrize("state, items, problem", [
    ("Captured-walk tested", [], "no cited captured/field evidence"),
    ("Captured-walk tested", [evidence("e", "synthetic")], "no cited captured/field evidence"),
    ("Real-device qualified", [evidence("e", "captured")], "no cited field evidence"),
    ("Unsupported", [evidence("e", "captured")], "no cited captured/field evidence"),
    ("Lab simulated", [evidence("e", "synthetic", lldp="empty")], "no cited synthetic evidence"),
    ("Supported", [], "is not one of"),
])
def test_claims_without_matching_evidence_are_rejected(state, items, problem):
    entry = row(lldp=state)
    entry["evidence"] = [e["id"] for e in items]
    errors = qualify.validate_matrix({"rows": [entry]}, {e["id"]: e for e in items})
    assert any(problem in error for error in errors), errors


def test_matching_evidence_is_accepted():
    field = evidence("f", "field")
    field["field"] = {"verified": ["lldp"]}
    entry = row(lldp="Real-device qualified", interfaces="Captured-walk tested")
    entry["evidence"] = ["f"]
    assert qualify.validate_matrix({"rows": [entry]}, {"f": field}) == []
    # A field record that did not verify LLDP does not qualify it.
    field["field"] = {"verified": ["interfaces"]}
    assert qualify.validate_matrix({"rows": [entry]}, {"f": field})
    unsupported = row(lldp="Unsupported")
    unsupported["evidence"] = ["c"]
    assert qualify.validate_matrix({"rows": [unsupported]}, {"c": evidence("c", "captured", lldp="unsupported")}) == []


def test_partial_needs_limitations_and_real_states_need_model_and_firmware():
    entry = row(vlan="Partially qualified")
    entry["evidence"] = ["c"]
    index = {"c": evidence("c", "captured", vlan="partial")}
    assert any("without stated limitations" in e for e in qualify.validate_matrix({"rows": [entry]}, index))
    entry["limitations"] = "Q-BRIDGE static table missing."
    assert qualify.validate_matrix({"rows": [entry]}, index) == []
    entry["firmware"] = None
    assert any("exact firmware" in e for e in qualify.validate_matrix({"rows": [entry]}, index))
    missing = row()
    missing["evidence"] = ["nowhere"]
    assert any("does not exist" in e for e in qualify.validate_matrix({"rows": [missing]}, {}))


def to_record(oid, tag, value):
    if tag == "4":
        return cw.Record(oid, cw.TAG_OCTETS, value.encode("latin-1"))
    if tag == "4x":
        return cw.Record(oid, cw.TAG_OCTETS, bytes.fromhex(value))
    if tag in ("6", "64"):
        return cw.Record(oid, tag, value)
    if tag == "5":
        return cw.Record(oid, tag, None)
    return cw.Record(oid, tag, int(value))


def sanitised_and_anonymised(tmp_path, records):
    """What the evidence workflow produces: capture_walk.py --sanitise, then anonymise.py."""
    clean = cw.render_snmprec(cw.Sanitiser(serials=True, aliases=True).apply(records))
    rows = [tuple(line.split("|", 2)) for line in clean.splitlines() if line.strip()]
    places = anonymise.Placeholders(tmp_path / "private-map.json")
    out = anonymise.anonymise_walk(rows, places, anonymise.Macs(places, anonymise.mac_values(rows)), {}, Counter())
    return "".join(f"{o}|{t}|{v}\n" for o, t, v in out)


def captured(tmp_path, walk_text, sanitised=True, anonymised=True):
    directory = tmp_path / "acme-x24-1.0"
    directory.mkdir()
    (directory / "capture.snmprec").write_text(walk_text)
    manifest = {
        "format": "network-explorer-walk-manifest-1", "device_label": "acme-x24-1.0",
        "captured_at": "2026-10-11T00:00:00Z", "snmp_version": "3",
        "snmp_security_level": "authPriv", "walk_options": {}, "subtrees": [], "snmprec_file": "capture.snmprec",
        "record_count": 1, "sanitisation_limits": [],
        "sanitised": {"enabled": sanitised, "serials": sanitised, "aliases": sanitised, "shared_map": False}}
    if anonymised:
        manifest["anonymised"] = {"tool": anonymise.TOOL, "version": anonymise.FORMAT_VERSION,
                                  "uptime_ticks": anonymise.UPTIME, "rules": anonymise.RULES}
    (directory / "manifest.json").write_text(json.dumps(manifest))
    (directory / "evidence.json").write_text(json.dumps({
        "id": "acme-x24-1.0", "kind": "captured", "walk": "capture.snmprec", "description": "Test capture.",
        "device": {"vendor": "Acme", "family": "X", "model": "X-24", "firmware": "1.0"},
        "classification": {"template": qualify.DEFAULT_TEMPLATE, "capabilities": {}}}))
    return directory


def test_unsanitised_capture_is_rejected(tmp_path):
    directory = captured(tmp_path, (WALKS / "sw-dist-01.snmprec").read_text(), sanitised=False)
    errors, _ = qualify.check_evidence(directory)
    text = "\n".join(errors)
    assert "was not taken with sanitisation" in text
    assert "1.3.6.1.2.1.1.5.0: system name is not a sanitised placeholder" in text
    assert "holds 10.102.5.10, not a documentation address" in text, "sw-dist-01's management address is caught"


def test_sanitised_and_anonymised_capture_passes(tmp_path):
    records = [to_record(*r) for r in qualify.read_snmprec(WALKS / "sw-dist-01.snmprec")]
    directory = captured(tmp_path, sanitised_and_anonymised(tmp_path, records))
    assert qualify.check_evidence(directory) == ([], [])


def test_sanitiser_output_alone_is_not_publishable(tmp_path):
    records = [to_record(*r) for r in qualify.read_snmprec(WALKS / "sw-dist-01.snmprec")]
    clean = cw.render_snmprec(cw.Sanitiser(serials=True, aliases=True).apply(records))
    text = "\n".join(qualify.check_evidence(captured(tmp_path, clean, anonymised=False))[0])
    assert "capture was not anonymised" in text
    assert "MAC address is not anonymised" in text and "bridge ID holds a MAC address" in text
    assert "neighbour system description is not a sanitised placeholder" in text


def test_free_text_addresses_credentials_in_manifest_and_bad_ids_are_rejected(tmp_path):
    records = [to_record(*r) for r in qualify.read_snmprec(WALKS / "sw-dist-01.snmprec")]
    records.append(cw.Record("1.3.6.1.2.1.2.2.1.2.999", cw.TAG_OCTETS, b"uplink to 10.20.30.40"))
    directory = captured(tmp_path, sanitised_and_anonymised(tmp_path, records))
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["target"] = "10.0.0.1"
    manifest["net_snmp_version"] = "5.9"
    (directory / "manifest.json").write_text(json.dumps(manifest))
    item = json.loads((directory / "evidence.json").read_text())
    item["id"] = "Other"
    del item["device"]["firmware"]
    (directory / "evidence.json").write_text(json.dumps(item))
    text = "\n".join(qualify.check_evidence(directory)[0])
    assert "free text contains IPv4 address 10.20.30.40" in text
    assert "unexpected keys ['net_snmp_version', 'target']" in text
    assert "id must match the directory name" in text
    assert "device.firmware is required" in text


def test_field_evidence_needs_a_field_record(tmp_path):
    records = [to_record(*r) for r in qualify.read_snmprec(WALKS / "sw-dist-01.snmprec")]
    directory = captured(tmp_path, sanitised_and_anonymised(tmp_path, records))
    item = json.loads((directory / "evidence.json").read_text())
    item["kind"] = "field"
    item["field"] = {"verified": ["lldp", "optics"]}
    (directory / "evidence.json").write_text(json.dumps(item))
    text = "\n".join(qualify.check_evidence(directory)[0])
    assert "field.observed_on is required" in text and "field.zabbix_version is required" in text
    assert "field.verified may list only" in text


SOFTWARE_REV = "1.3.6.1.2.1.47.1.1.1.1.10."
SYS_DESCR = "1.3.6.1.2.1.1.1.0"


def test_versions_in_revision_columns_pass_but_private_addresses_never_do():
    errors, _ = qualify.check_walk([(SOFTWARE_REV + "1", "4", "2.5.9.54"),
                                    (SOFTWARE_REV + "2", "4", "10.1.2.3"),
                                    ("1.0.8802.1.1.2.1.5.1.1.2.3.0", "4", "3.2.1.22")])   # LLDP-MED, RADLAN arc
    assert errors == [f"{SOFTWARE_REV}2: free text contains IPv4 address 10.1.2.3; edit it by hand"]


def test_a_version_in_free_text_needs_a_reviewed_acknowledgement():
    walk = [(SYS_DESCR, "4", "Acme X-24, 6.5.4.23, Linux")]
    assert "reviewed_versions" in qualify.check_walk(walk)[0][0]
    ok = [{"oid": SYS_DESCR, "value": "6.5.4.23", "reason": "firmware version, reviewed"}]
    assert qualify.check_walk(walk, ok) == ([], [])
    assert "needs an oid, a dotted-quad value and a reason" in qualify.check_walk(walk, [{**ok[0], "reason": ""}])[0][0]
    stale = qualify.check_walk([(SYS_DESCR, "4", "Acme X-24, 6.5.4.24")], ok)[0]
    assert any("has no such value there" in e for e in stale)


def test_a_private_address_cannot_be_acknowledged_as_a_version():
    url = ("1.3.6.1.4.1.674.10895.3000.1.2.100.6.0", "4", "http://10.0.0.5")
    claim = [{"oid": url[0], "value": "10.0.0.5", "reason": "it is a version"}]
    errors = qualify.check_walk([url], claim)[0]
    assert any("cannot acknowledge 10.0.0.5" in e for e in errors)
    assert any("free text contains IPv4 address 10.0.0.5; edit it by hand" in e for e in errors)


def test_mac_addresses_must_be_anonymised_but_port_bitmaps_are_not_macs():
    lldp_rem = "1.0.8802.1.1.2.1.4.1.1."
    walk = [("1.3.6.1.2.1.2.2.1.6.1", "4x", "00005e0053aa"),                  # ifPhysAddress, real
            ("1.3.6.1.2.1.2.2.1.6.2", "4x", "0200000000a1"),                  # ifPhysAddress, placeholder
            ("1.3.6.1.2.1.17.7.1.4.3.1.2.10", "4x", "8000000000c0"),         # egress PortList of 6 octets
            ("1.0.8802.1.1.2.1.5.32962.1.2.4.1.1.1", "4x", "0026424203000000"),  # dot1 protocol identity
            (lldp_rem + "4.0.1.1", "2", "4"), (lldp_rem + "5.0.1.1", "4x", "00005e0053bb"),
            (lldp_rem + "4.0.2.1", "2", "7"), (lldp_rem + "5.0.2.1", "4", "server-room-host"),
            ("1.3.6.1.2.1.17.2.5.0", "4x", "800000005e0053cc"),
            ("1.3.6.1.2.1.17.2.15.1.6.1", "4", "32768-00:00:5e:00:53:dd")]
    errors = [e.split(": ", 1)[0] for e in qualify.check_walk(walk)[0]]
    assert errors == ["1.3.6.1.2.1.2.2.1.6.1", lldp_rem + "5.0.1.1", lldp_rem + "5.0.2.1", "1.3.6.1.2.1.17.2.5.0",
                      "1.3.6.1.2.1.17.2.15.1.6.1"]


def test_uptime_and_end_device_tables_must_be_anonymised():
    walk = [("1.3.6.1.2.1.1.3.0", "67", "123456789"), ("1.3.6.1.2.1.2.2.1.9.1", "67", "99999999"),
            ("1.3.6.1.2.1.17.7.1.2.2.1.2.1.0.17.34.51.68.85", "2", "3")]
    errors = qualify.check_walk(walk)[0]
    assert len(errors) == 3 and "sysUpTime" in errors[0] and "older than" in errors[1] and "end-device" in errors[2]


def test_a_walk_path_cannot_leave_the_repository(tmp_path):
    item = {"id": "x", "kind": "synthetic", "walk": "../../etc/passwd", "_dir": tmp_path}
    with pytest.raises(qualify.UsageError):
        qualify.walk_path(item)


def test_rendered_matrix_has_every_capability_column():
    rendered = qualify.render_matrix(matrix(), qualify.evidence_index())
    header = next(line for line in rendered.splitlines() if line.startswith("| Vendor / family"))
    for label in ("Interfaces", "ENTITY", "MAU", "LLDP", "VLAN", "STP", "LAG", "Hardware", "PoE", "Known limitations",
                  "Evidence", "Qualified on"):
        assert label in header
    assert copy.deepcopy(rendered) == qualify.MATRIX_MD.read_text()


# --- Wi-Fi Explorer --------------------------------------------------------------------------------------------------

WIFI_WALKS = ROOT / "tests/fixtures/wifi/walks"


@needs_node
def test_wifi_matrix_is_current_and_backed_by_its_evidence():
    assert qualify.main(["--product", "wifi", "matrix", "--check"]) == 0


@needs_node
def test_wifi_classification_tells_a_controller_from_a_member():
    vc = qualify.classify_wifi(WIFI_WALKS / "aruba-instant-vc.snmprec")["capabilities"]
    member = qualify.classify_wifi(WIFI_WALKS / "aruba-instant-member.snmprec")["capabilities"]
    assert set(vc.values()) == {"ok"}
    assert member == {"controller": "absent", "ap_inventory": "unsupported", "ap_state": "unsupported",
                      "radio_inventory": "unsupported", "radio_state": "unsupported"}


def test_wifi_claims_need_wifi_evidence():
    states = {c: "Unqualified" for c in qualify.WIFI_CAPABILITIES}
    claim = {"vendor": "Aruba", "family": "Instant", "model": "AP-515", "firmware": "8.10",
             "states": {**states, "ap_state": "Captured-walk tested"}, "limitations": "", "evidence": []}
    errors = qualify.validate_matrix({"rows": [claim]}, qualify.evidence_index("wifi"), "wifi")
    assert any("ap_state is 'Captured-walk tested'" in e for e in errors)
    switch_states = {"rows": [{**claim, "states": {c: "Unqualified" for c in qualify.CAPABILITIES}}]}
    assert any("states must name exactly controller" in e
               for e in qualify.validate_matrix(switch_states, {}, "wifi"))


def test_unsanitised_aruba_ap_names_and_serials_are_rejected():
    ap = qualify.ARUBA_AI + ".2.1.1"
    errors, _ = qualify.check_walk([(f"{ap}.2.0.0.94.0.83.1", "4", "Reception-AP"),
                                    (f"{ap}.4.0.0.94.0.83.1", "4", "CNJ7KSV123"),
                                    (f"{ap}.2.0.0.94.0.83.2", "4", "device-002")])
    assert len(errors) == 2 and "AP name" in errors[0] and "AP serial" in errors[1]
