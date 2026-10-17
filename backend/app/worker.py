"""Background worker: runs AI jobs so they finish even if the user closes the tab.

Run:  python -m app.worker
Run more than one for more throughput; jobs are claimed safely (SKIP LOCKED).
"""

import asyncio
import logging
import signal

from app import models  # noqa: F401
from app.config import get_settings
from app.db import dispose_engine, get_sessionmaker, init_engine
from app.modules.jobs.queue import claim_next, extend_lease
from app.modules.jobs.runner import run_job
from app.modules.storage.local import LocalStorage

log = logging.getLogger("worker")
POLL_SECONDS = 1.0


async def _heartbeat(job_id: int, lease: int, stop: asyncio.Event) -> None:
    sessionmaker = get_sessionmaker()
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=lease / 3)
        except TimeoutError:
            async with sessionmaker() as db:
                await extend_lease(db, job_id, lease)


async def _run_one(job_id: int, settings, storage) -> None:
    stop = asyncio.Event()
    beat = asyncio.create_task(_heartbeat(job_id, settings.job_lease_seconds, stop))
    try:
        await run_job(job_id, sessionmaker=get_sessionmaker(), storage=storage, settings=settings)
    finally:
        stop.set()
        await beat


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    init_engine(settings.database_url)
    storage = LocalStorage(settings.storage_root)
    slots = asyncio.Semaphore(settings.worker_concurrency)
    running: set[asyncio.Task] = set()
    stopping = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stopping.set)
        except NotImplementedError:  # Windows
            pass

    log.info("worker started (concurrency %s)", settings.worker_concurrency)
    try:
        while not stopping.is_set():
            await slots.acquire()
            try:
                async with get_sessionmaker()() as db:
                    job_id = await claim_next(db, settings.job_lease_seconds)
            except Exception:
                log.exception("could not claim a job")
                job_id = None
            if job_id is None:
                slots.release()
                try:
                    await asyncio.wait_for(stopping.wait(), timeout=POLL_SECONDS)
                except TimeoutError:
                    pass
                continue
            log.info("job %s started", job_id)
            task = asyncio.create_task(_run_one(job_id, settings, storage))
            running.add(task)

            def _done(t: asyncio.Task, jid=job_id) -> None:
                running.discard(t)
                slots.release()
                log.info("job %s finished", jid)

            task.add_done_callback(_done)
    finally:
        log.info("stopping: waiting for %s running job(s)", len(running))
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
