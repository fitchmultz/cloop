# Release Process

This document describes the standard release workflow for Cloop.

## 1) Stabilize main

- Ensure `main` is green locally.
- Run the full gate:

```bash
make ci
```

This includes formatting/lint/type/tests, metadata checks, and artifact validation (`twine check`).

## 2) Update release metadata

- Update `version` in `pyproject.toml`.
- Update `__version__` in `src/cloop/_version.py`.
- Add release notes to `CHANGELOG.md` under a new heading:

```markdown
## [X.Y.Z] - YYYY-MM-DD
```

- Keep `## [Unreleased]` at the top for upcoming work.
- Version bumps happen at release time; CI enforces that `pyproject.toml` version already has a changelog heading.

## 3) Commit and tag

```bash
git add -A
git commit -m "release: vX.Y.Z"
git tag -a vX.Y.Z -m "Release vX.Y.Z"
```

## 4) Push

```bash
git push origin main
git push origin vX.Y.Z
```

Pushing a tag matching `v*.*.*` triggers `.github/workflows/release.yml`.
That workflow runs `make ci` and publishes a GitHub Release with built `dist/*` artifacts attached.

## 5) Post-release checks

- Confirm the new tag and GitHub Release are visible.
- Verify release notes are generated and readable.
- Verify `uv run cloop --help` works on a clean checkout.
- Verify docs links and badges resolve from public pages.
