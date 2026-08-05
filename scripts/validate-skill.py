#!/usr/bin/env python3
"""
Local skill validator — run before submitting a PR to AuraOS-skill-store.

Usage:
    python3 scripts/validate-skill.py skills/my-skill
    python3 scripts/validate-skill.py --all
"""

import ast
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("❌ PyYAML is required. Install it: pip install pyyaml")
    sys.exit(1)

REQUIRED_FILES = ["MANIFEST.yaml", "skill.md"]
REQUIRED_MANIFEST_FIELDS = ["id", "name", "version", "author", "description", "entry"]
VALID_TOOLS = {
    "say", "run_shell", "read_file", "write_file",
    "search_skills", "switch_skill", "activate_skill",
    "move", "capture_camera_image", "get_battery",
}
VALID_ENTRY_TYPES = {"python", "markdown", "both"}

errors = []


def validate_skill(skill_dir: Path) -> bool:
    skill_id = skill_dir.name
    local_errors: list[str] = []

    # Check required files
    for fname in REQUIRED_FILES:
        if not (skill_dir / fname).exists():
            local_errors.append(f"Missing required file: {fname}")

    # Validate MANIFEST.yaml
    manifest_path = skill_dir / "MANIFEST.yaml"
    if manifest_path.exists():
        try:
            manifest = yaml.safe_load(manifest_path.read_text())
        except yaml.YAMLError as e:
            local_errors.append(f"Invalid YAML: {e}")
            return _report(skill_id, local_errors)

        if not isinstance(manifest, dict):
            local_errors.append("MANIFEST.yaml must be a YAML mapping (not a list)")
            return _report(skill_id, local_errors)

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

        # Security scan on .py files
        for py_file in skill_dir.glob("*.py"):
            _scan_python(py_file, manifest, local_errors)

    # Validate skill.md has YAML frontmatter
    skill_md = skill_dir / "skill.md"
    if skill_md.exists():
        content = skill_md.read_text()
        if not content.startswith("---"):
            local_errors.append("skill.md must start with YAML frontmatter (---)")

    return _report(skill_id, local_errors)


def _scan_python(py_file: Path, manifest: dict, local_errors: list[str]) -> None:
    """Security scan: flag imports that aren't declared in MANIFEST permissions."""
    DANGEROUS = {
        "socket": "network",
        "requests": "network",
        "urllib.request": "network",
        "httpx": "network",
        "aiohttp": "network",
        "subprocess": "process",
        "os": "system",
        "shutil": "filesystem",
        "pickle": "deserialize",
        "ctypes": "native",
    }

    allowed_tools = set(manifest.get("permissions", {}).get("tools", []))
    source = py_file.read_text()

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        local_errors.append(f"{py_file.name}: syntax error — {e}")
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                base = alias.name.split(".")[0]
                if base in DANGEROUS:
                    local_errors.append(
                        f"{py_file.name}: imports '{alias.name}' — add "
                        f"'{DANGEROUS[base]}' permission to MANIFEST.yaml"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                base = node.module.split(".")[0]
                if base in DANGEROUS:
                    local_errors.append(
                        f"{py_file.name}: imports '{node.module}' — add "
                        f"'{DANGEROUS[base]}' permission to MANIFEST.yaml"
                    )
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
