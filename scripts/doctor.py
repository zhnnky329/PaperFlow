"""Capability check; never loads Marker models or prints secrets."""

import importlib.metadata
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv
import psutil

root = Path(__file__).resolve().parents[1]
load_dotenv(root / ".env")
sys.path.insert(0, str(root / "backend"))
from app.config import Config  # noqa: E402

config = Config()

print(f"OS: {platform.platform()} / {platform.machine()}")
print(f"Python: {sys.version.split()[0]} ({sys.executable})")
print(f"Conda environment: {os.environ.get('CONDA_DEFAULT_ENV') or 'not active'}")
print(f"RAM: {psutil.virtual_memory().total // (1024**2)} MiB")
print(f"Swap: {psutil.swap_memory().total // (1024**2)} MiB")
for executable in ("node", "npm", "xdg-open", "gio"):
    print(f"{executable}: {shutil.which(executable) or 'MISSING'}")
print(f"Configured Marker: {shutil.which(config.marker_executable) or 'MISSING'}")
print(f"Configured llama-server: {shutil.which(config.llama_cpp_binary) or 'MISSING (optional OCR)'}")
print(f"Marker inference: llamacpp / {config.marker_device} (one request at a time)")
from app.desktop import folder_opener  # noqa: E402

print(f"File manager: {'available' if folder_opener() else 'unavailable; copy paths instead'}")
print(f"Data directory: {config.data_dir}")
probe = config.data_dir
while not probe.exists() and probe != probe.parent:
    probe = probe.parent
print(f"Data directory writable: {os.access(probe, os.W_OK | os.X_OK)}")
print(f"Disk free: {shutil.disk_usage(probe).free // (1024**3)} GiB")
for package in ("fastapi", "sqlalchemy", "pytest", "ruff"):
    try:
        print(f"{package}: {importlib.metadata.version(package)}")
    except importlib.metadata.PackageNotFoundError:
        print(f"{package}: MISSING")
if executable := shutil.which(config.marker_executable):
    python = Path(executable).parent / "python"
    try:
        result = subprocess.run(
            [str(python), "-c", 'import importlib.metadata as m; print(m.version("marker-pdf"))'],
            capture_output=True, text=True, timeout=10,
        )
        print(f"Isolated marker-pdf: {result.stdout.strip() if result.returncode == 0 else 'UNAVAILABLE'}")
        if config.marker_device == "cuda":
            result = subprocess.run(
                [str(python), "-c", "import torch; print(torch.cuda.is_available())"],
                capture_output=True, text=True, timeout=20,
            )
            print(f"Marker PyTorch CUDA: {result.stdout.strip() if result.returncode == 0 else 'UNAVAILABLE'}")
    except (OSError, subprocess.SubprocessError):
        print("Isolated Marker probe: UNAVAILABLE")
if executable := shutil.which("nvidia-smi"):
    try:
        result = subprocess.run(
            [executable, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        print(f"NVIDIA (name, VRAM, driver): {result.stdout.strip() if result.returncode == 0 else 'UNAVAILABLE'}")
    except (OSError, subprocess.SubprocessError):
        print("NVIDIA: UNAVAILABLE")
