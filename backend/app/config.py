from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class UnsafePath(ValueError):
    pass


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAPERFLOW_", env_file=ROOT / ".env", extra="ignore")
    data_dir: Path = Path.home() / "Library/Application Support/PaperFlow"
    port: int = 8000
    marker_executable: str = "marker_single"
    marker_timeout: int = 1800
    max_upload_mb: int = 100

    def path(self, relative: str) -> Path:
        base = self.data_dir.resolve()
        path = (base / relative).resolve()
        if path == base or not path.is_relative_to(base):
            raise UnsafePath("Path outside data directory")
        return path
