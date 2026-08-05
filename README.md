# AuraOS Skill Store

The official skill marketplace for [AuraOS](https://github.com/FrontierX-AuraOS/aura-os).  
Browse, submit, and install skills that extend your Aura experience.

## For Users

Visit the **Skill Store** tab inside your Aura desktop app to browse and install skills with one click.

## For Developers

Want to publish a skill? Here's the flow:

1. **Fork** this repository
2. **Create** your skill folder under `skills/<skill-id>/`
3. **Write** the required files (see [SPEC.md](./SPEC.md))
4. **Submit** a Pull Request
5. After CI checks pass and a maintainer approves, your skill goes live 🚀

### Quick Start

```bash
# Copy the example skill as a template
cp -r example-skill skills/my-awesome-skill

# Edit the manifest and code
vim skills/my-awesome-skill/MANIFEST.yaml
vim skills/my-awesome-skill/main.py

# Validate locally
python3 scripts/validate-skill.py skills/my-awesome-skill

# Submit!
gh pr create --title "Add my-awesome-skill"
```

### Skill File Structure

```
skills/<skill-id>/
├── MANIFEST.yaml     # Required: metadata + permissions
├── skill.md          # Required: declarative skill definition (persona / actions)
├── main.py           # Optional: executable code (run by the daemon's subprocess runner)
├── icon.png          # Optional: 256×256 skill icon
└── README.md         # Optional: longer description for the store page
```

## Security

Every PR is scanned by CI for:
- Valid MANIFEST structure
- Declared permissions match actual code usage
- No unauthorized network calls, file access, or process spawning
- Sandbox execution test

See [SPEC.md](./SPEC.md) for the full permission model.
