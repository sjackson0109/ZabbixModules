"""Transport evidence and the shared canonical envelope."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from . import __version__


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class ReadResult:
    values: dict[str, Any] = field(default_factory=dict)
    complete: bool = True
    unsupported: bool = False
    error: str | None = None


class Evidence:
    def __init__(self) -> None:
        self.reads: dict[str, ReadResult] = {}
        self.errors: list[dict[str, str]] = []

    def scalar(self, oid: str) -> Any:
        return self.reads.get(oid, ReadResult()).values.get(oid)

    def table(self, oid: str) -> dict[tuple[int, ...], Any]:
        result = {}
        for full, value in self.reads.get(oid, ReadResult()).values.items():
            if full.startswith(oid + "."):
                try:
                    result[tuple(int(part) for part in full[len(oid) + 1:].split("."))] = value
                except ValueError:
                    self.error("malformed_index", "A table contains a nonnumeric index.")
        return result

    def error(self, code: str, message: str) -> None:
        # Error messages are fixed strings. Never interpolate raw SNMP/config data.
        error = {"code": code, "message": message}
        if error not in self.errors:
            self.errors.append(error)


def envelope(dataset: str, attempted_at: str | None = None, generation_id: str | None = None,
             method: str = "python_snmp") -> dict:
    return {
        "schema_version": "1.0",
        "dataset": dataset,
        "generation_id": generation_id or uuid4().hex,
        "attempted_at": attempted_at or utc_now(),
        "observed_at": None,
        "status": "failed",
        "complete": False,
        "source": {"method": method, "adapter": "standard-mibs", "version": __version__},
        "capability": {"state": "unknown", "reason": None},
        "errors": [],
        "data": [],
    }
