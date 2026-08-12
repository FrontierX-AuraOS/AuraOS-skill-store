"""
Upload Probe Skill — test the upload pipeline with real speaker output.

Triggered via run_skill_code. The model calls this when it needs the robot
to speak "上传链路测试成功" through its physical speaker, not just text.
"""


async def run(agent, task: str = "") -> str:
    """
    Speak "上传链路测试成功" through the robot's speaker to verify
    the upload pipeline is working end-to-end.

    Args:
        agent: The running LocalAgent instance.
        task: Natural-language parameter from the model (unused here).

    Returns:
        Status string indicating the probe completed.
    """
    msg_zh = "上传链路测试成功"
    msg_en = "Upload probe test successful"

    # Speak through the robot's speaker
    await agent._pipeline.speak(msg_zh)

    return "upload_probe_success"