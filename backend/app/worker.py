"""Processo que monitora continuamente: produtos, radar de ofertas e fila de avisos."""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import timedelta

from sqlalchemy import or_, select

from .config import get_settings
from .core.engine import run_watch
from .core.radar import cleanup, ingest_coupons, ingest_deals
from .core.sourcestate import get_status, is_waiting, mark_failure, mark_ok
from .db import init_db, session_scope
from .models import Heartbeat, RunRequest, Watch, utcnow
from .notify.dispatch import deliver_pending
from .notify.webpush import ensure_keys
from .sources.base import Blocked, FeedSource, Fetcher
from .sources.registry import feed_sources, store_sources

log = logging.getLogger("bftracker.worker")


class Worker:
    def __init__(self, fetcher: Fetcher | None = None):
        self.settings = get_settings()
        self.fetcher = fetcher or Fetcher()
        self.stop = asyncio.Event()
        self.running_watches: set[int] = set()
        self.running_feeds: set[str] = set()
        self.tasks: set[asyncio.Task] = set()
        self.watch_slots = asyncio.Semaphore(self.settings.worker_concurrency)
        self.feed_slots = asyncio.Semaphore(6)

    def _spawn(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def run_one_watch(self, watch_id: int) -> None:
        try:
            async with self.watch_slots:
                with session_scope() as db:
                    summary = await run_watch(db, watch_id, self.fetcher, store_sources(db))
                    if summary:
                        log.info("Monitorado %s: %s", watch_id, summary)
        except Exception:
            log.exception("Falha no monitorado %s", watch_id)
        finally:
            self.running_watches.discard(watch_id)

    async def run_one_feed(self, source: FeedSource) -> None:
        try:
            async with self.feed_slots:
                error = None
                try:
                    deals, coupons = await asyncio.wait_for(source.fetch(self.fetcher), 90)
                except Exception as exc:  # noqa: BLE001
                    error = exc
                with session_scope() as db:
                    status = get_status(db, source.key, source.name, "feed")
                    if error is not None:
                        state = "blocked" if isinstance(error, Blocked) else "error"
                        mark_failure(db, source.key, source.name, "feed", state,
                                     str(error) or type(error).__name__)
                        log.warning("Fonte %s: %s", source.key, error or type(error).__name__)
                        return
                    baseline = not status.baseline_done
                    result = ingest_deals(db, deals, baseline=baseline)
                    extra = ingest_coupons(db, coupons, baseline=baseline)
                    status = get_status(db, source.key, source.name, "feed")
                    status.baseline_done = True
                    mark_ok(db, source.key, source.name, "feed", len(deals) + len(coupons))
                    if result["new"] or extra["new"]:
                        log.info("Fonte %s: %s ofertas, %s cupons, %s avisos", source.key,
                                 result["new"], extra["new"],
                                 result["alerts"] + extra["alerts"])
        except Exception:
            log.exception("Falha ao processar a fonte %s", source.key)
        finally:
            self.running_feeds.discard(source.key)

    def schedule(self) -> None:
        now = utcnow()
        with session_scope() as db:
            requests = db.scalars(select(RunRequest).order_by(RunRequest.id)).all()
            forced_watches, forced_feeds = set(), set()
            for request in requests:
                if request.kind == "watch":
                    forced_watches.add(int(request.target))
                else:
                    forced_feeds.add(request.target)

            due = db.scalars(
                select(Watch.id)
                .where(Watch.active, or_(Watch.next_run_at.is_(None), Watch.next_run_at <= now))
                .order_by(Watch.next_run_at)
                .limit(20)
            ).all()
            capacity = self.settings.worker_concurrency * 2
            for watch_id in [*forced_watches, *due]:
                if watch_id in self.running_watches:
                    continue
                if watch_id not in forced_watches and len(self.running_watches) >= capacity:
                    continue
                self.running_watches.add(watch_id)
                self._spawn(self.run_one_watch(watch_id))

            for source in feed_sources(db):
                status = get_status(db, source.key, source.name, "feed")
                forced = source.key in forced_feeds
                if source.key in self.running_feeds or not status.enabled:
                    continue
                if not forced and (is_waiting(status) or
                                   (status.next_run_at and status.next_run_at > now)):
                    continue
                status.next_run_at = now + timedelta(seconds=source.interval_seconds)
                self.running_feeds.add(source.key)
                self._spawn(self.run_one_feed(source))

            for request in requests:
                db.delete(request)
            beat = db.get(Heartbeat, "worker")
            if beat is None:
                db.add(Heartbeat(name="worker", at=now))
            else:
                beat.at = now

    @staticmethod
    def _deliver() -> dict:
        with session_scope() as db:
            return deliver_pending(db)

    async def delivery_loop(self) -> None:
        while not self.stop.is_set():
            try:
                stats = await asyncio.to_thread(self._deliver)
                if stats["sent"] or stats["failed"]:
                    log.info("Avisos: %s", stats)
            except Exception:
                log.exception("Falha na entrega de avisos")
            await self._sleep(3)

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self.stop.wait(), seconds)
        except TimeoutError:
            pass

    async def run(self) -> None:
        with session_scope() as db:
            ensure_keys(db)
        delivery = asyncio.create_task(self.delivery_loop())
        next_cleanup = utcnow()
        log.info("Worker iniciado")
        while not self.stop.is_set():
            try:
                self.schedule()
                if utcnow() >= next_cleanup:
                    with session_scope() as db:
                        cleanup(db)
                    next_cleanup = utcnow() + timedelta(hours=12)
            except Exception:
                log.exception("Falha no agendador")
            await self._sleep(5)
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, delivery, return_exceptions=True)
        await self.fetcher.close()


async def _main() -> None:
    worker = Worker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop.set)
    await worker.run()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    init_db()
    asyncio.run(_main())


if __name__ == "__main__":
    main()
