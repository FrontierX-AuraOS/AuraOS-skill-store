#!/usr/bin/env python3
"""CI: Validate all MANIFEST.yaml files in skills/, and each skill's skill.md
frontmatter (bilingual fields, category taxonomy) — see DEVELOPER_GUIDE.md."""
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("❌ PyYAML not installed")
    sys.exit(1)

REQUIRED = ["id", "name", "version", "author", "description", "entry"]
VALID_TOOLS = {
    "say", "run_shell", "read_file", "write_file",
    "search_skills", "switch_skill", "activate_skill",
    "move", "capture_camera_image", "get_battery",
}

# Keep in sync with DEVELOPER_GUIDE.md's documented `category` enum.
VALID_CATEGORIES = {
    ("开发工具", "Developer Tools"),
    ("效率工具", "Productivity"),
    ("正能量", "Positive Energy"),
    ("创意娱乐", "Creative"),
}
VALID_CATEGORIES_ZH = {zh for zh, _ in VALID_CATEGORIES}
VALID_CATEGORIES_EN = {en for _, en in VALID_CATEGORIES}
REQUIRED_FRONTMATTER_FIELDS = ["title_zh", "title_en", "description_en", "category", "category_en"]
_CJK_RE = re.compile(r"[一-鿿]")
# CJK share of an _en field above this ratio means "this is Chinese text, not
# a translation" — below it, tolerate a short quoted Chinese phrase (e.g. a
# literal trigger word) inside an otherwise-English sentence.
_CJK_RATIO_THRESHOLD = 0.3

# Keep in sync with ci-registry.py's EXCLUDED_IDS — internal QA/test artifacts
# aren't held to the public-facing taxonomy/translation bar.
EXCLUDED_IDS = {"upload_probe_20260812"}


def _cjk_ratio(text: str) -> float:
    stripped = re.sub(r"\s", "", text)
    if not stripped:
        return 0.0
    return len(_CJK_RE.findall(stripped)) / len(stripped)


def _validate_skill_md(skill_dir: Path, skill_id: str, errors: list[str]) -> None:
    """Frontmatter must parse, carry both languages, and use the shared
    category taxonomy — this is what actually drives registry.json's
    title_en/description_en/tags_en, so a broken or missing field here ships
    straight to the public Skill Store in whatever language it fell back to."""
    skill_md = skill_dir / "skill.md"
    if not skill_md.is_file():
        errors.append(f"{skill_id}: missing skill.md")
        return

    text = skill_md.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        errors.append(f"{skill_id}: skill.md has no YAML frontmatter (must start with '---')")
        return

    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        errors.append(f"{skill_id}: skill.md frontmatter is invalid YAML — {exc}")
        return
    if not isinstance(fm, dict):
        errors.append(f"{skill_id}: skill.md frontmatter must be a YAML mapping")
        return

    for field in REQUIRED_FRONTMATTER_FIELDS:
        if not fm.get(field):
            errors.append(f"{skill_id}: skill.md frontmatter missing required field '{field}'")

    # Cheap but effective: an _en field containing CJK characters is almost
    # always a copy-paste of the zh value (or a placeholder), not a real
    # translation — catches exactly the class of bug that shipped Chinese
    # text to English-mode users with no warning anywhere in CI.
    for field in ("title_en", "description_en", "category_en"):
        value = fm.get(field)
        if isinstance(value, str) and _cjk_ratio(value) > _CJK_RATIO_THRESHOLD:
            errors.append(
                f"{skill_id}: skill.md '{field}' is mostly Chinese characters — "
                f"looks untranslated: {value!r}"
            )

    category = fm.get("category")
    category_en = fm.get("category_en")
    if category and category not in VALID_CATEGORIES_ZH:
        errors.append(
            f"{skill_id}: skill.md 'category' value {category!r} is not in the shared "
            f"taxonomy ({sorted(VALID_CATEGORIES_ZH)}) — see DEVELOPER_GUIDE.md"
        )
    if category_en and category_en not in VALID_CATEGORIES_EN:
        errors.append(
            f"{skill_id}: skill.md 'category_en' value {category_en!r} is not in the shared "
            f"taxonomy ({sorted(VALID_CATEGORIES_EN)}) — see DEVELOPER_GUIDE.md"
        )
    if category and category_en and (category, category_en) not in VALID_CATEGORIES:
        errors.append(
            f"{skill_id}: skill.md 'category'/'category_en' pair ({category!r}, {category_en!r}) "
            f"doesn't match — they must name the same taxonomy entry in both languages"
        )

errors = []
count = 0

skills_dir = Path("skills")
if not skills_dir.is_dir():
    print("ℹ️  No skills/ directory yet — nothing to validate")
    sys.exit(0)

for manifest_path in sorted(skills_dir.rglob("MANIFEST.yaml")):
    skill_dir = manifest_path.parent
    skill_id = skill_dir.name
    if skill_id in EXCLUDED_IDS:
        continue
    count += 1

    try:
        data = yaml.safe_load(manifest_path.read_text())
    except yaml.YAMLError as e:
        errors.append(f"{manifest_path}: invalid YAML — {e}")
        continue

    if not isinstance(data, dict):
        errors.append(f"{manifest_path}: must be a YAML mapping, got {type(data).__name__}")
        continue

    for key in REQUIRED:
        if key not in data:
            errors.append(f"{skill_id}: missing required field '{key}'")

    if data.get("id") != skill_id:
        errors.append(f"{skill_id}: id '{data.get('id')}' != folder name '{skill_id}'")

    version = str(data.get("version", ""))
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        errors.append(f"{skill_id}: version '{version}' is not valid semver")

    perms = data.get("permissions") or {}
    if isinstance(perms, dict):
        for t in (perms.get("tools") or []):
            if t not in VALID_TOOLS:
                errors.append(f"{skill_id}: unknown tool '{t}'")
        fs_scope = (perms.get("filesystem") or {}).get("scope", "skill")
        if fs_scope not in ("skill", "drive"):
            errors.append(f"{skill_id}: invalid filesystem.scope '{fs_scope}'")

    entry = data.get("entry") or {}
    if isinstance(entry, dict):
        etype = entry.get("type")
        if etype not in ("python", "markdown", "both"):
            errors.append(f"{skill_id}: entry.type must be python|markdown|both, got '{etype}'")
        if etype in ("python", "both"):
            main_file = entry.get("main", "main.py")
            if not (skill_dir / main_file).is_file():
                errors.append(f"{skill_id}: entry.main '{main_file}' not found")

    if len(data.get("tags") or []) > 5:
        errors.append(f"{skill_id}: max 5 tags")

    _validate_skill_md(skill_dir, skill_id, errors)

if errors:
    print(f"❌ {len(errors)} error(s):")
    for e in errors:
        print(f"   {e}")
    sys.exit(1)

print(f"✅ All {count} skill(s) valid")
