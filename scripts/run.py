"""Portable supervised startup. No model imports; bind loopback only."""

import os
import signal
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

root = Path(__file__).resolve().parents[1]
load_dotenv(root / ".env")
sys.path.insert(0, str(root / "backend"))
from app.config import Config  # noqa: E402

cfg = Config()
mode = sys.argv[1] if len(sys.argv) > 1 else "serve"
children = []
env = dict(os.environ, PYTHONPATH=str(root / "backend"))
try:
    children.append(
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(cfg.port),
            ],
            cwd=root,
            env=env,
        )
    )
    if mode == "dev":
        if cfg.port != 8000:
            raise RuntimeError("Dev proxy uses port 8000. Set PAPERFLOW_PORT=8000 for make dev.")
        children.append(
            subprocess.Popen(
                [str(root / "frontend/node_modules/.bin/vite"), "--host", "127.0.0.1"],
                cwd=root / "frontend",
                env=env,
            )
        )
    print(f"PaperFlow: http://127.0.0.1:{5173 if mode == 'dev' else cfg.port}", flush=True)

    def interrupt(*args):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    while all(child.poll() is None for child in children):
        import time

        time.sleep(0.3)
except KeyboardInterrupt:
    pass
finally:
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        try:
            child.wait(timeout=40)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
