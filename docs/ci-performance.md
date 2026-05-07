# Local CI Performance Notes

Purpose: document the current local CI gate and the runtime choices that keep the gate fast
without reducing validation coverage.

## Canonical gate

`make ci` is the local release gate. It aliases `check-full`, which runs:

- Python lock validation
- pi bridge lock validation and Node bridge tests
- frontend contract generation, typecheck, build, and Vitest tests
- Ruff formatting and lint checks
- environment, header, secret, version, changelog, and public-surface checks
- focused backup safety tests
- non-performance Python tests
- source distribution and wheel build with `twine check`

## Runtime controls

- `check-fast` and `check-full` run independent validation branches with `make -j4`.
- Broad pytest targets use `pytest-xdist` with `PYTEST_WORKERS ?= auto`:
  - `test`
  - `test-fast`
  - `test-all`
  - `test-cov`
- Developers can override worker count without editing the Makefile, for example:

```bash
make test PYTEST_WORKERS=4
```

## Validation signal

- `test` excludes only tests marked `performance`.
- `test-fast` excludes tests marked `slow` or `performance`.
- `test-all` includes every pytest marker.
- `test-backup-safety` remains an explicit prerequisite of `test` and `test-fast` so destructive
  restore regressions cannot fall out of the main local gates.
- Frontend build and Vitest remain part of both `test` and `test-fast`.

## Measurement protocol

Use this command when comparing CI-loop changes:

```bash
/usr/bin/time -p make ci
```

Record only measurements from the same machine, with warm dependency/build caches, and with no
unrelated working-tree changes.
