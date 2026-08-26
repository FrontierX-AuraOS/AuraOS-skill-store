#!/usr/bin/env python3
"""
Local skill validator — run before submitting a PR to AuraOS-skill-store.

Mirrors what CI actually checks (scripts/ci-validate.py, ci-security-scan.py)
so a passing run here means the PR will pass CI too — see those two files if
this one and CI ever disagree, and fix both.

Usage:
    python3 scripts/validate-skill.py skills/my-skill
    python3 scripts/validate-skill.py --all
"""

import ast
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("❌ PyYAML is required. Install it: pip install pyyaml")
    sys.exit(1)

REQUIRED_FILES = ["MANIFEST.yaml", "skill.md"]
REQUIRED_MANIFEST_FIELDS = ["id", "name", "version", "author", "description", "entry"]
REQUIRED_FRONTMATTER_FIELDS = ["title_zh", "title_en", "description_en", "category", "category_en"]
VALID_TOOLS = {
    "say", "run_shell", "read_file", "write_file",
    "search_skills", "switch_skill", "activate_skill",
    "move", "capture_camera_image", "get_battery",
}
VALID_ENTRY_TYPES = {"python", "markdown", "both"}

# Keep in sync with ci-validate.py / DEVELOPER_GUIDE.md.
VALID_CATEGORIES = {
    ("开发工具", "Developer Tools"),
    ("效率工具", "Productivity"),
    ("正能量", "Positive Energy"),
    ("创意娱乐", "Creative"),
}
VALID_CATEGORIES_ZH = {zh for zh, _ in VALID_CATEGORIES}
VALID_CATEGORIES_EN = {en for _, en in VALID_CATEGORIES}
_CJK_RE = re.compile(r"[一-鿿]")
_CJK_RATIO_THRESHOLD = 0.3

NETWORK_IMPORTS = {"socket", "requests", "urllib.request", "httpx", "aiohttp"}
PROCESS_IMPORTS = {"subprocess", "os"}  # "os" here only for os.system/os.popen, checked separately below
FILESYSTEM_IMPORTS = {"shutil"}
ALWAYS_FLAG = {"pickle": "deserialize", "ctypes": "native"}

errors = []


def _cjk_ratio(text: str) -> float:
    stripped = re.sub(r"\s", "", text)
    if not stripped:
        return 0.0
    return len(_CJK_RE.findall(stripped)) / len(stripped)


def _permission_covers(base: str, manifest: dict) -> bool:
    perms = manifest.get("permissions") or {}
    if not isinstance(perms, dict):
        return False
    if base in NETWORK_IMPORTS:
        return bool((perms.get("network") or {}).get("domains"))
    if base == "subprocess":
        return "run_shell" in (perms.get("tools") or [])
    if base in FILESYSTEM_IMPORTS:
        return (perms.get("filesystem") or {}).get("scope") in ("skill", "drive")
    return False


def validate_skill(skill_dir: Path) -> bool:
    skill_id = skill_dir.name
    local_errors: list[str] = []

    # Check required files
    for fname in REQUIRED_FILES:
        if not (skill_dir / fname).exists():
            local_errors.append(f"Missing required file: {fname}")

    # Validate MANIFEST.yaml
    manifest_path = skill_dir / "MANIFEST.yaml"
    manifest: dict = {}
    if manifest_path.exists():
        try:
            loaded = yaml.safe_load(manifest_path.read_text())
        except yaml.YAMLError as e:
            local_errors.append(f"MANIFEST.yaml: invalid YAML: {e}")
            return _report(skill_id, local_errors)

        if not isinstance(loaded, dict):
            local_errors.append("MANIFEST.yaml must be a YAML mapping (not a list)")
            return _report(skill_id, local_errors)
        manifest = loaded

        for field in REQUIRED_MANIFEST_FIELDS:
            if field not in manifest:
                local_errors.append(f"MANIFEST.yaml missing required field: {field}")

        if manifest.get("id") != skill_id:
            local_errors.append(
                f"MANIFEST.yaml id '{manifest.get('id')}' != folder name '{skill_id}'"
            )

        version = str(manifest.get("version", ""))
        parts = version.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            local_errors.append(f"version '{version}' is not valid semver")

        # Validate permissions
        perms = manifest.get("permissions", {})
        if perms:
            tools = perms.get("tools", [])
            for t in tools:
                if t not in VALID_TOOLS:
                    local_errors.append(f"Unknown tool: '{t}'")

            fs_scope = perms.get("filesystem", {}).get("scope", "skill")
            if fs_scope not in ("skill", "drive"):
                local_errors.append(f"Invalid filesystem.scope: '{fs_scope}'")

            domains = perms.get("network", {}).get("domains", [])
            if not isinstance(domains, list):
                local_errors.append("permissions.network.domains must be a list")

        # Validate entry
        entry = manifest.get("entry", {})
        if not isinstance(entry, dict):
            local_errors.append("entry must be a mapping")
        else:
            entry_type = entry.get("type")
            if entry_type not in VALID_ENTRY_TYPES:
                local_errors.append(f"entry.type must be one of: {', '.join(VALID_ENTRY_TYPES)}")

            if entry_type in ("python", "both"):
                main_file = entry.get("main", "main.py")
                if not (skill_dir / main_file).exists():
                    local_errors.append(f"entry.main '{main_file}' not found")

        # Security scan on .py files — cross-checked against declared permissions
        for py_file in skill_dir.glob("*.py"):
            _scan_python(py_file, manifest, local_errors)

    # Validate skill.md frontmatter — parses, both languages present, category
    # taxonomy respected. This is what actually reaches the public Skill
    # Store (registry.json's title_en/description_en/tags_en come straight
    # from here), so a broken or missing field here is what shipped Chinese
    # text to English-mode users last time with nothing catching it.
    skill_md = skill_dir / "skill.md"
    if skill_md.exists():
        _validate_skill_md(skill_md, skill_id, local_errors)

    return _report(skill_id, local_errors)


def _validate_skill_md(skill_md: Path, skill_id: str, local_errors: list[str]) -> None:
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        local_errors.append("skill.md must start with YAML frontmatter (---)")
        return

    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        local_errors.append("skill.md frontmatter has no closing '---'")
        return

    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        local_errors.append(f"skill.md frontmatter is invalid YAML: {e}")
        return
    if not isinstance(fm, dict):
        local_errors.append("skill.md frontmatter must be a YAML mapping")
        return

    for field in REQUIRED_FRONTMATTER_FIELDS:
        if not fm.get(field):
            local_errors.append(f"skill.md frontmatter missing required field '{field}'")

    for field in ("title_en", "description_en", "category_en"):
        value = fm.get(field)
        if isinstance(value, str) and _cjk_ratio(value) > _CJK_RATIO_THRESHOLD:
            local_errors.append(
                f"skill.md '{field}' is mostly Chinese characters — looks untranslated: {value!r}"
            )

    category = fm.get("category")
    category_en = fm.get("category_en")
    if category and category not in VALID_CATEGORIES_ZH:
        local_errors.append(
            f"skill.md 'category' value {category!r} is not in the shared taxonomy "
            f"({sorted(VALID_CATEGORIES_ZH)}) — see DEVELOPER_GUIDE.md"
        )
    if category_en and category_en not in VALID_CATEGORIES_EN:
        local_errors.append(
            f"skill.md 'category_en' value {category_en!r} is not in the shared taxonomy "
            f"({sorted(VALID_CATEGORIES_EN)}) — see DEVELOPER_GUIDE.md"
        )
    if category and category_en and (category, category_en) not in VALID_CATEGORIES:
        local_errors.append(
            f"skill.md 'category'/'category_en' pair ({category!r}, {category_en!r}) doesn't "
            f"match — they must name the same taxonomy entry in both languages"
        )


def _scan_python(py_file: Path, manifest: dict, local_errors: list[str]) -> None:
    """Security scan: flag imports that aren't declared in MANIFEST permissions."""
    source = py_file.read_text()

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        local_errors.append(f"{py_file.name}: syntax error — {e}")
        return

    def check_import(base: str, full_name: str) -> None:
        if base in ALWAYS_FLAG:
            local_errors.append(
                f"{py_file.name}: imports '{full_name}' — no permission covers this, "
                f"flagged for human review"
            )
        elif (base in NETWORK_IMPORTS or base == "subprocess" or base in FILESYSTEM_IMPORTS) \
                and not _permission_covers(base, manifest):
            local_errors.append(
                f"{py_file.name}: imports '{full_name}' — add the matching permission "
                f"to MANIFEST.yaml (network.domains / tools: [run_shell] / filesystem.scope)"
            )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                check_import(alias.name.split(".")[0], alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                check_import(node.module.split(".")[0], node.module)
        elif isinstance(node, ast.Call):
            func = None
            if isinstance(node.func, ast.Name):
                func = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func = node.func.attr
            if func in ("exec", "eval", "compile"):
                local_errors.append(
                    f"{py_file.name}: uses '{func}' — flagged for review"
                )

    if ("os.system" in source or "os.popen" in source) and not _permission_covers("subprocess", manifest):
        local_errors.append(
            f"{py_file.name}: uses os.system/os.popen — add 'run_shell' to MANIFEST.yaml tools"
        )


def _report(skill_id: str, local_errors: list[str]) -> bool:
    if local_errors:
        print(f"\n❌ {skill_id}:")
        for e in local_errors:
            print(f"   ⚠️  {e}")
        errors.extend(local_errors)
        return False
    else:
        print(f"✅ {skill_id}")
        return True


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--all":
        skills_root = Path("skills")
        if not skills_root.exists():
            print("No skills/ directory found")
            sys.exit(1)
        all_passed = True
        for skill_dir in sorted(skills_root.iterdir()):
            if skill_dir.is_dir() and not skill_dir.name.startswith("."):
                if not validate_skill(skill_dir):
                    all_passed = False
        if not all_passed:
            print(f"\n❌ {len(errors)} error(s) found. Fix them before submitting a PR.")
            sys.exit(1)
        print(f"\n🎉 All skills passed!")
    else:
        skill_dir = Path(sys.argv[1])
        if not skill_dir.exists():
            print(f"❌ Directory not found: {skill_dir}")
            sys.exit(1)
        if not validate_skill(skill_dir):
            print(f"\n❌ {len(errors)} error(s) found. Fix them before submitting a PR.")
            sys.exit(1)
        print(f"\n🎉 Ready to submit!")


if __name__ == "__main__":
    main()
