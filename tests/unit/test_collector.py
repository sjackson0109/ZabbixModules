"""Synthetic evidence tests; these are not vendor acceptance fixtures."""

import asyncio
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "collector"))

from network_explorer import oids
from network_explorer.collect import collect, serialize
from network_explorer.config import ConfigurationError, load_device, validate_device
from network_explorer.normalize import interface_uid
from network_explorer.transport import FixtureTransport, SnmpTransport
from network_explorer.validation import validate_agent_snapshot, validate_envelope


@pytest.fixture
def fixture():
    return json.loads((ROOT / "tests/fixtures/snmp/standard-switch.json").read_text())


def collected(fixture, dataset, **kwargs):
    return asyncio.run(collect(FixtureTransport(fixture), dataset, **kwargs))


@pytest.mark.parametrize("dataset", ["device", "interfaces", "lldp", "lag"])
def test_complete_standard_fixture(dataset, fixture):
    output = collected(fixture, dataset)
    validate_envelope(output)
    assert output["status"] == "ok"
    assert output["complete"] is True
    assert output["observed_at"] is not None


def test_interface_speed_units_logical_port_and_identity(fixture):
    rows = collected(fixture, "interfaces")["data"]
    assert rows[0]["speed_bps"] == 1_000_000_000
    assert rows[1]["speed_bps"] == 100_000_000
    assert rows[2]["physical"] is False
    assert rows[0]["uid"] == interface_uid("Gi1/0/1", None)
    assert rows[0]["alias"] == "example-Gi1/0/1"
    assert rows[0]["description"] == "GigabitEthernet1/0/1"
    assert "expected_speed_bps" not in rows[0]


def test_renumbered_ifindex_preserves_name_identity(fixture):
    before = collected(fixture, "interfaces")["data"]
    values = fixture["values"]
    for oid in oids.IF.values():
        old = oid + ".101"
        if old in values:
            values[oid + ".501"] = values.pop(old)
    values[oids.IF["index"] + ".501"] = 501
    after = collected(fixture, "interfaces")["data"]
    port = next(row for row in after if row["name"] == "Gi1/0/1")
    assert port["if_index"] == 501
    assert port["uid"] == before[0]["uid"]


def test_duplicate_identity_is_partial_and_never_merges_history(fixture):
    fixture["values"][oids.IF["name"] + ".102"] = "Gi1/0/1"
    first = collected(fixture, "interfaces", generation_id="first")
    second = collected(fixture, "interfaces", generation_id="second")
    assert first["status"] == "partial"
    assert first["complete"] is False
    assert len({row["uid"] for row in first["data"]}) == 3
    assert first["data"][0]["uid"] != second["data"][0]["uid"]
    assert first["errors"][0]["code"] == "identity_ambiguous"


def test_partial_walk_cannot_be_complete_discovery(fixture):
    fixture["results"][oids.IF["index"]] = {"complete": False, "error": "timeout"}
    fixture["values"].pop(oids.IF["index"] + ".102")
    output = collected(fixture, "interfaces")
    assert output["status"] == "partial"
    assert output["complete"] is False
    assert len(output["data"]) == 2
    assert "interface_count_mismatch" in {error["code"] for error in output["errors"]}


def test_failed_attempt_does_not_advance_observation(fixture):
    fixture["values"] = {}
    fixture["results"] = {oid: {"complete": False, "error": "timeout"}
                          for oid in (*oids.IF.values(), oids.IF_NUMBER, oids.UPTIME)}
    output = collected(fixture, "interfaces")
    validate_envelope(output)
    assert output["status"] == "failed"
    assert output["observed_at"] is None
    assert output["data"] == []
    assert output["capability"]["state"] == "unknown"


def test_unsupported_oid_is_not_inferred_from_timeout(fixture):
    fixture["values"] = {oids.UPTIME: 20000, oids.IF_NUMBER: 0}
    output = collected(fixture, "interfaces")
    assert output["status"] == "unsupported"
    assert output["capability"]["state"] == "unsupported"


def test_complete_empty_interface_table_remains_success(fixture):
    fixture["values"] = {oids.UPTIME: 20000, oids.IF_NUMBER: 0}
    fixture["results"] = {oid: {"complete": True, "unsupported": False} for oid in oids.IF.values()}
    output = collected(fixture, "interfaces")
    assert output["status"] == "ok"
    assert output["data"] == []
    assert output["complete"] is True


def test_reboot_discards_incoherent_snapshot(fixture):
    fixture["uptime_reads"] = [20000, 100]
    output = collected(fixture, "interfaces")
    assert output["status"] == "failed"
    assert output["observed_at"] is None
    assert output["errors"][0]["code"] == "device_restarted"


def test_lldp_uses_subtypes_and_compound_indices_not_localnum_ifindex(fixture):
    output = collected(fixture, "lldp", redact_remote=False)
    row = output["data"][0]
    assert row["local_interface_uid"] == interface_uid("Gi1/0/1", None)
    assert row["remote_chassis_id"] == {"subtype": 4, "value": "aa:bb:cc:dd:ee:ff"}
    assert row["remote_port_id"] == {"subtype": 5, "value": "Gi0/1"}
    assert row["remote_management_addresses"] == ["192.0.2.20"]
    assert row["observed_at"] == output["observed_at"]
    # A localNum that happens to equal an ifIndex provides no identity evidence.
    for oid in oids.LLDP_LOCAL.values():
        fixture["values"].pop(oid + ".7", None)
    for oid in oids.LLDP_REMOTE.values():
        old = oid + ".12345.7.1"
        if old in fixture["values"]:
            fixture["values"][oid + ".12345.101.1"] = fixture["values"].pop(old)
    output = collected(fixture, "lldp", redact_remote=False)
    assert output["data"][0]["local_interface_uid"] is None
    assert output["status"] == "partial"


def test_lldp_multiple_peers_and_ipv6_management_index(fixture):
    values = fixture["values"]
    for oid in oids.LLDP_REMOTE.values():
        old = oid + ".12345.7.1"
        if old in values:
            values[oid + ".12345.7.2"] = values[old]
    values[oids.LLDP_REMOTE["system_name"] + ".12345.7.2"] = "fixture-switch-c"
    octets = ".".join(str(part) for part in bytes.fromhex("20010db8000000000000000000000001"))
    values[oids.LLDP_REMOTE["management"] + ".12345.7.2.2.16." + octets] = 2
    output = collected(fixture, "lldp", redact_remote=False)
    assert len(output["data"]) == 2
    assert output["data"][1]["remote_management_addresses"] == ["2001:db8::1"]


def test_default_collection_suppression_protects_raw_item_consumers(fixture):
    output = collected(fixture, "lldp")
    row = output["data"][0]
    assert row["remote_chassis_id"] == {"subtype": None, "value": ""}
    assert row["remote_port_id"] == {"subtype": None, "value": ""}
    assert row["remote_management_addresses"] == []
    assert row["remote_system_name"] is None
    serialized = serialize(output)
    assert "fixture-switch-b" not in serialized
    assert "192.0.2.20" not in serialized
    assert "aa:bb:cc:dd:ee:ff" not in serialized


def test_standard_lag_member_evidence(fixture):
    output = collected(fixture, "lag", redact_remote=False)
    row = output["data"][0]
    assert row["if_index"] == 1000
    assert set(row["member_interface_uids"]) == {
        interface_uid("Gi1/0/1", None), interface_uid("Gi1/0/2", None)}
    assert row["partner_system_id"] == "aa:bb:cc:dd:ee:ff"
    assert collected(fixture, "lag")["data"][0]["partner_system_id"] is None


def test_unknown_lag_partner_and_dangling_aggregator_evidence(fixture):
    fixture["values"][oids.LAG["partner"] + ".1000"] = {"hex": "000000000000"}
    output = collected(fixture, "lag", redact_remote=False)
    assert output["data"][0]["partner_system_id"] is None
    fixture["values"][oids.LAG["attached"] + ".102"] = 2000
    output = collected(fixture, "lag", redact_remote=False)
    assert output["status"] == "partial"
    assert output["complete"] is False
    assert "lag_aggregator_unresolved" in {error["code"] for error in output["errors"]}


def test_individual_lag_table_row_requires_group_evidence(fixture):
    values = fixture["values"]
    for key, oid in oids.LAG.items():
        if key != "attached":
            values[oid + ".101"] = 2 if key == "individual" else {"hex": "001122334456"}
    output = collected(fixture, "lag", redact_remote=False)
    assert output["status"] == "ok"
    assert [row["if_index"] for row in output["data"]] == [1000]


def test_output_bound_fails_without_truncating_json(fixture):
    output = collected(fixture, "interfaces")
    failed = json.loads(serialize(output, max_bytes=800))
    validate_envelope(failed)
    assert failed["status"] == "failed"
    assert failed["data"] == []
    assert failed["errors"][0]["code"] == "output_limit"


def test_config_owner_only_and_allowlist(tmp_path):
    path = tmp_path / "devices.json"
    secret = "sensitive-community-for-test"
    device = {"address": "127.0.0.1", "snmp": {"version": "2c", "community": secret}}
    path.write_text(json.dumps({"version": 1, "devices": {"test": device}}))
    path.chmod(0o600)
    assert load_device(path, "test")["snmp"]["community"] == secret
    with pytest.raises(ConfigurationError, match="allowlist"):
        load_device(path, "other")
    path.chmod(0o644)
    with pytest.raises(ConfigurationError, match="owner-only"):
        load_device(path, "test")
    path.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(ConfigurationError, match="protected JSON"):
        load_device(link, "test")


def test_cli_failure_never_echoes_config_secrets(tmp_path):
    path = tmp_path / "devices.json"
    secret = "DO_NOT_ECHO_SECRET"
    path.write_text(json.dumps({"version": 1, "devices": {"test": {"address": "127.0.0.1",
                    "snmp": {"version": "3", "username": secret, "auth_key": secret,
                             "priv_key": secret, "auth_protocol": secret}}}}))
    path.chmod(0o600)
    result = subprocess.run([sys.executable, "-m", "network_explorer", "collect", "--config", str(path),
                             "--device", "test", "--dataset", "interfaces"],
                            env={**os.environ, "PYTHONPATH": str(ROOT / "collector")},
                            capture_output=True, text=True, check=True)
    assert secret not in result.stdout + result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout)["errors"][0]["code"] == "configuration_error"


def test_transport_exception_never_echoes_secrets(monkeypatch):
    device = validate_device({"address": "127.0.0.1", "snmp": {"version": "2c", "community": "SECRET_MARKER"}})
    transport = SnmpTransport(device)
    async def error():
        raise RuntimeError("SECRET_MARKER")
    monkeypatch.setattr(transport, "initialize", error)
    result = asyncio.run(transport.read(oids.UPTIME, scalar=True))
    assert result.error == "transport_error"
    assert "SECRET_MARKER" not in repr(result)


def test_agent_contract_binds_owner_and_rejects_replay(fixture):
    output = collected(fixture, "interfaces")
    output["source"].update(method="agent", source_instance="site-a-switch-a", collection_mode="once")
    validate_agent_snapshot(output, "site-a-switch-a")
    with pytest.raises(ValueError, match="owner"):
        validate_agent_snapshot(output, "site-b-switch-a")
    with pytest.raises(ValueError, match="already accepted"):
        validate_agent_snapshot(output, "site-a-switch-a", output["generation_id"])
    output["observed_at"] = "2099-01-01T00:00:00Z"
    with pytest.raises(ValueError, match="clock skew"):
        validate_agent_snapshot(output, "site-a-switch-a")


def test_schema_rejects_false_success_and_unknown_version(fixture):
    output = collected(fixture, "interfaces")
    output["complete"] = False
    with pytest.raises(ValueError):
        validate_envelope(output)
    output["complete"] = True
    output["schema_version"] = "2.0"
    with pytest.raises(ValueError):
        validate_envelope(output)


def test_packaged_schema_matches_public_contract():
    assert (ROOT / "schemas/envelope.schema.json").read_bytes() == (
        ROOT / "collector/network_explorer/envelope.schema.json").read_bytes()


def test_schema_checks_timestamps_without_optional_packages(fixture):
    output = collected(fixture, "interfaces")
    for bad in ("not-a-date", "2026-13-01T00:00:00Z", "2026-10-07 12:00:00Z"):
        output["attempted_at"] = bad
        with pytest.raises(ValueError):
            validate_envelope(output)


FIXTURE = ROOT / "tests/fixtures/snmp/standard-switch.json"


def run_cli(*args):
    command = "import sys; from network_explorer.cli import main; sys.argv[0] = 'collect'; raise SystemExit(main())"
    return subprocess.run([sys.executable, "-c", command, *args], capture_output=True, text=True, check=True,
                          env={**os.environ, "PYTHONPATH": str(ROOT / "collector")})


def test_cli_fixture_prints_a_valid_envelope():
    result = run_cli("fixture", "--path", str(FIXTURE), "--dataset", "interfaces")
    output = json.loads(result.stdout)
    validate_envelope(output)
    assert output["status"] == "ok" and result.stderr == ""


def test_cli_configuration_error_is_a_failed_envelope(tmp_path):
    result = run_cli("collect", "--config", str(tmp_path / "missing.json"), "--device", "a", "--dataset", "device")
    output = json.loads(result.stdout)
    assert output["status"] == "failed" and output["errors"][0]["code"] == "configuration_error"


def test_cli_unexpected_error_names_only_the_exception_class(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{ community: secret-value")
    result = run_cli("fixture", "--path", str(broken), "--dataset", "device")
    output = json.loads(result.stdout)
    assert output["status"] == "failed" and output["errors"][0]["code"] == "collection_error"
    assert result.stderr.strip() == "network-explorer-collect: JSONDecodeError"
    assert "secret-value" not in result.stdout + result.stderr
