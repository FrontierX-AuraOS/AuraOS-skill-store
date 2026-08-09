"""
meme_generator skill.
Generates funny Chinese meme captions from user input.
"""


async def run(context, task: str = "") -> str:
    """Entry point for the skill runner."""
    if not task or not task.strip():
        await context.say("给我一个场景或者情绪，我来配表情包文案～ 🐸")
        return "no_input"

    await context.say(f"收到！让我想想「{task}」怎么整活…")
    return "done"
