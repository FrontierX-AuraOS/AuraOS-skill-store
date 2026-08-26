---
name: see_and_poem
description: 先拍眼前画面，抽取关键词写一首平水韵绝句并朗读
aliases:
- 看景写诗
- 即景赋诗
greeting: 看看前面，用你看到的两三个词作一首绝句。
action_steps:
  repeat: 1
  actions:
  - tool: capture_camera_image
    args: {}
  - tool: say
    args:
      text: 好，我看看眼前……（此处由模型根据画面即时生成绝句并朗读，遵循平仄与平水韵，赏析一句即可）
title_zh: 先拍眼前画面，抽取关键词写一首平水韵绝句并朗读
title_en: see and poem
description_en: Action skill see_and_poem
is_persona: false
category: 创意娱乐
category_en: Creative
---
