import json
from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from app.db.models.analysis import AnalysisPhase, AnalysisStatus
from app.live.messages import (
    ClientMessage,
    CountsData,
    CountsMessage,
    ErrorData,
    ErrorMessage,
    EventsData,
    EventsMessage,
    LiveMessage,
    LiveProcess,
    PhaseData,
    PhaseMessage,
    PingMessage,
    PongMessage,
    ProcessData,
    ProcessMessage,
    StatusData,
    StatusMessage,
    SubscribeMessage,
)

NOW = datetime(2026, 10, 13, 12, 0, 0, tzinfo=UTC)
SERVER_MESSAGES = TypeAdapter(LiveMessage)
CLIENT_MESSAGES = TypeAdapter(ClientMessage)


def every_server_message() -> list[LiveMessage]:
    return [
        StatusMessage(
            ts=NOW,
            data=StatusData(
                status=AnalysisStatus.RUNNING,
                phase=AnalysisPhase.LIVE,
                elapsed_s=12.5,
                remaining_s=167.5,
            ),
        ),
        EventsMessage(ts=NOW, data=EventsData(events=[{"event": {"id": "a"}}], dropped=3)),
        ProcessMessage(
            ts=NOW, data=ProcessData(op="add", node=LiveProcess(pid=4, ppid=None, name="a.exe"))
        ),
        CountsMessage(
            ts=NOW, data=CountsData(by_lane={"file": 2}, by_severity={"info": 2}, total=2)
        ),
        PhaseMessage(ts=NOW, data=PhaseData()),
        ErrorMessage(ts=NOW, data=ErrorData(code="log_format", message="bad")),
        PongMessage(ts=NOW),
    ]


@pytest.mark.parametrize("message", every_server_message(), ids=lambda m: m.type)
def test_every_server_message_has_the_type_ts_data_envelope(message: LiveMessage) -> None:
    wire = json.loads(message.model_dump_json())

    assert set(wire) == {"type", "ts", "data"}
    assert wire["ts"] == "2026-10-13T12:00:00Z"


@pytest.mark.parametrize("message", every_server_message(), ids=lambda m: m.type)
def test_a_server_message_parses_back_into_its_own_model(message: LiveMessage) -> None:
    parsed = SERVER_MESSAGES.validate_json(message.model_dump_json())

    assert parsed == message


def test_the_status_message_carries_the_fields_of_the_spec() -> None:
    wire = json.loads(every_server_message()[0].model_dump_json())

    assert wire["data"] == {
        "status": "running",
        "phase": "live",
        "elapsed_s": 12.5,
        "remaining_s": 167.5,
    }


def test_the_phase_message_announces_the_final_phase() -> None:
    assert json.loads(PhaseMessage(ts=NOW, data=PhaseData()).model_dump_json())["data"] == {
        "phase": "final"
    }


def test_a_process_node_lists_what_the_tree_shows() -> None:
    node = LiveProcess(pid=7, ppid=4, name="cmd.exe", executable="C:\\cmd.exe", command_line="cmd")

    assert set(node.model_dump()) == {
        "pid",
        "ppid",
        "name",
        "executable",
        "command_line",
        "start",
        "end",
    }


def test_subscribe_defaults_leave_the_api_lane_out() -> None:
    message = CLIENT_MESSAGES.validate_python({"type": "subscribe", "data": {}})

    assert isinstance(message, SubscribeMessage)
    assert message.data.include_api is False
    assert message.data.lanes is None
    assert message.data.pids is None
    assert message.data.query is None


def test_subscribe_carries_lanes_pids_and_include_api() -> None:
    message = CLIENT_MESSAGES.validate_python(
        {"type": "subscribe", "data": {"lanes": ["file"], "pids": [4, 8], "include_api": True}}
    )

    assert isinstance(message, SubscribeMessage)
    assert (message.data.lanes, message.data.pids, message.data.include_api) == (
        ["file"],
        [4, 8],
        True,
    )


def test_ping_needs_no_data() -> None:
    assert isinstance(CLIENT_MESSAGES.validate_python({"type": "ping"}), PingMessage)


@pytest.mark.parametrize(
    "wire",
    [
        {"type": "nonsense"},
        {"type": "subscribe", "data": {"pids": ["x"]}},
        {"type": "subscribe", "data": {"colour": "red"}},
        {"data": {}},
    ],
)
def test_a_malformed_client_message_is_rejected(wire: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CLIENT_MESSAGES.validate_python(wire)
