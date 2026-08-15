"""AuraOS Skill entry for the immutable AURA Dual Core Twin release."""

from __future__ import annotations

import json
import re
from pathlib import Path

from aura.apps.node_web import node_web_app_from_env

APP_ID = "aura-dual-core-twin"
APP_VERSION = "0.1.1"
APP_NAME = "aura_dual_core_twin"
APP_PORT = 3000


def _release() -> tuple[str, str]:
    entry_dir = Path(__file__).resolve().parent
    metadata = json.loads((entry_dir / "release.json").read_text(encoding="utf-8"))
    version = str(metadata.get("version", ""))
    url = str(metadata.get("url", ""))
    digest = str(metadata.get("sha256", ""))
    if version != APP_VERSION or not url or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RuntimeError("Skill release metadata is invalid")
    return url, digest


def create_app():
    return node_web_app_from_env(
        name=APP_NAME,
        description="AURA Dual Core Twin tactical board game",
        environment="AURA_DUAL_CORE_TWIN_DIR",
        port=APP_PORT,
    )


async def run(agent, task: str = "") -> str:
    action = _action(task)
    if action == "stop":
        await agent.stop_app(APP_NAME)
        return json.dumps({"status": "stopped", "app": APP_NAME}, ensure_ascii=False)
    if action == "status":
        return json.dumps(agent.get_app_status(APP_NAME), ensure_ascii=False)
    if action == "logs":
        return json.dumps(agent.get_app_logs(APP_NAME), ensure_ascii=False)

    release_url, release_sha256 = _release()
    project_dir = await agent.install_app_bundle(
        app_id=APP_ID,
        version=APP_VERSION,
        url=release_url,
        sha256=release_sha256,
    )
    agent.set_app_environment("AURA_DUAL_CORE_TWIN_DIR", project_dir)
    await agent.deploy_app(Path(__file__))
    await agent.start_app(APP_NAME)
    await agent.wait_app_ready(APP_NAME, f"http://127.0.0.1:{APP_PORT}")
    return json.dumps(
        {
            "status": "started",
            "app": APP_NAME,
            "version": APP_VERSION,
            "url": f"http://127.0.0.1:{APP_PORT}",
        },
        ensure_ascii=False,
    )


def _action(task: str) -> str:
    text = task.strip().lower()
    if re.search(r"停止|关闭|stop|shutdown", text):
        return "stop"
    if re.search(r"日志|logs?", text):
        return "logs"
    if re.search(r"状态|status", text):
        return "status"
    return "start"
