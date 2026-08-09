"""
daily_journal skill.
Chats with user about their day and composes a structured journal entry.
"""


async def run(context, task: str = "") -> str:
    """Entry point for the skill runner."""
    if not task or not task.strip():
        await context.say("今天过得怎么样？随便聊聊～ 📔")
        return "no_input"

    await context.say(f"好，来聊聊「{task}」——今天发生了什么？")
    return "done"
