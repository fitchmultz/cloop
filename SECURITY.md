# Security Policy

## Scope and threat model

Cloop is designed as a **local-first** service.

- Run it on `localhost` or trusted private networks only.
- Do **not** expose this service directly to the public internet without adding your own authn/authz and perimeter controls.
- Treat all API keys and webhook secrets as sensitive credentials.

## Supported versions

Security fixes are applied to the latest version on `main`.

## Reporting a vulnerability

Please report vulnerabilities privately:

1. Prefer GitHub Security Advisories (private reporting) if enabled for this repository.
2. If private advisories are unavailable, contact the maintainer directly and avoid posting exploit details publicly.

Include:

- Affected version/commit
- Reproduction steps
- Expected vs. actual behavior
- Impact assessment

We will acknowledge reports quickly, triage severity, and provide remediation guidance.

## Secret handling

- Never commit `.env` or credential files.
- Use `.env.example` as the template and keep real secrets in local untracked `.env`.
- Rotate/revoke any credential immediately if it is ever committed, logged, or shared.
