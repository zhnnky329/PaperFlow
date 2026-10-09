"""Actual detached child cleanup; process enumeration requires unsandboxed macOS."""

import subprocess
import sys
import time
from pathlib import Path
import psutil
import pytest


def test_parent_death_cleans_detached_inference_child(tmp_path):
    try:
        psutil.pids()
    except (OSError, psutil.Error):
        pytest.skip("macOS sandbox blocks process enumeration; run this test outside sandbox")
    root = Path(__file__).resolve().parents[1]
    pid_file = tmp_path / "pid"
    cli = tmp_path / "spawn.py"
    cli.write_text(
        "import subprocess,sys,time\nfrom pathlib import Path\n"
        f'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],start_new_session=True)\n'
        f"Path({str(pid_file)!r}).write_text(str(p.pid))\ntime.sleep(60)\n"
    )
    argv = [sys.executable, str(root / "scripts/controlled_marker.py"), sys.executable, str(cli)]
    parent = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"import subprocess,time;subprocess.Popen({argv!r},start_new_session=True);time.sleep(60)",
        ]
    )
    child = None
    try:
        for _ in range(100):
            if pid_file.exists():
                break
            time.sleep(0.05)
        assert pid_file.exists()
        child = psutil.Process(int(pid_file.read_text()))
        parent.terminate()
        parent.wait(timeout=5)
        for _ in range(100):
            if not child.is_running() or child.status() == psutil.STATUS_ZOMBIE:
                break
            time.sleep(0.05)
        assert not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait()
        if child and child.is_running():
            try:
                child.kill()
            except psutil.Error:
                pass
