from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from mailchat.accounts.routes import router as accounts_router
from mailchat.config import settings
from mailchat.messages.routes import router as messages_router
from mailchat.shared.db import async_session, init_db
from mailchat.sync.worker import poll_forever

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    worker_task = asyncio.create_task(
        poll_forever(async_session, interval_seconds=settings.sync_poll_interval_seconds)
    )
    try:
        yield
    finally:
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task


def create_app() -> FastAPI:
    app = FastAPI(title="MailChat", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(accounts_router)
    app.include_router(messages_router)
    return app


app = create_app()
