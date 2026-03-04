# Release Process

This document describes the minimal release workflow for Cloop.

## 1) Prepare release branch

- Ensure `main` is green.
- Pull latest changes and create a release branch.

## 2) Update version + changelog

- Update `version` in `pyproject.toml`.
- Update `__version__` in `src/cloop/_version.py`.
- Add release notes to `CHANGELOG.md` under a new version heading.

## 3) Run full quality gate

```bash
make ci
```

This must pass before tagging.

## 4) Commit and tag

```bash
git add -A
git commit -m "release: vX.Y.Z"
git tag -a vX.Y.Z -m "Release vX.Y.Z"
```

## 5) Push and publish release notes

```bash
git push origin main
git push origin vX.Y.Z
```

Create a GitHub Release for the tag and paste the relevant changelog section.

## 6) Post-release checks

- Verify `uv run cloop --help` works on a clean checkout.
- Verify docs links, badges, and release notes are visible publicly.
