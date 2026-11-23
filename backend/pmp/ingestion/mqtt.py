"""Live data over MQTT (PHI-001 §5.1, change 1 of §19).

PMP subscribes to `<prefix>/+/samples` on the plant broker with QoS 1 and a persistent
session. Each message is one JSON batch; it is mapped, checked and stored exactly as a
REST batch, and acknowledged (PUBACK) only after the database commit, so a crash before
the commit makes the broker deliver it again. A message that cannot be read is kept in
the reject log with its reason and acknowledged; the subscriber never stops on one bad
message. The connection state is written for the ingestion-health screen.
"""

from __future__ import annotations

import json
import logging
import ssl
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from paho.mqtt import client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from pydantic import ValidationError

from pmp.core import Database
from pmp.ingestion.domain import BatchIn
from pmp.ingestion.service import ingest_batch, log_rejection, set_transport_state

logger = logging.getLogger(__name__)
TRANSPORT = "mqtt"
STATE_EVERY = timedelta(seconds=5)  # the last-message time is written at most this often


@dataclass(frozen=True)
class BrokerConfig:
    url: str  # mqtt://host:1883 or mqtts://host:8883
    topic_prefix: str = "pmp/v1"
    username: str | None = None
    password: str | None = None
    ca_file: Path | None = None
    client_id: str = "pmp-subscriber"

    @property
    def topic(self) -> str:
        return f"{self.topic_prefix.rstrip('/')}/+/samples"

    @property
    def display_url(self) -> str:
        """The URL without credentials, for the screen and the logs."""
        u = urlparse(self.url)
        return f"{u.scheme}://{u.hostname}:{self.port}"

    @property
    def tls(self) -> bool:
        return urlparse(self.url).scheme in ("mqtts", "ssl")

    @property
    def port(self) -> int:
        return urlparse(self.url).port or (8883 if self.tls else 1883)

    @property
    def host(self) -> str:
        return urlparse(self.url).hostname or "localhost"


def source_of(topic: str, prefix: str) -> str | None:
    """`pmp/v1/gw-site-a-01/samples` -> `gw-site-a-01`; None for any other topic."""
    head = prefix.rstrip("/") + "/"
    if not topic.startswith(head) or not topic.endswith("/samples"):
        return None
    source = topic[len(head) : -len("/samples")]
    return source if source and "/" not in source else None


def handle_message(
    database: Database,
    config: BrokerConfig,
    topic: str,
    payload: bytes,
    *,
    now: datetime,
    late_window: timedelta,
) -> tuple[int, int]:
    """Store one message in one transaction. Returns (accepted, rejected). A message that
    cannot be read is kept in the reject log and counts as one rejection."""
    source = source_of(topic, config.topic_prefix) or topic[:100]
    reason, detail = None, None
    batch = None
    try:
        data = json.loads(payload)
        if isinstance(data, dict) and "source" not in data:
            data["source"] = source
        batch = BatchIn.model_validate(data)
        if batch.source != source:
            reason, detail = "source_mismatch", f"payload source {batch.source!r} on {topic}"
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        reason, detail = "malformed", f"not JSON: {error}"
    except ValidationError as error:
        reason, detail = "malformed", str(error.errors()[0].get("msg", "invalid"))[:500]
    with database.session() as session:
        if reason is not None or batch is None:
            log_rejection(
                session,
                source=source,
                transport=TRANSPORT,
                reason=reason or "malformed",
                now=now,
                detail=detail,
            )
            return 0, 1
        result = ingest_batch(session, batch, now=now, late_window=late_window, transport=TRANSPORT)
    return result.accepted, len(result.rejected)


class Subscriber:
    """Subscribes and stores until stopped. One instance per process."""

    def __init__(
        self,
        database: Database,
        config: BrokerConfig,
        *,
        late_window: timedelta,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.database = database
        self.config = config
        self.late_window = late_window
        self.clock = clock
        self.stopping = threading.Event()
        self._last_state: datetime | None = None
        self.client = make_client(config, clean_start=False)
        self.client.manual_ack_set(True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _state(self, connected: bool, error: str | None = None, message: bool = False) -> None:
        now = self.clock()
        try:
            with self.database.session() as session:
                set_transport_state(
                    session,
                    TRANSPORT,
                    url=self.config.display_url,
                    topic=self.config.topic,
                    connected=connected,
                    now=now,
                    error=error,
                    message_at=now if message else None,
                )
        except Exception:  # the state is informative; never stop the subscriber over it
            logger.exception("Could not record the MQTT connection state")

    def _on_connect(self, client: mqtt.Client, _u: Any, _f: Any, reason: Any, _p: Any) -> None:
        if reason.is_failure:
            logger.warning("MQTT connection refused: %s", reason)
            self._state(False, f"Connection refused: {reason}")
            return
        client.subscribe(self.config.topic, qos=1)
        logger.info("Subscribed to %s on %s", self.config.topic, self.config.display_url)
        self._state(True)

    def _on_disconnect(self, _c: mqtt.Client, _u: Any, _f: Any, reason: Any, _p: Any) -> None:
        if not self.stopping.is_set():
            logger.warning("MQTT connection lost: %s", reason)
        self._state(False, None if self.stopping.is_set() else f"Connection lost: {reason}")

    def _on_message(self, client: mqtt.Client, _u: Any, message: mqtt.MQTTMessage) -> None:
        now = self.clock()
        try:
            handle_message(
                self.database,
                self.config,
                message.topic,
                bytes(message.payload),
                now=now,
                late_window=self.late_window,
            )
        except Exception:
            # Not acknowledged: the broker delivers it again after a reconnect.
            logger.exception("Could not store an MQTT message on %s", message.topic)
            return
        client.ack(message.mid, message.qos)  # PUBACK only after the commit
        if self._last_state is None or now - self._last_state >= STATE_EVERY:
            self._last_state = now
            self._state(True, message=True)

    def run(self) -> None:
        self.client.reconnect_delay_set(min_delay=1, max_delay=60)
        while not self.stopping.is_set():
            try:
                self.client.connect(self.config.host, self.config.port, keepalive=30)
                break
            except OSError as error:
                logger.warning("Cannot reach the MQTT broker: %s", error)
                self._state(False, f"Cannot reach the broker: {error}")
                self.stopping.wait(10)
        self.client.loop_start()
        self.stopping.wait()
        self.client.disconnect()
        self.client.loop_stop()

    def stop(self) -> None:
        self.stopping.set()


def make_client(config: BrokerConfig, *, clean_start: bool) -> mqtt.Client:
    client = mqtt.Client(
        CallbackAPIVersion.VERSION2,
        client_id=config.client_id,
        protocol=mqtt.MQTTv311,
        clean_session=clean_start,  # persistent session: QoS 1 messages wait while away
    )
    if config.username:
        client.username_pw_set(config.username, config.password)
    if config.tls:
        context = ssl.create_default_context(cafile=str(config.ca_file) if config.ca_file else None)
        client.tls_set_context(context)
    return client


def check_broker(config: BrokerConfig, timeout_s: float = 5.0) -> tuple[bool, str]:
    """Connect once with a throw-away client id and report what happened."""
    done = threading.Event()
    outcome: dict[str, Any] = {}
    probe = BrokerConfig(
        config.url,
        config.topic_prefix,
        config.username,
        config.password,
        config.ca_file,
        f"{config.client_id}-test",
    )
    client = make_client(probe, clean_start=True)

    def on_connect(_c: mqtt.Client, _u: Any, _f: Any, reason: Any, _p: Any) -> None:
        outcome["ok"] = not reason.is_failure
        outcome["text"] = "Connected" if outcome["ok"] else f"Refused: {reason}"
        done.set()

    client.on_connect = on_connect
    try:
        client.connect(probe.host, probe.port, keepalive=10)
    except OSError as error:
        return False, f"Cannot reach {probe.display_url}: {error}"
    client.loop_start()
    finished = done.wait(timeout_s)
    client.disconnect()
    client.loop_stop()
    if not finished:
        return False, f"No answer from {probe.display_url} within {timeout_s:g} s"
    return bool(outcome["ok"]), str(outcome["text"])
