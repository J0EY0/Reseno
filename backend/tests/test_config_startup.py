import os

import pytest
from cryptography.fernet import Fernet
from dotenv import dotenv_values

from app import config


def _key_configuration():
    return (
        f'RESENO_MASTER_KEY={Fernet.generate_key().decode("ascii")}\n'
        f'RESENO_JWT_SECRET={"test-secret-" * 4}\n'
    )


def test_default_configuration_path_is_independent_of_data_directory(
    tmp_path, monkeypatch
):
    configuration = tmp_path / "project" / "backend" / ".env"
    configuration.parent.mkdir(parents=True)
    data_dir = tmp_path / "custom-data"
    content = f'APP_DATA_DIR="{data_dir}"\nAPP_DB_PATH=\nAPP_STORAGE_DIR=\n'
    configuration.write_text(content)
    monkeypatch.setattr(config, "DEFAULT_ENV_PATH", configuration)
    monkeypatch.setattr(config, "DEFAULT_DATA_DIR", tmp_path / "default-data")
    monkeypatch.delenv("APP_ENV_FILE", raising=False)
    for name in (
        "APP_DATA_DIR",
        "APP_DB_PATH",
        "APP_STORAGE_DIR",
        "EXPORT_DIR",
        "APP_USER_SETTINGS_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    settings = config.initialize_settings()
    assert settings.env_file_path == configuration
    assert settings.data_dir == data_dir
    assert settings.db_path == data_dir / "app.db"
    assert settings.storage_dir == data_dir / "storage"
    assert settings.export_dir == data_dir / "storage" / "exports"
    assert settings.user_settings_path == data_dir / "user_settings.json"
    assert not (data_dir / ".env").exists()
    assert content in configuration.read_text()
    assert dotenv_values(configuration)["RESENO_MASTER_KEY"]


def test_startup_does_not_write_complete_read_only_configuration(tmp_path, monkeypatch):
    configuration = tmp_path / ".env"
    content = 'CUSTOM_VALUE="unchanged # value"\n' + _key_configuration()
    configuration.write_text(content)
    configuration.chmod(0o400)
    monkeypatch.setenv("APP_ENV_FILE", str(configuration))
    try:
        settings = config.initialize_settings()
        assert settings.env_file_path == configuration
        assert configuration.read_text() == content
        values = dotenv_values(configuration)
        assert settings.master_key == values[config.MASTER_KEY_ENV_NAME]
        assert settings.jwt_secret == values[config.JWT_SECRET_ENV_NAME]
        assert not os.environ.get(config.MASTER_KEY_ENV_NAME)
        assert not os.environ.get(config.JWT_SECRET_ENV_NAME)
    finally:
        configuration.chmod(0o600)


def test_missing_configuration_is_created_to_persist_generated_keys(
    tmp_path, monkeypatch
):
    configuration = tmp_path / "application" / ".env"
    monkeypatch.setenv("APP_ENV_FILE", str(configuration))
    settings = config.initialize_settings()
    assert settings.env_file_path == configuration
    values = dotenv_values(configuration)
    Fernet(values[config.MASTER_KEY_ENV_NAME].encode("ascii"))
    assert len(values[config.JWT_SECRET_ENV_NAME]) >= 32
    assert configuration.stat().st_mode & 0o777 == 0o600


def test_complete_environment_keys_do_not_require_a_configuration_file(
    tmp_path, monkeypatch
):
    configuration = tmp_path / "not-created" / ".env"
    monkeypatch.setenv("APP_ENV_FILE", str(configuration))
    monkeypatch.setenv(
        config.MASTER_KEY_ENV_NAME, Fernet.generate_key().decode("ascii")
    )
    monkeypatch.setenv(config.JWT_SECRET_ENV_NAME, "test-secret-" * 4)
    config.initialize_settings()
    assert not configuration.parent.exists()


def test_environment_overrides_configuration_without_changing_it(tmp_path, monkeypatch):
    configuration = tmp_path / ".env"
    content = (
        f"APP_DATA_DIR={tmp_path / 'from-file'}\nAPP_DB_PATH=\nAPP_STORAGE_DIR=\n"
        + _key_configuration()
    )
    configuration.write_text(content)
    monkeypatch.setenv("APP_ENV_FILE", str(configuration))
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "from-environment"))
    master_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv(config.MASTER_KEY_ENV_NAME, master_key)
    monkeypatch.delenv("APP_DB_PATH", raising=False)
    monkeypatch.delenv("APP_STORAGE_DIR", raising=False)
    settings = config.initialize_settings()
    assert settings.data_dir == tmp_path / "from-environment"
    assert settings.db_path == settings.data_dir / "app.db"
    assert settings.storage_dir == settings.data_dir / "storage"
    assert os.environ[config.MASTER_KEY_ENV_NAME] == master_key
    assert configuration.read_text() == content


@pytest.mark.parametrize("database", ["app.db", "auth.db"])
@pytest.mark.parametrize("partial_keys", [False, True])
def test_missing_secrets_cannot_silently_replace_keys_for_existing_data(
    tmp_path, database, partial_keys, monkeypatch
):
    path = tmp_path / database
    path.write_bytes(b"existing database")
    configuration = tmp_path / ".env"
    content = (
        f'RESENO_MASTER_KEY={Fernet.generate_key().decode("ascii")}\n'
        if partial_keys
        else ""
    )
    configuration.write_text(content)
    monkeypatch.setenv("APP_ENV_FILE", str(configuration))
    with pytest.raises(RuntimeError, match="[Ss]ecrets|[Kk]eys"):
        config.initialize_settings()
    assert path.read_bytes() == b"existing database"
    assert configuration.read_text() == content
