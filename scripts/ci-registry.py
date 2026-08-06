#!/usr/bin/env python3
"""Generate (dry-run or write) registry.json from skills/."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print("❌ PyYAML not installed")
    sys.exit(1)

DRY_RUN = "--dry-run" in sys.argv
BASE_URL = "https://raw.githubusercontent.com/FrontierX-AuraOS/AuraOS-skill-store/main"

skills = []
skills_dir = Path("skills")

if skills_dir.is_dir():
    for manifest_path in sorted(skills_dir.rglob("MANIFEST.yaml")):
        try:
            data = yaml.safe_load(manifest_path.read_text())
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue

        skill_dir = manifest_path.parent
        total_size = sum(
            f.stat().st_size for f in skill_dir.rglob("*") if f.is_file()
        )

        # Detect kind, titles, descriptions from skill.md frontmatter
        kind = "skill"
        title_zh = data.get("name", "")
        title_en = data.get("name", "")
        desc_zh = data.get("description", "")
        desc_en = data.get("description", "")
        author_id = data.get("author_id", "")
        skill_md = skill_dir / "skill.md"
        if skill_md.exists():
            try:
                text = skill_md.read_text(encoding="utf-8")
                import re as _re
                m = _re.match(r"^---\n(.*?)\n---", text, _re.DOTALL)
                if m:
                    fm = yaml.safe_load(m.group(1)) or {}
                    if fm.get("is_persona"):
                        kind = "persona"
                    title_zh = str(fm.get("title_zh") or data.get("name", ""))
                    title_en = str(fm.get("title_en") or data.get("name", ""))
                    desc_zh = str(fm.get("description") or desc_zh)
                    desc_en = str(fm.get("description_en") or desc_en)
            except Exception:
                pass

        skills.append({
            "id": data["id"],
            "name": data["name"],
            "title_zh": title_zh,
            "title_en": title_en,
            "description_zh": desc_zh,
            "description_en": desc_en,
            "version": str(data["version"]),
            "author": data["author"],
            "author_id": author_id,
            "description": desc_en,  # backward compat
            "kind": kind,
            "tags": data.get("tags") or [],
            "downloadUrl": f"{BASE_URL}/skills/{data['id']}",
            "iconUrl": f"{BASE_URL}/skills/{data['id']}/icon.png",
            "installs": 0,
            "tier": "reviewed",
            "minAuraVersion": data.get("minAuraVersion", "0.1.0"),
            "size": total_size,
            "checksum": hashlib.sha256(
                json.dumps(data, sort_keys=True).encode()
            ).hexdigest(),
        })

registry = {
    "version": 1,
    "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "skills": skills,
}

if DRY_RUN:
    print(json.dumps(registry, indent=2, ensure_ascii=False))
    print(f"\n✅ Registry dry-run OK ({len(skills)} skills)")
else:
    Path("registry.json").write_text(
        json.dumps(registry, indent=2, ensure_ascii=False) + "\n"
    )
    print(f"✅ registry.json written ({len(skills)} skills)")
