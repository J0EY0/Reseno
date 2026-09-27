import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SHARD_COUNT = 4
COLLECT_NODEIDS = """
import json
import sys
from pathlib import Path

import pytest

class Collector:
    def pytest_collection_finish(self, session):
        Path(sys.argv[1]).write_text(
            json.dumps([item.nodeid for item in session.items]), encoding="utf-8"
        )

raise SystemExit(pytest.main(sys.argv[2:], plugins=[Collector()]))
"""
SYNTHETIC_MODULE = """
import hashlib
import os
from pathlib import Path

import pytest

@pytest.mark.browser_smoke
@pytest.mark.parametrize("value", range(9))
def test_selected(value, request):
    nodeid = request.node.nodeid
    filename = hashlib.sha256(nodeid.encode()).hexdigest()
    with (Path(os.environ["SHARD_EXECUTION_DIR"]) / filename).open("x") as output:
        output.write(nodeid)

def test_unselected():
    pytest.fail("The browser smoke marker must exclude this test.")
"""


def run_pytest(
    workdir: Path,
    artifacts: Path,
    name: str,
    args: list[str],
    *,
    group: int | None = None,
    splits: int = SHARD_COUNT,
    collect: bool = False,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    durations = artifacts / f"{name}-durations.json"
    durations.write_text("{}", encoding="utf-8")
    env = dict(os.environ)
    for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD"):
        env.pop(key, None)
    env.update(extra_env or {})
    command = [sys.executable, "-m", "pytest"]
    if collect:
        command = [
            sys.executable,
            "-c",
            COLLECT_NODEIDS,
            str(artifacts / f"{name}-nodeids.json"),
        ]
        args = [*args, "--collect-only"]
    if group is not None:
        args = [*args, "--splits", str(splits), "--group", str(group)]
    return subprocess.run(
        [
            *command,
            *args,
            "-m",
            "browser_smoke",
            "--strict-markers",
            "--splitting-algorithm",
            "duration_based_chunks",
            "--durations-path",
            str(durations),
            "-q",
        ],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def collect_nodeids(
    workdir: Path,
    artifacts: Path,
    name: str,
    args: list[str],
    *,
    group: int | None = None,
) -> list[str]:
    result = run_pytest(workdir, artifacts, name, args, group=group, collect=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads((artifacts / f"{name}-nodeids.json").read_text())


def test_browser_smoke_shards_cover_the_collection_exactly_once(tmp_path):
    baseline = collect_nodeids(BACKEND_ROOT, tmp_path, "baseline", ["tests/e2e"])
    shards = [
        collect_nodeids(
            BACKEND_ROOT,
            tmp_path,
            f"shard-{group}",
            ["tests/e2e"],
            group=group,
        )
        for group in range(1, SHARD_COUNT + 1)
    ]

    assert baseline
    assert len(baseline) == len(set(baseline))
    assert all(shards)
    assert Counter(item for shard in shards for item in shard) == Counter(baseline)
    assert [item for shard in shards for item in shard] == baseline
    assert max(map(len, shards)) - min(map(len, shards)) <= SHARD_COUNT - 1


@pytest.fixture
def synthetic_suite(tmp_path):
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    browser_smoke: selected browser checks\n",
        encoding="utf-8",
    )
    for name in ("test_first.py", "test_second.py"):
        (suite / name).write_text(SYNTHETIC_MODULE, encoding="utf-8")
    return suite


def test_browser_shards_execute_with_xdist_without_duplicates_or_omissions(
    tmp_path, synthetic_suite
):
    baseline = collect_nodeids(synthetic_suite, tmp_path, "baseline", ["."])
    executions = tmp_path / "executions"
    executions.mkdir()

    for group in range(1, SHARD_COUNT + 1):
        result = run_pytest(
            synthetic_suite,
            tmp_path,
            f"shard-{group}",
            [".", "-n", "2", "--dist", "loadscope", "--max-worker-restart=0"],
            group=group,
            extra_env={"SHARD_EXECUTION_DIR": str(executions)},
        )
        assert result.returncode == 0, result.stdout + result.stderr

    executed = [path.read_text() for path in executions.iterdir()]
    assert baseline
    assert Counter(executed) == Counter(baseline)


@pytest.mark.parametrize(("splits", "group"), [(4, 0), (4, 5), (0, 1)])
def test_browser_sharding_rejects_invalid_groups(
    tmp_path, synthetic_suite, splits, group
):
    result = run_pytest(
        synthetic_suite,
        tmp_path,
        "invalid",
        ["."],
        group=group,
        splits=splits,
        collect=True,
    )

    assert result.returncode == pytest.ExitCode.USAGE_ERROR
    assert "ERROR:" in result.stderr
    assert not (tmp_path / "invalid-nodeids.json").exists()
