"""Capability check; never loads Marker models or prints secrets."""

import importlib.metadata
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv

root = Path(__file__).resolve().parents[1]
load_dotenv(root / ".env")
sys.path.insert(0, str(root / "backend"))
from app.config import Config  # noqa: E402

config = Config()

print(f"OS: {platform.platform()} / {platform.machine()}")
print(f"Python: {sys.version.split()[0]}")
for executable in ("node", "npm", "pnpm", "marker_single", "llama-server"):
    print(f"{executable}: {shutil.which(executable) or 'MISSING'}")
print(f"Configured Marker: {shutil.which(config.marker_executable) or 'MISSING'}")
print(
    f"Configured llama-server: {shutil.which(os.environ.get('LLAMA_CPP_BINARY', 'llama-server')) or 'MISSING'}"
)
for package in ("fastapi", "sqlalchemy", "marker-pdf"):
    try:
        print(f"{package}: {importlib.metadata.version(package)}")
    except importlib.metadata.PackageNotFoundError:
        print(f"{package}: MISSING")
if platform.system() == "Darwin":
    result = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True)
    print(f"RAM bytes: {result.stdout.strip() or 'UNAVAILABLE (sandbox)'}")
