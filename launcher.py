"""Double-click entry point for the AI Guard backend (PyInstaller target).

Starts the local API on http://127.0.0.1:8000 and opens the docs page. Closing
the console window stops the server. This is the base product (regex + Thai
NER); the optional MiniLM sensitive detector is not bundled in the .exe.
"""
import os
import secrets
import shutil
import sys
import threading
import time
import webbrowser

# UTF-8 mode (needed for Thai) is forced at build time via PyInstaller's
# --python-option "X utf8=1"; see build_exe.ps1.


def _ensure_pythainlp_data():
    """Place the bundled PyThaiNLP NER model where the library looks, so NER
    works offline on a fresh machine with no runtime download. Only fills in
    files that are missing — an existing user cache is left untouched."""
    if not getattr(sys, "frozen", False):
        return
    src = os.path.join(getattr(sys, "_MEIPASS", ""), "pythainlp-data")
    if not os.path.isdir(src):
        return
    dst = os.path.join(os.path.expanduser("~"), "pythainlp-data")
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        target = os.path.join(dst, name)
        if not os.path.exists(target):
            try:
                shutil.copy2(os.path.join(src, name), target)
            except Exception:
                pass


def _watch_parent_and_exit():
    """On unix the packaged app runs as the forked child of the PyInstaller
    onefile bootloader (the process Tauri spawns as its sidecar). A SIGKILL to
    that bootloader does not reach this child, so without this watchdog the
    backend would be orphaned and keep holding port 8000 as a zombie. Detect the
    reparent (our parent pid changes once the bootloader dies) and exit so the
    port is freed. Windows reaps the whole tree via `taskkill /T`, so this is
    unix-only."""
    if sys.platform == "win32":
        return
    initial_ppid = os.getppid()
    while True:
        time.sleep(1.0)
        if os.getppid() != initial_ppid:
            os._exit(0)


HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}"


def _open_browser():
    time.sleep(1.5)
    try:
        webbrowser.open(f"{URL}/docs")
    except Exception:
        pass


def _ensure_boot_token():
    """Generate a random boot token if the environment hasn't supplied one, so
    the in-process server enforces the control plane (shutdown / delete-session)
    even when launched standalone. Must run BEFORE `app.server` is imported —
    the server reads AIGUARD_TOKEN once at import. The value is never printed or
    logged; a caller that already set AIGUARD_TOKEN (e.g. the Tauri shell, which
    needs the value to shut the sidecar down) is left untouched."""
    if not os.environ.get("AIGUARD_TOKEN"):
        os.environ["AIGUARD_TOKEN"] = secrets.token_hex(16)


def main():
    _ensure_pythainlp_data()
    _ensure_boot_token()
    if getattr(sys, "frozen", False):
        # The packaged app is fully offline: it runs only on bundled models and
        # must never reach the network. This makes a missing model fail loudly at
        # first use instead of silently trying to download it.
        os.environ.setdefault("PYTHAINLP_OFFLINE", "1")
        # Reap this backend if the Tauri sidecar (our parent) is force-killed.
        threading.Thread(target=_watch_parent_and_exit, daemon=True).start()
    import uvicorn
    from app.server import app

    print("AI Guard backend")
    print(f"  API:    {URL}")
    print(f"  Docs:   {URL}/docs")
    print(f"  Health: {URL}/api/health")
    print("Load the browser extension, then use ChatGPT/Claude.")
    print("Keep this window open; close it to stop the server.")
    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
