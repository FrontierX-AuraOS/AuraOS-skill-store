# AURA 你画我猜

一个由 AuraOS Skill 启动并由 AppManager 监管的六回合网页游戏。基础模式不依赖云端模型或真实机器人；AuraOS Agent、视觉、语音和摄像头按实测能力启用。

## 游戏规则

- 视觉模型可用时，首页默认选择 `web_duel`，保证双方各猜 3 次；视觉不可用时默认保留可完整运行的 `web_only`。
- `web_only`：六回合均由 Agent 按固定笔画序列作画。每一笔只在用户点击“继续画一笔”后推进，用户可随时猜词。
- `web_duel`：六回合严格交替，第 1/3/5 回合由 Agent 作画、用户猜，第 2/4/6 回合由用户在网页画布作画、Agent 猜。画面以 PNG 进入 `VisionInput`；真实视觉不可用时允许继续画或降级为 Agent 作画、用户猜，不伪造 Agent 得分。
- `robot_camera`：同样在第 2/4/6 回合由用户作画、Agent 通过 AuraOS 摄像头和视觉能力各猜一次。
- 只有猜测者猜中才得一分。纯网页模式中 Agent 不参与猜测，因此不显示虚构的 Agent 分数，也不判定对战冠军。
- 服务端保存答案、推进笔画、判定猜测和计分；浏览器只提交带请求 ID 和预期序号的动作。
- 猜错后调用 AuraOS `GenerateCmd` 生成与本次猜测相关的回应；模型不可用或超时时使用明确标记的上下文后备话术。模型只生成对话，不能改分。

## 生命周期

Skill 入口仅接受固定动作：`check/install`、`start/open`、`restart`、`status`、`logs`、`stop`。入口将自身注册为 AuraApp，由现有 AppManager 在独立子进程中启动和回收，不拼接 shell 命令。

默认地址为 `http://127.0.0.1:3001`。端口被占用时启动失败并由 AppManager 记录明确错误，不会静默切换到未知端口。

## AuraOS 接口

- 状态与能力：`GET /api/daemon/status`
- 摄像头截图：`GET /api/media/camera/snapshot`
- TTS、ASR 和视觉请求：AuraOS 现有 `/ws/sdk` 类型化命令通道
- Agent 对话：`GenerateCmd(prompt)`，不向模型提供未揭晓答案；回复中出现答案时丢弃并回退。

AuraOS Daemon 始终是摄像头、麦克风、扬声器和模型的唯一所有者。本应用不直接打开硬件。

`runtime.json` 当前将 `vision_image_passthrough_confirmed` 设为 `true`。AuraOS 纯 `GenerateCmd` 会原样传递 PNG/JPEG 字节，并在有图时选择视觉 VLM；该调用不使用工具、不读写聊天历史、不显示或播音。摄像头和网页画布共享同一受限候选视觉适配器；模型调用或结构化解析失败时仍返回可见错误并保留降级路径，不伪造 Agent 得分。

Daemon 的状态字段会把 noop 也概括为 `local`。因此本 Skill 不直接相信该标签：Agent 对话初始为“待验证”，首次真实猜错时只有 `GenerateCmd` 返回非 noop 文本才转为可用，否则固定降级；TTS 只用不会播放的 `SynthesizeCmd` 非空音频结果判断并缓存 60 秒。纯 `GenerateCmd` 不再播音；模型文本先形成唯一 `DialogueEvent`，再由 AuraOS TTS 按事件序号精确消费一次。Windows noop Daemon 只报告“Daemon 已连接”，不会误报 Agent 模型或 TTS 已接通。

机器人屏幕目前只有 `RobotDisplaySink` 能力边界。它消费与网页相同的画布状态并返回不可用，不假设不存在的图像协议。

## 本地测试

从 Skill Store 工作树运行：

```powershell
$env:AURA_OS_ROOT = 'D:\path\to\aura-os'
$env:PYTHONPATH = "$env:AURA_OS_ROOT\src"
& "$env:AURA_OS_ROOT\.venv\Scripts\python.exe" -m pytest -q skills\aura-draw-and-guess\tests
python -X utf8 scripts\validate-skill.py skills\aura-draw-and-guess
python -X utf8 scripts\ci-validate.py
python -X utf8 scripts\ci-security-scan.py
python -X utf8 scripts\ci-registry.py --dry-run
```

真实视觉调用需要可用的模型配置。摄像头、扬声器、麦克风和机器人屏幕需要对应 RDK、凭据及已确认协议后单独验收；mock 通过不能替代真实硬件通过。
