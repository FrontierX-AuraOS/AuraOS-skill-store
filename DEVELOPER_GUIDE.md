# AuraOS Skill Developer Guide

## Overview

An Aura skill is a **directory** containing at minimum `skill.md`.  
If your skill needs code execution, add `main.py` with a `run(context, task)` function.

## Quick Start

```bash
cp -r example-skill skills/my-skill
```

## Required Files

```
skills/<skill-id>/             # folder name = skill id (kebab-case)
├── MANIFEST.yaml  ← required  # metadata + permissions
├── skill.md       ← required  # declarative definition
└── main.py        ← optional  # executable code
```

## MANIFEST.yaml

```yaml
id: my-skill                    # kebab-case, MUST match folder name
name: My Skill                  # display name (max 64 chars)
version: 1.0.0                  # semver
author: your-github-username    # you!
description: >-                 # one-liner for store cards (max 140 chars)
  What your skill does in one sentence.

# ── Optional ──
license: MIT
tags: [demo, utility]           # max 5, used for search/filter
minAuraVersion: 0.1.2

# ── Permissions (for code skills) ──
permissions:
  tools:                        # only these tools are allowed
    - say                       #   always allowed, no need to list
    - run_shell
    - read_file
  network:
    domains: []                 # allowed outbound domains (empty = no network)
  filesystem:
    scope: skill                 # "skill" = own dir only | "drive" = user drive
  maxRuntimeSec: 30

# ── Entry Point ──
entry:
  type: python                   # "python" | "markdown" | "both"
  main: main.py                  # entry file
  function: run                  # function name (default: run)
```

### Available Tools

| Tool | Permission | Description |
|------|-----------|-------------|
| `say` | (always allowed) | Send a chat message |
| `run_shell` | run_shell | Execute a shell command |
| `read_file` | read_file | Read from user's drive |
| `write_file` | write_file | Write to user's drive |
| `move` | move | Control robot movement |
| `capture_camera_image` | capture_camera_image | Take a photo |
| `search_skills` | search_skills | Find other skills |
| `switch_skill` | switch_skill | Activate another skill |

## skill.md Format

```markdown
---
type: persona                           # "persona" | "skill"
name: My Skill Display Name
name_zh: 我的技能                        # Chinese display name
description: Short one-line summary
description_en: English summary
title_zh: 中文标题
title_en: English Title
greeting: 你好！我能帮你做什么？           # First message when activated
greeting_en: Hello! What can I help with?
category: demo                          # one of: 人格情绪|桌游互动|安防监控|办公巡视|开发工具|demo|动作
---

中文系统提示词正文。

[[EN]]
English system prompt body.
```

## main.py Interface

```python
async def run(context, task: str = "") -> str:
    """
    Entry point called by the skill runner subprocess.

    Args:
        context: SkillContext with whitelisted tools (only what you declared in MANIFEST)
        task:    Task description from the agent

    Returns:
        Result string (shown to user)
    """
    await context.say(f"Processing: {task}")
    return "done"
```

### Using tools

```python
# Say something
await context.say("Hello!")

# Run a shell command (requires run_shell permission)
result = await context.run_shell("ls -la")

# Read a file (requires read_file permission)
content = await context.read_file("/path/to/file.txt")

# Write a file (requires write_file permission)
await context.write_file("/path/to/file.txt", "content")
```

## Validation

Before submitting, run:

```bash
python3 scripts/validate-skill.py skills/my-skill
```

## Submission

### Option A: Aura Studio (recommended)
1. Open Aura → Studio tab
2. Create your skill draft
3. Paste your GitHub PAT once
4. Click **"Publish to Store"**

### Option B: Manual PR
1. Fork `FrontierX-AuraOS/AuraOS-skill-store`
2. Add your skill folder under `skills/`
3. Run validation
4. Submit a Pull Request

## CI Checks

Your PR will be automatically checked for:
- ✅ MANIFEST.yaml structure and completeness
- ✅ No dangerous imports without declared permissions
- ✅ `skill.md` has valid frontmatter
- ✅ Registry can be generated successfully

## After Merge

Once merged, your skill appears in the Skill Store within minutes.  
Users can install it with one click from inside Aura.

## Rules

1. **Folder name = skill id** — must match `MANIFEST.yaml` `id` field
2. **Permissions must be declared** — any tool used must be in `permissions.tools`
3. **No `exec`/`eval`** — flagged for manual review
4. **Max 5 tags** — used for store search
5. **Semver versions** — `major.minor.patch`
