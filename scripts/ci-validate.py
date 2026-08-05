#!/usr/bin/env python3
"""CI: Validate all MANIFEST.yaml files in skills/."""
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

errors = []
count = 0

skills_dir = Path("skills")
if not skills_dir.is_dir():
    print("ℹ️  No skills/ directory yet — nothing to validate")
    sys.exit(0)

for manifest_path in sorted(skills_dir.rglob("MANIFEST.yaml")):
    count += 1
    skill_dir = manifest_path.parent
    skill_id = skill_dir.name

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

if errors:
    print(f"❌ {len(errors)} error(s):")
    for e in errors:
        print(f"   {e}")
    sys.exit(1)

print(f"✅ All {count} skill(s) valid")
