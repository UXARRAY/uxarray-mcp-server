# Claude Code Instructions for uxarray-mcp-server

## Git commits

- Author: **Rajeev Jain** `rajeeja@gmail.com`
- Never add Claude as a co-author or mention AI generation in commit messages.
- Use `git commit --author="Rajeev Jain <rajeeja@gmail.com>"` for all commits.

## Before every push

Always run both of these and fix any failures before pushing or opening a PR:

```bash
uv run pre-commit run --all-files
uv run pytest tests/ --ignore=tests/test_remote_agent.py -v
```

Never push if pre-commit or tests are failing.

## Code style

Follow the conventions in AGENTS.md.
