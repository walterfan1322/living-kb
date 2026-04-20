from __future__ import annotations

import asyncio

from living_kb.config import get_settings
from living_kb.db import init_db
from living_kb.services.scheduler import LocalScheduler


async def _main() -> None:
    settings = get_settings()
    if settings.is_sqlite:
        init_db()
    scheduler = LocalScheduler(settings)
    await scheduler.start()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await scheduler.stop()


def main() -> None:
    asyncio.run(_main())
