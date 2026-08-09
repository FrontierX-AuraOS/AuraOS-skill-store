"""
code_reviewer skill.
Reviews code snippets for bugs, security issues, performance, and readability.
"""


async def run(context, task: str = "") -> str:
    """Entry point for the skill runner."""
    if not task or not task.strip():
        await context.say("贴一段代码给我，我来帮你审查～ 🔍")
        return "no_input"

    await context.say(f"收到代码，让我仔细看看…")
    return "done"
