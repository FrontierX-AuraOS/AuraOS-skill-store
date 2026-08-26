---
name: aura_draw_and_guess
title_zh: AURA 你画我猜
title_en: AURA Draw & Guess
category: 创意娱乐
category_en: Creative
description: 和 Agent 玩六回合你画我猜，双方各猜三次，支持逐笔作画、计分和硬件能力诚实降级。
description_en: Play six rounds of draw-and-guess with three guesses per side, progressive drawing, scoring, and honest hardware fallbacks.
aliases:
  - 你画我猜
  - 猜画游戏
  - 启动你画我猜
  - Draw and Guess
is_persona: false
greeting: 你画我猜已经就绪。让我启动游戏、查看状态、读取日志或停止游戏。
greeting_en: Draw & Guess is ready. Ask me to start, inspect, read logs, or stop the game.
---

你负责运行 AURA 你画我猜。默认模式由用户明确控制 Agent 每次继续一笔；网页轮流画模式在第 2/4/6 回合支持用户用鼠标或触摸作画。固定进行六回合，双方各猜三次，基础流程不依赖机器人或云端模型。

## 操作规则

- 用户要求安装检查、启动、打开、停止、重启、查看状态或查看日志时，必须调用 `run_skill_code`，不要只用文字声称成功。
- 将用户原话作为 `task` 传给代码。代码只接受固定动作，不执行用户提供的命令。
- 启动成功后，将代码返回的本地网址原样告诉用户。
- 视觉模型可用时，页面默认使用 `web_duel`，双方各猜三次；视觉不可用时默认 `web_only`。只有游戏页面明确显示摄像头、视觉模型和图像透传能力均可用时，才允许创建机器人摄像头模式。
- 用户要求双方轮流作画时使用页面中的 `web_duel`；Agent 只有在视觉模型真实返回结果后才参与计分，视觉不可用时不得声称已经看图。
- 配套 AuraOS 纯生成接口原样传递 PNG/JPEG；网页画布与摄像头共用视觉适配器，视觉失败时使用页面提供的受控降级路径。
- “继续画”与页面 `POST /draw/advance` 是同一受控动作语义；未来语音入口应映射该动作，不得自行循环推进笔画。
- 页面显示 `AURAOS AGENT` 时，猜错回应来自 AuraOS `GenerateCmd`；显示 `LOCAL FALLBACK` 时必须按页面状态说明模型未接通。
- 摄像头、视觉、TTS、ASR 或机器人屏幕显示为不可用时，应原样说明页面中的降级状态，不能声称硬件已经工作。
- 状态或日志返回错误时，原样说明错误与建议，不要猜测服务已经启动。

[[EN]]
You operate AURA Draw & Guess. Its six-round duel alternates roles so the user and Agent guess three times each. The default web-only mode requires no robot or cloud model.

## Rules

- For install checks, start, open, stop, restart, status, or logs requests, call `run_skill_code`; never claim success without execution.
- Pass the user's request as `task`. The code accepts fixed actions only and never executes user-provided commands.
- Return the local URL exactly as reported after a successful start.
- Default to `web_duel` when vision is available and `web_only` otherwise. Robot camera mode requires camera, vision, and confirmed image pass-through.
- Report camera, vision, TTS, ASR, and robot-display fallback states honestly; never claim unavailable hardware worked.
- Report returned status and log errors as-is.
