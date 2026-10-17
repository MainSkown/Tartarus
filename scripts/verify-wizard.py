#!/usr/bin/env python3
"""Proves the guest wizard's backend path through the public API (make verify-wizard).

Clones a ready guest into a throwaway one with Defender switched the other way, checks that
analyses and a second clone are refused while it builds, waits for its self-test to make it
ready, runs an analysis on it, and deletes it. Needs the stack up and one ready guest; takes
about six minutes. Exit 0 when every check passes.
"""

# ruff: noqa: T201
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Protocol

BUILD_TIMEOUT_S = 1200
ANALYSIS_TIMEOUT_S = 300
POLL_S = 5
GATE_PROBE_DELAY_S = 20


@dataclass(frozen=True)
class Result:
    name: str
    ok: bool
    message: str = ""


def format_result(result: Result) -> str:
    tag = "[ OK ]" if result.ok else "[FAIL]"
    return f"{tag} {result.name}" + (f": {result.message}" if result.message else "")


class Api(Protocol):
    def request(self, method: str, path: str, **kwargs: Any) -> tuple[int, Any]: ...


class HttpApi:
    def __init__(self, base: str) -> None:
        self._base = base.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        upload: tuple[str, bytes, dict[str, Any]] | None = None,
    ) -> tuple[int, Any]:
        url = f"{self._base}/api{path}"
        headers: dict[str, str] = {}
        data: bytes | None = None
        if upload is not None:
            filename, content, options = upload
            boundary = uuid.uuid4().hex
            parts = [
                f'--{boundary}\r\nContent-Disposition: form-data; name="options"\r\n\r\n'
                f"{json.dumps(options)}\r\n".encode(),
                f"--{boundary}\r\nContent-Disposition: form-data; "
                f'name="file"; filename="{filename}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n".encode()
                + content
                + b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
            data = b"".join(parts)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310 - the local stack's own URL
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                raw = response.read()
                return response.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                return error.code, json.loads(raw) if raw else None
            except ValueError:
                return error.code, raw.decode(errors="replace")


def _message(body: Any) -> str:
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return str(body["error"].get("message", ""))
    return str(body)[:200]


def _job_outcome(job: Any, verdict: dict[str, Any] | None) -> str:
    if not isinstance(job, dict):
        return str(job)[:200]
    detail = (verdict or {}).get("message") or str(job.get("log", ""))[-200:]
    return f"job {job.get('status')}: {detail}"


def _wait(
    api: Api,
    path: str,
    done: Callable[[Any], bool],
    timeout_s: float,
    sleep: Callable[[float], None],
) -> tuple[int, Any]:
    deadline = time.monotonic() + timeout_s
    while True:
        status, body = api.request("GET", path)
        if (status == HTTPStatus.OK and done(body)) or time.monotonic() > deadline:
            return status, body
        sleep(POLL_S)


def verify(
    api: Api,
    *,
    source: str | None,
    name: str,
    sample: bytes,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Result]:
    results: list[Result] = []

    def check(check_name: str, ok: bool, message: str = "") -> bool:
        results.append(Result(check_name, ok, message))
        return ok

    status, health = api.request("GET", "/system/health")
    check(
        "the guest control service answers",
        status == HTTPStatus.OK and health["guest"]["status"] != "down",
        str(health)[:120],
    )
    status, profiles = api.request("GET", "/guests/profiles")
    check("profiles are listed", status == HTTPStatus.OK and bool(profiles), f"{status}")
    status, media = api.request("GET", "/guests/media")
    check(
        "installation media is listed",
        status == HTTPStatus.OK and isinstance(media, list),
        f"{status}",
    )

    status, guests = api.request("GET", "/guests")
    ready = [g for g in guests if g.get("state") == "ready"] if status == HTTPStatus.OK else []
    # An adopted guest carries giveaways that fail its clone's self-test on purpose.
    chosen = next(
        (g for g in ready if g["name"] == source or (source is None and not g.get("giveaways"))),
        None,
    )
    if not check("a ready guest to clone", chosen is not None, f"{len(ready)} ready"):
        return results
    defender_on = "DEFENDER ON" in (chosen.get("badges") or [])

    status, started = api.request(
        "POST",
        f"/guests/{chosen['name']}/clone",
        body={"name": name, "options": {"defender": not defender_on}},
    )
    if not check("the clone starts", status == HTTPStatus.ACCEPTED, _message(started)):
        return results
    job = started["job_id"]
    created = True
    try:
        sleep(GATE_PROBE_DELAY_S)
        status, refused = api.request(
            "POST",
            "/analyses",
            upload=(
                "probe.exe",
                sample,
                {"guest": chosen["name"], "package": "exe", "timeout": 60},
            ),
        )
        check(
            "analysis refused while a guest is being built",
            status == HTTPStatus.CONFLICT,
            f"{status} {_message(refused)}",
        )
        status, second = api.request(
            "POST", f"/guests/{chosen['name']}/clone", body={"name": f"{name}-2"}
        )
        check(
            "a second clone is refused while one runs",
            status == HTTPStatus.CONFLICT,
            f"{status} {_message(second)}",
        )

        status, final = _wait(
            api,
            f"/jobs/{job}",
            lambda j: j["status"] in ("done", "failed", "interrupted"),
            BUILD_TIMEOUT_S,
            sleep,
        )
        verdict = (
            ((final or {}).get("result") or {}).get("selftest") if isinstance(final, dict) else None
        )
        reached = status == HTTPStatus.OK and final["status"] == "done"
        check("clone reaches ready", reached, _job_outcome(final, verdict))
        if not reached:
            return results

        status, guests = api.request("GET", "/guests")
        new = next((g for g in guests if g["name"] == name), {}) if status == HTTPStatus.OK else {}
        expected = "DEFENDER OFF" if defender_on else "DEFENDER ON"
        check(
            "the new guest carries the Defender badge asked for",
            expected in (new.get("badges") or []),
            str(new.get("badges")),
        )

        status, submitted = api.request(
            "POST",
            "/analyses",
            upload=("probe.exe", sample, {"guest": name, "package": "exe", "timeout": 60}),
        )
        if check(
            "an analysis is accepted on the new guest",
            status == HTTPStatus.CREATED,
            _message(submitted),
        ):
            status, analysis = _wait(
                api,
                f"/analyses/{submitted['id']}",
                lambda a: a["status"] in ("done", "failed", "report_failed", "cancelled"),
                ANALYSIS_TIMEOUT_S,
                sleep,
            )
            ok = (
                status == HTTPStatus.OK
                and analysis["status"] == "done"
                and analysis.get("guest") == name
            )
            check(
                "analysis runs on the new guest",
                ok,
                f"{analysis.get('status') if isinstance(analysis, dict) else status}",
            )
    finally:
        if created:
            api.request("GET", f"/jobs/{job}")
            status, _ = api.request("DELETE", f"/guests/{name}")
            check(
                "the throwaway guest is deleted",
                status in (HTTPStatus.NO_CONTENT, HTTPStatus.NOT_FOUND),
                f"{status}",
            )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base", default="http://localhost:8080", help="Tartarus address (default %(default)s)"
    )
    parser.add_argument("--source", help="the ready guest to clone (default: the first ready one)")
    parser.add_argument("--sample", required=True, help="a harmless Windows executable to detonate")
    args = parser.parse_args(argv)
    with open(args.sample, "rb") as handle:
        sample = handle.read()
    results = verify(
        HttpApi(args.base), source=args.source, name=f"vw-{uuid.uuid4().hex[:6]}", sample=sample
    )
    for result in results:
        print(format_result(result), flush=True)
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
