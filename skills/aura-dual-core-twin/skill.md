---
name: aura_dual_core_twin
title_zh: AURA 方舟对决
title_en: AURA Dual Core Twin
category: 桌游互动
description: 安装、启动、停止并检查 AURA 方舟对决双人战术桌游。
description_en: Install, start, stop, and inspect the AURA Dual Core Twin tactical board game.
aliases:
  - 方舟对决
  - 方舟对战
  - 启动方舟对决
  - AURA Dual Core Twin
is_persona: false
greeting: 方舟对决已就绪。你可以让我启动、停止、查看状态或读取日志。
greeting_en: AURA Dual Core Twin is ready. Ask me to start, stop, inspect, or read its logs.
---

你负责运行 AURA 方舟对决。它默认使用两台虚拟 AURA，不需要实体机器人、手机摄像头或 `DEEPSEEK_API_KEY`。

## 操作规则

- 用户要求安装、启动、运行、打开、停止、重启、查看状态或查看日志时，必须调用 `run_skill_code` 执行本技能代码，不要只用文字声称成功。
- 将用户原话作为 `task` 传给代码。代码只接受固定动作，不执行用户提供的命令。
- 首次启动会下载并校验固定版本的项目包、运行 `npm ci` 和生产构建，可能需要数分钟。
- 启动成功后把代码返回的本地网址原样告诉用户。
- 实体机器人模式不是默认行为。只有用户明确将至少一方设为实体机器人，并为选择实体的一方配置对应 AuraOS Daemon 地址后，才指导其在游戏右上角连接机器人。
- 若状态或日志返回错误，原样说明错误与建议，不要猜测已经启动。

[[EN]]
You operate AURA Dual Core Twin. It defaults to two virtual AURA robots and requires no physical robot, phone camera, or `DEEPSEEK_API_KEY`.

## Rules

- For install, start, open, stop, restart, status, or logs requests, call `run_skill_code`; never claim success without execution.
- Pass the user's request as `task`. The code accepts only fixed actions and never executes user-provided commands.
- First start downloads and verifies an immutable release, then runs `npm ci` and a production build; this may take several minutes.
- Return the local URL from the code after a successful start.
- Physical robot mode is opt-in. Configure an AuraOS Daemon endpoint for each side explicitly set to use a physical robot.
- Report returned errors honestly; do not guess that the service is running.
