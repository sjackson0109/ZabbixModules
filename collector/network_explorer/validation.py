"""Canonical and future agent contracts; no agent execution/ingestion endpoint."""

import json
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from importlib.resources import files

from jsonschema import Draft202012Validator, FormatChecker

RFC3339 = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|([+-])(\d{2}):(\d{2}))")
FORMATS = FormatChecker()


def parse_date_time(value) -> datetime | None:
    """Parse an RFC 3339 date-time into an aware datetime, or return None.

    datetime.fromisoformat on Python 3.10 rejects fractions other than 3 or 6
    digits, and its errors echo the input, so parse the regex groups instead.
    """
    if not isinstance(value, str):
        return None
    match = RFC3339.fullmatch(value)
    if match is None:
        return None
    year, month, day, hour, minute, second, fraction, zone, sign, off_hour, off_minute = match.groups()
    microsecond = int((fraction or "0")[:6].ljust(6, "0"))
    try:
        if zone == "Z":
            tz = timezone.utc
        else:
            if int(off_hour) > 23 or int(off_minute) > 59:
                return None
            offset = timedelta(hours=int(off_hour), minutes=int(off_minute))
            tz = timezone(-offset if sign == "-" else offset)
        return datetime(int(year), int(month), int(day), int(hour), int(minute), int(second), microsecond, tz)
    except ValueError:
        return None


@FORMATS.checks("date-time")
def is_date_time(value) -> bool:
    """jsonschema skips date-time unless an optional package is installed; check it without one."""
    if not isinstance(value, str):
        return True
    return parse_date_time(value) is not None


@lru_cache(maxsize=1)
def validator():
    schema = json.loads(files("network_explorer").joinpath("envelope.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FORMATS)


def validate_envelope(value: dict) -> None:
    if not validator().is_valid(value):
        # Never expose a jsonschema exception which echoes source data.
        raise ValueError("Canonical envelope validation failed.")


def validate_agent_snapshot(value: dict, expected_source_instance: str,
                            previous_generation: str | None = None) -> dict:
    """Reserve ownership/time/replay rules for a later authenticated adapter.

    Calling this function does not authenticate an agent. The future ingestion
    transport must bind expected_source_instance to an authorised owning host.
    """
    validate_envelope(value)
    source = value["source"]
    if source["method"] != "agent" or source.get("source_instance") != expected_source_instance:
        raise ValueError("Agent source does not match the authorised owner.")
    if source.get("collection_mode") not in ("once", "periodic"):
        raise ValueError("Agent collection mode is missing.")
    if value["generation_id"] == previous_generation:
        raise ValueError("Agent snapshot was already accepted.")
    for field in ("attempted_at", "observed_at"):
        if value.get(field):
            time = parse_date_time(value[field])
            if time is None:
                # Fixed text: never echo source data.
                raise ValueError("Agent timestamp is not a valid RFC 3339 date-time.")
            if time > datetime.now(timezone.utc) + timedelta(minutes=5):
                raise ValueError("Agent timestamp exceeds permitted clock skew.")
    return value
