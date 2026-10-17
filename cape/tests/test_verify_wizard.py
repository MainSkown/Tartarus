import importlib.util
import pathlib

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "verify-wizard.py"


def load():
    spec = importlib.util.spec_from_file_location("verify_wizard", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeApi:
    """A scripted Tartarus API: `answers` maps (method, path-prefix) to (status, body) answers."""

    def __init__(self, answers):
        self.answers = {key: list(values) for key, values in answers.items()}
        self.calls = []

    def request(self, method, path, **_):
        self.calls.append((method, path))
        for (m, prefix), queue in self.answers.items():
            if m == method and path.startswith(prefix) and queue:
                return queue.pop(0) if len(queue) > 1 else queue[0]
        raise AssertionError(f"unscripted call {method} {path}")


READY = {"name": "lab1", "state": "ready", "badges": ["DEFENDER ON"], "ip": "192.168.150.11"}


def happy_answers(verdict_state="ready", analysis_status="done"):
    return {
        ("GET", "/system/health"): [(200, {"guest": {"status": "ok"}})],
        ("GET", "/guests/profiles"): [(200, [{"id": "windows"}])],
        ("GET", "/guests/media"): [(200, [{"file": "x.iso"}])],
        ("GET", "/guests"): [
            (200, [READY]),
            (200, [READY, {"name": "vw-test", "state": verdict_state, "badges": ["DEFENDER OFF"]}]),
        ],
        ("POST", "/guests/lab1/clone"): [
            (202, {"job_id": 7, "build_id": "b1", "guest": "vw-test"}),
            (409, {"error": {"message": "only one build or clone can be active at a time"}}),
        ],
        ("POST", "/analyses"): [
            (409, {"error": {"message": "A guest is being built"}}),
            (201, {"id": 9}),
        ],
        ("GET", "/jobs/7"): [
            (200, {"status": "running", "step": "copy", "progress": 5}),
            (
                200,
                {
                    "status": "done" if verdict_state == "ready" else "failed",
                    "step": "x",
                    "progress": 100,
                    "result": {"selftest": {"message": "all checks passed"}},
                },
            ),
        ],
        ("GET", "/analyses/9"): [
            (200, {"status": analysis_status, "guest": "vw-test", "guest_badges": ["DEFENDER OFF"]})
        ],
        ("DELETE", "/guests/vw-test"): [(204, None)],
    }


def run(api, **kwargs):
    module = load()
    return module.verify(
        api, source=None, name="vw-test", sample=b"MZ", sleep=lambda _s: None, **kwargs
    )


def failed(results):
    return [r for r in results if not r.ok]


def test_a_healthy_system_passes_every_check_and_cleans_up():
    api = FakeApi(happy_answers())
    results = run(api)
    assert failed(results) == [], [(r.name, r.message) for r in failed(results)]
    assert ("DELETE", "/guests/vw-test") in api.calls


def test_a_build_that_blocks_nothing_fails_the_gate_check():
    answers = happy_answers()
    answers[("POST", "/analyses")] = [(201, {"id": 8}), (201, {"id": 9})]
    results = run(FakeApi(answers))
    assert "analysis refused while a guest is being built" in [r.name for r in failed(results)]


def test_a_failing_self_test_fails_the_check_and_still_deletes_the_guest():
    api = FakeApi(happy_answers(verdict_state="failed"))
    results = run(api)
    assert any(r.name == "clone reaches ready" for r in failed(results))
    assert ("DELETE", "/guests/vw-test") in api.calls


def test_an_analysis_that_fails_on_the_new_guest_is_reported():
    results = run(FakeApi(happy_answers(analysis_status="failed")))
    assert any(r.name == "analysis runs on the new guest" for r in failed(results))


def test_no_ready_guest_to_clone_is_one_clear_failure_not_a_crash():
    answers = happy_answers()
    answers[("GET", "/guests")] = [(200, [{"name": "lab9", "state": "failed", "badges": []}])]
    results = run(FakeApi(answers))
    assert [r.name for r in failed(results)] == ["a ready guest to clone"]


def test_the_report_line_format_matches_the_other_verify_scripts():
    module = load()
    assert module.format_result(module.Result("x", True, "fine")).startswith("[ OK ] ")
    assert module.format_result(module.Result("x", False, "bad")).startswith("[FAIL] ")


def test_a_guest_that_carries_giveaways_is_not_chosen_as_the_source():
    answers = happy_answers()
    adopted = {"name": "win", "state": "ready", "badges": [], "giveaways": ["account Analyst"]}
    answers[("GET", "/guests")][0] = (200, [adopted, READY])
    api = FakeApi(answers)
    results = run(api)
    assert failed(results) == [], [(r.name, r.message) for r in failed(results)]
    assert ("POST", "/guests/lab1/clone") in api.calls
    assert ("POST", "/guests/win/clone") not in api.calls


def test_a_named_source_is_used_even_when_it_carries_giveaways():
    answers = happy_answers()
    adopted = {"name": "win", "state": "ready", "badges": [], "giveaways": ["account Analyst"]}
    answers[("GET", "/guests")][0] = (200, [adopted, READY])
    answers[("POST", "/guests/win/clone")] = [
        (202, {"job_id": 7, "build_id": "b1", "guest": "vw-test"})
    ]
    api = FakeApi(answers)
    module = load()
    module.verify(api, source="win", name="vw-test", sample=b"MZ", sleep=lambda _s: None)
    assert ("POST", "/guests/win/clone") in api.calls
