from pathlib import Path


def runtime_environment(data_dir: Path) -> dict[str, str]:
    return {
        "APP_DATA_DIR": str(data_dir),
        "APP_DB_PATH": str(data_dir / "app.db"),
        "APP_STORAGE_DIR": str(data_dir / "storage"),
        "APP_ENV_FILE": str(data_dir / ".env"),
        "APP_USER_SETTINGS_PATH": str(data_dir / "user_settings.json"),
        "EXPORT_DIR": str(data_dir / "storage" / "exports"),
        "RESENO_MASTER_KEY": "",
        "RESENO_JWT_SECRET": "",
    }
