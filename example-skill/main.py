"""
Echo Repeat Skill — a minimal example demonstrating the skill code interface.

The daemon's subprocess runner imports this module and calls run(context, task).
"""


async def run(context, task: str = "") -> str:
    """
    Entry point called by the skill runner.

    Args:
        context: SkillContext instance with whitelisted tool access
        task: The user's task string from the agent

    Returns:
        A result message string
    """
    if not task or not task.strip():
        await context.say("👋 你想让我重复什么？")
        return "no_input"

    # The 'say' tool was declared in MANIFEST.yaml — it's allowed
    await context.say(f"🔊 {task.strip()}")

    return "echoed"
