"""Portable supervised startup. No model imports; bind loopback only."""

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import httpx
from dotenv import load_dotenv

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
from app.config import Config  # noqa: E402


def open_browser(url):
    try:
        if sys.platform == "darwin":
            return subprocess.run(["/usr/bin/open", url], timeout=5).returncode == 0
        return webbrowser.open(url, new=2)
    except (OSError, subprocess.TimeoutExpired):
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=("serve", "dev"), default="serve")
    parser.add_argument("--no-open", action="store_true", help="Start without opening a browser")
    args = parser.parse_args(argv)
    load_dotenv(root / ".env")
    cfg = Config()
    if args.mode == "dev" and cfg.port != 8000:
        print("Dev proxy uses port 8000. Set PAPERFLOW_PORT=8000 for make dev.", file=sys.stderr)
        return 1
    try:
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", cfg.port))
    except OSError:
        print(f"端口 {cfg.port} 无法使用，请先停止已有服务或修改 PAPERFLOW_PORT。", file=sys.stderr)
        return 1

    children = []
    env = dict(os.environ, PYTHONPATH=str(root / "backend"))
    url = f"http://127.0.0.1:{5173 if args.mode == 'dev' else cfg.port}"
    browser_pending = args.mode == "serve" and not args.no_open
    deadline = time.monotonic() + 30
    previous_handler = signal.getsignal(signal.SIGTERM)

    def interrupt(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        children.append(
            subprocess.Popen(
                [
                    sys.executable, "-m", "uvicorn", "app.main:create_app", "--factory",
                    "--no-access-log", "--host", "127.0.0.1", "--port", str(cfg.port),
                ],
                cwd=root,
                env=env,
            )
        )
        if args.mode == "dev":
            children.append(
                subprocess.Popen(
                    [str(root / "frontend/node_modules/.bin/vite"), "--host", "127.0.0.1"],
                    cwd=root / "frontend",
                    env=env,
                )
            )
        print(f"PaperFlow: {url}", flush=True)
        with httpx.Client(timeout=0.5, trust_env=False, follow_redirects=False) as client:
            while all(child.poll() is None for child in children):
                if browser_pending:
                    ready = False
                    try:
                        ready = client.get(url + "/api/v1/health").status_code == 200
                    except httpx.HTTPError:
                        pass
                    if ready and all(child.poll() is None for child in children):
                        browser_pending = False
                        if not open_browser(url):
                            print(f"浏览器未能自动打开，请访问 {url}", flush=True)
                    elif time.monotonic() >= deadline:
                        browser_pending = False
                        print(f"服务仍在启动，请稍后访问 {url}", flush=True)
                time.sleep(0.3)
        return next((child.returncode for child in children if child.returncode), 0)
    except KeyboardInterrupt:
        return 0
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
        signal.signal(signal.SIGTERM, previous_handler)


if __name__ == "__main__":
    sys.exit(main())
