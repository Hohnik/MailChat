from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailchat.accounts.routes import router as accounts_router
from mailchat.config import get_settings
from mailchat.messages.routes import router as messages_router
from mailchat.shared.db import Database
from mailchat.shared.exceptions import AccountNotFoundError
from mailchat.sync.worker import SyncWorker, poll_forever

STATIC_DIR = Path(__file__).parent / "static"


def create_app(database: Database, *, sync_worker: SyncWorker | None) -> FastAPI:
    """The app, on the database it should run on and with the worker it should
    sync through. Both are said out loud, every time: `sync_worker=None` runs no
    poll loop at all, which is what a test that only exercises routes wants — no
    second writer on its database, and no calls out to a mail server. Nothing
    here reads the configuration; `production_app` does that.
    """

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await database.create_tables()
        async with _syncing(sync_worker, database.sessions):
            yield

    app = FastAPI(title="MailChat", lifespan=lifespan)
    app.state.session_factory = database.sessions
    app.add_exception_handler(AccountNotFoundError, _account_not_found)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(accounts_router)
    app.include_router(messages_router)
    return app


def production_app() -> FastAPI:
    """What `just run` and `just dev` serve: the configured database, and the
    real poll loop on the configured interval. Being a function rather than a
    module-level app is what keeps the two apart — importing this module builds
    nothing, opens no database, and demands no environment.
    """
    settings = get_settings()
    return create_app(
        Database(settings.database_url),
        sync_worker=partial(poll_forever, interval_seconds=settings.sync_poll_interval_seconds),
    )


async def _account_not_found(_: Request, __: Exception) -> Response:
    """What an account the accounts module says isn't there means over HTTP.

    One place, for every route that asks it — the accounts section is the
    exception, and only because it catches the error first to render the message
    in the page the user is already on. The domain's own wording stays inside;
    a client that asked for an id already knows which one it asked for.
    """
    return JSONResponse(status_code=404, content={"detail": "Account not found"})


@asynccontextmanager
async def _syncing(
    sync_worker: SyncWorker | None, session_factory: async_sessionmaker[AsyncSession]
) -> AsyncIterator[None]:
    """Sync every account on its interval, for as long as the app is up."""
    if sync_worker is None:
        yield
        return

    worker_task = asyncio.create_task(sync_worker(session_factory))
    try:
        yield
    finally:
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task
