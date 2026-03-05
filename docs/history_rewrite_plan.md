# Optional Commit History Rewrite Plan (Private Repo)

Use this only while the repository is still private and all collaborators are aligned.

## Goal

Produce a public-safe history by removing sensitive material and collapsing noisy commit chains.

## Safety rules

1. Freeze pushes temporarily.
2. Create a backup branch/tag before rewriting.
3. Coordinate with anyone who has cloned the repo.
4. Force-push only after local + CI verification.

## Secret scrubbing procedure (recommended before any squash/reword)

This removes tracked secret files/content from all commits.

```bash
# 1) Backup current state
git checkout main
git pull --ff-only origin main
git branch backup/main-before-public-rewrite
git tag backup-before-public-rewrite

# 2) Install filter tool (one-time)
# macOS: brew install git-filter-repo

# 3) Rewrite history to drop .env everywhere
git filter-repo --path .env --invert-paths --force

# 4) Optional: redact known literal secrets in all blobs
# Create .secrets-replacements.txt with lines like:
# old-secret-string==>REDACTED
# and then:
# git filter-repo --replace-text .secrets-replacements.txt --force

# 5) Verify history is clean
git log --all -- .env
uv run python scripts/check_secrets.py

# 6) Run full quality gate
make ci

# 7) Force-push rewritten refs
git push --force-with-lease --all origin
git push --force-with-lease --tags origin
```

## Optional readability pass (after secret scrub)

```bash
# Example: clean up recent commit narrative
git rebase -i --rebase-merges HEAD~80
make ci
git push --force-with-lease origin main
```

## If rewrite is not feasible

Prefer non-destructive cleanup:

- keep forward commits coherent and conventional (`feat:`, `fix:`, `docs:`, `chore:`)
- keep release/readiness docs current
- document rationale in `docs/release_readiness_report.md`
