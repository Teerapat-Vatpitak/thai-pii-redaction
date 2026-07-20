"""Salt-free sweep: run every sample file through the WEB path N times.

The service salts are random per session, so repeated runs sweep the same
space the PR #33/#34 flake hunts covered. Any OutboundLeakError here is a
guard false positive on the unified path.
"""

import sys

# Python auto-prepends this script's own directory (benchmark/) to sys.path.
# benchmark/types.py then shadows the stdlib `types` module that
# pathlib/dataclasses/enum import internally -- drop it before importing
# anything else, then add the repo root for our own imports below.
sys.path.pop(0)

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pii_redactor.ingest.text_cleaner import clean
from pii_redactor.session_service import OutboundLeakError, SessionService

FILES = [
    "examples/prompts/01_sick_leave_email.txt",
    "examples/prompts/02_medical_consult.txt",
    "examples/prompts/03_bank_complaint.txt",
    "tests/sample_thai.txt",
]
RUNS = 30

failures = 0
for rel in FILES:
    text = clean(Path(rel).read_text(encoding="utf-8")).text
    for mode in ("token", "surrogate"):
        fail = 0
        for _ in range(RUNS):
            svc = SessionService()
            try:
                out = svc.sanitize(text, mode=mode)
                svc.restore(out.session_id, out.sanitized_text)
            except OutboundLeakError:
                fail += 1
        failures += fail
        print(f"{rel} [{mode}]: {fail}/{RUNS} guard failures")
print(f"TOTAL: {failures}")
sys.exit(1 if failures else 0)
