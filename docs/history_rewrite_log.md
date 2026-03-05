# History Rewrite Execution Log

Date: 2026-03-04

## Scope

- Removed `.env` from Git history using `git filter-repo`.
- Republished rewritten history to `origin/main` and `origin/ralph/RQ-0124`.
- Pruned local backup refs after backup verification.

## Commands executed

### 1) Preflight

```bash
git status --short --branch
git remote -v
make ci
```

### 2) Backup snapshot (before rewrite)

```bash
git branch backup/main-before-history-rewrite-20260304T174150
git tag backup-before-history-rewrite-20260304T174150
git bundle create ../cloop-history-backups/cloop-pre-rewrite-20260304T174150.bundle --all
git bundle verify ../cloop-history-backups/cloop-pre-rewrite-20260304T174150.bundle
```

### 3) History rewrite

```bash
git filter-repo --path .env --invert-paths --force
git remote add origin https://github.com/fitchmultz/cloop.git
git fetch origin --prune
```

### 4) Verification and publish

```bash
git log --all -- .env
uv run python scripts/check_secrets.py
make ci
git push --force-with-lease origin main
git push --force-with-lease origin ralph/RQ-0124
git fetch origin --prune
git log origin/main -- .env
git log origin/ralph/RQ-0124 -- .env
```

### 5) Post-rewrite local hygiene

```bash
git branch --list 'backup/*'
git tag --list 'backup*'
git branch -D backup/main-before-history-rewrite-20260304T174150
git tag -d backup-before-history-rewrite-20260304T174150   # no-op if already absent
git branch --list 'backup/*'
git tag --list 'backup*'
```

## Final state

- `origin/main` and `origin/ralph/RQ-0124` contain no `.env` history.
- `make ci` passes on rewritten history.
- Local backup refs were pruned.
- Out-of-band bundle backup is retained at `../cloop-history-backups/cloop-pre-rewrite-20260304T174150.bundle`.

## Restore instructions

### Restore into a separate clone from bundle (recommended)

```bash
git clone ../cloop-history-backups/cloop-pre-rewrite-20260304T174150.bundle cloop-pre-rewrite-restore
cd cloop-pre-rewrite-restore
git branch -a
```

### Recover pre-rewrite branch into current clone from bundle

```bash
git fetch ../cloop-history-backups/cloop-pre-rewrite-20260304T174150.bundle \
  refs/heads/backup/main-before-history-rewrite-20260304T174150:refs/heads/recovery/main-before-history-rewrite-20260304T174150
```

### Restore from backup refs in another local clone (if present)

```bash
git checkout backup/main-before-history-rewrite-20260304T174150
# optional
git checkout backup-before-history-rewrite-20260304T174150
```

## Related docs

- [History rewrite plan](history_rewrite_plan.md)
- [Public release checklist](public_release_checklist.md)
