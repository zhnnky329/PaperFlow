import os
from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr, field_validator

ROOT = Path(__file__).resolve().parents[2]


class UnsafePath(ValueError):
    pass


def default_data_dir():
    xdg = Path(os.environ.get("XDG_DATA_HOME") or "")
    base = xdg if xdg.is_absolute() else Path.home() / ".local/share"
    return base / "paperflow"


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PAPERFLOW_", env_file=ROOT / ".env", extra="ignore", populate_by_name=True
    )
    data_dir: Path = Field(default_factory=default_data_dir)
    port: int = 8000
    marker_executable: str = "marker_single"
    marker_timeout: int = 1800
    marker_device: Literal["cpu", "cuda"] = "cpu"
    llama_cpp_binary: str = Field(default="llama-server", validation_alias="LLAMA_CPP_BINARY")
    llama_cpp_gpu_layers: int = Field(default=99, ge=0, le=999, validation_alias="LLAMA_CPP_NGL")
    max_upload_mb: int = 100
    metadata_online: bool = True
    discovery_online: bool = True
    deepseek_api_key: SecretStr = SecretStr("")

    @field_validator("data_dir", mode="before")
    @classmethod
    def absolute_data_dir(cls, value):
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("PAPERFLOW_DATA_DIR must be an absolute path")
        return path

    def path(self, relative: str) -> Path:
        base = self.data_dir.resolve()
        path = (base / relative).resolve()
        if path == base or not path.is_relative_to(base):
            raise UnsafePath("Path outside data directory")
        return path
