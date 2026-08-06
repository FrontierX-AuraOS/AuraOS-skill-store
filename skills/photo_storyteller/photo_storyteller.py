"""
Photo Storyteller Skill — capture a photo and create an imaginative story
with beginning, dilemma, and ending.
"""


async def run(agent, task: str = "") -> str:
    """Capture a photo and prompt the model to create a three-part story.

    Args:
        agent: The running LocalAgent instance.
        task: Optional extra instructions from the caller.

    Returns:
        Status string indicating the result.
    """
    # 1. Announce intent
    if agent._pipeline is not None:
        await agent._pipeline.speak(
            "📷 让我拍一张照片，然后给你编一个有趣的故事～"
        )

    # 2. Capture a photo
    capture_fn = agent._tools.get("capture_camera_image")
    if capture_fn is None:
        if agent._pipeline is not None:
            await agent._pipeline.speak(
                "❌ 相机不可用，请检查硬件连接。\n"
                "❌ Camera not available. Please check hardware connection."
            )
        return "camera_not_available"

    try:
        image_bytes = capture_fn()
        if image_bytes is None or (isinstance(image_bytes, bytes) and len(image_bytes) == 0):
            if agent._pipeline is not None:
                await agent._pipeline.speak(
                    "❌ 拍照失败：相机返回了空画面，请检查摄像头。\n"
                    "❌ Capture failed: camera returned an empty frame."
                )
            return "capture_failed"
    except Exception as e:
        if agent._pipeline is not None:
            await agent._pipeline.speak(f"❌ 拍照出错：{e}")
        return f"capture_error: {e}"

    # 3. Give the storytelling prompt
    story_prompt = (
        "请根据刚才拍摄的照片内容，发挥想象力编一个生动有趣的中文故事。\n"
        "故事必须包含三个部分：\n"
        "  🎬 开头 — 引入场景和角色\n"
        "  ⚡ 困境 — 角色遇到什么难题或挑战\n"
        "  🎉 结局 — 如何解决或收尾\n"
        "故事要完整、有画面感、最好带一点惊喜或趣味。\n"
        + (f"\n附加要求：{task}" if task else "")
    )

    if agent._pipeline is not None:
        await agent._pipeline.speak(story_prompt)

    return "photo_captured"