#!/usr/bin/env python3
"""CI: Security scan on all .py files in skills/."""
import ast
import sys
from pathlib import Path

DANGEROUS_IMPORTS = {
    "socket": "network",
    "requests": "network",
    "urllib.request": "network",
    "urllib3": "network",
    "httpx": "network",
    "aiohttp": "network",
    "websocket": "network",
    "subprocess": "process",
    "shutil": "filesystem",
    "pickle": "deserialize",
    "ctypes": "native",
}

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

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        findings.append(f"{py_file}: syntax error — {e}")
        continue

    for node in ast.walk(tree):
        # Check imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                base = alias.name.split(".")[0]
                if base in DANGEROUS_IMPORTS:
                    findings.append(
                        f"{py_file}: imports '{alias.name}' → "
                        f"needs '{DANGEROUS_IMPORTS[base]}' in MANIFEST.yaml"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                base = node.module.split(".")[0]
                if base in DANGEROUS_IMPORTS:
                    findings.append(
                        f"{py_file}: imports '{node.module}' → "
                        f"needs '{DANGEROUS_IMPORTS[base]}' in MANIFEST.yaml"
                    )

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

    # os.system check
    if "os.system" in source or "os.popen" in source:
        findings.append(f"{py_file}: uses os.system/os.popen — needs 'process' permission")

if findings:
    print(f"⚠️  {len(findings)} issue(s):")
    for f in findings:
        print(f"   {f}")
    sys.exit(1)

print(f"✅ Security scan passed ({count} file(s))")
