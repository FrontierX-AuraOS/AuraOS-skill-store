# AuraOS Skill Store · 技能商店

<p align="center">
  <strong>中文</strong> &nbsp;|&nbsp; <a href="#english">English</a>
</p>

---

## 中文

AuraOS 官方技能商店。浏览、提交、一键安装扩展 Aura 能力的技能。

### 用户使用

在 Aura 桌面应用中打开 **技能商店** 标签页，浏览并一键下载安装。

### 开发者提交

三种方式，按需选择：

**方式一：Aura Studio 一键发布（推荐）**

1. 在 Aura 的 Studio 标签中写好 skill 草稿
2. 粘贴一次你的 GitHub Personal Access Token
3. 点击 **"Publish to Store"** → 自动创建 PR

**方式二：GitHub 网页上传**

1. Fork 本仓库
2. 在 `skills/` 下创建你的 skill 文件夹
3. 直接在 GitHub 网页上拖拽上传文件
4. 发起 Pull Request

**方式三：命令行**

```bash
cp -r example-skill skills/my-skill   # 复制模板
vim skills/my-skill/MANIFEST.yaml     # 编辑清单
vim skills/my-skill/skill.md          # 编辑定义
vim skills/my-skill/main.py           # 编辑代码（可选）
python3 scripts/validate-skill.py skills/my-skill  # 本地校验
gh pr create --title "Add my-skill"               # 提交 PR
```

### 文件结构

```
skills/<skill-id>/         # 文件夹名 = skill id（kebab-case）
├── MANIFEST.yaml          # 必需：元数据 + 权限声明
├── skill.md               # 必需：声明式定义（persona / 动作序列）
├── main.py                # 可选：可执行代码
├── icon.png               # 可选：256×256 图标
└── README.md              # 可选：商店详情页长描述
```

### 安全审查

每个 PR 自动通过 CI 检查：
- MANIFEST 结构完整性
- 代码中使用的工具是否已在 manifest 中声明
- 无恶意 import（socket、subprocess 等未声明权限）
- `exec` / `eval` 标记人工审查

详见 [SPEC.md](./SPEC.md) 和 [DEVELOPER_GUIDE.md](./DEVELOPER_GUIDE.md)。

---

## <a name="english">English</a>

The official skill marketplace for AuraOS. Browse, submit, and install skills with one click.

### For Users

Open the **Skill Store** tab in your Aura desktop app to browse and install.

### For Developers

Three ways to submit:

**Option A: Aura Studio (recommended)**

1. Write your skill draft in Aura's Studio tab
2. Paste your GitHub PAT once
3. Click **"Publish to Store"** → PR is created automatically

**Option B: GitHub Web UI**

1. Fork this repo
2. Create your skill folder under `skills/`
3. Drag & drop files directly on GitHub
4. Open a Pull Request

**Option C: CLI**

```bash
cp -r example-skill skills/my-skill
vim skills/my-skill/MANIFEST.yaml
vim skills/my-skill/skill.md
vim skills/my-skill/main.py
python3 scripts/validate-skill.py skills/my-skill
gh pr create --title "Add my-skill"
```

### File Structure

```
skills/<skill-id>/
├── MANIFEST.yaml     # Required: metadata + permissions
├── skill.md          # Required: declarative definition
├── main.py           # Optional: executable code
├── icon.png          # Optional: 256×256 icon
└── README.md         # Optional: long description
```

### CI Security Checks

Every PR is scanned for:
- Valid MANIFEST structure
- Declared permissions match actual code usage
- No dangerous imports without permission
- `exec` / `eval` flagged for human review

See [SPEC.md](./SPEC.md) and [DEVELOPER_GUIDE.md](./DEVELOPER_GUIDE.md) for details.
