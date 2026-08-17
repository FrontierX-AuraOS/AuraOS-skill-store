"""
Photo Story Teller Skill — capture a photo, identify the hand-held object,
and craft an original story with beginning, dilemma, climax, and ending.
照片故事家技能——拍照并识别手中物品，创作包含开头、困境、高潮、结尾的原创故事。
"""


async def run(agent, task: str = "") -> str:
    """Capture a photo and prompt the model to identify the object and tell a story."""

    await agent._pipeline.speak(
        "📷 正在拍照，请把你想让我识别的物品拿在手里……\n"
        "📷 Taking a photo — please hold the object you'd like me to identify..."
    )

    try:
        capture = agent._tools.get("capture_camera_image")
        if capture is None:
            await agent._pipeline.speak(
                "❌ 无法拍照：摄像头不可用。请直接上传一张照片，我来识别物品并创作故事。\n"
                "❌ Camera not available. Please upload a photo directly and I'll identify the object and create a story."
            )
            return "no_camera"

        result = capture()
        if result is None:
            await agent._pipeline.speak(
                "⚠️ 拍照返回为空，请再试一次或直接上传照片。\n"
                "⚠️ Capture returned empty. Please try again or upload a photo directly."
            )
            return "capture_empty"

        await agent._pipeline.speak(
            "✅ 照片已拍摄！让我看看你手里拿的是什么……\n"
            "✅ Photo captured! Let me see what you're holding...\n\n"
            + (f"额外提示 / Extra hint: {task}" if task else "")
        )

        return "photo_captured"

    except PermissionError:
        await agent._pipeline.speak(
            "❌ 权限不足：capture_camera_image 未授权。\n"
            "❌ Permission denied: capture_camera_image not authorized."
        )
        return "permission_denied"

    except Exception as e:
        await agent._pipeline.speak(f"❌ 出错了 / Error: {e}")
        return f"error: {e}"