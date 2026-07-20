#!/usr/bin/env python3
"""Cross-platform smoke test for the packaged sidecar's runtime lifecycle.

Runs on macOS/Linux CI to verify the F1 orphan-port watchdog on real kernels:
start the packaged sidecar, confirm it serves /api/health, then SIGKILL its
PyInstaller bootloader parent (as Tauri does on unix) and assert the orphaned
child exits and frees port 8000. Windows reaps the whole tree via `taskkill /T`,
so this check is unix-only and refuses to run on win32.
"""

import glob
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST = "127.0.0.1"
PORT = 8000
BIN_GLOB = str(ROOT / "desktop" / "src-tauri" / "binaries" / "aiguard-*")


def find_sidecar():
    matches = sorted(m for m in glob.glob(BIN_GLOB) if not m.endswith(".d"))
    if not matches:
        raise FileNotFoundError(
            f"no staged sidecar matching {BIN_GLOB}; run scripts/build_sidecar.py first"
        )
    return matches[0]


def port_is_free(host=HOST, port=PORT):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) != 0


def wait_for(pred, timeout, interval=0.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return False


def health_ok():
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}/api/health", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def sanitize_ok():
    data = json.dumps({"text": "ติดต่อ 0812345678", "mode": "token"}).encode("utf-8")
    req = urllib.request.Request(
        f"http://{HOST}:{PORT}/api/sanitize",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        if r.status != 200:
            raise SystemExit(f"FAIL: /api/sanitize returned {r.status}")
        body = json.loads(r.read())
    if "sanitized_text" not in body:
        raise SystemExit("FAIL: /api/sanitize response missing sanitized_text (engine did not run)")
    print("PASS: /api/sanitize ran (engine loaded)")


def run_smoke():
    binary = find_sidecar()
    print(f"sidecar: {binary}")
    os.chmod(binary, 0o755)
    proc = subprocess.Popen([binary])
    try:
        if not wait_for(health_ok, timeout=60):
            raise SystemExit("FAIL: sidecar did not serve /api/health within 60s")
        print("PASS: /api/health responded")
        sanitize_ok()
        # SIGKILL the PyInstaller bootloader parent (uncatchable, like Tauri's unix kill).
        proc.kill()
        proc.wait(timeout=10)
        # The orphaned python child's watchdog must detect the reparent and exit,
        # releasing port 8000.
        if not wait_for(port_is_free, timeout=15):
            raise SystemExit(
                "FAIL: port 8000 still bound 15s after killing the sidecar parent "
                "(watchdog did not reap the orphan)"
            )
        print("PASS: port 8000 freed after orphaning the sidecar")
    finally:
        if proc.poll() is None:
            proc.kill()


def main():
    if sys.platform == "win32":
        raise SystemExit(
            "smoke_sidecar is unix-only (the watchdog no-ops on Windows; "
            "taskkill /T handles the tree there)"
        )
    run_smoke()


if __name__ == "__main__":
    main()
