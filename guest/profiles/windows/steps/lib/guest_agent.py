#!/usr/bin/python3
"""A client of the guest agent for the Windows steps, and its command line.

Usage (reads TT_CONTEXT_JSON for the guest's address and work folder, TT_PROFILE_DIR for the
scripts to upload):

    guest_agent.py answers                      exit 0 if the agent answers, else 1
    guest_agent.py exists NAME                  exit 0 if NAME is in the work folder, else 1
    guest_agent.py retrieve NAME LOCAL_FILE     copy NAME from the work folder
    guest_agent.py retrieve-system NAME LOCAL_FILE   copy NAME from the 64-bit Windows system folder
    guest_agent.py run SCRIPT [--with FILE]... [--arg NAME=VALUE]... [--async]

SCRIPT is a file name in the profile folder, or a path inside it (`selftest/guest-facts.ps1`): the
guest always gets it by its plain name. --with files are paths inside the profile folder too, so a
helper in the profile's root reaches a script in a subfolder, and are stored by their plain names.

TT_AGENT_HOST, when set, is the address to talk to instead of the guest's recorded one: a copy that
has just been cloned answers on the address DHCP gave it, not on the one it will be given.

`run` uploads the script and its helper files to the work folder, runs the script in the 64-bit
PowerShell, prints each line it wrote as a `LOG` line, deletes everything it uploaded and exits with
the script's own exit code. The agent's /execute does not return a process exit code, so a small
driver script, written here and uploaded with the rest, prints `EXITCODE <n>` after the script.
With --async the agent answers at once and the script runs on in the guest: no output, no exit
code, which is for a script that ends the connection by changing the guest's address.
Codes of this program itself: 70 the agent could not be used, 71 the script printed no exit code.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path

AGENT_FAILED = 70
NO_EXIT_CODE = 71
SCRIPT_THREW = 40
DRIVER_NAME = "run.ps1"
# The agent's PowerShell is 32-bit; the 64-bit one is reached through Sysnative. Slash paths,
# because the agent splits the command line like a POSIX shell, which eats backslashes.
POWERSHELL = "C:/Windows/Sysnative/WindowsPowerShell/v1.0/powershell.exe"
# The agent is 32-bit, so `System32` is redirected for it to the 32-bit folder; `Sysnative` is the
# real 64-bit one, where the kernel is.
SYSTEM_DIR = "C:\\Windows\\Sysnative"
EXIT_CODE_LINE = re.compile(r"EXITCODE (-?\d+)\s*")
RESULT_LINE = re.compile(r"\s*RESULT ([^=\s]+)=(.*)")
PLAIN_FILE_NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}")
PARAMETER_NAME = re.compile(r"[A-Za-z][A-Za-z0-9]{0,63}")
WORK_DIR = re.compile(r"[A-Za-z]:\\[A-Za-z0-9_.\\-]+")
DEFAULT_REQUEST_TIMEOUT_S = 10.0
DEFAULT_SCRIPT_TIMEOUT_S = 900.0
RETRIEVE_TIMEOUT_S = 60.0


class AgentError(Exception):
    """The agent could not do what was asked; the message is meant for the build log."""


@dataclass(frozen=True)
class ScriptRun:
    exit_code: int | None
    results: list[tuple[str, str]]
    lines: list[str]
    stderr: str


def parse_results(lines: Sequence[str]) -> list[tuple[str, str]]:
    return [
        (match.group(1), match.group(2)) for line in lines if (match := RESULT_LINE.fullmatch(line))
    ]


def _quoted(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise AgentError("a value for the script holds a line break")
    return "'" + value.replace("'", "''") + "'"


def driver_text(
    script_path: str, arguments: Mapping[str, str], cleanup_paths: Sequence[str]
) -> str:
    """The PowerShell that runs `script_path` and reports its exit code, then deletes the files."""
    parts = [f"& {_quoted(script_path)}"]
    for name, value in arguments.items():
        if not PARAMETER_NAME.fullmatch(name):
            raise AgentError(f"'{name}' is not a parameter name")
        parts.append(f"-{name} {_quoted(value)}")
    removals = ", ".join(_quoted(path) for path in cleanup_paths)
    return (
        "$ErrorActionPreference = 'Continue'\n"
        "$global:LASTEXITCODE = $null\n"
        "try {\n"
        f"  {' '.join(parts)}\n"
        "  $code = if ($null -eq $LASTEXITCODE) { 0 } else { $LASTEXITCODE }\n"
        "} catch {\n"
        "  Write-Output ('RESULT error=' + $_.Exception.Message)\n"
        f"  $code = {SCRIPT_THREW}\n"
        "} finally {\n"
        f"  Remove-Item -Force -ErrorAction SilentlyContinue {removals}\n"
        "}\n"
        'Write-Output "EXITCODE $code"\n'
    )


def _multipart(fields: Mapping[str, str], files: Mapping[str, bytes]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    body = b""
    for name, value in fields.items():
        body += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
        ).encode()
    for name, data in files.items():
        disposition = f'form-data; name="{name}"; filename="{name}"'
        header = f"--{boundary}\r\nContent-Disposition: {disposition}\r\n"
        header += "Content-Type: application/octet-stream\r\n\r\n"
        body += header.encode() + data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


class GuestAgent:
    def __init__(
        self, base_url: str, work_dir: str, *, timeout: float = DEFAULT_REQUEST_TIMEOUT_S
    ) -> None:
        if not WORK_DIR.fullmatch(work_dir):
            raise AgentError(f"the work folder '{work_dir}' is not a plain absolute Windows path")
        self._url = base_url.rstrip("/")
        self._work_dir = work_dir
        self._timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def answers(self) -> bool:
        try:
            with self._opener.open(f"{self._url}/", timeout=self._timeout) as response:
                return response.status == HTTPStatus.OK
        except (OSError, urllib.error.URLError):
            return False

    def exists(self, name: str) -> bool:
        status, _ = self._post("/retrieve", {"filepath": self._remote(name)})
        return status == HTTPStatus.OK

    def retrieve(self, name: str) -> bytes:
        status, body = self._post(
            "/retrieve", {"filepath": self._remote(name)}, timeout=RETRIEVE_TIMEOUT_S
        )
        if status != HTTPStatus.OK:
            raise AgentError(f"could not fetch {name} from the guest (agent answered {status})")
        return body

    def retrieve_system_file(self, name: str) -> bytes:
        """A file of the 64-bit system folder (the kernel, for its symbol id), by plain name."""
        if not PLAIN_FILE_NAME.fullmatch(name):
            raise AgentError(f"'{name}' is not a plain file name")
        status, body = self._post(
            "/retrieve", {"filepath": f"{SYSTEM_DIR}\\{name}"}, timeout=RETRIEVE_TIMEOUT_S
        )
        if status != HTTPStatus.OK:
            raise AgentError(
                f"could not fetch {name} from the guest's system folder (agent answered {status})"
            )
        return body

    def store(self, name: str, data: bytes) -> None:
        status, body = self._post("/store", {"filepath": self._remote(name)}, {"file": data})
        if status != HTTPStatus.OK:
            raise AgentError(f"could not store {name} on the guest: {_message(body, status)}")

    def run_script(
        self,
        local_dir: Path,
        script: str,
        *,
        with_files: Sequence[str] = (),
        arguments: Mapping[str, str] | None = None,
        timeout: float = DEFAULT_SCRIPT_TIMEOUT_S,
    ) -> ScriptRun:
        command = self._upload(local_dir, script, with_files, arguments or {})
        body = self._execute(script, {"command": command}, timeout)
        reply = json.loads(body)
        return _script_run(reply.get("stdout") or "", reply.get("stderr") or "")

    def start_script(
        self,
        local_dir: Path,
        script: str,
        *,
        with_files: Sequence[str] = (),
        arguments: Mapping[str, str] | None = None,
    ) -> None:
        """Start the script and return at once: for one that ends this connection itself."""
        command = self._upload(local_dir, script, with_files, arguments or {})
        self._execute(script, {"command": command, "async": "1"}, self._timeout)

    def _upload(
        self, local_dir: Path, script: str, with_files: Sequence[str], arguments: Mapping[str, str]
    ) -> str:
        """Store the script, its helpers and the driver; the command that runs the driver."""
        read_from = [script, *with_files]
        uploaded = [Path(name).name for name in read_from]
        contents = {
            stored: self._read_local(local_dir, name) for stored, name in zip(uploaded, read_from)
        }
        driver = driver_text(
            self._slashed(script),
            arguments,
            [self._slashed(name) for name in [*uploaded, DRIVER_NAME]],
        )
        for name, data in contents.items():
            self.store(name, data)
        self.store(DRIVER_NAME, driver.encode("ascii"))
        return f"{POWERSHELL} -NoProfile -ExecutionPolicy Bypass -File {self._slashed(DRIVER_NAME)}"

    def _execute(self, script: str, fields: Mapping[str, str], timeout: float) -> bytes:
        status, body = self._post("/execute", fields, timeout=timeout)
        if status != HTTPStatus.OK:
            raise AgentError(f"the guest agent refused to run {script}: {_message(body, status)}")
        return body

    def _post(
        self,
        path: str,
        fields: Mapping[str, str],
        files: Mapping[str, bytes] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, bytes]:
        body, content_type = _multipart(fields, files or {})
        request = urllib.request.Request(  # noqa: S310 - the guest's address from the build context
            f"{self._url}{path}", data=body, headers={"Content-Type": content_type}
        )
        try:
            with self._opener.open(request, timeout=timeout or self._timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as refusal:
            return refusal.code, refusal.read()
        except (OSError, urllib.error.URLError) as problem:
            raise AgentError(f"the guest agent at {self._url} did not answer: {problem}") from None

    def _remote(self, name: str) -> str:
        if not PLAIN_FILE_NAME.fullmatch(name):
            raise AgentError(f"'{name}' is not a plain file name")
        return f"{self._work_dir}\\{name}"

    def _slashed(self, name: str) -> str:
        return self._remote(name).replace("\\", "/")

    @staticmethod
    def _read_local(directory: Path, name: str) -> bytes:
        try:
            return (directory / name).read_bytes()
        except OSError:
            raise AgentError(f"{name} is not in {directory}") from None


def _message(body: bytes, status: int) -> str:
    try:
        return str(json.loads(body)["message"])
    except (ValueError, KeyError, TypeError):
        return f"HTTP {status}"


def _script_run(stdout: str, stderr: str) -> ScriptRun:
    exit_code = None
    lines = []
    for line in stdout.splitlines():
        if match := EXIT_CODE_LINE.fullmatch(line):
            exit_code = int(match.group(1))
        elif line.strip():
            lines.append(line)
    return ScriptRun(exit_code, parse_results(lines), lines, stderr)


def _agent_from_environment() -> GuestAgent:
    context = json.loads(Path(os.environ["TT_CONTEXT_JSON"]).read_text(encoding="utf-8"))
    guest, agent = context["guest"], context["profile"]["agent"]
    host = os.environ.get("TT_AGENT_HOST") or guest["ip"]
    return GuestAgent(f"http://{host}:{agent['port']}", guest["work_dir"])


def _arguments_from(pairs: Sequence[str]) -> dict[str, str]:
    return dict(pair.partition("=")[::2] for pair in pairs)


def _script_location(script: str) -> tuple[Path, str]:
    """The folder to read `script` from and the plain name it is stored under in the guest."""
    path = Path(script)
    if path.is_absolute() or ".." in path.parts:
        raise AgentError(f"'{script}' must be a path inside the profile folder")
    return Path(os.environ["TT_PROFILE_DIR"]) / path.parent, path.name


def _helper_locations(helpers: Sequence[str], script_dir: Path) -> list[str]:
    """Each helper, a path inside the profile folder, as the path to read it from `script_dir`."""
    locations = []
    for helper in helpers:
        helper_dir, name = _script_location(helper)
        locations.append(os.path.relpath(helper_dir / name, script_dir))
    return locations


def _run(agent: GuestAgent, options: argparse.Namespace) -> int:
    local_dir, script = _script_location(options.script)
    with_files = _helper_locations(options.with_files, local_dir)
    arguments = _arguments_from(options.arg)
    if options.asynchronous:
        agent.start_script(local_dir, script, with_files=with_files, arguments=arguments)
        return 0
    result = agent.run_script(
        local_dir,
        script,
        with_files=with_files,
        arguments=arguments,
        timeout=options.timeout,
    )
    for line in result.lines:
        sys.stdout.write(f"LOG {line}\n")
    if result.exit_code is None:
        sys.stderr.write(f"{script} printed no exit code; stderr: {result.stderr}\n")
        return NO_EXIT_CODE
    return result.exit_code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="guest_agent.py")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("answers")
    commands.add_parser("exists").add_argument("name")
    retrieve = commands.add_parser("retrieve")
    retrieve.add_argument("name")
    retrieve.add_argument("local_file", type=Path)
    retrieve_system = commands.add_parser("retrieve-system")
    retrieve_system.add_argument("name")
    retrieve_system.add_argument("local_file", type=Path)
    run = commands.add_parser("run")
    run.add_argument("script")
    run.add_argument("--with", dest="with_files", action="append", default=[])
    run.add_argument("--arg", action="append", default=[])
    run.add_argument("--timeout", type=float, default=DEFAULT_SCRIPT_TIMEOUT_S)
    run.add_argument("--async", dest="asynchronous", action="store_true")
    return parser


def main(argv: Sequence[str]) -> int:
    options = _parser().parse_args(argv)
    try:
        agent = _agent_from_environment()
        if options.command == "answers":
            return 0 if agent.answers() else 1
        if options.command == "exists":
            return 0 if agent.exists(options.name) else 1
        if options.command == "retrieve":
            options.local_file.write_bytes(agent.retrieve(options.name))
            return 0
        if options.command == "retrieve-system":
            options.local_file.write_bytes(agent.retrieve_system_file(options.name))
            return 0
        return _run(agent, options)
    except AgentError as problem:
        sys.stderr.write(f"guest agent: {problem}\n")
        return AGENT_FAILED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
