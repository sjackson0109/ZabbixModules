"""Protected local device allowlist; credentials never enter command arguments."""

import json
import os
import re
import stat
from pathlib import Path

DEVICE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


class ConfigurationError(ValueError):
    """Only fixed messages may be supplied to this exception."""


def load_device(path: str | Path, device_id: str) -> dict:
    if not DEVICE_ID.fullmatch(device_id):
        raise ConfigurationError("Device identifier is invalid.")
    # O_NOFOLLOW plus fstat avoids following symlinks and check/open races.
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
                raise ConfigurationError("Configuration must be a regular owner-only file (0600).")
            if metadata.st_uid not in (0, os.geteuid()):
                raise ConfigurationError("Configuration must be owned by root or the running account.")
            if metadata.st_size > 1_048_576:
                raise ConfigurationError("Configuration exceeds the size limit.")
            config = json.load(stream)
    except ConfigurationError:
        raise
    except (OSError, ValueError, UnicodeError):
        raise ConfigurationError("Configuration cannot be read as protected JSON.") from None
    if not isinstance(config, dict) or config.get("version") != 1 or not isinstance(config.get("devices"), dict):
        raise ConfigurationError("Configuration format is unsupported.")
    device = config["devices"].get(device_id)
    if not isinstance(device, dict):
        raise ConfigurationError("Device is not present in the local allowlist.")
    return validate_device(device)


def validate_device(raw: dict) -> dict:
    device = dict(raw)
    host = device.get("address")
    if not isinstance(host, str) or not host or len(host) > 253 or any(char.isspace() for char in host):
        raise ConfigurationError("Configured SNMP endpoint is invalid.")
    def bounded(key: str, default: int | float, minimum: int | float, maximum: int | float):
        value = device.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= value <= maximum:
            raise ConfigurationError("A collection resource limit is invalid.")
        device[key] = value
    bounded("port", 161, 1, 65535)
    bounded("timeout", 2, 0.1, 10)
    bounded("retries", 0, 0, 2)
    bounded("deadline", 25, 1, 120)
    bounded("max_varbinds", 20000, 1, 200000)
    bounded("max_output_bytes", 61440, 1024, 1048576)
    for key in ("port", "retries", "max_varbinds", "max_output_bytes"):
        if not isinstance(device[key], int):
            raise ConfigurationError("An integer collection resource limit is invalid.")
    if not isinstance(device.get("redact_remote", True), bool):
        raise ConfigurationError("Remote identity suppression flag is invalid.")
    device.setdefault("redact_remote", True)
    snmp = device.get("snmp")
    if not isinstance(snmp, dict) or snmp.get("version") not in ("2c", "3"):
        raise ConfigurationError("SNMP version must be 2c or 3.")
    if snmp["version"] == "2c":
        if not isinstance(snmp.get("community"), str) or not snmp["community"]:
            raise ConfigurationError("SNMPv2c binding is incomplete.")
    else:
        if not isinstance(snmp.get("username"), str) or not snmp["username"]:
            raise ConfigurationError("SNMPv3 binding is incomplete.")
        level = snmp.get("security_level", "authPriv")
        if level not in ("noAuthNoPriv", "authNoPriv", "authPriv"):
            raise ConfigurationError("SNMPv3 security level is unsupported.")
        if level != "noAuthNoPriv":
            if snmp.get("auth_protocol", "sha256") not in ("sha1", "sha224", "sha256", "sha384", "sha512"):
                raise ConfigurationError("SNMPv3 authentication algorithm is unsupported.")
            if not isinstance(snmp.get("auth_key"), str) or len(snmp["auth_key"]) < 8:
                raise ConfigurationError("SNMPv3 authentication binding is incomplete.")
        if level == "authPriv":
            if snmp.get("priv_protocol", "aes128") != "aes128":
                raise ConfigurationError("SNMPv3 privacy algorithm is unsupported; use AES128.")
            if not isinstance(snmp.get("priv_key"), str) or len(snmp["priv_key"]) < 8:
                raise ConfigurationError("SNMPv3 privacy binding is incomplete.")
    context = snmp.get("context", "")
    if not isinstance(context, str) or len(context.encode("utf-8")) > 32:
        raise ConfigurationError("SNMP context is invalid.")
    return device
