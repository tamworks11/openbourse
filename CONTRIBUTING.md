# Contributing to openbourse

Thanks for your interest in `openbourse`. This document covers the
practicalities of getting a change merged.

## Ground rules

- Be kind. Our [Code of Conduct](CODE_OF_CONDUCT.md) applies to every
  interaction in issues, pull requests, and discussions.
- All contributions are licensed under [Apache 2.0](LICENSE). By opening a
  pull request, you agree your contribution is offered under that license
  and that you have the right to make it.
- Keep changes focused. One concern per pull request makes review tractable.

## Local setup

```bash
git clone https://github.com/<your-fork>/openbourse.git
cd openbourse
poetry install --extras dev
poetry run pre-commit install
cp .env.example .env
docker compose up -d postgres
poetry run bourse db migrate
poetry run bourse db seed
```

## Workflow

1. Open or claim an issue describing the change. For larger features, please
   discuss the approach before writing code.
2. Create a topic branch: `git checkout -b feat/short-description`.
3. Make your change. Add or update tests.
4. Run the full check suite locally:

   ```bash
   poetry run ruff check .
   poetry run ruff format --check .
   poetry run mypy src
   poetry run pytest
   ```

5. Commit with a clear message. We use [Conventional Commits](https://www.conventionalcommits.org/)
   loosely — `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.
6. Open a pull request against `main`. Link the issue. Describe the change
   and how to verify it.

## Tests

- Unit tests live in `tests/unit/` and must run without a database.
- Integration tests live in `tests/integration/` and assume the bundled
  Postgres container is up. They are gated by the `integration` pytest
  marker so unit-only runs stay fast.
- Provider tests should default to the stubbed implementations. Real-API
  tests, when added, must be marked `@pytest.mark.live` and skipped unless
  the relevant API key is present in the environment.

## Adding a provider

Real provider implementations go in `src/openbourse/providers/`. Follow the
abstract base in `providers/base.py` and the existing stub modules as a
template. Wire selection through `config.use_stubs` so contributors without
API keys still get a working app.

## Database changes

Schema changes require an Alembic migration:

```bash
poetry run alembic revision --autogenerate -m "describe change"
poetry run alembic upgrade head
```

Review the generated SQL — autogenerate is a starting point, not a finish
line. Do not edit existing migrations once merged; add a new one.

## Releasing

Maintainers tag releases as `vX.Y.Z`. The CI workflow builds and publishes
artifacts. Update `CHANGELOG.md` in the same pull request that bumps the
version in `pyproject.toml`.
