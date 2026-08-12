"""
Manual Probe Skill — triggered by "手测技能", replies "手测成功".
Used to verify skill system loading and triggering.
"""

TRIGGERS = {"手测技能", "manual probe", "手测"}


async def run(context, task: str = "") -> str:
    """Run the manual probe skill.

    Args:
        context: The running agent context (has .say() for speaking).
        task: Natural language input from the model at invocation time.

    Returns:
        Status string: "success", "no_trigger", or "waiting".
    """
    msg = (task or "").strip()

    if not msg:
        await context.say(
            "请在对话中输入「手测技能」来触发此技能。\n"
            "Please say \"manual probe\" to trigger this skill."
        )
        return "waiting"

    # Check if any trigger word appears in the message
    for trigger in TRIGGERS:
        if trigger in msg:
            await context.say("手测成功")
            return "success"

    await context.say(
        f"未识别到触发词。请说「手测技能」来触发。\n"
        f"No trigger word detected. Please say \"manual probe\" to trigger.\n"
        f"你发送的内容 / Your input: {msg}"
    )
    return "no_trigger"