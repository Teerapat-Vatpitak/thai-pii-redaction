from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hosted_image_excludes_non_service_and_runtime_artifacts():
    patterns = {
        line.strip().rstrip("/")
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert {
        ".venv",
        ".venv-*",
        "node_modules",
        "desktop",
        "extension",
        "office-addin",
        "desktop/src-tauri/target",
        "out",
        "tmp",
        "artifacts",
        "logs",
        ".env",
        ".env.*",
    } <= patterns
