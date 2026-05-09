# Security Policy

## Supported Versions

`openbourse` is in active early development. Security fixes are applied to
the `main` branch and the most recent tagged release.

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1   | :x:                |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Email `tamworks11@gmail.com` with:

- A description of the vulnerability and its impact.
- A minimal proof-of-concept (script, payload, or reproduction steps).
- The version / commit you tested against.

You should receive an acknowledgement within **72 hours**. If the report is
valid, we'll work with you on a coordinated disclosure timeline — typically
30–90 days depending on severity and whether a third-party dependency is
involved.

## Scope

In scope:

- Code shipped from this repository (`src/openbourse/`).
- The default provider configurations and their parsers (FMP, EDGAR,
  yfinance, Anthropic SDK use).
- The bundled Alembic migrations and database schema.

Out of scope:

- Vulnerabilities in upstream dependencies — please report those to their
  respective maintainers (we'll happily coordinate a release once they're
  patched).
- Issues that require an attacker to already have shell or filesystem
  access on the user's machine.
- Misconfiguration of `.env` files (e.g. committing secrets to a public
  fork). The `.gitignore` ships with `.env` blocked by default.

## Disclosure

Once a fix lands and a release is tagged, we'll publish:

1. A GitHub Security Advisory with a CVE if applicable.
2. A note in `CHANGELOG.md` under the affected version.
3. Credit to the reporter (with permission).
