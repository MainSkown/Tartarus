"""The daemon: reconciles session files into listeners and serves each connection to its session.

A session file in the shared directory is the whole interface. For every file the daemon binds a
listener per (host address, service port) of that session's hosts, shared and refcounted when
sessions share a host, and removes listeners no session needs. A connection is served only if its
source address is some session's guest and the destination is a host of that same session; any
other connection is closed at once and counted. The daemon never runs anything a client sends.
"""

import asyncio
import logging
import os
from collections import Counter
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field

from lan_session import (
    Layout,
    SessionFormatError,
    SessionSpec,
    SessionStatus,
    read_session,
    read_status,
    session_keys,
    status_keys,
    write_status,
)
from lan_sim.clock import Clock, SystemClock
from lan_sim.events import Endpoint
from lan_sim.limits import Limits
from lan_sim.service import Connection, FrameworkError, PeerClosed, Service
from lan_sim.session_log import (
    REFUSED_FOREIGN_HOST,
    REFUSED_PORT_NOT_SERVED,
    REFUSED_SESSION_LIMIT,
    REFUSED_SOURCE_LIMIT,
    FileSink,
    SessionLog,
)

DEFAULT_POLL_INTERVAL_S = 0.5
LISTENER_CLOSE_TIMEOUT_S = 2.0

Signature = tuple[int, int, int]
Address = tuple[str, int]


class _BindError(Exception):
    pass


@dataclass
class _Listener:
    server: asyncio.Server
    owners: set[str] = field(default_factory=set)


@dataclass(eq=False)
class _ActiveSession:
    spec: SessionSpec
    log: SessionLog
    signature: Signature
    endpoints: list[Address] = field(default_factory=list)
    tasks: set[asyncio.Task[None]] = field(default_factory=set)
    open_by_service: Counter[tuple[str, str]] = field(default_factory=Counter)
    open_total: int = 0

    def admit(self, source_ip: str, kind: str, limits: Limits) -> str | None:
        """Counts the connection in and returns None, or returns why it must be refused."""
        if self.open_total >= limits.max_connections_per_session:
            return REFUSED_SESSION_LIMIT
        if self.open_by_service[(source_ip, kind)] >= limits.max_connections_per_source_service:
            return REFUSED_SOURCE_LIMIT
        self.open_by_service[(source_ip, kind)] += 1
        self.open_total += 1
        return None

    def release(self, source_ip: str, kind: str) -> None:
        self.open_by_service[(source_ip, kind)] -= 1
        self.open_total -= 1


def _endpoint(address: object) -> Endpoint | None:
    if isinstance(address, tuple) and len(address) >= 2:  # noqa: PLR2004 - (host, port[, ...])
        return Endpoint(str(address[0]), int(address[1]))
    return None


class Daemon:
    def __init__(  # noqa: PLR0913 - collaborators the tests replace
        self,
        layout: Layout,
        services: Mapping[str, Service],
        *,
        limits: Limits | None = None,
        clock: Clock | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL_S,
        logger: logging.Logger | None = None,
    ) -> None:
        for kind, service in services.items():
            if service.kind != kind:
                raise ValueError(
                    f"the service registered as {kind!r} says its kind is {service.kind!r}"
                )
        self._layout = layout
        self._services = dict(services)
        self._limits = limits or Limits()
        self._clock = clock or SystemClock()
        self._poll_interval = poll_interval
        self._logger = logger or logging.getLogger("lan_sim")
        self._sessions: dict[str, _ActiveSession] = {}
        self._by_guest: dict[str, _ActiveSession] = {}
        self._failed: dict[str, Signature] = {}
        self._listeners: dict[Address, _Listener] = {}
        self._stop = asyncio.Event()
        self.refused_unknown_source = 0

    def request_stop(self) -> None:
        self._stop.set()

    def active_connections(self, key: str) -> int:
        session = self._sessions.get(key)
        return session.open_total if session else 0

    def listening_endpoints(self) -> set[Address]:
        return set(self._listeners)

    async def run(self) -> None:
        self._layout.status_dir.mkdir(parents=True, exist_ok=True)
        self._layout.logs_dir.mkdir(parents=True, exist_ok=True)
        self._close_stale_statuses()
        try:
            while not self._stop.is_set():
                await self._reconcile_once_safely()
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), self._poll_interval)
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        for key in list(self._sessions):
            await self._close_session(key)
        self._logger.info(
            "stopped; %d connections from unknown sources were refused", self.refused_unknown_source
        )

    async def reconcile(self) -> None:
        """One pass: closes sessions whose file is gone or changed, opens new ones."""
        on_disk = {key: self._signature(key) for key in session_keys(self._layout)}
        for key, active in list(self._sessions.items()):
            if on_disk.get(key) != active.signature:
                await self._close_session(key)
        for key, signature in list(self._failed.items()):
            if on_disk.get(key) != signature:
                del self._failed[key]
                if key not in on_disk:
                    self._write_status(key, SessionStatus("closed"))
        for key, signature in on_disk.items():
            if signature is not None and key not in self._sessions and key not in self._failed:
                await self._open_session(key, signature)

    async def _reconcile_once_safely(self) -> None:
        try:
            await self.reconcile()
        except Exception as error:  # noqa: BLE001 - one bad pass must not stop the daemon
            self._logger.error("reconcile failed: %s", type(error).__name__)

    def _signature(self, key: str) -> Signature | None:
        try:
            stat = os.stat(self._layout.session_file(key), follow_symlinks=False)
        except FileNotFoundError:
            return None
        return (stat.st_mtime_ns, stat.st_size, stat.st_ino)

    def _close_stale_statuses(self) -> None:
        present = set(session_keys(self._layout))
        for key in status_keys(self._layout):
            try:
                status = read_status(self._layout, key)
            except (SessionFormatError, OSError):
                status = None
            if key not in present and (status is None or status.state != "closed"):
                self._write_status(key, SessionStatus("closed"))

    def _write_status(self, key: str, status: SessionStatus) -> None:
        try:
            write_status(self._layout, key, status)
        except OSError as error:
            self._logger.error("cannot write the status of session %s: %s", key, error.strerror)

    # --- opening ----------------------------------------------------------------------------------

    def _fail(self, key: str, signature: Signature, error: str) -> None:
        self._failed[key] = signature
        self._logger.warning("session %s failed: %s", key, error)
        self._write_status(key, SessionStatus("failed", error))

    def _problem_with(self, spec: SessionSpec) -> str | None:
        owner = self._by_guest.get(spec.guest_address)
        if owner is not None:
            return f"guest address {spec.guest_address} already has session {owner.spec.key}"
        for host in spec.hosts:
            for service in host.services:
                if service.kind not in self._services:
                    return f"no service registered for kind {service.kind!r}"
        return None

    async def _open_session(self, key: str, signature: Signature) -> None:
        try:
            spec = read_session(self._layout, key)
        except FileNotFoundError:
            return
        except (SessionFormatError, OSError) as error:
            self._fail(key, signature, str(error))
            return
        problem = self._problem_with(spec)
        if problem is not None:
            self._fail(key, signature, problem)
            return
        sink = FileSink(self._layout.log_file(key))
        active = _ActiveSession(spec, SessionLog(key, sink, self._clock, self._limits), signature)
        self._sessions[key] = active
        self._by_guest[spec.guest_address] = active
        try:
            await self._bind(active)
        except _BindError as error:
            self._unregister(active)
            await self._release_listeners(active)
            self._fail(key, signature, str(error))
            return
        self._logger.info("session %s listening on %d endpoints", key, len(active.endpoints))
        self._write_status(key, SessionStatus("listening"))

    async def _bind(self, active: _ActiveSession) -> None:
        for address, port in active.spec.endpoints():
            listener = self._listeners.get((address, port))
            if listener is None:
                try:
                    server = await asyncio.start_server(
                        self._handle,
                        host=address,
                        port=port,
                        reuse_address=True,
                        limit=self._limits.max_bytes_read_per_connection,
                    )
                except OSError as error:
                    raise _BindError(
                        f"cannot listen on {address}:{port}: {error.strerror or error}"
                    ) from error
                listener = self._listeners[(address, port)] = _Listener(server)
            listener.owners.add(active.spec.key)
            active.endpoints.append((address, port))

    # --- closing ----------------------------------------------------------------------------------

    def _unregister(self, active: _ActiveSession) -> None:
        self._sessions.pop(active.spec.key, None)
        if self._by_guest.get(active.spec.guest_address) is active:
            del self._by_guest[active.spec.guest_address]

    async def _release_listeners(self, active: _ActiveSession) -> None:
        servers = []
        for endpoint in active.endpoints:
            listener = self._listeners[endpoint]
            listener.owners.discard(active.spec.key)
            if not listener.owners:
                del self._listeners[endpoint]
                listener.server.close()
                servers.append(listener.server)
        active.endpoints.clear()
        for server in servers:
            with suppress(TimeoutError):
                await asyncio.wait_for(server.wait_closed(), LISTENER_CLOSE_TIMEOUT_S)

    async def _cancel_connections(self, active: _ActiveSession) -> None:
        tasks = tuple(active.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _close_session(self, key: str) -> None:
        active = self._sessions.get(key)
        if active is None:
            return
        self._unregister(active)
        await self._cancel_connections(active)
        await self._release_listeners(active)
        active.log.close()
        self._write_status(key, SessionStatus("closed"))
        self._logger.info("session %s closed", key)

    # --- serving ----------------------------------------------------------------------------------

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await self._dispatch(reader, writer)
        finally:
            writer.close()

    async def _dispatch(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        source = _endpoint(writer.get_extra_info("peername"))
        destination = _endpoint(writer.get_extra_info("sockname"))
        session = self._by_guest.get(source.ip) if source else None
        if session is None or source is None or destination is None:
            self.refused_unknown_source += 1
            return
        host = session.spec.host_at(destination.ip)
        if host is None:
            session.log.count_refused(REFUSED_FOREIGN_HOST)
            return
        service = host.service_on(destination.port)
        if service is None:
            session.log.count_refused(REFUSED_PORT_NOT_SERVED)
            return
        refusal = session.admit(source.ip, service.kind, self._limits)
        if refusal is not None:
            session.log.count_refused(refusal)
            return
        try:
            connection = Connection(
                reader=reader,
                writer=writer,
                host=host,
                service=service,
                session=session.spec,
                source=source,
                destination=destination,
                log=session.log.connection_log(host.fqdn, service.kind, source, destination),
                clock=self._clock,
                limits=self._limits,
            )
            await self._run_connection(session, connection)
        finally:
            session.release(source.ip, service.kind)

    async def _run_connection(self, session: _ActiveSession, connection: Connection) -> None:
        task = asyncio.current_task()
        if task is not None:
            session.tasks.add(task)
        started = self._clock.monotonic()
        try:
            await self._serve(self._services[connection.service.kind], connection)
        finally:
            if task is not None:
                session.tasks.discard(task)
            elapsed = self._clock.monotonic() - started
            connection.log.connection(
                bytes_in=connection.bytes_in,
                bytes_out=connection.bytes_out,
                duration_ms=int(elapsed * 1000),
            )

    async def _serve(self, service: Service, connection: Connection) -> None:
        lifetime = asyncio.timeout(self._limits.max_connection_seconds)
        try:
            async with lifetime:
                await service.serve(connection)
        except PeerClosed:
            pass
        except FrameworkError as error:
            connection.log.service_request(name=error.record_name, detail=str(error))
        except TimeoutError:
            reason = "connection-too-long" if lifetime.expired() else "service-error"
            connection.log.service_request(name=reason, detail="TimeoutError")
        except Exception as error:  # noqa: BLE001 - a service bug must not take the daemon down
            connection.log.service_request(name="service-error", detail=type(error).__name__)
            self._logger.warning(
                "service %s raised %s", connection.service.kind, type(error).__name__
            )
