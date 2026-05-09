# Development guide

This guide covers the day-to-day mechanics of working on `openbourse`.

## First-time setup

```bash
git clone https://github.com/OpenBourse/openbourse.git
cd openbourse
poetry install --extras dev
poetry run pre-commit install
cp .env.example .env
docker compose up -d postgres
poetry run bourse db migrate
poetry run bourse db seed
poetry run bourse run
```

If you skip the database steps the TUI still works — it falls back to the
bundled fixture in `src/openbourse/data/seed.json`.

## Running the test suite

```bash
poetry run pytest                         # unit tests only
poetry run pytest -m integration          # requires Postgres
poetry run pytest -m "not integration"    # explicit unit-only
poetry run pytest --cov-report=html       # HTML coverage report
```

Unit tests run against `sqlite+aiosqlite:///:memory:` so they're fast and
hermetic. Integration tests use the Postgres container declared in
`docker-compose.yml`.

## Live provider tests

Add `@pytest.mark.live` to any test that hits a real third-party API. The
default `pytest.ini_options` selectors do not run them; surface them
explicitly when you have keys configured:

```bash
OPENBOURSE_FMP_API_KEY=... OPENBOURSE_USE_STUBS=false poetry run pytest -m live
```

## Adding a new screen

1. Add an entry to `BUILTIN_SCREENS` in
   `src/openbourse/screening/criteria.py`.
2. Add fixtures to `tests/unit/test_criteria.py` covering pass/reject
   boundary cases.
3. Update `docs/architecture.md` if the new screen needs new criteria
   fields.

## Adding a new provider

1. Implement the appropriate Protocol in `providers/base.py`.
2. Place the real implementation in `providers/<name>.py`. Provide a
   matching `Stub<Name>Provider` returning fixture data.
3. Wire it into `providers/registry.py` so `build_providers` selects the
   right variant based on `Settings`.
4. Cover the parser logic with unit tests using static payloads (no live
   network).

## Generating a migration

```bash
poetry run alembic revision --autogenerate -m "describe change"
```

Always review the generated SQL by hand. `--autogenerate` doesn't catch
column type changes reliably and may miss server-default tweaks.

## Textual development tips

```bash
# Run the app with the debug overlay enabled.
poetry run textual run --dev openbourse.tui:BourseApp

# Open the live console in another terminal.
poetry run textual console
```

Reactive watchers are defined as `watch_<attr>(self, value)` methods on the
widget. CSS lives in `src/openbourse/tui/styles.tcss`.
