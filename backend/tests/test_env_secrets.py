import multiprocessing
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from dotenv import dotenv_values

from app.env_secrets import ensure_env_secrets

KEY_NAMES = {"RESENO_MASTER_KEY", "RESENO_JWT_SECRET"}


def _configured() -> dict[str, str]:
    return {
        "RESENO_MASTER_KEY": Fernet.generate_key().decode("ascii"),
        "RESENO_JWT_SECRET": "test-secret-" * 4,
    }


def _read_pair(path: Path) -> dict[str, str | None]:
    values = dotenv_values(path, interpolate=False)
    return {key: values.get(key) for key in KEY_NAMES}


def _initialize_in_process(env_path: str, barrier: Any, results: Any) -> None:
    barrier.wait(timeout=10)
    try:
        results.put(("ok", ensure_env_secrets(Path(env_path), {})))
    except Exception as exc:
        results.put(("error", str(exc)))


def test_initialization_persists_one_complete_private_pair(tmp_path: Path) -> None:
    path = tmp_path / "config" / ".env"
    first = ensure_env_secrets(path, {})
    assert set(first) == KEY_NAMES
    Fernet(first["RESENO_MASTER_KEY"].encode("ascii"))
    assert len(first["RESENO_JWT_SECRET"].encode("utf-8")) >= 32
    assert _read_pair(path) == first
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert ensure_env_secrets(path, {}) == first
    assert set(path.parent.iterdir()) == {path, Path(f"{path}.lock")}


def test_generation_preserves_existing_config_and_persists_the_explicit_key(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".env"
    original = (
        "# startup configuration\n"
        "APP_DATA_DIR='/path with spaces'\n"
        'CUSTOM_VALUE="first line\nsecond line ${UNCHANGED}"\n'
        "RESENO_MASTER_KEY=\n"
        "RESENO_JWT_SECRET=\n"
        "# final comment"
    )
    path.write_text(original)
    master = _configured()["RESENO_MASTER_KEY"]
    pair = ensure_env_secrets(path, {"RESENO_MASTER_KEY": master})
    assert pair["RESENO_MASTER_KEY"] == master
    assert _read_pair(path) == pair
    assert "# final comment" in path.read_text()
    assert original.split("RESENO_MASTER_KEY=", 1)[0] in path.read_text()
    assert dotenv_values(path, interpolate=False)["CUSTOM_VALUE"] == (
        "first line\nsecond line ${UNCHANGED}"
    )
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "jwt_secret",
    [
        "quoted-'secret-" * 4,
        "backslash-\\\\secret-" * 4,
        "quoted-\\'secret-${LITERAL}-" * 3,
        "含有中文的密钥" * 5,
    ],
)
def test_generation_preserves_configured_secret_values_exactly(
    tmp_path: Path, jwt_secret: str
) -> None:
    path = tmp_path / ".env"
    pair = ensure_env_secrets(path, {"RESENO_JWT_SECRET": jwt_secret})
    assert pair["RESENO_JWT_SECRET"] == jwt_secret
    assert _read_pair(path) == pair
    assert ensure_env_secrets(path, {}) == pair


@pytest.mark.parametrize(
    "configured",
    [
        {"RESENO_MASTER_KEY": "invalid-master-key"},
        {"RESENO_MASTER_KEY": "非 ASCII master key"},
        {"RESENO_JWT_SECRET": "too-short-secret"},
        {"RESENO_JWT_SECRET": "\ud800"},
    ],
)
def test_invalid_configuration_does_not_create_files(
    tmp_path: Path, configured: dict[str, str]
) -> None:
    with pytest.raises(RuntimeError) as error:
        ensure_env_secrets(tmp_path / ".env", configured)
    assert not list(tmp_path.iterdir())
    for value in configured.values():
        assert value not in str(error.value)
    assert error.value.__suppress_context__


@pytest.mark.parametrize(
    "payload",
    [
        b"\xff\xfe",
        b"RESENO_MASTER_KEY=invalid",
        b"RESENO_JWT_SECRET=too-short-secret",
    ],
)
def test_invalid_existing_key_is_never_rebuilt(tmp_path: Path, payload: bytes) -> None:
    path = tmp_path / ".env"
    path.write_bytes(payload)
    with pytest.raises(RuntimeError):
        ensure_env_secrets(path, {})
    assert path.read_bytes() == payload
    assert list(tmp_path.iterdir()) == [path]


def test_complete_environment_keys_require_no_configuration_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = _configured()

    def unexpected_file_access(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Complete environment keys do not need a config file")

    monkeypatch.setattr(Path, "read_text", unexpected_file_access)
    monkeypatch.setattr(Path, "mkdir", unexpected_file_access)
    assert ensure_env_secrets(tmp_path / ".env", configured) == configured
    assert not list(tmp_path.iterdir())


def test_existing_pair_is_read_only_and_empty_environment_values_are_unspecified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".env"
    pair = ensure_env_secrets(path, {})
    before = path.read_bytes()
    path.chmod(0o400)
    tmp_path.chmod(0o500)

    def unexpected_write(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Complete keys must not need a writable directory")

    monkeypatch.setattr(Path, "mkdir", unexpected_write)
    monkeypatch.setattr(os, "replace", unexpected_write)
    try:
        assert ensure_env_secrets(path, dict.fromkeys(KEY_NAMES, "")) == pair
        assert path.read_bytes() == before
        assert stat.S_IMODE(path.stat().st_mode) == 0o400
    finally:
        tmp_path.chmod(0o700)
        path.chmod(0o600)


def test_environment_override_does_not_modify_complete_file(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    pair = ensure_env_secrets(path, {})
    before = path.read_bytes()
    replacement = Fernet.generate_key().decode("ascii")
    assert ensure_env_secrets(path, {"RESENO_MASTER_KEY": replacement}) == {
        **pair,
        "RESENO_MASTER_KEY": replacement,
    }
    assert path.read_bytes() == before


@pytest.mark.parametrize("database_name", ["app.db", "auth.db"])
@pytest.mark.parametrize("configured_key", [None, "RESENO_MASTER_KEY"])
def test_missing_key_for_existing_database_is_never_generated(
    tmp_path: Path, database_name: str, configured_key: str | None
) -> None:
    path = tmp_path / ".env"
    database_path = tmp_path / database_name
    database_path.write_bytes(b"existing data")
    configured = {}
    if configured_key:
        configured[configured_key] = _configured()[configured_key]
    with pytest.raises(RuntimeError, match="missing for existing data"):
        ensure_env_secrets(path, configured, existing_data_paths=(database_path,))
    assert not path.exists()
    assert database_path.read_bytes() == b"existing data"


def test_complete_file_keys_are_usable_with_existing_database(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    pair = ensure_env_secrets(path, {})
    database_path = tmp_path / "app.db"
    database_path.write_bytes(b"existing data")
    assert ensure_env_secrets(path, {}, existing_data_paths=(database_path,)) == pair


def test_empty_database_does_not_prevent_initialization(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    database_path = tmp_path / "app.db"
    database_path.touch()
    pair = ensure_env_secrets(path, {}, existing_data_paths=(database_path,))
    assert _read_pair(path) == pair
    assert database_path.read_bytes() == b""


@pytest.mark.parametrize("existing_file", [False, True])
def test_multiple_processes_share_the_atomically_published_pair(
    tmp_path: Path, existing_file: bool
) -> None:
    path = tmp_path / ".env"
    if existing_file:
        path.write_text(
            "APP_DATA_DIR=/test/data\nRESENO_MASTER_KEY=\nRESENO_JWT_SECRET=\n"
        )
    context = multiprocessing.get_context("spawn")
    process_count = 6
    barrier = context.Barrier(process_count)
    results = context.Queue()
    processes = [
        context.Process(
            target=_initialize_in_process, args=(str(path), barrier, results)
        )
        for _ in range(process_count)
    ]
    try:
        for process in processes:
            process.start()
        outcomes = [results.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
        pairs = [result for status, result in outcomes if status == "ok"]
        assert len(pairs) == process_count
        assert all(pair == pairs[0] for pair in pairs)
        assert _read_pair(path) == pairs[0]
        assert set(path.parent.iterdir()) == {path, Path(f"{path}.lock")}
        if existing_file:
            assert (
                dotenv_values(path, interpolate=False)["APP_DATA_DIR"] == "/test/data"
            )
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(timeout=3)
        results.close()
        results.join_thread()


@pytest.mark.parametrize("existing_file", [False, True])
def test_publication_failure_leaves_no_partial_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing_file: bool
) -> None:
    path = tmp_path / ".env"
    before = b"APP_DATA_DIR=/test/data\nRESENO_MASTER_KEY=\nRESENO_JWT_SECRET=\n"
    if existing_file:
        path.write_bytes(before)
    original_replace = os.replace

    def reject_publication(source: Path, target: Path) -> None:
        if Path(target) == path:
            assert set(_read_pair(source)) == KEY_NAMES
            assert all(_read_pair(source).values())
            assert stat.S_IMODE(source.stat().st_mode) == 0o600
            raise OSError("Publication unavailable")
        original_replace(source, target)

    monkeypatch.setattr(os, "replace", reject_publication)
    with pytest.raises(OSError, match="Publication unavailable"):
        ensure_env_secrets(path, {})
    if existing_file:
        assert path.read_bytes() == before
    else:
        assert not path.exists()
    assert not list(tmp_path.glob("*.tmp"))
