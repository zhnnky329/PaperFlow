"""Run actual Marker CLI, record elapsed/returncode, stop the whole process group on timeout."""

import argparse
import os
import signal
import subprocess
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--executable", default="marker_single")
parser.add_argument("--pdf", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--timeout", type=int, default=1800)
parser.add_argument(
    "--disable-ocr", action="store_true", help="Diagnostic only; does not pass full math Gate"
)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
argv = [
    args.executable,
    str(args.pdf.resolve()),
    "--output_format",
    "html",
    "--output_dir",
    str(args.output.resolve()),
    "--mode",
    "fast",
]
if args.disable_ocr:
    argv.append("--disable_ocr")
print("argv:", repr(argv), flush=True)
started = time.monotonic()
with (args.output / "gate.log").open("w") as log:
    process = subprocess.Popen(argv, stdout=log, stderr=log, start_new_session=True)
    try:
        code = process.wait(timeout=args.timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        code = 124
elapsed = round(time.monotonic() - started, 2)
print(f"returncode={code}; elapsed_seconds={elapsed}", flush=True)
print("HTML:", [str(p) for p in args.output.rglob("*.html")], flush=True)
raise SystemExit(code)
