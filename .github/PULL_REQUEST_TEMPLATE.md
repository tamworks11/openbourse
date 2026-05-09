<!-- Thanks for contributing! Please fill in the sections below. -->

## What this changes

<!-- A short summary. Linking the issue this fixes is gold: "Fixes #123". -->

## Why

<!-- The motivation. Sometimes the "what" is obvious but the "why" isn't. -->

## How to verify

<!-- Steps a reviewer can run locally to see the change in action. -->

```bash
# Example:
poetry run pytest -m "not integration"
poetry run bourse run
```

## Checklist

- [ ] Tests pass locally (`poetry run pytest -m "not integration"`)
- [ ] Lint + format clean (`poetry run ruff check . && poetry run ruff format --check .`)
- [ ] Type-check clean (`poetry run mypy src`)
- [ ] Docs updated if behaviour changed (README, docstrings, `docs/`)
- [ ] `CHANGELOG.md` updated under `[Unreleased]`
- [ ] If touching providers, both real and stub variants updated
- [ ] If adding a DB column, an Alembic migration accompanies it
