"""Canonical and future agent contracts; no agent execution/ingestion endpoint."""

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from importlib.resources import files

from jsonschema import Draft202012Validator, FormatChecker


@lru_cache(maxsize=1)
def validator():
    schema = json.loads(files("network_explorer").joinpath("envelope.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


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
            time = datetime.fromisoformat(value[field].replace("Z", "+00:00"))
            if time > datetime.now(timezone.utc) + timedelta(minutes=5):
                raise ValueError("Agent timestamp exceeds permitted clock skew.")
    return value
