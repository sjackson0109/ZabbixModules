#!/usr/bin/env python3
"""Manage disposable local Zabbix labs without exposing generated credentials."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def settings(version: str) -> dict:
    lock = json.loads((HERE / "images.lock.json").read_text())
    row = lock["versions"][version]
    state = HERE / ".state" / version
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state, 0o700)
    credentials = state / "credentials.json"
    if not credentials.exists():
        fd = os.open(credentials, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump({"database": secrets.token_hex(24), "admin": secrets.token_urlsafe(30)}, stream)
    keys = json.loads(credentials.read_text())
    suffix = version.replace(".", "")
    http_port = {"7.0": 18070, "7.2": 18072, "7.4": 18074}[version]
    sender_port = {"7.0": 10070, "7.2": 10072, "7.4": 10074}[version]
    values = {
        "DATABASE_IMAGE": lock["database"]["image"],
        "SERVER_IMAGE": row["server"]["image"],
        "WEB_IMAGE": row["web"]["image"],
        "PROXY_IMAGE": row["proxy"]["image"],
        "POSTGRES_PASSWORD": keys["database"],
        "HTTP_PORT": str(http_port),
        "SENDER_PORT": str(sender_port),
    }
    envfile = state / "runtime.env"
    fd = os.open(envfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("".join(f"{k}={v}\n" for k, v in values.items()))
    return {
        "version": version, "patch": row["patch"], "state": state,
        "envfile": envfile, "credentials": keys, "project": f"ne{suffix}",
        "url": f"http://127.0.0.1:{http_port}", "sender_port": sender_port,
    }


def compose(config: dict, *args: str, capture: bool = False) -> subprocess.CompletedProcess:
    command = ["docker", "compose", "--project-name", config["project"],
               "--env-file", str(config["envfile"]), "-f", str(HERE / "compose.yaml"), *args]
    return subprocess.run(command, check=True, text=True, capture_output=capture)


def api_request(url: str, method: str, params: object, token: str | None = None) -> object:
    data = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url + "/api_jsonrpc.php", data, headers)
    # The lab is deliberately loopback-only; ignore external HTTP proxy configuration.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    # Template imports run inside one request and can take longer than ordinary calls on a busy host.
    timeout = 120 if method == "configuration.import" else 10
    with opener.open(request, timeout=timeout) as response:
        result = json.load(response)
    if "error" in result:
        raise RuntimeError(f"{method}: {result['error']}")
    return result["result"]


def ready(config: dict, timeout: int = 180) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            version = api_request(config["url"], "apiinfo.version", {})
            if version != config["patch"]:
                raise RuntimeError(f"Expected {config['patch']}, got {version}")
            print(f"Zabbix {version}: API ready on loopback.", flush=True)
            return
        except Exception as error:
            if time.monotonic() >= deadline:
                raise RuntimeError("Zabbix API did not become ready; inspect service status/logs.") from error
            time.sleep(2)


def login(config: dict) -> str:
    password = config["credentials"]["admin"]
    marker = config["state"] / "admin-configured"
    if not marker.exists():
        token = api_request(config["url"], "user.login", {"username": "Admin", "password": "zabbix"})
        user = api_request(config["url"], "user.get", {"output": ["userid"], "filter": {"username": "Admin"}}, token)
        api_request(config["url"], "user.update", {
            "userid": user[0]["userid"], "passwd": password, "current_passwd": "zabbix",
        }, token)
        marker.touch(mode=0o600)
    return api_request(config["url"], "user.login", {"username": "Admin", "password": password})


def install_modules(config: dict) -> None:
    container = compose(config, "ps", "-q", "web", capture=True).stdout.strip()
    frontend = ROOT / "frontend"
    for module in sorted(frontend.iterdir()):
        manifest = module / "manifest.json"
        if not manifest.is_file():
            continue
        destination = "/usr/share/zabbix/modules/" + module.name
        subprocess.run(["docker", "exec", "-u", "0", container, "mkdir", "-p", destination], check=True)
        subprocess.run(["docker", "cp", str(module) + "/.", container + ":" + destination], check=True)
        subprocess.run(["docker", "exec", "-u", "0", container, "sh", "-c",
                        'chmod -R a+rX "$1"; chown -R zabbix:zabbix "$1"', "sh", destination], check=True)
    token = login(config)
    installed = {row["id"]: row for row in api_request(config["url"], "module.get", {"output": "extend"}, token)}
    for module in sorted(frontend.iterdir()):
        manifest_path = module / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text())
        if manifest["id"] in installed:
            api_request(config["url"], "module.update", {"moduleid": installed[manifest["id"]]["moduleid"], "status": 1}, token)
        else:
            api_request(config["url"], "module.create", {
                "id": manifest["id"], "relative_path": "modules/" + module.name,
                "status": 1, "config": manifest.get("config", {}),
            }, token)
    print("Frontend modules copied and registered through the Zabbix API.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["start", "wait", "install-modules", "status", "stop", "destroy"])
    parser.add_argument("--version", choices=["7.0", "7.2", "7.4"], default="7.0")
    args = parser.parse_args()
    config = settings(args.version)
    if args.operation == "start":
        compose(config, "up", "-d")
        ready(config)
        token = login(config)
        if not api_request(config["url"], "proxy.get", {"output": ["proxyid"], "filter": {"name": "ne-lab-proxy"}}, token):
            api_request(config["url"], "proxy.create", {"name": "ne-lab-proxy", "operating_mode": 0}, token)
    elif args.operation == "wait":
        ready(config)
    elif args.operation == "install-modules":
        ready(config)
        install_modules(config)
    elif args.operation == "status":
        compose(config, "ps")
    elif args.operation == "stop":
        compose(config, "stop")
    else:
        compose(config, "down", "--volumes", "--remove-orphans")
        marker = config["state"] / "admin-configured"
        marker.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
