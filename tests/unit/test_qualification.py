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

import capture_walk as cw  # noqa: E402
import qualify  # noqa: E402

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
        assert qualify.classify(qualify.walk_path(item)) == item["classification"], ident


@needs_node
def test_classification_reports_what_the_walk_shows():
    stack = qualify.classify(WALKS / "sw-stack-01.snmprec")["capabilities"]
    assert stack == {c: "ok" for c in qualify.CAPABILITIES}
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


def captured(tmp_path, walk_text, sanitised=True):
    directory = tmp_path / "acme-x24-1.0"
    directory.mkdir()
    (directory / "capture.snmprec").write_text(walk_text)
    (directory / "manifest.json").write_text(json.dumps({
        "format": "network-explorer-walk-manifest-1", "device_label": "acme-x24-1.0",
        "captured_at": "2026-10-11T00:00:00Z", "net_snmp_version": "5.9", "snmp_version": "3",
        "snmp_security_level": "authPriv", "walk_options": {}, "subtrees": [], "snmprec_file": "capture.snmprec",
        "record_count": 1, "sanitisation_limits": [],
        "sanitised": {"enabled": sanitised, "serials": sanitised, "aliases": sanitised, "shared_map": False}}))
    (directory / "evidence.json").write_text(json.dumps({
        "id": "acme-x24-1.0", "kind": "captured", "walk": "capture.snmprec", "description": "Test capture.",
        "device": {"vendor": "Acme", "family": "X", "model": "X-24", "firmware": "1.0"},
        "classification": {"capabilities": {}}}))
    return directory


def test_unsanitised_capture_is_rejected(tmp_path):
    directory = captured(tmp_path, (WALKS / "sw-dist-01.snmprec").read_text(), sanitised=False)
    errors, _ = qualify.check_evidence(directory)
    text = "\n".join(errors)
    assert "was not taken with sanitisation" in text
    assert "1.3.6.1.2.1.1.5.0: system name is not a sanitised placeholder" in text
    assert "holds 10.102.5.10, not a documentation address" in text, "sw-dist-01's management address is caught"


def test_capture_walk_sanitiser_output_passes(tmp_path):
    records = [to_record(*r) for r in qualify.read_snmprec(WALKS / "sw-dist-01.snmprec")]
    clean = cw.render_snmprec(cw.Sanitiser(serials=True, aliases=True).apply(records))
    directory = captured(tmp_path, clean)
    errors, warnings = qualify.check_evidence(directory)
    assert errors == [], errors
    assert any("MAC addresses" in w for w in warnings), "kept MAC addresses are pointed out to the reviewer"


def test_free_text_addresses_credentials_in_manifest_and_bad_ids_are_rejected(tmp_path):
    records = [to_record(*r) for r in qualify.read_snmprec(WALKS / "sw-dist-01.snmprec")]
    records.append(cw.Record("1.3.6.1.2.1.2.2.1.2.999", cw.TAG_OCTETS, b"uplink to 10.20.30.40"))
    directory = captured(tmp_path, cw.render_snmprec(cw.Sanitiser(serials=True, aliases=True).apply(records)))
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["target"] = "10.0.0.1"
    (directory / "manifest.json").write_text(json.dumps(manifest))
    item = json.loads((directory / "evidence.json").read_text())
    item["id"] = "Other"
    del item["device"]["firmware"]
    (directory / "evidence.json").write_text(json.dumps(item))
    text = "\n".join(qualify.check_evidence(directory)[0])
    assert "free text contains IPv4 address 10.20.30.40" in text
    assert "unexpected keys ['target']" in text
    assert "id must match the directory name" in text
    assert "device.firmware is required" in text


def test_field_evidence_needs_a_field_record(tmp_path):
    records = [to_record(*r) for r in qualify.read_snmprec(WALKS / "sw-dist-01.snmprec")]
    directory = captured(tmp_path, cw.render_snmprec(cw.Sanitiser(serials=True, aliases=True).apply(records)))
    item = json.loads((directory / "evidence.json").read_text())
    item["kind"] = "field"
    item["field"] = {"verified": ["lldp", "poe"]}
    (directory / "evidence.json").write_text(json.dumps(item))
    text = "\n".join(qualify.check_evidence(directory)[0])
    assert "field.observed_on is required" in text and "field.zabbix_version is required" in text
    assert "field.verified may list only" in text


def test_a_walk_path_cannot_leave_the_repository(tmp_path):
    item = {"id": "x", "kind": "synthetic", "walk": "../../etc/passwd", "_dir": tmp_path}
    with pytest.raises(qualify.UsageError):
        qualify.walk_path(item)


def test_rendered_matrix_has_every_capability_column():
    rendered = qualify.render_matrix(matrix(), qualify.evidence_index())
    header = next(line for line in rendered.splitlines() if line.startswith("| Vendor / family"))
    for label in ("Interfaces", "ENTITY", "MAU", "LLDP", "VLAN", "STP", "LAG", "Known limitations", "Evidence",
                  "Qualified on"):
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
