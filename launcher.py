"""Double-click entry point for the AI Guard backend (PyInstaller target).

Starts the local API on http://127.0.0.1:8000 and opens the docs page. Closing
the console window stops the server. This is the base product (regex + Thai
NER); the optional MiniLM sensitive detector is not bundled in the .exe.
"""
import threading
import time
import webbrowser

# UTF-8 mode (needed for Thai) is forced at build time via PyInstaller's
# --python-option "X utf8=1"; see build_exe.ps1.

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
