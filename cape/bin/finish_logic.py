"""Ends a running analysis early by asking the guest's agent for a folder.

CAPE's analyzer in the guest stops the analysis as soon as a folder named md5("cape-<task id>")
exists in the guest's temp directory (analyzer/windows/analyzer.py, analysis_loop). The guest
network exists only inside the cape container, so only a service in it can ask the agent to
create that folder. Used by `guest-control`, for the guest named in the request.
"""

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

# A CAPE task id is a database integer; more digits than this is not one.
MAX_TASK_ID_DIGITS = 18
ERROR_MESSAGE_LIMIT = 200
# The guest is on a local network; a proxy in the environment must never get this request.
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))

type Answer = tuple[int, dict[str, Any]]


def completion_folder(task_id: int) -> str:
    # The name CAPE's analyzer looks for; not a security use of md5.
    return hashlib.md5(f"cape-{task_id}".encode()).hexdigest()  # noqa: S324


def folder_path(finish_dir: str, task_id: int) -> str:
    separator = "\\" if "\\" in finish_dir else "/"
    return f"{finish_dir.rstrip(separator)}{separator}{completion_folder(task_id)}"


def parse_task_id(raw: str) -> int | None:
    if not re.fullmatch(f"[0-9]{{1,{MAX_TASK_ID_DIGITS}}}", raw):
        return None
    return int(raw)


def mkdir_request(agent_url: str, directory: str) -> urllib.request.Request:
    # No `mode`: the agent defaults to 0o777 and Windows ignores it.
    form = urllib.parse.urlencode({"dirpath": directory})
    # The URL is built from an address the engine gave, never from the request.
    return urllib.request.Request(f"{agent_url}/mkdir", data=form.encode(), method="POST")  # noqa: S310


def finish_response(
    raw_task_id: str,
    destination: Callable[[], tuple[str, str]],
    timeout: float,
    send: Callable[..., Any] = DIRECT.open,
) -> Answer:
    """`destination` returns the agent's URL and the finish directory; it is asked only once the
    task id is known to be digits, so a malformed request looks nothing up."""
    task_id = parse_task_id(raw_task_id)
    if task_id is None:
        return 400, {"error": "the task id must be digits only"}
    agent_url, finish_dir = destination()
    return finish_task(task_id, agent_url, finish_dir, timeout, send)


def finish_task(
    task_id: int,
    agent_url: str,
    finish_dir: str,
    timeout: float,
    send: Callable[..., Any] = DIRECT.open,
) -> Answer:
    """Asks the guest agent for the folder; returns the HTTP status and JSON body to answer with."""
    request = mkdir_request(agent_url, folder_path(finish_dir, task_id))
    try:
        with send(request, timeout=timeout) as answer:
            agent_status = answer.status
            body = answer.read()
    except urllib.error.HTTPError as refused:
        detail = _agent_message(refused.read())
        suffix = f": {detail}" if detail else ""
        return 502, {"error": f"the guest agent refused (HTTP {refused.code}){suffix}"}
    except (OSError, ValueError) as unreachable:
        return 502, {"error": f"the guest agent is unreachable ({type(unreachable).__name__})"}
    if agent_status != 200:  # noqa: PLR2004 - the agent's success status
        return 502, {"error": f"the guest agent answered HTTP {agent_status}"}
    if not isinstance(_json_or_none(body), dict):
        return 502, {"error": "the guest agent answered something that is not JSON"}
    return 200, {"finished": True}


def _agent_message(body: bytes) -> str:
    # The agent's 500 carries a traceback next to its message; only the message is repeated.
    try:
        message = json.loads(body).get("message")
    except (ValueError, AttributeError):
        return ""
    return message[:ERROR_MESSAGE_LIMIT] if isinstance(message, str) else ""


def _json_or_none(body: bytes) -> object:
    try:
        return json.loads(body)
    except ValueError:
        return None
