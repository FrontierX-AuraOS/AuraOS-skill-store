from __future__ import annotations

import asyncio
import base64
import http.client
import importlib.util
import json
import random
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
import yaml


SKILL_DIR = Path(__file__).resolve().parents[1]
ENTRY = SKILL_DIR / "aura_draw_and_guess.py"
SPEC = importlib.util.spec_from_file_location("aura_draw_and_guess_tested", ENTRY)
assert SPEC is not None and SPEC.loader is not None
game = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = game
SPEC.loader.exec_module(game)


def capabilities(*, robot: bool = False, tts: bool = False, asr: bool = False, dialogue: bool = False) -> dict[str, Any]:
    def item(available: bool, detail: str) -> dict[str, Any]:
        return {"available": available, "status": "ready" if available else "unavailable", "detail": detail}

    return {
        "web": item(True, "web ready"),
        "web_drawing": item(True, "web drawing"),
        "daemon": item(robot or tts or asr or dialogue, "daemon"),
        "camera": item(robot, "camera"),
        "vision": item(robot, "vision"),
        "robot_camera": item(robot, "robot camera"),
        "dialogue_agent": {**item(dialogue, "dialogue agent"), "attemptable": dialogue},
        "tts": item(tts, "tts"),
        "asr": item(asr, "asr"),
        "display": item(False, "screen protocol unavailable"),
    }


class FakeProbe:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value

    def get(self, refresh: bool = False) -> dict[str, Any]:
        del refresh
        return json.loads(json.dumps(self.value))


class RecordingTTS:
    def __init__(self) -> None:
        self.events: list[tuple[str, int, str]] = []

    def publish(self, event: dict[str, Any]) -> str:
        self.events.append((event["session_id"], event["sequence"], event["text"]))
        return "spoken"


class RecordingDisplay(game.RobotDisplaySink):
    def __init__(self) -> None:
        self.states: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def publish(self, canvas_state: dict[str, Any], event: dict[str, Any]) -> str:
        self.states.append((canvas_state, event))
        return "unavailable"


class FakeCamera:
    def __init__(self, error: str | None = None) -> None:
        self.error = error
        self.calls = 0

    def snapshot(self, timeout: float = 5.0) -> bytes:
        assert timeout == 5.0
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        return b"\xff\xd8\xffmock-jpeg"


class FakeVision:
    def __init__(self) -> None:
        self.answer_id = ""
        self.calls: list[tuple[bytes, tuple[Any, ...]]] = []

    def guess(self, image: bytes, candidates: tuple[Any, ...], timeout: float = 20.0) -> dict[str, Any]:
        assert timeout == 20.0
        assert self.answer_id in {item.answer_id for item in candidates}
        self.calls.append((image, candidates))
        return {"answer_id": self.answer_id, "confidence": 0.91, "explanation": "轮廓与候选一致"}


class FakeSpeech:
    def __init__(self, text: str = "", error: str | None = None) -> None:
        self.text = text
        self.error = error

    def listen(self, timeout: float = 15.0) -> str:
        assert timeout == 15.0
        if self.error:
            raise RuntimeError(self.error)
        return self.text


class FakeDialogue:
    def __init__(self, text: str = "我听见了，换个角度再猜猜。", error: str | None = None) -> None:
        self.text = text
        self.error = error
        self.calls: list[tuple[str, int, str]] = []

    def reply_to_wrong_guess(self, guess: str, round_number: int, progress: str, timeout: float = 15.0) -> str:
        assert timeout == 15.0
        self.calls.append((guess, round_number, progress))
        if self.error:
            raise RuntimeError(self.error)
        return self.text


class FakeClock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


def make_service(
    *,
    robot: bool = False,
    tts: RecordingTTS | None = None,
    speech: FakeSpeech | None = None,
    camera: FakeCamera | None = None,
    vision: FakeVision | None = None,
    display: RecordingDisplay | None = None,
    dialogue: FakeDialogue | None = None,
    clock: FakeClock | None = None,
) -> Any:
    return game.GameService(
        probe=FakeProbe(capabilities(robot=robot, tts=tts is not None, asr=speech is not None, dialogue=dialogue is not None)),
        tts=tts,
        speech=speech,
        camera=camera,
        vision=vision,
        dialogue=dialogue,
        display=display,
        timeout_seconds=15,
        rng=random.Random(7),
        clock=clock or game.time.monotonic,
    )


def mutation(state: dict[str, Any], request_id: str, **extra: Any) -> dict[str, Any]:
    return {"request_id": request_id, "expected_sequence": state["sequence"], **extra}


def secret(service: Any, state: dict[str, Any]) -> Any:
    return service._sessions[state["session_id"]].current.secret


def correct_guess(service: Any, state: dict[str, Any], request_id: str) -> dict[str, Any]:
    answer = secret(service, state).aliases[0]
    return service.submit_guess(state["session_id"], mutation(state, request_id, guess=answer))


def test_public_state_hides_answer_until_round_result() -> None:
    service = make_service()
    state = service.create_session()
    private = secret(service, state)
    serialized = json.dumps(state, ensure_ascii=False)

    assert private.label not in serialized
    assert private.answer_id not in serialized
    assert "answer_id" not in serialized
    assert state["current_round"]["revealed_answer"] is None
    assert state["events"][0]["tts_status"] == "unavailable"
    assert state["current_round"]["display_status"] == "unavailable"

    state = correct_guess(service, state, "correct-0001")
    assert state["current_round"]["revealed_answer"] == private.label


def test_web_only_completes_six_rounds_without_fake_agent_score() -> None:
    tts = RecordingTTS()
    display = RecordingDisplay()
    service = make_service(tts=tts, display=display)
    state = service.create_session("web_only")

    # Round one can be guessed before the first stroke.
    state = correct_guess(service, state, "round1-correct")
    assert state["score"] == {"user_score": 1, "agent_score": None, "agent_participated": False}
    assert state["current_round"]["canvas"]["currentStrokeIndex"] == len(state["current_round"]["canvas"]["strokeSequence"])

    state = service.next_round(state["session_id"], mutation(state, "round2-next"))
    total = len(state["current_round"]["canvas"]["strokeSequence"])
    for index in range(total):
        state = service.advance_drawing(state["session_id"], mutation(state, f"round2-draw-{index}"))
    assert state["current_round"]["status"] == "guessing"
    state = correct_guess(service, state, "round2-correct")

    for round_number in range(3, game.TOTAL_ROUNDS + 1):
        state = service.next_round(
            state["session_id"], mutation(state, f"round{round_number}-next")
        )
        state = service.end_round(
            state["session_id"], mutation(state, f"round{round_number}-end")
        )

    assert state["state"] == "finished"
    assert state["score"]["user_score"] == 2
    assert state["score"]["agent_score"] is None
    assert state["champion"] == "not_applicable"
    assert [item["result"] for item in state["rounds"]] == [
        "correct",
        "correct",
        "ended",
        "ended",
        "ended",
        "ended",
    ]
    assert state["events"][-1]["type"] == "game_summary"
    assert "Agent 没有参与猜测" in state["events"][-1]["text"]

    for round_number in range(1, game.TOTAL_ROUNDS + 1):
        phases = {
            event["phase"]
            for event in state["events"]
            if event.get("dialogue") and event["round"] == round_number
        }
        assert {"round_started", "drawing_midpoint", "drawing_complete", "round_result"} <= phases

    sequences = [event["sequence"] for event in state["events"]]
    assert sequences == sorted(set(sequences))
    assert all({"session_id", "round", "sequence", "phase"} <= event.keys() for event in state["events"])
    assert [text for _, _, text in tts.events] == [event["text"] for event in state["events"] if event.get("dialogue")]
    assert len({(session_id, sequence) for session_id, sequence, _ in tts.events}) == len(tts.events)
    assert display.states
    assert all(marker["sequence"] <= state["sequence"] for _, marker in display.states)


def test_web_duel_gives_each_side_three_guessing_rounds() -> None:
    service = make_service(robot=True, vision=FakeVision())
    state = service.create_session("web_duel")

    assert len(state["rounds"]) == game.TOTAL_ROUNDS == 6
    assert [item["guesser"] for item in state["rounds"]] == [
        "user",
        "agent",
        "user",
        "agent",
        "user",
        "agent",
    ]
    assert [item["drawing_source"] for item in state["rounds"]] == [
        "agent_svg",
        "web_canvas",
        "agent_svg",
        "web_canvas",
        "agent_svg",
        "web_canvas",
    ]


def test_web_duel_persists_mouse_drawing_and_scores_real_vision_result() -> None:
    vision = FakeVision()
    service = make_service(robot=True, vision=vision)
    state = service.create_session("web_duel")
    state = service.end_round(state["session_id"], mutation(state, "end-first-round"))
    state = service.next_round(state["session_id"], mutation(state, "open-draw-round"))

    assert state["current_round"]["drawing_source"] == "web_canvas"
    assert state["current_round"]["drawing_prompt"] == secret(service, state).label
    strokes = [{"points": [[12, 18], [120, 90], [260, 160]]}]
    state = service.save_user_drawing(
        state["session_id"], mutation(state, "save-web-stroke", strokes=strokes)
    )
    assert state["current_round"]["canvas"]["userStrokes"][0]["points"] == strokes[0]["points"]

    vision.answer_id = secret(service, state).answer_id
    png = base64.b64encode(b"\x89PNG\r\n\x1a\nmock").decode("ascii")
    state = service.canvas_guess(
        state["session_id"], mutation(state, "canvas-guess-01", image=f"data:image/png;base64,{png}")
    )

    assert vision.calls[0][0].startswith(b"\x89PNG")
    assert state["score"] == {"user_score": 0, "agent_score": 1, "agent_participated": True}
    assert state["current_round"]["result"] == "correct"
    assert state["current_round"]["guess_history"][-1]["source"] == "web_canvas"


def test_web_duel_does_not_fake_agent_guess_without_image_capability() -> None:
    service = make_service()
    state = service.create_session("web_duel")
    state = service.end_round(state["session_id"], mutation(state, "end-first-no-vision"))
    state = service.next_round(state["session_id"], mutation(state, "open-no-vision-round"))
    state = service.save_user_drawing(
        state["session_id"],
        mutation(state, "save-no-vision", strokes=[{"points": [[1, 1], [2, 2]]}]),
    )
    png = base64.b64encode(b"\x89PNG\r\n\x1a\nmock").decode("ascii")

    with pytest.raises(game.GameError) as raised:
        service.canvas_guess(
            state["session_id"], mutation(state, "guess-no-vision", image=f"data:image/png;base64,{png}")
        )

    assert raised.value.code == "capability_unavailable"
    current = service.get_session(state["session_id"])
    assert current["score"]["agent_score"] is None
    assert current["current_round"]["status"] == "user_drawing"


def test_wrong_guess_reply_uses_auraos_dialogue_or_contextual_fallback() -> None:
    dialogue = FakeDialogue("这条思路有意思，不过轮廓还对不上。让我再补一笔。")
    tts = RecordingTTS()
    service = make_service(dialogue=dialogue, tts=tts)
    state = service.create_session()
    state = service.submit_guess(state["session_id"], mutation(state, "wrong-guess-model", guess="香蕉"))
    state = service.agent_reply(
        state["session_id"], mutation(state, "reply-wrong-model", guess="香蕉")
    )

    event = [item for item in state["events"] if item["type"] == "agent_reply"][-1]
    assert dialogue.calls == [("香蕉", 1, f"0/{len(secret(service, state).strokes)} 笔")]
    assert event["dialogue_source"] == "auraos_model"
    assert event["text"] == dialogue.text
    assert event["tts_status"] == "spoken"
    assert tts.events.count((event["session_id"], event["sequence"], event["text"])) == 1

    fallback_service = make_service()
    fallback = fallback_service.create_session()
    fallback = fallback_service.submit_guess(
        fallback["session_id"], mutation(fallback, "wrong-guess-local", guess="西瓜")
    )
    fallback = fallback_service.agent_reply(
        fallback["session_id"], mutation(fallback, "reply-wrong-local", guess="西瓜")
    )
    fallback_event = [item for item in fallback["events"] if item["type"] == "agent_reply"][-1]
    assert fallback_event["dialogue_source"] == "fallback"
    assert "西瓜" in fallback_event["text"]


def test_idempotency_and_sequence_conflict_do_not_duplicate_score() -> None:
    service = make_service()
    state = service.create_session()
    body = mutation(state, "same-request-1", guess=secret(service, state).aliases[0])

    first = service.submit_guess(state["session_id"], body)
    second = service.submit_guess(state["session_id"], body)

    assert first == second
    assert second["score"]["user_score"] == 1
    assert len([event for event in second["events"] if event["type"] == "round_result"]) == 1

    with pytest.raises(game.GameError) as raised:
        service.next_round(
            state["session_id"],
            {"request_id": "stale-next-01", "expected_sequence": 0},
        )
    assert raised.value.code == "sequence_conflict"
    assert raised.value.status == 409


def test_empty_guess_and_timeout_have_authoritative_results() -> None:
    clock = FakeClock()
    service = make_service(clock=clock)
    state = service.create_session()

    with pytest.raises(game.GameError) as raised:
        service.submit_guess(state["session_id"], mutation(state, "empty-guess-1", guess="  "))
    assert raised.value.code == "empty_guess"
    assert service.get_session(state["session_id"])["score"]["user_score"] == 0

    clock.value += 16
    expired = service.get_session(state["session_id"])
    assert expired["current_round"]["result"] == "timeout"
    assert expired["current_round"]["revealed_answer"]
    assert expired["score"]["user_score"] == 0


def test_robot_camera_round_scores_agent_and_can_produce_tie() -> None:
    camera = FakeCamera()
    vision = FakeVision()
    service = make_service(robot=True, camera=camera, vision=vision)
    state = service.create_session("robot_camera")

    state = correct_guess(service, state, "user-point-1")
    state = service.next_round(state["session_id"], mutation(state, "to-camera-01"))
    assert state["current_round"]["drawer"] == "user"
    assert state["current_round"]["guesser"] == "agent"

    vision.answer_id = secret(service, state).answer_id
    state = service.camera_guess(state["session_id"], mutation(state, "camera-guess-1"))
    assert camera.calls == 1
    assert state["score"] == {"user_score": 1, "agent_score": 1, "agent_participated": True}
    assert state["current_round"]["result"] == "correct"
    assert state["vision_result"]["confidence"] == 0.91
    camera_states = [
        event["status"] for event in state["events"] if event["type"] == "camera_status"
    ]
    assert camera_states == ["capturing", "recognizing", "judging"]

    for round_number in range(3, game.TOTAL_ROUNDS + 1):
        state = service.next_round(
            state["session_id"], mutation(state, f"to-round-{round_number}")
        )
        state = service.end_round(
            state["session_id"], mutation(state, f"end-round-{round_number}")
        )
    assert state["champion"] == "tie"


def test_camera_failure_generates_visible_error_and_falls_back_to_web() -> None:
    camera = FakeCamera(error="camera 503")
    vision = FakeVision()
    service = make_service(robot=True, camera=camera, vision=vision)
    state = service.create_session("robot_camera")
    state = service.end_round(state["session_id"], mutation(state, "finish-round1"))
    state = service.next_round(state["session_id"], mutation(state, "next-camera-1"))
    state = service.camera_guess(state["session_id"], mutation(state, "camera-fails-1"))

    assert state["current_round"]["drawer"] == "agent"
    assert state["current_round"]["guesser"] == "user"
    assert state["current_round"]["status"] == "drawing"
    errors = [event for event in state["events"] if event["type"] == "capability_error"]
    assert errors and "camera 503" in errors[-1]["text"]
    assert state["score"]["agent_score"] is None

    state = correct_guess(service, state, "fallback-correct")
    assert state["score"]["user_score"] == 1


def test_asr_transcript_is_echoed_before_using_same_scoring_path() -> None:
    speech = FakeSpeech()
    service = make_service(speech=speech)
    state = service.create_session()
    speech.text = secret(service, state).aliases[0]

    state = service.voice_guess(state["session_id"], mutation(state, "voice-guess-01"))

    assert state["transcript"] == speech.text
    assert state["score"]["user_score"] == 1
    transcript_event = next(event for event in state["events"] if event["type"] == "voice_transcript")
    guess_event = next(event for event in state["events"] if event["type"] == "guess_result")
    assert transcript_event["sequence"] < guess_event["sequence"]
    assert state["current_round"]["guess_history"][-1]["source"] == "asr"


def test_asr_failure_keeps_text_path_available() -> None:
    service = make_service(speech=FakeSpeech(error="ASR timeout"))
    state = service.create_session()
    state = service.voice_guess(state["session_id"], mutation(state, "voice-error-01"))

    assert state["current_round"]["status"] == "drawing"
    assert state["score"]["user_score"] == 0
    assert "ASR timeout" in state["voice_error"]
    assert any(event["type"] == "capability_error" for event in state["events"])


def test_vision_parser_accepts_only_structured_candidate_result() -> None:
    candidates = game.ANSWER_DECK[:3]
    parsed = game.AuraDaemonVision.parse(
        json.dumps({"answer_id": candidates[1].answer_id, "confidence": 0.72, "explanation": "shape"}),
        candidates,
    )
    assert parsed == {"answer_id": candidates[1].answer_id, "confidence": 0.72, "explanation": "shape"}

    with pytest.raises(RuntimeError, match="JSON"):
        game.AuraDaemonVision.parse("```json\n{}\n```", candidates)
    with pytest.raises(RuntimeError, match="候选范围外"):
        game.AuraDaemonVision.parse('{"answer_id":"outside","confidence":0.5}', candidates)
    with pytest.raises(RuntimeError, match="0 到 1"):
        game.AuraDaemonVision.parse(
            json.dumps({"answer_id": candidates[0].answer_id, "confidence": 2}), candidates
        )


def test_robot_mode_is_rejected_when_image_contract_is_unavailable() -> None:
    service = make_service(robot=False)
    with pytest.raises(game.GameError) as raised:
        service.create_session("robot_camera")
    assert raised.value.status == 409
    assert raised.value.code == "capability_unavailable"
    assert service.create_session("web_only")["mode"] == "web_only"


@pytest.mark.parametrize(
    ("user_score", "agent_score", "expected"),
    [(2, 1, "user"), (1, 2, "agent"), (1, 1, "tie")],
)
def test_comparable_scores_cover_all_champion_results(
    user_score: int, agent_score: int, expected: str
) -> None:
    service = make_service(robot=True, camera=FakeCamera(), vision=FakeVision())
    public = service.create_session("robot_camera")
    session = service._sessions[public["session_id"]]
    session.agent_participated = True
    session.user_score = user_score
    session.agent_score = agent_score
    assert service._champion(session) == expected


def test_http_server_serves_app_security_headers_and_session_api() -> None:
    service = make_service()
    server = game.create_http_server(service, SKILL_DIR, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        html = response.read().decode("utf-8")
        assert response.status == 200
        assert "AURA 你画我猜" in html
        assert response.getheader("Content-Security-Policy")
        assert response.getheader("Cache-Control") == "no-store"

        body = json.dumps({"mode": "web_only"}).encode("utf-8")
        connection.request("POST", "/api/sessions", body=body, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        state = json.loads(response.read())
        assert response.status == 201
        assert state["round"] == 1
        assert "answer_id" not in json.dumps(state)

        connection.request("GET", f"/api/sessions/{state['session_id']}")
        response = connection.getresponse()
        refreshed = json.loads(response.read())
        assert refreshed["session_id"] == state["session_id"]
        assert refreshed["sequence"] == state["sequence"]
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_configured_port_conflict_fails_instead_of_switching_ports() -> None:
    first = game.create_http_server(make_service(), SKILL_DIR, port=0)
    port = first.server_address[1]
    try:
        with pytest.raises(OSError):
            game.create_http_server(make_service(), SKILL_DIR, port=port)
    finally:
        first.server_close()


class FakeAgent:
    def __init__(self) -> None:
        self.state = "not_deployed"
        self.calls: list[str] = []

    def get_app_status(self, name: str) -> dict[str, Any]:
        return {"name": name, "state": self.state, "error": None}

    async def deploy_app(self, path: Path) -> dict[str, str]:
        assert path == ENTRY
        self.calls.append("deploy")
        self.state = "stopped"
        return {"status": "deployed", "app": game.APP_NAME}

    async def start_app(self, name: str) -> dict[str, str]:
        self.calls.append("start")
        self.state = "running"
        return {"status": "started", "app": name}

    async def wait_app_ready(self, name: str, url: str, timeout: float) -> dict[str, str]:
        assert name == game.APP_NAME
        assert url == "http://127.0.0.1:3001/health"
        assert timeout == 20.0
        self.calls.append("ready")
        return {"status": "ready", "app": name, "url": url}

    async def stop_app(self, name: str) -> dict[str, str]:
        self.calls.append("stop")
        self.state = "stopped"
        return {"status": "stopped", "app": name}

    def get_app_logs(self, name: str) -> dict[str, Any]:
        return {"lines": [name], "next_offset": 1}


def test_skill_entry_accepts_fixed_lifecycle_actions_only() -> None:
    agent = FakeAgent()
    started = json.loads(asyncio.run(game.run(agent, "请启动你画我猜; rm -rf ignored")))
    assert started["status"] == "started"
    assert started["url"] == "http://127.0.0.1:3001"
    assert agent.calls == ["deploy", "start", "ready"]

    status = json.loads(asyncio.run(game.run(agent, "查看状态")))
    assert status["state"] == "running"
    logs = json.loads(asyncio.run(game.run(agent, "日志")))
    assert logs["lines"] == [game.APP_NAME]
    stopped = json.loads(asyncio.run(game.run(agent, "停止")))
    assert stopped["status"] == "stopped"


def test_store_http_install_route_writes_complete_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from aura.daemon.app.dependencies import get_daemon
    import aura.daemon.app.routers.skills_store as store_router

    installed_root = tmp_path / "skills"
    monkeypatch.setattr(store_router, "SKILLS_DIR", installed_root)
    manifest = yaml.safe_load((SKILL_DIR / "MANIFEST.yaml").read_text(encoding="utf-8"))
    declared = [manifest["entry"]["main"], *manifest["entry"]["files"]]
    files = {
        filename: (SKILL_DIR / filename).read_text(encoding="utf-8")
        for filename in ["MANIFEST.yaml", "skill.md", *declared]
    }

    class DaemonWithoutLocalBackend:
        backend = None

    app = FastAPI()
    app.include_router(store_router.router, prefix="/api")
    app.dependency_overrides[get_daemon] = lambda: DaemonWithoutLocalBackend()
    with TestClient(app) as client:
        response = client.post(
            "/api/skills_store/install",
            json={"id": "aura-draw-and-guess", "version": manifest["version"], "files": files},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        installed = client.get("/api/skills_store/installed")
        assert installed.status_code == 200
        assert installed.json() == [{"id": "aura-draw-and-guess", "version": manifest["version"]}]

    installed_dir = installed_root / "aura-draw-and-guess"
    assert all((installed_dir / filename).is_file() for filename in files)
    assert (installed_dir / ".version").read_text(encoding="utf-8") == manifest["version"]


def test_store_installed_skill_starts_and_reclaims_supervised_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from aura.agent.local_agent import LocalAgent
    import aura.agent.local_agent as local_agent_module
    from aura.agent.skills import load_skills
    from aura.apps.manager import AppManager
    import aura.daemon.app.routers.skills_store as store_router

    manifest = yaml.safe_load((SKILL_DIR / "MANIFEST.yaml").read_text(encoding="utf-8"))
    declared = [manifest["entry"]["main"], *manifest["entry"]["files"]]
    assert declared == [
        "aura_draw_and_guess.py",
        "game.html",
        "game.css",
        "game.js",
        "runtime.json",
    ]
    support_files = manifest["entry"]["files"]
    assert all((SKILL_DIR / filename).stat().st_size <= 64 * 1024 for filename in support_files)

    installed_root = tmp_path / "skills"
    installed_dir = installed_root / "aura-draw-and-guess"
    files = {
        filename: (SKILL_DIR / filename).read_text(encoding="utf-8")
        for filename in ["MANIFEST.yaml", "skill.md", *declared]
    }
    monkeypatch.setattr(store_router, "SKILLS_DIR", installed_root)
    request = store_router.InstallRequest(
        id="aura-draw-and-guess",
        version=str(manifest["version"]),
        files=files,
    )

    class DaemonWithoutLocalBackend:
        backend = None

    installed = asyncio.run(
        store_router.install_skill(request, daemon=DaemonWithoutLocalBackend())
    )
    assert installed == {
        "status": "ok",
        "id": "aura-draw-and-guess",
        "version": "0.1.0",
    }
    assert (installed_dir / ".version").read_text(encoding="utf-8") == "0.1.0"
    loaded = load_skills(installed_root)["aura_draw_and_guess"]
    assert loaded.code_path == (installed_dir / "aura_draw_and_guess.py").resolve()

    installed_spec = importlib.util.spec_from_file_location(
        "aura_draw_and_guess_installed", loaded.code_path
    )
    assert installed_spec is not None and installed_spec.loader is not None
    installed_game = importlib.util.module_from_spec(installed_spec)
    sys.modules[installed_spec.name] = installed_game
    installed_spec.loader.exec_module(installed_game)

    monkeypatch.setattr(local_agent_module, "SKILLS_DIR", installed_root)
    agent = LocalAgent.__new__(LocalAgent)
    agent._app_manager = AppManager(backend=None)  # type: ignore[arg-type]

    async def scenario() -> None:
        try:
            result = json.loads(await installed_game.run(agent, "启动"))
            assert result["url"] == "http://127.0.0.1:3001"
            assert agent.get_app_status(installed_game.APP_NAME)["state"] == "running"
            connection = http.client.HTTPConnection("127.0.0.1", 3001, timeout=3)
            connection.request("GET", "/health")
            response = connection.getresponse()
            assert response.status == 200
            assert json.loads(response.read())["app"] == game.APP_NAME
            connection.close()
        finally:
            status = agent.get_app_status(installed_game.APP_NAME)
            if status["state"] != "not_deployed":
                await agent.stop_app(installed_game.APP_NAME)

    asyncio.run(scenario())
    assert agent.get_app_status(installed_game.APP_NAME)["state"] == "stopped"
    connection = http.client.HTTPConnection("127.0.0.1", 3001, timeout=0.5)
    with pytest.raises(OSError):
        connection.request("GET", "/health")
    connection.close()


def test_store_app_start_rejects_an_existing_server_on_configured_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aura.agent.local_agent import LocalAgent
    import aura.agent.local_agent as local_agent_module
    from aura.apps.manager import AppManager

    holder = game.create_http_server(make_service(), SKILL_DIR, port=3001)
    holder_thread = threading.Thread(target=holder.serve_forever, daemon=True)
    holder_thread.start()
    monkeypatch.setattr(local_agent_module, "SKILLS_DIR", SKILL_DIR.parent)
    agent = LocalAgent.__new__(LocalAgent)
    agent._app_manager = AppManager(backend=None)  # type: ignore[arg-type]

    async def scenario() -> None:
        try:
            with pytest.raises(RuntimeError, match="无法监听 127.0.0.1:3001"):
                await game.run(agent, "启动")
            status = agent.get_app_status(game.APP_NAME)
            assert status["state"] == "error"
            assert "端口可能已被占用" in str(status["error"])
        finally:
            status = agent.get_app_status(game.APP_NAME)
            if status["state"] != "not_deployed":
                await agent.stop_app(game.APP_NAME)

    try:
        asyncio.run(scenario())
    finally:
        holder.shutdown()
        holder.server_close()
        holder_thread.join(timeout=3)
