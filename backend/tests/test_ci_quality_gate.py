import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parents[2] / ".github/scripts/quality-gate.py"


def gate_results(*, checks=True, image=True, container=True, browser=True):
    return {
        "changes": {
            "result": "success",
            "outputs": {
                "run_checks": str(checks).lower(),
                "image_inputs": str(image).lower(),
                "container_validation": str(container).lower(),
            },
        },
        "backend": {"result": "success" if checks else "skipped"},
        "frontend": {"result": "success" if checks else "skipped"},
        "browser-smoke": {"result": "success" if checks and browser else "skipped"},
        "container-validation": {
            "result": "success" if container and browser else "skipped"
        },
    }


def run_gate(
    needs, *, event="pull_request", git_ref="refs/pull/12/merge", default="main"
):
    return subprocess.run(
        [sys.executable, str(GATE)],
        env={
            **os.environ,
            "NEEDS_JSON": json.dumps(needs),
            "EVENT_NAME": event,
            "GIT_REF": git_ref,
            "DEFAULT_BRANCH": default,
        },
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("event", "git_ref", "default", "flags", "browser"),
    [
        ("pull_request", "refs/pull/12/merge", "main", (False, False, False), True),
        ("push", "refs/heads/main", "main", (False, False, False), True),
        ("pull_request", "refs/pull/12/merge", "main", (True, False, False), True),
        ("pull_request", "refs/pull/12/merge", "main", (True, False, True), True),
        ("pull_request", "refs/pull/12/merge", "main", (True, True, True), True),
        ("push", "refs/heads/main", "main", (True, False, False), True),
        ("push", "refs/heads/main", "main", (True, False, True), True),
        ("push", "refs/heads/main", "main", (True, True, True), True),
        ("push", "refs/heads/topic", "main", (True, True, True), False),
        ("push", "refs/heads/develop", "develop", (True, True, True), True),
        ("push", "refs/tags/v1.2.3", "main", (True, True, True), True),
        ("push", "refs/tags/preview", "main", (True, True, True), False),
    ],
)
def test_gate_accepts_success_and_only_applicable_skips(
    event, git_ref, default, flags, browser
):
    checks, image, container = flags
    result = run_gate(
        gate_results(checks=checks, image=image, container=container, browser=browser),
        event=event,
        git_ref=git_ref,
        default=default,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "job", ["changes", "backend", "frontend", "browser-smoke", "container-validation"]
)
@pytest.mark.parametrize("status", ["failure", "cancelled", "skipped"])
def test_gate_rejects_unsuccessful_required_jobs(job, status):
    needs = gate_results()
    needs[job]["result"] = status
    result = run_gate(needs)
    assert result.returncode == 1
    assert "::error::" in result.stderr


@pytest.mark.parametrize("name", ["run_checks", "image_inputs", "container_validation"])
@pytest.mark.parametrize("invalid", [None, "", "TRUE", True])
def test_gate_rejects_invalid_filter_output(name, invalid):
    needs = gate_results()
    needs["changes"]["outputs"][name] = invalid
    assert run_gate(needs).returncode == 1


@pytest.mark.parametrize(
    "missing",
    ["changes", "backend", "frontend", "browser-smoke", "container-validation"],
)
def test_gate_rejects_missing_job(missing):
    needs = gate_results()
    del needs[missing]
    assert run_gate(needs).returncode == 1


@pytest.mark.parametrize("flags", [(True, True, False), (False, False, True)])
def test_gate_rejects_inconsistent_filter_outputs(flags):
    checks, image, container = flags
    needs = gate_results(checks=checks, image=image, container=container)
    assert run_gate(needs).returncode == 1


def test_release_tag_cannot_skip_validation_using_path_filters():
    needs = gate_results(checks=False, image=False, container=False)
    assert run_gate(needs, event="push", git_ref="refs/tags/v1.2.3").returncode == 1


def test_gate_rejects_unexpected_job_execution():
    needs = gate_results(checks=False, image=False, container=False)
    needs["backend"]["result"] = "success"
    assert run_gate(needs).returncode == 1
