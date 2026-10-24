## Description
Brief description of what this PR does.

## Type of Change
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Build/CI change
- [ ] Refactor (no functional changes)

## Testing
- [ ] Tests pass locally (`python tests/test_code.py && python tests/test_agent.py && python tests/test_confirm.py`)
- [ ] Manual test: installer builds (`build.ps1 -SkipTests`)
- [ ] Manual test: first-run setup works
- [ ] Manual test: HUD opens, voice works, model responds
- [ ] Manual test: uninstall cleans up shortcuts

## Checklist
- [ ] My code follows the style of the project
- [ ] I have updated documentation if needed (README, config.example.json, etc.)
- [ ] I have not committed personal data (`config.json`, `data/`, `auden.db`)
- [ ] New tools are added to `core/tools.py` with `@tool` decorator
- [ ] Config changes are backward compatible (deep-merge handles missing keys)

## Screenshots / Logs (if applicable)