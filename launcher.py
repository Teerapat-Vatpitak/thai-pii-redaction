"""Double-click entry point for the AI Guard backend (PyInstaller target).

Starts the local API on http://127.0.0.1:8000 and opens the docs page. Closing
the console window stops the server. This is the base product (regex + Thai
NER); the optional MiniLM sensitive detector is not bundled in the .exe.
"""
import os
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


HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}"


def _open_browser():
    time.sleep(1.5)
    try:
        webbrowser.open(f"{URL}/docs")
    except Exception:
        pass


def main():
    _ensure_pythainlp_data()
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
