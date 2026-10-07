"""Fixed dataset CLI; SNMP credentials accepted only through protected config."""

import argparse
import asyncio

from .collect import DATASETS, collect, serialize
from .config import ConfigurationError, load_device
from .models import envelope
from .transport import FixtureTransport, SnmpTransport
from .validation import validate_envelope


async def run(args) -> dict:
    transport = None
    try:
        if args.command == "fixture":
            transport = FixtureTransport.from_file(args.path)
            redact = not args.show_remote
        else:
            device = load_device(args.config, args.device)
            args.max_output_bytes = device["max_output_bytes"]
            transport = SnmpTransport(device)
            redact = device["redact_remote"]
        output = await collect(transport, args.dataset, redact_remote=redact)
        validate_envelope(output)
        return output
    except ConfigurationError as error:
        output = envelope(args.dataset)
        output["errors"] = [{"code": "configuration_error", "message": str(error)}]
        return output
    except Exception:
        output = envelope(args.dataset, method="fixture" if args.command == "fixture" else "python_snmp")
        output["errors"] = [{"code": "collection_error", "message": "Collection could not produce a validated dataset."}]
        return output
    finally:
        if transport is not None:
            await transport.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Network Explorer read-only collector")
    commands = parser.add_subparsers(dest="command", required=True)
    live = commands.add_parser("collect", help="Collect an allowlisted device using protected local configuration")
    live.add_argument("--config", default="/etc/network-explorer/devices.json")
    live.add_argument("--device", required=True)
    live.add_argument("--dataset", choices=DATASETS, required=True)
    fixture = commands.add_parser("fixture", help="Normalize an explicitly synthetic SNMP fixture")
    fixture.add_argument("--path", required=True)
    fixture.add_argument("--dataset", choices=DATASETS, required=True)
    fixture.add_argument("--show-remote", action="store_true", help="Preserve synthetic remote identities")
    args = parser.parse_args()
    output = asyncio.run(run(args))
    # Envelope status is authoritative: external checks may ignore process exit status.
    print(serialize(output, getattr(args, "max_output_bytes", 61440)))
    return 0
