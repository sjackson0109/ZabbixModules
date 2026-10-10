"""Supply-chain and release-gate rules for the GitHub Actions workflows."""
from pathlib import Path
import re

import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
PINNED = re.compile(r"^[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40}$")


def steps(workflow):
    for job in workflow["jobs"].values():
        if "uses" in job:
            yield job["uses"], None
        for step in job.get("steps", []):
            if "uses" in step:
                yield step["uses"], step


def load(name):
    return yaml.safe_load((WORKFLOWS / name).read_text())


def test_third_party_actions_are_pinned_to_a_commit_with_the_version_noted():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text()
        for uses, _ in steps(yaml.safe_load(text)):
            if uses.startswith("./"):
                continue
            assert PINNED.match(uses), f"{path.name}: {uses} is not pinned to a commit SHA"
            line = next(line for line in text.splitlines() if uses in line)
            assert re.search(r"#\s*v?\d+\.\d+\.\d+\s*$", line), f"{path.name}: {uses} has no version comment"


def test_release_publishes_only_after_checks_and_every_zabbix_version():
    release = load("release.yml")
    assert release["jobs"]["checks"]["uses"] == "./.github/workflows/checks.yml"
    assert release["jobs"]["compatibility"]["uses"] == "./.github/workflows/compatibility.yml"
    assert set(release["jobs"]["publish"]["needs"]) == {"checks", "compatibility"}
    compatibility = load("compatibility.yml")
    assert compatibility["jobs"]["zabbix"]["strategy"]["matrix"]["version"] == ["7.0", "7.2", "7.4"]
    # PyYAML reads the bare "on" key as True.
    assert "workflow_call" in compatibility[True]


def test_release_attests_every_archive_it_publishes():
    publish = load("release.yml")["jobs"]["publish"]
    assert publish["permissions"]["id-token"] == "write"
    assert publish["permissions"]["attestations"] == "write"
    attest = next(step for uses, step in steps({"jobs": {"publish": publish}}) if uses.startswith("actions/attest@"))
    assert "dist/*.tar" in attest["with"]["subject-path"]


def test_checks_run_the_chromium_suite_with_a_locked_playwright():
    chromium = load("checks.yml")["jobs"]["chromium"]
    commands = [step.get("run", "") for step in chromium["steps"]]
    assert "npm ci --no-audit --no-fund" in commands
    assert "node tests/browser/widgets.runtime.cjs" in commands
    lock = (WORKFLOWS.parents[1] / "tests" / "browser" / "package-lock.json").read_text()
    assert '"node_modules/playwright"' in lock
