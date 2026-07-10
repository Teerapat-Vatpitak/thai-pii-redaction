#!/usr/bin/env python3
"""Windows smoke test for the packaged sidecar exe.

Boot the PyInstaller-built AIGuard sidecar, confirm it serves the real API
(/api/health plus /api/sanitize with the offline Thai NER engine actually
loaded), then kill its whole process tree with `taskkill /T /F` -- exactly how
the Tauri shell reaps it on Windows (`sidecar.rs`) -- and assert port 8000 is
released.

This is the coverage CI never had: Windows is the only platform users actually
run, yet `smoke_sidecar.py` refuses to run on win32 (it exercises the unix
orphan-watchdog, which is a no-op on Windows because taskkill /T reaps the
tree). This script is the Windows-side counterpart -- it boots the shipped
binary end-to-end instead of the source app.
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
# Prefer the staged Tauri sidecar (what smoke_sidecar.py uses); fall back to the
# raw PyInstaller output so this works straight after `build_sidecar.py` too.
STAGED_GLOB = str(ROOT / "desktop" / "src-tauri" / "binaries" / "aiguard-*")


def find_sidecar():
    matches = sorted(
        m for m in glob.glob(STAGED_GLOB) if m.endswith(".exe")
    )
    if matches:
        return matches[0]
    fallback = ROOT / "dist" / "AIGuard.exe"
    if fallback.is_file():
        return str(fallback)
    raise FileNotFoundError(
        f"no packaged sidecar found (looked for {STAGED_GLOB} and {fallback}); "
        "run scripts/build_sidecar.py first"
    )


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


def taskkill_tree(pid):
    # /T reaps the child the PyInstaller onefile bootloader spawned; /F forces it.
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        text=True,
    )


def run_smoke():
    binary = find_sidecar()
    print(f"sidecar: {binary}")
    proc = subprocess.Popen([binary])
    try:
        if not wait_for(health_ok, timeout=90):
            raise SystemExit("FAIL: sidecar did not serve /api/health within 90s")
        print("PASS: /api/health responded")
        sanitize_ok()
        taskkill_tree(proc.pid)
        if not wait_for(port_is_free, timeout=15):
            raise SystemExit(
                "FAIL: port 8000 still bound 15s after taskkill /T /F "
                "(the process tree was not fully reaped)"
            )
        print("PASS: port 8000 freed after killing the sidecar tree")
    finally:
        if proc.poll() is None:
            taskkill_tree(proc.pid)


def main():
    if sys.platform != "win32":
        raise SystemExit(
            "smoke_exe is Windows-only (it exercises taskkill /T tree reaping; "
            "use smoke_sidecar.py for the unix orphan-watchdog check)"
        )
    run_smoke()


if __name__ == "__main__":
    main()
