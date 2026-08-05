"""
Echo Repeat Skill — echo user messages with emotional tone.
"""


async def run(context, task: str = "") -> str:
    msg = (task or "").strip()

    if not msg:
        await context.say("👋 What should I repeat? / 你想让我重复什么？")
        return "no_input"

    await context.say(f"🔊 {msg}")
    return "echoed"
