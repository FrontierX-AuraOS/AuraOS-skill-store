#!/usr/bin/env python3
"""CI: Security scan on all .py files in skills/.

Cross-checks each dangerous import against the skill's own MANIFEST.yaml
permissions — a properly-declared permission doesn't fail the build; an
undeclared one does. (Previously this always flagged the import regardless
of what was declared, so every skill using `requests`/`subprocess`/etc.
failed CI even with correct permissions — DEVELOPER_GUIDE.md promises "no
dangerous imports without declared permissions", not "no dangerous imports,
period".)
"""
import sys
from pathlib import Path

try:
    import ast
    import yaml
except ImportError:
    print("❌ PyYAML not installed")
    sys.exit(1)

# import base -> which MANIFEST.yaml permission covers it, and how to check
# that permission was actually declared. No entry here (pickle, ctypes) means
# there's no declarable permission for it in the schema — always flag those
# for human review, regardless of the manifest.
NETWORK_IMPORTS = {"socket", "requests", "urllib.request", "urllib3", "httpx", "aiohttp", "websocket"}
PROCESS_IMPORTS = {"subprocess"}
FILESYSTEM_IMPORTS = {"shutil"}
ALWAYS_FLAG = {"pickle": "deserialize", "ctypes": "native"}


def _permission_covers(base: str, manifest: dict) -> bool:
    perms = manifest.get("permissions") or {}
    if not isinstance(perms, dict):
        return False
    if base in NETWORK_IMPORTS:
        domains = (perms.get("network") or {}).get("domains")
        return bool(domains)
    if base in PROCESS_IMPORTS:
        return "run_shell" in (perms.get("tools") or [])
    if base in FILESYSTEM_IMPORTS:
        scope = (perms.get("filesystem") or {}).get("scope")
        return scope in ("skill", "drive")
    return False


findings = []
count = 0

skills_dir = Path("skills")
if not skills_dir.is_dir():
    print("ℹ️  No skills/ directory yet — nothing to scan")
    sys.exit(0)

for py_file in sorted(skills_dir.rglob("*.py")):
    if py_file.parent.name.startswith("."):
        continue
    count += 1
    source = py_file.read_text(encoding="utf-8")

    manifest_path = py_file.parent / "MANIFEST.yaml"
    manifest: dict = {}
    if manifest_path.is_file():
        try:
            loaded = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                manifest = loaded
        except yaml.YAMLError:
            pass  # ci-validate.py already reports malformed MANIFEST.yaml

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        findings.append(f"{py_file}: syntax error — {e}")
        continue

    def _check_import(base: str, full_name: str) -> None:
        if base in ALWAYS_FLAG:
            findings.append(
                f"{py_file}: imports '{full_name}' — no permission covers this, "
                f"MUST be flagged for human review"
            )
        elif (base in NETWORK_IMPORTS or base in PROCESS_IMPORTS or base in FILESYSTEM_IMPORTS) \
                and not _permission_covers(base, manifest):
            findings.append(
                f"{py_file}: imports '{full_name}' without a matching declared permission "
                f"in MANIFEST.yaml (see DEVELOPER_GUIDE.md permissions)"
            )

    for node in ast.walk(tree):
        # Check imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                _check_import(alias.name.split(".")[0], alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                _check_import(node.module.split(".")[0], node.module)

        # Flag exec/eval
        if isinstance(node, ast.Call):
            func = None
            if isinstance(node.func, ast.Name):
                func = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func = node.func.attr
            if func in ("exec", "eval", "compile"):
                findings.append(
                    f"{py_file}: uses '{func}' — MUST be flagged for human review"
                )

    # os.system check — covered by the same "process" permission as subprocess
    if ("os.system" in source or "os.popen" in source) and not _permission_covers("subprocess", manifest):
        findings.append(
            f"{py_file}: uses os.system/os.popen without 'run_shell' declared in MANIFEST.yaml"
        )

if findings:
    print(f"⚠️  {len(findings)} issue(s):")
    for f in findings:
        print(f"   {f}")
    sys.exit(1)

print(f"✅ Security scan passed ({count} file(s))")
