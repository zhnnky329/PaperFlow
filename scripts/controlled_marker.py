"""Supervisor for Marker and its detached inference descendants.

Parent death, SIGTERM, timeout in API worker: terminate only tracked descendants.
No global process-name killing; process creation time protects against PID reuse.
"""

import os
import signal
import subprocess
import sys
import time
import psutil

parent = os.getppid()
stopping = False
owned = {}


def stop(*_):
    global stopping
    stopping = True


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
process = subprocess.Popen(sys.argv[1:])
try:
    direct = psutil.Process(process.pid)
    owned[(direct.pid, direct.create_time())] = direct
except (psutil.Error, OSError):
    pass
try:
    while True:
        try:
            descendants = psutil.Process(os.getpid()).children(recursive=True)
            for child in descendants:
                owned[(child.pid, child.create_time())] = child
        except (psutil.Error, OSError):
            pass
        if stopping or os.getppid() != parent:
            break
        if process.poll() is not None:
            break
        time.sleep(0.1)
finally:
    for child in owned.values():
        try:
            if child.is_running():
                child.terminate()
        except (psutil.Error, OSError):
            pass
    _, alive = psutil.wait_procs(list(owned.values()), timeout=2)
    for child in alive:
        try:
            child.kill()
        except (psutil.Error, OSError):
            pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
sys.exit(process.returncode or (143 if stopping else 0))
