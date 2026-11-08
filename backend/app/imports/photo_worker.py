"""Фоновая загрузка и обработка фото участников после импорта (B1-06, IM-01, QR-02)."""

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.imports.photo_apply import finish_batch_photos, save_participant_photo
from app.imports.photo_fetch import PhotoFetchError, fetch_photo
from app.imports.photo_image import PhotoImageError, normalize_photo
from app.imports.photo_store import store_photo

log = logging.getLogger("app.imports.photos")

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@dataclass(frozen=True)
class PhotoJob:
    """Задание на скачивание фото участника."""

    participant_id: int
    conference_id: int
    row: int  # номер строки файла, как в остальных предупреждениях отчёта (`row.number`)
    url: str


class PhotoWorker:
    """Фоновый воркер для скачивания, обработки и сохранения фото."""

    def __init__(self, sessions: SessionFactory, settings: Callable[[], Settings]) -> None:
        self._sessions = sessions
        self._settings = settings
        self._semaphore = asyncio.Semaphore(settings().photo_workers)
        self._tasks: set[asyncio.Task[None]] = set()

    def submit(self, batch_id: int, jobs: list[PhotoJob]) -> None:
        """Поставить список заданий партии в очередь обработки."""
        if not jobs:
            return
        task = asyncio.create_task(self._process(batch_id, jobs))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait_idle(self) -> None:
        """Дождаться завершения всех запущенных задач (для тестов)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def stop(self) -> None:
        """Отменить все задачи (остановка приложения)."""
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def _process(self, batch_id: int, jobs: list[PhotoJob]) -> None:
        try:
            results = await asyncio.gather(*(self._one(j) for j in jobs))
            loaded = sum(1 for r in results if r is True)
            failed_rows = [job.row for job, r in zip(jobs, results, strict=True) if r is False]
            async with self._sessions() as s:
                await finish_batch_photos(s, batch_id, loaded=loaded, failed_rows=failed_rows)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Ошибка при завершении загрузки фото для партии %s", batch_id)

    async def _one(self, job: PhotoJob) -> bool | None:
        async with self._semaphore:
            cfg = self._settings()
            try:
                data = await fetch_photo(
                    job.url,
                    max_bytes=cfg.photo_max_mb * 1024 * 1024,
                    timeout_s=cfg.photo_timeout_s,
                    max_redirects=cfg.photo_max_redirects,
                )
                jpeg = await asyncio.to_thread(
                    normalize_photo,
                    data,
                    max_pixels=cfg.photo_max_pixels,
                    max_side_px=cfg.photo_max_side_px,
                    quality=cfg.photo_jpeg_quality,
                )
                path, sha = await asyncio.to_thread(
                    store_photo,
                    cfg.photo_dir,
                    job.conference_id,
                    job.participant_id,
                    jpeg,
                )
                async with self._sessions() as s:
                    applied = await save_participant_photo(
                        s, job.participant_id, job.url, path, sha
                    )
                return True if applied else None
            except (PhotoFetchError, PhotoImageError) as e:
                log.warning("Фото участника %s не загружено: %s", job.participant_id, e.reason)
                return False
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception(
                    "Непредвиденная ошибка при загрузке фото участника %s",
                    job.participant_id,
                )
                return False


__all__ = ["PhotoJob", "PhotoWorker", "SessionFactory"]
