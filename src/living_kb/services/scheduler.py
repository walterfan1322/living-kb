from __future__ import annotations

import asyncio
import contextlib

from living_kb.config import Settings
from living_kb.db import SessionLocal
from living_kb.services.jobs import JobService


class LocalScheduler:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if not self.settings.scheduler_enabled or self._task:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def run_once(self):
        with SessionLocal() as session:
            jobs = JobService(session, self.settings)
            jobs.ensure_scheduled_health_check()
            job = jobs.claim_next_job()
            if job:
                return jobs.run_job(job)
            return None

    async def _run_loop(self) -> None:
        while self._running:
            await self.run_once()
            await asyncio.sleep(self.settings.scheduler_poll_seconds)
