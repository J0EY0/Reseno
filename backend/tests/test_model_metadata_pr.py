import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github/scripts/model-metadata-pr.sh"
SNAPSHOT = "backend/app/services/model_metadata_snapshot.json"
UPDATE_BRANCH = "automation/model-metadata"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


@dataclass
class MetadataRepository:
    directory: Path
    remote: Path
    runner: Path
    environment: dict[str, str]
    main_head: str

    def git(self, *arguments: str, remote: bool = False) -> str:
        result = subprocess.run(
            ["git", *arguments],
            cwd=self.remote if remote else self.directory,
            env=self.environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return result.stdout.strip()

    def write_snapshot(self, context_tokens: int) -> None:
        path = self.directory / SNAPSHOT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"contextWindowTokens": context_tokens}) + "\n",
            encoding="utf-8",
        )

    def existing_update(
        self, *, manual_changes: bool = False, manual_snapshot: bool = False
    ) -> str:
        self.git("switch", "-c", UPDATE_BRANCH)
        self.write_snapshot(200_000)
        self.git("add", SNAPSHOT)
        self.git(
            "-c", "user.name=github-actions[bot]", "-c", f"user.email={BOT_EMAIL}",
            "commit", "-m", "Refresh model metadata",
        )
        if manual_changes:
            (self.directory / "manual-test.py").write_text(
                "assert 1 + 1 == 2\n", encoding="utf-8"
            )
            self.git("add", "manual-test.py")
            self.git("commit", "-m", "Add a manual regression test")
        if manual_snapshot:
            self.write_snapshot(250_000)
            self.git("add", SNAPSHOT)
            self.git("commit", "-m", "Correct a model limit manually")
        head = self.git("rev-parse", "HEAD")
        self.git("push", "origin", UPDATE_BRANCH)
        (self.runner / "model-metadata-previous.json").write_bytes(
            (self.directory / SNAPSHOT).read_bytes()
        )
        self.git("switch", "main")
        self.git("branch", "-D", UPDATE_BRANCH)
        self.environment.update(PREVIOUS_HEAD=head, EXISTING_PR="16")
        return head

    def remote_head(self) -> str:
        return self.git("rev-parse", f"refs/heads/{UPDATE_BRANCH}", remote=True)

    def gh_calls(self) -> list[dict[str, object]]:
        path = self.runner / "gh-calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    def run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=self.directory,
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=30,
        )


@pytest.fixture
def metadata_repository(tmp_path: Path) -> MetadataRepository:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_TERMINAL_PROMPT="0",
    )
    remote = tmp_path / "remote.git"
    directory = tmp_path / "checkout"
    for arguments in (
        ["init", "--bare", "--initial-branch=main", str(remote)],
        ["clone", str(remote), str(directory)],
    ):
        subprocess.run(
            ["git", *arguments],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    runner = tmp_path / "runner"
    runner.mkdir()
    (runner / "model-metadata-pr.md").write_text(
        "Model metadata changes\n\n- Context: 100000 → 200000\n",
        encoding="utf-8",
    )
    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    gh = binary_directory / "gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "arguments = sys.argv[1:]\n"
        "body = pathlib.Path(arguments[arguments.index('--body-file') + 1])\n"
        "record = {'args': arguments, 'body': body.read_text()}\n"
        "path = pathlib.Path(os.environ['RUNNER_TEMP']) / 'gh-calls.jsonl'\n"
        "with path.open('a') as output:\n"
        "    output.write(json.dumps(record) + '\\n')\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    environment.update(
        PATH=f"{binary_directory}{os.pathsep}{environment['PATH']}",
        RUNNER_TEMP=str(runner),
        PREVIOUS_HEAD="",
        EXISTING_PR="",
        UPDATE_BRANCH=UPDATE_BRANCH,
        BASE_BRANCH="main",
    )
    repository = MetadataRepository(directory, remote, runner, environment, "")
    repository.git("config", "user.name", "Metadata Test")
    repository.git("config", "user.email", "metadata-test@example.com")
    repository.write_snapshot(100_000)
    repository.git("add", SNAPSHOT)
    repository.git("commit", "-m", "Initial snapshot")
    repository.git("push", "origin", "main")
    repository.main_head = repository.git("rev-parse", "HEAD")
    return repository


def test_first_update_pushes_only_snapshot_and_creates_pr(metadata_repository):
    repository = metadata_repository
    repository.write_snapshot(200_000)

    result = repository.run()

    assert result.returncode == 0, result.stdout + result.stderr
    head = repository.remote_head()
    assert head != repository.main_head
    assert repository.git("rev-parse", "main", remote=True) == repository.main_head
    assert repository.git(
        "diff", "--name-only", repository.main_head, head, remote=True
    ) == SNAPSHOT
    assert json.loads(repository.git("show", f"{head}:{SNAPSHOT}", remote=True)) == {
        "contextWindowTokens": 200_000
    }
    calls = repository.gh_calls()
    assert len(calls) == 1
    assert calls[0]["args"] == [
        "pr", "create", "--base", "main", "--head", UPDATE_BRANCH,
        "--title", "chore(models): refresh bundled model metadata",
        "--body-file", str(repository.runner / "model-metadata-pr.md"),
    ]
    assert "Context: 100000 → 200000" in calls[0]["body"]
    assert "Validation: model metadata" in calls[0]["body"]


def test_unchanged_open_pr_preserves_head_and_updates_report(metadata_repository):
    repository = metadata_repository
    previous_head = repository.existing_update()
    repository.write_snapshot(200_000)

    result = repository.run()

    assert result.returncode == 0, result.stdout + result.stderr
    assert repository.remote_head() == previous_head
    assert repository.git("rev-parse", "HEAD") == repository.main_head
    assert repository.git("branch", "--show-current") == "main"
    calls = repository.gh_calls()
    assert len(calls) == 1
    assert calls[0]["args"] == [
        "pr", "edit", "16", "--body-file",
        str(repository.runner / "model-metadata-pr.md"),
    ]
    assert "Context: 100000 → 200000" in calls[0]["body"]


def test_changed_open_pr_pushes_snapshot_and_updates_report(metadata_repository):
    repository = metadata_repository
    previous_head = repository.existing_update()
    repository.write_snapshot(300_000)
    (repository.runner / "model-metadata-pr.md").write_text(
        "Model metadata changes\n\n- Context: 100000 → 300000\n",
        encoding="utf-8",
    )

    result = repository.run()

    assert result.returncode == 0, result.stdout + result.stderr
    head = repository.remote_head()
    assert head != previous_head
    assert json.loads(repository.git("show", f"{head}:{SNAPSHOT}", remote=True)) == {
        "contextWindowTokens": 300_000
    }
    calls = repository.gh_calls()
    assert len(calls) == 1
    assert calls[0]["args"][:3] == ["pr", "edit", "16"]
    assert "Context: 100000 → 300000" in calls[0]["body"]


def test_manual_pr_changes_are_preserved_without_publishing(metadata_repository):
    repository = metadata_repository
    previous_head = repository.existing_update(manual_changes=True)
    repository.write_snapshot(300_000)

    result = repository.run()

    assert result.returncode != 0
    assert "manual changes" in result.stdout + result.stderr
    assert repository.remote_head() == previous_head
    assert repository.git(
        "show", f"{previous_head}:manual-test.py", remote=True
    ) == "assert 1 + 1 == 2"
    assert repository.gh_calls() == []


def test_concurrent_remote_update_is_rejected_by_lease(metadata_repository):
    repository = metadata_repository
    previous_head = repository.existing_update()
    repository.git("switch", "-c", "concurrent-update", previous_head)
    repository.write_snapshot(400_000)
    repository.git("add", SNAPSHOT)
    repository.git("commit", "-m", "Concurrent metadata change")
    concurrent_head = repository.git("rev-parse", "HEAD")
    repository.git("push", "origin", f"HEAD:refs/heads/{UPDATE_BRANCH}")
    repository.git("switch", "main")
    repository.write_snapshot(300_000)

    result = repository.run()

    assert result.returncode != 0
    assert repository.remote_head() == concurrent_head
    assert "stale info" in result.stdout + result.stderr
    assert repository.gh_calls() == []


def test_manual_snapshot_change_is_preserved_without_publishing(metadata_repository):
    repository = metadata_repository
    previous_head = repository.existing_update(manual_snapshot=True)
    repository.write_snapshot(300_000)

    result = repository.run()

    assert result.returncode != 0
    assert "manual changes" in result.stdout + result.stderr
    assert repository.remote_head() == previous_head
    assert json.loads(repository.git(
        "show", f"{previous_head}:{SNAPSHOT}", remote=True
    )) == {"contextWindowTokens": 250_000}
    assert repository.gh_calls() == []


def test_rejected_push_does_not_create_pr(metadata_repository):
    repository = metadata_repository
    hook = repository.remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    repository.write_snapshot(200_000)

    result = repository.run()

    assert result.returncode != 0
    assert "pre-receive hook declined" in result.stdout + result.stderr
    assert repository.git("branch", "--list", UPDATE_BRANCH, remote=True) == ""
    assert repository.gh_calls() == []
