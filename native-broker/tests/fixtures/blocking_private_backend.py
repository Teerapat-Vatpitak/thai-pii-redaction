"""Test-only private backend whose local detector never returns."""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

repository_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(repository_root))

private_backend_main = importlib.import_module("native_broker_backend").main

ready = Path(sys.argv[1])


def blocked_detect(*_args, **_kwargs):
    ready.write_bytes(b"ready")
    while True:
        time.sleep(0.05)


def install_blocking_detector() -> None:
    import pii_redactor.detectors.aggregate as aggregate

    aggregate.detect_all = blocked_detect


raise SystemExit(private_backend_main(prepare=install_blocking_detector))
