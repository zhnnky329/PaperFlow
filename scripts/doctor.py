"""Capability check; never loads Marker models or prints secrets."""

import importlib.metadata
import platform
import shutil
import subprocess
import sys

print(f"OS: {platform.platform()} / {platform.machine()}")
print(f"Python: {sys.version.split()[0]}")
for executable in ("node", "npm", "pnpm", "marker_single", "llama-server"):
    print(f"{executable}: {shutil.which(executable) or 'MISSING'}")
for package in ("fastapi", "sqlalchemy", "marker-pdf"):
    try:
        print(f"{package}: {importlib.metadata.version(package)}")
    except importlib.metadata.PackageNotFoundError:
        print(f"{package}: MISSING")
if platform.system() == "Darwin":
    result = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True)
    print(f"RAM bytes: {result.stdout.strip() or 'UNAVAILABLE (sandbox)'}")
