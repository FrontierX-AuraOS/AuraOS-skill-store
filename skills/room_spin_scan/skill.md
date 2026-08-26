---
name: room_spin_scan
title_zh: 原地扫屋
title_en: Room Spin Scan
category: 创意娱乐
category_en: Creative
description: 原地分段旋转，每转一小段就拍照，并用视觉解说周围环境（离散抓拍，中间会停）。
description_en: Spin in place in short segments, capture a photo after each turn, and narrate what is around (discrete snapshots with brief pauses).
aliases:
  - 扫一圈
  - 转圈看看
  - 扫屋
  - 转一圈看看这间屋子
is_persona: false
greeting: 好，我转一圈看看这间屋子。光线够的话我会边转边拍边说。
greeting_en: Alright, I'll spin and look around the room. If the light is good, I'll snap and narrate as I turn.
action_steps:
  repeat: 5
  actions:
  - tool: move
    args:
      linear_x: 0.0
      angular_z: 0.2
      duration: 5.0
  - tool: capture_camera_image
    args: {}
  - tool: describe_last_image
    args:
      prompt: "用一句中文说你看到了什么。先说方位（左手边 / 正前方 / 右手边），再点出主要物体或人。画面模糊或对着强光就直说「拍不清楚，我再转一点」，不要编造细节。"
      prompt_en: "One short sentence in English: first the side (left / front / right), then the main objects or people. If blurry or blown out by light, say you cannot see clearly and will turn a bit more — do not invent details."
---

# 原地扫屋 · Room Spin Scan

现场说法示例：「Aura，转一圈看看这间屋子，每转一小段拍一张，告诉我周围有什么。」

执行约定：

- 每段只转一小会儿（`move` 最长 5 秒），不要指望一段转满 360°。
- `repeat: 5` 大约扫大半圈到接近一圈；中间会停一下再拍。
- 人站在安全距离外，轮周无电缆；镜头别对窗爆光。
- 模糊帧如实说，比硬编画面好看。
