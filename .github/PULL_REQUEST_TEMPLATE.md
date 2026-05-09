<!-- Thanks for contributing to openbourse! Please fill in the sections below. -->

## Summary

<!-- One paragraph: what this PR does and the user-visible result. -->

## Motivation

<!-- Why this matters. Link the issue this addresses if there is one. -->

Closes #

## Type of change

<!-- Check all that apply. -->

- [ ] Bug fix (non-breaking)
- [ ] New feature (non-breaking)
- [ ] Refactor / cleanup (no functional change)
- [ ] Documentation
- [ ] Performance
- [ ] Breaking change (CLI flag, TUI keybind, DB schema, public API)
- [ ] Other: <!-- describe -->

## What changed

<!-- Bulleted walkthrough so a reviewer can navigate the diff. Mention any
     non-obvious design choices or trade-offs you considered. -->

-

## How to verify

<!-- Concrete commands a reviewer can paste to see the change. Include any
     setup steps if the PR requires a fresh DB or specific .env values. -->

```bash
poetry run pytest -m "not integration"
poetry run bourse run
```

## Screenshots / recordings

<!-- For TUI or visual changes, regenerate screenshots and reference them:

       poetry run python scripts/take_screenshots.py

     Then drop the resulting SVGs into the description (drag-drop in GitHub).
     Before/after pairs are ideal for layout changes. -->

## Risks / things to watch

<!-- What could break? Are there edge cases you didn't cover? Performance
     concerns at high ticker counts? Breaking changes for existing users? -->

## Checklist

- [ ] Tests added or updated to cover the change
- [ ] `poetry run pytest -m "not integration"` passes locally
- [ ] `poetry run ruff check . && poetry run ruff format --check .` clean
- [ ] `poetry run mypy src` clean
- [ ] Docstrings added or updated for new public functions / classes
- [ ] `CHANGELOG.md` entry under `[Unreleased]`
- [ ] If a DB column or table changed: Alembic migration committed
- [ ] If a provider was added/changed: real **and** stub variants updated
- [ ] If TUI visuals changed: `docs/screenshots/*.svg` regenerated
- [ ] Backwards-compatible — or "Breaking change" checked above with a
      migration note in the PR description

## Notes for the reviewer

<!-- Anything else worth flagging: areas that need scrutiny, open questions,
     follow-up work that's intentionally out of scope. Optional. -->
