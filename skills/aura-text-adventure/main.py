"""AuraOS entry point for the deterministic AURA Text Adventure skill."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import AdventureEngine, AdventureError, format_event


async def run(agent, task: str = "") -> str:
    """Load one SQLite snapshot, process one command, and return its event text.

    AuraOS imports this module in a fresh module context for every
    ``run_skill_code`` call.  No game state is kept in module globals.
    """
    try:
        engine = AdventureEngine()
        event = engine.handle(task)
        return format_event(event)
    except AdventureError as exc:
        return f"错误：{exc}"
