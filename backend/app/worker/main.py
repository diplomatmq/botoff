from __future__ import annotations

import asyncio
import logging
import signal

from app.config import get_settings
from app.db import SessionLocal
from app.logging_config import configure_logging
from app.worker.scheduler import Worker

logger = logging.getLogger("portals.worker.entrypoint")


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.worker_enabled:
        logger.warning("worker disabled by configuration; exiting")
        return

    worker = Worker(SessionLocal, settings=settings)
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(worker.stop()))
        except NotImplementedError:
            pass

    await worker.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
