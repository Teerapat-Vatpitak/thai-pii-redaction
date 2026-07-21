"""python -m app.worker — the platform deployment entrypoint.

Config is 100% env vars so the container can be repointed without a rebuild:
AIGUARD_QUEUE_POLL_URL / AIGUARD_QUEUE_RESULT_URL (required),
AIGUARD_QUEUE_IDLE_S (default 2.0), AIFORTHAI_API_KEY (auth, optional).
SIGTERM/SIGINT set the stop event -> the loop finishes its current job and
exits 0, which is what a container orchestrator expects.
"""

from __future__ import annotations

import logging
import os
import signal
import threading

from app.worker.runner import run
from app.worker.transport import HttpPollTransport


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop = threading.Event()

    def _stop(signum, frame):
        stop.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    transport = HttpPollTransport()
    idle = float(os.environ.get("AIGUARD_QUEUE_IDLE_S", "2.0"))
    run(transport, stop=stop, idle_sleep_s=idle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
