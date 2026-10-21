"""The live event stream (FR-VIS-03, NFR-PERF-02, ARC §7.4, plan 5.3).

GET /api/v1/events is a server-sent-event stream of `score.updated`, `alert.changed` and
`job.progress`. The worker announces each change with a PostgreSQL NOTIFY in the same
transaction as the change; every web process keeps one LISTEN connection (EventHub) and
fans the notifications out to its open streams.

A stream only carries events for models the user may see (their scope); job events go to
every signed-in user. Holding a stream open is not user activity, so it does not keep the
session alive: when the session ends (idle timeout, sign-out, deactivation) the stream
sends `session.ended` and closes. A browser reconnects on its own and should re-read what
it shows, since events sent while it was away are not replayed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.engine import make_url

from pmp.api.alerts import visible_models
from pmp.api.deps import SignedIn, database_of, policy_of, signed_in
from pmp.core import EVENT_CHANNEL, resolve_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["events"])
User = Annotated[SignedIn, Depends(signed_in)]
KEEPALIVE_S = 15.0  # a comment line keeps proxies from closing a quiet stream
RECHECK_S = 60.0  # how often the session and the visible models are checked again
QUEUE_SIZE = 1000  # per stream; beyond this the oldest events are dropped


class EventHub:
    """One LISTEN connection per process, shared by every open stream."""

    def __init__(self, database_url: str) -> None:
        url = make_url(database_url).set(drivername="postgresql")
        self._dsn = url.render_as_string(hide_password=False)
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[Any]]] = set()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.ready = threading.Event()

    def subscribe(self) -> asyncio.Queue[Any]:
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=QUEUE_SIZE)
        with self._lock:
            self._subscribers.add((asyncio.get_running_loop(), queue))
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(target=self._listen, name="pmp-events", daemon=True)
                self._thread.start()
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Any]) -> None:
        with self._lock:
            self._subscribers = {s for s in self._subscribers if s[1] is not queue}

    def stop(self) -> None:
        self._stop.set()

    def _listen(self) -> None:
        while not self._stop.is_set():
            try:
                with psycopg.connect(self._dsn, autocommit=True) as connection:
                    connection.execute(f"LISTEN {EVENT_CHANNEL}")
                    self.ready.set()
                    while not self._stop.is_set():
                        for note in connection.notifies(timeout=1.0, stop_after=100):
                            self._publish(note.payload)
            except psycopg.Error:
                logger.exception("Event listener lost its connection; reconnecting")
                self.ready.clear()
                self._stop.wait(2.0)

    def _publish(self, payload: str) -> None:
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            return
        with self._lock:
            subscribers = list(self._subscribers)
        for loop, queue in subscribers:
            loop.call_soon_threadsafe(_offer, queue, event)


def _offer(queue: asyncio.Queue[Any], event: dict[str, Any]) -> None:
    """A client that has fallen far behind loses its oldest events, not the newest."""
    if queue.full():
        queue.get_nowait()
    queue.put_nowait(event)


def hub_of(request: Request) -> EventHub:
    hub: EventHub | None = getattr(request.app.state, "event_hub", None)
    if hub is None:
        url = database_of(request).engine.url.render_as_string(hide_password=False)
        hub = EventHub(url)
        request.app.state.event_hub = hub
    return hub


def _frame(event: dict[str, Any]) -> str:
    return f"event: {event.get('type', 'message')}\ndata: {json.dumps(event, default=str)}\n\n"


@router.get(
    "/events",
    response_class=StreamingResponse,
    summary="Live events (server-sent events): score.updated, alert.changed, job.progress",
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def get_events(
    request: Request,
    user: User,
    timeout_s: Annotated[
        float | None, Query(gt=0, le=3600, description="close after this long (tests, polling)")
    ] = None,
) -> StreamingResponse:
    hub = hub_of(request)
    database, policy = database_of(request), policy_of(request)

    def visible() -> set[int] | None:
        """Model IDs the user may see now, or None if the session has ended."""
        with database.session() as session:
            active = resolve_session(
                session, user.token, datetime.now(UTC), policy=policy, touch=False
            )
            if active is None:
                return None
            current = SignedIn(user.actor, active, user.token, user.via_cookie)
            return set(visible_models(session, current))

    models = await asyncio.to_thread(visible)
    queue = hub.subscribe()

    async def stream() -> AsyncIterator[str]:
        nonlocal models
        started = last_check = time.monotonic()
        try:
            yield ": connected\n\n"
            while True:
                now = time.monotonic()
                if timeout_s is not None and now - started >= timeout_s:
                    return
                if now - last_check >= RECHECK_S:
                    models, last_check = await asyncio.to_thread(visible), now
                if models is None:
                    yield _frame({"type": "session.ended"})
                    return
                wait = max(0.05, min(KEEPALIVE_S, RECHECK_S - (now - last_check)))
                if timeout_s is not None:
                    wait = min(wait, max(0.0, timeout_s - (now - started)))
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=wait)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                model_id = event.get("model_id")
                if model_id is not None and model_id not in models and now - last_check > 5:
                    models, last_check = await asyncio.to_thread(visible), time.monotonic()
                    if models is None:
                        continue  # reported at the top of the loop
                if model_id is None or model_id in models:
                    yield _frame(event)
        finally:
            hub.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
